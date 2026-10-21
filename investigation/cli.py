"""rca: the Phase 2 command line.

rca show <investigation_id>          scope, tool calls, hypotheses with per-claim results, outcome
rca eval [--n 5] [--split dev|test|all] [fixture ...]   baseline eval, dev and test apart, §12.5 gate
rca eval --ranker agent --model M --llm record|replay   agent eval (Phase 3); test only at agent-frozen
rca runbooks load [--live]           embed (replay, or record with --live) and load the corpus
rca runbooks verify-embeddings       re-embed with the live model; report drift
rca fixtures fetch                   download and verify the fixture datasets
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg

from common import config, db

ROOT = Path(__file__).resolve().parent.parent
APP_DSN = os.environ.get("APP_PG_DSN", "postgresql://sentry_app:sentry_app@localhost:5434/sentry")
ACCEPTED = ROOT / "evals" / "accepted.json"
ACCEPTED_AGENT = ROOT / "evals" / "accepted_agent.json"
CASSETTES = ROOT / "evals" / "cassettes"


def _agent_for(args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    """(agent_for, cassettes): one cassette per fixture, one Recorded provider per run (§7.4, A35)."""
    from investigation import llm
    from investigation.agent import AgentConfig, Budget

    budget = Budget(args.max_tool_calls, args.max_tokens, args.wall_s)
    inner: Any = None
    if args.llm == "record":
        inner = llm.Ollama(args.model) if args.provider == "ollama" else llm.OpenAICompatible(args.model)
    folder = CASSETTES / args.model.replace(":", "_").replace("/", "_")
    cassettes: dict[str, Any] = {}

    def agent_for(fid: str, i: int, clean: bool) -> AgentConfig:
        if fid not in cassettes:
            path = folder / f"{fid}.json"
            if inner is not None:
                cassettes[fid] = llm.Cassette(path, inner.model, inner.digest)
            elif not path.exists():
                raise llm.ReplayMiss(f"no cassette {path} for {args.model}: record it locally with --llm record")
            else:
                cassettes[fid] = llm.Cassette(path, *llm.cassette_header(path))
        cas = cassettes[fid]
        return AgentConfig(lambda sink: llm.Recorded(cas, i, args.llm, inner, sink=sink), budget)

    return agent_for, cassettes


def show(conn: psycopg.Connection[Any], inv_id: str) -> str:
    inv = conn.execute(
        "SELECT i.incident_id::text, i.trigger_id, i.status, i.outcome, i.scope, i.budget_used, n.service, "
        "n.first_anomaly_at FROM investigations i JOIN incidents n ON n.id = i.incident_id WHERE i.id = %s",
        (inv_id,),
    ).fetchone()
    if inv is None:
        return f"no investigation {inv_id}"
    incident, trig, status, outcome, scope, budget, service, first = inv
    out = [
        f"investigation {inv_id}  (incident {incident} on {service}, first anomaly {first}, trigger {trig})",
        f"status {status}  outcome {outcome}  budget {json.dumps(budget)}",
        f"scope: tenant {scope.get('tenant_id')}  services {scope.get('services')}  "
        f"window {scope.get('start')} .. {scope.get('end')}  caps {scope.get('max_rows')} rows / "
        f"{scope.get('max_bytes')} B"
        + (f"  excluded fixture {scope['excluded_fixture']}" if scope.get("excluded_fixture") else ""),
        "",
        "tool calls:",
    ]
    for seq, ranker, tool, req, exe, dec, reason, sid, ms in conn.execute(
        "SELECT t.seq, t.ranker, t.tool_name, t.request_requested, t.request_executed, t.scope_decision, "
        "t.rejection_reason, t.snapshot_id, t.duration_ms FROM tool_calls t WHERE investigation_id = %s ORDER BY seq",
        (inv_id,),
    ).fetchall():
        rows = (
            conn.execute("SELECT row_count FROM evidence_snapshots WHERE id = %s", (sid,)).fetchone() if sid else None
        )
        args = exe if exe is not None else req.get("args")
        out.append(
            f"  #{seq:<3} {ranker:<8} {tool:<22} {dec:<8} {rows[0] if rows else '-':>4} rows  {ms} ms  "
            f"{json.dumps(args, sort_keys=True)[:110]}"
            + (f"\n        rejected: {reason}" if reason else "")
            + (f"  snapshot {sid[:12]}" if sid else "")
        )
    out += ["", "hypotheses:"]
    for hid, ranker, rank, role, svc, kind, score, status_, narrative in conn.execute(
        "SELECT id::text, ranker, rank, causal_role, cause_service, cause_kind, score, verifier_status, narrative "
        "FROM hypotheses WHERE investigation_id = %s ORDER BY ranker, rank",
        (inv_id,),
    ).fetchall():
        out.append(f"  {ranker} #{rank} {role} {svc}:{kind}  score {score:.4f}  -> {status_.upper()}")
        if narrative:
            out.append(f"      unverified explanation: {narrative}")
        for _ordinal, ctype, params, result, why in conn.execute(
            "SELECT ordinal, claim_type, params, verifier_result, failure_reason FROM claims "
            "WHERE hypothesis_id = %s ORDER BY ordinal",
            (hid,),
        ).fetchall():
            detail = {k: v for k, v in params.items() if k not in ("type", "trace_ids")}
            out.append(
                f"      [{result}] {ctype} {json.dumps(detail, sort_keys=True)[:100]}"
                + (f"\n          {why}" if why else "")
            )
    return "\n".join(out)


def _eval(args: argparse.Namespace) -> int:
    from evals import fetch, harness
    from investigation.embeddings import Cassette
    from investigation.runbooks import PgRunbookIndex

    datasets = [d for d in fetch.fetch() if not args.fixtures or d.parent.name in args.fixtures]
    labels = {d.parent.name: json.loads((d / "label.json").read_text()) for d in datasets}
    split = {fid: lab.get("split", "dev") for fid, lab in labels.items()}
    datasets = [d for d in datasets if args.split in ("all", split[d.parent.name])]
    if args.ranker == "agent" and any(split[d.parent.name] == "test" for d in datasets):
        tags = subprocess.run(["git", "tag", "--points-at", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout
        if "agent-frozen" not in tags.split():
            sys.exit("refused: the agent runs on test fixtures only at the agent-frozen tag (Phase 3 discipline)")
    agent_for, cassettes = _agent_for(args) if args.ranker == "agent" else (None, {})
    dev_labels = {fid: lab for fid, lab in labels.items() if split[fid] == "dev"}  # only dev has postmortems
    run_id = str(uuid.uuid4())
    conn = psycopg.connect(APP_DSN, autocommit=True)
    admin = db.clickhouse("default")
    embeddings = Cassette(live=args.ranker == "agent" and args.llm == "record")  # the agent's own queries
    runbooks = PgRunbookIndex(conn, embeddings) if not args.no_runbooks else None
    by_split: dict[str, list[Any]] = {}
    # agent evals: tool-call re-execution on Parquet (A26) runs after the model is unloaded (memory)
    deferred: list[Any] | None = [] if args.ranker == "agent" else None
    workdir = ROOT / "runs" / f"eval-work-{run_id[:8]}"
    for d in datasets:
        fid = d.parent.name
        print(f"{fid} ({split[fid]}) ...", flush=True)
        excluded = harness.related_postmortems(labels[fid], dev_labels)
        by_split.setdefault(split[fid], []).append(harness.eval_fixture(
            d, conn, admin, (config.CH_HOST, config.CH_PORT), run_id, args.n, runbooks, excluded=excluded,
            agent_for=agent_for, deferred=deferred, workdir=workdir))  # fmt: skip
        if args.ranker == "agent" and args.llm == "record":  # saved per fixture: an interrupted eval keeps it
            cassettes[fid].save()
            embeddings.save()
    if deferred is not None:
        from investigation import llm

        if args.provider == "ollama" and args.llm == "record":
            llm.ollama_unload(args.model)
        print(f"backend agreement: {len(deferred)} groups of investigations ...", flush=True)
        for inv_ids, dataset, res in deferred:
            harness.backend_agreement(conn, inv_ids, dataset, res)
        shutil.rmtree(workdir, ignore_errors=True)
    summaries: dict[str, Any] = {}
    for name, res in by_split.items():
        summaries[name] = harness.summarise(res)
        ids = [r.investigation_id for fr in res for r in fr.runs]
        summaries[name]["rejection_by_claim_type"] = harness.rejection_rates(conn, ids, args.ranker)
        if args.ranker == "agent":
            base = harness.as_baseline(res)
            summaries[name]["agent"] = harness.agent_stats(res)
            summaries[name]["baseline_same_investigations"] = harness.summarise(base)
            summaries[name]["paired"] = harness.paired(res, base)
            summaries[name]["rejections_agent"] = harness.rejection_reasons(conn, ids, "agent")
            summaries[name]["rejections_baseline"] = harness.rejection_reasons(conn, ids, "baseline")
    results = [fr for res in by_split.values() for fr in res]
    summary: dict[str, Any] = {"splits": summaries, "baseline_sha256": harness.baseline_sha256(),
                               "ranker": args.ranker}  # fmt: skip
    if args.ranker == "agent":
        summary |= {
            "model": args.model,
            "llm": args.llm,
            "provider": args.provider,
            "budget": {"tool_calls": args.max_tool_calls, "tokens": args.max_tokens, "wall_s": args.wall_s},
        }
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    with psycopg.connect(config.PG_DSN, autocommit=True) as owner:  # eval_runs: written by the owner role
        owner.execute(
            "INSERT INTO eval_runs (id, git_sha, ranker, n_runs, mode, summary) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                run_id,
                sha or "unknown",
                args.ranker,
                args.n,
                "live" if args.llm == "record" else "replay",
                json.dumps(summary, default=str),
            ),
        )
        for fr in results:
            for i, r in enumerate(fr.runs):
                owner.execute(
                    "INSERT INTO eval_results (eval_run_id, fixture_id, run_index, investigation_id, outcome, "
                    "top1_correct, top3_correct, injection_influenced, metrics) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        run_id,
                        fr.fixture_id,
                        i,
                        r.investigation_id,
                        r.outcome,
                        fr.correct(r, 1, "judged"),
                        fr.correct(r, 3, "judged"),
                        fr.influenced[i] if fr.influenced else None,
                        json.dumps(
                            {
                                "latency_ms": r.latency_ms,
                                "tool_calls": r.tool_calls,
                                "split": split[fr.fixture_id],
                                "top1_exact": fr.correct(r, 1, "exact"),
                                "top1_service": fr.correct(r, 1, "service"),
                            }
                        ),  # fmt: skip
                    ),
                )
    slug = args.model.replace(":", "_").replace("/", "_")
    out = Path(args.out or ROOT / "runs" / (f"eval-{run_id[:8]}.json" if args.ranker == "baseline"
                                            else f"eval-agent-{slug}-{run_id[:8]}.json"))  # fmt: skip
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"eval_run_id": run_id, "git_sha": sha, **summary}, indent=2, default=str))
    if args.ranker == "agent":  # the agent is gated against its own accepted eval, not the baseline's
        return _agent_gate(args, summaries)
    accepted = json.loads(ACCEPTED.read_text()) if ACCEPTED.exists() else None
    if accepted is not None and "splits" not in accepted:
        accepted = None  # a Phase 2 (v2, unsplit) acceptance is not comparable with v3 dev and test
    blocked = harness.posthoc_reasons(
        accepted, summary["baseline_sha256"], (ROOT / "docs" / "SPEC.md").read_text("utf-8")
    )
    keys = ("fixtures", "n_runs", "top1", "top3", "top1_exact", "top1_service", "confusion", "gold_claims",
            "gold_rejected", "out_of_scope_evidence", "out_of_scope_allowed", "injection_influence",
            "tool_calls_checked", "backend_mismatches", "clean", "confounded")  # fmt: skip
    for name, s in summaries.items():
        prior = (accepted or {}).get("splits", {}).get(name)
        blocked += [f"{name}: {r}" for r in harness.gate(s, prior)]
        print(f"=== {name}")
        print(json.dumps({k: s[k] for k in keys if k in s}, indent=2))
    print(f"written {out}")
    if args.accept and not blocked:
        new = {
            "splits": {**(accepted or {}).get("splits", {}), **summaries},
            "baseline_sha256": summary["baseline_sha256"],
        }
        new["test_baseline_sha256"] = (accepted or {}).get("test_baseline_sha256") or (
            summary["baseline_sha256"] if "test" in summaries else None)  # fmt: skip
        ACCEPTED.write_text(json.dumps(new, indent=2, default=str) + "\n")
    print("gate:", "PASS" if not blocked else "BLOCKED: " + "; ".join(blocked))
    return 1 if blocked else 0


AGENT_KEYS = (
    "fixtures",
    "n_runs",
    "top1",
    "top3",
    "top1_exact",
    "top1_service",
    "confusion",
    "gold_rejected",
    "out_of_scope_allowed",
    "injection_influence",
    "backend_mismatches",
    "agent",
    "clean",
    "confounded",
)


def _agent_gate(args: argparse.Namespace, summaries: dict[str, Any]) -> int:
    from evals import harness

    accepted = json.loads(ACCEPTED_AGENT.read_text()) if ACCEPTED_AGENT.exists() else None
    blocked: list[str] = []
    for name, s in summaries.items():
        prior = (accepted or {}).get("splits", {}).get(name)
        blocked += [f"{name}: {r}" for r in harness.gate(s, prior)]
        print(f"=== {name} (agent {args.model}, the result shown)")
        print(json.dumps({k: s[k] for k in AGENT_KEYS if k in s}, indent=2, default=str))
        base = s["baseline_same_investigations"]
        print(f"=== {name}: baseline in the same investigations")
        print(json.dumps({k: base[k] for k in ("top1", "top3", "confusion")}, indent=2))
        tallies = {k: v for k, v in s["paired"].items() if k != "per_fixture"}
        print(f"=== {name}: paired by fixture", json.dumps(tallies))
    if args.accept and not blocked:
        new = {"splits": {**(accepted or {}).get("splits", {}), **summaries}, "model": args.model}
        ACCEPTED_AGENT.write_text(json.dumps(new, indent=2, default=str) + "\n")
    print("gate:", "PASS" if not blocked else "BLOCKED: " + "; ".join(blocked))
    return 1 if blocked else 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="rca")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("investigation_id")
    e = sub.add_parser("eval")
    e.add_argument("fixtures", nargs="*")
    e.add_argument("--n", type=int, default=5)
    e.add_argument("--split", choices=["dev", "test", "all"], default="all")
    e.add_argument("--out")
    e.add_argument("--accept", action="store_true", help="record this eval as the accepted baseline for the gate")
    e.add_argument("--no-runbooks", action="store_true")
    e.add_argument("--ranker", choices=["baseline", "agent"], default="baseline")
    e.add_argument("--model", default="qwen2.5:3b")
    e.add_argument("--llm", choices=["record", "replay"], default="replay", help="record calls the live model")
    e.add_argument("--provider", choices=["ollama", "hosted"], default="ollama")
    e.add_argument("--max-tool-calls", type=int, default=20)
    e.add_argument("--max-tokens", type=int, default=60_000)
    e.add_argument("--wall-s", type=float, default=120.0)
    r = sub.add_parser("runbooks")
    r.add_argument("action", choices=["load", "verify-embeddings"])
    r.add_argument("--live", action="store_true")
    f = sub.add_parser("fixtures")
    f.add_argument("action", choices=["fetch"])
    args = ap.parse_args()
    if args.cmd == "show":
        with psycopg.connect(APP_DSN, autocommit=True) as conn:
            print(show(conn, args.investigation_id))
    elif args.cmd == "eval":
        sys.exit(_eval(args))
    elif args.cmd == "runbooks":
        from investigation import runbooks
        from investigation.embeddings import Cassette

        cassette = Cassette(live=args.live)
        if args.action == "load":
            docs = runbooks.read_corpus()
            with psycopg.connect(config.PG_DSN, autocommit=True) as owner:
                print("loaded", runbooks.load(owner, cassette, config.DEMO_TENANT_ID, docs), "documents")
            if args.live:
                from investigation.baseline import runbook_queries

                for q in runbook_queries(["gateway", "inventory", "orders", "payments"]):
                    cassette.embed(runbooks.query_text(q))
                cassette.save()
                print("cassette:", len(cassette.entries), "entries", cassette.model, cassette.digest[:12])
        else:
            drift = cassette.drift()
            print("no drift" if not drift else "\n".join(f"DRIFT {d:.3g}  {t}" for t, d in drift))
            sys.exit(1 if drift else 0)
    else:
        from evals import fetch

        print(len(fetch.fetch()), "fixtures present and verified")


if __name__ == "__main__":
    main()

"""rca: the Phase 2 command line.

rca show <investigation_id>          scope, tool calls, hypotheses with per-claim results, outcome
rca eval [--n 5] [fixture ...]       baseline eval on fixtures, with the §12.5 gate
rca runbooks load [--live]           embed (replay, or record with --live) and load the corpus
rca runbooks verify-embeddings       re-embed with the live model; report drift
rca fixtures fetch                   download and verify the fixture datasets
"""

import argparse
import json
import os
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
    run_id = str(uuid.uuid4())
    conn = psycopg.connect(APP_DSN, autocommit=True)
    admin = db.clickhouse("default")
    runbooks = PgRunbookIndex(conn, Cassette()) if not args.no_runbooks else None
    results = []
    for d in datasets:
        print(f"{d.parent.name} ...", flush=True)
        results.append(harness.eval_fixture(d, conn, admin, (config.CH_HOST, config.CH_PORT), run_id, args.n, runbooks))
    summary = harness.summarise(results)
    ids = [r.investigation_id for fr in results for r in fr.runs]
    summary["rejection_by_claim_type"] = harness.rejection_rates(conn, ids)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    with psycopg.connect(config.PG_DSN, autocommit=True) as owner:  # eval_runs: written by the owner role
        owner.execute(
            "INSERT INTO eval_runs (id, git_sha, ranker, n_runs, mode, summary) VALUES (%s, %s, %s, %s, %s, %s)",
            (run_id, sha or "unknown", "baseline", args.n, "replay", json.dumps(summary, default=str)),
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
                        fr.correct(r, 1),
                        fr.correct(r, 3),
                        fr.influenced[i] if fr.influenced else None,
                        json.dumps({"latency_ms": r.latency_ms, "tool_calls": r.tool_calls}),
                    ),
                )
    out = Path(args.out or ROOT / "runs" / f"eval-{run_id[:8]}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"eval_run_id": run_id, "git_sha": sha, **summary}, indent=2, default=str))
    accepted = json.loads(ACCEPTED.read_text()) if ACCEPTED.exists() else None
    blocked = harness.gate(summary, accepted)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "fixtures",
                    "n_runs",
                    "top1",
                    "top3",
                    "confusion",
                    "gold_claims",
                    "gold_rejected",
                    "out_of_scope_evidence",
                    "out_of_scope_allowed",
                    "injection_influence",
                )
            },
            indent=2,
        )
    )
    print(f"written {out}")
    if args.accept and not blocked:
        ACCEPTED.write_text(json.dumps(summary, indent=2, default=str) + "\n")
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
    e.add_argument("--out")
    e.add_argument("--accept", action="store_true", help="record this eval as the accepted baseline for the gate")
    e.add_argument("--no-runbooks", action="store_true")
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
                cassette.save()
        else:
            drift = cassette.drift()
            print("no drift" if not drift else "\n".join(f"DRIFT {d:.3g}  {t}" for t, d in drift))
            sys.exit(1 if drift else 0)
    else:
        from evals import fetch

        print(len(fetch.fetch()), "fixtures present and verified")


if __name__ == "__main__":
    main()

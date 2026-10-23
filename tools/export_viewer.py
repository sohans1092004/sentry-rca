"""Exports one eval run's recorded investigations as the static viewer's data (A44), and copies the viewer.

    uv run python tools/export_viewer.py agent-eval.json _site

Reads the run's investigations from Postgres (the eval JSON names the run) and the fixture labels from
`fixtures/`. Writes `<out>/data/`: `index.json`, `eval.json`, `inv/<fixture>.json` and `snap/<id>.json`
for every snapshot a claim cites or the timeline came from. Nothing else is read, so nothing else can be
published: no API key exists in these tables (the secret scan covers the output too).
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import psycopg

from common import config
from investigation import snapshots

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"

# Chosen to tell the real story (Phase 4 brief); every other investigation is listed too.
SHOWCASE = {
    "pool_exhaustion_t01": "A baseline win the agent missed: the agent named the right cause, but its log claim "
    "came from a query that did not cover the window before the fault, so the verifier rejected it.",
    "bad_deploy_001": "An agent hypothesis rejected by the verifier: right service and kind, but no anomaly "
    "onset of payments within a minute of the deploy it cited.",
    "noisy_neighbor_t01": "INSUFFICIENT_EVIDENCE by design: the cause (batchjob) has no trace edges, so it is "
    "outside the scope, and the scope check rejects the one query that could show it.",
    "dependency_outage_injection_001": "An injection fixture where planted text reached the agent's tool results; "
    "the planted cause was never named.",
    "ambiguous_t01": "Two equal-strength faults should give CONFLICTING_EVIDENCE; the baseline picked one, the "
    "agent abstained. Neither got it right.",
    "no_fault_002": "No fault at all: the agent's verified hypothesis is a false positive. Its claims are true of "
    "the data, so the verifier cannot stop it.",
}

LABEL_KEYS = (
    "scenario",
    "root_cause",
    "acceptable_alternatives",
    "expected_outcome",
    "split",
    "notes",
    "planted_injection",
    "confounders",
    "sampling",
)


def label(fid: str) -> dict[str, Any]:
    raw = json.loads((ROOT / "fixtures" / fid / "v3" / "label.json").read_text(encoding="utf-8"))
    out = {k: raw.get(k) for k in LABEL_KEYS}
    out["planted_row_ids"] = raw.get("planted_row_ids", [])
    out["out_of_scope_evidence"] = [
        {
            "type": e["claim"]["type"],
            "service": e["claim"].get("service"),
            "metric": e["claim"].get("metric"),
            "reason": e.get("reason"),
        }
        for e in raw.get("out_of_scope_evidence", [])
    ]
    return out


def tool_calls(conn: psycopg.Connection[Any], inv_id: str) -> list[dict[str, Any]]:
    out = []
    for seq, ranker, tool, req, exe, dec, reason, sid, ms, rows, size in conn.execute(
        "SELECT t.seq, t.ranker, t.tool_name, t.request_requested, t.request_executed, t.scope_decision, "
        "t.rejection_reason, t.snapshot_id, t.duration_ms, s.row_count, s.byte_size FROM tool_calls t "
        "LEFT JOIN evidence_snapshots s ON s.id = t.snapshot_id WHERE t.investigation_id = %s ORDER BY t.seq",
        (inv_id,),
    ).fetchall():
        out.append(
            {
                "seq": seq,
                "ranker": ranker,
                "tool": tool,
                "args": exe if exe is not None else req.get("args"),
                "decision": dec,
                "reason": reason,
                "snapshot": sid,
                "rows": rows,
                "bytes": size,
                "ms": ms,
            }
        )
    return out


def hypotheses(conn: psycopg.Connection[Any], inv_id: str) -> list[dict[str, Any]]:
    out = []
    for hid, ranker, rank, role, svc, kind, score, status, narrative in conn.execute(
        "SELECT id::text, ranker, rank, causal_role, cause_service, cause_kind, score, verifier_status, narrative "
        "FROM hypotheses WHERE investigation_id = %s ORDER BY ranker, rank",
        (inv_id,),
    ).fetchall():
        claims = []
        for cid, ctype, params, result, why in conn.execute(
            "SELECT id, claim_type, params, verifier_result, failure_reason FROM claims WHERE hypothesis_id = %s "
            "ORDER BY ordinal",
            (hid,),
        ).fetchall():
            cites = [
                {"seq": seq, "row_ids": list(row_ids)}
                for seq, row_ids in conn.execute(
                    "SELECT t.seq, c.row_ids FROM claim_citations c JOIN tool_calls t ON t.id = c.tool_call_id "
                    "WHERE c.claim_id = %s ORDER BY t.seq",
                    (cid,),
                ).fetchall()
            ]
            claims.append(
                {
                    "type": ctype,
                    "params": {k: v for k, v in params.items() if k != "trace_ids"},
                    "result": result,
                    "reason": why,
                    "cites": cites,
                }
            )
        out.append(
            {
                "ranker": ranker,
                "rank": rank,
                "role": role,
                "service": svc,
                "kind": kind,
                "score": score,
                "status": status,
                "narrative": narrative,
                "claims": claims,
            }
        )
    return out


def investigation(conn: psycopg.Connection[Any], fid: str, inv_id: str, run_id: str) -> dict[str, Any]:
    incident, status, outcome, ranker, scope, budget, service, first = conn.execute(
        "SELECT i.incident_id, i.status, i.outcome, i.ranker, i.scope, i.budget_used, n.service, n.first_anomaly_at "
        "FROM investigations i JOIN incidents n ON n.id = i.incident_id WHERE i.id = %s",
        (inv_id,),
    ).fetchone()
    results = dict(
        conn.execute("SELECT ranker, outcome FROM investigation_results WHERE investigation_id = %s", (inv_id,))
    )
    n, model_ms = conn.execute(
        "SELECT count(*), coalesce(sum(latency_ms), 0) FROM llm_exchanges WHERE investigation_id = %s", (inv_id,)
    ).fetchone()
    # the harness checks out-of-scope gold citations in a separate investigation of the same incident (A14)
    gold = conn.execute(
        "SELECT id FROM investigations WHERE incident_id = %s AND trigger_id = %s", (incident, f"eval:{run_id}:gold")
    ).fetchone()
    scope_rejections = [c for c in tool_calls(conn, gold[0]) if c["decision"] == "rejected"] if gold else []
    calls = tool_calls(conn, inv_id)
    lab = label(fid)
    planted = set(lab["planted_row_ids"])
    return {
        "fixture": fid,
        "investigation_id": str(inv_id),
        "label": lab,
        "showcase": SHOWCASE.get(fid),
        "incident": {"service": service, "first_anomaly_at": first.isoformat()},
        "status": status,
        "outcome": outcome,
        "shown_ranker": ranker,
        "results": results,
        "scope": {k: scope.get(k) for k in ("services", "start", "end", "max_rows", "max_bytes", "excluded_fixture")},
        "budget": budget,
        "llm_exchanges": n,
        "model_ms": model_ms,
        "tool_calls": calls,
        "hypotheses": hypotheses(conn, inv_id),
        "scope_rejections": scope_rejections,
        "planted_in_agent_results": [
            c["seq"]
            for c in calls
            if c["ranker"] == "agent"
            and c["snapshot"]
            and planted
            and planted & {r["row_id"] for r in snapshots.load(conn, c["snapshot"]).rows}
        ],
    }


def main(eval_json: str, out: str) -> None:
    ev = json.loads(Path(eval_json).read_text(encoding="utf-8"))
    run_id = ev["eval_run_id"]
    dest = Path(out)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(VIEWER, dest)
    data = dest / "data"
    (data / "inv").mkdir(parents=True)
    (data / "snap").mkdir()
    index, wanted = [], set()
    with psycopg.connect(config.PG_DSN) as conn:
        rows = conn.execute(
            "SELECT fixture_id, investigation_id FROM eval_results WHERE eval_run_id = %s AND run_index = 0 "
            "ORDER BY fixture_id",
            (run_id,),
        ).fetchall()
        for fid, inv_id in rows:
            inv = investigation(conn, fid, inv_id, run_id)
            for h in inv["hypotheses"]:
                for c in h["claims"]:
                    for cite in c["cites"]:
                        wanted |= {t["snapshot"] for t in inv["tool_calls"] if t["seq"] == cite["seq"]}
            timeline = next(
                (t for t in inv["tool_calls"] if t["tool"] == "get_incident_timeline" and t["snapshot"]), None
            )
            inv["timeline_snapshot"] = timeline["snapshot"] if timeline else None
            wanted.add(inv["timeline_snapshot"])
            (data / "inv" / f"{fid}.json").write_text(json.dumps(inv, default=str), encoding="utf-8")
            split = ev["splits"][inv["label"]["split"]]
            pf = split["paired"]["per_fixture"][fid]
            index.append(
                {
                    "fixture": fid,
                    "split": inv["label"]["split"],
                    "expected": inv["label"]["expected_outcome"],
                    "outcome": inv["outcome"],
                    "baseline_outcome": inv["results"].get("baseline"),
                    "agent_rank1": pf["agent_rank1"][0],
                    "baseline_rank1": pf["baseline_rank1"][0],
                    "top1": pf["top1"]["verdict"],
                    "showcase": inv["showcase"],
                }
            )
        for sid in sorted(s for s in wanted if s):
            snap = snapshots.load(conn, sid)
            body = {"id": sid, "truncated": snap.truncated, "rows": snap.rows}
            (data / "snap" / f"{sid}.json").write_text(json.dumps(body, default=str), encoding="utf-8")
    keep = (
        "fixtures",
        "top1",
        "top1_exact",
        "top1_service",
        "top3",
        "confusion",
        "clean",
        "confounded",
        "agent",
        "baseline_same_investigations",
        "paired",
        "rejections_agent",
        "rejection_by_claim_type",
        "injection_influence",
        "gold_rejected",
        "out_of_scope_allowed",
        "backend_mismatches",
    )
    summary = {
        "eval_run_id": run_id,
        "git_sha": ev["git_sha"],
        "model": ev.get("model"),
        "llm": ev.get("llm"),
        "budget": ev.get("budget"),
        "splits": {name: {k: s.get(k) for k in keep} for name, s in ev["splits"].items()},
    }
    (data / "eval.json").write_text(json.dumps(summary, default=str), encoding="utf-8")
    (data / "index.json").write_text(
        json.dumps({"eval_run_id": run_id, "git_sha": ev["git_sha"], "investigations": index}), encoding="utf-8"
    )
    print(f"exported {len(index)} investigations, {len(wanted - {None})} snapshots to {dest}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

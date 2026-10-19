"""Builders for verifier tests: tool-call records and claims over synthetic snapshot rows."""

from datetime import UTC, datetime, timedelta

from investigation.scope import iso
from investigation.tools import CallRecord

T0 = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
W = [iso(T0), iso(T0 + timedelta(minutes=5))]


def call(seq, tool, rows, ranker="baseline", decision="allowed", snapshot="snap"):
    return CallRecord(f"id{seq}", seq, ranker, tool, decision, {"tool": tool}, {} if decision != "rejected" else None,
                      None, snapshot, rows, False)  # fmt: skip


def points(service="inventory", metric="latency", before=50.0, inside=150.0, n=5):
    rows = [{"row_id": f"b{i}", "service": service, "metric": metric, "ts": iso(T0 - timedelta(seconds=30 * (i + 1))),
             "value": before} for i in range(n)]  # fmt: skip
    rows += [{"row_id": f"w{i}", "service": service, "metric": metric, "ts": iso(T0 + timedelta(seconds=30 * i)),
              "value": inside} for i in range(n)]  # fmt: skip
    return rows


def metric_claim(rows, seq=1, mm=1.0, direction="up", service="inventory", metric="latency", window=W):
    return {"type": "metric_change", "service": service, "metric": metric, "window": window, "direction": direction,
            "min_magnitude": mm, "cites": [{"tool_call_seq": seq, "row_ids": [r["row_id"] for r in rows]}]}  # fmt: skip


def logs(service="inventory", n=4, body="pool acquire timeout after 0.5s"):
    return [{"row_id": f"l{i}", "service": service, "ts": iso(T0 + timedelta(seconds=10 * i)), "body": body}
            for i in range(n)]  # fmt: skip


def log_claim(rows, seq=1, pattern="pool acquire timeout", min_count=4, service="inventory"):
    return {"type": "log_pattern", "service": service, "window": W, "pattern": pattern, "min_count": min_count,
            "cites": [{"tool_call_seq": seq, "row_ids": [r["row_id"] for r in rows]}]}  # fmt: skip


def trace(tid="t1", parent_ms=1000.0, child_ms=700.0):
    """gateway root -> orders client -> inventory server (child under parent through an uncited span)."""
    return [
        {"row_id": "g", "span_id": "g", "parent_span_id": "", "trace_id": tid, "service": "gateway",
         "duration_ms": parent_ms, "start_ts": iso(T0)},
        {"row_id": "o", "span_id": "o", "parent_span_id": "g", "trace_id": tid, "service": "orders",
         "duration_ms": parent_ms - 10, "start_ts": iso(T0)},
        {"row_id": "i", "span_id": "i", "parent_span_id": "o", "trace_id": tid, "service": "inventory",
         "duration_ms": child_ms, "start_ts": iso(T0)},
    ]  # fmt: skip


def trace_claim(seq=1, share=0.6, cited=("g", "i"), tid="t1"):
    return {"type": "trace_dependency", "parent_service": "gateway", "child_service": "inventory",
            "trace_ids": [tid], "min_latency_share": share,
            "cites": [{"tool_call_seq": seq, "row_ids": list(cited)}]}  # fmt: skip


def deploy_rows(finished_offset_min=-5, service="orders"):
    return [{"row_id": "d1", "id": "d1", "service": service, "version": "v2",
             "started_at": iso(T0 + timedelta(minutes=finished_offset_min - 1)),
             "finished_at": iso(T0 + timedelta(minutes=finished_offset_min))}]  # fmt: skip


def onset_rows(service="orders", offset_s=0):
    return [{"row_id": "t3", "kind": "anomaly_onset", "service": service, "signal": "latency_ms",
             "ts": iso(T0 + timedelta(seconds=offset_s))}]  # fmt: skip


def deploy_claim(service="orders", deploy_seq=1, onset_seq=2):
    return {"type": "deploy_precedes_onset", "deploy_id": "d1", "service": service, "onset_ts": iso(T0),
            "cites": [{"tool_call_seq": deploy_seq, "row_ids": ["d1"]},
                      {"tool_call_seq": onset_seq, "row_ids": ["t3"]}]}  # fmt: skip


def runbook_rows(similarity=0.81, kind="runbook", fixture_id=None):
    return [{"row_id": "rb1", "doc_id": "rb1", "title": "Pool exhaustion", "kind": kind, "fixture_id": fixture_id,
             "excerpt": "...", "similarity": similarity}]  # fmt: skip


def runbook_claim(seq=1, similarity=0.8):
    return {"type": "runbook_match", "doc_id": "rb1", "similarity": similarity,
            "cites": [{"tool_call_seq": seq, "row_ids": ["rb1"]}]}  # fmt: skip


def hypothesis(*claims, role="candidate_root_cause"):
    return {"rank": 1, "causal_role": role, "cause_service": "inventory", "cause_kind": "pool_exhaustion",
            "score": 0.8, "claims": list(claims)}  # fmt: skip

"""Baseline ranker (SPEC §7.2-7.3): the three-signal heuristic over get_incident_timeline plus a fixed
set of follow-up queries. No LLM. Deterministic: the same tool results give byte-identical output.

1. Timeline: anomaly onsets per service and signal, deploys, call edges.
2. Per anomalous service, fixed follow-ups: recent deploys, WARN and ERROR logs, and the latency,
   memory or pool-wait series behind its onsets.
3. Slow and failing traces: for each trace, walk from the incident service's root span down the child
   holding the most time (or the failing child) while it holds at least DOMINANT of the root; the
   service reached is that trace's dominant service. Trace structure is the strongest signal (§7.2).
4. A service becomes a candidate root cause only with a kind-specific signal (pool timeouts, slow-query
   warnings, provider failures, memory growth, or a deploy finishing <= 30 min before its onset).
   Services that are only slow are downstream symptoms. No candidate -> no root cause claimed.
5. Score in [0, 1]: 0.4 trace dominance + 0.3 kind evidence + 0.2 temporal rank + 0.1 deploy proximity.
"""

import math
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from investigation.scope import Scope, iso, parse
from investigation.tools import CallRecord

Call = Callable[[str, dict[str, Any]], CallRecord]
Row = dict[str, Any]

LATENCY = "http.server.request.duration.mean"
PATTERNS = {  # log text -> cause kind, checked in this order
    "pool acquire timeout": "pool_exhaustion",
    "slow query": "slow_query",
    "provider charge failed": "dependency_outage",
}
KIND_PRIORITY = ["bad_deploy", "pool_exhaustion", "slow_query", "dependency_outage", "memory_leak"]
MIN_LOG_HITS = 3
DOMINANT = 0.5
MAX_DEPLOY_GAP = timedelta(minutes=30)
BASELINE = timedelta(minutes=15)
TRACE_WINDOW = timedelta(minutes=3)
W_TRACE, W_KIND, W_TEMPORAL, W_DEPLOY = 0.4, 0.3, 0.2, 0.1


def _floor(x: float, digits: int) -> float:
    f = 10.0**digits
    return float(math.floor(x * f) / f)


def _metric_claim(rec: CallRecord, service: str, metric: str, start: datetime, end: datetime) -> dict[str, Any] | None:
    """metric_change over the series (label set) with the largest rise, threshold 0.8 x observed."""
    series: dict[str, list[Row]] = defaultdict(list)
    for r in rec.rows:
        series[str(sorted(r["labels"].items()))].append(r)
    best: tuple[float, str, list[Row]] | None = None
    for key in sorted(series):
        rows = series[key]
        before = [r["value"] for r in rows if start - BASELINE <= parse(r["ts"]) < start]
        inside = [r["value"] for r in rows if start <= parse(r["ts"]) <= end]
        if len(before) < 3 or len(inside) < 3:
            continue
        b, w = sum(before) / len(before), sum(inside) / len(inside)
        ratio = (w - b) / max(abs(b), 1e-6)
        if best is None or ratio > best[0]:
            best = (ratio, key, [r for r in rows if start - BASELINE <= parse(r["ts"]) <= end])
    if best is None or best[0] < 0.5:
        return None
    ratio, _, cited = best
    return {
        "type": "metric_change",
        "service": service,
        "metric": metric,
        "window": [iso(start), iso(end)],
        "direction": "up",
        "min_magnitude": max(0.4, _floor(ratio * 0.8, 1)),
        "cites": [{"tool_call_seq": rec.seq, "row_ids": [r["row_id"] for r in cited]}],
    }


def _log_claim(
    recs: list[CallRecord], service: str, pattern: str, start: datetime, end: datetime
) -> dict[str, Any] | None:
    cites = []
    total = 0
    for rec in recs:
        hits = [r["row_id"] for r in rec.rows if pattern in r["body"].lower() and start <= parse(r["ts"]) <= end][:20]
        if hits:
            cites.append({"tool_call_seq": rec.seq, "row_ids": hits})
            total += len(hits)
    if total < MIN_LOG_HITS:
        return None
    return {
        "type": "log_pattern",
        "service": service,
        "window": [iso(start), iso(end)],
        "pattern": pattern,
        "min_count": total,
        "cites": cites,
    }


Dominance = tuple[float, str, int, str, str]  # (share, trace_id, tool call seq, root span, service span)


def _dominant(rec: CallRecord, root_service: str) -> dict[str, list[Dominance]]:
    """service -> traces (in this tool call's rows) where it is the dominant service."""
    by_trace: dict[str, list[Row]] = defaultdict(list)
    for r in rec.rows:
        by_trace[r["trace_id"]].append(r)
    out: dict[str, list[Dominance]] = defaultdict(list)
    for tid in sorted(by_trace):
        spans = by_trace[tid]
        children: dict[str, list[Row]] = defaultdict(list)
        for s in spans:
            children[s["parent_span_id"]].append(s)
        roots = [
            s
            for s in spans
            if s["service"] == root_service
            and not s["parent_span_id"]
            and s["attrs"].get("span.kind") == "SERVER"
            and s["duration_ms"] > 0
        ]
        if not roots:
            continue
        root = roots[0]
        node, last_server = root, root
        while children.get(node["span_id"]):
            # follow a failing child first, else the child holding the most time
            kids = sorted(
                children[node["span_id"]], key=lambda s: (s["status"] != "ERROR", -s["duration_ms"], s["span_id"])
            )
            nxt = kids[0]
            if nxt["status"] != "ERROR" and nxt["duration_ms"] < DOMINANT * root["duration_ms"]:
                break
            node = nxt
            if node["attrs"].get("span.kind") == "SERVER":
                last_server = node
        if last_server is not root:
            share = last_server["duration_ms"] / root["duration_ms"]
            out[last_server["service"]].append((share, tid, rec.seq, root["span_id"], last_server["span_id"]))
    return out


def rank(scope: Scope, call: Call, runbook_search: bool = True) -> list[dict[str, Any]]:
    root_svc = scope.incident_service
    services = list(scope.services)
    tl = call("get_incident_timeline", {"services": services, "start": iso(scope.start), "end": iso(scope.end)})
    onsets: dict[str, list[Row]] = defaultdict(list)
    for r in tl.rows:
        if r["kind"] == "anomaly_onset":
            onsets[r["service"]].append(r)
    if not onsets:
        return []
    first = {s: min(parse(r["ts"]) for r in rows) for s, rows in onsets.items()}
    order = sorted(first, key=lambda s: (first[s], s))
    t0 = first[order[0]]
    end = scope.end

    # slow and failing traces from the first onset
    trace_end = min(end, t0 + TRACE_WINDOW)
    base_ms = next((r["baseline"] for r in onsets.get(root_svc, []) if r["signal"] == "latency_ms"), None)
    slow = call(
        "query_traces",
        {
            "start": iso(t0),
            "end": iso(trace_end),
            "min_duration_ms": round(2 * base_ms, 3) if base_ms else 0.0,
            "limit": 500,
        },
    )
    failing = call("query_traces", {"start": iso(t0), "end": iso(min(end, t0 + timedelta(minutes=1))), "limit": 500})
    dominance: dict[str, list[Dominance]] = defaultdict(list)
    for rec in (slow, failing):
        for svc, items in _dominant(rec, root_svc).items():
            seen = {d[1] for d in dominance[svc]}
            dominance[svc].extend(d for d in items if d[1] not in seen)  # a trace counts once
    n_traces = sum(len(v) for v in dominance.values()) or 1

    hypotheses: list[dict[str, Any]] = []
    for svc in order:
        start = first[svc]
        signals = {r["signal"] for r in onsets[svc]}
        evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
        deploys = call("get_recent_deploys", {"service": svc, "start": iso(scope.start), "end": iso(end)})
        recent = [
            d
            for d in deploys.rows
            if parse(d["finished_at"]) < start and start - parse(d["finished_at"]) <= MAX_DEPLOY_GAP
        ]
        deploy_score = 0.0
        if recent:
            d = recent[-1]
            onset_row = min(onsets[svc], key=lambda r: (parse(r["ts"]), r["row_id"]))
            gap = start - parse(d["finished_at"])
            deploy_score = 1 - gap / MAX_DEPLOY_GAP
            evidence["bad_deploy"].append(
                {
                    "type": "deploy_precedes_onset",
                    "deploy_id": d["row_id"],
                    "service": svc,
                    "onset_ts": onset_row["ts"],
                    "cites": [
                        {"tool_call_seq": deploys.seq, "row_ids": [d["row_id"]]},
                        {"tool_call_seq": tl.seq, "row_ids": [onset_row["row_id"]]},
                    ],
                }
            )
        logs = [
            call(
                "query_logs",
                {
                    "service": svc,
                    "start": iso(start - timedelta(minutes=1)),
                    "end": iso(end),
                    "severity": sev,
                    "limit": 500,
                },
            )
            for sev in ("WARN", "ERROR")  # OTel exports logging.WARNING as WARN
        ]
        for pattern, kind in PATTERNS.items():
            if (c := _log_claim(logs, svc, pattern, start, end)) is not None:
                evidence[kind].append(c)
        if "memory_mib" in signals:
            mem = call(
                "query_metrics",
                {"service": svc, "metric": "container.memory.usage", "start": iso(start - BASELINE), "end": iso(end)},
            )
            if (c := _metric_claim(mem, svc, "container.memory.usage", start, end)) is not None:
                evidence["memory_leak"].append(c)
        if "pool_wait_ms" in signals:
            pool = call(
                "query_metrics",
                {"service": svc, "metric": "db.pool.wait.mean", "start": iso(start - BASELINE), "end": iso(end)},
            )
            if (c := _metric_claim(pool, svc, "db.pool.wait.mean", start, end)) is not None:
                evidence["pool_exhaustion"].append(c)
        lat = call(
            "query_metrics", {"service": svc, "metric": LATENCY, "start": iso(start - BASELINE), "end": iso(end)}
        )
        latency_claim = _metric_claim(lat, svc, LATENCY, start, end)
        support = [c for c in [latency_claim] if c is not None]
        dom = sorted(dominance.get(svc, []), key=lambda x: (-x[0], x[1]))[:5]
        if svc != root_svc and len(dom) >= 3 and dom[-1][0] >= 0.3:
            support.append(
                {
                    "type": "trace_dependency",
                    "parent_service": root_svc,
                    "child_service": svc,
                    "trace_ids": [t for _, t, _, _, _ in dom],
                    "min_latency_share": _floor(dom[-1][0], 2),
                    "cites": [{"tool_call_seq": seq, "row_ids": [p, ch]} for _, _, seq, p, ch in dom],
                }
            )
        trace_score = len(dominance.get(svc, [])) / n_traces
        temporal = 1 - order.index(svc) / len(order)
        kinds = [k for k in KIND_PRIORITY if evidence.get(k)]
        if kinds:
            kind = kinds[0]
            claims = evidence[kind] + support
            if runbook_search:
                rb = call("search_runbooks", {"query": f"{kind.replace('_', ' ')} in {svc}", "top_k": 3})
                top = [r for r in rb.rows if r["similarity"] >= 0.75][:1]
                claims += [
                    {
                        "type": "runbook_match",
                        "doc_id": r["row_id"],
                        "similarity": _floor(r["similarity"], 4),
                        "cites": [{"tool_call_seq": rb.seq, "row_ids": [r["row_id"]]}],
                    }
                    for r in top
                ]
            score = W_TRACE * trace_score + W_KIND + W_TEMPORAL * temporal + W_DEPLOY * deploy_score
            hypotheses.append(
                {
                    "causal_role": "candidate_root_cause",
                    "cause_service": svc,
                    "cause_kind": kind,
                    "score": round(score, 6),
                    "claims": claims,
                    "narrative": f"{svc}: {kind} evidence; dominant in {len(dominance.get(svc, []))} of "
                    f"{n_traces} slow or failing traces.",
                }
            )
        elif support:
            score = W_TRACE * trace_score + W_TEMPORAL * temporal
            hypotheses.append(
                {
                    "causal_role": "downstream_symptom",
                    "cause_service": svc,
                    "cause_kind": "latency",
                    "score": round(score, 6),
                    "claims": support,
                    "narrative": f"{svc} slowed with no cause of its own in the evidence.",
                }
            )
    hypotheses.sort(
        key=lambda h: (h["causal_role"] != "candidate_root_cause", -float(h["score"]), str(h["cause_service"]))
    )
    return [{"rank": i + 1, **h} for i, h in enumerate(hypotheses)]

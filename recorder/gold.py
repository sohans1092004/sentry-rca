"""Gold claims: typed claims (SPEC §8.1) that are true for a recorded fixture by construction, built
from the exported rows and checked against the §8.2 rules before they are written. Cites name the
§5.1 tool call that returns the cited rows (Amendment A6); Phase 2 replays them as tool calls.

Thresholds are set conservatively below what the data shows (magnitude x 0.8, latency share
rounded down), so a verifier implementing §8.2 exactly passes them with margin."""

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

EPS = 1e-6
BASELINE = timedelta(minutes=15)  # §8.2: the 15 minutes before the claim window
MIN_LOG_RATIO = 2.0  # §8.2 (A24): a log_pattern must at least double against the window before it
MAX_ROWS = 500  # the tool's row cap: a truncated answer cannot prove a count


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _in(t: datetime, start: datetime, end: datetime) -> bool:
    return start <= t <= end


def check_metric_change(rows: list[dict[str, Any]], start: datetime, end: datetime, min_magnitude: float) -> bool:
    before = [r["value"] for r in rows if start - BASELINE <= r["ts"] < start]
    inside = [r["value"] for r in rows if _in(r["ts"], start, end)]
    if len(before) < 3 or len(inside) < 3:
        return False
    b, w = sum(before) / len(before), sum(inside) / len(inside)
    return bool((w - b) / max(abs(b), EPS) >= min_magnitude)


def metric_change(metrics: list[dict[str, Any]], service: str, metric: str, start: datetime, end: datetime,
                  ) -> dict[str, Any] | None:  # fmt: skip
    series: dict[tuple[tuple[str, str], ...], list[dict[str, Any]]] = defaultdict(list)
    for r in metrics:
        if r["service"] == service and r["metric"] == metric and start - BASELINE <= r["ts"] <= end:
            series[tuple(sorted(r["labels"].items()))].append(r)
    best: tuple[float, Any, list[dict[str, Any]]] | None = None
    for labels, rows in series.items():
        before = [r["value"] for r in rows if r["ts"] < start]
        inside = [r["value"] for r in rows if r["ts"] >= start]
        if len(before) < 3 or len(inside) < 3:
            continue
        b, w = sum(before) / len(before), sum(inside) / len(inside)
        ratio = (w - b) / max(abs(b), EPS)
        if best is None or ratio > best[0]:
            best = (ratio, labels, rows)
    if best is None or best[0] < 0.5:
        return None
    ratio, labels, rows = best
    mm = max(0.4, math.floor(ratio * 0.8 * 10) / 10)
    assert check_metric_change(rows, start, end, mm)
    return {
        "type": "metric_change", "service": service, "metric": metric, "window": [_iso(start), _iso(end)],
        "direction": "up", "min_magnitude": mm,
        "cites": [{"tool": "query_metrics",
                   "args": {"service": service, "metric": metric, "start": _iso(start - BASELINE), "end": _iso(end),
                            "labels": dict(labels)},
                   "row_ids": [str(r["point_id"]) for r in sorted(rows, key=lambda r: r["ts"])]}],
    }  # fmt: skip


def log_ratio(n_window: int, n_pre: int) -> float:
    """§8.2 (A24): count in the window over the count in the equal-length window just before it; an
    empty pre-window counts as one line, so a pattern that appears from nothing needs >= 2 lines."""
    return n_window / max(n_pre, 1)


def check_log_pattern(rows: list[dict[str, Any]], pattern: str, start: datetime, end: datetime,
                      min_count: int, min_ratio: float) -> bool:  # fmt: skip
    pre_start = start - (end - start)
    match = [r for r in rows if pattern.lower() in r["body"].lower()]
    n_win = sum(1 for r in match if _in(r["ts"], start, end))
    n_pre = sum(1 for r in match if pre_start <= r["ts"] < start)
    return n_win >= min_count and min_ratio >= MIN_LOG_RATIO and log_ratio(n_win, n_pre) >= min_ratio


def log_pattern(logs: list[dict[str, Any]], service: str, pattern: str, start: datetime, end: datetime,
                ) -> dict[str, Any] | None:  # fmt: skip
    """A log_pattern claim whose count rose (A24). The window is shortened from the fault start until
    the query over [pre-window start, end] fits under the row cap."""
    match = sorted((r for r in logs if r["service"] == service and pattern.lower() in r["body"].lower()),
                   key=lambda r: r["ts"])  # fmt: skip
    for length in (end - start, timedelta(seconds=120), timedelta(seconds=60), timedelta(seconds=30)):
        w_end = min(end, start + length)
        pre_start = start - (w_end - start)
        rows = [r for r in match if pre_start <= r["ts"] <= w_end]
        hits = [r for r in rows if r["ts"] >= start]
        n_pre = len(rows) - len(hits)
        if len(rows) >= MAX_ROWS or len(hits) < 3:
            continue
        ratio = log_ratio(len(hits), n_pre)
        if ratio < MIN_LOG_RATIO:
            return None  # present, but not elevated: not evidence
        min_ratio = max(MIN_LOG_RATIO, math.floor(ratio * 0.8 * 10) / 10)
        cited = hits[:20]
        assert check_log_pattern(rows, pattern, start, w_end, len(cited), min_ratio)
        return {
            "type": "log_pattern", "service": service, "window": [_iso(start), _iso(w_end)], "pattern": pattern,
            "min_count": len(cited), "min_ratio": min_ratio,
            "cites": [{"tool": "query_logs",
                       "args": {"service": service, "start": _iso(pre_start), "end": _iso(w_end), "contains": pattern,
                                "limit": MAX_ROWS},
                       "row_ids": [str(r["log_id"]) for r in cited]}],
        }  # fmt: skip
    return None


def trace_dependency(spans: list[dict[str, Any]], parent_service: str, child_service: str, start: datetime,
                     end: datetime) -> dict[str, Any] | None:  # fmt: skip
    by_trace: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for s in spans:
        by_trace[s["trace_id"]][s["span_id"]] = s

    def descends(span: dict[str, Any], ancestor: str, trace: dict[str, dict[str, Any]]) -> bool:
        seen = 0
        while span["parent_span_id"] and seen < 64:
            if span["parent_span_id"] == ancestor:
                return True
            nxt = trace.get(span["parent_span_id"])
            if nxt is None:
                return False
            span, seen = nxt, seen + 1
        return False

    def server(s: dict[str, Any], service: str) -> bool:
        return bool(s["service"] == service and s["attrs"].get("span.kind") == "SERVER")

    found = []
    for tid, trace in by_trace.items():
        for p in trace.values():
            if not (server(p, parent_service) and not p["parent_span_id"] and _in(p["start_ts"], start, end)):
                continue
            kids = [s for s in trace.values() if server(s, child_service) and descends(s, p["span_id"], trace)]
            if kids and p["duration_ms"] > 0:
                c = max(kids, key=lambda s: s["duration_ms"])
                found.append((c["duration_ms"] / p["duration_ms"], tid, p, c))
    found.sort(key=lambda x: -x[0])
    top = found[:5]
    if len(top) < 3 or top[-1][0] < 0.3:
        return None
    share = math.floor(top[-1][0] * 100) / 100
    return {
        "type": "trace_dependency", "parent_service": parent_service, "child_service": child_service,
        "trace_ids": [t for _, t, _, _ in top], "min_latency_share": share,
        "cites": [{"tool": "query_traces",
                   "args": {"trace_id": t, "start": _iso(start - timedelta(minutes=1)), "end": _iso(end), "limit": 500},
                   "row_ids": [p["span_id"], c["span_id"]]} for _, t, p, c in top],
    }  # fmt: skip


LATENCY = "http.server.request.duration.mean"


def for_fault(kind: str, service: str, params: dict[str, Any], start: datetime, end: datetime,
              tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:  # fmt: skip
    """The claims known true for one injected fault in [start, end]."""
    m, lg, sp = tables["metrics"], tables["logs"], tables["spans"]
    claims: list[dict[str, Any] | None] = []
    latency_fault = kind in ("slow_query", "lock_wait", "pool_exhaustion", "conn_leak", "dependency_outage",
                             "memory_leak", "cache_stampede", "cpu_quota") or (
        kind == "bad_deploy" and params.get("mode") == "slow"
    )  # fmt: skip
    if latency_fault:
        claims.append(metric_change(m, service, LATENCY, start, end))
        if service != "gateway":
            claims.append(trace_dependency(sp, "gateway", service, start, end))
    # v3 vocabulary (A21): what the services' normal code paths log. Labels v1/v2 were built by the
    # Phase 1 vocabulary (git history); they are kept as recorded and no longer rebuilt.
    if kind == "bad_deploy":
        if params.get("mode") == "errors":
            claims.append(log_pattern(lg, service, "Exception in ASGI application", start, end))
    elif kind == "lock_wait":
        claims.append(log_pattern(lg, service, "duration:", start, end))
    elif kind == "conn_leak":
        claims.append(log_pattern(lg, service, "QueuePool limit", start, end))
        claims.append(metric_change(m, service, "db.pool.wait.mean", start, end))
    elif kind == "dependency_outage":
        claims.append(log_pattern(lg, service, "provider charge failed", start, end))
    elif kind == "config_change":
        claims.append(log_pattern(lg, service, "payments call failed", start, end))
    elif kind == "cache_stampede":
        claims.append(metric_change(m, service, "cache.requests", start, end))
    elif kind == "refused":  # applied to the callers; the logs are theirs
        pattern = "Connection refused" if service == "payments" else "inventory call failed"
        claims.append(log_pattern(lg, service, pattern, start, end))
    elif kind == "cpu_quota":
        claims.append(metric_change(m, service, "container.cpu.throttled", start, end))
    elif kind == "memory_leak":
        claims.append(metric_change(m, service, "container.memory.usage", start, end))
    elif kind == "cpu_burn":  # noisy_neighbor: the job's own CPU, and the symptom at the edge
        claims.append(metric_change(m, "batchjob", "container.cpu.utilization", start, end))
        claims.append(metric_change(m, "gateway", LATENCY, start, end))
    elif kind == "jitter":  # no_fault: only the symptom is real
        claims.append(metric_change(m, "gateway", LATENCY, start, end))
    return [c for c in claims if c is not None]


def _identity(c: dict[str, Any]) -> tuple[Any, ...]:
    return (c["type"], c.get("service"), c.get("metric"), c.get("pattern"), c.get("parent_service"),
            c.get("child_service"))  # fmt: skip


def for_run(run: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Gold claims for a whole injection run. A fault applied to several services at once (no_fault's
    jitter on all four) yields the same claim per step; each distinct claim is kept once."""
    end = datetime.fromisoformat(run["injection_end"])
    claims: dict[tuple[Any, ...], dict[str, Any]] = {}
    for a in run["applied"]:
        # planted lines are false by construction, and confounders are not causes: never gold
        if a["kind"] == "plant_logs" or a.get("role", "cause") != "cause":
            continue
        at = datetime.fromisoformat(a["at"])
        for c in for_fault(a["kind"], a["service"], a["params"], at, min(end, at + timedelta(seconds=a["duration_s"])),
                           tables):  # fmt: skip
            claims.setdefault(_identity(c), c)
    return list(claims.values())

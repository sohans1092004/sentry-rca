"""get_incident_timeline (SPEC §5.1): deploys, anomaly onsets per service and signal, and call edges in
the window, merged chronologically. Rows are computed, so their row_id is an ordinal (§4.3).

Onset detection (Amendment A20), per service and signal, on 30 s buckets:
- baseline = the buckets in the first BASELINE of the window (needs >= MIN_BASELINE of them);
- a bucket is anomalous when value > median + max(4 x 1.4826 x MAD, RISE x |median|, FLOOR[signal]);
- the onset is the first of two consecutive anomalous buckets after the baseline.
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from investigation.backend import Backend, Row

BUCKET = timedelta(seconds=30)
BASELINE = timedelta(minutes=10)
MIN_BASELINE = 6
RISE = 0.5
FLOOR = {"latency_ms": 20.0, "error_rate": 0.05, "cpu_cores": 0.2, "memory_mib": 32.0, "pool_wait_ms": 20.0}
METRICS = ["http.server.request.duration.sum", "http.server.request.duration.count", "container.cpu.utilization",
           "container.memory.usage", "db.pool.wait.sum", "db.pool.wait.count"]  # fmt: skip
FETCH_LIMIT = 1_000_000  # internal fetch; the result itself is capped when snapshotted


def _bucket(t: datetime, start: datetime) -> datetime:
    return start + BUCKET * int((t - start) / BUCKET)


def signals(rows: list[Row], start: datetime) -> dict[tuple[str, str], dict[datetime, float]]:
    """(service, signal) -> bucket -> value."""
    acc: dict[tuple[str, str, datetime], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    gauges: dict[tuple[str, str, datetime], list[float]] = defaultdict(list)
    for r in rows:
        b, svc, m = _bucket(r["ts"], start), r["service"], r["metric"]
        if m.startswith("http.server.request.duration."):
            a = acc[(svc, "http", b)]
            a[m.rsplit(".", 1)[1]] += r["value"]
            if m.endswith(".count") and str(r["labels"].get("http.response.status_code", "")).startswith("5"):
                a["errors"] += r["value"]
        elif m.startswith("db.pool.wait."):
            acc[(svc, "pool", b)][m.rsplit(".", 1)[1]] += r["value"]
        elif m == "container.cpu.utilization":
            gauges[(svc, "cpu_cores", b)].append(r["value"])
        elif m == "container.memory.usage":
            gauges[(svc, "memory_mib", b)].append(r["value"] / 1048576)
    out: dict[tuple[str, str], dict[datetime, float]] = defaultdict(dict)
    for (svc, kind, b), a in acc.items():
        if a.get("count", 0) > 0:
            if kind == "http":
                out[(svc, "latency_ms")][b] = 1000 * a["sum"] / a["count"]
                out[(svc, "error_rate")][b] = a["errors"] / a["count"]
            else:
                out[(svc, "pool_wait_ms")][b] = a["sum"] / a["count"]
    for (svc, sig, b), vals in gauges.items():
        out[(svc, sig)][b] = sum(vals) / len(vals)
    return out


def onset(series: dict[datetime, float], signal: str, start: datetime) -> dict[str, Any] | None:
    times = sorted(series)
    base = [series[t] for t in times if t < start + BASELINE]
    if len(base) < MIN_BASELINE:
        return None
    median = statistics.median(base)
    mad = statistics.median(abs(x - median) for x in base)
    threshold = median + max(4 * 1.4826 * mad, RISE * abs(median), FLOOR[signal])
    after = [t for t in times if t >= start + BASELINE]
    for t0, t1 in zip(after, after[1:], strict=False):
        if t1 - t0 == BUCKET and series[t0] > threshold and series[t1] > threshold:
            peak = max(series[t] for t in after if t >= t0)
            return {"ts": t0, "baseline": round(median, 6), "threshold": round(threshold, 6), "peak": round(peak, 6)}
    return None


def build(backend: Backend, tenant: str, services: list[str], start: datetime, end: datetime) -> list[Row]:
    rows: list[Row] = []
    for d in backend.deploys(tenant, None, start, end):
        if d["service"] in services:
            rows.append({"kind": "deploy", "ts": d["finished_at"], "service": d["service"], "deploy_id": d["id"],
                         "version": d["version"], "started_at": d["started_at"]})  # fmt: skip
    metric_rows = backend.metrics(tenant, services, METRICS, start, end, {}, FETCH_LIMIT)
    for (svc, sig), series in sorted(signals(metric_rows, start).items()):
        o = onset(series, sig, start)
        if o is not None:
            rows.append({"kind": "anomaly_onset", "service": svc, "signal": sig, **o})
    for parent, child, calls in backend.edges(tenant, start, end):
        if parent in services or child in services:
            rows.append({"kind": "call_edge", "ts": start, "parent": parent, "child": child, "calls": calls})
    rows.sort(key=lambda r: (r["ts"], r["kind"], r.get("service", ""), r.get("signal", ""), r.get("parent", ""),
                             r.get("child", "")))  # fmt: skip
    return [{**r, "row_id": f"t{i}"} for i, r in enumerate(rows)]

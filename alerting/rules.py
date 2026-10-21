"""Pure rule evaluation (SPEC §2.1, ADR-004; thresholds in Amendment A8). No I/O here."""

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

MINUTE = timedelta(minutes=1)


@dataclass
class Window:
    """What the engine read from ClickHouse for one rule evaluation."""

    status_counts: dict[str, float] = field(default_factory=dict)  # status code -> requests in window
    buckets: dict[float, float] = field(default_factory=dict)  # bucket upper bound (s) -> count in window
    baseline_p95_ms: list[float] = field(default_factory=list)  # one value per baseline minute


def outside_incidents(minutes: dict[datetime, Any], periods: list[tuple[datetime, datetime]]) -> dict[datetime, Any]:
    """A29: baseline minutes that overlap no incident period. An incident's period runs from its first
    anomaly to its resolution, so the fault that opened it and its recovery never become "normal"."""
    return {m: v for m, v in minutes.items() if not any(m < end and m + MINUTE > start for start, end in periods)}


def quantile_ms(buckets: dict[float, float], q: float) -> float | None:
    """Quantile from per-bucket counts (upper bounds in seconds), linear within a bucket, as
    Prometheus' histogram_quantile does. The +Inf bucket returns its lower bound."""
    total = sum(buckets.values())
    if total <= 0:
        return None
    target, cumulative, lower = q * total, 0.0, 0.0
    for le in sorted(buckets):
        count = buckets[le]
        if count > 0 and cumulative + count >= target:
            if math.isinf(le):
                return lower * 1000
            return (lower + (le - lower) * (target - cumulative) / count) * 1000
        cumulative += count
        if not math.isinf(le):
            lower = le
    return lower * 1000


def robust_z(value: float, baseline: list[float]) -> tuple[float, float]:
    """(z, median) with z = (value - median) / (1.4826 * MAD). Sigma is floored at 5 % of the
    median and 1 ms, so a perfectly flat baseline cannot turn a 1 ms wobble into z = inf."""
    median = statistics.median(baseline)
    mad = statistics.median(abs(x - median) for x in baseline)
    sigma = max(1.4826 * mad, 0.05 * median, 1.0)
    return (value - median) / sigma, median


def check(condition: dict[str, Any], w: Window) -> dict[str, Any] | None:
    """The first breached sub-condition of an any_of rule, with its numbers; None if healthy."""
    for c in condition["any_of"]:
        if c["kind"] == "error_rate":
            total = sum(w.status_counts.values())
            errors = sum(n for code, n in w.status_counts.items() if code.startswith("5"))
            if total >= c["min_requests"] and errors / total > c["threshold"]:
                return {"kind": "error_rate", "value": errors / total, "requests": total}
        elif c["kind"] == "latency_zscore":
            current = quantile_ms(w.buckets, c["quantile"])
            if current is None or len(w.baseline_p95_ms) < c["min_baseline_points"]:
                continue
            z, median = robust_z(current, w.baseline_p95_ms)
            if z > c["z"] and current > c["min_ratio"] * median and current - median > c["min_delta_ms"]:
                return {"kind": "latency_zscore", "value": current, "baseline_median": median, "z": z}
        else:
            raise ValueError(f"unknown condition kind {c['kind']}")
    return None

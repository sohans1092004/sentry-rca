import uuid
from datetime import UTC, datetime, timedelta

from recorder import gold

T0 = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
W0, W1 = T0, T0 + timedelta(minutes=3)


def point(svc, ts, value, labels=None):
    return {"service": svc, "metric": gold.LATENCY, "labels": labels or {"route": "/x"}, "ts": ts, "value": value,
            "point_id": uuid.uuid4()}  # fmt: skip


def series(before, inside):
    rows = [point("orders", T0 - timedelta(seconds=5 * (i + 1)), before) for i in range(30)]
    return rows + [point("orders", T0 + timedelta(seconds=5 * i), inside) for i in range(30)]


def test_metric_change_claim_is_true_with_margin():
    rows = series(0.040, 0.300) + [point("orders", T0, 9.0, {"route": "/other"})]  # noise series: too few points
    c = gold.metric_change(rows, "orders", gold.LATENCY, W0, W1)
    assert c["min_magnitude"] == 5.2  # ratio 6.5, x 0.8, rounded down
    cited = [r for r in rows if str(r["point_id"]) in set(c["cites"][0]["row_ids"])]
    assert len(cited) == 60 and c["cites"][0]["args"]["labels"] == {"route": "/x"}
    assert gold.check_metric_change(cited, W0, W1, 6.5)  # the exact §8.2 boundary passes...
    assert not gold.check_metric_change(cited, W0, W1, 6.5001)  # ...and just over it fails


def test_metric_change_needs_three_points_each_side_and_a_real_change():
    assert gold.metric_change(series(0.04, 0.3)[28:32], "orders", gold.LATENCY, W0, W1) is None
    assert gold.metric_change(series(0.04, 0.045), "orders", gold.LATENCY, W0, W1) is None


def span(tid, sid, parent, svc, dur, kind="SERVER"):
    return {"trace_id": tid, "span_id": sid, "parent_span_id": parent, "service": svc, "duration_ms": dur,
            "start_ts": T0 + timedelta(seconds=10), "attrs": {"span.kind": kind}}  # fmt: skip


def test_trace_dependency_requires_descendant_and_share():
    spans = []
    for i in range(4):
        t = f"t{i}"
        spans += [span(t, f"g{i}", "", "gateway", 1000), span(t, f"c{i}", f"g{i}", "orders", 900, "CLIENT"),
                  span(t, f"i{i}", f"c{i}", "inventory", 600 + i * 50)]  # fmt: skip
    spans.append(span("t9", "x", "unrelated", "inventory", 999))  # not under any gateway span
    c = gold.trace_dependency(spans, "gateway", "inventory", W0, W1)
    assert c["trace_ids"] == ["t3", "t2", "t1", "t0"] and c["min_latency_share"] == 0.6
    assert c["cites"][0]["row_ids"] == ["g3", "i3"]


def test_log_pattern_cites_matching_rows_only():
    logs = [{"service": "inventory", "ts": T0 + timedelta(seconds=i), "body": b, "log_id": uuid.uuid4()}
            for i, b in enumerate(["Pool acquire TIMEOUT after 0.5s", "ok", "pool acquire timeout x"])]  # fmt: skip
    c = gold.log_pattern(logs, "inventory", "pool acquire timeout", W0, W1)
    assert c["min_count"] == 2 and len(c["cites"][0]["row_ids"]) == 2
    assert gold.log_pattern(logs, "orders", "pool acquire timeout", W0, W1) is None

"""Property tests: on generated variants the verifier agrees with recorder/gold.py (the tests import
gold; the verifier never does), and tightening a true claim past the data makes it fail."""

from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from investigation.scope import iso
from investigation.verifier import verify_claim
from recorder import gold
from tests.unit.verifier_helpers import T0, call

END = T0 + timedelta(minutes=5)
values = st.floats(min_value=0.0, max_value=1e4, allow_nan=False, allow_infinity=False)
offsets_before = st.integers(min_value=1, max_value=900)  # seconds before T0, inside the 15-min baseline
offsets_inside = st.integers(min_value=0, max_value=300)  # seconds after T0, inside the window


def _metric_rows(before, inside):
    rows = [{"row_id": f"b{i}", "service": "s", "metric": "m", "ts": T0 - timedelta(seconds=o), "value": v}
            for i, (o, v) in enumerate(before)]  # fmt: skip
    rows += [{"row_id": f"w{i}", "service": "s", "metric": "m", "ts": T0 + timedelta(seconds=o), "value": v}
             for i, (o, v) in enumerate(inside)]  # fmt: skip
    return rows


def _as_snapshot(rows):
    return [{**r, "ts": iso(r["ts"])} for r in rows]


@settings(max_examples=400, deadline=None)
@given(
    before=st.lists(st.tuples(offsets_before, values), min_size=0, max_size=8),
    inside=st.lists(st.tuples(offsets_inside, values), min_size=0, max_size=8),
    mm=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
)
def test_metric_change_agrees_with_gold(before, inside, mm):
    rows = _metric_rows(before, inside)
    expected = gold.check_metric_change(rows, T0, END, mm)
    claim = {"type": "metric_change", "service": "s", "metric": "m", "window": [iso(T0), iso(END)],
             "direction": "up", "min_magnitude": mm,
             "cites": [{"tool_call_seq": 1, "row_ids": [r["row_id"] for r in rows] or ["none"]}]}  # fmt: skip
    got = verify_claim(0, claim, {1: call(1, "query_metrics", _as_snapshot(rows))}, "baseline")
    assert got.passed is expected, got.reason


words = st.sampled_from(["pool", "acquire", "timeout", "TIMEOUT", "Pool", "ok", "slow", "query", "x"])


@settings(max_examples=300, deadline=None)
@given(bodies=st.lists(st.lists(words, min_size=1, max_size=6).map(" ".join), min_size=1, max_size=30),
       pattern=st.sampled_from(["pool acquire", "timeout", "slow query", "Pool"]))  # fmt: skip
def test_log_pattern_gold_claims_pass_and_tightened_ones_fail(bodies, pattern):
    lg = [{"row_id": f"l{i}", "log_id": f"l{i}", "service": "s", "ts": T0 + timedelta(seconds=i), "body": b}
          for i, b in enumerate(bodies)]  # fmt: skip
    claim = gold.log_pattern(lg, "s", pattern, T0, END)
    if claim is None:
        assert not any(pattern.lower() in b.lower() for b in bodies)
        return
    calls = {1: call(1, "query_logs", _as_snapshot(lg))}
    claim = {**claim, "cites": [{"tool_call_seq": 1, "row_ids": claim["cites"][0]["row_ids"]}]}
    assert verify_claim(0, claim, calls, "baseline").passed
    tighter = {**claim, "min_count": claim["min_count"] + 1}
    assert not verify_claim(0, tighter, calls, "baseline").passed


@st.composite
def traces(draw):
    spans = []
    for t in range(draw(st.integers(min_value=3, max_value=7))):
        tid = f"tr{t}"
        parent_ms = draw(st.floats(min_value=10, max_value=5000))
        depth = draw(st.integers(min_value=1, max_value=5))  # intermediate spans between root and child
        child_ms = draw(st.floats(min_value=0, max_value=parent_ms))
        spans.append({"trace_id": tid, "span_id": f"{tid}r", "parent_span_id": "", "service": "gateway",
                      "attrs": {"span.kind": "SERVER"}, "start_ts": T0 + timedelta(seconds=t),
                      "duration_ms": parent_ms})  # fmt: skip
        prev = f"{tid}r"
        for d in range(depth):
            spans.append({"trace_id": tid, "span_id": f"{tid}m{d}", "parent_span_id": prev, "service": "orders",
                          "attrs": {"span.kind": "CLIENT"}, "start_ts": T0 + timedelta(seconds=t),
                          "duration_ms": parent_ms})  # fmt: skip
            prev = f"{tid}m{d}"
        spans.append({"trace_id": tid, "span_id": f"{tid}c", "parent_span_id": prev, "service": "inventory",
                      "attrs": {"span.kind": "SERVER"}, "start_ts": T0 + timedelta(seconds=t),
                      "duration_ms": child_ms})  # fmt: skip
    return spans


@settings(max_examples=200, deadline=None)
@given(spans=traces())
def test_trace_dependency_gold_claims_pass_and_tightened_ones_fail(spans):
    claim = gold.trace_dependency(spans, "gateway", "inventory", T0, END)
    if claim is None:
        return  # gold emits nothing below a 0.3 share; nothing to agree on
    snapshot = [{**s, "row_id": s["span_id"], "start_ts": iso(s["start_ts"])} for s in spans]
    calls = {1: call(1, "query_traces", snapshot)}
    row_ids = [rid for c in claim["cites"] for rid in c["row_ids"]]
    claim = {**claim, "cites": [{"tool_call_seq": 1, "row_ids": row_ids}]}
    got = verify_claim(0, claim, calls, "baseline")
    assert got.passed, got.reason
    tighter = {**claim, "min_latency_share": claim["min_latency_share"] + 0.01}
    assert not verify_claim(0, tighter, calls, "baseline").passed

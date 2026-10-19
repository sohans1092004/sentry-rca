"""Recording-time sampling (A22, G1): deterministic, whole traces kept or dropped together, about the
configured fractions kept."""

import uuid

from recorder.record import sample


def test_sampling_keeps_whole_traces_and_about_the_configured_fractions():
    spans = [{"trace_id": f"t{t}", "span_id": f"s{t}.{i}"} for t in range(2000) for i in range(3)]
    logs = [{"log_id": uuid.UUID(int=i)} for i in range(5000)]
    tables = {"spans": spans, "logs": logs, "metrics": [{"point_id": 1}], "deploys": []}
    out = sample(tables, {"traces": 0.5, "logs": 0.7})
    kept = {}
    for s in out["spans"]:
        kept.setdefault(s["trace_id"], 0)
        kept[s["trace_id"]] += 1
    assert set(kept.values()) == {3}  # a trace is kept whole or not at all
    assert 0.45 < len(kept) / 2000 < 0.55 and 0.67 < len(out["logs"]) / 5000 < 0.73
    assert out["metrics"] == tables["metrics"]  # metrics are never sampled
    assert sample(tables, {"traces": 0.5, "logs": 0.7}) == out  # deterministic

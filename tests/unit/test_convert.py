import time

from opentelemetry.proto.trace.v1.trace_pb2 import Span

from common import synthetic
from processors.convert import convert_logs, convert_metrics, convert_traces


def test_metrics_expand_histogram_and_keep_ids_stable():
    payload = synthetic.metrics("orders", 4).SerializeToString()
    a, b = convert_metrics(payload), convert_metrics(payload)
    names = sorted({r[2] for r in a.rows})
    assert names == [
        "synthetic.duration.bucket",
        "synthetic.duration.count",
        "synthetic.duration.mean",
        "synthetic.duration.sum",
        "synthetic.gauge",
    ]
    assert len(a.rows) == 4 + 3 + 3  # gauges + count/sum/mean + 3 buckets
    assert [r[-1] for r in a.rows] == [r[-1] for r in b.rows]
    assert not a.rejects


def test_logs_and_traces_convert():
    lg = convert_logs(synthetic.logs("payments", 3).SerializeToString())
    assert len(lg.rows) == 3 and lg.rows[0][1] == "payments" and lg.rows[0][3] == "INFO"
    tr = convert_traces(synthetic.traces("inventory", 2).SerializeToString())
    assert len(tr.rows) == 2 and tr.rows[0][9]["span.kind"] == "SERVER" and tr.rows[0][7] == 5.0


def test_missing_identity_rejects_resource():
    for build, convert in (
        (synthetic.metrics, convert_metrics),
        (synthetic.logs, convert_logs),
        (synthetic.traces, convert_traces),
    ):
        out = convert(build(None, 2).SerializeToString())
        assert not out.rows and out.rejects[0].reason == "resource has no service.name"
        out = convert(build("gateway", 2, tenant=None).SerializeToString())
        assert not out.rows and "sentry.tenant_id" in out.rejects[0].reason


def test_bad_record_rejected_neighbours_kept():
    data = synthetic.traces("gateway", 3)
    spans = data.resource_spans[0].scope_spans[0].spans
    spans[1].span_id = b"\x01\x02"
    spans[2].end_time_unix_nano = spans[2].start_time_unix_nano - 1
    out = convert_traces(data.SerializeToString())
    assert len(out.rows) == 1
    assert [r.reason for r in out.rejects] == ["span_id has 2 bytes", "span ends before it starts"]


def test_nan_and_bucket_mismatch_rejected():
    data = synthetic.metrics("orders", 2, ts_ns=time.time_ns())
    m = data.resource_metrics[0].scope_metrics[0].metrics
    m[0].gauge.data_points[0].as_double = float("nan")
    m[1].histogram.data_points[0].bucket_counts.append(9)
    out = convert_metrics(data.SerializeToString())
    reasons = sorted(r.reason for r in out.rejects)
    assert reasons == [
        "histogram synthetic.duration has 4 buckets for 2 bounds",
        "metric synthetic.gauge value is not finite",
    ]
    assert len(out.rows) == 1


def test_span_kind_client_peer():
    data = synthetic.traces("orders", 1)
    sp = data.resource_spans[0].scope_spans[0].spans[0]
    sp.kind = Span.SPAN_KIND_CLIENT
    assert convert_traces(data.SerializeToString()).rows[0][9]["span.kind"] == "CLIENT"

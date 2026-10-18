"""Synthetic OTLP payloads for tests and the ingestion-ceiling load generator."""

import os
import time

from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord, LogsData, ResourceLogs, ScopeLogs
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    Gauge,
    Histogram,
    HistogramDataPoint,
    Metric,
    MetricsData,
    NumberDataPoint,
    ResourceMetrics,
    ScopeMetrics,
)
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, TracesData

from common.config import DEMO_TENANT_ID

_last_ns = 0


def _now_ns() -> int:
    """Strictly increasing: Windows clocks tick coarsely, and two payloads built in the same tick
    would be identical telemetry (and correctly deduplicated)."""
    global _last_ns
    _last_ns = max(time.time_ns(), _last_ns + 1000)
    return _last_ns


def _kv(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))


def resource(service: str | None, tenant: str | None = DEMO_TENANT_ID) -> Resource:
    attrs = []
    if service is not None:
        attrs.append(_kv("service.name", service))
    if tenant is not None:
        attrs.append(_kv("sentry.tenant_id", tenant))
    return Resource(attributes=attrs)


def metrics(service: str | None, n: int, ts_ns: int | None = None, tenant: str | None = DEMO_TENANT_ID) -> MetricsData:
    """n gauge points plus one histogram point (which expands to count/sum/mean/buckets)."""
    ts = ts_ns or _now_ns()
    gauge = Metric(
        name="synthetic.gauge",
        gauge=Gauge(
            data_points=[
                NumberDataPoint(
                    time_unix_nano=ts + i * 1_000_000, as_double=float(i), attributes=[_kv("series", str(i % 10))]
                )
                for i in range(n)
            ]
        ),
    )
    hist = Metric(
        name="synthetic.duration",
        histogram=Histogram(
            data_points=[
                HistogramDataPoint(
                    time_unix_nano=ts, count=3, sum=0.3, explicit_bounds=[0.1, 1.0], bucket_counts=[1, 2, 0]
                )
            ]
        ),
    )
    return MetricsData(
        resource_metrics=[
            ResourceMetrics(resource=resource(service, tenant), scope_metrics=[ScopeMetrics(metrics=[gauge, hist])])
        ]
    )


def logs(service: str | None, n: int, ts_ns: int | None = None, tenant: str | None = DEMO_TENANT_ID) -> LogsData:
    ts = ts_ns or _now_ns()
    records = [
        LogRecord(
            time_unix_nano=ts + i * 1000,
            severity_text="INFO",
            body=AnyValue(string_value=f"synthetic log line {i}"),
            attributes=[_kv("i", str(i))],
        )
        for i in range(n)
    ]
    return LogsData(
        resource_logs=[ResourceLogs(resource=resource(service, tenant), scope_logs=[ScopeLogs(log_records=records)])]
    )


def traces(service: str | None, n: int, ts_ns: int | None = None, tenant: str | None = DEMO_TENANT_ID) -> TracesData:
    ts = ts_ns or _now_ns()
    trace_id = os.urandom(16)
    spans = [
        Span(
            trace_id=trace_id,
            span_id=os.urandom(8),
            name=f"synthetic span {i}",
            kind=Span.SPAN_KIND_SERVER,
            start_time_unix_nano=ts,
            end_time_unix_nano=ts + 5_000_000,
        )
        for i in range(n)
    ]
    return TracesData(
        resource_spans=[ResourceSpans(resource=resource(service, tenant), scope_spans=[ScopeSpans(spans=spans)])]
    )

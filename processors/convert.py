"""OTLP protobuf -> ClickHouse rows, with schema validation (SPEC §2.1, §15 row 2).

Decode failures reject the whole message; every other check rejects only the offending record
(a data point, log record or span; or a whole resource when its identity is missing), so one bad
record never drops its neighbours.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogsData
from opentelemetry.proto.metrics.v1.metrics_pb2 import MetricsData
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status, TracesData

from common import ids

TENANT_ATTR = "sentry.tenant_id"  # set by the Collector (upsert), never trusted from the SDK

METRIC_COLUMNS = ["tenant_id", "service", "metric", "labels", "ts", "value", "point_id"]
LOG_COLUMNS = ["tenant_id", "service", "ts", "severity", "body", "trace_id", "span_id", "attrs", "log_id"]
SPAN_COLUMNS = [
    "tenant_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "service",
    "name",
    "start_ts",
    "duration_ms",
    "status",
    "attrs",
]


class Invalid(Exception):
    pass


def _check(ok: bool, reason: str) -> None:
    if not ok:
        raise Invalid(reason)


@dataclass
class Reject:
    reason: str
    record: dict[str, Any]


@dataclass
class Converted:
    rows: list[list[Any]] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)


def _any(v: AnyValue) -> str:
    kind = v.WhichOneof("value")
    if kind is None:
        return ""
    if kind == "string_value":
        return v.string_value
    if kind == "bool_value":
        return "true" if v.bool_value else "false"
    if kind == "int_value":
        return str(v.int_value)
    if kind == "double_value":
        return repr(v.double_value)
    if kind == "bytes_value":
        return v.bytes_value.hex()
    return json.dumps(MessageToDict(v), sort_keys=True)


def _attrs(kvs: Any) -> dict[str, str]:
    items: list[KeyValue] = sorted(kvs, key=lambda kv: kv.key)
    return {kv.key: _any(kv.value) for kv in items}


def _ts(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC)


def _identity(resource_attrs: dict[str, str]) -> tuple[str, str]:
    service = resource_attrs.get("service.name", "")
    tenant = resource_attrs.get(TENANT_ATTR, "")
    _check(service != "", "resource has no service.name")
    _check(tenant != "", f"resource has no {TENANT_ATTR}")
    return tenant, service


def _record(msg: Message) -> dict[str, Any]:
    out: dict[str, Any] = MessageToDict(msg)
    return out


def _guarded(out: Converted, msg: Message, rows: Callable[..., list[list[Any]]], *args: Any) -> None:
    try:
        out.rows.extend(rows(*args))
    except Invalid as e:
        out.rejects.append(Reject(str(e), _record(msg)))


# --- metrics ---------------------------------------------------------------------------------


def _metric_row(tenant: str, service: str, name: str, labels: dict[str, str], ts_ns: int, value: float) -> list[Any]:
    _check(name != "", "metric has no name")
    _check(ts_ns > 0, f"metric {name} point has no timestamp")
    _check(math.isfinite(value), f"metric {name} value is not finite")
    return [tenant, service, name, labels, _ts(ts_ns), value, ids.point_id(tenant, service, name, labels, ts_ns)]


def _number_rows(tenant: str, service: str, name: str, dp: Any) -> list[list[Any]]:
    which = dp.WhichOneof("value")
    _check(which is not None, f"metric {name} point has no value")
    value = dp.as_double if which == "as_double" else float(dp.as_int)
    return [_metric_row(tenant, service, name, _attrs(dp.attributes), dp.time_unix_nano, value)]


def _histogram_rows(tenant: str, service: str, name: str, dp: Any) -> list[list[Any]]:
    """A histogram point becomes .count, .sum, .mean and one .bucket row per bucket (label le =
    upper bound; per-bucket counts, not cumulative)."""
    n_counts, n_bounds = len(dp.bucket_counts), len(dp.explicit_bounds)
    _check(n_counts == n_bounds + 1, f"histogram {name} has {n_counts} buckets for {n_bounds} bounds")
    labels, ts = _attrs(dp.attributes), dp.time_unix_nano
    rows = [_metric_row(tenant, service, f"{name}.count", labels, ts, float(dp.count))]
    if dp.HasField("sum"):
        rows.append(_metric_row(tenant, service, f"{name}.sum", labels, ts, dp.sum))
        if dp.count > 0:
            rows.append(_metric_row(tenant, service, f"{name}.mean", labels, ts, dp.sum / dp.count))
    bounds = [repr(b) for b in dp.explicit_bounds] + ["+Inf"]
    for le, n in zip(bounds, dp.bucket_counts, strict=True):
        rows.append(_metric_row(tenant, service, f"{name}.bucket", {**labels, "le": le}, ts, float(n)))
    return rows


def convert_metrics(payload: bytes) -> Converted:
    data = MetricsData.FromString(payload)
    out = Converted()
    for rm in data.resource_metrics:
        try:
            tenant, service = _identity(_attrs(rm.resource.attributes))
        except Invalid as e:
            out.rejects.append(Reject(str(e), _record(rm)))
            continue
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                kind = m.WhichOneof("data")
                if kind in ("gauge", "sum"):
                    for dp in m.gauge.data_points if kind == "gauge" else m.sum.data_points:
                        _guarded(out, dp, _number_rows, tenant, service, m.name, dp)
                elif kind == "histogram":
                    for dp in m.histogram.data_points:
                        _guarded(out, dp, _histogram_rows, tenant, service, m.name, dp)
                else:
                    out.rejects.append(Reject(f"unsupported metric type {kind} for {m.name}", _record(m)))
    return out


# --- logs ------------------------------------------------------------------------------------

_SEVERITY = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"]


def _severity(text: str, number: int) -> str:
    if text:
        return text.upper()
    if 1 <= number <= 24:
        return _SEVERITY[(number - 1) // 4]
    return "UNSPECIFIED"


def _log_rows(tenant: str, service: str, lr: Any) -> list[list[Any]]:
    ts_ns = lr.time_unix_nano or lr.observed_time_unix_nano
    _check(ts_ns > 0, "log record has no timestamp")
    _check(len(lr.trace_id) in (0, 16), f"log trace_id has {len(lr.trace_id)} bytes")
    _check(len(lr.span_id) in (0, 8), f"log span_id has {len(lr.span_id)} bytes")
    sev = _severity(lr.severity_text, lr.severity_number)
    body = _any(lr.body)
    trace_id, span_id = lr.trace_id.hex(), lr.span_id.hex()
    attrs = _attrs(lr.attributes)
    lid = ids.log_id(tenant, service, ts_ns, sev, body, trace_id, span_id, attrs)
    return [[tenant, service, _ts(ts_ns), sev, body, trace_id, span_id, attrs, lid]]


def convert_logs(payload: bytes) -> Converted:
    data = LogsData.FromString(payload)
    out = Converted()
    for rl in data.resource_logs:
        try:
            tenant, service = _identity(_attrs(rl.resource.attributes))
        except Invalid as e:
            out.rejects.append(Reject(str(e), _record(rl)))
            continue
        for sl in rl.scope_logs:
            for lr in sl.log_records:
                _guarded(out, lr, _log_rows, tenant, service, lr)
    return out


# --- traces ----------------------------------------------------------------------------------

_ZERO_TRACE = bytes(16)


def _span_rows(tenant: str, service: str, version: str, sp: Any) -> list[list[Any]]:
    _check(len(sp.trace_id) == 16 and sp.trace_id != _ZERO_TRACE, "span has no valid trace_id")
    _check(len(sp.span_id) == 8, f"span_id has {len(sp.span_id)} bytes")
    _check(len(sp.parent_span_id) in (0, 8), f"parent_span_id has {len(sp.parent_span_id)} bytes")
    _check(sp.name != "", "span has no name")
    _check(sp.start_time_unix_nano > 0, "span has no start time")
    _check(sp.end_time_unix_nano >= sp.start_time_unix_nano, "span ends before it starts")
    attrs = _attrs(sp.attributes)
    attrs["span.kind"] = Span.SpanKind.Name(sp.kind).removeprefix("SPAN_KIND_")
    if version:
        attrs["service.version"] = version
    status = Status.StatusCode.Name(sp.status.code).removeprefix("STATUS_CODE_")
    duration_ms = (sp.end_time_unix_nano - sp.start_time_unix_nano) / 1e6
    return [[
        tenant, sp.trace_id.hex(), sp.span_id.hex(), sp.parent_span_id.hex(), service, sp.name,
        _ts(sp.start_time_unix_nano), duration_ms, status, dict(sorted(attrs.items())),
    ]]  # fmt: skip


def convert_traces(payload: bytes) -> Converted:
    data = TracesData.FromString(payload)
    out = Converted()
    for rs in data.resource_spans:
        res = _attrs(rs.resource.attributes)
        try:
            tenant, service = _identity(res)
        except Invalid as e:
            out.rejects.append(Reject(str(e), _record(rs)))
            continue
        for ss in rs.scope_spans:
            for sp in ss.spans:
                _guarded(out, sp, _span_rows, tenant, service, res.get("service.version", ""), sp)
    return out


SIGNALS: dict[str, tuple[str, list[str], Callable[[bytes], Converted]]] = {
    "metrics": ("metrics", METRIC_COLUMNS, convert_metrics),
    "logs": ("logs", LOG_COLUMNS, convert_logs),
    "traces": ("spans", SPAN_COLUMNS, convert_traces),
}

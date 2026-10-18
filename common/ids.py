"""Stable IDs: the same telemetry always gets the same ID, so a redelivered copy collapses into
the original in ReplacingMergeTree (SPEC §4.1 Dedup)."""

import json
import uuid

_NAMESPACE = uuid.UUID("6d3c1f0e-7a52-4b8e-9a51-5e2f0c9b1a47")


def _stable(*parts: object) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, json.dumps(parts, sort_keys=True, separators=(",", ":")))


def point_id(tenant: str, service: str, metric: str, labels: dict[str, str], ts_ns: int) -> uuid.UUID:
    return _stable("m", tenant, service, metric, labels, ts_ns)


def log_id(
    tenant: str,
    service: str,
    ts_ns: int,
    severity: str,
    body: str,
    trace_id: str,
    span_id: str,
    attrs: dict[str, str],
) -> uuid.UUID:
    return _stable("l", tenant, service, ts_ns, severity, body, trace_id, span_id, attrs)

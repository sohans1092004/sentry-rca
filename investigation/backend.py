"""Raw telemetry access behind the tools. Every implementation returns the same rows, in the same
order, for the same arguments: time bounds inclusive, one row per stable ID, tenant always filtered.

- ClickHouseBackend: the real one; every value is a bound parameter, never string-built SQL.
- OfflineBackend: the same filters over a fixture's Parquet rows, for unit tests and development
  without a database. tests/integration/test_backend_agreement.py holds the two to identical output.
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Protocol

from clickhouse_connect.driver.client import Client

Row = dict[str, Any]


class Backend(Protocol):
    def metrics(self, tenant: str, services: list[str], metrics: list[str], start: datetime, end: datetime,
                labels: dict[str, str], limit: int) -> list[Row]: ...  # fmt: skip

    def logs(self, tenant: str, service: str, start: datetime, end: datetime, severity: str | None,
             contains: str | None, trace_id: str | None, limit: int) -> list[Row]: ...  # fmt: skip

    def spans(self, tenant: str, services: list[str], trace_id: str | None, start: datetime, end: datetime,
              min_duration_ms: float | None, limit: int) -> list[Row]: ...  # fmt: skip

    def deploys(self, tenant: str, service: str | None, start: datetime, end: datetime) -> list[Row]: ...

    def edges(self, tenant: str, start: datetime, end: datetime) -> list[tuple[str, str, int]]: ...


def _utc(v: Any) -> Any:
    return v.replace(tzinfo=UTC) if isinstance(v, datetime) and v.tzinfo is None else v


def _dicts(result: Any) -> list[Row]:
    cols = list(result.column_names)
    return [{c: _utc(v) for c, v in zip(cols, r, strict=True)} for r in result.result_rows]


class ClickHouseBackend:
    def __init__(self, ch: Client):
        self.ch = ch

    def _q(self, sql: str, params: dict[str, Any]) -> list[Row]:
        return _dicts(self.ch.query(sql, parameters=params))

    def metrics(self, tenant: str, services: list[str], metrics: list[str], start: datetime, end: datetime,
                labels: dict[str, str], limit: int) -> list[Row]:  # fmt: skip
        keys, values = sorted(labels), [labels[k] for k in sorted(labels)]
        return self._q(
            "SELECT service, metric, labels, ts, value, toString(point_id) AS point_id FROM metrics "
            "WHERE tenant_id = {t:String} AND service IN {s:Array(String)} AND metric IN {m:Array(String)} "
            "AND ts >= {a:DateTime64(3)} AND ts <= {b:DateTime64(3)} "
            "AND arrayAll((k, v) -> labels[k] = v, {lk:Array(String)}, {lv:Array(String)}) "
            "ORDER BY ts, point_id LIMIT 1 BY point_id LIMIT {n:UInt32}",
            {"t": tenant, "s": services, "m": metrics, "a": start, "b": end, "lk": keys, "lv": values, "n": limit},
        )

    def logs(self, tenant: str, service: str, start: datetime, end: datetime, severity: str | None,
             contains: str | None, trace_id: str | None, limit: int) -> list[Row]:  # fmt: skip
        return self._q(
            "SELECT service, ts, severity, body, trace_id, span_id, attrs, toString(log_id) AS log_id FROM logs "
            "WHERE tenant_id = {t:String} AND service = {s:String} "
            "AND ts >= {a:DateTime64(3)} AND ts <= {b:DateTime64(3)} "
            "AND ({sev:String} = '' OR severity = {sev:String}) "
            "AND ({c:String} = '' OR positionCaseInsensitiveUTF8(body, {c:String}) > 0) "
            "AND ({tr:String} = '' OR trace_id = {tr:String}) "
            "ORDER BY ts, log_id LIMIT 1 BY log_id LIMIT {n:UInt32}",
            {"t": tenant, "s": service, "a": start, "b": end, "sev": severity or "", "c": contains or "",
             "tr": trace_id or "", "n": limit},
        )  # fmt: skip

    def spans(self, tenant: str, services: list[str], trace_id: str | None, start: datetime, end: datetime,
              min_duration_ms: float | None, limit: int) -> list[Row]:  # fmt: skip
        return self._q(
            "SELECT trace_id, span_id, parent_span_id, service, name, start_ts, duration_ms, status, attrs "
            "FROM spans WHERE tenant_id = {t:String} AND service IN {s:Array(String)} "
            "AND start_ts >= {a:DateTime64(3)} AND start_ts <= {b:DateTime64(3)} "
            "AND ({tr:String} = '' OR trace_id = {tr:String}) AND duration_ms >= {d:Float64} "
            "ORDER BY start_ts, trace_id, span_id LIMIT 1 BY trace_id, span_id LIMIT {n:UInt32}",
            {"t": tenant, "s": services, "a": start, "b": end, "tr": trace_id or "", "d": min_duration_ms or 0.0,
             "n": limit},
        )  # fmt: skip

    def deploys(self, tenant: str, service: str | None, start: datetime, end: datetime) -> list[Row]:
        from common import deploys

        return deploys.recent(self.ch, tenant, start, end, service)  # the one deploy code path (A9)

    def edges(self, tenant: str, start: datetime, end: datetime) -> list[tuple[str, str, int]]:
        rows = self.ch.query(
            "SELECT parent_service, child_service, toUInt64(uniqExactMerge(calls)) FROM service_edges "
            "WHERE tenant_id = {t:String} AND bucket >= toStartOfFiveMinutes({a:DateTime64(3)}) "
            "AND bucket <= {b:DateTime64(3)} GROUP BY parent_service, child_service ORDER BY 1, 2",
            parameters={"t": tenant, "a": start, "b": end},
        ).result_rows
        return [(str(p), str(c), int(n)) for p, c, n in rows]


def _bucket(t: datetime) -> datetime:
    """toStartOfFiveMinutes."""
    return t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)


def _in(t: datetime, a: datetime, b: datetime) -> bool:
    return a <= t <= b


class OfflineBackend:
    """A fixture's tables (as recorder.dataset.read_parquet returns them), filtered in Python."""

    def __init__(self, tables: dict[str, list[Row]]):
        self.t = tables

    def metrics(self, tenant: str, services: list[str], metrics: list[str], start: datetime, end: datetime,
                labels: dict[str, str], limit: int) -> list[Row]:  # fmt: skip
        rows = [r for r in self.t["metrics"] if r["tenant_id"] == tenant and r["service"] in services
                and r["metric"] in metrics and _in(r["ts"], start, end)
                and all(r["labels"].get(k) == v for k, v in labels.items())]  # fmt: skip
        rows = _first_by(sorted(rows, key=lambda r: (r["ts"], str(r["point_id"]))), lambda r: str(r["point_id"]))
        cols = ("service", "metric", "labels", "ts", "value")
        return [{**{c: r[c] for c in cols}, "point_id": str(r["point_id"])} for r in rows[:limit]]

    def logs(self, tenant: str, service: str, start: datetime, end: datetime, severity: str | None,
             contains: str | None, trace_id: str | None, limit: int) -> list[Row]:  # fmt: skip
        c = (contains or "").lower()
        rows = [r for r in self.t["logs"] if r["tenant_id"] == tenant and r["service"] == service
                and _in(r["ts"], start, end) and (not severity or r["severity"] == severity)
                and c in r["body"].lower() and (not trace_id or r["trace_id"] == trace_id)]  # fmt: skip
        rows = _first_by(sorted(rows, key=lambda r: (r["ts"], str(r["log_id"]))), lambda r: str(r["log_id"]))
        cols = ("service", "ts", "severity", "body", "trace_id", "span_id", "attrs")
        return [{**{k: r[k] for k in cols}, "log_id": str(r["log_id"])} for r in rows[:limit]]

    def spans(self, tenant: str, services: list[str], trace_id: str | None, start: datetime, end: datetime,
              min_duration_ms: float | None, limit: int) -> list[Row]:  # fmt: skip
        rows = [r for r in self.t["spans"] if r["tenant_id"] == tenant and r["service"] in services
                and _in(r["start_ts"], start, end) and (not trace_id or r["trace_id"] == trace_id)
                and r["duration_ms"] >= (min_duration_ms or 0.0)]  # fmt: skip
        key = lambda r: (r["start_ts"], r["trace_id"], r["span_id"])  # noqa: E731
        rows = _first_by(sorted(rows, key=key), lambda r: (r["trace_id"], r["span_id"]))
        cols = (
            "trace_id",
            "span_id",
            "parent_span_id",
            "service",
            "name",
            "start_ts",
            "duration_ms",
            "status",
            "attrs",
        )
        return [{k: r[k] for k in cols} for r in rows[:limit]]

    def deploys(self, tenant: str, service: str | None, start: datetime, end: datetime) -> list[Row]:
        rows = [r for r in self.t["deploys"] if r["tenant_id"] == tenant and _in(r["finished_at"], start, end)
                and (service is None or r["service"] == service)]  # fmt: skip
        return _first_by(sorted(rows, key=lambda r: (r["finished_at"], r["id"])), lambda r: r["id"])

    def edges(self, tenant: str, start: datetime, end: datetime) -> list[tuple[str, str, int]]:
        """As the service_edges view derives them: one edge per CLIENT span naming its callee, counted
        exactly, over every span whose 5-minute bucket overlaps the window (so a span in the last
        bucket counts even when it starts after `end`, as ClickHouse's bucket filter has it; A33)."""
        lo = _bucket(start)
        calls: dict[tuple[str, str], set[str]] = defaultdict(set)
        for s in self.t["spans"]:
            if (
                s["tenant_id"] != tenant
                or s["attrs"].get("span.kind") != "CLIENT"
                or not lo <= _bucket(s["start_ts"]) <= end
            ):
                continue
            child = s["attrs"].get("peer.service") or s["attrs"].get("server.address", "")
            if child and child != s["service"]:
                calls[(s["service"], child)].add(s["span_id"])
        return [(p, c, len(ids)) for (p, c), ids in sorted(calls.items())]


def _first_by(rows: list[Row], key: Any) -> list[Row]:
    seen: set[Any] = set()
    out = []
    for r in rows:
        k = key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out

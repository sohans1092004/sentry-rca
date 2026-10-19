"""Tool-Execution Layer (SPEC §5): six read-only tools, scope enforced before execution, every row with
a row_id, every result snapshotted and audited before it is returned.

execute() is pure (arguments -> decision, executed request, rows). ToolLayer adds what must never be
skipped: the snapshot and the tool_calls row are written first, then the rows are returned, exactly as
stored. A per-investigation cache keyed by the executed request avoids re-running identical queries;
a resumed investigation reuses its persisted calls instead of writing them twice.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import psycopg

from investigation import snapshots, timeline
from investigation.backend import Backend, Row
from investigation.scope import MAX_TOP_K, Scope, iso, parse

LOG_BODY_MAX = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# tool -> (required args, optional args)
TOOLS: dict[str, tuple[set[str], set[str]]] = {
    "get_incident_timeline": ({"services", "start", "end"}, set()),
    "query_metrics": ({"service", "metric", "start", "end"}, {"labels"}),
    "query_logs": ({"service", "start", "end"}, {"severity", "contains", "trace_id", "limit"}),
    "query_traces": ({"start", "end"}, {"trace_id", "service", "min_duration_ms", "limit"}),
    "get_recent_deploys": ({"service", "start", "end"}, set()),
    "search_runbooks": ({"query"}, {"top_k"}),
}
TENANT_ARGS = {"tenant", "tenant_id"}


class RunbookIndex(Protocol):
    def search(self, tenant: str, query: str, top_k: int, exclude_fixture: str | None) -> list[Row]: ...


class Rejected(Exception):
    pass


@dataclass
class Decision:
    decision: str  # allowed | clamped | rejected
    reason: str | None
    executed: dict[str, Any] | None
    rows: list[Row] = field(default_factory=list)
    truncated: bool = False


def _check_services(scope: Scope, services: list[str]) -> None:
    outside = [s for s in services if s not in scope.services]
    if outside:
        raise Rejected(f"service {', '.join(outside)} outside scope {list(scope.services)}")


def _window(scope: Scope, args: dict[str, Any], clamps: list[str]) -> tuple[datetime, datetime]:
    try:
        start, end = parse(args["start"]), parse(args["end"])
    except (TypeError, ValueError) as e:
        raise Rejected(f"bad time: {e}") from e
    if start > end:
        raise Rejected("start is after end")
    if end < scope.start or start > scope.end:
        raise Rejected(f"window {iso(start)}..{iso(end)} entirely outside scope {iso(scope.start)}..{iso(scope.end)}")
    if start < scope.start:
        start = scope.start
        clamps.append("start")
    if end > scope.end:
        end = scope.end
        clamps.append("end")
    return start, end


def _limit(scope: Scope, args: dict[str, Any], key: str, cap: int, clamps: list[str]) -> int:
    n = args.get(key, cap)
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise Rejected(f"{key} must be a positive integer")
    if n > cap:
        clamps.append(key)
        return cap
    return n


def _clean_log(r: Row) -> Row:
    body = _CONTROL.sub("", r["body"])[:LOG_BODY_MAX]
    return {**r, "body": body, "row_id": r["log_id"]}


def prepare(scope: Scope, tool: str, args: dict[str, Any], has_runbooks: bool = True) -> Decision:
    """Scope enforcement only: validate, reject or clamp, and return the request that will run."""
    clamps: list[str] = []
    try:
        if tool not in TOOLS:
            raise Rejected(f"unknown tool {tool}")
        required, optional = TOOLS[tool]
        given = set(args) - TENANT_ARGS
        if missing := required - given:
            raise Rejected(f"missing argument {sorted(missing)}")
        if unknown := given - required - optional:
            raise Rejected(f"unknown argument {sorted(unknown)}")
        for k in TENANT_ARGS & set(args):
            if str(args[k]) != scope.tenant_id:
                raise Rejected(f"tenant {args[k]} is not this investigation's tenant")
        if tool == "search_runbooks":
            if not has_runbooks:
                raise Rejected("no runbook index")
            top_k = _limit(scope, args, "top_k", MAX_TOP_K, clamps)
            executed: dict[str, Any] = {"query": str(args["query"]), "top_k": top_k}
            return Decision("clamped" if clamps else "allowed", None, executed)
        start, end = _window(scope, args, clamps)
        executed = {"start": iso(start), "end": iso(end)}
        if tool == "get_incident_timeline":
            services = sorted(set(args["services"])) if isinstance(args["services"], list) else []
            if not services:
                raise Rejected("services must be a non-empty list")
            _check_services(scope, services)
            executed["services"] = services
        elif tool == "query_metrics":
            _check_services(scope, [args["service"]])
            labels = args.get("labels") or {}
            if not isinstance(labels, dict):
                raise Rejected("labels must be an object")
            executed |= {"service": args["service"], "metric": args["metric"], "labels": dict(sorted(labels.items()))}
        elif tool == "query_logs":
            _check_services(scope, [args["service"]])
            executed |= {
                "service": args["service"],
                "limit": _limit(scope, args, "limit", scope.max_rows, clamps),
                **{k: args[k] for k in ("severity", "contains", "trace_id") if args.get(k)},
            }
        elif tool == "query_traces":
            services = list(scope.services)
            if args.get("service"):
                _check_services(scope, [args["service"]])
                services = [args["service"]]
            executed |= {
                "services": services,
                "limit": _limit(scope, args, "limit", scope.max_rows, clamps),
                **{k: args[k] for k in ("trace_id", "min_duration_ms") if args.get(k) is not None},
            }
        else:  # get_recent_deploys
            _check_services(scope, [args["service"]])
            executed["service"] = args["service"]
        return Decision("clamped" if clamps else "allowed", None, executed)
    except Rejected as e:
        return Decision("rejected", str(e), None)
    except (KeyError, TypeError) as e:
        return Decision("rejected", f"bad argument: {e}", None)


def fetch(
    backend: Backend, runbooks: RunbookIndex | None, scope: Scope, tool: str, ex: dict[str, Any]
) -> tuple[list[Row], bool]:
    """Run an already-prepared request: (rows with row_id, truncated). The tenant is always the scope's."""
    t = scope.tenant_id
    if tool == "search_runbooks":
        assert runbooks is not None
        return runbooks.search(t, ex["query"], ex["top_k"], scope.excluded_fixture), False
    start, end = parse(ex["start"]), parse(ex["end"])
    limit = ex.get("limit", scope.max_rows)
    if tool == "get_incident_timeline":
        rows = timeline.build(backend, t, ex["services"], start, end)
    elif tool == "query_metrics":
        rows = [
            {**r, "row_id": r["point_id"]}
            for r in backend.metrics(t, [ex["service"]], [ex["metric"]], start, end, ex["labels"], limit + 1)
        ]
    elif tool == "query_logs":
        rows = [
            _clean_log(r)
            for r in backend.logs(
                t, ex["service"], start, end, ex.get("severity"), ex.get("contains"), ex.get("trace_id"), limit + 1
            )
        ]
    elif tool == "query_traces":
        rows = [
            {**r, "row_id": r["span_id"]}
            for r in backend.spans(
                t, ex["services"], ex.get("trace_id"), start, end, ex.get("min_duration_ms"), limit + 1
            )
        ]
    else:
        rows = [{**r, "row_id": r["id"]} for r in backend.deploys(t, ex["service"], start, end)]
    return rows[:limit], len(rows) > limit


def execute(backend: Backend, runbooks: RunbookIndex | None, scope: Scope, tool: str, args: dict[str, Any]) -> Decision:
    """prepare + fetch. Never raises for a bad request: it is rejected."""
    d = prepare(scope, tool, args, runbooks is not None)
    if d.executed is not None:
        d.rows, d.truncated = fetch(backend, runbooks, scope, tool, d.executed)
    return d


# --- persistence -------------------------------------------------------------------------------


@dataclass
class CallRecord:
    id: str
    seq: int
    ranker: str
    tool_name: str
    scope_decision: str
    requested: dict[str, Any]
    executed: dict[str, Any] | None
    reason: str | None
    snapshot_id: str | None
    rows: list[Row]  # as stored in the snapshot (empty when rejected)
    truncated: bool


class Store(Protocol):
    def record(
        self, investigation_id: str, rec: CallRecord, snap: snapshots.Snapshot | None, duration_ms: int
    ) -> None: ...

    def calls(self, investigation_id: str) -> dict[int, CallRecord]: ...


class PgStore:
    def __init__(self, conn: psycopg.Connection[Any]):
        self.conn = conn

    def record(self, investigation_id: str, rec: CallRecord, snap: snapshots.Snapshot | None, duration_ms: int) -> None:
        with self.conn.transaction():
            if snap is not None:
                snapshots.store(self.conn, snap)
            self.conn.execute(
                "INSERT INTO tool_calls (id, investigation_id, ranker, seq, tool_name, request_requested, "
                "request_executed, scope_decision, rejection_reason, snapshot_id, duration_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (rec.id, investigation_id, rec.ranker, rec.seq, rec.tool_name, json.dumps(rec.requested),
                 json.dumps(rec.executed) if rec.executed is not None else None, rec.scope_decision, rec.reason,
                 rec.snapshot_id, duration_ms),
            )  # fmt: skip

    def calls(self, investigation_id: str) -> dict[int, CallRecord]:
        rows = self.conn.execute(
            "SELECT id::text, seq, ranker, tool_name, request_requested, request_executed, scope_decision, "
            "rejection_reason, snapshot_id FROM tool_calls WHERE investigation_id = %s ORDER BY seq",
            (investigation_id,),
        ).fetchall()
        out = {}
        for cid, seq, ranker, tool, req, exe, dec, reason, sid in rows:
            snap = snapshots.load(self.conn, sid) if sid else None
            out[seq] = CallRecord(cid, seq, ranker, tool, dec, req, exe, reason, sid,
                                  snap.rows if snap else [], snap.truncated if snap else False)  # fmt: skip
        return out


class MemoryStore:
    """In-process store with the same rules (unique seq, append-only), for unit tests."""

    def __init__(self) -> None:
        self.snaps: dict[str, snapshots.Snapshot] = {}
        self.by_inv: dict[str, dict[int, CallRecord]] = {}

    def record(self, investigation_id: str, rec: CallRecord, snap: snapshots.Snapshot | None, duration_ms: int) -> None:
        calls = self.by_inv.setdefault(investigation_id, {})
        if rec.seq in calls:
            raise ValueError(f"duplicate tool call seq {rec.seq}")
        if snap is not None:
            self.snaps.setdefault(snap.id, snap)
        calls[rec.seq] = rec

    def calls(self, investigation_id: str) -> dict[int, CallRecord]:
        return dict(self.by_inv.get(investigation_id, {}))


class ToolLayer:
    """One per (investigation, ranker). Calls are numbered in issue order; seq is unique per
    investigation, so a second ranker in the same investigation continues the numbering."""

    def __init__(self, store: Store, backend: Backend, runbooks: RunbookIndex | None, investigation_id: str,
                 scope: Scope, ranker: str):  # fmt: skip
        self.store, self.backend, self.runbooks = store, backend, runbooks
        self.investigation_id, self.scope, self.ranker = investigation_id, scope, ranker
        prior = store.calls(investigation_id)
        self.mine = sorted((r for r in prior.values() if r.ranker == ranker), key=lambda r: r.seq)
        self.next_seq = max(prior, default=0) + 1
        self.issued = 0
        self.cache: dict[bytes, CallRecord] = {}
        self.calls_made = 0

    def call(self, tool: str, args: dict[str, Any]) -> CallRecord:
        requested = {"tool": tool, "args": args}
        if self.issued < len(self.mine):  # resuming: this call was persisted before a restart
            rec = self.mine[self.issued]
            self.issued += 1
            if rec.requested != json.loads(snapshots.canonical(requested)):
                raise RuntimeError(f"resume diverged at seq {rec.seq}: the ranker is not deterministic")
            return rec
        self.issued += 1
        t0 = time.monotonic()
        d = prepare(self.scope, tool, args, self.runbooks is not None)
        snap: snapshots.Snapshot | None = None
        snapshot_id, rows, truncated = None, [], False
        key = snapshots.canonical({"tool": tool, **d.executed}) if d.executed is not None else b""
        if d.executed is not None and (hit := self.cache.get(key)) is not None:
            snapshot_id, rows, truncated = hit.snapshot_id, hit.rows, hit.truncated  # already stored
        elif d.executed is not None:
            d.rows, d.truncated = fetch(self.backend, self.runbooks, self.scope, tool, d.executed)
            snap = snapshots.build(self.scope.tenant_id, d.rows, truncated=d.truncated)
            snapshot_id, rows, truncated = snap.id, json.loads(snap.content)["rows"], snap.truncated
        rec = CallRecord(str(uuid.uuid4()), self.next_seq, self.ranker, tool, d.decision,
                         json.loads(snapshots.canonical(requested)), d.executed, d.reason, snapshot_id, rows,
                         truncated)  # fmt: skip
        # the snapshot and the audit row are written before anything is returned
        self.store.record(self.investigation_id, rec, snap, int((time.monotonic() - t0) * 1000))
        if d.executed is not None:
            self.cache[key] = rec
        self.next_seq += 1
        self.calls_made += 1
        return rec

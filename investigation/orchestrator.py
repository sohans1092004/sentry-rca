"""Investigation orchestrator (SPEC §7.1; Phase 2: baseline only).

Steps, each committed before the next, so a restart resumes instead of starting over:
  1. investigation row, inserted idempotently on (incident_id, trigger_id) (§6, §15 row 4);
  2. scope, computed once and stored (§5.2);
  3. tool calls and snapshots (the tool layer reuses persisted calls on resume, §15 row 12);
  4. hypotheses + claims + citations, verified, in one transaction (append-only tables);
  5. the ranker's result and the investigation's status and outcome.

    python -m investigation.orchestrator        # consume incidents.opened
"""

import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg

from investigation import baseline
from investigation import scope as scope_mod
from investigation.backend import Backend
from investigation.run import Ranker, RankerResult, run_ranker
from investigation.tools import CallRecord, PgStore, RunbookIndex

RANKER = "baseline"
MAX_CONCURRENT = 2  # §9 max_concurrent_investigations
SLOT_LOCK_BASE = 7_340_100


def _crash_point(name: str) -> None:
    # Test hook: the resume test kills the process exactly here.
    if os.environ.get("SENTRY_CRASH_POINT") == name:
        os._exit(43)


def trigger(conn: psycopg.Connection[Any], event: dict[str, Any], kind: str = "auto") -> tuple[str, bool]:
    """Step 1: (investigation id, created). A redelivered trigger finds the existing investigation."""
    row = conn.execute(
        "INSERT INTO investigations (id, tenant_id, incident_id, trigger_id, trigger_kind, ranker, status, scope) "
        "SELECT %s, tenant_id, id, %s, %s, %s, 'running', '{}' FROM incidents WHERE id = %s "
        "ON CONFLICT (incident_id, trigger_id) DO NOTHING RETURNING id::text",
        (str(uuid.uuid4()), event["trigger_id"], kind, RANKER, event["incident_id"]),
    ).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE incidents SET status = 'investigating' WHERE id = %s AND status = 'open'", (event["incident_id"],)
        )
        return str(row[0]), True
    existing = conn.execute(
        "SELECT id::text FROM investigations WHERE incident_id = %s AND trigger_id = %s",
        (event["incident_id"], event["trigger_id"]),
    ).fetchone()
    if existing is None:
        raise LookupError(f"incident {event['incident_id']} does not exist")
    return str(existing[0]), False


def _scope(
    conn: psycopg.Connection[Any],
    backend: Backend,
    inv_id: str,
    clamp: tuple[datetime, datetime] | None,
    excluded_fixture: str | None,
) -> scope_mod.Scope:
    """Step 2: compute once; later runs reuse the stored scope (the graph may have grown since)."""
    stored, tenant, service, first, last = conn.execute(
        "SELECT i.scope, n.tenant_id::text, n.service, n.first_anomaly_at, n.last_seen FROM investigations i "
        "JOIN incidents n ON n.id = i.incident_id WHERE i.id = %s",
        (inv_id,),
    ).fetchone() or (None, None, None, None, None)
    if stored:
        return scope_mod.Scope.from_json(stored)
    incident = {"tenant_id": tenant, "service": service, "first_anomaly_at": first, "last_seen": last}
    sc = scope_mod.compute(backend, incident, clamp=clamp, excluded_fixture=excluded_fixture)
    conn.execute("UPDATE investigations SET scope = %s WHERE id = %s", (json.dumps(sc.to_json()), inv_id))
    return sc


def _persist_hypotheses(
    conn: psycopg.Connection[Any], inv_id: str, result: RankerResult, calls: dict[int, CallRecord]
) -> None:
    """Step 4, in one transaction; skipped when a previous run already committed it."""
    done = conn.execute(
        "SELECT 1 FROM hypotheses WHERE investigation_id = %s AND ranker = %s LIMIT 1", (inv_id, RANKER)
    ).fetchone()
    if done:
        return
    with conn.transaction():
        for h, v in zip(result.hypotheses, result.verification, strict=True):
            hid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO hypotheses (id, investigation_id, ranker, rank, causal_role, cause_service, cause_kind, "
                "score, narrative, verifier_status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    hid,
                    inv_id,
                    RANKER,
                    h["rank"],
                    h["causal_role"],
                    h["cause_service"],
                    h["cause_kind"],
                    h["score"],
                    h.get("narrative"),
                    v.status,
                ),
            )
            for c, cr in zip(h["claims"], v.claims, strict=True):
                cid = str(uuid.uuid4())
                params = {k: val for k, val in c.items() if k != "cites"}
                conn.execute(
                    "INSERT INTO claims (id, hypothesis_id, ordinal, claim_type, params, verifier_result, "
                    "failure_reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        cid,
                        hid,
                        cr.ordinal,
                        c["type"],
                        json.dumps(params),
                        "passed" if cr.passed else "failed",
                        cr.reason,
                    ),
                )
                merged: dict[str, list[str]] = {}
                for cite in c.get("cites", []):
                    call = calls.get(cite.get("tool_call_seq"))
                    if call is not None:  # a fabricated seq has no row to reference; the failure reason says so
                        merged.setdefault(call.id, []).extend(str(r) for r in cite.get("row_ids", []))
                for call_id, row_ids in merged.items():
                    conn.execute(
                        "INSERT INTO claim_citations (claim_id, tool_call_id, row_ids) VALUES (%s, %s, %s)",
                        (cid, call_id, row_ids),
                    )


def investigate(
    conn: psycopg.Connection[Any],
    backend: Backend,
    runbooks: RunbookIndex | None,
    inv_id: str,
    *,
    clamp: tuple[datetime, datetime] | None = None,
    excluded_fixture: str | None = None,
    rank: Ranker = baseline.rank,
) -> str:
    t0 = time.monotonic()
    done = conn.execute(
        "SELECT outcome FROM investigation_results WHERE investigation_id = %s AND ranker = %s", (inv_id, RANKER)
    ).fetchone()
    if done:
        return str(done[0])
    sc = _scope(conn, backend, inv_id, clamp, excluded_fixture)
    store = PgStore(conn)
    result = run_ranker(store, backend, runbooks, inv_id, sc, RANKER, rank)
    _crash_point("before_hypotheses")
    _persist_hypotheses(conn, inv_id, result, store.calls(inv_id))
    _crash_point("after_hypotheses")
    budget = {"tool_calls": result.tool_calls, "wall_ms": int((time.monotonic() - t0) * 1000)}
    with conn.transaction():
        conn.execute(
            "INSERT INTO investigation_results (investigation_id, ranker, outcome) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (inv_id, RANKER, result.outcome),
        )
        conn.execute(
            "UPDATE investigations SET status = 'complete', outcome = %s, ranker = %s, budget_used = %s, "
            "completed_at = %s WHERE id = %s",
            (result.outcome, RANKER, json.dumps(budget), datetime.now(UTC), inv_id),
        )
    return result.outcome


def acquire_slot(conn: psycopg.Connection[Any], wait_s: float = 0.5) -> int:
    """§9: at most MAX_CONCURRENT investigations at once, across processes (session advisory locks)."""
    while True:
        for slot in range(MAX_CONCURRENT):
            row = conn.execute("SELECT pg_try_advisory_lock(%s)", (SLOT_LOCK_BASE + slot,)).fetchone()
            if row and row[0]:
                return slot
        time.sleep(wait_s)


def release_slot(conn: psycopg.Connection[Any], slot: int) -> None:
    conn.execute("SELECT pg_advisory_unlock(%s)", (SLOT_LOCK_BASE + slot,))


def main() -> None:
    from confluent_kafka import Consumer

    from common import config, db
    from investigation.backend import ClickHouseBackend

    conn = psycopg.connect(os.environ.get("APP_PG_DSN", config.PG_DSN), autocommit=True)
    backend = ClickHouseBackend(db.clickhouse())
    consumer = Consumer(
        {
            "bootstrap.servers": config.KAFKA_BOOTSTRAP,
            "group.id": "sentry-orchestrator",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([config.INCIDENTS_OPENED_TOPIC])
    while True:
        msg = consumer.poll(1.0)
        if msg is None or msg.error() is not None:
            continue
        event = json.loads(msg.value() or b"{}")
        inv_id, created = trigger(conn, event)
        slot = acquire_slot(conn)
        try:
            outcome = investigate(conn, backend, None, inv_id)
        finally:
            release_slot(conn, slot)
        consumer.commit(message=msg, asynchronous=False)  # after the investigation is recorded
        print(
            json.dumps({"event": "investigated", "investigation_id": inv_id, "created": created, "outcome": outcome}),
            flush=True,
        )


if __name__ == "__main__":
    main()

"""Phase 2 against real Postgres (pgvector) and ClickHouse: grants, idempotency, tenant filter in SQL,
snapshots surviving deletion, contamination in SQL, orchestrator resume, eval read-only/hash."""

import contextlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from common.config import DEMO_TENANT_ID
from investigation import orchestrator
from investigation.backend import ClickHouseBackend
from investigation.embeddings import Cassette, _pack
from investigation.runbooks import Doc, PgRunbookIndex, load, query_text
from investigation.scope import Scope, iso
from investigation.tools import PgStore, ToolLayer, execute
from investigation.verifier import verify_claim
from processors.convert import METRIC_COLUMNS
from tests.integration.conftest import ch_client

T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
OTHER = "00000000-0000-4000-8000-0000000000bb"


def app_conn(pg_dsn):
    """The application's role (0005_app_role.sql), on the test's database."""
    dsn = pg_dsn.replace("sentry:sentry@", "sentry_app:sentry_app@")
    return psycopg.connect(dsn, autocommit=True)


def incident(pg, service="gateway"):
    iid = str(uuid.uuid4())
    pg.execute(
        "INSERT INTO incidents (id, tenant_id, fingerprint, service, status, first_anomaly_at, last_seen) "
        "VALUES (%s, %s, %s, %s, 'open', %s, %s)",
        (iid, DEMO_TENANT_ID, f"test:{iid}", service, T0, T0 + timedelta(minutes=2)),
    )
    return iid


def metric_rows(tenant, service, n=12, value=1.0):
    return [
        [tenant, service, "lat", {"route": "/x"}, T0 + timedelta(seconds=5 * i), value + i, uuid.uuid4()]
        for i in range(n)
    ]


# --- append-only grants (§4.2) -------------------------------------------------------------------


def test_app_role_cannot_update_or_delete_audit_rows(pg, pg_dsn):
    iid = incident(pg)
    with app_conn(pg_dsn) as app:
        inv, _ = orchestrator.trigger(app, {"incident_id": iid, "trigger_id": "t"})
        app.execute(
            "INSERT INTO tool_calls (id, investigation_id, ranker, seq, tool_name, request_requested, "
            "scope_decision) VALUES (%s, %s, 'baseline', 1, 'query_logs', '{}', 'allowed')",
            (str(uuid.uuid4()), inv),
        )
        for sql in ("UPDATE tool_calls SET tool_name = 'tampered'", "DELETE FROM tool_calls"):
            with contextlib.suppress(psycopg.errors.InsufficientPrivilege):
                app.execute(sql)
    rows = pg.execute("SELECT tool_name FROM tool_calls").fetchall()
    assert rows == [("query_logs",)], f"the app role changed the audit trail: {rows}"


# --- idempotent investigation insert (§6, §15 row 4) ----------------------------------------------


def test_redelivered_trigger_creates_no_second_investigation(pg, pg_dsn):
    iid = incident(pg)
    with app_conn(pg_dsn) as app:
        a, created_a = orchestrator.trigger(app, {"incident_id": iid, "trigger_id": f"opened:{iid}"})
        b, created_b = orchestrator.trigger(app, {"incident_id": iid, "trigger_id": f"opened:{iid}"})
    n = pg.execute("SELECT count(*) FROM investigations WHERE incident_id = %s", (iid,)).fetchone()[0]
    assert n == 1, f"{n} investigations for one trigger"
    assert a == b and (created_a, created_b) == (True, False)


# --- tenant filter in the real SQL ---------------------------------------------------------------


def test_clickhouse_queries_never_return_another_tenants_rows(ch_db):
    ch, _ = ch_db
    ch.insert(
        "metrics",
        metric_rows(DEMO_TENANT_ID, "orders") + metric_rows(OTHER, "orders", value=1000.0),
        column_names=METRIC_COLUMNS,
    )
    sc = Scope(DEMO_TENANT_ID, "gateway", ("gateway", "orders"), T0 - timedelta(minutes=5), T0 + timedelta(minutes=5))
    d = execute(
        ClickHouseBackend(ch),
        None,
        sc,
        "query_metrics",
        {"service": "orders", "metric": "lat", "start": iso(sc.start), "end": iso(sc.end)},
    )
    assert len(d.rows) == 12 and max(r["value"] for r in d.rows) < 1000, "another tenant's rows came back"


# --- snapshots survive deletion (§4.3) ------------------------------------------------------------


def test_citation_resolves_after_the_telemetry_is_deleted(pg, pg_dsn, ch_db):
    ch, _ = ch_db
    rows = metric_rows(DEMO_TENANT_ID, "orders", n=6, value=10.0)
    rows += [
        [
            DEMO_TENANT_ID,
            "orders",
            "lat",
            {"route": "/x"},
            T0 + timedelta(minutes=2, seconds=5 * i),
            100.0,
            uuid.uuid4(),
        ]
        for i in range(6)
    ]
    ch.insert("metrics", rows, column_names=METRIC_COLUMNS)
    iid = incident(pg)
    sc = Scope(DEMO_TENANT_ID, "gateway", ("gateway", "orders"), T0 - timedelta(minutes=5), T0 + timedelta(minutes=10))
    with app_conn(pg_dsn) as app:
        inv, _ = orchestrator.trigger(app, {"incident_id": iid, "trigger_id": "t"})
        layer = ToolLayer(PgStore(app), ClickHouseBackend(ch), None, inv, sc, "baseline")
        rec = layer.call(
            "query_metrics", {"service": "orders", "metric": "lat", "start": iso(sc.start), "end": iso(sc.end)}
        )
        ch.command("ALTER TABLE metrics DELETE WHERE 1 SETTINGS mutations_sync = 2")
        assert ch.query("SELECT count() FROM metrics").result_rows[0][0] == 0
        claim = {
            "type": "metric_change",
            "service": "orders",
            "metric": "lat",
            "window": [iso(T0 + timedelta(minutes=2)), iso(T0 + timedelta(minutes=3))],
            "direction": "up",
            "min_magnitude": 5.0,
            "cites": [{"tool_call_seq": rec.seq, "row_ids": [r["row_id"] for r in rec.rows]}],
        }
        r = verify_claim(0, claim, PgStore(app).calls(inv), "baseline")
    assert r.passed, f"citation did not resolve after the telemetry was deleted: {r.reason}"


# --- contamination rule in the real SQL (§12.2) ---------------------------------------------------


def _vec(seed):
    import hashlib

    h = hashlib.sha256(seed.encode()).digest()
    return [((h[i % 32] / 255.0) - 0.5) for i in range(768)]


def test_fixtures_own_postmortem_is_not_returned_by_search_runbooks(pg, pg_dsn, tmp_path):
    docs = [
        Doc(str(uuid.uuid4()), "Postmortem: pool_exhaustion_001", "postmortem", "pool_exhaustion_001", "inventory"),
        Doc(str(uuid.uuid4()), "Pool exhaustion", "runbook", None, "pools"),
    ]
    cassette = Cassette(tmp_path / "c.json")
    for d in docs:
        cassette.entries[cassette.key(d.text)] = {"text": d.text, "vector": _pack(_vec(d.title))}
    cassette.entries[cassette.key(query_text("pool"))] = {"text": "q", "vector": _pack(_vec(docs[0].title))}
    load(pg, cassette, DEMO_TENANT_ID, docs)
    with app_conn(pg_dsn) as app:
        index = PgRunbookIndex(app, cassette)
        hits = index.search(DEMO_TENANT_ID, "pool", 5, "pool_exhaustion_001")
        everything = index.search(DEMO_TENANT_ID, "pool", 5, None)
    assert docs[0].id not in [h["doc_id"] for h in hits], "the evaluated fixture's own postmortem was returned"
    assert everything[0]["doc_id"] == docs[0].id and everything[0]["similarity"] == pytest.approx(1.0, abs=1e-6)


# --- orchestrator: kill mid-investigation, resume without duplicates (§15 row 12) -----------------


def test_killed_investigation_resumes_without_duplicating_rows(pg, pg_dsn, ch_db, ch_container):
    ch, name = ch_db
    ch.insert("metrics", metric_rows(DEMO_TENANT_ID, "gateway", n=40), column_names=METRIC_COLUMNS)
    iid = incident(pg)
    with app_conn(pg_dsn) as app:
        inv, _ = orchestrator.trigger(app, {"incident_id": iid, "trigger_id": "t"})
    env = {
        **os.environ,
        "CH_HOST": ch_container.get_container_host_ip(),
        "CH_PORT": str(ch_container.get_exposed_port(8123)),
        "CH_DATABASE": name,
    }
    code = f"""
import psycopg
from common import db
from investigation import orchestrator
from investigation.backend import ClickHouseBackend
conn = psycopg.connect({pg_dsn.replace("sentry:sentry@", "sentry_app:sentry_app@")!r}, autocommit=True)
print(orchestrator.investigate(conn, ClickHouseBackend(db.clickhouse()), None, {inv!r}))
"""
    crashed = subprocess.run(
        [sys.executable, "-c", code],
        env={**env, "SENTRY_CRASH_POINT": "before_hypotheses"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert crashed.returncode == 43, crashed.stderr[-2000:]
    calls_before = pg.execute("SELECT count(*) FROM tool_calls WHERE investigation_id = %s", (inv,)).fetchone()[0]
    assert calls_before > 0
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    calls_after = pg.execute(
        "SELECT count(*), count(DISTINCT seq) FROM tool_calls WHERE investigation_id = %s", (inv,)
    ).fetchone()
    assert calls_after == (calls_before, calls_before), "the resumed run re-wrote tool calls"
    status = pg.execute("SELECT status, outcome FROM investigations WHERE id = %s", (inv,)).fetchone()
    assert status[0] == "complete" and status[1] == done.stdout.strip()
    again = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert again.stdout.strip() == status[1]  # a third run finds it complete and writes nothing
    assert (
        pg.execute("SELECT count(*) FROM investigation_results WHERE investigation_id = %s", (inv,)).fetchone()[0] == 1
    )
    assert (
        pg.execute("SELECT count(*) FROM tool_calls WHERE investigation_id = %s", (inv,)).fetchone()[0] == calls_before
    )


# --- eval databases are read-only, and the hash catches a write (A16) -----------------------------


def test_eval_user_cannot_write(ch_db, ch_container):
    from evals.harness import readonly_client

    ch, name = ch_db
    addr = (ch_container.get_container_host_ip(), int(ch_container.get_exposed_port(8123)))
    ro = readonly_client(ch_client(ch_container), addr, name)
    with pytest.raises(Exception, match="(?i)not enough privileges|ACCESS_DENIED"):
        ro.insert("metrics", metric_rows(DEMO_TENANT_ID, "orders", n=1), column_names=METRIC_COLUMNS)
    assert ro.query("SELECT count() FROM metrics").result_rows[0][0] == 0


def test_eval_fails_when_the_database_changes(pg_dsn, ch_container, tmp_path):
    """Guard check: with write access granted and a tool that writes, the content hash must fail the eval."""
    from evals.harness import EvalFailed, eval_fixture
    from tests.integration.test_recorder import _record, _seed

    admin = ch_client(ch_container)
    src = f"src_{uuid.uuid4().hex[:8]}"
    from common.migrate import migrate_clickhouse

    migrate_clickhouse(admin, src)
    now = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(pg_dsn, autocommit=True) as pg:
        _seed(ch_client(ch_container, src), pg, now)
        dataset = tmp_path / "fx"
        _record(ch_client(ch_container, src), pg, dataset, now)
    window = [iso(now - timedelta(minutes=5)), iso(now + timedelta(minutes=5))]
    (dataset / "label.json").write_text(
        json.dumps(
            {
                "fixture_id": "fx",
                "scenario": "no_fault",
                "root_cause": None,
                "acceptable_alternatives": [],
                "symptom_services": [],
                "expected_outcome": "INSUFFICIENT_EVIDENCE",
                "planted_injection": False,
                "gold_claims": [],
            }
        )
    )
    (dataset / "injection.json").write_text(
        json.dumps(
            {
                "incident": {
                    "service": "gateway",
                    "opened_at": now.isoformat(),
                    "first_anomaly_at": now.isoformat(),
                    "last_seen": now.isoformat(),
                    "alert_count": 1,
                }
            }
        )
    )
    manifest = json.loads((dataset / "manifest.json").read_text())
    (dataset / "manifest.json").write_text(json.dumps({**manifest, "window": window}))

    def writing_ranker(scope, call, runbook_search=True):
        call(
            "get_incident_timeline",
            {"services": list(scope.services), "start": iso(scope.start), "end": iso(scope.end)},
        )
        layer_client = writing_ranker.client  # the eval's own client, as a misbehaving tool would hold it
        layer_client.insert("metrics", metric_rows(DEMO_TENANT_ID, "gateway", n=1), column_names=METRIC_COLUMNS)
        return []

    from evals import harness

    original = harness.readonly_client

    def capture(admin_, addr, database, write=False):
        c = original(admin_, addr, database, write)
        writing_ranker.client = c
        return c

    harness.readonly_client = capture
    addr = (ch_container.get_container_host_ip(), int(ch_container.get_exposed_port(8123)))
    try:
        with app_conn(pg_dsn) as app, pytest.raises(EvalFailed, match="database changed"):
            eval_fixture(dataset, app, admin, addr, str(uuid.uuid4()), 1, rank=writing_ranker, grant_write=True)
    finally:
        harness.readonly_client = original

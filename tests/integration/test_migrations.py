import uuid
from datetime import UTC, datetime

from common import deploys
from common.config import DEMO_TENANT_ID
from common.migrate import migrate_clickhouse, migrate_postgres, move_deploys
from tests.integration.conftest import ch_client


def test_postgres_migrations_rerun_is_noop(pg):
    assert migrate_postgres(pg) == []
    tables = {r[0] for r in pg.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert {"tenants", "incidents", "alert_rules", "fixtures", "schema_migrations"} <= tables
    assert "deploys" not in tables  # moved to ClickHouse (Amendment A9)
    assert pg.execute("SELECT count(*) FROM alert_rules").fetchone() == (1,)


def test_clickhouse_migrations_rerun_is_noop(ch_db, ch_container):
    client, name = ch_db
    assert migrate_clickhouse(ch_client(ch_container), name) == []
    tables = {r[0] for r in client.query("SHOW TABLES").result_rows}
    assert {"metrics", "logs", "spans", "service_edges", "service_edges_mv", "metrics_1h", "deploys"} <= tables


def test_deploys_still_in_postgres_are_copied_to_clickhouse_once(pg, ch_db):
    ch, name = ch_db
    t = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    did = str(uuid.uuid4())
    pg.execute("CREATE TABLE deploys (id UUID PRIMARY KEY, tenant_id UUID NOT NULL, service TEXT NOT NULL, "
               "version TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ NOT NULL)")  # fmt: skip
    pg.execute("INSERT INTO deploys VALUES (%s, %s, 'orders', 'v2', %s, %s)", (did, DEMO_TENANT_ID, t, t))
    assert move_deploys(pg, ch, name) == 1
    assert move_deploys(pg, ch, name) == 1  # a re-run copies again...
    [d] = deploys.recent(ch, DEMO_TENANT_ID, t, t)  # ...and still reads as one deploy
    assert (d["id"], d["service"], d["version"], d["finished_at"]) == (did, "orders", "v2", t)
    pg.execute("DROP TABLE deploys")
    assert move_deploys(pg, ch, name) == 0  # after the drop migration there is nothing to move

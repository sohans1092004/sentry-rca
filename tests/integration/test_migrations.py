from common.migrate import migrate_clickhouse, migrate_postgres
from tests.integration.conftest import ch_client


def test_postgres_migrations_rerun_is_noop(pg):
    assert migrate_postgres(pg) == []
    tables = {r[0] for r in pg.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert {"tenants", "incidents", "alert_rules", "deploys", "fixtures", "schema_migrations"} <= tables
    assert pg.execute("SELECT count(*) FROM alert_rules").fetchone() == (1,)


def test_clickhouse_migrations_rerun_is_noop(ch_db, ch_container):
    client, name = ch_db
    assert migrate_clickhouse(ch_client(ch_container), name) == []
    tables = {r[0] for r in client.query("SHOW TABLES").result_rows}
    assert {"metrics", "logs", "spans", "service_edges", "service_edges_mv", "metrics_1h", "metrics_1h_mv"} <= tables

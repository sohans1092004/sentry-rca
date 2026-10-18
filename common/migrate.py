"""Forward-only migrations for Postgres and ClickHouse; safe to re-run.

    python -m common.migrate            # both stores, from env config
"""

from pathlib import Path

import psycopg
from clickhouse_connect.driver.client import Client

from common import db

MIGRATIONS = Path(__file__).parent / "migrations"


def _files(store: str) -> list[Path]:
    return sorted((MIGRATIONS / store).glob("*.sql"))


def migrate_postgres(conn: psycopg.Connection[tuple[object, ...]]) -> list[str]:
    """Each file runs in its own transaction together with its bookkeeping row."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    applied = []
    for f in _files("postgres"):
        with conn.transaction():
            # The advisory lock makes two concurrent migrators apply each file once.
            conn.execute("SELECT pg_advisory_xact_lock(7340001)")
            row = conn.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (f.stem,)).fetchone()
            if row:
                continue
            conn.execute(f.read_text(encoding="utf-8").encode())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (f.stem,))
            applied.append(f.stem)
    return applied


def clickhouse_statements(f: Path) -> list[str]:
    text = "\n".join(
        line for line in f.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--")
    )
    return [s.strip() for s in text.split(";") if s.strip()]


def migrate_clickhouse(client: Client, database: str) -> list[str]:
    """ClickHouse DDL is not transactional; every statement is IF NOT EXISTS, so a file that
    failed half-way is simply re-run."""
    client.command(f"CREATE DATABASE IF NOT EXISTS `{database}`")
    client.command(
        f"CREATE TABLE IF NOT EXISTS `{database}`.schema_migrations "
        "(version String, applied_at DateTime DEFAULT now()) ENGINE = MergeTree ORDER BY version"
    )
    done = {r[0] for r in client.query(f"SELECT version FROM `{database}`.schema_migrations").result_rows}
    applied = []
    for f in _files("clickhouse"):
        if f.stem in done:
            continue
        for stmt in clickhouse_statements(f):
            client.command(stmt, settings={"database": database})
        client.insert(f"`{database}`.schema_migrations", [[f.stem]], column_names=["version"])
        applied.append(f.stem)
    return applied


def main() -> None:
    from common import config

    with db.postgres() as conn:
        print("postgres applied:", migrate_postgres(conn) or "nothing new")
    client = db.clickhouse(database="default")
    print("clickhouse applied:", migrate_clickhouse(client, config.CH_DATABASE) or "nothing new")


if __name__ == "__main__":
    main()

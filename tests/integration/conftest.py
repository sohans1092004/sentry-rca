"""Testcontainers: one container per store per session; an isolated database/topic per test."""

import uuid

import clickhouse_connect
import psycopg
import pytest
from confluent_kafka.admin import AdminClient, NewTopic
from testcontainers.community.clickhouse import ClickHouseContainer
from testcontainers.community.kafka import RedpandaContainer
from testcontainers.community.postgres import PostgresContainer

from common.migrate import migrate_clickhouse, migrate_postgres

# Same images as deploy/compose.yaml.
PG_IMAGE = "postgres:16.10-alpine"
CH_IMAGE = "clickhouse/clickhouse-server:25.8.33.6"
RP_IMAGE = "redpandadata/redpanda:v25.2.1"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(PG_IMAGE, username="sentry", password="sentry", dbname="sentry") as c:
        yield c


@pytest.fixture(scope="session")
def ch_container():
    with ClickHouseContainer(CH_IMAGE, username="sentry", password="sentry", dbname="sentry") as c:
        yield c


@pytest.fixture(scope="session")
def kafka_bootstrap():
    with RedpandaContainer(RP_IMAGE) as c:
        yield c.get_bootstrap_server()


def _pg_url(c, dbname):
    return f"postgresql://sentry:sentry@{c.get_container_host_ip()}:{c.get_exposed_port(5432)}/{dbname}"


@pytest.fixture
def pg_dsn(pg_container):
    """A fresh, migrated database per test."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_pg_url(pg_container, "sentry"), autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    dsn = _pg_url(pg_container, name)
    with psycopg.connect(dsn, autocommit=True) as conn:
        migrate_postgres(conn)
    yield dsn
    with psycopg.connect(_pg_url(pg_container, "sentry"), autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture
def pg(pg_dsn):
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        yield conn


def ch_client(c, database="default"):
    return clickhouse_connect.get_client(
        host=c.get_container_host_ip(),
        port=int(c.get_exposed_port(8123)),
        username="sentry",
        password="sentry",
        database=database,
    )


@pytest.fixture
def ch_db(ch_container):
    """(client bound to a fresh migrated database, database name)."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    migrate_clickhouse(ch_client(ch_container), name)
    client = ch_client(ch_container, name)
    yield client, name
    ch_client(ch_container).command(f"DROP DATABASE IF EXISTS {name}")


@pytest.fixture
def topics(kafka_bootstrap):
    """Factory: create uniquely named topics, returns their names."""
    admin = AdminClient({"bootstrap.servers": kafka_bootstrap})

    def make(*bases, partitions=3):
        names = [f"{b}.{uuid.uuid4().hex[:8]}" for b in bases]
        for f in admin.create_topics([NewTopic(n, partitions, 1) for n in names]).values():
            f.result(30)
        return names

    return make

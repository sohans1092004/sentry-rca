"""Store connections."""

import clickhouse_connect
import psycopg
from clickhouse_connect.driver.client import Client

from common import config


def clickhouse(database: str | None = None) -> Client:
    return clickhouse_connect.get_client(
        host=config.CH_HOST,
        port=config.CH_PORT,
        username=config.CH_USER,
        password=config.CH_PASSWORD,
        database=config.CH_DATABASE if database is None else database,
    )


def postgres(dsn: str | None = None) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn or config.PG_DSN, autocommit=True)

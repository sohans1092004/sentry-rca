"""The demo Postgres, shared by orders and inventory.

Faults reach it through normal code paths only (Amendment A21):
- slow_query: a lock wait inside the database. A trigger on the target table sleeps while a row in
  `lock_waits` says so; the injector writes that row over its own connection, so the application's
  SQL text and spans are exactly what healthy traffic sends.
- pool_exhaustion: a connection leak. With the fault on, some queries never return their connection
  for a while; the pool (size 10) fills and acquires time out.

Healthy traffic meets the same code paths without touching user requests: inventory's maintenance
task has its own one-connection pool, where a fail-fast acquire times out (the same QueuePool line)
and a reconciliation query runs under a 100 ms statement timeout and is cancelled (the same query
failure line). Cache misses log slow statements."""

import asyncio
import logging
import os
import random
import time
from typing import Any

import asyncpg
from opentelemetry import metrics

from services.faults import Faults

DSN = os.environ.get("DEMO_DB_DSN", "postgresql://demo:demo@localhost:5433/demo")
POOL_SIZE = 10
ACQUIRE_TIMEOUT_S = 0.5
STATEMENT_TIMEOUT_MS = 2000
SLOW_STATEMENT_MS = 200  # like Postgres log_min_duration_statement
log = logging.getLogger("db")

LOCK_WAITS = """
CREATE TABLE IF NOT EXISTS lock_waits (
  tbl TEXT NOT NULL, op TEXT NOT NULL, delay_ms INT NOT NULL, until TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (tbl, op));
CREATE OR REPLACE FUNCTION lock_wait() RETURNS trigger AS $$
DECLARE d INT;
BEGIN
  SELECT delay_ms INTO d FROM lock_waits WHERE tbl = TG_TABLE_NAME AND op = TG_OP AND until > clock_timestamp();
  IF d IS NOT NULL THEN PERFORM pg_sleep(d / 1000.0); END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
"""


def lock_wait_trigger(table: str) -> str:
    return f"CREATE OR REPLACE TRIGGER {table}_lock_wait BEFORE INSERT OR UPDATE ON {table} " \
           "FOR EACH ROW EXECUTE FUNCTION lock_wait();"  # fmt: skip


class PoolTimeout(Exception):
    pass


class Db:
    def __init__(self, faults: Faults, size: int = POOL_SIZE, statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
                 instrumented: bool = True):  # fmt: skip
        self.faults = faults
        self.pool: asyncpg.Pool | None = None
        self.size = size
        self.statement_timeout_ms = statement_timeout_ms
        self.in_use = 0
        meter = metrics.get_meter("sentry.demo")
        self.wait_ms = meter.create_histogram("db.pool.wait", unit="ms", description="time to acquire a connection")
        if instrumented:  # one pool gauge per service: the maintenance pool is not the service's pool
            meter.create_observable_gauge(
                "db.pool.in_use", [lambda _o: [metrics.Observation(self.in_use, {"pool.size": str(self.size)})]]
            )

    async def _pool(self) -> asyncpg.Pool:
        settings = {"statement_timeout": str(self.statement_timeout_ms)}
        return await asyncpg.create_pool(DSN, min_size=min(2, self.size), max_size=self.size, server_settings=settings)

    async def connect(self) -> None:
        """A pool without schema work (the service's main Db creates the schema)."""
        self.pool = await self._pool()

    async def start(self, schema: str, tables: list[str]) -> None:
        for attempt in range(30):
            try:
                self.pool = await self._pool()
                break
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(1 + attempt * 0.2)
        assert self.pool is not None, "demo database unreachable"
        async with self.pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(42)")
            try:
                await conn.execute(schema + LOCK_WAITS + "".join(lock_wait_trigger(t) for t in tables))
            finally:
                await conn.execute("SELECT pg_advisory_unlock(42)")

    async def set_statement_timeout(self, ms: int) -> None:
        """New connections get the new setting; the old pool drains in the background."""
        if ms != self.statement_timeout_ms and self.pool is not None:
            old, self.statement_timeout_ms = self.pool, ms
            self.pool = await self._pool()
            asyncio.get_running_loop().create_task(old.close())

    async def run(self, name: str, sql: str, *args: Any, fetch: bool = True,
                  acquire_timeout_s: float = ACQUIRE_TIMEOUT_S) -> Any:  # fmt: skip
        pool = self.pool  # release to the pool we acquired from, even if it is replaced meanwhile
        assert pool is not None
        t0 = time.monotonic()
        try:
            conn = await pool.acquire(timeout=acquire_timeout_s)
        except TimeoutError as e:
            self.wait_ms.record((time.monotonic() - t0) * 1000, {"query": name})
            log.error("QueuePool limit of size %d overflow 0 reached, connection timed out, timeout %.2f",
                      self.size, acquire_timeout_s)  # fmt: skip
            raise PoolTimeout(name) from e
        self.wait_ms.record((time.monotonic() - t0) * 1000, {"query": name})
        self.in_use += 1
        held_s = 0.0
        if (leak := self.faults.get("conn_leak")) is not None and random.random() < leak["p"]:
            held_s = leak["hold_s"]  # this code path forgets the connection until a sweep reclaims it
        try:
            q0 = time.monotonic()
            try:
                result = await (conn.fetch(sql, *args) if fetch else conn.execute(sql, *args))
            except asyncpg.PostgresError as e:
                log.error("query %s failed: %s: %s", name, type(e).__name__, e)
                raise
            if (ms := (time.monotonic() - q0) * 1000) >= SLOW_STATEMENT_MS:
                log.warning("duration: %.3f ms  statement: %s", ms, " ".join(sql.split()))
            return result
        finally:
            if held_s:
                asyncio.get_running_loop().create_task(self._release_later(pool, conn, held_s))
            else:
                self.in_use -= 1
                await pool.release(conn)

    async def _release_later(self, pool: asyncpg.Pool, conn: Any, after_s: float) -> None:
        await asyncio.sleep(after_s)
        self.in_use -= 1
        await pool.release(conn)

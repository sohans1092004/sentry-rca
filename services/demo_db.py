"""The demo Postgres, shared by orders and inventory, with the DB-level faults: slow_query (a
pg_sleep before one named query) and pool_exhaustion (the pool shrunk and every query held)."""

import asyncio
import logging
import os
import time
from typing import Any

import asyncpg
from opentelemetry import metrics

from services.faults import Faults

DSN = os.environ.get("DEMO_DB_DSN", "postgresql://demo:demo@localhost:5433/demo")
POOL_SIZE = 10
ACQUIRE_TIMEOUT_S = 2.0
log = logging.getLogger("db")


class PoolTimeout(Exception):
    pass


class Db:
    def __init__(self, faults: Faults):
        self.faults = faults
        self.pool: asyncpg.Pool | None = None
        self.size = POOL_SIZE
        meter = metrics.get_meter("sentry.demo")
        self.wait_ms = meter.create_histogram("db.pool.wait", unit="ms", description="time to acquire a connection")
        self.in_use = 0
        meter.create_observable_gauge(
            "db.pool.in_use", [lambda _o: [metrics.Observation(self.in_use, {"pool.size": str(self.size)})]]
        )

    async def start(self, schema: str) -> None:
        for attempt in range(30):
            try:
                self.pool = await asyncpg.create_pool(DSN, min_size=2, max_size=self.size)
                break
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(1 + attempt * 0.2)
        assert self.pool is not None, "demo database unreachable"
        async with self.pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(42)")
            try:
                await conn.execute(schema)
            finally:
                await conn.execute("SELECT pg_advisory_unlock(42)")

    async def _right_size(self, want: int) -> None:
        if want != self.size and self.pool is not None:
            old, self.size = self.pool, want
            self.pool = await asyncpg.create_pool(DSN, min_size=1, max_size=want)
            asyncio.get_running_loop().create_task(old.close())
            log.warning("connection pool resized to %d", want)

    async def run(self, name: str, sql: str, *args: Any, fetch: bool = True) -> Any:
        pe = self.faults.get("pool_exhaustion")
        await self._right_size(pe["pool_size"] if pe else POOL_SIZE)
        pool = self.pool  # release to the pool we acquired from, even if it is resized meanwhile
        assert pool is not None
        timeout = pe["acquire_timeout_s"] if pe else ACQUIRE_TIMEOUT_S
        t0 = time.monotonic()
        try:
            conn = await pool.acquire(timeout=timeout)
        except TimeoutError as e:
            self.wait_ms.record((time.monotonic() - t0) * 1000, {"query": name})
            log.error("pool acquire timeout after %.1fs for query %s (pool size %d)", timeout, name, self.size)
            raise PoolTimeout(name) from e
        self.wait_ms.record((time.monotonic() - t0) * 1000, {"query": name})
        self.in_use += 1
        try:
            sq = self.faults.get("slow_query")
            delay_ms = (sq["delay_ms"] if sq and sq["query"] == name else 0) + (pe["query_delay_ms"] if pe else 0)
            if delay_ms:
                await conn.execute("SELECT pg_sleep($1)", delay_ms / 1000)
                if sq and sq["query"] == name and delay_ms >= 200:
                    log.warning("slow query %s took over %d ms", name, delay_ms)
            return await (conn.fetch(sql, *args) if fetch else conn.execute(sql, *args))
        finally:
            self.in_use -= 1
            await pool.release(conn)

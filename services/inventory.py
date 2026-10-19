"""inventory: reads and writes stock in the demo Postgres; confirms holds for payments (A2).

Reservations first check an availability figure kept in an in-process cache (TTL ~15 min, staggered);
a miss runs a reconciliation query that costs ~100-150 ms. A stock import invalidates 1-3 keys now
and then; cache_stampede invalidates all of them every few seconds, so every reservation misses.
Every 5-10 minutes a maintenance task, on its own one-connection pool with a 100 ms statement
timeout, holds its connection while a fail-fast acquire times out, then reconciles one SKU, which
Postgres cancels: healthy traffic logs pool timeouts and statement timeouts from the same code as a
fault would, and no user request waits. (Measured 14:17, 14:51, 15:37 UTC: reconciliation load and
holding the service pool each raised gateway p95 2x for ~30 s and opened an incident.)"""

import asyncio
import contextlib
import logging
import random
import time
import uuid

import asyncpg
from fastapi import HTTPException
from opentelemetry import metrics

from services.base import Service
from services.demo_db import Db, PoolTimeout

SKUS = 100
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS stock (sku TEXT PRIMARY KEY, qty BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS holds (
  id UUID PRIMARY KEY, sku TEXT NOT NULL, qty INT NOT NULL, status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
INSERT INTO stock SELECT 'sku-' || i, 1000000000 FROM generate_series(0, {SKUS - 1}) i ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS holds_sku_created ON holds (sku, created_at);
"""
AVAILABILITY = (
    "SELECT count(*) AS n FROM (SELECT sku FROM holds WHERE sku = $1 ORDER BY created_at DESC LIMIT 1500) a "
    "JOIN (SELECT sku FROM holds WHERE sku = $1 ORDER BY created_at DESC LIMIT 1500) b USING (sku)"
)
CACHE_TTL_S = 900
log = logging.getLogger("inventory")


async def _start(s: Service) -> None:
    await db.start(SCHEMA, ["stock", "holds"])
    asyncio.get_running_loop().create_task(_invalidations())
    await maint.connect()
    asyncio.get_running_loop().create_task(_reconcile())


svc = Service("inventory", _start)
app = svc.app
db = Db(svc.faults)
maint = Db(svc.faults, size=1, statement_timeout_ms=100, instrumented=False)
_cache: dict[str, tuple[float, int]] = {}
cache_requests = metrics.get_meter("sentry.demo").create_counter("cache.requests", description="lookups by result")


def invalidate(keys: list[str]) -> None:
    log.info("availability cache invalidated: %d keys", len(keys))
    for k in keys:
        _cache.pop(k, None)


async def _invalidations() -> None:
    next_import = time.monotonic() + random.uniform(600, 900)
    while True:
        storm = svc.faults.get("cache_stampede")
        await asyncio.sleep(storm["interval_s"] if storm else 1)
        if storm:
            invalidate(list(_cache))
        elif time.monotonic() >= next_import:
            invalidate(random.sample(sorted(_cache), min(len(_cache), random.randint(1, 3))))
            next_import = time.monotonic() + random.uniform(600, 900)


async def _reconcile() -> None:
    while True:
        await asyncio.sleep(random.uniform(300, 600))
        assert maint.pool is not None
        async with maint.pool.acquire():  # its only connection: the next acquire must time out
            with contextlib.suppress(PoolTimeout):
                await maint.run("maintenance", "SELECT 1", acquire_timeout_s=0.05)
        with contextlib.suppress(asyncpg.QueryCanceledError):
            await maint.run("reconcile", AVAILABILITY, f"sku-{random.randrange(SKUS)}")


async def _available(sku: str) -> int:
    now = time.monotonic()
    if (hit := _cache.get(sku)) is not None and hit[0] > now:
        cache_requests.add(1, {"cache": "availability", "result": "hit"})
        return hit[1]
    cache_requests.add(1, {"cache": "availability", "result": "miss"})
    rows = await db.run("availability", AVAILABILITY, sku)
    _cache[sku] = (now + CACHE_TTL_S * random.uniform(0.8, 1.2), int(rows[0]["n"]))
    return int(rows[0]["n"])


@app.post("/reserve")
async def reserve(body: dict[str, object]) -> dict[str, object]:
    sku, qty = str(body["sku"]), int(str(body["qty"]))
    hold_id = uuid.uuid4()
    try:
        await _available(sku)
        rows = await db.run(
            "reserve",
            "WITH s AS (UPDATE stock SET qty = qty - $2 WHERE sku = $1 AND qty >= $2 RETURNING sku) "
            "INSERT INTO holds (id, sku, qty, status) SELECT $3, sku, $2, 'held' FROM s RETURNING id",
            sku, qty, hold_id,
        )  # fmt: skip
    except PoolTimeout as e:
        raise HTTPException(503, "database busy") from e
    if not rows:
        raise HTTPException(404, f"unknown sku {sku}")
    return {"hold_id": str(hold_id)}


@app.post("/holds/confirm")
async def confirm(body: dict[str, object]) -> dict[str, object]:
    try:
        hold_id = uuid.UUID(str(body["hold_id"]))
        rows = await db.run("confirm_hold", "UPDATE holds SET status = 'confirmed' WHERE id = $1 RETURNING id", hold_id)
    except PoolTimeout as e:
        raise HTTPException(503, "database busy") from e
    if not rows:
        raise HTTPException(404, "no such hold")
    return {"confirmed": True}


@app.get("/stock/{sku}")
async def stock(sku: str) -> dict[str, object]:
    try:
        rows = await db.run("get_stock", "SELECT qty FROM stock WHERE sku = $1", sku)
    except PoolTimeout as e:
        raise HTTPException(503, "database busy") from e
    if not rows:
        raise HTTPException(404, f"unknown sku {sku}")
    return {"sku": sku, "qty": rows[0]["qty"]}

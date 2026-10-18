"""inventory: reads and writes stock in the demo Postgres; confirms holds for payments (A2)."""

import logging
import uuid

from fastapi import HTTPException

from services.base import Service
from services.demo_db import Db, PoolTimeout

SKUS = 100
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS stock (sku TEXT PRIMARY KEY, qty BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS holds (
  id UUID PRIMARY KEY, sku TEXT NOT NULL, qty INT NOT NULL, status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
INSERT INTO stock SELECT 'sku-' || i, 1000000000 FROM generate_series(0, {SKUS - 1}) i ON CONFLICT DO NOTHING;
"""
log = logging.getLogger("inventory")


async def _start(s: Service) -> None:
    await db.start(SCHEMA)


svc = Service("inventory", _start)
app = svc.app
db = Db(svc.faults)


@app.post("/reserve")
async def reserve(body: dict[str, object]) -> dict[str, object]:
    sku, qty = str(body["sku"]), int(str(body["qty"]))
    hold_id = uuid.uuid4()
    try:
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

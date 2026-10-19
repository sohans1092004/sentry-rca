"""orders: calls inventory then payments; writes to the demo Postgres (SPEC §3).

Runtime configuration is reloaded every second and each change is logged; a feature flag flips now
and then. config_change sets the database statement timeout to 2 (ms, where 2000 was meant)."""

import asyncio
import logging
import random
import time
import uuid

import httpx
from fastapi import HTTPException

from services.base import Service, url
from services.demo_db import STATEMENT_TIMEOUT_MS, Db, PoolTimeout

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  id UUID PRIMARY KEY, sku TEXT NOT NULL, qty INT NOT NULL, amount NUMERIC NOT NULL,
  hold_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""
log = logging.getLogger("orders")


async def _start(s: Service) -> None:
    await db.start(SCHEMA, ["orders"])
    asyncio.get_running_loop().create_task(_config())


async def _config() -> None:
    current: dict[str, object] = {"db.statement_timeout_ms": STATEMENT_TIMEOUT_MS, "feature.recommendations": "on"}
    next_flip = time.monotonic() + random.uniform(300, 600)
    while True:
        await asyncio.sleep(1)
        want = dict(current)
        cc = svc.faults.get("config_change")
        want["db.statement_timeout_ms"] = cc["statement_timeout_ms"] if cc else STATEMENT_TIMEOUT_MS
        if time.monotonic() >= next_flip:
            want["feature.recommendations"] = "off" if current["feature.recommendations"] == "on" else "on"
            next_flip = time.monotonic() + random.uniform(300, 600)
        changed = [f"{k} {current[k]} -> {v}" for k, v in want.items() if current[k] != v]
        if changed:
            log.info("configuration reloaded: %s", ", ".join(changed))
            current = want
            await db.set_statement_timeout(int(str(current["db.statement_timeout_ms"])))


svc = Service("orders", _start)
app = svc.app
db = Db(svc.faults)


async def _call(service: str, path: str, body: dict[str, object]) -> dict[str, object]:
    try:
        r = await svc.http.post(url(service) + path, json=body)
    except httpx.HTTPError as e:
        log.error("%s call failed: %s", service, type(e).__name__)
        raise HTTPException(502, f"{service} unavailable") from e
    if r.status_code >= 400:
        log.error("%s %s returned %d", service, path, r.status_code)
        raise HTTPException(502 if r.status_code >= 500 else r.status_code, f"{service} failed")
    out: dict[str, object] = r.json()
    return out


@app.post("/orders", status_code=201)
async def create_order(body: dict[str, object]) -> dict[str, object]:
    sku, qty = str(body.get("sku", "")), body["qty"]  # qty is passed on as sent; inventory parses it
    if not sku.startswith("sku-") or float(str(qty)) < 1:
        raise HTTPException(422, "bad order")
    order_id = str(uuid.uuid4())
    hold = await _call("inventory", "/reserve", {"sku": sku, "qty": qty})
    amount = round(float(str(qty)) * 9.99, 2)
    await _call("payments", "/charge", {"order_id": order_id, "amount": amount, "hold_id": hold["hold_id"],
                                        "currency": body.get("currency", "USD")})  # fmt: skip
    try:
        await db.run("insert_order", "INSERT INTO orders (id, sku, qty, amount, hold_id) VALUES ($1, $2, $3, $4, $5)",
                     uuid.UUID(order_id), sku, int(float(str(qty))), amount, uuid.UUID(str(hold["hold_id"])),
                     fetch=False)  # fmt: skip
    except PoolTimeout as e:
        raise HTTPException(503, "database busy") from e
    log.info("order %s created for %s x%d", order_id, sku, qty)
    return {"order_id": order_id, "amount": amount}


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> dict[str, object]:
    try:
        oid = uuid.UUID(order_id)
    except ValueError as e:
        raise HTTPException(404, "no such order") from e
    try:
        rows = await db.run("get_order", "SELECT id, sku, qty, amount FROM orders WHERE id = $1", oid)
    except PoolTimeout as e:
        raise HTTPException(503, "database busy") from e
    if not rows:
        raise HTTPException(404, "no such order")
    r = rows[0]
    return {"order_id": str(r["id"]), "sku": r["sku"], "qty": r["qty"], "amount": float(r["amount"])}

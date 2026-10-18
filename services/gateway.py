"""gateway: public entry; calls orders (SPEC §3)."""

import logging

import httpx
from fastapi import Response

from services.base import Service, url

svc = Service("gateway")
app = svc.app
log = logging.getLogger("gateway")


async def _forward(method: str, path: str, json: object | None = None) -> Response:
    try:
        r = await svc.http.request(method, url("orders") + path, json=json)
    except httpx.HTTPError as e:
        log.error("orders unreachable: %s", type(e).__name__)
        return Response('{"error": "orders unavailable"}', status_code=503, media_type="application/json")
    if r.status_code >= 500:
        log.error("orders returned %d for %s %s", r.status_code, method, path)
    return Response(r.content, status_code=r.status_code, media_type="application/json")


@app.post("/checkout")
async def checkout(body: dict[str, object]) -> Response:
    return await _forward("POST", "/orders", body)


@app.get("/orders/{order_id}")
async def get_order(order_id: str) -> Response:
    return await _forward("GET", f"/orders/{order_id}")

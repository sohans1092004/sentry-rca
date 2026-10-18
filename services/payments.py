"""payments: confirms the inventory hold, then charges a simulated provider; retries both on
failure, which is what turns an inventory pool exhaustion into a retry storm (A2)."""

import asyncio
import hashlib
import logging
import os
import random

import httpx
from fastapi import HTTPException
from opentelemetry import metrics, trace

from services.base import Service, url

RETRIES = 3
svc = Service("payments")
app = svc.app
log = logging.getLogger("payments")
tracer = trace.get_tracer("sentry.demo.payments")
attempts = metrics.get_meter("sentry.demo").create_counter("payments.attempts", description="calls incl. retries")


def _sign(payload: str) -> str:
    # Request signing: a little CPU per attempt, so retries show up as CPU (SPEC §3 retry storm).
    return hashlib.pbkdf2_hmac("sha256", payload.encode(), b"demo-salt", 3000).hex()


async def _with_retries(what: str, call: object) -> None:
    for attempt in range(RETRIES + 1):
        attempts.add(1, {"call": what, "retry": str(attempt > 0).lower()})
        try:
            await call()  # type: ignore[operator]
            return
        except HTTPException:
            raise  # a 4xx answer is final, not a failure to retry
        except Exception as e:
            if attempt == RETRIES:
                log.error("%s failed after %d retries: %s", what, RETRIES, e)
                raise HTTPException(502, f"{what} failed") from e
            log.warning("%s failed (attempt %d), retrying: %s", what, attempt + 1, e)
            await asyncio.sleep(0.05 * 2**attempt)


@app.post("/charge")
async def charge(body: dict[str, object]) -> dict[str, object]:
    async def confirm_hold() -> None:
        _sign(str(body))
        r = await svc.http.post(url("inventory") + "/holds/confirm", json={"hold_id": body["hold_id"]})
        if r.status_code >= 500:
            raise RuntimeError(f"inventory returned {r.status_code}")
        if r.status_code >= 400:
            raise HTTPException(409, "hold not confirmable")

    async def provider_charge() -> None:
        _sign(str(body))
        with tracer.start_as_current_span(
            "provider.charge", kind=trace.SpanKind.CLIENT, attributes={"peer.service": "provider"}
        ) as span:  # fmt: skip
            outage = svc.faults.get("dependency_outage")
            if outage and random.random() < outage["error_rate"]:
                await asyncio.sleep(outage["timeout_ms"] / 1000)
                span.set_status(trace.StatusCode.ERROR, "provider timeout")
                raise TimeoutError("payment provider timed out")
            await asyncio.sleep(max(0.005, random.gauss(0.015, 0.004)))

    try:
        await _with_retries("hold confirmation", confirm_hold)
        await _with_retries("provider charge", provider_charge)
    except httpx.HTTPError as e:
        raise HTTPException(502, "upstream error") from e
    return {"charged": body["amount"], "provider_ref": os.urandom(6).hex()}

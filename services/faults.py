"""Fault switches the injector flips over HTTP (POST/DELETE /_fault), and the request middleware
that applies the generic ones. Every fault expires on its own, so a crashed injector never leaves
the demo system broken."""

import asyncio
import logging
import random
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("faults")


class Faults:
    def __init__(self) -> None:
        self._active: dict[str, tuple[dict[str, Any], float]] = {}

    def get(self, kind: str) -> dict[str, Any] | None:
        entry = self._active.get(kind)
        if entry is None:
            return None
        if time.monotonic() > entry[1]:
            del self._active[kind]
            return None
        return entry[0]

    def set(self, kind: str, params: dict[str, Any], duration_s: float) -> None:
        self._active[kind] = (params, time.monotonic() + duration_s)

    def clear(self) -> None:
        self._active.clear()

    def snapshot(self) -> dict[str, Any]:
        return {k: p for k in list(self._active) if (p := self.get(k)) is not None}


# memory_leak: an unbounded "recent requests" cache that every request scans linearly.
_LEAK: list[dict[str, Any]] = []


async def _plant(faults: Faults, params: dict[str, Any]) -> None:
    """Planted log lines for injection fixtures (SPEC §3): text that names a false cause."""
    lines, i = params["lines"], 0
    while faults.get("plant_logs") is not None:
        log.error(lines[i % len(lines)])
        i += 1
        await asyncio.sleep(params.get("interval_s", 3))


def install(app: FastAPI, faults: Faults, service: str) -> None:
    @app.post("/_fault")
    async def set_fault(body: dict[str, Any]) -> dict[str, Any]:
        kind, params = body["kind"], body.get("params", {})
        faults.set(kind, params, float(body.get("duration_s", 300)))
        if kind == "bad_deploy":
            log.info("deploy finished: %s now running version %s", service, params.get("version"))
        if kind == "plant_logs":
            asyncio.get_running_loop().create_task(_plant(faults, params))
        return faults.snapshot()

    @app.delete("/_fault")
    async def clear_faults() -> dict[str, Any]:
        faults.clear()
        _LEAK.clear()
        return {}

    @app.get("/_fault")
    async def get_faults() -> dict[str, Any]:
        return faults.snapshot()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.middleware("http")
    async def apply_faults(request: Request, call_next: Any) -> Any:
        if request.url.path in ("/_fault", "/healthz"):
            return await call_next(request)
        await asyncio.sleep(random.uniform(0, 0.004))  # harmless background wobble
        if (j := faults.get("jitter")) and random.random() < j["p"]:
            await asyncio.sleep(random.uniform(0, j["max_ms"]) / 1000)
        if (leak := faults.get("memory_leak")) is not None:
            key = random.randrange(1000)
            _LEAK.extend({"k": key, "v": "x" * leak["bytes"]} for _ in range(leak["objects"]))
            sum(1 for e in _LEAK if e["k"] == key)  # the O(n) lookup that makes the leak slow
        elif _LEAK:
            _LEAK.clear()  # fault expired: the "fix" is a restart, which frees the cache
        if (bd := faults.get("bad_deploy")) is not None:
            if bd["mode"] == "errors" and random.random() < bd["error_rate"]:
                log.error("unhandled error in %s %s: KeyError 'currency' (version %s)",
                          request.method, request.url.path, bd["version"])  # fmt: skip
                return JSONResponse({"error": "internal"}, status_code=500)
            if bd["mode"] == "slow":
                await asyncio.sleep(bd["delay_ms"] / 1000)
        return await call_next(request)

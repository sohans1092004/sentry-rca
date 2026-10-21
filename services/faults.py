"""Fault switches the injector flips over HTTP (POST/DELETE /_fault), and the request middleware
that applies the generic ones. Every fault expires on its own, so a crashed injector never leaves
the demo system broken.

Nothing here logs or names a fault (Amendment A21): a fault changes behaviour, and the evidence is
whatever the normal code paths then emit."""

import asyncio
import random
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request


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


# memory_leak: an unbounded "recent requests" cache that every request scans linearly, so latency
# grows with the leak (~64 B per entry; ~1M entries cost tens of ms per scan).
_LEAK: list[tuple[int, int]] = []
# memory_step (a confounder): a one-off allocation held until the fault clears, like a cache warm-up
_BALLAST: list[bytearray] = []


def install(app: FastAPI, faults: Faults, announce: Callable[[str], None]) -> None:
    @app.post("/_fault")
    async def set_fault(body: dict[str, Any]) -> dict[str, Any]:
        kind, params = body["kind"], body.get("params", {})
        faults.set(kind, params, float(body.get("duration_s", 300)))
        if kind in ("bad_deploy", "deploy"):  # a deploy, harmful or not, announces its version the same way
            announce(params["version"])
        if kind == "memory_step":
            _BALLAST.append(bytearray(params["mib"] * 2**20))
        return faults.snapshot()

    @app.delete("/_fault")
    async def clear_faults() -> dict[str, Any]:
        faults.clear()
        _LEAK.clear()
        _BALLAST.clear()
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
            _LEAK.extend((key, i) for i in range(leak["objects"]))
            sum(1 for e in _LEAK if e[0] == key)  # the O(n) lookup that makes the leak slow
        elif _LEAK:
            _LEAK.clear()  # fault expired: the "fix" is a restart, which frees the cache
        if (bd := faults.get("bad_deploy")) is not None:
            if bd["mode"] == "errors" and random.random() < bd["error_rate"]:
                raise KeyError("currency")  # the new version reads a field old clients never send
            if bd["mode"] == "slow":
                await asyncio.sleep(bd["delay_ms"] / 1000)
        return await call_next(request)

"""Common demo-service wiring: telemetry, faults, an HTTP client whose calls carry trace context, and
the request logging every service shares (unhandled exceptions, client errors, deploys)."""

import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from services import faults as faults_mod
from services import telemetry

log = logging.getLogger("http")


def refusing(faults: faults_mod.Faults, host: str) -> bool:
    """Is `host` refusing connections right now? inventory's listener drops out for half a second
    every 20 minutes (a worker restart); the connection_refused fault makes it cycle on and off."""
    if host != "inventory":
        return False
    now = time.time()
    if (f := faults.get("refused")) is not None:
        return bool(now % f["period_s"] < f["on_s"])
    return now % 1200 < 0.5


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, faults: faults_mod.Faults) -> None:
        self.faults, self.inner = faults, httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if refusing(self.faults, request.url.host):
            raise httpx.ConnectError("[Errno 111] Connection refused", request=request)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


class Service:
    def __init__(self, name: str, on_start: Callable[["Service"], Awaitable[None]] | None = None):
        telemetry.setup(name)
        self.name = name
        self.faults = faults_mod.Faults()
        self.http: httpx.AsyncClient

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            self.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0), transport=_Transport(self.faults))
            if on_start:
                await on_start(self)
            yield
            await self.http.aclose()

        self.app = FastAPI(title=name, lifespan=lifespan)
        faults_mod.install(self.app, self.faults, self.announce)

        @self.app.middleware("http")  # added after the fault middleware, so it wraps it
        async def request_log(request: Request, call_next: Any) -> Any:
            if request.url.path in ("/_fault", "/healthz"):
                return await call_next(request)
            try:
                response = await call_next(request)
            except Exception as e:
                log.error("Exception in ASGI application: %s: %s", type(e).__name__, e)
                return JSONResponse({"error": "internal"}, status_code=500)
            if 400 <= response.status_code < 500:
                log.warning("%s %s returned %d", request.method, request.url.path, response.status_code)
            return response

        telemetry.instrument(self.app)

    def announce(self, version: str) -> None:
        log.info("deploy finished: %s now running version %s", self.name, version)


def url(service: str) -> str:
    port = {"orders": 8081, "payments": 8082, "inventory": 8083}[service]
    return os.environ.get(f"{service.upper()}_URL", f"http://{service}:{port}")

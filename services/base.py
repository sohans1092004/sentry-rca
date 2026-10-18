"""Common demo-service wiring: telemetry, faults, an HTTP client whose calls carry trace context."""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from services import faults as faults_mod
from services import telemetry


class Service:
    def __init__(self, name: str, on_start: Callable[["Service"], Awaitable[None]] | None = None):
        telemetry.setup(name)
        self.name = name
        self.faults = faults_mod.Faults()
        self.http: httpx.AsyncClient

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            self.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
            if on_start:
                await on_start(self)
            yield
            await self.http.aclose()

        self.app = FastAPI(title=name, lifespan=lifespan)
        faults_mod.install(self.app, self.faults, name)
        telemetry.instrument(self.app)


def url(service: str) -> str:
    port = {"orders": 8081, "payments": 8082, "inventory": 8083}[service]
    return os.environ.get(f"{service.upper()}_URL", f"http://{service}:{port}")

"""batchjob: a CPU-heavy job pinned to the same cores as payments and inventory (noisy_neighbor,
A3). It emits only its container CPU/memory metrics: no traces connect it to anything."""

import multiprocessing
import time

from fastapi import FastAPI

from services import telemetry

telemetry.setup("batchjob")
app = FastAPI(title="batchjob")
_workers: list[multiprocessing.Process] = []


def _burn(until: float) -> None:
    x = 0
    while time.time() < until:
        x = (x * 31 + 7) % 1_000_003


@app.post("/_fault")
async def start(body: dict[str, object]) -> dict[str, int]:
    params = body.get("params", {})
    assert isinstance(params, dict)
    until = time.time() + float(str(body.get("duration_s", 300)))
    for _ in range(int(params.get("workers", 4))):
        p = multiprocessing.Process(target=_burn, args=(until,), daemon=True)
        p.start()
        _workers.append(p)
    return {"workers": len(_workers)}


@app.delete("/_fault")
async def stop() -> dict[str, int]:
    for p in _workers:
        p.terminate()
    _workers.clear()
    return {"workers": 0}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

"""Traffic generator: Poisson arrivals with a daily-shaped rate, plus harmless background noise
(unknown order lookups -> 404, occasional invalid requests -> 422) so fixtures are never clean, and,
rarely, malformed requests that break each service's parser for real (500s through the same error
handling a bad deploy goes through, Amendment A21).

    python -m services.traffic
"""

import asyncio
import math
import os
import random
import time

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:8080")
BASE_RPS = float(os.environ.get("BASE_RPS", "4"))
DAY_S = float(os.environ.get("DAY_SECONDS", "86400"))
rng = random.Random(int(os.environ.get("TRAFFIC_SEED", "1")))


def rate(t: float) -> float:
    """BASE_RPS +- 40 %: lowest at the start of each 'day', highest half-way through."""
    return BASE_RPS * (1 - 0.4 * math.cos(2 * math.pi * (t % DAY_S) / DAY_S))


async def one(client: httpx.AsyncClient, recent: list[str]) -> None:
    r = rng.random()
    try:
        if r < 0.80:
            resp = await client.post("/checkout", json={"sku": f"sku-{rng.randrange(100)}", "qty": rng.randint(1, 3)})
            if resp.status_code == 201:
                recent.append(resp.json()["order_id"])
                del recent[:-200]
        elif r < 0.97:
            oid = rng.choice(recent) if recent and rng.random() < 0.9 else "00000000-0000-0000-0000-000000000000"
            await client.get(f"/orders/{oid}")
        elif r < 0.997:
            await client.post("/checkout", json={"sku": "bogus", "qty": 0})
        else:  # malformed: no qty (orders), a fractional qty (inventory), an unknown currency (payments)
            sku = f"sku-{rng.randrange(100)}"
            bad = rng.choice([{"sku": sku}, {"sku": sku, "qty": "2.5"}, {"sku": sku, "qty": 1, "currency": "XAU"}])
            await client.post("/checkout", json=bad)
    except httpx.HTTPError:
        pass


async def main() -> None:
    recent: list[str] = []
    tasks: set[asyncio.Task[None]] = set()
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=10) as client:
        while True:
            await asyncio.sleep(rng.expovariate(rate(time.time())))
            t = asyncio.create_task(one(client, recent))
            tasks.add(t)
            t.add_done_callback(tasks.discard)


if __name__ == "__main__":
    asyncio.run(main())

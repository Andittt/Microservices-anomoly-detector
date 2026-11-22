"""Traffic generator: sends checkout requests at a realistic, slowly varying rate.

Requests are fired open-loop (not waiting for the previous one), so a slow
downstream service shows up as higher latency rather than lower traffic.
"""
import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402

from common import config  # noqa: E402


async def fire(client, sem, stats):
    async with sem:
        try:
            r = await client.post(f"{config.CHECKOUT_URL}/checkout", json={})
            stats[r.status_code // 100] = stats.get(r.status_code // 100, 0) + 1
        except httpx.HTTPError:
            stats["conn_err"] = stats.get("conn_err", 0) + 1


async def main(min_rps, max_rps):
    sem = asyncio.Semaphore(300)
    stats = {}
    rate = (min_rps + max_rps) / 2
    target = rate
    next_change = time.time()
    last_report = time.time()
    async with httpx.AsyncClient(timeout=15.0) as client:
        print(f"[traffic] sending to {config.CHECKOUT_URL}/checkout at {min_rps}-{max_rps} req/s", flush=True)
        while True:
            now = time.time()
            if now >= next_change:  # pick a new target load every 20-40 s
                target = random.uniform(min_rps, max_rps)
                next_change = now + random.uniform(20, 40)
            rate += (target - rate) * 0.05  # drift smoothly toward target
            asyncio.create_task(fire(client, sem, stats))
            await asyncio.sleep(random.expovariate(rate))
            if now - last_report > 30:
                print(f"[traffic] ~{rate:.1f} req/s, responses so far: {stats}", flush=True)
                last_report = now


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--min-rps", type=float, default=6)
    p.add_argument("--max-rps", type=float, default=12)
    a = p.parse_args()
    try:
        asyncio.run(main(a.min_rps, a.max_rps))
    except KeyboardInterrupt:
        pass

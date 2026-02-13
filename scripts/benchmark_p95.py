#!/usr/bin/env python3
import asyncio
import time
import statistics
import httpx

BASE = "http://127.0.0.1:8088"
ENDPOINTS = [
    ("/health", {}),
    ("/api/v1/ai/state", {}),
    ("/api/v1/positions/assessment", {}),
    ("/api/v1/macro/risk/overview", {}),
]

REQUESTS_PER_ENDPOINT = 15
CONCURRENCY = 1
TIMEOUT = 30.0

async def hit(client, path, params):
    start = time.perf_counter()
    r = await client.get(f"{BASE}{path}", params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return (time.perf_counter() - start) * 1000

async def run_endpoint(path, params):
    times = []
    errors = []
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bound_call():
        async with sem:
            try:
                t = await hit(client, path, params)
                times.append(t)
            except Exception as e:
                times.append(float("nan"))
                errors.append(repr(e))

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        tasks = [asyncio.create_task(bound_call()) for _ in range(REQUESTS_PER_ENDPOINT)]
        await asyncio.gather(*tasks)

    clean = [t for t in times if t == t]
    if not clean:
        return {"count": 0, "errors": errors[:3]}
    clean.sort()
    p95 = clean[int(0.95 * (len(clean)-1))]
    return {
        "count": len(clean),
        "p50": statistics.median(clean),
        "p95": p95,
        "avg": statistics.mean(clean),
        "min": clean[0],
        "max": clean[-1],
        "errors": errors[:3],
    }

async def main():
    results = {}
    for path, params in ENDPOINTS:
        stats = await run_endpoint(path, params)
        results[path] = stats

    for path, stats in results.items():
        print(path, stats)

if __name__ == "__main__":
    asyncio.run(main())

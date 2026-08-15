"""Timing helper shared by workloads.py and mixed_workload.py."""
from __future__ import annotations

import time
from typing import Any, Callable

from tqdm import tqdm

from bench.models import LatencyStats


def _call_with_retry(fn: Callable[[], Any], attempts: int = 2, backoff_sec: float = 1.0) -> Any:
    """Retry a flaky call before timing it. Retries happen before the timer
    starts for that iteration, so a successful retry gets a clean latency
    reading rather than one inflated by a prior failed attempt + backoff —
    free-tier connections drop essentially at random (observed on CognoDB),
    and a single dropped read shouldn't abort an entire 100-iteration workload.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(backoff_sec)
    raise last_exc  # type: ignore[misc]


def timed_run(fn: Callable[[], Any], iterations: int, warmup: int, desc: str = "") -> LatencyStats:
    """Run fn() `warmup` times (discarded), then `iterations` times, timing each
    call in milliseconds, and return p50/p95 over the timed iterations.
    """
    for _ in tqdm(range(warmup), desc=f"  {desc} warmup", unit="call", leave=False):
        _call_with_retry(fn)

    samples_ms: list[float] = []
    for _ in tqdm(range(iterations), desc=f"  {desc} run", unit="call", leave=False):
        start = time.perf_counter()
        _call_with_retry(fn)
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    return LatencyStats.from_samples_ms(samples_ms, warmup_iterations=warmup)

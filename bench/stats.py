"""Timing helper shared by workloads.py and mixed_workload.py."""
from __future__ import annotations

import time
from typing import Any, Callable

from tqdm import tqdm

from bench.models import LatencyStats, VarianceResult


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

    The very first warmup call is also timed and kept as `cold_ms` — the
    latency spec asks for cold-start numbers to be reported separately
    whenever they're captured, rather than folded into the warmed-up p50/p95.
    """
    cold_ms: float | None = None
    for i in tqdm(range(warmup), desc=f"  {desc} warmup", unit="call", leave=False):
        start = time.perf_counter()
        _call_with_retry(fn)
        elapsed = (time.perf_counter() - start) * 1000.0
        if i == 0:
            cold_ms = elapsed

    samples_ms: list[float] = []
    for _ in tqdm(range(iterations), desc=f"  {desc} run", unit="call", leave=False):
        start = time.perf_counter()
        _call_with_retry(fn)
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    return LatencyStats.from_samples_ms(samples_ms, warmup_iterations=warmup, cold_ms=cold_ms)


def run_variance_check(
    fn: Callable[[], Any],
    description: str,
    repeats: int = 5,
    iterations: int = 30,
    warmup: int = 5,
) -> VarianceResult:
    """Time the same query across several independent warmup+measure passes
    (rather than one pass with many iterations) to see whether the p50 itself
    is stable run-to-run, or drifts with external conditions (cache state,
    network variance, neighboring load on a shared free tier).
    """
    import numpy as np

    run_p50s: list[float] = []
    for _ in tqdm(range(repeats), desc=f"  {description} variance run", unit="run", leave=False):
        stats = timed_run(fn, iterations, warmup, desc=description)
        run_p50s.append(stats.p50_ms)

    arr = np.asarray(run_p50s, dtype=float)
    mean = float(arr.mean())
    stdev = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    cv_pct = (stdev / mean * 100.0) if mean > 0 else 0.0

    return VarianceResult(
        description=description,
        run_p50_ms=run_p50s,
        mean_p50_ms=mean,
        stdev_p50_ms=stdev,
        coefficient_of_variation_pct=cv_pct,
    )

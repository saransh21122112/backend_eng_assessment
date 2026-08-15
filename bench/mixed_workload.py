"""Mixed read/write throughput benchmark: fixed-duration, N concurrent clients.

Satisfies the spec's "sustained queries/second with a stated client
concurrency (e.g. 10-40 concurrent clients) and read/write mix" bullet, plus
the concurrency-sweep strong-submission bullet.
"""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor

from bench.models import MixedWorkloadPoint
from bench.platforms import GraphClient


def _worker(
    client: GraphClient, node_ids: list[str], read_write_ratio: float, deadline: float
) -> tuple[int, int]:
    ops = 0
    errors = 0
    while time.monotonic() < deadline:
        try:
            if random.random() < read_write_ratio:
                client.run_mixed_read(random.choice(node_ids))
            else:
                client.run_mixed_write(random.choice(node_ids), random.choice(node_ids))
            ops += 1
        except Exception:
            errors += 1
    return ops, errors


def run_mixed_workload(
    client: GraphClient,
    node_ids: list[str],
    concurrency: int,
    duration_sec: float,
    read_write_ratio: float = 0.8,
) -> MixedWorkloadPoint:
    start = time.monotonic()
    deadline = start + duration_sec
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_worker, client, node_ids, read_write_ratio, deadline)
            for _ in range(concurrency)
        ]
        results = [f.result() for f in futures]
    actual_elapsed_sec = time.monotonic() - start

    total_ops = sum(ops for ops, _ in results)
    total_errors = sum(errors for _, errors in results)

    return MixedWorkloadPoint(
        concurrency=concurrency,
        read_write_ratio=f"{round(read_write_ratio * 100)}/{round((1 - read_write_ratio) * 100)}",
        throughput_qps=total_ops / actual_elapsed_sec,
        duration_sec=actual_elapsed_sec,
        errors=total_errors,
    )


def run_concurrency_sweep(
    client: GraphClient,
    node_ids: list[str],
    concurrencies: list[int] = [1, 10, 40],
    duration_sec: float = 5.0,
    read_write_ratio: float = 0.8,
) -> list[MixedWorkloadPoint]:
    return [
        run_mixed_workload(client, node_ids, concurrency, duration_sec, read_write_ratio)
        for concurrency in concurrencies
    ]

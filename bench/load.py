"""Bulk-load nodes/edges into a GraphClient and measure ingest throughput.

Schema setup happens before the timer starts — we're measuring insert rate,
not index-build time.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from tqdm import tqdm

from bench.models import LoadResult
from bench.platforms import GraphClient

T = TypeVar("T")


def _batches(rows: list[dict], batch_size: int) -> list[list[dict]]:
    return [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]


def _with_retries(fn: Callable[[], T], attempts: int = 3, backoff_sec: float = 2.0) -> T:
    """Retry a single batch call on transient connection failures.

    Free-tier connections can drop mid-batch essentially at random (observed
    on CognoDB's free c0 tier: roughly 1-in-20-25 requests). This is a
    per-request retry, distinct from the driver's own managed-transaction
    retry inside a single execute_write/execute_read call — that one retries
    within a bounded window before giving up; this one gives a fresh attempt
    (and thus a fresh pooled connection) after that window is exhausted.
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


def load_platform(
    client: GraphClient,
    nodes: list[dict],
    edges: list[dict],
    batch_size: int = 1000,
) -> LoadResult:
    client.ensure_schema()

    start = time.perf_counter()

    node_batches = _batches(nodes, batch_size)
    edge_batches = _batches(edges, batch_size)
    nodes_loaded = sum(
        _with_retries(lambda b=batch: client.load_nodes(b))
        for batch in tqdm(node_batches, desc="  nodes", unit="batch", leave=False)
    )
    relationships_loaded = sum(
        _with_retries(lambda b=batch: client.load_edges(b))
        for batch in tqdm(edge_batches, desc="  edges", unit="batch", leave=False)
    )

    wall_clock_sec = time.perf_counter() - start
    denom = max(wall_clock_sec, 1e-6)

    return LoadResult(
        nodes_loaded=nodes_loaded,
        relationships_loaded=relationships_loaded,
        wall_clock_sec=wall_clock_sec,
        nodes_per_sec=nodes_loaded / denom,
        relationships_per_sec=relationships_loaded / denom,
        load_method=f"driver batch UNWIND/insert_many, batch_size={batch_size}",
    )

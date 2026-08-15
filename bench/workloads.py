"""Read workloads: traversal, point/indexed lookup, aggregation.

Each function wraps `stats.timed_run` and packs the result into the matching
pydantic model from `bench.models`. Random start ids are chosen fresh per
iteration (via `random.choice`) so timings reflect a spread of start nodes,
not one cached hot path. Seed randomness at the call site, not here.
"""
from __future__ import annotations

import random

from bench.models import AggregationResult, LookupKind, LookupResult, TraversalResult
from bench.platforms import GraphClient
from bench.stats import timed_run


def run_traversal_workload(
    client: GraphClient,
    start_ids: list[str],
    hops: int,
    iterations: int = 100,
    warmup: int = 10,
) -> TraversalResult:
    stats = timed_run(
        lambda: client.run_traversal(random.choice(start_ids), hops),
        iterations,
        warmup,
    )
    return TraversalResult(hop_depth=hops, stats=stats)


def run_point_lookup_workload(
    client: GraphClient,
    node_ids: list[str],
    iterations: int = 100,
    warmup: int = 10,
) -> LookupResult:
    stats = timed_run(
        lambda: client.run_point_lookup(random.choice(node_ids)),
        iterations,
        warmup,
    )
    return LookupResult(kind=LookupKind.POINT, indexed_properties=[], stats=stats)


def run_indexed_lookup_workload(
    client: GraphClient,
    age_range: tuple[int, int] = (25, 45),
    iterations: int = 100,
    warmup: int = 10,
) -> LookupResult:
    stats = timed_run(
        lambda: client.run_indexed_lookup(*age_range),
        iterations,
        warmup,
    )
    return LookupResult(kind=LookupKind.INDEXED, indexed_properties=["age"], stats=stats)


def run_aggregation_workload(
    client: GraphClient,
    description: str = "count of FRIEND relationships",
    iterations: int = 100,
    warmup: int = 10,
) -> AggregationResult:
    stats = timed_run(client.run_aggregation, iterations, warmup)
    return AggregationResult(description=description, stats=stats)

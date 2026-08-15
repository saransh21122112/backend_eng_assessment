from __future__ import annotations

from typing import Any

from bench.models import LookupKind, PlatformConfig, PlatformName, QueryDialect
from bench.platforms import GraphClient
from bench.workloads import (
    run_aggregation_workload,
    run_indexed_lookup_workload,
    run_point_lookup_workload,
    run_traversal_workload,
)

_CONFIG = PlatformConfig(
    name=PlatformName.MEMGRAPH,
    uri="bolt://localhost:7687",
    user="",
    password="",
    dialect=QueryDialect.CYPHER,
    advertised_vcpu=0.5,
    advertised_ram_mb=256,
    advertised_disk_gb=1,
    managed=False,
)


class FakeGraphClient(GraphClient):
    def __init__(self):
        super().__init__(_CONFIG)
        self.traversal_calls: list[tuple[str, int]] = []
        self.point_lookup_calls: list[str] = []
        self.indexed_lookup_calls: list[tuple[int, int]] = []
        self.aggregation_calls: int = 0

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def ensure_schema(self) -> list[str]: return []
    def load_nodes(self, nodes: list[dict]) -> int: return 0
    def load_edges(self, edges: list[dict]) -> int: return 0

    def run_traversal(self, start_id: str, hops: int) -> Any:
        self.traversal_calls.append((start_id, hops))
        return None

    def run_point_lookup(self, node_id: str) -> Any:
        self.point_lookup_calls.append(node_id)
        return None

    def run_indexed_lookup(self, min_age: int, max_age: int) -> Any:
        self.indexed_lookup_calls.append((min_age, max_age))
        return None

    def run_aggregation(self) -> Any:
        self.aggregation_calls += 1
        return None

    def run_mixed_read(self, node_id: str) -> Any: return None
    def run_mixed_write(self, src_id: str, dst_id: str) -> Any: return None
    def footprint(self) -> dict[str, float | None]:
        return {"stored_data_mb": None, "memory_mb": None}


def test_run_traversal_workload():
    client = FakeGraphClient()
    start_ids = ["a", "b", "c"]
    result = run_traversal_workload(client, start_ids, hops=2, iterations=20, warmup=2)

    assert result.hop_depth == 2
    assert result.stats.iterations == 20
    assert result.stats.warmup_iterations == 2

    recorded_ids = [sid for sid, _ in client.traversal_calls]
    assert len(client.traversal_calls) == 22  # warmup + iterations
    assert all(sid in start_ids for sid in recorded_ids)
    assert all(hops == 2 for _, hops in client.traversal_calls)
    assert len(set(recorded_ids)) > 1


def test_run_point_lookup_workload():
    client = FakeGraphClient()
    node_ids = ["n1", "n2", "n3"]
    result = run_point_lookup_workload(client, node_ids, iterations=20, warmup=2)

    assert result.kind == LookupKind.POINT
    assert result.indexed_properties == []
    assert result.stats.iterations == 20
    assert result.stats.warmup_iterations == 2
    assert all(nid in node_ids for nid in client.point_lookup_calls)
    assert len(set(client.point_lookup_calls)) > 1


def test_run_indexed_lookup_workload():
    client = FakeGraphClient()
    result = run_indexed_lookup_workload(client, age_range=(20, 50), iterations=15, warmup=1)

    assert result.kind == LookupKind.INDEXED
    assert result.indexed_properties == ["age"]
    assert result.stats.iterations == 15
    assert result.stats.warmup_iterations == 1
    assert all(call == (20, 50) for call in client.indexed_lookup_calls)
    assert len(client.indexed_lookup_calls) == 16


def test_run_aggregation_workload():
    client = FakeGraphClient()
    result = run_aggregation_workload(client, description="my agg", iterations=10, warmup=3)

    assert result.description == "my agg"
    assert result.stats.iterations == 10
    assert result.stats.warmup_iterations == 3
    assert client.aggregation_calls == 13

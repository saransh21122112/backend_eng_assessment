from __future__ import annotations

from typing import Any

from bench.load import load_platform
from bench.models import PlatformConfig, PlatformName, QueryDialect
from bench.platforms import GraphClient


class FakeGraphClient(GraphClient):
    """In-memory GraphClient recording calls, for testing load_platform."""

    def __init__(self) -> None:
        config = PlatformConfig(
            name=PlatformName.NEO4J_COMMUNITY,
            uri="bolt://fake",
            user="u",
            password="p",
            dialect=QueryDialect.CYPHER,
            advertised_vcpu=0.5,
            advertised_ram_mb=256,
            advertised_disk_gb=1,
            managed=False,
        )
        super().__init__(config)
        self.node_batches: list[list[dict]] = []
        self.edge_batches: list[list[dict]] = []
        self.call_order: list[str] = []

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def ensure_schema(self) -> list[str]:
        self.call_order.append("ensure_schema")
        return ["id", "age"]

    def load_nodes(self, nodes: list[dict]) -> int:
        self.call_order.append("load_nodes")
        self.node_batches.append(nodes)
        return len(nodes)

    def load_edges(self, edges: list[dict]) -> int:
        self.call_order.append("load_edges")
        self.edge_batches.append(edges)
        return len(edges)

    def run_traversal(self, start_id: str, hops: int) -> Any:
        raise NotImplementedError

    def run_point_lookup(self, node_id: str) -> Any:
        raise NotImplementedError

    def run_indexed_lookup(self, min_age: int, max_age: int) -> Any:
        raise NotImplementedError

    def run_aggregation(self) -> Any:
        raise NotImplementedError

    def run_mixed_read(self, node_id: str) -> Any:
        raise NotImplementedError

    def run_mixed_write(self, src_id: str, dst_id: str) -> Any:
        raise NotImplementedError

    def footprint(self) -> dict[str, float | None]:
        raise NotImplementedError


def test_batching_splits_correctly():
    client = FakeGraphClient()
    nodes = [{"id": str(i), "age": i} for i in range(10)]
    load_platform(client, nodes, [], batch_size=3)

    assert [len(b) for b in client.node_batches] == [3, 3, 3, 1]


def test_result_counts_and_rates():
    client = FakeGraphClient()
    nodes = [{"id": str(i), "age": i} for i in range(10)]
    edges = [{"src": "0", "dst": "1"} for _ in range(5)]

    result = load_platform(client, nodes, edges, batch_size=4)

    assert result.nodes_loaded == 10
    assert result.relationships_loaded == 5
    assert isinstance(result.nodes_per_sec, float) and result.nodes_per_sec > 0
    assert isinstance(result.relationships_per_sec, float) and result.relationships_per_sec > 0
    assert result.wall_clock_sec >= 0
    assert "batch_size=4" in result.load_method


def test_ensure_schema_called_before_loads():
    client = FakeGraphClient()
    nodes = [{"id": "0", "age": 1}]
    edges = [{"src": "0", "dst": "0"}]

    load_platform(client, nodes, edges, batch_size=1)

    assert client.call_order[0] == "ensure_schema"
    assert client.call_order.index("ensure_schema") < client.call_order.index("load_nodes")
    assert client.call_order.index("ensure_schema") < client.call_order.index("load_edges")


def test_empty_input():
    client = FakeGraphClient()
    result = load_platform(client, [], [], batch_size=100)

    assert result.nodes_loaded == 0
    assert result.relationships_loaded == 0
    assert result.nodes_per_sec == 0
    assert result.relationships_per_sec == 0

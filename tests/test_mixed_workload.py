from __future__ import annotations

import threading
from typing import Any

from bench.mixed_workload import run_concurrency_sweep, run_mixed_workload
from bench.platforms import GraphClient


class FakeClient(GraphClient):
    """No-op GraphClient for exercising the workload loop without real I/O."""

    def __init__(self):
        self.reads = 0
        self.writes = 0
        self._lock = threading.Lock()

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def ensure_schema(self) -> list[str]: return []
    def load_nodes(self, nodes: list[dict]) -> int: return 0
    def load_edges(self, edges: list[dict]) -> int: return 0
    def run_traversal(self, start_id: str, hops: int) -> Any: return None
    def run_point_lookup(self, node_id: str) -> Any: return None
    def run_indexed_lookup(self, min_age: int, max_age: int) -> Any: return None
    def run_aggregation(self) -> Any: return None
    def footprint(self) -> dict[str, float | None]: return {"stored_data_mb": None, "memory_mb": None}

    def run_mixed_read(self, node_id: str) -> Any:
        with self._lock:
            self.reads += 1

    def run_mixed_write(self, src_id: str, dst_id: str) -> Any:
        with self._lock:
            self.writes += 1


class FlakyClient(FakeClient):
    """Every Nth write raises, to exercise the error-counting path."""

    def __init__(self, fail_every: int = 3):
        super().__init__()
        self.fail_every = fail_every
        self._write_calls = 0

    def run_mixed_write(self, src_id: str, dst_id: str) -> Any:
        with self._lock:
            self._write_calls += 1
            if self._write_calls % self.fail_every == 0:
                raise RuntimeError("simulated write failure")
            self.writes += 1


NODE_IDS = [f"n{i}" for i in range(10)]


def test_run_mixed_workload_basic():
    client = FakeClient()
    point = run_mixed_workload(client, NODE_IDS, concurrency=4, duration_sec=0.2)

    assert point.concurrency == 4
    assert point.throughput_qps > 0
    assert abs(point.duration_sec - 0.2) < 0.3
    assert point.errors == 0
    assert point.read_write_ratio == "80/20"


def test_run_mixed_workload_counts_errors():
    client = FlakyClient(fail_every=3)
    # force writes to happen: 0% reads so every op is a write
    point = run_mixed_workload(client, NODE_IDS, concurrency=3, duration_sec=0.2, read_write_ratio=0.0)

    assert point.errors > 0
    assert point.throughput_qps >= 0


def test_run_concurrency_sweep():
    client = FakeClient()
    points = run_concurrency_sweep(client, NODE_IDS, concurrencies=[1, 2], duration_sec=0.15)

    assert len(points) == 2
    assert [p.concurrency for p in points] == [1, 2]

"""Shared result/config schema for the benchmark harness.

Every module (load, workloads, mixed_workload, render_readme) reads or writes
these types instead of passing around raw dicts, so `results.json` has one
source of truth for its shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, SecretStr


class QueryDialect(str, Enum):
    CYPHER = "cypher"
    AQL = "aql"


class PlatformName(str, Enum):
    COGNODB = "cognodb"
    AURA = "aura"
    NEO4J_COMMUNITY = "neo4j-community"
    MEMGRAPH = "memgraph"
    ARANGODB = "arangodb"


class PlatformConfig(BaseModel):
    name: PlatformName
    uri: str
    user: str
    password: SecretStr
    dialect: QueryDialect
    advertised_vcpu: float
    advertised_ram_mb: int
    advertised_disk_gb: float
    managed: bool  # True = real managed cloud tier, False = self-hosted/resource-capped


class LatencyStats(BaseModel):
    p50_ms: float
    p95_ms: float
    iterations: int
    warmup_iterations: int

    @classmethod
    def from_samples_ms(
        cls, samples_ms: list[float], warmup_iterations: int
    ) -> "LatencyStats":
        import numpy as np

        arr = np.asarray(samples_ms, dtype=float)
        return cls(
            p50_ms=float(np.percentile(arr, 50)),
            p95_ms=float(np.percentile(arr, 95)),
            iterations=len(samples_ms),
            warmup_iterations=warmup_iterations,
        )


class LoadResult(BaseModel):
    nodes_loaded: int
    relationships_loaded: int
    wall_clock_sec: float
    nodes_per_sec: float
    relationships_per_sec: float
    load_method: str


class TraversalResult(BaseModel):
    hop_depth: int = Field(ge=1, le=3)
    stats: LatencyStats


class LookupKind(str, Enum):
    POINT = "point"
    INDEXED = "indexed"


class LookupResult(BaseModel):
    kind: LookupKind
    indexed_properties: list[str] = Field(default_factory=list)
    stats: LatencyStats


class AggregationResult(BaseModel):
    description: str
    stats: LatencyStats


class MixedWorkloadPoint(BaseModel):
    concurrency: int
    read_write_ratio: str  # e.g. "80/20"
    throughput_qps: float
    duration_sec: float
    errors: int = 0


class FootprintResult(BaseModel):
    stored_data_mb: Optional[float] = None
    memory_mb: Optional[float] = None
    notes: str = "not observable"


class PlatformResult(BaseModel):
    platform: PlatformName
    managed: bool
    advertised_specs: str
    load: Optional[LoadResult] = None
    traversals: list[TraversalResult] = Field(default_factory=list)
    lookups: list[LookupResult] = Field(default_factory=list)
    aggregations: list[AggregationResult] = Field(default_factory=list)
    mixed_workload: list[MixedWorkloadPoint] = Field(default_factory=list)
    footprint: FootprintResult = Field(default_factory=FootprintResult)
    caveats: list[str] = Field(default_factory=list)
    failed: bool = False
    failure_reason: Optional[str] = None


class DatasetInfo(BaseModel):
    source: str
    node_count: int
    relationship_count: int
    sample_seed: int


class BenchmarkResults(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dataset: DatasetInfo
    results: list[PlatformResult] = Field(default_factory=list)

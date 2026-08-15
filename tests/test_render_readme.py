from bench.models import (
    AggregationResult,
    BenchmarkResults,
    DatasetInfo,
    FootprintResult,
    LatencyStats,
    LoadResult,
    LookupKind,
    LookupResult,
    MixedWorkloadPoint,
    PlatformName,
    PlatformResult,
    TraversalResult,
)
from results.render_readme import (
    render_aggregation_table,
    render_caveats_section,
    render_footprint_table,
    render_load_table,
    render_lookup_table,
    render_mixed_workload_table,
    render_readme,
    render_traversal_table,
)


def _stats(p50: float = 1.0, p95: float = 2.0) -> LatencyStats:
    return LatencyStats(p50_ms=p50, p95_ms=p95, iterations=10, warmup_iterations=2)


def _fake_results() -> BenchmarkResults:
    cognodb = PlatformResult(
        platform=PlatformName.COGNODB,
        managed=True,
        advertised_specs="free tier",
        load=LoadResult(
            nodes_loaded=1000,
            relationships_loaded=2000,
            wall_clock_sec=5.0,
            nodes_per_sec=200.0,
            relationships_per_sec=400.0,
            load_method="bulk import",
        ),
        traversals=[
            TraversalResult(hop_depth=1, stats=_stats(1.0, 2.0)),
            TraversalResult(hop_depth=2, stats=_stats(3.0, 4.0)),
        ],
        lookups=[
            LookupResult(kind=LookupKind.POINT, stats=_stats(0.5, 1.0)),
            LookupResult(kind=LookupKind.INDEXED, indexed_properties=["email"], stats=_stats(0.6, 1.1)),
        ],
        aggregations=[
            AggregationResult(description="count by type", stats=_stats(5.0, 6.0)),
            AggregationResult(description="avg degree", stats=_stats(7.0, 8.0)),
        ],
        mixed_workload=[
            MixedWorkloadPoint(concurrency=1, read_write_ratio="80/20", throughput_qps=100.0, duration_sec=10.0),
            MixedWorkloadPoint(concurrency=4, read_write_ratio="80/20", throughput_qps=350.0, duration_sec=10.0),
        ],
        footprint=FootprintResult(stored_data_mb=12.5, memory_mb=100.0, notes="stable"),
        caveats=["Free tier resources not fully controllable."],
    )

    arangodb = PlatformResult(
        platform=PlatformName.ARANGODB,
        managed=False,
        advertised_specs="0.5 vCPU / 256MB RAM",
        load=None,
        traversals=[TraversalResult(hop_depth=1, stats=_stats(2.0, 3.0))],
        lookups=[LookupResult(kind=LookupKind.POINT, stats=_stats(1.0, 2.0))],
        aggregations=[],
        mixed_workload=[],
        footprint=FootprintResult(),
        caveats=[],
    )

    memgraph = PlatformResult(
        platform=PlatformName.MEMGRAPH,
        managed=False,
        advertised_specs="0.5 vCPU / 256MB RAM",
        failed=True,
        failure_reason="OOM during load",
    )

    return BenchmarkResults(
        dataset=DatasetInfo(source="soc-Pokec", node_count=1000, relationship_count=2000, sample_seed=42),
        results=[cognodb, arangodb, memgraph],
    )


def test_render_load_table():
    out = render_load_table(_fake_results())
    assert "cognodb" in out
    assert "memgraph" in out
    assert "failed: OOM during load" in out
    assert "not observable" in out  # arangodb has no load result


def test_render_traversal_table():
    out = render_traversal_table(_fake_results())
    assert "cognodb" in out
    assert "1-hop p50" in out
    assert "2-hop p50" in out
    assert "not observable" in out  # arangodb missing 2-hop
    assert "failed: OOM during load" in out


def test_render_lookup_table():
    out = render_lookup_table(_fake_results())
    assert "cognodb" in out
    assert "email" in out
    assert "failed: OOM during load" in out


def test_render_aggregation_table():
    out = render_aggregation_table(_fake_results())
    assert "count by type" in out
    assert "avg degree" in out
    assert "not observable" in out  # arangodb has no aggregations
    assert "failed: OOM during load" in out


def test_render_mixed_workload_table():
    out = render_mixed_workload_table(_fake_results())
    assert "cognodb" in out
    assert "80/20" in out
    assert "not observable" in out  # arangodb has no mixed workload points
    assert "failed: OOM during load" in out


def test_render_footprint_table():
    out = render_footprint_table(_fake_results())
    assert "12.5" in out
    assert "not observable" in out  # arangodb footprint fields are None
    assert "failed: OOM during load" in out


def test_render_caveats_section():
    out = render_caveats_section(_fake_results())
    assert "**cognodb**" in out
    assert "Free tier resources" in out


def test_render_readme_end_to_end(tmp_path):
    results_path = tmp_path / "results.json"
    results_path.write_text(_fake_results().model_dump_json())

    template_path = tmp_path / "README.md"
    template_path.write_text("# Title\n\n## Results\n\n<!-- RESULTS_TABLES:START -->\n<!-- RESULTS_TABLES:END -->\n\n## Analysis\n")

    output_path = tmp_path / "OUT.md"
    render_readme(str(results_path), str(template_path), str(output_path))

    content = output_path.read_text()
    assert "<!-- RESULTS_TABLES:START -->" in content  # marker preserved for the next re-render
    assert "cognodb" in content


def test_render_readme_is_idempotent_on_rerun(tmp_path):
    """Re-running against a README that already has rendered tables should
    re-splice cleanly, not duplicate or leave stale content — this used to
    silently no-op once the marker had been consumed on the first render.
    """
    results_path = tmp_path / "results.json"
    results_path.write_text(_fake_results().model_dump_json())

    template_path = tmp_path / "README.md"
    template_path.write_text("# Title\n\n## Results\n\n<!-- RESULTS_TABLES:START -->\n<!-- RESULTS_TABLES:END -->\n\n## Analysis\n")

    render_readme(str(results_path), str(template_path), str(template_path))
    first_pass = template_path.read_text()
    assert first_pass.count("<!-- RESULTS_TABLES:START -->") == 1
    assert first_pass.count("cognodb") >= 1

    render_readme(str(results_path), str(template_path), str(template_path))
    second_pass = template_path.read_text()
    assert second_pass.count("<!-- RESULTS_TABLES:START -->") == 1
    assert second_pass == first_pass  # same input results.json -> byte-identical re-render


def test_render_readme_no_results_yet(tmp_path):
    results_path = tmp_path / "does_not_exist.json"
    template_path = tmp_path / "README.md"
    template_path.write_text("# Title\n\n## Results\n\n<!-- RESULTS_TABLES:START -->\n<!-- RESULTS_TABLES:END -->\n")

    output_path = tmp_path / "OUT.md"
    render_readme(str(results_path), str(template_path), str(output_path))

    content = output_path.read_text()
    assert "No results yet" in content
    assert "# Title" in content

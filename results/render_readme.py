"""Render benchmark results (results/results.json) into README.md tables.

Reads a BenchmarkResults JSON file and renders markdown tables for each
metric category, then splices them into a README template at the
<!-- RESULTS_TABLES --> marker.
"""
from __future__ import annotations

import argparse
import os
from typing import Optional

from tabulate import tabulate

from bench.models import BenchmarkResults, LookupKind

MARKER = "<!-- RESULTS_TABLES -->"


def load_results(path: str) -> BenchmarkResults:
    with open(path, "r") as f:
        return BenchmarkResults.model_validate_json(f.read())


def _na(value: Optional[float], fmt: str = "{:.2f}") -> str:
    return "not observable" if value is None else fmt.format(value)


def render_load_table(results: BenchmarkResults) -> str:
    rows = []
    for r in results.results:
        if r.failed:
            rows.append([r.platform.value, r.managed, f"failed: {r.failure_reason}", "", "", ""])
        elif r.load is None:
            rows.append([r.platform.value, r.managed, "not observable", "not observable", "not observable", "not observable"])
        else:
            rows.append([
                r.platform.value,
                r.managed,
                f"{r.load.nodes_per_sec:.1f}",
                f"{r.load.relationships_per_sec:.1f}",
                f"{r.load.wall_clock_sec:.2f}",
                r.load.load_method,
            ])
    headers = ["Platform", "Managed?", "Nodes/sec", "Rels/sec", "Wall-clock (s)", "Load method"]
    return tabulate(rows, headers=headers, tablefmt="github")


def render_traversal_table(results: BenchmarkResults) -> str:
    depths = sorted({t.hop_depth for r in results.results for t in r.traversals})
    headers = ["Platform"]
    for d in depths:
        headers += [f"{d}-hop p50", f"{d}-hop p95"]

    rows = []
    for r in results.results:
        if r.failed:
            row = [r.platform.value] + [f"failed: {r.failure_reason}"] * (2 * len(depths))
            rows.append(row)
            continue
        by_depth = {t.hop_depth: t for t in r.traversals}
        row = [r.platform.value]
        for d in depths:
            t = by_depth.get(d)
            if t is None:
                row += ["not observable", "not observable"]
            else:
                row += [f"{t.stats.p50_ms:.2f}", f"{t.stats.p95_ms:.2f}"]
        rows.append(row)
    return tabulate(rows, headers=headers, tablefmt="github")


def render_lookup_table(results: BenchmarkResults) -> str:
    headers = ["Platform", "Point p50", "Point p95", "Indexed p50", "Indexed p95", "Indexed properties"]
    rows = []
    for r in results.results:
        if r.failed:
            rows.append([r.platform.value, f"failed: {r.failure_reason}", "", "", "", ""])
            continue
        by_kind = {l.kind: l for l in r.lookups}
        point = by_kind.get(LookupKind.POINT)
        indexed = by_kind.get(LookupKind.INDEXED)
        rows.append([
            r.platform.value,
            f"{point.stats.p50_ms:.2f}" if point else "not observable",
            f"{point.stats.p95_ms:.2f}" if point else "not observable",
            f"{indexed.stats.p50_ms:.2f}" if indexed else "not observable",
            f"{indexed.stats.p95_ms:.2f}" if indexed else "not observable",
            ", ".join(indexed.indexed_properties) if indexed else "not observable",
        ])
    return tabulate(rows, headers=headers, tablefmt="github")


def render_aggregation_table(results: BenchmarkResults) -> str:
    headers = ["Platform", "Description", "p50", "p95"]
    rows = []
    for r in results.results:
        if r.failed:
            rows.append([r.platform.value, f"failed: {r.failure_reason}", "", ""])
            continue
        if not r.aggregations:
            rows.append([r.platform.value, "not observable", "not observable", "not observable"])
            continue
        for a in r.aggregations:
            rows.append([r.platform.value, a.description, f"{a.stats.p50_ms:.2f}", f"{a.stats.p95_ms:.2f}"])
    return tabulate(rows, headers=headers, tablefmt="github")


def render_mixed_workload_table(results: BenchmarkResults) -> str:
    headers = ["Platform", "Concurrency", "Read/Write mix", "Throughput (qps)", "Errors"]
    rows = []
    for r in results.results:
        if r.failed:
            rows.append([r.platform.value, "", f"failed: {r.failure_reason}", "", ""])
            continue
        if not r.mixed_workload:
            rows.append([r.platform.value, "not observable", "not observable", "not observable", "not observable"])
            continue
        for m in r.mixed_workload:
            rows.append([r.platform.value, m.concurrency, m.read_write_ratio, f"{m.throughput_qps:.1f}", m.errors])
    return tabulate(rows, headers=headers, tablefmt="github")


def render_footprint_table(results: BenchmarkResults) -> str:
    headers = ["Platform", "Stored data (MB)", "Memory (MB)", "Notes"]
    rows = []
    for r in results.results:
        if r.failed:
            rows.append([r.platform.value, "", "", f"failed: {r.failure_reason}"])
            continue
        f = r.footprint
        rows.append([r.platform.value, _na(f.stored_data_mb), _na(f.memory_mb), f.notes])
    return tabulate(rows, headers=headers, tablefmt="github")


def render_caveats_section(results: BenchmarkResults) -> str:
    lines = []
    for r in results.results:
        for c in r.caveats:
            lines.append(f"**{r.platform.value}**: {c}")
    return "\n".join(f"- {line}" for line in lines) if lines else "_No caveats recorded._"


def _dataset_line(results: BenchmarkResults) -> str:
    d = results.dataset
    return (
        f"Dataset: {d.source} — {d.node_count:,} nodes, {d.relationship_count:,} relationships "
        f"(sample seed {d.sample_seed}). Generated at {results.generated_at.isoformat()}."
    )


def render_readme(results_path: str, template_path: str, output_path: str) -> None:
    with open(template_path, "r") as f:
        template = f.read()

    if not os.path.exists(results_path):
        body = f"_No results yet — run `python bench/run_all.py` then `python {os.path.relpath(__file__)}` to populate this section._"
        output = template.replace(MARKER, body)
        with open(output_path, "w") as f:
            f.write(output)
        return

    results = load_results(results_path)

    sections = [
        _dataset_line(results),
        "## Data Loading\n\n" + render_load_table(results),
        "## Traversals\n\n" + render_traversal_table(results),
        "## Lookups\n\n" + render_lookup_table(results),
        "## Aggregations\n\n" + render_aggregation_table(results),
        "## Mixed Workload\n\n" + render_mixed_workload_table(results),
        "## Footprint\n\n" + render_footprint_table(results),
        "## Caveats\n\n" + render_caveats_section(results),
    ]
    body = "\n\n".join(sections)
    output = template.replace(MARKER, body)
    with open(output_path, "w") as f:
        f.write(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render benchmark results into README.md")
    parser.add_argument("--results", default="results/results.json")
    parser.add_argument("--template", default="README.md")
    parser.add_argument("--output", default="README.md")
    args = parser.parse_args()
    render_readme(args.results, args.template, args.output)

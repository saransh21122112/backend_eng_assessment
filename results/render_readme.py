"""Render benchmark results (results/results.json) into README.md tables.

Reads a BenchmarkResults JSON file and renders markdown tables for each
metric category, then splices them into a README template at the
<!-- RESULTS_TABLES --> marker.
"""
from __future__ import annotations

import argparse
import os
import re
from typing import Optional

from tabulate import tabulate

from bench.models import BenchmarkResults, LookupKind

MARKER_START = "<!-- RESULTS_TABLES:START -->"
MARKER_END = "<!-- RESULTS_TABLES:END -->"


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


def render_cold_vs_warm_table(results: BenchmarkResults) -> str:
    headers = ["Platform", "Workload", "Cold (1st call, ms)", "Warm p50 (ms)", "Warm p95 (ms)"]
    rows = []
    for r in results.results:
        if r.failed:
            rows.append([r.platform.value, "", f"failed: {r.failure_reason}", "", ""])
            continue
        for t in r.traversals:
            rows.append([
                r.platform.value, f"{t.hop_depth}-hop traversal",
                _na(t.stats.cold_ms), f"{t.stats.p50_ms:.2f}", f"{t.stats.p95_ms:.2f}",
            ])
        for lk in r.lookups:
            rows.append([
                r.platform.value, f"{lk.kind.value} lookup",
                _na(lk.stats.cold_ms), f"{lk.stats.p50_ms:.2f}", f"{lk.stats.p95_ms:.2f}",
            ])
        for a in r.aggregations:
            rows.append([
                r.platform.value, a.description,
                _na(a.stats.cold_ms), f"{a.stats.p50_ms:.2f}", f"{a.stats.p95_ms:.2f}",
            ])
    return tabulate(rows, headers=headers, tablefmt="github")


def render_variance_table(results: BenchmarkResults) -> str:
    headers = ["Platform", "Metric", "Per-run p50 (ms)", "Mean p50 (ms)", "Stdev (ms)", "CV (%)"]
    rows = []
    for r in results.results:
        if r.failed:
            rows.append([r.platform.value, "", f"failed: {r.failure_reason}", "", "", ""])
            continue
        if not r.variance:
            rows.append([r.platform.value, "not observable", "not observable", "not observable", "not observable", "not observable"])
            continue
        for v in r.variance:
            per_run = ", ".join(f"{p:.2f}" for p in v.run_p50_ms)
            rows.append([
                r.platform.value, v.description, per_run,
                f"{v.mean_p50_ms:.2f}", f"{v.stdev_p50_ms:.2f}", f"{v.coefficient_of_variation_pct:.1f}",
            ])
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


def _splice(template: str, body: str) -> str:
    """Replace the region between MARKER_START/MARKER_END with `body`, keeping
    the markers so the next render is a clean re-splice rather than a no-op.

    Falls back to replacing everything between the `## Results` heading and
    the next top-level heading if the markers aren't present yet (e.g. the
    first render against an older README that predates this marker scheme) —
    and inserts the markers so every render after that is idempotent.
    """
    wrapped = f"{MARKER_START}\n\n{body}\n\n{MARKER_END}"
    if MARKER_START in template and MARKER_END in template:
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END)
        return re.sub(pattern, wrapped, template, flags=re.S)

    match = re.search(r"(^## Results\n).*?(?=^## Analysis\b)", template, flags=re.S | re.M)
    if match:
        return template[: match.end(1)] + wrapped + "\n\n" + template[match.end():]

    # No prior results section at all — nothing sensible to splice into.
    return template + "\n\n" + wrapped + "\n"


def render_readme(results_path: str, template_path: str, output_path: str) -> None:
    with open(template_path, "r") as f:
        template = f.read()

    if not os.path.exists(results_path):
        body = f"_No results yet — run `python bench/run_all.py` then `python {os.path.relpath(__file__)}` to populate this section._"
        output = _splice(template, body)
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
        "## Warm vs. Cold\n\n"
        "Cold = latency of the first call to a freshly-connected client, before "
        "any warm-up. Warm p50/p95 come from the timed run after warm-up, same "
        "numbers as the tables above — reproduced here so warm and cold sit "
        "side by side per the spec's \"report cold-start numbers separately\" rule.\n\n"
        + render_cold_vs_warm_table(results),
        "## Run-to-Run Variance\n\n"
        "The aggregation query, timed across 5 independent warmup+measure passes "
        "(rather than one pass with many iterations) per platform, to check "
        "whether p50 itself drifts run-to-run — e.g. from shared free-tier "
        "neighbors, network variance, or cache state — rather than just "
        "reporting a single run's percentile as if it were exact.\n\n"
        + render_variance_table(results),
        "## Mixed Workload\n\n" + render_mixed_workload_table(results),
        "## Footprint\n\n" + render_footprint_table(results),
        "## Caveats\n\n" + render_caveats_section(results),
    ]
    body = "\n\n".join(sections)
    output = _splice(template, body)
    with open(output_path, "w") as f:
        f.write(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render benchmark results into README.md")
    parser.add_argument("--results", default="results/results.json")
    parser.add_argument("--template", default="README.md")
    parser.add_argument("--output", default="README.md")
    args = parser.parse_args()
    render_readme(args.results, args.template, args.output)

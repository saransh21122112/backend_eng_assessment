"""Single entrypoint: loads the sampled dataset into every configured platform,
runs every required workload category, and writes results/results.json.

Usage:
    python bench/run_all.py                              # every platform with creds in .env
    python bench/run_all.py --platforms memgraph,neo4j-community   # self-hosted only, no cloud creds needed
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from tqdm import tqdm

from bench.load import load_platform
from bench.mixed_workload import run_concurrency_sweep
from bench.models import (
    BenchmarkResults,
    DatasetInfo,
    FootprintResult,
    PlatformResult,
)
from bench.platforms import load_platform_configs, make_client
from bench.stats import run_variance_check
from bench.workloads import (
    run_aggregation_workload,
    run_indexed_lookup_workload,
    run_point_lookup_workload,
    run_traversal_workload,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_nodes(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return [{"id": row["id"], "age": int(row["age"])} for row in csv.DictReader(f)]


def _read_edges(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return [{"src": row["src"], "dst": row["dst"]} for row in csv.DictReader(f)]


def _load_dataset_info(path: Path) -> DatasetInfo:
    return DatasetInfo.model_validate_json(path.read_text())


def run_one_platform(
    name: str,
    config,
    nodes: list[dict],
    edges: list[dict],
    sample_ids: list[str],
    iterations: int,
    warmup: int,
    concurrencies: list[int],
    duration_sec: float,
    batch_size: int,
    skip_load: bool = False,
) -> PlatformResult:
    advertised = (
        f"{config.advertised_vcpu} vCPU / {config.advertised_ram_mb}MB RAM / "
        f"{config.advertised_disk_gb}GB disk ({'managed' if config.managed else 'self-hosted, capped'})"
    )
    result = PlatformResult(
        platform=config.name, managed=config.managed, advertised_specs=advertised
    )
    # one advance() call per stage transition below: load, 2-hop, 3-hop, point lookup,
    # indexed lookup, aggregation, variance, mixed workload, footprint, done = 10
    stage_bar = tqdm(total=10, desc=f"{name:16s} connect", unit="stage", leave=False)

    def advance(label: str) -> None:
        stage_bar.set_description(f"{name:16s} {label}")
        stage_bar.update(1)

    client = make_client(config)
    try:
        client.connect()
    except Exception as exc:  # connection failures are exactly the honest caveats the spec wants surfaced
        result.failed = True
        result.failure_reason = f"connect failed: {exc}"
        stage_bar.close()
        return result
    advance("load")

    try:
        if skip_load:
            result.caveats.append(
                "load stage skipped for this run (--skip-load): reusing data already "
                "loaded by a prior clean run, to avoid the non-idempotent CREATE loader "
                "duplicating data on re-run. Ingest throughput figures, if present, are "
                "carried over from that prior run rather than re-measured here."
            )
        else:
            result.load = load_platform(client, nodes, edges, batch_size=batch_size)
        advance("1-hop")
        result.traversals = []
        for hops, label in zip((1, 2, 3), ("2-hop", "3-hop", "point lookup")):
            result.traversals.append(run_traversal_workload(client, sample_ids, hops, iterations, warmup))
            advance(label)
        result.lookups = [run_point_lookup_workload(client, sample_ids, iterations, warmup)]
        advance("indexed lookup")
        result.lookups.append(run_indexed_lookup_workload(client, (25, 45), iterations, warmup))
        advance("aggregation")
        result.aggregations = [run_aggregation_workload(client, iterations=iterations, warmup=warmup)]
        advance("variance")
        result.variance = [
            run_variance_check(client.run_aggregation, "count of FRIEND relationships (repeated runs)")
        ]
        advance("mixed workload")
        result.mixed_workload = run_concurrency_sweep(
            client, sample_ids, concurrencies=concurrencies, duration_sec=duration_sec
        )
        advance("footprint")
        footprint = client.footprint()
        result.footprint = FootprintResult(**footprint)
        advance("done")
    except Exception as exc:
        result.failed = True
        result.failure_reason = str(exc)
        result.caveats.append(f"run aborted partway through: {exc}")
    finally:
        stage_bar.close()
        try:
            client.close()
        except Exception:
            pass

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platforms", default=None, help="comma-separated platform names, default all with creds set")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--concurrencies", default="1,10,40")
    parser.add_argument("--duration", type=float, default=5.0, help="seconds per mixed-workload concurrency level")
    parser.add_argument("--sample-size", type=int, default=1000, help="start-node pool for traversal/lookup workloads")
    parser.add_argument("--batch-size", type=int, default=1000, help="rows per UNWIND batch during load")
    parser.add_argument(
        "--skip-load", action="store_true",
        help="skip the load stage and reuse already-loaded data (safe re-run without duplicating rows)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(REPO_ROOT / "results" / "results.json"))
    args = parser.parse_args()

    random.seed(args.seed)
    only = args.platforms.split(",") if args.platforms else None
    concurrencies = [int(c) for c in args.concurrencies.split(",")]

    dataset_dir = REPO_ROOT / "data"
    nodes = _read_nodes(dataset_dir / "pokec_sample_nodes.csv")
    edges = _read_edges(dataset_dir / "pokec_sample_edges.csv")
    dataset_info = _load_dataset_info(dataset_dir / "dataset_info.json")

    sample_ids = [n["id"] for n in random.sample(nodes, min(args.sample_size, len(nodes)))]

    configs = load_platform_configs(only=only)
    if not configs:
        raise SystemExit(
            "No platform credentials found. Copy .env.example to .env and fill in at least one "
            "platform's URI, or pass --platforms to target the self-hosted ones after `docker compose up -d`."
        )

    results = BenchmarkResults(dataset=dataset_info)
    for name, config in tqdm(configs.items(), desc="platforms", unit="platform"):
        platform_result = run_one_platform(
            name.value, config, nodes, edges, sample_ids,
            args.iterations, args.warmup, concurrencies, args.duration, args.batch_size,
            skip_load=args.skip_load,
        )
        results.results.append(platform_result)
        status = "FAILED: " + (platform_result.failure_reason or "") if platform_result.failed else "ok"
        tqdm.write(f"--- {name.value}: {status} ---")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(results.model_dump_json(indent=2))
    print(f"\nwrote {output_path}")


if __name__ == "__main__":
    main()

"""Download and sample the SNAP soc-Pokec relationships dataset.

Downloads the full edge list, then samples a connected subgraph of roughly
`target_edges` relationships via a seeded BFS expansion from a random start
node (not a random edge subset, which would likely be disconnected on a
large sparse graph). Assigns each sampled node a synthetic `age` property
since we're not fetching the separate real profile-attributes file.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

from bench.models import DatasetInfo

SNAP_URL = "https://snap.stanford.edu/data/soc-pokec-relationships.txt.gz"
DATA_DIR = Path(__file__).parent
EDGELIST_PATH = DATA_DIR / "pokec-relationships.txt.gz"
NODES_CSV = DATA_DIR / "pokec_sample_nodes.csv"
EDGES_CSV = DATA_DIR / "pokec_sample_edges.csv"
DATASET_INFO_JSON = DATA_DIR / "dataset_info.json"


def download_edgelist(dest_path: Path = EDGELIST_PATH) -> None:
    """Download the SNAP soc-Pokec edge list gzip, skipping if already present."""
    if dest_path.exists():
        return
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(SNAP_URL, dest_path)


def iter_edges_from_gzip(path: Path) -> Iterator[tuple[int, int]]:
    """Yield (src, dst) int pairs from the tab-separated gzip edge list."""
    with gzip.open(path, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            src, dst = line.split("\t")
            yield int(src), int(dst)


def sample_connected_subgraph(
    edge_iterator: Iterable[tuple[int, int]],
    target_edges: int = 200_000,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Seeded BFS expansion collecting edges until target_edges is hit (or exhausted).

    Returns (nodes, edges) where nodes = [{"id": int, "age": int}, ...] and
    edges = [{"src": int, "dst": int}, ...], restricted to the collected
    connected component.
    """
    rng = random.Random(seed)

    adjacency: dict[int, list[int]] = defaultdict(list)
    all_nodes: set[int] = set()
    for src, dst in edge_iterator:
        adjacency[src].append(dst)
        adjacency[dst].append(src)
        all_nodes.add(src)
        all_nodes.add(dst)

    if not all_nodes:
        return [], []

    start = rng.choice(sorted(all_nodes))

    visited: set[int] = {start}
    frontier = [start]
    collected_edges: list[tuple[int, int]] = []
    seen_edges: set[tuple[int, int]] = set()

    while frontier and len(collected_edges) < target_edges:
        current = frontier.pop(0)
        neighbors = list(adjacency[current])
        rng.shuffle(neighbors)
        for nbr in neighbors:
            edge_key = (current, nbr) if current <= nbr else (nbr, current)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                collected_edges.append(edge_key)
            if nbr not in visited:
                visited.add(nbr)
                frontier.append(nbr)
            if len(collected_edges) >= target_edges:
                break

    node_ids = sorted(visited)
    nodes = [{"id": nid, "age": rng.randint(18, 80)} for nid in node_ids]
    edges = [{"src": s, "dst": d} for s, d in collected_edges]
    return nodes, edges


def write_outputs(nodes: list[dict], edges: list[dict], seed: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(NODES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "age"])
        writer.writeheader()
        writer.writerows(nodes)

    with open(EDGES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["src", "dst"])
        writer.writeheader()
        writer.writerows(edges)

    info = DatasetInfo(
        source="SNAP soc-Pokec",
        node_count=len(nodes),
        relationship_count=len(edges),
        sample_seed=seed,
    )
    DATASET_INFO_JSON.write_text(info.model_dump_json(indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-edges", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    download_edgelist()
    nodes, edges = sample_connected_subgraph(
        iter_edges_from_gzip(EDGELIST_PATH), target_edges=args.target_edges, seed=args.seed
    )
    write_outputs(nodes, edges, args.seed)
    print(f"nodes={len(nodes)} edges={len(edges)}")

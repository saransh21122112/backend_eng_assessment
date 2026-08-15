from data.prepare_dataset import sample_connected_subgraph

# A small connected graph: a chain plus a couple of branches (7 edges).
SYNTHETIC_EDGES = [
    (1, 2),
    (2, 3),
    (3, 4),
    (4, 5),
    (2, 5),
    (5, 6),
    (6, 7),
]


def test_respects_target_edge_count_or_exhausts_graph():
    nodes, edges = sample_connected_subgraph(SYNTHETIC_EDGES, target_edges=3, seed=42)
    assert len(edges) <= 3

    # Target larger than the graph has -> exhausts and returns all edges.
    nodes_all, edges_all = sample_connected_subgraph(SYNTHETIC_EDGES, target_edges=1000, seed=42)
    assert len(edges_all) == len(SYNTHETIC_EDGES)
    assert len(nodes_all) == 7


def test_edges_reference_only_output_nodes():
    nodes, edges = sample_connected_subgraph(SYNTHETIC_EDGES, target_edges=4, seed=1)
    node_ids = {n["id"] for n in nodes}
    for e in edges:
        assert e["src"] in node_ids
        assert e["dst"] in node_ids


def test_ages_within_range():
    nodes, _ = sample_connected_subgraph(SYNTHETIC_EDGES, target_edges=1000, seed=7)
    for n in nodes:
        assert 18 <= n["age"] <= 80


def test_deterministic_for_same_seed():
    result1 = sample_connected_subgraph(SYNTHETIC_EDGES, target_edges=5, seed=42)
    result2 = sample_connected_subgraph(SYNTHETIC_EDGES, target_edges=5, seed=42)
    assert result1 == result2

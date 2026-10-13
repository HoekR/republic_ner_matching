"""The full-graph round trip: a graph rebuilt from persisted records equals the live one.

User, 2026-10-09: "is the graph saved to disk?" / "AND WORK FROM AND ON THE SAVED GRAPH FROM NOW
ON." Same discipline as Stage 3's `Consolidation.to_records()`/`from_records()`, generalized to
the whole graph -- `sequence_graph/persist.py`'s own module docstring.
"""

from __future__ import annotations

from sequence_graph.correspondence import ALIGNED_TO, add_aligned_to_gold, add_aligned_to_solver
import pytest

from sequence_graph.persist import (
    _snapshot_logical_names,
    build_full_graph,
    edge_records,
    graph_from_records,
    node_records,
)


def test_round_trip_preserves_every_node_and_edge_count():
    """A small, fast slice: build just the base graph plus gold ALIGNED_TO (skip the expensive
    full legacy-concordance read and solver runs -- those are exercised in
    test_sequence_graph_correspondence.py already; this test is about the round trip itself)."""
    from sequence_graph.build import build

    graph = build()
    add_aligned_to_gold(graph)
    nodes = node_records(graph)
    edges = edge_records(graph)
    rebuilt = graph_from_records(nodes, edges)

    assert rebuilt.number_of_nodes() == graph.number_of_nodes()
    assert rebuilt.number_of_edges() == graph.number_of_edges()
    for kind in ("Scan", "Session", "HtrResolution", "Paragraph", "SittingDay", "EnrichedResolution"):
        original = sum(1 for _n, d in graph.nodes(data=True) if d["kind"] == kind)
        reconstructed = sum(1 for _n, d in rebuilt.nodes(data=True) if d["kind"] == kind)
        assert original == reconstructed, kind


def test_round_trip_preserves_node_object_fields():
    """Not just counts -- the reconstructed node's own dataclass fields must match exactly,
    including the fields the live object's own class derives nothing extra from."""
    from sequence_graph.build import build

    graph = build()
    nodes = node_records(graph)
    edges = edge_records(graph)
    rebuilt = graph_from_records(nodes, edges)

    sample_id = next(n for n, d in graph.nodes(data=True) if d["kind"] == "Session")
    original_obj = graph.nodes[sample_id]["obj"]
    rebuilt_obj = rebuilt.nodes[sample_id]["obj"]
    assert original_obj == rebuilt_obj  # frozen dataclasses compare by value


def test_round_trip_preserves_distinct_aligned_to_keys_on_the_same_pair():
    """The one case that would silently break if `key` were re-derived from `kind` instead of
    saved exactly: a pair carrying BOTH a gold and a solver ALIGNED_TO edge must survive as two
    distinct edges, not collapse into one."""
    from sequence_graph.build import build

    graph = build()
    add_aligned_to_gold(graph)
    add_aligned_to_solver(graph, ["1629-03-02"])
    nodes = node_records(graph)
    edges = edge_records(graph)
    rebuilt = graph_from_records(nodes, edges)

    original_aligned = [
        (u, v, k) for u, v, k, d in graph.edges(keys=True, data=True) if d.get("kind") == ALIGNED_TO
    ]
    rebuilt_aligned = [
        (u, v, k) for u, v, k, d in rebuilt.edges(keys=True, data=True) if d.get("kind") == ALIGNED_TO
    ]
    assert sorted(original_aligned) == sorted(rebuilt_aligned)


def test_round_trip_preserves_evidence_fields_and_none_for_sequence_edges():
    """NEXT/CONTAINS edges carry no Evidence (must round-trip as None, not crash); OBSERVED_ON/
    ALIGNED_TO edges must carry their Evidence back exactly, including `detail`."""
    from sequence_graph.build import build
    from sequence_graph.correspondence import add_observed_on

    graph = build()
    add_observed_on(graph)
    add_aligned_to_gold(graph)
    nodes = node_records(graph)
    edges = edge_records(graph)
    rebuilt = graph_from_records(nodes, edges)

    for u, v, key, data in graph.edges(keys=True, data=True):
        rebuilt_data = rebuilt.get_edge_data(u, v, key=key)
        if "evidence" not in data:
            assert "evidence" not in rebuilt_data or rebuilt_data.get("evidence") is None
            continue
        assert rebuilt_data["evidence"] == data["evidence"]


def test_graph_from_records_is_idempotent_on_its_own_output():
    """Persisting a persisted graph again must reproduce the same records -- round-tripping twice
    is the same as once."""
    from sequence_graph.build import build

    graph = build()
    add_aligned_to_gold(graph)
    nodes_1 = node_records(graph)
    edges_1 = edge_records(graph)
    rebuilt = graph_from_records(nodes_1, edges_1)
    nodes_2 = node_records(rebuilt)
    edges_2 = edge_records(rebuilt)

    assert sorted(nodes_1, key=lambda r: r["node_id"]) == sorted(nodes_2, key=lambda r: r["node_id"])
    assert len(edges_1) == len(edges_2)


def test_snapshot_logical_names_reject_bad_labels():
    nodes, edges = _snapshot_logical_names("seed_overflow_wire")
    assert nodes == "sequence_graph_nodes_snapshot_seed_overflow_wire"
    assert edges == "sequence_graph_edges_snapshot_seed_overflow_wire"
    with pytest.raises(ValueError):
        _snapshot_logical_names("bad/label")

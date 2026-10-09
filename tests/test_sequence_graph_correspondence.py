"""Stage 2's primitives: correspondence edges, `monotone_map`, `traversal_is_inferred`.

`plans/SEQUENCE_GRAPH_SPINE.md` Stage 2. Functional tests against a live build
(nothing persisted until Stage 3), following the same convention as `test_sequence_graph_build.py`.
"""

from __future__ import annotations

import networkx as nx
import pytest

from sequence_graph.build import CONTAINS, NEXT, build
from sequence_graph.correspondence import (
    ALIGNED_TO,
    DATED_AS,
    LABELLED_AS,
    OBSERVED_ON,
    PINNED_TO,
    Evidence,
    MonotonicityReport,
    add_aligned_to_gold,
    add_aligned_to_solver,
    add_dated_as,
    add_observed_on,
    add_pinned_and_labelled,
    gold_aligned_pairs,
    monotone_map,
    traversal_is_inferred,
)


def test_traversal_is_inferred_flags_pinned_to_and_labelled_as():
    assert traversal_is_inferred([OBSERVED_ON, DATED_AS]) is False
    assert traversal_is_inferred([PINNED_TO]) is True
    assert traversal_is_inferred([LABELLED_AS]) is True
    assert traversal_is_inferred([OBSERVED_ON, DATED_AS, PINNED_TO]) is True


def test_monotonicity_report_rate_is_violations_over_checked():
    report = MonotonicityReport(edge_kind="X", checked=100, violations=(("a", "b"), ("c", "d")))
    assert report.rate == pytest.approx(0.02)


def test_monotonicity_report_rate_is_zero_when_nothing_was_checked():
    assert MonotonicityReport(edge_kind="X", checked=0, violations=()).rate == 0.0


def test_a_date_can_carry_both_pinned_to_and_labelled_as_the_same_session():
    """The MultiDiGraph regression: `session-3185-num-13` has `1626-01-15` in BOTH
    `resolved_dates` and `label_dates`. A plain DiGraph silently drops one of the two edges when
    they share the same (day, session) endpoints; both must survive here."""
    graph = build()
    add_observed_on(graph)
    add_dated_as(graph)
    add_pinned_and_labelled(graph)

    day_node, session_node = "day:1626-01-15", "session:session-3185-num-13"
    assert graph.has_edge(day_node, session_node, key=PINNED_TO)
    assert graph.has_edge(day_node, session_node, key=LABELLED_AS)
    kinds = {d["kind"] for _u, _v, d in graph.edges(data=True) if (_u, _v) == (day_node, session_node)}
    assert kinds == {PINNED_TO, LABELLED_AS}


def test_monotone_map_groups_by_shared_component_on_both_ends():
    """A synthetic two-inventory case: inverting the map in one inventory must not count as a
    violation against the other inventory's own, correctly-ordered map."""
    graph = nx.MultiDiGraph()
    # inventory A: scans 1,2 -> dates in order (fine)
    for i, (scan, day) in enumerate([(1, "d1"), (2, "d2")]):
        graph.add_node(f"scanA{scan}", kind="Scan", obj=None)
        graph.add_node(f"day_{day}", kind="SittingDay", obj=None)
        graph.add_edge(f"scanA{scan}", f"day_{day}", key=DATED_AS, kind=DATED_AS)
    graph.add_edge("scanA1", "scanA2", key=NEXT, kind=NEXT)
    graph.add_edge("day_d1", "day_d2", key=NEXT, kind=NEXT)
    # inventory B: scans 1,2 -> dates INVERTED (a real violation)
    for scan, day in [(1, "d4"), (2, "d3")]:
        graph.add_node(f"scanB{scan}", kind="Scan", obj=None)
        graph.add_node(f"day_{day}", kind="SittingDay", obj=None)
        graph.add_edge(f"scanB{scan}", f"day_{day}", key=DATED_AS, kind=DATED_AS)
    graph.add_edge("scanB1", "scanB2", key=NEXT, kind=NEXT)
    graph.add_edge("day_d3", "day_d4", key=NEXT, kind=NEXT)  # d3 < d4 in the day chain

    report = monotone_map(graph, from_kind="Scan", to_kind="SittingDay", edge_kind=DATED_AS)
    assert report.checked == 4
    assert len(report.violations) == 1  # only inventory B's pair, A's own pair is clean


def test_observed_on_only_targets_sessions_that_are_stage_1_nodes():
    """A sidelined or post-bar session has no node at all, so it must get no OBSERVED_ON edge
    rather than a dangling edge to a node that was never created."""
    graph = build()
    n = add_observed_on(graph)
    for u, v, d in graph.edges(data=True):
        if d.get("kind") == OBSERVED_ON:
            assert graph.nodes[u]["kind"] == "Session"
            assert graph.nodes[v]["kind"] == "Scan"
    assert n > 0


def test_aligned_to_gold_is_observed_true_with_no_confidence():
    """Gold edges are a hard, positive fact -- observed=True, no fabricated confidence number
    (hand annotation has no separately measured error rate to carry)."""
    graph = build()
    n = add_aligned_to_gold(graph)
    assert n > 0
    aligned_edges = [
        (u, v, d) for u, v, d in graph.edges(data=True) if d.get("kind") == ALIGNED_TO
    ]
    assert len(aligned_edges) == n
    for u, v, data in aligned_edges:
        assert graph.nodes[u]["kind"] == "EnrichedResolution"
        assert graph.nodes[v]["kind"] == "HtrResolution"
        assert data["evidence"].observed is True
        assert data["evidence"].confidence is None


def test_gold_aligned_pairs_filters_by_evidence_not_by_pair():
    """The one sanctioned calibration read path: observed=True only, by the edge's OWN evidence
    flag -- never by assuming solver and gold disagree. Two parallel edges on the SAME (u, v) pair
    (one gold, one solver, agreeing) must still count once, correctly, as a gold pair; a
    solver-only edge on a DIFFERENT pair must never appear."""
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "enriched:x:0", "htr_res:a", key=f"{ALIGNED_TO}:gold", kind=ALIGNED_TO,
        evidence=Evidence(channel="gold_annotation", source="boundary_gold_sample", observed=True),
    )
    graph.add_edge(  # same pair, solver agrees -- must not create a second, wrong entry
        "enriched:x:0", "htr_res:a", key=f"{ALIGNED_TO}:solver", kind=ALIGNED_TO,
        evidence=Evidence(channel="dp_solver", source="sequence_graph.align", observed=False),
    )
    graph.add_edge(  # solver-only, different pair -- must never leak into the gold read path
        "enriched:x:1", "htr_res:b", key=f"{ALIGNED_TO}:solver", kind=ALIGNED_TO,
        evidence=Evidence(channel="dp_solver", source="sequence_graph.align", observed=False),
    )
    pairs = gold_aligned_pairs(graph)
    assert pairs == [("enriched:x:0", "htr_res:a")]


def test_solver_edges_never_overwrite_a_gold_edge_on_the_same_pair():
    """Regression for the bug found live (2026-10-09): both halves first keyed on the literal
    string `ALIGNED_TO`, so a solver edge on a pair gold already covered silently replaced the
    hard fact with the derived one in the MultiDiGraph. Gold must survive regardless of what the
    solver writes afterward, on the one gold day (1629-03-02) scored elsewhere in this suite."""
    graph = build()
    n_gold = add_aligned_to_gold(graph)
    add_aligned_to_solver(graph, ["1629-03-02"])
    gold_after = [
        (u, v, d) for u, v, d in graph.edges(data=True)
        if d.get("kind") == ALIGNED_TO and d["evidence"].observed is True
    ]
    assert len(gold_after) == n_gold  # not one gold edge lost to a same-key overwrite

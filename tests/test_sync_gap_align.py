"""Unit tests for sync_gap_align push + DP₂ short/opening helpers — no full corpus DP."""

from __future__ import annotations

import networkx as nx

from sequence_graph.align import INSERTION_SPLIT, MATCH, AlignedPair, AlignmentResult
from sequence_graph.correspondence import ALIGNED_TO, Evidence
from sequence_graph.nodes import EnrichedResolution, HtrResolution
from sequence_graph.sync_gap_align import (
    CHANNEL_SHORT_OPENING,
    PathBatch,
    build_short_opening_scorer,
    opening_strength,
    push_batches_to_graph,
    taken_read_flats,
)


def test_push_batches_writes_solver_aligned_to():
    graph = nx.MultiDiGraph()
    enriched = EnrichedResolution(date="1629-03-02", index=0)
    htr = HtrResolution.from_flat_id("session-3188-num-58-resolution-1")
    graph.add_node(enriched.node_id, kind="EnrichedResolution", obj=enriched)
    graph.add_node(htr.node_id, kind="HtrResolution", obj=htr)

    result = AlignmentResult(
        pairs=(AlignedPair(MATCH, 0, 0, 0.5),),
        total_cost=0.5,
        n_leading_free=0,
        n_trailing_free=0,
        abstained=False,
    )
    batches = [
        PathBatch(
            tier="projection",
            volgnrs=("1629-03-02_0",),
            flat_ids=("session-3188-num-58-resolution-1",),
            result=result,
            detail={"inventory": "3188"},
        )
    ]
    n = push_batches_to_graph(graph, batches)
    assert n == 1
    edges = list(graph.edges(keys=True, data=True))
    assert len(edges) == 1
    _u, _v, key, data = edges[0]
    assert key == f"{ALIGNED_TO}:solver"
    assert data["kind"] == ALIGNED_TO
    ev: Evidence = data["evidence"]
    assert ev.observed is False
    assert ev.channel == "dp_solver"
    assert ev.source == "sequence_graph.sync_gap_align"
    assert ev.detail["tier"] == "projection"


def test_push_batches_uses_evidence_channel_from_detail():
    graph = nx.MultiDiGraph()
    enriched = EnrichedResolution(date="1626-03-27", index=1)
    htr = HtrResolution.from_flat_id("session-3185-num-57-resolution-2")
    graph.add_node(enriched.node_id, kind="EnrichedResolution", obj=enriched)
    graph.add_node(htr.node_id, kind="HtrResolution", obj=htr)

    result = AlignmentResult(
        pairs=(AlignedPair(MATCH, 0, 0, 0.2),),
        total_cost=0.2,
        n_leading_free=0,
        n_trailing_free=0,
        abstained=False,
    )
    batches = [
        PathBatch(
            tier="trusted_bracket_dp2",
            volgnrs=("1626-03-27_1",),
            flat_ids=("session-3185-num-57-resolution-2",),
            result=result,
            detail={
                "evidence_channel": CHANNEL_SHORT_OPENING,
                "aligner": "dp2_short_opening",
            },
        )
    ]
    n = push_batches_to_graph(graph, batches)
    assert n == 1
    _u, _v, _key, data = list(graph.edges(keys=True, data=True))[0]
    ev: Evidence = data["evidence"]
    assert ev.channel == CHANNEL_SHORT_OPENING
    assert ev.detail["aligner"] == "dp2_short_opening"


def test_opening_strength_open_close_and_open_only():
    open_close = (
        "Ontfangen een Missive van den Ambassadeur, waerop egeen resolutie is gevallen."
    )
    open_only = "Ontfangen een requeste van Jan, ende daernaer andere saecken."
    none = "Is geordonneert dat men sal...."
    assert opening_strength(open_close) == 1.0
    assert opening_strength(open_only) == 0.5
    assert opening_strength(none) == 0.0


def test_taken_read_flats_freezes_match_and_insertion():
    flats = ["a", "b", "c", "d"]
    result = AlignmentResult(
        pairs=(
            AlignedPair(MATCH, 0, 0, 0.1),
            AlignedPair(INSERTION_SPLIT, None, 1, 0.1),
            AlignedPair(MATCH, 1, 3, 0.1),
        ),
        total_cost=0.3,
        n_leading_free=0,
        n_trailing_free=0,
        abstained=False,
    )
    assert taken_read_flats(result, flats) == {"a", "b", "d"}


def test_short_opening_scorer_zero_unless_short_and_opening():
    scorer = build_short_opening_scorer(
        {"1626-01-01_0"},
        {"flat-open": 1.0, "flat-plain": 0.0},
    )
    assert scorer("1626-01-01_0", "flat-open") == 1.0
    assert scorer("1626-01-01_0", "flat-plain") == 0.0
    assert scorer("1626-01-01_9", "flat-open") == 0.0

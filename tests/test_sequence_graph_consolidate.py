"""Stage 3's gate: a genuine partition, enforced, round-trippable; `query` answers all three.

`plans/SEQUENCE_GRAPH_SPINE.md` Stage 3: "dropping one class makes check_partition
raise; a consolidation rebuilt from persisted records equals the live one; query answers for a
session, a date and a scan."
"""

from __future__ import annotations

import pytest

import networkx as nx

from running_axis.tally import PopulationMismatch, Tally, check_partition
from sequence_graph.consolidate import (
    ALIGNED_TO_STATUS,
    CORRESPONDENCE_CLASSES,
    PROBLEM_TYPES,
    Consolidation,
    aligned_to_status,
    build_consolidation,
)
from sequence_graph.correspondence import ALIGNED_TO, Evidence


@pytest.fixture(scope="module")
def consolidation() -> Consolidation:
    return build_consolidation()


def test_correspondence_classes_are_a_genuine_partition(consolidation):
    """323+406+81 = 810 (the old 3-way split) is NOT the whole; the 4th class, wide_window
    (224), is what the old split silently dropped. Checked via check_partition, not summed."""
    tallies = consolidation.correspondence_tallies()
    assert set(tallies) == set(CORRESPONDENCE_CLASSES)
    check_partition(consolidation.whole(), tallies.values())  # must not raise
    assert sum(t.value for t in tallies.values()) == consolidation.whole().value == 1034
    assert tallies["wide_window"].value == 224


def test_problem_types_are_a_genuine_partition(consolidation):
    tallies = consolidation.problem_type_tallies()
    assert set(tallies) == set(PROBLEM_TYPES)
    check_partition(consolidation.whole(), tallies.values())
    assert sum(t.value for t in tallies.values()) == consolidation.whole().value == 1034


def test_dropping_one_class_makes_check_partition_raise(consolidation):
    tallies = list(consolidation.correspondence_tallies().values())
    with pytest.raises(PopulationMismatch):
        check_partition(consolidation.whole(), tallies[:-1])  # one class missing


def test_a_tally_from_an_unregistered_population_cannot_be_checked(consolidation):
    """The registry refuses an unregistered population outright -- the whole point of
    registering a closed taxonomy instead of using a bare string label."""
    from running_axis.tally import POPULATIONS
    with pytest.raises(KeyError):
        POPULATIONS.get("sequence_graph_correspondence_not_a_real_class")


def test_round_trip_through_records_equals_the_live_consolidation(consolidation):
    records = consolidation.to_records()
    rebuilt = Consolidation.from_records(records)
    assert rebuilt.correspondence_tallies() == consolidation.correspondence_tallies()
    assert rebuilt.problem_type_tallies() == consolidation.problem_type_tallies()


def test_t7_stays_in_the_taxonomy_at_zero_rather_than_being_removed(consolidation):
    """The taxonomy is closed by what it classifies, not by what today's data produces."""
    assert consolidation.problem_type_tallies()["T7_nothing_inferred"].value == 0
    assert "T7_nothing_inferred" in PROBLEM_TYPES


def test_aligned_to_status_is_a_genuine_partition_gold_beats_solver():
    """User, 2026-10-09: 'positive clear what is fixed, what is still open, what is missing.'
    A synthetic graph with one of each case -- gold, solver-only, and genuinely unaligned --
    must land in exactly the right bucket, and the three buckets must sum to the whole."""
    graph = nx.MultiDiGraph()
    for index in range(3):
        graph.add_node(f"enriched:x:{index}", kind="EnrichedResolution", obj=None)
    graph.add_node("htr_res:a", kind="HtrResolution", obj=None)
    graph.add_node("htr_res:b", kind="HtrResolution", obj=None)

    graph.add_edge(  # resolution 0: gold-verified
        "enriched:x:0", "htr_res:a", key=f"{ALIGNED_TO}:gold", kind=ALIGNED_TO,
        evidence=Evidence(channel="gold_annotation", source="boundary_gold_sample", observed=True),
    )
    graph.add_edge(  # resolution 1: solver-derived only, no gold
        "enriched:x:1", "htr_res:b", key=f"{ALIGNED_TO}:solver", kind=ALIGNED_TO,
        evidence=Evidence(channel="dp_solver", source="sequence_graph.align", observed=False),
    )
    # resolution 2: no ALIGNED_TO edge at all -- genuinely unaligned

    status = aligned_to_status(graph)
    assert {name: tally.value for name, tally in status.items()} == {
        "gold_verified": 1, "legacy_concordance_only": 0, "solver_derived_only": 1, "unaligned": 1,
    }
    assert sum(t.value for t in status.values()) == 3
    assert set(status) == set(ALIGNED_TO_STATUS)


def test_aligned_to_status_gold_wins_when_a_resolution_has_both():
    """A resolution with BOTH a gold and a solver edge counts once, as gold_verified -- a hard
    fact is never downgraded just because a derived one also exists on the same node."""
    graph = nx.MultiDiGraph()
    graph.add_node("enriched:x:0", kind="EnrichedResolution", obj=None)
    graph.add_node("htr_res:a", kind="HtrResolution", obj=None)
    graph.add_edge(
        "enriched:x:0", "htr_res:a", key=f"{ALIGNED_TO}:gold", kind=ALIGNED_TO,
        evidence=Evidence(channel="gold_annotation", source="boundary_gold_sample", observed=True),
    )
    graph.add_edge(
        "enriched:x:0", "htr_res:a", key=f"{ALIGNED_TO}:solver", kind=ALIGNED_TO,
        evidence=Evidence(channel="dp_solver", source="sequence_graph.align", observed=False),
    )
    status = aligned_to_status(graph)
    assert status["gold_verified"].value == 1
    assert status["solver_derived_only"].value == 0


def test_aligned_to_status_legacy_concordance_outranks_solver_but_not_gold():
    """Priority among the two derived sources: legacy_concordance (the existing, corpus-tested
    production pipeline) outranks solver_derived (today's new, unfitted, barely-tested DP) -- and
    gold still outranks both. Three nodes, one of each shape."""
    graph = nx.MultiDiGraph()
    for index in range(3):
        graph.add_node(f"enriched:x:{index}", kind="EnrichedResolution", obj=None)
    graph.add_node("htr_res:a", kind="HtrResolution", obj=None)

    graph.add_edge(  # has both legacy and solver -- legacy must win
        "enriched:x:0", "htr_res:a", key=f"{ALIGNED_TO}:legacy", kind=ALIGNED_TO,
        evidence=Evidence(channel="legacy_concordance", source="resolution_concordance_1626_1630", observed=False),
    )
    graph.add_edge(
        "enriched:x:0", "htr_res:a", key=f"{ALIGNED_TO}:solver", kind=ALIGNED_TO,
        evidence=Evidence(channel="dp_solver", source="sequence_graph.align", observed=False),
    )
    graph.add_edge(  # has gold AND legacy -- gold must win
        "enriched:x:1", "htr_res:a", key=f"{ALIGNED_TO}:gold", kind=ALIGNED_TO,
        evidence=Evidence(channel="gold_annotation", source="boundary_gold_sample", observed=True),
    )
    graph.add_edge(
        "enriched:x:1", "htr_res:a", key=f"{ALIGNED_TO}:legacy", kind=ALIGNED_TO,
        evidence=Evidence(channel="legacy_concordance", source="resolution_concordance_1626_1630", observed=False),
    )
    # enriched:x:2: no edges at all -- unaligned

    status = aligned_to_status(graph)
    assert status["legacy_concordance_only"].value == 1  # enriched:x:0
    assert status["gold_verified"].value == 1  # enriched:x:1
    assert status["solver_derived_only"].value == 0
    assert status["unaligned"].value == 1  # enriched:x:2

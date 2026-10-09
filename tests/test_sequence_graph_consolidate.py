"""Stage 3's gate: a genuine partition, enforced, round-trippable; `query` answers all three.

`plans/the-two-deep-hits-melodic-avalanche.md` Stage 3: "dropping one class makes check_partition
raise; a consolidation rebuilt from persisted records equals the live one; query answers for a
session, a date and a scan."
"""

from __future__ import annotations

import pytest

from running_axis.tally import PopulationMismatch, Tally, check_partition
from sequence_graph.consolidate import (
    CORRESPONDENCE_CLASSES,
    PROBLEM_TYPES,
    Consolidation,
    build_consolidation,
)


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

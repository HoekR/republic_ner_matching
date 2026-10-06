"""Tests for `running_axis.tally` -- that an ambiguous count cannot be expressed.

Each test names the real incident it prevents. The point is not that the arithmetic is
correct but that the *wrong* arithmetic raises: a bare integer is what let 1,240 / 1,059 /
1,594 / 535 be quoted interchangeably, and what let a one-month gap count stand in for a
corpus one.
"""

from __future__ import annotations

import pytest

from running_axis.tally import (
    AXIS_DATE_LABELS,
    ENRICHED_DATES,
    ENRICHED_RESOLUTIONS,
    ENRICHED_WITH_AXIS_LABEL,
    POPULATIONS,
    Comparison,
    PopulationMismatch,
    ENRICHED_WITHOUT_AXIS_LABEL,
    PopulationRegistry,
    Ratio,
    check_partition,
    Tally,
    Window,
    total,
)

OCT = Window.of("1628-10-01", "1628-10-31")
NOV = Window.of("1628-11-01", "1628-11-30")
ALL = Window.all()


# --- windows ---------------------------------------------------------------------------


def test_window_rejects_backwards_and_overlapping_spans():
    with pytest.raises(ValueError, match="backwards"):
        Window.of("1628-10-31", "1628-10-01")
    with pytest.raises(ValueError, match="overlap"):
        Window((("1628-10-01", "1628-10-31"), ("1628-10-15", "1628-11-30")))


def test_window_disjointness_and_union():
    assert OCT.is_disjoint_from(NOV)
    assert not OCT.is_disjoint_from(ALL)
    merged = OCT.union(NOV)
    assert merged.start == "1628-10-01" and merged.end == "1628-11-30"
    assert len(merged.spans) == 2


def test_window_renders_its_bounds():
    assert str(OCT) == "1628-10-01..1628-10-31"
    assert "2 spans" in str(OCT.union(NOV))


# --- the 1,240 / 1,059 incident --------------------------------------------------------


def test_the_four_date_counts_are_distinguishable_by_name_alone():
    axis = Tally(AXIS_DATE_LABELS, ALL, 1_240)
    enriched = Tally(ENRICHED_DATES, ALL, 1_594)
    both = Tally(ENRICHED_WITH_AXIS_LABEL, ALL, 1_059)
    rendered = {str(t) for t in (axis, enriched, both)}
    assert len(rendered) == 3
    for text in rendered:
        assert "dates" in text and "1626-01-01..1630-12-31" in text


def test_subtracting_two_unrelated_date_populations_raises():
    """1,240 - 1,059 was never a meaningful subtraction: the 1,240 counts axis labels,
    which are not a superset of the enriched dates that carry one."""
    axis = Tally(AXIS_DATE_LABELS, ALL, 1_240)
    both = Tally(ENRICHED_WITH_AXIS_LABEL, ALL, 1_059)
    with pytest.raises(PopulationMismatch, match="not declared a subset"):
        axis - both


def test_subtracting_a_declared_subset_yields_its_complement():
    """1,594 enriched - 1,059 with a label = 535 without one, and the result says so."""
    enriched = Tally(ENRICHED_DATES, ALL, 1_594)
    labelled = Tally(ENRICHED_WITH_AXIS_LABEL, ALL, 1_059)
    remainder = enriched - labelled
    assert remainder.value == 535
    assert remainder.population.name == "enriched_without_axis_label"


def test_partition_of_the_enriched_dates_is_machine_checked():
    enriched = Tally(ENRICHED_DATES, ALL, 1_594)
    with_label = Tally(ENRICHED_WITH_AXIS_LABEL, ALL, 1_059)
    without_label = Tally(ENRICHED_WITHOUT_AXIS_LABEL, ALL, 535)
    check_partition(enriched, [with_label, without_label])


def test_a_partition_that_does_not_account_for_the_whole_fails_loudly():
    enriched = Tally(ENRICHED_DATES, ALL, 1_594)
    with_label = Tally(ENRICHED_WITH_AXIS_LABEL, ALL, 1_059)
    with pytest.raises(PopulationMismatch, match="does not account for"):
        check_partition(enriched, [with_label])


def test_a_partition_part_must_be_a_declared_subset():
    enriched = Tally(ENRICHED_DATES, ALL, 1_594)
    stray = Tally(AXIS_DATE_LABELS, ALL, 1_240)
    with pytest.raises(PopulationMismatch, match="not declared a subset"):
        check_partition(enriched, [stray])


def test_a_subset_must_be_registered_before_the_population_citing_it():
    registry = PopulationRegistry()
    with pytest.raises(KeyError, match="must be registered before"):
        registry.register("part", "dates", "a part", subset_of="whole_not_yet_there")


def test_comparison_prints_both_population_names():
    axis = Tally(AXIS_DATE_LABELS, ALL, 1_240)
    both = Tally(ENRICHED_WITH_AXIS_LABEL, ALL, 1_059)
    comparison = axis.against(both)
    assert comparison.difference == 181
    text = str(comparison)
    assert "axis_date_labels" in text and "enriched_with_axis_label" in text
    assert "+181" in text


def test_same_population_subtraction_stays_in_that_population():
    enriched = Tally(ENRICHED_DATES, ALL, 1_594)
    fewer = Tally(ENRICHED_DATES, ALL, 1_059)
    result = enriched - fewer
    assert result.value == 535
    assert result.population is ENRICHED_DATES


# --- the three-gap-counts incident -----------------------------------------------------


def test_a_one_month_tally_cannot_be_added_to_a_corpus_tally():
    """120 gaps from 1628-10 and a full-window count are not summable."""
    month = Tally(ENRICHED_RESOLUTIONS, OCT, 230)
    corpus = Tally(ENRICHED_RESOLUTIONS, ALL, 19_120)
    with pytest.raises(PopulationMismatch, match="overlapping windows"):
        month + corpus


def test_disjoint_months_sum_to_their_union():
    october = Tally(ENRICHED_RESOLUTIONS, OCT, 230)
    november = Tally(ENRICHED_RESOLUTIONS, NOV, 180)
    combined = october + november
    assert combined.value == 410
    assert combined.window.spans == OCT.union(NOV).spans


def test_total_sums_disjoint_windows_and_refuses_overlaps():
    months = [
        Tally(ENRICHED_RESOLUTIONS, Window.of(f"1628-{m:02d}-01", f"1628-{m:02d}-28"), m)
        for m in (1, 2, 3)
    ]
    assert total(months).value == 6
    with pytest.raises(PopulationMismatch):
        total([months[0], months[0]])


def test_total_refuses_an_empty_sequence():
    with pytest.raises(ValueError, match="nothing to total"):
        total([])


def test_a_tally_always_renders_its_window():
    """The on-disk ledger said '120 gaps' with nothing naming its one-month window."""
    assert "1628-10-01..1628-10-31" in str(Tally(ENRICHED_RESOLUTIONS, OCT, 120))


# --- shares cannot be quoted bare ------------------------------------------------------


def test_ratio_names_both_sides():
    recoverable = Tally(ENRICHED_RESOLUTIONS, ALL, 983)
    no_axis = Tally(ENRICHED_RESOLUTIONS, ALL, 5_590)
    ratio = recoverable.over(no_axis)
    assert ratio.value == pytest.approx(983 / 5590)
    text = str(ratio)
    assert "983" in text and "5,590" in text and "17.6%" in text


def test_ratio_refuses_to_mix_units():
    """A count of dates is not a share of resolutions."""
    dates = Tally(ENRICHED_DATES, ALL, 66)
    resolutions = Tally(ENRICHED_RESOLUTIONS, ALL, 5_590)
    with pytest.raises(PopulationMismatch, match="one unit"):
        Ratio(numerator=dates, denominator=resolutions)


def test_ratio_refuses_to_mix_windows():
    month = Tally(ENRICHED_RESOLUTIONS, OCT, 10)
    corpus = Tally(ENRICHED_RESOLUTIONS, ALL, 100)
    with pytest.raises(PopulationMismatch, match="one window"):
        Ratio(numerator=month, denominator=corpus)


def test_empty_denominator_is_a_finding_not_a_zero_share():
    """The Group C existence check's base rate of exactly 100% came from this shape."""
    numerator = Tally(ENRICHED_RESOLUTIONS, OCT, 0)
    denominator = Tally(ENRICHED_RESOLUTIONS, OCT, 0)
    with pytest.raises(ZeroDivisionError, match="is a finding"):
        numerator.over(denominator).value


# --- the registry is closed ------------------------------------------------------------


def test_an_unregistered_population_cannot_be_counted():
    with pytest.raises(KeyError, match="not registered"):
        POPULATIONS.get("gaps_of_some_kind")


def test_the_refusal_lists_what_is_known():
    registry = PopulationRegistry()
    registry.register("placed", "resolutions", "Resolutions with a paragraph assignment.")
    with pytest.raises(KeyError, match="Known: placed"):
        registry.get("unplaced")


def test_a_population_cannot_be_redefined_silently():
    registry = PopulationRegistry()
    registry.register("placed", "resolutions", "first definition")
    with pytest.raises(ValueError, match="already registered"):
        registry.register("placed", "resolutions", "a different definition")


def test_registered_populations_carry_a_definition_and_attribution():
    population = POPULATIONS.get("enriched_without_axis_label")
    assert population.attribution == "axis_label"
    assert "NOT the same as" in population.definition, "the trap must be documented in place"
    assert str(population) == "enriched_without_axis_label[dates/axis_label]"


def test_negative_tallies_are_rejected():
    with pytest.raises(ValueError, match="negative tally"):
        Tally(ENRICHED_DATES, ALL, -1)

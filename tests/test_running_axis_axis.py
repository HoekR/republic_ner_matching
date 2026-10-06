"""Tests for `running_axis.axis` -- addressability, views, and order-preserving mutation.

Most tests build a `RunningAxis` directly from spans and date states rather than through
`load()`, so they are fast and independent of the real datasets. The last few read the real
corpus and are the regression guard on the figures this model was built to correct.
"""

from __future__ import annotations

import pytest

from running_axis.axis import (
    ADDRESSABILITY,
    DateState,
    MonotonicityError,
    RunningAxis,
    SessionSpan,
)
from running_axis.tally import PopulationMismatch, Window, total


def session(num, begin, end, label_dates=(), resolved_dates=(), inventory="3187"):
    return SessionSpan(
        session_id=f"session-{inventory}-num-{num}",
        inventory=inventory,
        session_num=num,
        char_begin=begin,
        char_end=end,
        paragraph_count=2,
        label_dates=tuple(label_dates),
        resolved_dates=tuple(resolved_dates),
    )


def date_state(date, k_e=5, status="resolved_auto", resolved=None, labelled=False):
    return DateState(
        date=date,
        k_e=k_e,
        status=status,
        inventory="3187",
        resolved_session_id=resolved,
        has_axis_label=labelled,
    )


def small_axis():
    """One of each addressability class, so the partition has every branch populated."""
    sessions = {
        "session-3187-num-1": session(1, 0, 100, label_dates=("1628-10-01",), resolved_dates=("1628-10-01",)),
        "session-3187-num-2": session(2, 100, 200, label_dates=("1628-10-01",), resolved_dates=("1628-10-03",)),
    }
    dates = {
        "1628-10-01": date_state("1628-10-01", 10, resolved="session-3187-num-1", labelled=True),
        "1628-10-03": date_state("1628-10-03", 7, status="cross_day_shift", resolved="session-3187-num-2"),
        "1628-10-04": date_state("1628-10-04", 1, status="nihil_actum"),
        "1628-10-31": date_state("1628-10-31", 9, status="missing_htr"),
    }
    return RunningAxis({}, sessions, dates)


# --- addressability ------------------------------------------------------------------


def test_addressability_covers_each_class():
    axis = small_axis()
    assert axis.dates["1628-10-01"].addressability == "labelled"
    assert axis.dates["1628-10-03"].addressability == "dropped_by_label_grouping"
    assert axis.dates["1628-10-04"].addressability == "nihil_actum"
    assert axis.dates["1628-10-31"].addressability == "no_session"


def test_a_pinned_date_is_not_no_session_even_without_a_label():
    """The ledger defect: this date has a resolved session and was still filed as no_axis."""
    state = date_state("1628-10-03", resolved="session-3187-num-2", labelled=False)
    assert state.is_pinned
    assert state.addressability == "dropped_by_label_grouping"


def test_every_date_gets_exactly_one_class():
    axis = small_axis()
    for state in axis.dates.values():
        assert state.addressability in ADDRESSABILITY


# --- reporting -----------------------------------------------------------------------


def test_report_partitions_both_units():
    """report() asserts its own arithmetic; this test is that the assertion runs."""
    report = small_axis().view("1628-10-01", "1628-10-31").report()
    assert report["enriched_dates"].value == 4
    assert report["enriched_resolutions"].value == 27
    assert sum(report[f"dates_{n}"].value for n in ADDRESSABILITY) == 4
    assert sum(report[f"resolutions_{n}"].value for n in ADDRESSABILITY) == 27


def test_every_reported_figure_names_its_window():
    report = small_axis().view("1628-10-01", "1628-10-31").report()
    for tally in report.values():
        assert str(tally.window) == "1628-10-01..1628-10-31"
        assert "1628-10-01..1628-10-31" in str(tally)


def test_report_values_are_tallies_not_integers():
    for tally in small_axis().view("1628-10-01", "1628-10-31").report().values():
        assert not isinstance(tally, int)
        assert tally.population.unit in {"dates", "resolutions", "sessions"}


def test_session_count_is_window_scoped_not_the_corpus_total():
    """The script printed a coverage-wide session count beside window tallies, which is the
    exact ambiguity this package exists to prevent."""
    axis = small_axis()
    assert len(axis.sessions) == 2, "two sessions exist across the whole coverage"
    empty = axis.view("1628-10-06", "1628-10-30").report()["axis_sessions"]
    assert empty.value == 0, "a window claiming no session must not inherit the corpus total"
    assert str(empty.window) == "1628-10-06..1628-10-30"
    wide = axis.view("1628-10-01", "1628-10-31").report()["axis_sessions"]
    assert wide.value == 2


def test_a_session_enters_a_window_by_either_attribution():
    """session-3187-num-2 is labelled 1628-10-01 but resolved to 10-03, so it belongs to a
    window containing either date -- which is the whole point of carrying both."""
    axis = small_axis()
    by_label = axis.view("1628-10-01", "1628-10-02").report()["axis_sessions"]
    assert by_label.value == 2
    by_resolution = axis.view("1628-10-03", "1628-10-03").report()["axis_sessions"]
    assert [s.session_id for s in axis.view("1628-10-03", "1628-10-03").sessions] == [
        "session-3187-num-2"
    ]
    assert by_resolution.value == 1


# --- views ---------------------------------------------------------------------------


def test_view_filters_to_its_window():
    axis = small_axis()
    assert [d.date for d in axis.view("1628-10-01", "1628-10-03").dates] == [
        "1628-10-01",
        "1628-10-03",
    ]
    assert len(axis.view("1628-10-01", "1628-10-31").dates) == 4


def test_disjoint_views_sum_to_the_wider_view():
    axis = small_axis()
    early = axis.view("1628-10-01", "1628-10-02").report()["enriched_resolutions"]
    late = axis.view("1628-10-03", "1628-10-31").report()["enriched_resolutions"]
    whole = axis.view("1628-10-01", "1628-10-31").report()["enriched_resolutions"]
    assert total([early, late]).value == whole.value


def test_overlapping_views_cannot_be_summed():
    axis = small_axis()
    left = axis.view("1628-10-01", "1628-10-10").report()["enriched_resolutions"]
    right = axis.view("1628-10-05", "1628-10-31").report()["enriched_resolutions"]
    with pytest.raises(PopulationMismatch, match="overlapping windows"):
        left + right


def test_out_of_coverage_raises_rather_than_returning_zeros():
    axis = small_axis()
    with pytest.raises(KeyError, match="outside this model's coverage"):
        axis.view("1700-01-01", "1700-12-31")


def test_backwards_window_is_rejected():
    with pytest.raises(ValueError, match="backwards"):
        small_axis().view("1628-10-31", "1628-10-01")


def test_state_for_is_the_same_entry_point_as_view():
    axis = small_axis()
    assert axis.state_for("1628-10-01", "1628-10-31").window == Window.of(
        "1628-10-01", "1628-10-31"
    )


# --- mutation ------------------------------------------------------------------------


def test_place_anchor_pins_a_date_and_shares_the_session():
    axis = small_axis()
    axis.place_anchor("1628-10-31", "session-3187-num-2")
    assert axis.dates["1628-10-31"].resolved_session_id == "session-3187-num-2"
    assert axis.sessions["session-3187-num-2"].is_shared
    assert axis.dates["1628-10-31"].addressability == "dropped_by_label_grouping"


def test_place_anchor_rejects_an_inverting_pin():
    """10-31 cannot sit on session 1 while 10-03 sits on session 2."""
    axis = small_axis()
    with pytest.raises(MonotonicityError, match="inverts"):
        axis.place_anchor("1628-10-31", "session-3187-num-1")


def test_place_anchor_rejects_unknown_date_or_session():
    axis = small_axis()
    with pytest.raises(KeyError):
        axis.place_anchor("1699-01-01", "session-3187-num-1")
    with pytest.raises(KeyError):
        axis.place_anchor("1628-10-05", "session-3187-num-99")


def test_shift_anchor_moves_a_pin():
    axis = small_axis()
    axis.place_anchor("1628-10-31", "session-3187-num-2")
    axis.shift_anchor("1628-10-31", "session-3187-num-2")
    assert axis.dates["1628-10-31"].resolved_session_id == "session-3187-num-2"


def test_moving_a_date_onto_an_earlier_dates_session_is_sharing_not_inversion():
    axis = small_axis()
    axis.shift_anchor("1628-10-03", "session-3187-num-1")
    assert axis.sessions["session-3187-num-1"].resolved_dates == (
        "1628-10-01",
        "1628-10-03",
    )


def test_shift_anchor_rolls_back_when_the_move_would_invert():
    """A failed mutation must not leave the model half-moved."""
    axis = small_axis()
    axis.place_anchor("1628-10-31", "session-3187-num-2")
    with pytest.raises(MonotonicityError):
        axis.shift_anchor("1628-10-31", "session-3187-num-1")
    assert axis.dates["1628-10-31"].resolved_session_id == "session-3187-num-2"
    assert "1628-10-31" in axis.sessions["session-3187-num-2"].resolved_dates


def test_a_shared_session_is_not_an_inversion():
    """Two dates on one session is the archive's own behaviour, not disorder."""
    axis = small_axis()
    axis.place_anchor("1628-10-31", "session-3187-num-2")
    assert axis.sessions["session-3187-num-2"].resolved_dates == (
        "1628-10-03",
        "1628-10-31",
    )


# --- snapshot ------------------------------------------------------------------------


def test_snapshot_separates_coverage_totals_from_any_window():
    """Coverage-wide figures live under a key that says so, never beside window counts."""
    records = small_axis().snapshot()
    meta = records[0]
    assert meta["record_type"] == "meta"
    assert meta["coverage"] == {"start": "1628-10-01", "end": "1628-10-31"}
    assert set(meta["coverage_totals"]) == {
        "inventories",
        "paragraphs",
        "characters",
        "sessions",
        "enriched_dates",
    }
    assert "window" not in meta, "a bare 'window' key invited reading these as window-scoped"
    assert sum(1 for r in records if r["record_type"] == "session") == 2
    assert sum(1 for r in records if r["record_type"] == "date") == 4
    dates = [r for r in records if r["record_type"] == "date"]
    assert all("addressability" in r for r in dates)


# --- the real corpus -----------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus():
    return RunningAxis.load()


def test_corpus_addressability_partition(corpus):
    report = corpus.view("1626-01-01", "1630-12-31").report()
    assert report["enriched_dates"].value == 1_594
    assert report["dates_labelled"].value == 1_059
    assert report["dates_dropped_by_label_grouping"].value == 66
    assert report["dates_nihil_actum"].value == 125
    assert report["dates_no_session"].value == 344
    assert report["enriched_resolutions"].value == 19_120
    assert report["resolutions_dropped_by_label_grouping"].value == 983
    assert report["resolutions_no_session"].value == 4_482


def test_october_1628_decomposes_instead_of_being_dropped(corpus):
    """The ledger called all 16 of these no_axis under one fabricated inventory."""
    report = corpus.view("1628-10-01", "1628-10-31").report()
    assert report["enriched_dates"].value == 31
    assert report["dates_labelled"].value == 15
    assert report["dates_dropped_by_label_grouping"].value == 3
    assert report["dates_nihil_actum"].value == 2
    assert report["dates_no_session"].value == 11


def test_corpus_month_views_sum_to_the_year(corpus):
    months = [
        corpus.view(f"1628-{m:02d}-01", f"1628-{m:02d}-31").report()["enriched_resolutions"]
        for m in range(1, 13)
    ]
    year = corpus.view("1628-01-01", "1628-12-31").report()["enriched_resolutions"]
    assert total(months).value == year.value


def test_shared_session_is_representable(corpus):
    """session-3185-num-56 carries a 28 March heading inside a 27 March session; the
    ledger gives it one date, so the model must be able to hold both."""
    corpus.place_anchor("1626-03-28", "session-3185-num-56")
    shared = corpus.sessions["session-3185-num-56"]
    assert shared.resolved_dates == ("1626-03-27", "1626-03-28")
    assert shared.is_shared

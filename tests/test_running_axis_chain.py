"""Tests for `running_axis.chain` -- gap buckets and session brackets.

The two integration tests at the end are the point of the module: the model must reproduce
`s6b_known_point_ledger` and `session_offset_eval` digit for digit, because an accounting that
quietly disagrees with the scripts it replaces is worse than no accounting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from running_axis.axis import DateState, RunningAxis, SessionSpan
from running_axis.chain import (
    BUCKETS,
    NEARLY_DETERMINED,
    GapLedger,
    KnownPoint,
    bucket_of,
    build_brackets,
    gaps_from_chain,
)
from running_axis.tally import Window

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OCT = Window.of("1628-10-01", "1628-10-31")


def point(index, char, *kinds):
    return {"enriched_index": index, "char_position": char, "kinds": list(kinds)}


# --- buckets -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size,expected",
    [(0, "determined"), (1, "nearly_determined"), (2, "nearly_determined"), (3, "open"), (9, "open")],
)
def test_bucket_boundaries(size, expected):
    assert bucket_of(size) == expected


def test_nearly_determined_threshold_is_the_ledgers():
    assert NEARLY_DETERMINED == 2


# --- gaps ----------------------------------------------------------------------------


def test_gaps_are_one_per_adjacent_pair():
    chain = [point(0, 0, "session_start"), point(3, 500), point(4, 900, "session_end")]
    gaps = gaps_from_chain(chain)
    assert len(gaps) == 2
    assert [g.resolutions_in_gap for g in gaps] == [2, 0]
    assert [g.char_span for g in gaps] == [500, 400]


def test_a_single_point_chain_has_no_gaps():
    assert gaps_from_chain([point(0, 0)]) == []
    assert gaps_from_chain([]) == []


def test_gap_dict_matches_the_ledgers_field_names():
    gap = gaps_from_chain([point(0, 0, "session_start"), point(2, 10, "session_end")])[0]
    assert set(gap.to_dict()) == {
        "left_kinds",
        "right_kinds",
        "left_enriched_index",
        "right_enriched_index",
        "resolutions_in_gap",
        "char_span",
    }
    assert gap.to_dict()["resolutions_in_gap"] == 1


def test_known_point_accepts_objects_as_well_as_dicts():
    gaps = gaps_from_chain([KnownPoint(0, 0), KnownPoint(5, 100)])
    assert gaps[0].resolutions_in_gap == 4


# --- the ledger ----------------------------------------------------------------------


def test_gap_ledger_buckets_and_weights():
    ledger = GapLedger(OCT)
    ledger.add_day([point(0, 0), point(1, 100), point(5, 400)])  # 0-gap then a 3-gap
    report = ledger.report()
    assert report["gaps_total"].value == 2
    assert report["gaps_determined"].value == 1
    assert report["gap_chars_determined"].value == 100
    assert report["gaps_open"].value == 1
    assert report["gap_resolutions_open"].value == 3
    assert report["gap_chars_open"].value == 300


def test_gap_ledger_reports_both_disagreeing_shares_together():
    """A 0-gap is a row but no work, so the two shares differ and neither stands alone."""
    ledger = GapLedger(OCT)
    for _ in range(9):
        ledger.add_day([point(0, 0), point(1, 10)])
    ledger.add_day([point(0, 0), point(6, 50)])
    shares = ledger.shares()
    assert set(shares) == {"settled_share_by_gap", "open_share_by_resolution"}
    assert shares["settled_share_by_gap"] == pytest.approx(0.9)
    assert shares["open_share_by_resolution"] == pytest.approx(1.0)


def test_every_ledger_figure_names_its_window():
    ledger = GapLedger(OCT)
    ledger.add_day([point(0, 0), point(1, 10)])
    for tally in ledger.report().values():
        assert str(tally.window) == "1628-10-01..1628-10-31"


# --- brackets ------------------------------------------------------------------------


def bracket_axis():
    sessions = {
        f"session-3187-num-{n}": SessionSpan(
            session_id=f"session-3187-num-{n}",
            inventory="3187",
            session_num=n,
            char_begin=n * 100,
            char_end=(n + 1) * 100,
            paragraph_count=2,
            resolved_dates=tuple(resolved),
        )
        for n, resolved in {1: ("1628-10-01",), 2: (), 3: ("1628-10-05",)}.items()
    }
    dates = {
        "1628-10-01": DateState("1628-10-01", 5, "resolved_auto", "3187", "session-3187-num-1", True, "3187"),
        "1628-10-03": DateState("1628-10-03", 7, "missing_htr", "3187", None, False, None),
        "1628-10-05": DateState("1628-10-05", 4, "resolved_auto", "3187", "session-3187-num-3", True, "3187"),
    }
    return RunningAxis({}, sessions, dates)


def test_a_bracket_with_equal_supply_and_demand_is_determined():
    brackets = build_brackets(bracket_axis())
    interior = [b for b in brackets if b.kind == "interior"]
    assert len(interior) == 1
    assert interior[0].bracket_class == "determined"
    assert interior[0].n_e == interior[0].n_h == 1
    assert interior[0].unresolved_dates == ("1628-10-03",)
    assert interior[0].unclaimed_sessions == ("session-3187-num-2",)
    assert interior[0].unresolved_k_e == 7


def test_nihil_dates_are_dropped_before_ranking():
    """A nihil sitting consumes no HTR session, so counting it shifts every later position."""
    axis = bracket_axis()
    axis.dates["1628-10-02"] = DateState("1628-10-02", 1, "nihil_actum", "3187", None, False, None)
    interior = [b for b in build_brackets(axis) if b.kind == "interior"]
    assert interior[0].unresolved_dates == ("1628-10-03",)


def test_an_unclaimed_session_is_counted_in_only_one_bracket():
    brackets = build_brackets(bracket_axis())
    seen = [s for b in brackets for s in b.unclaimed_sessions]
    assert len(seen) == len(set(seen))


def test_head_and_tail_brackets_exist_and_are_typed():
    kinds = {b.kind for b in build_brackets(bracket_axis())}
    assert {"head", "interior", "tail"} <= kinds


# --- reproducing the scripts ---------------------------------------------------------


def test_reproduces_s6b_known_point_ledger_field_for_field():
    """Same chains in, same accounting out -- counts, char spans and both shares."""
    path = PROJECT_ROOT / "output" / "s6b_known_point_ledger.jsonl"
    if not path.exists():
        pytest.skip("s6b_known_point_ledger output not built")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    report, days = lines[0], [r for r in lines[1:] if r.get("date")]
    window = report["window"]
    ledger = GapLedger(Window.of(window["start"], window["end"]))
    for day in days:
        ledger.add_day(day["chain"])

    mine, theirs = ledger.report(), report["overall"]
    assert mine["gaps_total"].value == theirs["gaps"]
    for bucket in BUCKETS:
        assert mine[f"gaps_{bucket}"].value == theirs["buckets"][bucket]["gaps"]
        assert mine[f"gap_resolutions_{bucket}"].value == theirs["buckets"][bucket]["resolutions"]
        assert mine[f"gap_chars_{bucket}"].value == theirs["buckets"][bucket]["chars"]
    shares = ledger.shares()
    assert shares["settled_share_by_gap"] == pytest.approx(theirs["settled_share_by_gap"])
    assert shares["open_share_by_resolution"] == pytest.approx(theirs["open_share_by_resolution"])


def test_reproduces_session_offset_eval_with_one_documented_difference():
    """Sittings and determined pairings match exactly; unclaimed sessions differ by the
    184 beyond the enriched edition, which session_offset_eval drops via
    restrict_to_enriched_span and this model deliberately keeps visible."""
    path = PROJECT_ROOT / "output" / "session_offset_eval.jsonl"
    if not path.exists():
        pytest.skip("session_offset_eval output not built")
    theirs = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    brackets = build_brackets(RunningAxis.load())

    assert sum(b.n_e for b in brackets) == theirs["unresolved_sittings"]
    assert sum(b.unresolved_k_e for b in brackets) == theirs["unresolved_k_e"]
    determined = [b for b in brackets if b.bracket_class == "determined"]
    assert sum(b.n_e for b in determined) == theirs["determined_sittings"]
    assert sum(b.unresolved_k_e for b in determined) == theirs["determined_k_e"]
    assert sum(b.n_h for b in brackets) == (
        theirs["unclaimed_sessions"] + theirs["sessions_beyond_enriched_edition"]
    )

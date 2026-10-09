"""The corpus scope bar is a user rule, so it gets a test, not just a docstring.

Rule (user, 2026-09-25, restated FULL STOP 2026-10-08): the enriched XML edition ends 1630-05-14;
dates after it are not reconsidered and scans or HTR text after it are not taken into account.
It was already written in `plans/COLLISION_AVOIDANCE_TRACK.md` and enforced for one data shape by
`session_offset_eval.restrict_to_enriched_span`, and it was still broken on 2026-10-08 by work on
a different shape. These tests pin the shape-agnostic primitive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.corpus_scope import (
    MAIN_SERIES,
    SIDELINED_INVENTORIES,
    assert_no_sidelined,
    inventory_of,
    is_main_series,
    is_sidelined,
    series_meta,
    split_main_series,
    suspicious_secret_dates,
    EXPECTED_END,
    SCOPE_RULE,
    drop_out_of_scope,
    in_scope,
    split_by_scope,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_the_bar_is_the_date_the_rule_names():
    assert EXPECTED_END == "1630-05-14"


@pytest.mark.parametrize(
    "date",
    ["1626-01-01", "1630-05-13", "1630-05-14", pd.Period("1630-05-14", freq="D")],
)
def test_on_or_before_the_bar_is_in_scope(date):
    assert in_scope(date)


@pytest.mark.parametrize(
    "date",
    [
        "1630-05-15",
        "1630-05-29",  # the first of the 47 days wrongly reported as unaccounted room
        "1630-12-09",  # the last of them
        "1630-12-31",  # where the HTR axis actually ends
        pd.Period("1630-06-01", freq="D"),
    ],
)
def test_after_the_bar_is_out_of_scope(date):
    assert not in_scope(date)


@pytest.mark.parametrize("value", [None, "", "unknown", "None", "n/a"])
def test_unparseable_is_out_of_scope_not_in(value):
    """A missing date must never be admitted by default -- fail closed, not open."""
    assert not in_scope(value)


def test_drop_out_of_scope_splits_any_shape():
    """The leak happened because the only helper needed a DataFrame. Tuples must work too."""
    anchors = [
        ("3189", 253, "1630-05-29"),
        ("3185", 10, "1626-02-01"),
        ("3189", 590, "1630-12-09"),
    ]
    kept, dropped = drop_out_of_scope(anchors, key=lambda a: a[2])
    assert [a[0] for a in kept] == ["3185"]
    assert len(dropped) == 2


def test_split_by_scope_on_a_frame():
    frame = pd.DataFrame({"date": ["1630-05-14", "1630-05-15"], "scans": [2, 3]})
    kept, dropped = split_by_scope(frame, "date")
    assert list(kept["date"]) == ["1630-05-14"]
    assert list(dropped["date"]) == ["1630-05-15"]
    assert kept["scans"].sum() == 2


def test_rule_text_states_the_prohibition_not_just_the_date():
    for phrase in ("1630-05-14", "not taken into account", "denominator"):
        assert phrase in SCOPE_RULE


# --------------------------------------------------------------------------------------------
# Sidelining the secret series (user, 2026-10-08). Executable for the same reason the scope bar
# is: it existed as a per-script constant, was imported by name, and got breached anyway.
# --------------------------------------------------------------------------------------------


def test_main_series_is_the_five_ordinary_registers():
    assert MAIN_SERIES == frozenset({"3185", "3186", "3187", "3188", "3189"})
    assert SIDELINED_INVENTORIES == frozenset({"4562", "4861"})
    assert not (MAIN_SERIES & SIDELINED_INVENTORIES)


def test_inventory_is_read_from_both_id_styles():
    assert inventory_of("session-3185-num-12") == "3185"
    assert inventory_of("NL-HaNA_1.01.02_3187_0190") == "3187"
    assert inventory_of("session-4562-num-164-resolution-2") == "4562"
    assert inventory_of("nonsense") is None


def test_secret_series_is_sidelined_and_main_series_is_not():
    assert is_sidelined("session-4562-num-164")
    assert is_sidelined("session-4861-num-3")
    assert not is_sidelined("session-3185-num-1")
    assert is_main_series("session-3189-num-77")
    assert not is_main_series("session-4562-num-164")


def test_sidelining_fails_OPEN_unlike_the_scope_bar():
    """An unreadable id must not be silently sidelined -- that would hide main-series work.

    Deliberately opposite to `in_scope`, which fails closed because including post-bar material
    corrupts a result.
    """
    assert not is_sidelined(None)
    assert not is_sidelined("nonsense")
    assert not is_main_series(None)
    assert not is_main_series("nonsense")


def test_split_main_series_partitions_without_loss():
    frame = pd.DataFrame({"session_id": [
        "session-3185-num-1", "session-4562-num-164", "session-3189-num-77",
        "session-4861-num-3", "nonsense",
    ]})
    main, other = split_main_series(frame, "session_id")
    assert len(main) == 2
    assert len(other) == 3  # two sidelined plus the unreadable one
    assert len(main) + len(other) == len(frame)


def test_series_meta_records_the_tautology_that_makes_n_e_zero_meaningless():
    meta = series_meta()
    assert meta["sidelined_inventories"] == ["4562", "4861"]
    assert "tautology" in meta["sidelining_rule"]


# ------------------------------------------------------------------------------------------
# assert_no_sidelined: the 2026-10-08 false-positive regression.
#
# A first version of this check serialised each row to JSON and searched for the literal
# text "4562"/"4861". That matched inside 14562 (a character count) and 0.4562 (a
# probability) as readily as inside a real session id -- a false "verification" that
# reported sidelined material was absent when it was not being tested at all. The fix
# is: only STRING fields are ever tested, and each through `is_sidelined`, never text
# containment on a serialised form. These are the exact values that fooled the old check.
# ------------------------------------------------------------------------------------------


def test_assert_no_sidelined_does_not_false_positive_on_14562_as_a_count():
    """14562 as an integer (a character count, e.g.) must never be read as inventory 4562."""
    frame = pd.DataFrame({"session_id": ["session-3185-num-1"], "char_length": [14562]})
    assert_no_sidelined(frame)  # must not raise


def test_assert_no_sidelined_does_not_false_positive_on_0_4562_as_a_probability():
    """0.4562 as a float (a probability, e.g.) must never be read as inventory 4562."""
    frame = pd.DataFrame({"session_id": ["session-3188-num-9"], "p_room_improbably_large": [0.4562]})
    assert_no_sidelined(frame)  # must not raise


def test_assert_no_sidelined_catches_a_sidelined_id_nested_in_a_list_field():
    records = [{
        "session_id": "session-3185-num-1",
        "unclaimed_sessions": ["session-3185-num-2", "session-4562-num-9"],
    }]
    with pytest.raises(AssertionError, match="session-4562-num-9"):
        assert_no_sidelined(records)


def test_assert_no_sidelined_catches_a_sidelined_id_in_a_named_column():
    frame = pd.DataFrame({"inventory": ["3185", "4861"]})
    with pytest.raises(AssertionError):
        assert_no_sidelined(frame, "inventory")


def test_assert_no_sidelined_narrows_to_one_column_when_given():
    """A sidelined id elsewhere in the row must not trip the check when `column` is given."""
    frame = pd.DataFrame({
        "inventory": ["3185"],
        "unrelated_note": ["session-4562-num-1 was considered and rejected"],
    })
    assert_no_sidelined(frame, "inventory")  # must not raise -- only 'inventory' is checked


def test_assert_no_sidelined_accepts_an_iterable_of_plain_dicts():
    assert_no_sidelined([{"session_id": "session-3189-num-1"}])  # must not raise


# ------------------------------------------------------------------------------------------
# suspicious_secret_dates: decision 2026-10-08 -- sideline by LEDGER, not by secrecy.
# ------------------------------------------------------------------------------------------


def test_suspicious_secret_dates_is_disjoint_from_sidelined_dates():
    from scripts.corpus_scope import sidelined_dates

    suspicious = suspicious_secret_dates()
    sidelined = sidelined_dates()
    assert suspicious, "expected the measured 73-date population to be non-empty"
    assert not (suspicious & sidelined), (
        "a date cannot be both sidelined (ledger states 4562/4861) and suspicious "
        "(ledger states a main-series inventory) -- the two criteria are disjoint by construction"
    )


def test_series_meta_carries_the_suspicious_count_and_does_not_sideline_it():
    meta = series_meta()
    assert meta["suspicious_secret_dates_count"] == len(suspicious_secret_dates())
    assert "LEDGER" in meta["suspicious_secret_dates_rule"]


# ------------------------------------------------------------------------------------------
# FUNCTIONAL: the guard against the real pipeline output, not against synthetic rows.
#
# The unit tests above prove `assert_no_sidelined` is logically correct on hand-built data.
# They do not prove the real sequence datasets are clean -- that was exactly the gap on
# 2026-10-08: a "verification" ran, reported zero hits, and was wrong, because it tested the
# wrong thing (JSON-substring containment) rather than because the logic it meant to apply was
# untested. A unit test on synthetic rows cannot catch that class of error; only running the
# guard against what the scripts actually wrote can. Follows the established pattern in
# `tests/test_running_axis_chain.py` ("reproducing the scripts"): read the real `.jsonl` output
# directly, skip if a script has not been run yet, never regenerate it here.
# ------------------------------------------------------------------------------------------

SEQUENCE_OUTPUTS = [
    "sequence_reconciliation.jsonl",
    "bracket_business_ledger.jsonl",
    "bracket_gap_census.jsonl",
    "scan_gap_findings.jsonl",
]


def _load_jsonl(name: str) -> list[dict]:
    path = PROJECT_ROOT / "output" / name
    if not path.exists():
        pytest.skip(f"{name} not built")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("name", SEQUENCE_OUTPUTS)
def test_no_sidelined_material_in_real_sequence_output(name):
    """Every sequence-track dataset that scripts/corpus_scope.py's guard is meant to protect,
    checked against what is actually on disk right now -- not a stand-in for it."""
    records = _load_jsonl(name)
    data_rows = [r for r in records if r.get("record_type") not in (None, "meta")]
    assert data_rows, f"{name} has no data rows to check (only meta/empty)"
    assert_no_sidelined(data_rows)


def test_real_sequence_output_actually_exercises_the_recursive_walk():
    """A guard that only ever sees clean data proves nothing about the regression it exists for.
    Confirm the real rows, pooled across all four sequence datasets, contain the false-positive
    bait (an int > 9999, a float in (0, 1), a populated list field) so a silent reversion to
    substring matching would have a chance to be caught by the test above, not only by the
    synthetic unit tests. No single dataset carries all three shapes -- measured: sequence_
    reconciliation and bracket_gap_census carry the large ints, bracket_business_ledger and
    scan_gap_findings carry the small floats, and every one of the four carries list fields."""
    data_rows = [
        r
        for name in SEQUENCE_OUTPUTS
        for r in _load_jsonl(name)
        if r.get("record_type") not in (None, "meta")
    ]
    values = [v for row in data_rows for v in row.values()]
    has_large_int = any(isinstance(v, int) and v > 9999 for v in values)
    has_small_float = any(isinstance(v, float) and 0 < v < 1 for v in values)
    has_list_field = any(isinstance(v, list) and v for v in values)
    assert has_large_int, "expected a real row with an int > 9999 (the 14562-style bait)"
    assert has_small_float, "expected a real row with a float in (0, 1) (the 0.4562-style bait)"
    assert has_list_field, "expected a real row with a populated list field"

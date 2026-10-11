"""Duplicate-session split proposals -- machine-gated, not a human review queue.

User 2026-10-09: persist map half; will not review all proposed pins. Gate accepts/rejects
aggregates. No PINNED_TO / production mutation.
"""

from __future__ import annotations

import pytest

from sequence_graph.duplicate_sessions import (
    _proposed_ranges,
    _structural_ok,
    gate_duplicate_session_splits,
    held_out_ok,
    resolve_duplicate_session_claims,
)


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return resolve_duplicate_session_claims()


@pytest.fixture(scope="module")
def axis_and_concordance():
    from data_io import load
    from scripts.s6_duplicate_session_date_headings import session_paragraphs

    axis = load("paragraph_axis_1626_1630")
    return session_paragraphs(axis), load("resolution_concordance_1626_1630")


def test_resolve_covers_in_scope_main_series_duplicates(records):
    """67 corpus-wide; 3 are sidelined 4562 -- main-series in-scope population is 64."""
    assert len(records) == 64
    assert all(r["session"].startswith("session-318") for r in records)


def test_known_validation_case_is_proposed_correctly(records):
    record = next(r for r in records if r["session"] == "session-3186-num-46")
    assert record["verdict"] == "shared_confirmed"
    assert record["dates"] == ["1627-03-11", "1627-03-13"]
    assert record["split_at_paragraph"] == 18
    assert record["proposed_ranges"]["1627-03-13"]["paragraph_range"] == [18, 47]
    assert record["proposed_ranges"]["1627-03-11"]["paragraph_range"] == [0, 17]


def test_undecided_sessions_get_no_proposed_ranges(records):
    undecided = [r for r in records if not r["verdict"].startswith("shared")]
    assert undecided
    assert all(r["proposed_ranges"] is None for r in undecided)


def test_proposed_ranges_partition_two_date_splits(records):
    two_date_shared = [
        r for r in records if r["verdict"].startswith("shared") and len(r["dates"]) == 2
    ]
    assert two_date_shared
    for record in two_date_shared:
        ranges = sorted(v["paragraph_range"] for v in record["proposed_ranges"].values())
        (lo1, hi1), (lo2, hi2) = ranges
        assert lo1 == 0
        assert hi1 + 1 == lo2
        assert hi2 == record["paragraphs"] - 1


def test_three_date_session_leaves_earlier_dates_undivided(records):
    record = next(r for r in records if r["session"] == "session-3185-num-13")
    assert record["dates"] == ["1626-01-15", "1626-01-16", "1626-01-17"]
    ranges = record["proposed_ranges"]
    assert ranges["1626-01-17"]["undivided_among"] == []
    assert ranges["1626-01-15"]["undivided_among"] == ["1626-01-16"]
    assert ranges["1626-01-16"]["undivided_among"] == ["1626-01-15"]
    assert ranges["1626-01-15"]["paragraph_range"] == ranges["1626-01-16"]["paragraph_range"]


def test_proposed_ranges_helper_returns_none_without_a_split():
    assert _proposed_ranges(["1626-01-01", "1626-01-02"], total_paragraphs=10, split=None) is None
    assert _proposed_ranges(["1626-01-01", "1626-01-02"], total_paragraphs=None, split=3) is None


def test_held_out_precondition(axis_and_concordance):
    by_session, _ = axis_and_concordance
    assert held_out_ok(by_session) is True


def test_gate_aggregates_not_a_review_queue(records, axis_and_concordance):
    by_session, concordance = axis_and_concordance
    gate = gate_duplicate_session_splits(records, by_session, concordance)
    assert gate["record_type"] == "gate"
    assert "review_policy" in gate and "machine_gate_only" in gate["review_policy"]
    assert gate["n_total"] == len(records)
    assert gate["n_proposed_shared"] + gate["n_undecided"] == gate["n_total"]
    assert gate["held_out_ok"] is True
    assert gate["structural_pass"] is True
    # Control may be slow; require the sample filled and pass-or-documented false counts.
    assert gate["control_n"] == gate["control_n_requested"]
    if gate["gate_pass"]:
        assert gate["n_gate_eligible"] == gate["n_proposed_shared"]
        assert gate["control_false_shared"] == 0
    else:
        assert gate["n_gate_eligible"] == 0


def test_structural_ok_matches_helper(records):
    shared = [r for r in records if r["verdict"].startswith("shared")]
    assert shared
    assert all(_structural_ok(r) for r in shared)

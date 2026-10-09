"""The duplicate-session-claim proposal set -- a reviewable worklist, not applied anywhere.

User, 2026-10-09: "i think it should resolve this" (session-3186-num-46, PINNED_TO both
1627-03-11 and 1627-03-13), then "persist the 25 located splits as a reviewable proposal set;
pause before rewriting graph edges or production pins." These tests check the persisted proposal
is correct and complete; none of them touch `sequence_graph`'s own graph, by design -- there is
nothing graph-side to test yet.
"""

from __future__ import annotations

import pytest

from sequence_graph.duplicate_sessions import _proposed_ranges, resolve_duplicate_session_claims


@pytest.fixture(scope="module")
def records() -> list[dict]:
    """Computed once per test run -- the fuzzy heading search over 67 sessions is not cheap, and
    every test below reads the same result, same convention as
    test_sequence_graph_consolidate.py's module-scoped `consolidation` fixture."""
    return resolve_duplicate_session_claims()


def test_resolve_duplicate_session_claims_covers_the_known_67(records):
    """The project's own standing figure (docs/DECISIONS.md, PLAN.md): 67 sessions are claimed
    by more than one enriched date."""
    assert len(records) == 67


def test_the_known_validation_case_is_proposed_correctly(records):
    """session-3186-num-46 is the exact case that triggered this module: claimed by both
    1627-03-11 and 1627-03-13, confirmed shared, split located at paragraph 18 of 48."""
    record = next(r for r in records if r["session"] == "session-3186-num-46")
    assert record["verdict"] == "shared_confirmed"
    assert record["dates"] == ["1627-03-11", "1627-03-13"]
    assert record["split_at_paragraph"] == 18
    assert record["proposed_ranges"]["1627-03-13"]["paragraph_range"] == [18, 47]
    assert record["proposed_ranges"]["1627-03-11"]["paragraph_range"] == [0, 17]


def test_undecided_sessions_get_no_proposed_ranges(records):
    """A session whose verdict does NOT start with 'shared' (no_heading_signal,
    hits_but_none_verified, one_claimant_heading_only) must get `proposed_ranges: None` -- never a
    guessed range standing in for a real one."""
    undecided = [r for r in records if not r["verdict"].startswith("shared")]
    assert undecided  # the population genuinely has undecided cases (42 of 67, historically)
    assert all(r["proposed_ranges"] is None for r in undecided)


def test_proposed_ranges_partition_the_session_for_a_two_date_split(records):
    """For exactly 2 claimant dates, the two proposed ranges must partition [0, total-1] exactly
    -- no gap, no overlap."""
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
    """session-3185-num-13 (3 claimant dates) must name the two earlier dates as undivided among
    each other, not silently split them evenly or assign one over the other."""
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

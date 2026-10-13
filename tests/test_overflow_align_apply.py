"""Unit tests for overflow_align_apply helpers — no corpus DP."""

from __future__ import annotations

from sequence_graph.align import AlignedPair, AlignmentResult, MATCH, DELETION_GAP
from sequence_graph.overflow_align_apply import (
    _ordered_claimants,
    _parse_volgnr_key,
    normalize_cuts,
    order_match_rate,
    segment_ids,
    slice_segments,
)


def test_normalize_cuts_clamps_and_sorts():
    assert normalize_cuts([100, 50, 50, -1, 999], 200, 2) == [50, 100]
    assert normalize_cuts(None, 100, 0) == []
    assert len(normalize_cuts([], 100, 2)) == 2  # even-split pad


def test_slice_segments_three_parts():
    text = "abcdefghij"  # len 10
    segs = slice_segments(text, [3, 7])
    assert segs == ["abc", "defg", "hij"]


def test_slice_segments_empty_and_no_cuts():
    assert slice_segments("", []) == [""]
    assert slice_segments("abc", []) == ["abc"]


def test_segment_ids():
    assert segment_ids("session-3185-num-1-resolution-2", 3) == [
        "session-3185-num-1-resolution-2::seg0",
        "session-3185-num-1-resolution-2::seg1",
        "session-3185-num-1-resolution-2::seg2",
    ]


def test_order_match_rate_diagonal():
    result = AlignmentResult(
        pairs=(
            AlignedPair(MATCH, 0, 0, 0.1),
            AlignedPair(MATCH, 1, 1, 0.1),
            AlignedPair(DELETION_GAP, 2, None, 1.0),
        ),
        total_cost=1.2,
        n_leading_free=0,
        n_trailing_free=0,
        abstained=False,
    )
    assert order_match_rate(result, 3) == 1.0


def test_order_match_rate_crossed():
    result = AlignmentResult(
        pairs=(
            AlignedPair(MATCH, 0, 1, 0.1),
            AlignedPair(MATCH, 1, 0, 0.1),
        ),
        total_cost=0.2,
        n_leading_free=0,
        n_trailing_free=0,
        abstained=False,
    )
    assert order_match_rate(result, 2) == 0.0


def test_ordered_claimants_editorial_not_half():
    prop = {
        "flat_id": "session-3185-num-150-resolution-5",
        "claimant_volgnrs": [
            "1626-09-23_5",
            "1626-09-23_0",
            "1626-09-23_8",
        ],
    }
    assert _ordered_claimants(prop) == [
        "1626-09-23_0",
        "1626-09-23_5",
        "1626-09-23_8",
    ]
    assert _parse_volgnr_key("1626-09-23_5") == ("1626-09-23", 5)


def test_ordered_claimants_drops_out_of_scope_dates():
    """Post-bar / unparseable dates must not reach the DP (fail closed at entry)."""
    prop = {
        "flat_id": "session-3185-num-150-resolution-5",
        "claimant_volgnrs": [
            "1626-09-23_0",
            "1630-06-01_0",  # past enriched end
            "not-a-date_1",
            "1626-09-23_5",
        ],
    }
    assert _ordered_claimants(prop) == ["1626-09-23_0", "1626-09-23_5"]

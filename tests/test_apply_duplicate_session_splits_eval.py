"""Unit tests for diagnostic duplicate-session split apply (no production write)."""

from __future__ import annotations

import pandas as pd

from scripts.apply_duplicate_session_splits_eval import (
    _place_in_range,
    apply_splits,
    slice_separated,
)


def test_place_in_range_unique_when_room_suffices():
    pairs = _place_in_range(3, 10, 20)
    assert pairs == [(10, 10), (11, 11), (12, 12)]


def test_place_in_range_packs_when_overfull():
    pairs = _place_in_range(5, 0, 1)
    assert len(pairs) == 5
    assert all(0 <= s <= 1 and e == s for s, e in pairs)


def test_apply_splits_exclusive_only_and_abstains_undivided():
    concordance = pd.DataFrame(
        [
            {
                "enriched_date": "1627-03-11",
                "resolution_index": 0,
                "resolved_session_id": "session-3186-num-46",
                "paragraph_start_index": 0.0,
                "paragraph_end_index": 40.0,
            },
            {
                "enriched_date": "1627-03-11",
                "resolution_index": 1,
                "resolved_session_id": "session-3186-num-46",
                "paragraph_start_index": 1.0,
                "paragraph_end_index": 41.0,
            },
            {
                "enriched_date": "1627-03-13",
                "resolution_index": 0,
                "resolved_session_id": "session-3186-num-46",
                "paragraph_start_index": None,
                "paragraph_end_index": None,
            },
            {
                "enriched_date": "1626-01-15",
                "resolution_index": 0,
                "resolved_session_id": "session-3185-num-13",
                "paragraph_start_index": 0.0,
                "paragraph_end_index": 5.0,
            },
        ]
    )
    proposals = [
        {
            "session": "session-3186-num-46",
            "proposed_ranges": {
                "1627-03-13": {"paragraph_range": [18, 47], "undivided_among": []},
                "1627-03-11": {"paragraph_range": [0, 17], "undivided_among": []},
            },
        },
        {
            "session": "session-3185-num-13",
            "proposed_ranges": {
                "1626-01-15": {"paragraph_range": [0, 13], "undivided_among": ["1626-01-16"]},
            },
        },
    ]
    out, log = apply_splits(concordance, proposals)
    by_date = {e["enriched_date"]: e for e in log}
    assert by_date["1627-03-11"]["applied"] is True
    assert by_date["1627-03-13"]["applied"] is True
    assert by_date["1626-01-15"]["applied"] is False
    assert by_date["1626-01-15"]["reason"] == "abstain_undivided_shared_range"
    later = out.loc[out["enriched_date"] == "1627-03-13"].iloc[0]
    assert later["paragraph_start_index"] == 18
    earlier = out.loc[
        (out["enriched_date"] == "1627-03-11") & (out["resolution_index"] == 0)
    ].iloc[0]
    assert earlier["paragraph_start_index"] == 0


def test_slice_separated_counts_unique_short_extents():
    frame = pd.DataFrame(
        {
            "enriched_date": ["1627-03-11", "1627-03-11", "1627-03-13"],
            "paragraph_start_index": [0.0, 1.0, 18.0],
            "paragraph_end_index": [0.0, 1.0, 18.0],
        }
    )
    stats = slice_separated(frame, {"1627-03-11", "1627-03-13"})
    assert stats["separated"] == 3
    assert stats["attributed"] == 3

import pandas as pd

from scripts.s6b_session_fingerprint_match import (
    _find_raw_matches,
    match_fingerprints,
    normalize,
)


def test_normalize_collapses_whitespace_and_lowercases():
    assert normalize("  Actere  ende\nResoltaren  ") == "actere ende resoltaren"


def test_find_raw_matches_requires_minimum_length():
    raw_group = pd.DataFrame({"raw_session_id": ["s-1"], "text": ["ab"]})
    assert _find_raw_matches("ab", raw_group) == []


def test_find_raw_matches_finds_substring_not_just_prefix():
    # The flat fingerprint starts partway into the raw session's concatenated text --
    # exactly the alignment slack substring containment exists to tolerate.
    raw_group = pd.DataFrame(
        {
            "raw_session_id": ["s-1"],
            "text": ["leading attendance line that resolutions_flat drops " + "x" * 40],
        }
    )
    fingerprint = "x" * 40
    assert _find_raw_matches(fingerprint, raw_group) == ["s-1"]


def test_find_raw_matches_is_ambiguous_when_shared_by_two_raw_sessions():
    fingerprint = "y" * 40
    raw_group = pd.DataFrame(
        {
            "raw_session_id": ["s-1", "s-2"],
            "text": [fingerprint, fingerprint],
        }
    )
    assert _find_raw_matches(fingerprint, raw_group) == ["s-1", "s-2"]


def _flat_row(inventory_id, flat_num, fingerprint):
    return {
        "inventory_id": inventory_id,
        "flat_num": flat_num,
        "flat_session_id": f"session-{inventory_id}-num-{flat_num}",
        "date": "1626-01-01",
        "fingerprint": fingerprint,
    }


def _raw_row(inventory_id, raw_num, text):
    return {
        "inventory_id": inventory_id,
        "raw_num": raw_num,
        "raw_session_id": f"session-{inventory_id}-num-{raw_num}",
        "text": text,
    }


def test_match_fingerprints_computes_offset_for_a_unique_match():
    fp = "z" * 40
    flat_fp = pd.DataFrame([_flat_row(3185, 25, fp)])
    raw_fp = pd.DataFrame([_raw_row(3185, 26, "prefix noise " + fp)])

    result = match_fingerprints(flat_fp, raw_fp)

    row = result.iloc[0]
    assert row["raw_matches"] == ["session-3185-num-26"]
    assert row["raw_num"] == 26
    assert row["offset"] == 1


def test_match_fingerprints_scopes_the_search_to_the_same_inventory():
    fp = "w" * 40
    flat_fp = pd.DataFrame([_flat_row(3185, 1, fp)])
    # Same fingerprint exists in a different inventory -- must not count as a match.
    raw_fp = pd.DataFrame([_raw_row(4562, 1, fp)])

    result = match_fingerprints(flat_fp, raw_fp)

    row = result.iloc[0]
    assert row["raw_matches"] == []
    assert row["raw_num"] is None
    assert row["offset"] is None


def test_match_fingerprints_leaves_unmatched_sessions_as_none_not_nan():
    flat_fp = pd.DataFrame([_flat_row(3185, 1, "q" * 40)])
    raw_fp = pd.DataFrame([_raw_row(3185, 1, "unrelated content")])

    result = match_fingerprints(flat_fp, raw_fp)

    row = result.iloc[0]
    assert row["raw_num"] is None
    assert row["offset"] is None

"""Unit tests for overflow cut gold promote — no corpus I/O."""

from __future__ import annotations

from sequence_graph.overflow_cut_promote import (
    approved_reviews,
    run_overflow_cut_promote,
)


def test_approved_reviews_filters_and_normalizes() -> None:
    anns = {
        "annotations": {
            "flat-a": {
                "text": "AAAA|||CUT|||BBBB|||CUT|||CCCC",
                "verdict": "approve",
                "uncertain": False,
                "note": "ok",
            },
            "flat-b": {
                "text": "XXXX|||CUT|||YYYY",
                "verdict": "defer",
            },
            "flat-c": {
                "text": "no cuts",
                "verdict": "approve",
            },
            "flat-d": {
                "text": "P|||CUT|||Q",
                "verdict": "skip",
            },
        }
    }
    got = approved_reviews(anns)
    assert set(got) == {"flat-a"}
    assert got["flat-a"]["gold_offsets"] == [4, 8]
    assert got["flat-a"]["is_gold"] is True


def test_promote_flips_cut_proposal_is_gold() -> None:
    annotations = {
        "annotations": {
            "session-3185-num-151-resolution-2": {
                "text": "A" * 1241 + "|||CUT|||" + "B" * 461 + "|||CUT|||"
                + "C" * 665 + "|||CUT|||" + "D" * 100,
                "verdict": "approve",
                "uncertain": False,
                "note": "",
            },
            "session-3185-num-150-resolution-5": {
                "text": "X" * 1257 + "|||CUT|||" + "Y" * 2006 + "|||CUT|||"
                + "Z" * 134 + "|||CUT|||" + "W" * 50,
                "verdict": "approve",
                "uncertain": True,
                "note": "3 vs 5",
            },
        }
    }
    track = [
        {
            "record_type": "cut_proposal",
            "flat_id": "session-3185-num-151-resolution-2",
            "session_id": "session-3185-num-151",
            "n_claimants": 4,
            "claimant_volgnrs": ["a", "b", "c", "d"],
            "encoder_cuts": [798, 1241, 1469],
            "even_split_cuts": [732, 1464, 2196],
            "flat_char_len": 3000,
            "is_gold": False,
        },
        {
            "record_type": "cut_proposal",
            "flat_id": "session-3185-num-150-resolution-5",
            "session_id": "session-3185-num-150",
            "n_claimants": 5,
            "claimant_volgnrs": ["a", "b", "c", "d", "e"],
            "encoder_cuts": [377, 658, 1077, 1257],
            "flat_char_len": 3500,
            "is_gold": False,
        },
        {
            "record_type": "cut_proposal",
            "flat_id": "session-3185-num-148-resolution-4",
            "n_claimants": 2,
            "is_gold": False,
        },
    ]
    rows = run_overflow_cut_promote(annotations=annotations, track_rows=track)
    meta = next(r for r in rows if r["record_type"] == "meta")
    gold = [r for r in rows if r["record_type"] == "cut_proposal"]
    assert meta["gate"] == "PASS"
    assert meta["n_approved"] == 2
    assert meta["n_uncertain"] == 1
    assert len(gold) == 2
    assert all(r["is_gold"] is True for r in gold)
    by_id = {r["flat_id"]: r for r in gold}
    assert by_id["session-3185-num-151-resolution-2"]["gold_offsets"] == [
        1241,
        1702,
        2367,
    ]
    assert by_id["session-3185-num-151-resolution-2"]["expected_cuts_disagrees"] is False
    assert by_id["session-3185-num-150-resolution-5"]["uncertain"] is True
    assert by_id["session-3185-num-150-resolution-5"]["expected_cuts_disagrees"] is True
    # Machine track rows for non-reviewed flats stay out of gold
    assert "session-3185-num-148-resolution-4" not in by_id

"""Track P P3 — re-paragraph + offset carry through backbone/segment_gap."""

from __future__ import annotations

from scripts.s6c_gap_segmentation import segment_day
from scripts.s6c_reparagraph import (
    cuts_from_alignments,
    extents_from_starts,
    interior_cuts,
    map_offset_to_new_index,
    remap_alignments,
    reparagraph_axis,
    segment_day_with_offsets,
    select_interior_cuts,
    starts_from_segment_positions,
)


def _axis(*texts: str) -> list[dict]:
    return [
        {
            "text": text,
            "para_index": index,
            "axis_id": f"day#p{index}",
            "flat_id": f"session-x-resolution-{index + 1}",
        }
        for index, text in enumerate(texts)
    ]


def test_interior_cuts_drop_edges_and_out_of_range():
    assert interior_cuts([(0, 0), (0, 5), (0, 10), (1, 3), (9, 1)], [10, 4]) == [
        (0, 5),
        (1, 3),
    ]


def test_reparagraph_splits_one_host_into_ordered_pieces():
    # "abcdefghij" cut at 3 and 7 → abc | defg | hij
    result = reparagraph_axis(_axis("abcdefghij"), [(0, 3), (0, 7)], version="test_v")
    texts = [row["text"] for row in result["axis"]]
    assert texts == ["abc", "defg", "hij"]
    assert result["n_paragraphs_before"] == 1
    assert result["n_paragraphs_after"] == 3
    assert result["cuts_applied"] == [(0, 3), (0, 7)]
    assert all(row["axis_version"] == "test_v" for row in result["axis"])
    assert result["old_to_new"][0] == [(0, 0, 3), (1, 3, 7), (2, 7, 10)]
    # Parent metadata preserved on pieces
    assert result["axis"][1]["parent_para_index"] == 0
    assert result["axis"][1]["parent_char_start"] == 3
    assert result["axis"][1]["flat_id"] == "session-x-resolution-1"


def test_reparagraph_leaves_uncut_neighbours_intact():
    result = reparagraph_axis(_axis("aa", "bbbbbb", "cc"), [(1, 2)])
    assert [row["text"] for row in result["axis"]] == ["aa", "bb", "bbbb", "cc"]
    assert result["old_to_new"][0] == [(0, 0, 2)]
    assert result["old_to_new"][1] == [(1, 0, 2), (2, 2, 6)]
    assert result["old_to_new"][2] == [(3, 0, 2)]


def test_map_offset_opens_the_piece_that_starts_at_the_cut():
    successor = reparagraph_axis(_axis("0123456789"), [(0, 4)])
    mapping = successor["old_to_new"]
    assert map_offset_to_new_index(0, None, mapping) == 0
    assert map_offset_to_new_index(0, 0, mapping) == 0
    assert map_offset_to_new_index(0, 3, mapping) == 0
    assert map_offset_to_new_index(0, 4, mapping) == 1  # cut opens right piece
    assert map_offset_to_new_index(0, 9, mapping) == 1


def test_two_offset_anchors_on_one_paragraph_become_distinct_after_carry():
    # Classic collision: enriched 1 and 2 both on paragraph 0, distinct offsets.
    # Without offsets, segment_day pins both to 0. With offsets, re-paragraph
    # yields three pieces and unique starts.
    axis = _axis("AAAAABBBBBCCCCC")
    alignments = [(1, 0, 5), (2, 0, 10)]
    plain = segment_day(3, 1, [(1, 0), (2, 0)])
    assert plain == [0, 0]

    carried = segment_day_with_offsets(3, axis, alignments)
    assert [row["text"] for row in carried["successor"]["axis"]] == [
        "AAAAA",
        "BBBBB",
        "CCCCC",
    ]
    assert carried["positions"] == [1, 2]
    starts = starts_from_segment_positions(carried["positions"])
    assert starts == [0, 1, 2]
    assert len(set(starts)) == 3


def test_synthetic_pair_gold_offsets_unlock_unique_starts():
    # Mimic synthetic_boundary: two separated segments concatenated, gold cut
    # at len(first). Only resolution 1 carries the interior offset.
    left, right = "FIRST_SEGMENT_TEXT", "SECOND_SEGMENT_TEXT"
    axis = _axis(left + right)
    cut = len(left)
    alignments = [(1, 0, cut)]
    carried = segment_day_with_offsets(2, axis, alignments)
    assert len(carried["successor"]["axis"]) == 2
    assert carried["positions"] == [1]
    starts = starts_from_segment_positions(carried["positions"])
    assert starts == [0, 1]
    spans = extents_from_starts(starts, 2)
    assert spans == [(0, 0), (1, 1)]


def test_remap_alignments_drops_char_offsets():
    successor = reparagraph_axis(_axis("abcdefghij"), [(0, 5)])
    remapped = remap_alignments([(1, 0, 5), (2, 0, None)], successor["old_to_new"])
    assert remapped == [(1, 1), (2, 0)]


def test_cuts_from_alignments_ignores_zero_and_missing():
    assert cuts_from_alignments([(1, 0, 0), (2, 0, None), (3, 0, 12), (4, None, 5)]) == [
        (0, 12)
    ]


def test_parent_axis_is_not_mutated():
    axis = _axis("abcdefghij")
    original_text = axis[0]["text"]
    reparagraph_axis(axis, [(0, 4)])
    assert axis[0]["text"] == original_text
    assert "parent_para_index" not in axis[0]


def test_select_interior_cuts_takes_top_ranked_in_text_order():
    class _Cand:
        def __init__(self, offset: int, rank: tuple) -> None:
            self.offset = offset
            self.rank = rank

    # Higher rank wins; returned sorted by offset.
    cuts = select_interior_cuts(
        [_Cand(30, (0, 0, 1)), _Cand(10, (1, 0, 1)), _Cand(20, (0, 1, 1))],
        2,
    )
    assert cuts == [10, 20]


def test_select_interior_cuts_partial_when_under_proposed():
    class _Cand:
        def __init__(self, offset: int) -> None:
            self.offset = offset
            self.rank = (1,)

    assert select_interior_cuts([_Cand(5)], 3) == [5]
    assert select_interior_cuts([], 2) == []

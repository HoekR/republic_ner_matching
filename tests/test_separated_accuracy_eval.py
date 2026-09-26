"""Tests for scripts/separated_accuracy_eval.py (Step 5c.1 of the collision-avoidance track).

The load-bearing logic is the gold convention: which slot opens which resolution, and which
slots are not placements at all. Those are the assertions that decide whether the accuracy
number means anything, so they are tested against hand-built fixtures mirroring real gold shapes.
"""

from __future__ import annotations

import pandas as pd

from scripts.separated_accuracy_eval import (
    _separated_under,
    accuracy,
    gold_start_paragraphs,
    is_located,
    label_separation,
    uniform_start_paragraphs,
)


def cut(paragraph_stream_index, *, unit="paragraph_boundary", kind="cut", located=True):
    slot = {"paragraph_stream_index": paragraph_stream_index, "unit": unit, "kind": kind}
    if located:
        slot |= {"flat_id": "session-3185-num-7-resolution-1", "char_offset": 424}
    else:
        slot |= {"flat_id": None, "char_offset": None}
    return slot


class TestIsLocated:
    def test_placeholder_slot_is_not_located(self):
        assert not is_located(cut(28, unit="out_of_range", located=False))

    def test_fully_annotated_slot_is_located(self):
        assert is_located(cut(3))


class TestGoldStartParagraphs:
    def test_cut_c_opens_resolution_c_plus_one(self):
        """The canonical off-by-one: boundaries[0] ends resolution 0, it does not start it."""
        day = {"boundaries": [cut(0), cut(2, unit="mid_paragraph"), cut(3)]}
        assert gold_start_paragraphs(day, 4) == [0, 1, 2, 4]

    def test_paragraph_boundary_opens_the_next_paragraph(self):
        """char_offset == len(paragraph), so the resolution it opens starts at index + 1."""
        day = {"boundaries": [cut(5, unit="paragraph_boundary")]}
        assert gold_start_paragraphs(day, 2) == [0, 6]

    def test_mid_paragraph_opens_inside_its_own_paragraph(self):
        day = {"boundaries": [cut(5, unit="mid_paragraph")]}
        assert gold_start_paragraphs(day, 2) == [0, 5]

    def test_end_of_last_resolution_is_not_an_opening(self):
        """It closes the day; counting it would shift every start by one on 13 gold days."""
        day = {"boundaries": [cut(1), cut(6, kind="end_of_last_resolution")]}
        assert gold_start_paragraphs(day, 3) == [0, 2, None]

    def test_leading_start_slot_relocates_the_first_resolution(self):
        """8 gold days open away from paragraph 0; the `start` slot is not a cut."""
        day = {"boundaries": [cut(1, unit="mid_paragraph", kind="start"), cut(3)]}
        assert gold_start_paragraphs(day, 3) == [1, 4, None]

    def test_unlocated_placeholder_is_unknown_not_a_start(self):
        day = {"boundaries": [cut(28, unit="out_of_range", located=False), cut(3)]}
        assert gold_start_paragraphs(day, 3) == [0, None, 4]

    def test_missing_cuts_yield_none_not_a_short_list(self):
        """Gold is sparse (373 slots against 623 resolutions); length must still equal k_e."""
        assert gold_start_paragraphs({"boundaries": []}, 4) == [0, None, None, None]


class TestUniformStartParagraphs:
    def test_matches_segment_gap_ideal_spacing(self):
        assert uniform_start_paragraphs(12, 4) == [0, 3, 6, 9]

    def test_single_resolution_day_has_no_cuts(self):
        assert uniform_start_paragraphs(9, 1) == [0]

    def test_more_resolutions_than_paragraphs_repeats_positions(self):
        assert uniform_start_paragraphs(2, 4) == [0, 0, 1, 1]


class TestLabelSeparation:
    def frame(self):
        return pd.DataFrame(
            [
                # unique start, extent 1 -> separated
                {"enriched_date": "1626-01-08", "resolution_index": 0,
                 "paragraph_start_index": 0, "paragraph_end_index": 0},
                # shared start -> collision
                {"enriched_date": "1626-01-08", "resolution_index": 1,
                 "paragraph_start_index": 2, "paragraph_end_index": 2},
                {"enriched_date": "1626-01-08", "resolution_index": 2,
                 "paragraph_start_index": 2, "paragraph_end_index": 2},
                # unique start, extent 5 -> extent loss
                {"enriched_date": "1626-01-08", "resolution_index": 3,
                 "paragraph_start_index": 4, "paragraph_end_index": 8},
            ]
        )

    def test_flags_and_reasons(self):
        labelled = label_separation(self.frame())
        assert labelled["loss_reason"].tolist() == ["separated", "collision", "collision", "extent"]
        assert labelled["separated"].tolist() == [True, False, False, False]

    def test_uniqueness_is_scoped_to_the_date(self):
        frame = self.frame()
        frame.loc[frame["resolution_index"] == 2, "enriched_date"] = "1626-01-09"
        labelled = label_separation(frame)
        assert labelled["separated"].tolist() == [True, True, True, False]

    def test_collision_and_extent_reported_together(self):
        frame = pd.DataFrame(
            [
                {"enriched_date": "d", "resolution_index": 0,
                 "paragraph_start_index": 1, "paragraph_end_index": 9},
                {"enriched_date": "d", "resolution_index": 1,
                 "paragraph_start_index": 1, "paragraph_end_index": 9},
            ]
        )
        assert label_separation(frame)["loss_reason"].tolist() == ["collision_and_extent"] * 2


class TestAccuracy:
    def test_unlocated_gold_rows_are_dropped_not_counted_wrong(self):
        frame = pd.DataFrame(
            {"gold_start": [3, None, 5], "predicted_start": [3, 9, 7]}
        )
        result = accuracy(frame, "predicted_start")
        assert result["n"] == 2
        assert result["exact_agreement"] == 0.5
        assert result["mean_abs_displacement"] == 1.0

    def test_within_1_is_a_superset_of_exact(self):
        frame = pd.DataFrame({"gold_start": [3, 3, 3], "predicted_start": [3, 4, 8]})
        result = accuracy(frame, "predicted_start")
        assert result["exact_agreement"] == round(1 / 3, 4)
        assert result["within_1"] == round(2 / 3, 4)

    def test_empty_frame_returns_nulls_not_zeros(self):
        result = accuracy(pd.DataFrame({"gold_start": [], "predicted_start": []}), "predicted_start")
        assert result == {"n": 0, "exact_agreement": None, "within_1": None,
                          "mean_abs_displacement": None, "median_abs_displacement": None}


class TestSeparatedUnder:
    def test_counts_unique_bounded_spans(self):
        day_frame = pd.DataFrame([{"date": "d", "paragraph_count": 6}])
        frame = pd.DataFrame(
            {"date": ["d"] * 3, "resolution_index": [0, 1, 2], "gold_start": [0, 1, 2]}
        )
        # spans (0,1), (1,2), (2,6): extents 2, 2, 5 -> the last loses on extent
        assert _separated_under(day_frame, "d", frame, "gold_start") == 2

    def test_partial_annotation_scores_zero_rather_than_a_flattering_subset(self):
        day_frame = pd.DataFrame([{"date": "d", "paragraph_count": 6}])
        frame = pd.DataFrame(
            {"date": ["d"] * 3, "resolution_index": [0, 1, 2], "gold_start": [0, None, 2]}
        )
        assert _separated_under(day_frame, "d", frame, "gold_start") == 0



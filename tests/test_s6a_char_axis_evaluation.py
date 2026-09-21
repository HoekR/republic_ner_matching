from scripts.s6a_char_axis_evaluation import (
    REF_KINDS,
    axis_char_length,
    ceiling_report,
    char_starts,
    compose,
    composed_positions,
    fold_groups,
    lump_prediction,
    lumped_positions,
    opening_paragraph,
)


def axis(*lengths):
    return [{"text": "x" * length} for length in lengths]


def test_char_starts_are_cumulative_with_no_separator():
    assert char_starts(axis(424, 90, 746)) == [0, 424, 514]


def test_axis_char_length_sums_paragraph_texts():
    assert axis_char_length(axis(424, 90, 746)) == 1260


def test_compose_adds_the_within_paragraph_offset_to_the_paragraph_start():
    assert compose([0, 424, 514], 2, 409) == 923


def test_paragraph_final_cut_composes_to_the_start_of_the_next_paragraph():
    # Gold records a paragraph_boundary cut at char_offset == len(paragraph), so the
    # two descriptions of that same point must land on one coordinate.
    starts = char_starts(axis(424, 90, 746))
    assert compose(starts, 0, 424) == compose(starts, 1, 0)


def test_compose_returns_none_for_offsetless_slots():
    assert compose([0, 424], 1, None) is None


def test_compose_returns_none_when_the_paragraph_index_is_off_axis():
    assert compose([0, 424], 7, 10) is None


def test_composed_positions_drops_offsetless_slots_and_sorts():
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 409},
            {"kind": "cut", "paragraph_stream_index": 0, "char_offset": 424},
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": None},
        ]
    }
    assert composed_positions(day, [0, 424, 514], REF_KINDS) == [424, 923]


def test_composed_positions_ignores_kinds_outside_the_requested_set():
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 0, "char_offset": 10},
            {"kind": "note", "paragraph_stream_index": 1, "char_offset": 10},
        ]
    }
    assert composed_positions(day, [0, 424], REF_KINDS) == [10]


def test_fold_groups_reports_a_collision_that_character_offsets_separate():
    # 1626-01-08: two distinct cuts inside paragraph 2, 337 characters apart.
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 409, "unit": "mid_paragraph"},
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 746, "unit": "paragraph_boundary"},
        ]
    }
    (group,) = fold_groups(day, [0, 424, 514], REF_KINDS)
    assert group["slot_count"] == 2
    assert group["distinct_composed"] == 2
    assert group["fully_separated"] is True
    assert [slot["composed"] for slot in group["slots"]] == [923, 1260]


def test_fold_groups_marks_offsetless_collisions_as_unseparated():
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 28, "char_offset": None, "unit": "out_of_range"},
            {"kind": "cut", "paragraph_stream_index": 28, "char_offset": None, "unit": "out_of_range"},
        ]
    }
    (group,) = fold_groups(day, char_starts(axis(*([10] * 29))), REF_KINDS)
    assert group["null_offsets"] == 2
    assert group["fully_separated"] is False


def test_fold_groups_skips_paragraphs_holding_a_single_slot():
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 0, "char_offset": 10},
            {"kind": "cut", "paragraph_stream_index": 1, "char_offset": 20},
        ]
    }
    assert fold_groups(day, [0, 424], REF_KINDS) == []


def test_ceiling_report_separates_slots_that_share_a_paragraph_index():
    days = [
        {
            "date": "1626-01-08",
            "boundaries": [
                {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 409},
                {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 746},
            ],
        }
    ]
    report = ceiling_report(days, {"1626-01-08": [0, 424, 514]})
    assert report["cut_slots"] == 2
    assert report["distinct_paragraph_positions"] == 1
    assert report["distinct_char_positions"] == 2
    assert report["char_recall_bound_tol0"] == 1.0


def test_ceiling_report_counts_offsetless_slots_as_unreachable():
    days = [
        {
            "date": "1626-02-03",
            "boundaries": [
                {"kind": "cut", "paragraph_stream_index": 28, "char_offset": None},
                {"kind": "cut", "paragraph_stream_index": 28, "char_offset": None},
            ],
        }
    ]
    report = ceiling_report(days, {"1626-02-03": char_starts(axis(*([10] * 29)))})
    assert report["null_offset_slots"] == 2
    assert report["distinct_char_positions"] == 0


def test_opening_paragraph_advances_past_a_paragraph_boundary_cut():
    assert opening_paragraph({"paragraph_stream_index": 2, "unit": "paragraph_boundary"}) == 3


def test_opening_paragraph_stays_put_for_an_interior_cut():
    assert opening_paragraph({"paragraph_stream_index": 2, "unit": "mid_paragraph"}) == 2


def test_opening_paragraph_is_none_without_an_index():
    assert opening_paragraph({"paragraph_stream_index": None, "unit": "out_of_range"}) is None


def test_lumping_collapses_an_interior_cut_onto_its_paragraph_start():
    # 1626-01-08 paragraph 2 holds a mid_paragraph cut at 409 and a boundary cut at 746.
    # Lumped, the first is credited at paragraph 2's start and the second opens paragraph 3.
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 409, "unit": "mid_paragraph"},
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 746, "unit": "paragraph_boundary"},
        ]
    }
    assert lumped_positions(day, [0, 424, 514, 1260], REF_KINDS) == [514, 1260]


def test_lumping_deduplicates_cuts_opening_in_one_paragraph():
    day = {
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 100, "unit": "mid_paragraph"},
            {"kind": "cut", "paragraph_stream_index": 2, "char_offset": 300, "unit": "mid_paragraph"},
        ]
    }
    assert lumped_positions(day, [0, 424, 514], REF_KINDS) == [514]


def test_lumping_keeps_offsetless_cuts_that_still_carry_a_paragraph():
    # Unlike strict composition, lumping can place an out_of_range cut at its paragraph start.
    day = {"boundaries": [{"kind": "cut", "paragraph_stream_index": 1, "char_offset": None, "unit": "out_of_range"}]}
    assert lumped_positions(day, [0, 424, 514], REF_KINDS) == [424]


def test_lump_prediction_maps_paragraph_indices_to_their_starts():
    assert lump_prediction([0, 424, 514], [1, 2]) == [424, 514]


def test_lump_prediction_drops_indices_off_the_axis():
    assert lump_prediction([0, 424], [1, 9]) == [424]


def test_ceiling_report_ignores_start_slots():
    # The guide's 352/280/320 figures are measured over kind == "cut" only.
    days = [
        {
            "date": "1626-02-03",
            "boundaries": [
                {"kind": "start", "paragraph_stream_index": 0, "char_offset": 5},
                {"kind": "cut", "paragraph_stream_index": 1, "char_offset": 5},
            ],
        }
    ]
    assert ceiling_report(days, {"1626-02-03": [0, 424]})["cut_slots"] == 1

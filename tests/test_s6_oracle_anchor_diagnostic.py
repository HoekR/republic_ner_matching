from scripts.s6_oracle_anchor_diagnostic import (
    anchor_obstruction,
    compose_prediction,
    oracle_anchors,
    reachability,
    thin_anchors,
)


def day(k_e, cuts):
    return {
        "k_e": k_e,
        "boundaries": [
            {"kind": "cut", "paragraph_stream_index": index, "unit": unit} for index, unit in cuts
        ],
    }


def test_oracle_anchors_open_the_next_resolution_after_a_paragraph_boundary_cut():
    # A paragraph_boundary cut at p sits at the END of p, so the next resolution opens at p+1.
    assert oracle_anchors(day(3, [(4, "paragraph_boundary"), (9, "paragraph_boundary")])) == [(0, 0), (1, 5), (2, 10)]


def test_oracle_anchors_stay_inside_the_paragraph_for_a_mid_paragraph_cut():
    assert oracle_anchors(day(2, [(4, "mid_paragraph")])) == [(0, 0), (1, 4)]


def test_consecutive_boundary_and_mid_cuts_in_one_paragraph_stay_monotone():
    # 1626-01-08: a mid_paragraph cut then a paragraph_boundary cut, both recorded at index 2.
    # Reading both as 2 fabricates a collision; the units separate them.
    assert oracle_anchors(day(3, [(2, "mid_paragraph"), (2, "paragraph_boundary")])) == [(0, 0), (1, 2), (2, 3)]


def test_oracle_anchors_are_empty_for_a_single_resolution_day():
    assert oracle_anchors(day(1, [])) == []


def test_oracle_anchors_take_only_the_first_k_e_minus_one_cuts():
    result = oracle_anchors(day(2, [(4, "paragraph_boundary"), (9, "paragraph_boundary")]))
    assert result == [(0, 0), (1, 5)]


def test_obstruction_flags_an_anchor_past_the_end_of_the_axis():
    assert anchor_obstruction([(0, 0), (1, 8)], k_e=2, axis_count=8) == "anchor_beyond_axis"


def test_oracle_anchors_bail_out_on_a_cut_with_no_paragraph_index():
    assert oracle_anchors(day(3, [(4, "paragraph_boundary"), (None, "out_of_range")])) is None


def test_thin_anchors_all_keeps_everything():
    anchors = [(0, 0), (1, 4), (2, 9)]
    assert thin_anchors(anchors, "all") == anchors


def test_thin_anchors_half_takes_every_other():
    assert thin_anchors([(0, 0), (1, 4), (2, 9), (3, 12)], "half") == [(0, 0), (2, 9)]


def test_thin_anchors_endpoints_keeps_only_first_and_last():
    assert thin_anchors([(0, 0), (1, 4), (2, 9), (3, 12)], "endpoints") == [(0, 0), (3, 12)]


def test_thin_anchors_endpoints_tolerates_a_single_anchor():
    assert thin_anchors([(0, 0)], "endpoints") == [(0, 0)]


def test_obstruction_flags_an_axis_shorter_than_the_resolution_count():
    assert anchor_obstruction([(0, 0), (1, 1)], k_e=7, axis_count=3) == "axis_shorter_than_k_e"


def test_obstruction_flags_folded_anchors_sharing_a_paragraph():
    # Two gold cuts inside one paragraph: perfect anchors, but not strictly increasing.
    assert anchor_obstruction([(0, 0), (1, 2), (2, 2)], k_e=3, axis_count=8) == "folded_anchors_non_monotone"


def test_obstruction_is_absent_for_a_usable_anchor_set():
    assert anchor_obstruction([(0, 0), (1, 2), (2, 5)], k_e=3, axis_count=8) is None


def test_reachability_splits_cuts_by_annotated_unit():
    counts = reachability(
        day(4, [(1, "paragraph_boundary"), (2, "mid_paragraph"), (2, "mid_paragraph")])
    )
    assert counts == {
        "paragraph_boundary_cuts": 1,
        "mid_paragraph_cuts": 2,
        "out_of_range_cuts": 0,
    }


def test_compose_prediction_uses_the_snap_offset_when_a_phrase_matched():
    starts = [0, 424, 514]
    snapped = [(1, ("de heeren van", 336, 1.0)), (2, None)]
    assert compose_prediction(starts, snapped) == [514, 760]


def test_compose_prediction_falls_back_to_the_paragraph_start_without_a_snap():
    assert compose_prediction([0, 424, 514], [(2, None)]) == [514]


def test_compose_prediction_drops_positions_off_the_axis():
    assert compose_prediction([0, 424], [(7, None)]) == []

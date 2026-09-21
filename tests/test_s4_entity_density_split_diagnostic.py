from scripts.s4_entity_density_split_diagnostic import (
    classify_positions,
    content_boundary_indices,
    label_axis_paragraphs,
    summary_statistics,
)


def test_classify_positions_distinguishes_bundled_from_single():
    assert classify_positions([2, 2, 5]) == {2: 2, 5: 1}


def test_classify_positions_handles_three_way_collision():
    assert classify_positions([1, 1, 1]) == {1: 3}


def test_content_boundary_indices_excludes_out_of_range_slots():
    day = {
        "boundaries": [
            {"kind": "cut", "unit": "out_of_range", "paragraph_stream_index": 7},
            {"kind": "cut", "unit": "out_of_range", "paragraph_stream_index": 7},
            {"kind": "cut", "unit": "paragraph_boundary", "paragraph_stream_index": 3},
            {"kind": "end_of_last_resolution", "unit": "paragraph_boundary", "paragraph_stream_index": 9},
        ]
    }
    assert content_boundary_indices(day) == [3]


def test_label_axis_paragraphs_buckets_by_position_count():
    day_axis = [
        {"axis_id": "a0", "flat_id": "f0", "para_index": 0, "entity_annotation_count": 0},
        {"axis_id": "a1", "flat_id": "f0", "para_index": 1, "entity_annotation_count": 5},
        {"axis_id": "a2", "flat_id": "f1", "para_index": 0, "entity_annotation_count": 2},
        {"axis_id": "a3", "flat_id": "f1", "para_index": 1, "entity_annotation_count": 0},
    ]
    rows = label_axis_paragraphs(day_axis, {1: 2, 2: 1}, k_e=3, date="1626-01-01")
    categories = {row["axis_id"]: row["category"] for row in rows}
    assert categories == {
        "a0": "non_boundary",
        "a1": "bundled",
        "a2": "clean_single_boundary",
        "a3": "non_boundary",
    }
    bundled_row = next(row for row in rows if row["axis_id"] == "a1")
    assert bundled_row["is_bundled"] is True
    assert bundled_row["entity_annotation_count"] == 5
    assert bundled_row["gold_boundary_slot_count"] == 2


def test_summary_statistics_fully_separated_case():
    stats = summary_statistics(bundled_counts=[5, 6, 7], clean_counts=[1, 2, 3, 4])
    assert stats["n_bundled"] == 3
    assert stats["n_clean"] == 4
    assert stats["common_language_effect_size"] == 1.0


def test_summary_statistics_partial_separation_hand_computed():
    # 12 pairs: wins = 1+0+0+0 + 1+0.5+0+0 + 1+1+0+0 = 4.5 -> 4.5/12 = 0.375
    stats = summary_statistics(bundled_counts=[2, 3, 8], clean_counts=[1, 3, 9, 10])
    assert stats["common_language_effect_size"] == 0.375


def test_summary_statistics_best_threshold_recovers_perfect_separation():
    stats = summary_statistics(bundled_counts=[10, 10, 10], clean_counts=[1, 1, 1])
    assert stats["best_threshold"] == {"threshold": 2, "tpr": 1.0, "fpr": 0.0, "youden_j": 1.0}

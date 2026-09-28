from scripts.anchor_set_reconciliation import (
    classify,
    flat_id_positions,
    production_anchor_positions,
    summarize,
)


def test_flat_id_positions_records_first_paragraph_index():
    axis = [
        {"flat_id": "res-1"},
        {"flat_id": "res-1"},
        {"flat_id": "res-2"},
    ]
    assert flat_id_positions(axis) == {"res-1": 0, "res-2": 2}


def test_production_anchor_positions_requires_shared_entities():
    enriched_ids = ["e0", "e1"]
    axis_ids = ["a0", "a1"]
    lookup = {("e0", "a0"): {"Amsterdam"}}
    idf_weights = {"Amsterdam": 1.0}
    anchored = production_anchor_positions(enriched_ids, axis_ids, lookup, idf_weights)
    assert anchored == {0: 0}


def test_production_anchor_positions_empty_without_any_overlap():
    enriched_ids = ["e0"]
    axis_ids = ["a0"]
    anchored = production_anchor_positions(enriched_ids, axis_ids, {}, {})
    assert anchored == {}


def test_classify_agreement_at_same_position():
    rows = classify({0: 5}, {0: 5})
    assert rows == [{"enriched_index": 0, "status": "both", "distance": 0}]


def test_classify_agreement_with_distance():
    rows = classify({1: 3}, {1: 7})
    assert rows == [{"enriched_index": 1, "status": "both", "distance": 4}]


def test_classify_resolution_only_and_paragraph_only():
    rows = classify({0: 1}, {2: 9})
    by_index = {row["enriched_index"]: row for row in rows}
    assert by_index[0]["status"] == "resolution_only"
    assert by_index[2]["status"] == "paragraph_only"


def test_summarize_agreement_rate_and_exact_share():
    rows = [
        {"enriched_index": 0, "status": "both", "distance": 0},
        {"enriched_index": 1, "status": "both", "distance": 2},
        {"enriched_index": 2, "status": "resolution_only", "distance": None},
        {"enriched_index": 3, "status": "paragraph_only", "distance": None},
    ]
    summary = summarize(rows)
    assert summary["total_either"] == 4
    assert summary["both"] == 2
    assert summary["agreement_rate"] == 0.5
    assert summary["exact_position_share_of_both"] == 0.5
    assert summary["mean_distance_of_both"] == 1.0


def test_summarize_empty_rows_does_not_divide_by_zero():
    summary = summarize([])
    assert summary["agreement_rate"] == 0.0
    assert summary["exact_position_share_of_both"] == 0.0

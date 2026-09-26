from scripts.s6_group_b_position_scores_eval import group_b_position_scores


def test_group_b_position_scores_uses_best_match_score_per_paragraph():
    axis = [
        {"axis_id": "p0", "flat_id": "res-1"},
        {"axis_id": "p1", "flat_id": "res-2"},
        {"axis_id": "p2", "flat_id": "res-1"},
    ]
    matches_by_flat_id = {
        "res-1": [{"match_score": 85.7}, {"match_score": 100.0}],
        "res-2": [{"match_score": 60.0}],
    }
    assert group_b_position_scores(axis, matches_by_flat_id) == {0: 1.0, 1: 0.6, 2: 1.0}


def test_group_b_position_scores_skips_paragraphs_with_no_matches():
    axis = [{"axis_id": "p0", "flat_id": "res-unmatched"}]
    assert group_b_position_scores(axis, {}) == {}


def test_group_b_position_scores_caps_at_one():
    axis = [{"axis_id": "p0", "flat_id": "res-1"}]
    matches_by_flat_id = {"res-1": [{"match_score": 250.0}]}
    assert group_b_position_scores(axis, matches_by_flat_id) == {0: 1.0}

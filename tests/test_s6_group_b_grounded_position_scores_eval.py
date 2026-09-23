from scripts.s6_group_b_grounded_position_scores_eval import group_b_grounded_position_scores


def test_grounded_filter_drops_ungrounded_matches():
    axis = [{"axis_id": "p0", "flat_id": "res-1"}]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Holland", "match_score": 90.0}]}
    assert group_b_grounded_position_scores(axis, matches_by_flat_id, grounded_names=set()) == {}


def test_grounded_filter_keeps_grounded_matches_and_takes_best_score():
    axis = [{"axis_id": "p0", "flat_id": "res-1"}]
    matches_by_flat_id = {
        "res-1": [
            {"canonical_name": "Holland", "match_score": 90.0},
            {"canonical_name": "Oudenbosch", "match_score": 60.0},
        ]
    }
    scores = group_b_grounded_position_scores(axis, matches_by_flat_id, grounded_names={"oudenbosch"})
    assert scores == {0: 0.6}


def test_grounded_filter_is_case_insensitive():
    axis = [{"axis_id": "p0", "flat_id": "res-1"}]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Oudenbosch", "match_score": 85.0}]}
    scores = group_b_grounded_position_scores(axis, matches_by_flat_id, grounded_names={"oudenbosch"})
    assert scores == {0: 0.85}

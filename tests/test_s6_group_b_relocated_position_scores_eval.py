from scripts.s6_group_b_relocated_position_scores_eval import group_b_relocated_position_scores


def test_relocated_scores_only_the_paragraph_containing_the_name():
    axis = [
        {"axis_id": "p0", "flat_id": "res-1", "text": "Rotterdam sent a delegate."},
        {"axis_id": "p1", "flat_id": "res-1", "text": "The chamber convened as usual."},
    ]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Rotterdam", "match_score": 100.0}]}
    assert group_b_relocated_position_scores(axis, matches_by_flat_id) == {0: 1.0}


def test_relocated_scores_skips_paragraphs_with_no_matches():
    axis = [{"axis_id": "p0", "flat_id": "res-unmatched", "text": "Some text."}]
    assert group_b_relocated_position_scores(axis, {}) == {}


def test_relocated_scores_drops_flat_matches_that_localize_nowhere():
    axis = [
        {"axis_id": "p0", "flat_id": "res-1", "text": "Unrelated opening formula."},
        {"axis_id": "p1", "flat_id": "res-1", "text": "Also unrelated closing text."},
    ]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Zeeland", "match_score": 85.7}]}
    assert group_b_relocated_position_scores(axis, matches_by_flat_id) == {}


def test_relocated_scores_use_fuzzy_fallback_within_threshold():
    axis = [{"axis_id": "p0", "flat_id": "res-1", "text": "The delegate from Uijtrecht spoke."}]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Utrecht", "match_score": 85.7}]}
    scores = group_b_relocated_position_scores(axis, matches_by_flat_id)
    assert set(scores) == {0}
    assert scores[0] >= 0.85

from scripts.s6_group_b_candidate_grounded_position_scores_eval import (
    anchor_backbone,
    group_b_candidate_grounded_position_scores,
)


def test_anchor_backbone_matches_segment_day_convention():
    backbone = anchor_backbone(3, 5, [(1, 1), (2, 3)])
    assert backbone == [(0, 0), (1, 1), (2, 3), (3, 5)]


def test_anchor_backbone_clips_out_of_order_anchors_forward():
    backbone = anchor_backbone(3, 5, [(1, 3), (2, 1)])
    assert backbone == [(0, 0), (1, 3), (2, 3), (3, 5)]


def test_candidate_grounded_scores_only_gaps_candidate_entities():
    axis = [
        {"axis_id": "p0", "flat_id": "res-1"},
        {"axis_id": "p1", "flat_id": "res-1"},
    ]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Rotterdam", "match_score": 90.0}]}
    backbone = [(0, 0), (2, 2)]
    enriched_ids = ["cand-1"]
    items_by_key = {"cand-1": {"places": ["Rotterdam"]}}
    stats = {"candidate_slots": 0, "candidate_slots_matched": 0}

    scores = group_b_candidate_grounded_position_scores(
        axis, matches_by_flat_id, backbone, enriched_ids, items_by_key,
        loc_names={}, per_names={}, org_names={}, persons_info={}, institution_names={},
        candidate_stats=stats,
    )

    assert scores == {0: 0.9, 1: 0.9}
    assert stats == {"candidate_slots": 1, "candidate_slots_matched": 1}


def test_candidate_grounded_drops_matches_not_claimed_by_the_gaps_own_candidates():
    axis = [{"axis_id": "p0", "flat_id": "res-1"}]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Holland", "match_score": 90.0}]}
    backbone = [(0, 0), (1, 1)]
    enriched_ids = []  # no gap between (0,0) and (1,1): right_enriched - left_enriched - 1 == 0
    items_by_key = {}
    stats = {"candidate_slots": 0, "candidate_slots_matched": 0}

    scores = group_b_candidate_grounded_position_scores(
        axis, matches_by_flat_id, backbone, enriched_ids, items_by_key,
        loc_names={}, per_names={}, org_names={}, persons_info={}, institution_names={},
        candidate_stats=stats,
    )

    assert scores == {}


def test_candidate_grounded_skips_unmatched_candidate_ids_and_records_the_miss():
    axis = [{"axis_id": "p0", "flat_id": "res-1"}]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Rotterdam", "match_score": 90.0}]}
    backbone = [(0, 0), (2, 1)]
    enriched_ids = ["cand-missing"]
    items_by_key = {}
    stats = {"candidate_slots": 0, "candidate_slots_matched": 0}

    scores = group_b_candidate_grounded_position_scores(
        axis, matches_by_flat_id, backbone, enriched_ids, items_by_key,
        loc_names={}, per_names={}, org_names={}, persons_info={}, institution_names={},
        candidate_stats=stats,
    )

    assert scores == {}
    assert stats == {"candidate_slots": 1, "candidate_slots_matched": 0}


def test_candidate_grounded_drops_names_not_in_gap_candidates_own_entities():
    axis = [{"axis_id": "p0", "flat_id": "res-1"}]
    matches_by_flat_id = {"res-1": [{"canonical_name": "Holland", "match_score": 90.0}]}
    backbone = [(0, 0), (2, 1)]
    enriched_ids = ["cand-1"]
    items_by_key = {"cand-1": {"places": ["Rotterdam"]}}
    stats = {"candidate_slots": 0, "candidate_slots_matched": 0}

    scores = group_b_candidate_grounded_position_scores(
        axis, matches_by_flat_id, backbone, enriched_ids, items_by_key,
        loc_names={}, per_names={}, org_names={}, persons_info={}, institution_names={},
        candidate_stats=stats,
    )

    assert scores == {}

import numpy as np
import pytest

from scripts.s6c_gap_segmentation import (
    segment_day,
    segment_gap,
    similarity_position_scores,
    similarity_rank_scores,
)


def test_no_resolutions_needs_no_slots():
    assert segment_gap(0, 10, 0) == []


def test_even_split_matches_plain_interpolation_with_no_evidence():
    # Same shape as interpolate_positions(4, 12, [(0, 1), (3, 10)]) == [4, 7, 10];
    # segment_gap is handed the single interior gap directly: from anchor axis 1 to
    # anchor axis 10, 2 unplaced resolutions.
    assert segment_gap(1, 10, 2) == [4, 7]


def test_phrase_bonus_pulls_the_slot_toward_a_nearby_hit():
    # Ideal split of a 1-resolution gap from 0 to 10 is position 5; a strong phrase hit
    # one paragraph away is worth more than the dispersion penalty of moving there.
    assert segment_gap(0, 10, 1, {6: 1.0}) == [6]


def test_weak_or_distant_evidence_does_not_override_the_even_split():
    # A hit far from the ideal costs more dispersion than its bonus is worth.
    assert segment_gap(0, 10, 1, {9: 0.5}) == [5]


def test_repeats_are_allowed_when_the_gap_is_narrower_than_the_count():
    # Only one paragraph (index 3) available for 3 resolutions -- must repeat, not abort.
    result = segment_gap(3, 4, 3)
    assert result == [3, 3, 3]


def test_segment_day_needs_no_anchors_for_a_single_resolution_day():
    assert segment_day(1, 12, []) == []


def test_segment_day_interpolates_between_a_strict_entity_anchor_and_the_end_sentinel():
    # Anchor at enriched index 3 pins that resolution to paragraph 10; the two unplaced
    # resolutions before it (1, 2) split evenly between the structural session-start
    # sentinel (0, 0) and that anchor.
    assert segment_day(4, 12, [(3, 10)]) == [3, 6, 10]


def test_segment_day_prefers_the_structural_start_sentinel_over_an_enriched_index_zero_anchor():
    # Unlike interpolate_positions, an NW match at enriched index 0 does not override
    # "resolution 0 starts the session" (STEP_S6 section 2.2 group D / s6b's chain
    # convention) -- it is dropped from the backbone rather than shifting the origin.
    assert segment_day(4, 12, [(0, 1), (3, 10)]) == segment_day(4, 12, [(3, 10)])


def test_segment_day_never_aborts_when_axis_is_shorter_than_k_e():
    # interpolate_positions(4, 3, [(0, 0), (3, 2)]) is None -- this must still return
    # a monotone (non-decreasing) answer of the right length.
    result = segment_day(4, 3, [(0, 0), (3, 2)])
    assert len(result) == 3
    assert result == sorted(result)
    assert all(0 <= position < 3 for position in result)


def test_segment_day_never_aborts_on_folded_non_monotone_anchors():
    # Two different enriched resolutions (1 and 2) both anchor to paragraph 4 -- strictly
    # increasing anchors don't exist, but a non-decreasing backbone still does.
    result = segment_day(4, 10, [(1, 4), (2, 4)])
    assert len(result) == 3
    assert result == sorted(result)


def test_rank_scores_pull_each_slot_to_its_own_resolutions_evidence():
    # Two slots in a gap from 0 to 12 (ideal split: 4, 8). Slot 1's resolution likes
    # paragraph 2 and slot 2's likes paragraph 10 -- a single shared `position_scores` map
    # cannot express that, since it would offer both hits to both slots.
    assert segment_gap(0, 12, 2, rank_scores=[{2: 1.0}, {10: 1.0}]) == [2, 10]


def test_rank_scores_cannot_invert_the_order_of_two_slots():
    # Slot 1's evidence sits *after* slot 2's. The DP fills slots in increasing position, so
    # the result must stay non-decreasing -- at most one of the two hits can be honoured.
    result = segment_gap(0, 12, 2, rank_scores=[{10: 1.0}, {2: 1.0}])
    assert result == sorted(result)


def test_rank_scores_supersede_position_scores_for_the_slots_they_cover():
    # The shared map's hit at 6 is ignored where a rank-specific map exists, even an empty one.
    assert segment_gap(0, 10, 1, {6: 1.0}, rank_scores=[{}]) == [5]
    assert segment_gap(0, 10, 1, {6: 1.0}, rank_scores=[{3: 1.0}]) == [3]


def test_segment_day_routes_resolution_scores_to_the_right_gap_slot():
    # Gap after the (0, 0) sentinel holds enriched resolutions 1 and 2 (anchor at 3).
    # Keying by enriched index -- not by rank -- is what makes the evidence addressable.
    positions = segment_day(
        4, 12, [(3, 10)], resolution_scores={1: {2: 1.0}, 2: {7: 1.0}}
    )
    assert positions == [2, 7, 10]


def test_segment_day_ignores_resolution_scores_for_anchored_resolutions():
    # Resolution 3 is pinned by an anchor, so its own similarity row must not move it.
    assert segment_day(4, 12, [(3, 10)], resolution_scores={3: {5: 1.0}}) == segment_day(
        4, 12, [(3, 10)]
    )


def test_rank_scores_keep_rows_apart_where_the_collapsed_form_cannot():
    # Resolution 0 matches paragraph 0, resolution 1 matches paragraph 2. The collapsed
    # per-paragraph max reports both paragraphs as equally good for everyone; the per-rank
    # form retains which row each hit came from. This is the mechanism difference the
    # corpus re-run tests, stated as an assertion rather than prose.
    matrix = np.array([[0.9, 0.1, 0.2], [0.2, 0.1, 0.8]])
    collapsed = similarity_position_scores(matrix, scale=1.0)
    assert collapsed[0] == pytest.approx(0.9)
    assert collapsed[2] == pytest.approx(0.8)
    per_rank = similarity_rank_scores(matrix, scale=1.0, normalize="raw")
    assert per_rank[0][0] == pytest.approx(0.9)
    assert per_rank[1][2] == pytest.approx(0.8)
    assert per_rank[1][0] == pytest.approx(0.2)


def test_rownorm_cancels_the_absolute_similarity_level():
    # Two resolutions with the same *shape* but 10x different levels -- the failure mode
    # commit 8f90e4b diagnosed -- must produce identical bonuses under rownorm.
    matrix = np.array([[0.02, 0.01], [0.20, 0.10]])
    scores = similarity_rank_scores(matrix, scale=1.0, normalize="rownorm")
    assert scores[0] == pytest.approx(scores[1])
    assert scores[0][0] == pytest.approx(1.0)


def test_zscore_keeps_only_paragraphs_above_a_resolutions_own_mean():
    matrix = np.array([[0.30, 0.10, 0.10, 0.10]])
    scores = similarity_rank_scores(matrix, scale=1.0, normalize="zscore")
    assert set(scores[0]) == {0}


def test_similarity_rank_scores_tolerates_an_empty_or_degenerate_matrix():
    assert similarity_rank_scores(np.zeros((0, 0))) == {}
    # A flat row has no dispersion to standardise by and must not divide by zero.
    assert similarity_rank_scores(np.array([[0.5, 0.5]]), normalize="zscore") == {}


def test_similarity_rank_scores_rejects_an_unknown_normalization():
    with pytest.raises(ValueError):
        similarity_rank_scores(np.array([[0.5, 0.1]]), normalize="softmax")


def test_segment_day_clips_an_out_of_order_anchor_instead_of_aborting():
    # The anchor at enriched index 2 points backwards in axis space relative to the
    # anchor at enriched index 1 -- almost certainly noise, but it must not crash the
    # whole day; the offending anchor is clipped forward.
    result = segment_day(4, 10, [(1, 6), (2, 2)])
    # Filter out None values for comparison with the old behavior
    resolved = [r for r in result if r is not None]
    assert len(resolved) >= 1
    assert resolved == sorted(resolved)
    assert resolved[0] == 6


def test_segment_day_abstains_on_forced_collapse_gaps():
    # A gap where 3 unanchored resolutions must fit into 1 paragraph (room=1) is
    # provably unseparable: floor = ceil(3/1) = 3 > 1. All three should be None.
    # Setup: enriched_count=5, axis has 3 paragraphs. Anchors at 0 and 4 with
    # room=1 (between paragraphs 0 and 1). Gap has 3 unanchored resolutions (1,2,3).
    result = segment_day(5, 3, [(0, 0), (4, 1)])
    # Positions are [p1, p2, p3, p4]. p4 is anchored at paragraph 1 (from anchor at index 4).
    # The gap between (0,0) and (4,1) has room=1 and 3 resolutions, so all should be None.
    assert len(result) == 4
    # p1, p2, p3 should be None (floor=3 > 1)
    assert result[0] is None
    assert result[1] is None
    assert result[2] is None
    # p4 should be anchored
    assert result[3] == 1


def test_segment_day_resolves_floor_equals_1_gaps():
    # A gap where 2 unanchored resolutions fit into 2 paragraphs has room=2 and
    # floor = ceil(2/2) = 1, so the gap should be resolved normally via segment_gap.
    result = segment_day(4, 12, [(3, 10)])
    # Without anchors at start, we have backbone: (0,0), (3,10), (4,12)
    # Gap 1: from 0 to 3, enriched gap=2, axis gap room=10, floor=1 -> resolve via segment_gap
    # Gap 2: from 3 to 4, enriched gap=0, no gap
    assert len(result) == 3
    assert result[0] is not None
    assert result[1] is not None
    assert result[2] == 10  # anchored


def test_segment_day_mixes_resolved_and_abstained_gaps():
    # Multiple gaps, some resolvable (floor=1) and some not (floor>1).
    # Setup: 7 resolutions, 12 paragraphs
    # Anchors at (2, 2) and (5, 4) and (6, 6)
    # Gap 1: enriched [0,2) gap=1, axis [0,2) room=2, floor=1 -> resolve
    # Gap 2: enriched [2,5) gap=2, axis [2,4) room=2, floor=1 -> resolve
    # Gap 3: enriched [5,6) gap=0, no gap
    result = segment_day(7, 12, [(2, 2), (5, 4), (6, 6)])
    assert len(result) == 6
    # All should be resolved for these gaps
    resolved = [r for r in result if r is not None]
    assert len(resolved) == 6
    assert result[-1] == 6  # last one is anchored

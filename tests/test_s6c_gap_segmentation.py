from scripts.s6c_gap_segmentation import segment_day, segment_gap


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


def test_segment_day_clips_an_out_of_order_anchor_instead_of_aborting():
    # The anchor at enriched index 2 points backwards in axis space relative to the
    # anchor at enriched index 1 -- almost certainly noise, but it must not crash the
    # whole day; the offending anchor is clipped forward.
    result = segment_day(4, 10, [(1, 6), (2, 2)])
    assert len(result) == 3
    assert result == sorted(result)
    assert result[0] == 6

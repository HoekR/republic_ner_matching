from scripts.s4_paragraph_axis_baseline import interpolate_positions, overlap_enriched_id, project_boundaries, snap_to_phrase


def test_normalizes_fallback_enriched_id_to_overlap_key():
    assert overlap_enriched_id("163006ap.xml#11", "1630-04-06") == "1630-04-06_11"


def test_projects_monotone_enriched_matches_to_paragraph_starts():
    assert project_boundaries(3, [(0, 1), (1, 4), (2, 7)]) == [4, 7]


def test_abstains_when_any_enriched_item_has_no_match():
    assert project_boundaries(3, [(0, 1), (1, None), (2, 7)]) is None


def test_interpolates_unanchored_items_between_entity_matches():
    assert interpolate_positions(4, 12, [(0, 1), (3, 10)]) == [4, 7, 10]


def test_interpolation_abstains_when_axis_is_too_short():
    assert interpolate_positions(4, 3, [(0, 0), (3, 2)]) is None


def test_snap_to_phrase_prefers_the_closest_candidate():
    hits = {1: ("is gelesen", 0, 1.0), 4: ("ontfangen een missive", 20, 0.9)}
    assert snap_to_phrase(3, hits) == (4, ("ontfangen een missive", 20, 0.9))
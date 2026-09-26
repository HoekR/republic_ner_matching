from scripts.s4_resolution_baseline import project_resolution_boundaries


def test_projects_all_enriched_transitions_to_flat_starts():
    alignments = [(0, 1), (1, 3), (2, 4)]

    assert project_resolution_boundaries(3, alignments) == [3, 4]


def test_abstains_when_an_enriched_resolution_is_unmatched():
    alignments = [(0, 1), (1, None), (2, 4)]

    assert project_resolution_boundaries(3, alignments) is None


def test_abstains_for_non_monotone_projection():
    alignments = [(0, 3), (1, 2), (2, 4)]

    assert project_resolution_boundaries(3, alignments) is None
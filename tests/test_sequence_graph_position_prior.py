"""Step 1 of the positional-prior design (user, 2026-10-09): measure before building.

Answers whether a local uniform-spread expectation predicts a gold resolution's true position
well enough to be worth turning into a CostModel term. Not yet wired into align.py/CostModel --
see sequence_graph/position_prior.py's own module docstring.
"""

from __future__ import annotations

from sequence_graph.position_prior import measure_displacement, summarize


def test_measure_displacement_is_non_circular_and_well_shaped():
    """Every row must come from a real gold-located resolution, never a guess or a solver edge --
    and the two coordinates must be genuinely different sources (true position from gold
    annotation, expected position from pure counting), not the same number twice."""
    displacements = measure_displacement()
    assert len(displacements) > 0
    assert set(displacements.columns) >= {
        "date", "ref_index", "k_e", "room", "true_position", "expected_position", "displacement",
    }
    assert (displacements["true_position"] >= 0).all()
    assert (displacements["expected_position"] >= 0).all()
    assert (displacements["displacement"] == displacements["true_position"] - displacements["expected_position"]).all()


def test_the_median_prediction_is_unbiased():
    """The uniform-spread expectation should not be systematically early or late -- a real signal
    worth building on has to center near zero, not just be tight around some other offset."""
    displacements = measure_displacement()
    stats = summarize(displacements)
    assert stats["median"] == 0


def test_known_severe_mismatch_days_dominate_the_tail():
    """1626-11-16 (k_e=14 vs k_f=47) and 1626-10-27 are already-documented severe
    over-segmentation cases elsewhere in this project (notebooks/sequence_graph_exploration.ipynb
    tested 1626-11-16 directly). This pins that finding down as a regression: removing exactly
    these two days should sharply tighten the distribution, confirming the tail is a known,
    nameable pathology class and not generic noise across the whole corpus."""
    displacements = measure_displacement()
    full_std = summarize(displacements)["std"]
    clean = displacements[~displacements["date"].isin(["1626-11-16", "1626-10-27"])]
    clean_std = summarize(clean)["std"]
    assert clean_std < full_std / 2  # removing 2 of ~33 days more than halves the spread

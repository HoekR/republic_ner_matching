"""Stage 4's calibration pass: match_cost/gap_cost fit on gold, non-circularly.

`plans/SEQUENCE_GRAPH_SPINE.md` Stage 4, "Next" item (a). Functional tests against the real
corpus (`boundary_gold_sample`), same convention as `test_sequence_graph_align.py`'s real-data
adapter tests -- the synthetic/no-corpus-access tests live there, these need gold.
"""

from __future__ import annotations

import math

from sequence_graph.align import CostModel
from sequence_graph.fit_cost import (
    build_calibration_pairs,
    fit_cost_model,
    fit_deletion_rate,
    fit_match_logit,
)


def test_calibration_pairs_are_balanced_positive_and_negative():
    """One gold-matched positive and one within-day-derangement negative per located resolution
    -- never an imbalanced or empty set, or the logistic fit downstream is meaningless."""
    pairs = build_calibration_pairs()
    assert len(pairs) > 0
    assert len(pairs) % 2 == 0
    assert (pairs["label"] == 1).sum() == (pairs["label"] == 0).sum()


def test_calibration_pairs_never_touch_a_solver_derived_edge():
    """Non-circularity by construction: every row comes from boundary_gold_sample's own hand-
    verified boundaries, not from sequence_graph.align's own DP output -- there is no code path
    here that could read a derived ALIGNED_TO edge back in as training data."""
    import inspect

    from sequence_graph import fit_cost

    source = inspect.getsource(fit_cost)
    assert "align_bracket" not in source  # the DP itself is never invoked to build training data
    assert "add_aligned_to_solver" not in source


def test_positive_overlap_scores_exceed_negative_on_average():
    """The calibration signal must point the right way: a real match should score higher overlap
    than a same-day wrong pairing, on average -- otherwise fitting a logistic curve to it would
    just encode noise."""
    pairs = build_calibration_pairs()
    positive_mean = pairs.loc[pairs["label"] == 1, "overlap"].mean()
    negative_mean = pairs.loc[pairs["label"] == 0, "overlap"].mean()
    assert positive_mean > negative_mean


def test_fit_match_logit_has_a_positive_slope():
    """Higher overlap must predict a match, not the reverse -- `coef` positive is the sign
    convention `CostModel.match_cost` relies on (cost decreases as `z = intercept + coef*overlap`
    grows)."""
    pairs = build_calibration_pairs()
    _intercept, coef = fit_match_logit(pairs)
    assert coef > 0


def test_fit_deletion_rate_is_a_genuine_proportion():
    rate = fit_deletion_rate()
    assert 0.0 <= rate <= 1.0


def test_fitted_cost_model_only_changes_match_cost_and_gap_cost():
    """Scope discipline: insertion_cost/split_discount/soft_clip_cost are NOT calibrated this
    pass (no split-vs-margin-content labels exist in gold) -- the fitted model must carry the
    base model's values for those unchanged, not silently drift."""
    base = CostModel(soft_clip_cost=0.73, split_discount=0.21, base_match=1.5, match_lambda=0.9)
    fitted, _report = fit_cost_model(base)
    assert fitted.soft_clip_cost == base.soft_clip_cost
    assert fitted.split_discount == base.split_discount
    assert fitted.base_match == base.base_match
    assert fitted.match_lambda == base.match_lambda
    assert fitted.match_logit is not None
    assert fitted.gap_cost != base.gap_cost  # this one IS expected to move


def test_fitted_match_cost_still_decreases_with_overlap():
    """Same invariant as the unfitted form's own test (test_defect_4 in
    test_sequence_graph_align.py): more evidence must keep costing less, regardless of which
    formula produces the number."""
    fitted, _report = fit_cost_model()
    low = fitted.match_cost(0.0)
    mid = fitted.match_cost(1.0)
    high = fitted.match_cost(5.0)
    assert low > mid > high


def test_fitted_match_cost_is_a_real_log_probability_not_the_linear_form():
    """`match_logit` set must route through `-log(sigmoid(z))`, not the old `base - lambda*overlap`
    -- checked by comparing against a hand-computed softplus at one point, not just "it runs"."""
    model = CostModel(match_logit=(0.0, 1.0))  # z = overlap; at overlap=0, sigmoid(0) = 0.5
    expected = math.log1p(math.exp(0.0))  # -log(0.5) = log(2)
    assert model.match_cost(0.0) == expected
    assert abs(expected - math.log(2)) < 1e-9


def test_unfitted_cost_model_is_unaffected_by_match_logit_being_unset():
    """`CostModel()`'s default stays the original linear form -- no behavior change for every
    existing caller that doesn't pass `match_logit`."""
    model = CostModel()
    assert model.match_logit is None
    assert model.match_cost(1.0) == max(model.epsilon, model.base_match - model.match_lambda * 1.0)

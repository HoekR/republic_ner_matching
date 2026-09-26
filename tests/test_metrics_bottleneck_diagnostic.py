"""Unit tests for Tier P bottleneck diagnostic decision aid."""

from __future__ import annotations

from scripts.metrics_bottleneck_diagnostic import classify_bottleneck, run_placement


def test_classify_bottleneck_redesign_when_oracle_low():
    result = classify_bottleneck(oracle_coverage=0.263, real_coverage=0.05)
    assert result["recommended_focus"] == "algorithm_redesign"
    assert result["coverage_gap"] == round(0.263 - 0.05, 4)


def test_classify_bottleneck_evidence_when_gap_large_and_oracle_ok():
    result = classify_bottleneck(oracle_coverage=0.70, real_coverage=0.40)
    assert result["recommended_focus"] == "tier_a_d_evidence"


def test_classify_bottleneck_placement_when_gap_small():
    result = classify_bottleneck(oracle_coverage=0.70, real_coverage=0.65)
    assert result["recommended_focus"] == "tier_p_placement"


def test_run_placement_abstains_on_non_monotone_anchors():
    result = run_placement(
        k_e=3,
        axis_count=8,
        anchors=[(0, 0), (1, 2), (2, 2)],
        starts=[0, 10, 20, 30, 40, 50, 60, 70],
        hits={},
    )
    assert result["status"] == "abstained"
    assert result["reason"] == "folded_anchors_non_monotone"


def test_run_placement_predicts_on_monotone_anchors():
    result = run_placement(
        k_e=3,
        axis_count=8,
        anchors=[(0, 0), (1, 2), (2, 5)],
        starts=[0, 10, 20, 30, 40, 50, 60, 70],
        hits={},
    )
    assert result["status"] == "predicted"
    assert len(result["hyp_composed"]) >= 1

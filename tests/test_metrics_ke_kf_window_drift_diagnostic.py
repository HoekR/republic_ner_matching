"""Unit tests for the windowed K_e-vs-K_f shift-signature diagnostic."""

from __future__ import annotations

import pandas as pd

from scripts.metrics_ke_kf_window_drift_diagnostic import (
    build_output_records,
    classify_shift_signature,
    collision_weak_separation_crosstab,
    complementary_adjacent_pairs,
    lag1_autocorrelation,
    load_predictions_frame,
    residual_series,
    select_windows,
    session_collision_dates,
    summarize_window,
)


def test_load_predictions_frame_extracts_required_columns():
    records = [
        {"date": "1626-01-01", "k_e": 5, "paragraph_count": 3, "status": "predicted", "reason": None},
        {"date": "1626-01-02", "k_e": 0, "paragraph_count": 0, "status": "abstained", "reason": "missing_htr"},
    ]
    frame = load_predictions_frame(records)
    assert list(frame["date"]) == ["1626-01-01", "1626-01-02"]
    assert frame.loc[0, "k_e"] == 5
    assert frame.loc[1, "reason"] == "missing_htr"


def test_select_windows_filters_by_threshold_and_excludes_adjacent_solid():
    gaps = [
        {"record_type": "gap", "n_nonsolid_session_days": 15, "dominant_class": "weak_separation"},
        {"record_type": "gap", "n_nonsolid_session_days": 3, "dominant_class": "weak_separation"},
        {"record_type": "gap", "n_nonsolid_session_days": 0, "dominant_class": "adjacent_solid"},
        {"record_type": "day", "n_nonsolid_session_days": 99},
    ]
    selected = select_windows(gaps, min_gap_session_days=8)
    assert len(selected) == 1
    assert selected[0]["n_nonsolid_session_days"] == 15


def test_residual_series_is_ke_minus_paragraph_count():
    frame = pd.DataFrame({"k_e": [5, 2, 8], "paragraph_count": [3, 4, 1]})
    residuals = residual_series(frame)
    assert residuals.tolist() == [2, -2, 7]


def test_lag1_autocorrelation_none_when_too_short():
    assert lag1_autocorrelation(pd.Series([1, 2, 3])) is None


def test_complementary_adjacent_pairs_counts_sign_flips_above_magnitude():
    # +5, -4, +1 (below magnitude, ignored), +6, -5
    residuals = pd.Series([5, -4, 1, 6, -5])
    n_complementary, n_adjacent = complementary_adjacent_pairs(residuals, min_magnitude=2)
    # pairs: (5,-4) flip+strong -> yes; (-4,1) 1 below magnitude -> no;
    # (1,6) 1 below magnitude -> no; (6,-5) flip+strong -> yes
    assert n_complementary == 2
    assert n_adjacent == 4


def test_classify_shift_signature_alternating_pattern():
    assert (
        classify_shift_signature(autocorr=-0.6, complementary_share=0.1, mean_residual=1.0)
        == "shift_candidate"
    )
    assert (
        classify_shift_signature(autocorr=0.2, complementary_share=0.6, mean_residual=1.0)
        == "shift_candidate"
    )


def test_classify_shift_signature_uniform_shortfall():
    assert (
        classify_shift_signature(autocorr=0.5, complementary_share=0.0, mean_residual=3.0)
        == "uniform_shortfall"
    )


def test_classify_shift_signature_inconclusive_when_no_signal():
    assert classify_shift_signature(autocorr=None, complementary_share=None, mean_residual=0.0) == "inconclusive"


def test_summarize_window_alternating_synthetic_window():
    gap = {
        "left_solid_date": "1626-01-10",
        "right_solid_date": "1626-01-15",
        "n_nonsolid_session_days": 4,
        "dominant_class": "weak_separation",
    }
    window_frame = pd.DataFrame(
        {
            "date": ["1626-01-10", "1626-01-11", "1626-01-12", "1626-01-13", "1626-01-14", "1626-01-15"],
            "k_e": [5, 1, 6, 1, 6, 5],
            "paragraph_count": [5, 6, 1, 6, 1, 5],
            "status": ["predicted"] * 6,
            "reason": [None] * 6,
        }
    )
    summary = summarize_window(gap, window_frame)
    assert summary["n_window_days"] == 6
    assert summary["shift_signature"] == "shift_candidate"
    assert summary["n_complementary_adjacent_pairs"] >= 3


def test_session_collision_dates_finds_shared_session():
    concordance = [
        {"enriched_date": "1627-03-27", "day_status": "resolved_auto", "resolved_session_id": "s-55"},
        {"enriched_date": "1627-03-29", "day_status": "resolved_auto", "resolved_session_id": "s-55"},
        {"enriched_date": "1627-03-28", "day_status": "resolved_auto", "resolved_session_id": "s-56"},
        {"enriched_date": "1627-03-30", "day_status": "missing_htr", "resolved_session_id": None},
        # Duplicate row for the same date (e.g. multiple resolutions that date) must not
        # itself count as a collision.
        {"enriched_date": "1627-03-28", "day_status": "resolved_auto", "resolved_session_id": "s-56"},
    ]
    assert session_collision_dates(concordance) == {"1627-03-27", "1627-03-29"}


def test_collision_weak_separation_crosstab_effect_size():
    day_frame = pd.DataFrame(
        [
            {"enriched_date": "1627-03-27", "day_status": "resolved_auto", "nonsolid_class": "weak_separation"},
            {"enriched_date": "1627-03-29", "day_status": "resolved_auto", "nonsolid_class": "weak_separation"},
            {"enriched_date": "1627-03-28", "day_status": "resolved_auto", "nonsolid_class": None},
            {"enriched_date": "1627-03-30", "day_status": "resolved_auto", "nonsolid_class": None},
        ]
    )
    crosstab = collision_weak_separation_crosstab(
        day_frame,
        resolved_dates={"1627-03-27", "1627-03-29", "1627-03-28", "1627-03-30"},
        collision_dates={"1627-03-27", "1627-03-29"},
    )
    assert crosstab["n_collision_days"] == 2
    assert crosstab["collision_weak_separation_rate"] == 1.0
    assert crosstab["noncollision_weak_separation_rate"] == 0.0
    assert crosstab["n_weak_separation_days_total"] == 2
    assert crosstab["weak_separation_days_collision_share"] == 1.0


def test_build_output_records_meta_counts_signatures():
    windows = [
        {
            "left_solid_date": "1626-01-10",
            "right_solid_date": "1626-01-12",
            "n_nonsolid_session_days": 8,
            "dominant_class": "weak_separation",
        }
    ]
    predictions = pd.DataFrame(
        {
            "date": ["1626-01-10", "1626-01-11", "1626-01-12"],
            "k_e": [5, 8, 5],
            "paragraph_count": [5, 2, 5],
            "status": ["predicted"] * 3,
            "reason": [None] * 3,
        }
    )
    day_frame = pd.DataFrame(
        [
            {"enriched_date": "1626-01-10", "day_status": "resolved_auto", "nonsolid_class": None},
            {"enriched_date": "1626-01-11", "day_status": "resolved_auto", "nonsolid_class": "weak_separation"},
            {"enriched_date": "1626-01-12", "day_status": "resolved_auto", "nonsolid_class": None},
        ]
    )
    records = build_output_records(
        windows,
        predictions,
        day_frame=day_frame,
        resolved_dates={"1626-01-10", "1626-01-11", "1626-01-12"},
        collision_dates={"1626-01-11"},
    )
    meta = records[0]
    assert meta["record_type"] == "meta"
    assert meta["n_windows_inspected"] == 1
    assert sum(meta["shift_signature_counts"].values()) == 1
    assert meta["n_session_collision_dates_corpus"] == 1
    crosstab = records[1]
    assert crosstab["record_type"] == "corpus_collision_crosstab"
    assert crosstab["n_weak_separation_days_collision_involved"] == 1
    window = records[2]
    assert window["record_type"] == "window"
    assert len(window["days"]) == 3

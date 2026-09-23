"""Unit tests for the windowed K_e-vs-K_f shift-signature diagnostic."""

from __future__ import annotations

import pandas as pd

from scripts.metrics_ke_kf_window_drift_diagnostic import (
    build_output_records,
    classify_shift_signature,
    complementary_adjacent_pairs,
    lag1_autocorrelation,
    load_predictions_frame,
    residual_series,
    select_windows,
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
    records = build_output_records(windows, predictions)
    meta = records[0]
    assert meta["record_type"] == "meta"
    assert meta["n_windows_inspected"] == 1
    assert sum(meta["shift_signature_counts"].values()) == 1
    assert records[1]["record_type"] == "window"
    assert len(records[1]["days"]) == 3

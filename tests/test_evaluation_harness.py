import pytest
from evaluation_harness import (
    compute_boundary_prf,
    compute_pk_and_windowdiff,
    evaluate_segmentation_session,
    summarize_segmentation_evaluations,
    evaluate_audited_backtest,
)

def test_boundary_prf_exact_match():
    ref = [2, 5, 8]
    hyp = [2, 5, 8]
    res = compute_boundary_prf(ref, hyp, tolerance=0)
    assert res.precision == 1.0
    assert res.recall == 1.0
    assert res.f1 == 1.0
    assert res.tp == 3
    assert res.fp == 0
    assert res.fn == 0
    assert res.exact_count_matched is True

def test_boundary_prf_tolerance():
    ref = [2, 5, 8]
    hyp = [2, 6, 8]
    res0 = compute_boundary_prf(ref, hyp, tolerance=0)
    assert res0.tp == 2
    assert res0.fp == 1
    assert res0.fn == 1
    assert abs(res0.precision - 2/3) < 1e-5
    
    res1 = compute_boundary_prf(ref, hyp, tolerance=1)
    assert res1.tp == 3
    assert res1.fp == 0
    assert res1.fn == 0
    assert res1.precision == 1.0
    assert res1.recall == 1.0

def test_pk_and_windowdiff_perfect():
    ref = [2, 5]
    hyp = [2, 5]
    seg = compute_pk_and_windowdiff(ref, hyp, total_length=10)
    assert seg.p_k == 0.0
    assert seg.window_diff == 0.0

def test_pk_and_windowdiff_mismatch():
    ref = [2, 5]
    hyp = [4, 8]
    seg = compute_pk_and_windowdiff(ref, hyp, total_length=10)
    assert seg.p_k > 0.0
    assert seg.window_diff > 0.0

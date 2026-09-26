#!/usr/bin/env python3
"""Evaluation harness for count-constrained segmentation transfer and alignment.

Implements primary boundary segmentation metrics (tolerance-aware Precision/Recall/F1,
WindowDiff, P_k, and exact-count satisfaction) and secondary pair-level backtest
evaluations (audited 42-pair benchmark) as defined in docs/SEGMENTATION_TRANSFER.md.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd


@dataclass
class BoundaryMetrics:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    tolerance: int
    exact_count_matched: bool


@dataclass
class TextSegmentationMetrics:
    p_k: float
    window_diff: float
    window_size_k: int
    unit_length: int
    ref_boundary_count: int
    hyp_boundary_count: int


@dataclass
class SessionEvaluationResult:
    session_id: str
    date: str
    k_e: int  # normative resolution count
    k_pred: int  # predicted resolution count
    exact_count_satisfied: bool
    boundary_metrics: dict[int, BoundaryMetrics]  # tolerance -> metrics
    seg_metrics: TextSegmentationMetrics | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def compute_boundary_prf(
    ref_boundaries: Sequence[int],
    hyp_boundaries: Sequence[int],
    tolerance: int = 0,
) -> BoundaryMetrics:
    """Compute Precision, Recall, and F1 for predicted boundaries against reference.
    
    A predicted boundary is counted as True Positive if there is an unmatched
    reference boundary within distance <= tolerance.
    """
    sorted_ref = sorted(list(ref_boundaries))
    sorted_hyp = sorted(list(hyp_boundaries))
    
    if not sorted_ref and not sorted_hyp:
        return BoundaryMetrics(
            precision=1.0,
            recall=1.0,
            f1=1.0,
            tp=0,
            fp=0,
            fn=0,
            tolerance=tolerance,
            exact_count_matched=True,
        )
    
    if not sorted_hyp:
        return BoundaryMetrics(
            precision=0.0,
            recall=0.0,
            f1=0.0,
            tp=0,
            fp=0,
            fn=len(sorted_ref),
            tolerance=tolerance,
            exact_count_matched=False,
        )
        
    if not sorted_ref:
        return BoundaryMetrics(
            precision=0.0,
            recall=0.0,
            f1=0.0,
            tp=0,
            fp=len(sorted_hyp),
            fn=0,
            tolerance=tolerance,
            exact_count_matched=False,
        )

    matched_ref = set()
    tp = 0
    
    # Match each hyp to the closest available ref within tolerance
    for h in sorted_hyp:
        best_r = None
        best_dist = tolerance + 1
        for i, r in enumerate(sorted_ref):
            if i in matched_ref:
                continue
            dist = abs(h - r)
            if dist <= tolerance and dist < best_dist:
                best_dist = dist
                best_r = i
        if best_r is not None:
            matched_ref.add(best_r)
            tp += 1
            
    fp = len(sorted_hyp) - tp
    fn = len(sorted_ref) - tp
    precision = tp / len(sorted_hyp) if sorted_hyp else 0.0
    recall = tp / len(sorted_ref) if sorted_ref else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return BoundaryMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        fp=fp,
        fn=fn,
        tolerance=tolerance,
        exact_count_matched=(len(sorted_hyp) == len(sorted_ref)),
    )


def compute_pk_and_windowdiff(
    ref_boundaries: Sequence[int],
    hyp_boundaries: Sequence[int],
    total_length: int,
    k: int | None = None,
) -> TextSegmentationMetrics:
    """Compute Beeferman's P_k and Pevzner-Hearst's WindowDiff segmentation metrics.
    
    Parameters:
        ref_boundaries: integer cut-point indices in [1, total_length - 1]
        hyp_boundaries: integer cut-point indices in [1, total_length - 1]
        total_length: total sequence length (number of discrete units/lines/characters)
        k: window size. If None, default is round(total_length / (2 * (len(ref_boundaries) + 1)))
    """
    if total_length <= 1:
        return TextSegmentationMetrics(
            p_k=0.0,
            window_diff=0.0,
            window_size_k=1,
            unit_length=total_length,
            ref_boundary_count=len(ref_boundaries),
            hyp_boundary_count=len(hyp_boundaries),
        )

    num_ref = len(ref_boundaries)
    if k is None:
        avg_seg_len = total_length / max(1, num_ref + 1)
        k = max(1, int(round(avg_seg_len / 2.0)))

    # Construct boundary marker vectors of length total_length
    ref_vec = np.zeros(total_length, dtype=int)
    for b in ref_boundaries:
        if 0 <= b < total_length:
            ref_vec[b] = 1

    hyp_vec = np.zeros(total_length, dtype=int)
    for b in hyp_boundaries:
        if 0 <= b < total_length:
            hyp_vec[b] = 1

    # Prefix sums for O(1) interval boundary counting
    ref_prefix = np.zeros(total_length + 1, dtype=int)
    ref_prefix[1:] = np.cumsum(ref_vec)

    hyp_prefix = np.zeros(total_length + 1, dtype=int)
    hyp_prefix[1:] = np.cumsum(hyp_vec)

    num_windows = total_length - k
    if num_windows <= 0:
        # Edge case: window larger than text
        c_ref = ref_prefix[-1] - ref_prefix[0]
        c_hyp = hyp_prefix[-1] - hyp_prefix[0]
        pk_pen = 1.0 if ((c_ref == 0 and c_hyp > 0) or (c_ref > 0 and c_hyp == 0)) else 0.0
        wd_pen = 1.0 if c_ref != c_hyp else 0.0
        return TextSegmentationMetrics(
            p_k=pk_pen,
            window_diff=wd_pen,
            window_size_k=k,
            unit_length=total_length,
            ref_boundary_count=num_ref,
            hyp_boundary_count=len(hyp_boundaries),
        )

    pk_diffs = 0
    wd_diffs = 0

    for i in range(num_windows):
        c_ref = ref_prefix[i + k] - ref_prefix[i]
        c_hyp = hyp_prefix[i + k] - hyp_prefix[i]

        # P_k: penalizes if one sequence has boundaries and the other has none
        if (c_ref == 0 and c_hyp > 0) or (c_ref > 0 and c_hyp == 0):
            pk_diffs += 1

        # WindowDiff: penalizes any count discrepancy
        if c_ref != c_hyp:
            wd_diffs += 1

    return TextSegmentationMetrics(
        p_k=pk_diffs / num_windows,
        window_diff=wd_diffs / num_windows,
        window_size_k=k,
        unit_length=total_length,
        ref_boundary_count=num_ref,
        hyp_boundary_count=len(hyp_boundaries),
    )


def evaluate_segmentation_session(
    session_id: str,
    date: str,
    k_e: int,
    ref_boundaries: Sequence[int],
    hyp_boundaries: Sequence[int],
    total_length: int,
    tolerances: Sequence[int] = (0, 1, 2, 5),
    metadata: dict[str, Any] | None = None,
) -> SessionEvaluationResult:
    """Evaluate predicted cut-points for a single session-day."""
    k_pred = len(hyp_boundaries) + 1
    exact_count = (k_pred == k_e)
    
    boundary_metrics = {
        tol: compute_boundary_prf(ref_boundaries, hyp_boundaries, tolerance=tol)
        for tol in tolerances
    }
    
    seg_metrics = compute_pk_and_windowdiff(ref_boundaries, hyp_boundaries, total_length)
    
    return SessionEvaluationResult(
        session_id=session_id,
        date=date,
        k_e=k_e,
        k_pred=k_pred,
        exact_count_satisfied=exact_count,
        boundary_metrics=boundary_metrics,
        seg_metrics=seg_metrics,
        metadata=metadata or {},
    )


def summarize_segmentation_evaluations(
    results: Sequence[SessionEvaluationResult],
    tolerances: Sequence[int] = (0, 1, 2, 5),
) -> dict[str, Any]:
    """Aggregate per-session segmentation results across the corpus."""
    if not results:
        return {"total_sessions": 0, "error": "No results to summarize"}

    total = len(results)
    exact_count_matched = sum(1 for r in results if r.exact_count_satisfied)
    exact_count_rate = exact_count_matched / total

    summary: dict[str, Any] = {
        "total_sessions": total,
        "exact_count_satisfied_sessions": exact_count_matched,
        "exact_count_satisfaction_rate": exact_count_rate,
        "boundary_metrics_by_tolerance": {},
        "mean_pk": float(np.mean([r.seg_metrics.p_k for r in results if r.seg_metrics])),
        "mean_window_diff": float(np.mean([r.seg_metrics.window_diff for r in results if r.seg_metrics])),
    }

    for tol in tolerances:
        prs = [r.boundary_metrics[tol].precision for r in results if tol in r.boundary_metrics]
        recs = [r.boundary_metrics[tol].recall for r in results if tol in r.boundary_metrics]
        f1s = [r.boundary_metrics[tol].f1 for r in results if tol in r.boundary_metrics]
        total_tp = sum(r.boundary_metrics[tol].tp for r in results if tol in r.boundary_metrics)
        total_fp = sum(r.boundary_metrics[tol].fp for r in results if tol in r.boundary_metrics)
        total_fn = sum(r.boundary_metrics[tol].fn for r in results if tol in r.boundary_metrics)
        
        # Micro and Macro
        micro_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        micro_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) > 0 else 0.0

        summary["boundary_metrics_by_tolerance"][str(tol)] = {
            "macro_precision": float(np.mean(prs)),
            "macro_recall": float(np.mean(recs)),
            "macro_f1": float(np.mean(f1s)),
            "micro_precision": float(micro_p),
            "micro_recall": float(micro_r),
            "micro_f1": float(micro_f1),
            "total_tp": total_tp,
            "total_fp": total_fp,
            "total_fn": total_fn,
        }

    return summary


def evaluate_audited_backtest(
    audited_benchmark_path: Path | str,
    predictions_map: dict[str, str | None],
) -> dict[str, Any]:
    """Secondary evaluation: pair-level precision on the audited 42-pair backtest.
    
    Parameters:
        audited_benchmark_path: path to output/ground_truth_audited.json
        predictions_map: dict mapping enriched_id -> predicted flat_id (or None if abstained)
    """
    path = Path(audited_benchmark_path)
    if not path.exists():
        return {"error": f"Benchmark file not found: {path}"}

    items = json.loads(path.read_text(encoding="utf-8"))
    
    total_benchmark = len(items)
    correct_evaluated = 0
    fp_evaluated = 0
    abstained = 0
    missing = 0
    
    details = []
    for item in items:
        e_id = item["enriched_id"]
        gt_flat_id = item["flat_id"]
        gt_verdict = item.get("audited_verdict", "correct")
        
        pred_flat = predictions_map.get(e_id)
        if pred_flat is None:
            abstained += 1
            status = "abstained"
        elif pred_flat == gt_flat_id:
            if gt_verdict == "correct":
                correct_evaluated += 1
                status = "true_positive"
            else:
                fp_evaluated += 1
                status = "false_positive"
        else:
            fp_evaluated += 1
            status = "mismatch"

        details.append({
            "enriched_id": e_id,
            "ground_truth_flat_id": gt_flat_id,
            "predicted_flat_id": pred_flat,
            "status": status,
        })

    decided = correct_evaluated + fp_evaluated
    precision = correct_evaluated / decided if decided > 0 else 0.0
    coverage = decided / total_benchmark if total_benchmark > 0 else 0.0
    abstention_rate = abstained / total_benchmark if total_benchmark > 0 else 0.0

    return {
        "total_benchmark_pairs": total_benchmark,
        "decided_pairs": decided,
        "correct_pairs": correct_evaluated,
        "mismatched_pairs": fp_evaluated,
        "abstained_pairs": abstained,
        "precision_on_decided": precision,
        "coverage": coverage,
        "abstention_rate": abstention_rate,
        "details": details,
    }


if __name__ == "__main__":
    # Self-test unit check
    ref = [2, 5, 8]
    hyp = [2, 6, 8]
    total_len = 10
    prf_0 = compute_boundary_prf(ref, hyp, tolerance=0)
    prf_1 = compute_boundary_prf(ref, hyp, tolerance=1)
    seg = compute_pk_and_windowdiff(ref, hyp, total_len)
    
    print("Harness verification test:")
    print(f"Tol 0: P={prf_0.precision:.3f}, R={prf_0.recall:.3f}, F1={prf_0.f1:.3f}")
    print(f"Tol 1: P={prf_1.precision:.3f}, R={prf_1.recall:.3f}, F1={prf_1.f1:.3f}")
    print(f"P_k={seg.p_k:.3f}, WindowDiff={seg.window_diff:.3f}, k={seg.window_size_k}")

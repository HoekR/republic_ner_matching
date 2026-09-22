#!/usr/bin/env python3
"""Summarize Step 4 candidate ranking results.

Analyzes the ranking report and computes:
- top-1 candidate accuracy
- top-2 recall
- abstention/uncertain rate
- accuracy by stratum
- whether the LLM adds value when entity/formula scores are weak
- agreement between structured fields and the enriched summary
- gate status: does LLM improve over strongest deterministic baseline?

Usage:
    uv run python scripts/summarize_short_resolution_ranking.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_ranking_report(path: Path) -> tuple[dict, list[dict]]:
    """Load ranking report JSONL file."""
    meta = None
    records = []
    
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("record_type") == "ranking_meta":
                meta = rec
            else:
                records.append(rec)
    
    return meta or {}, records


def compute_gate_status(records: list[dict]) -> dict:
    """Compute gate status: does LLM improve over deterministic baseline?
    
    Gate: Continue only if the LLM improves held-out ranking over the strongest
    deterministic baseline, not merely over the positional-only baseline.
    """
    
    # Filter to test split only
    test_records = [r for r in records if r.get("split") == "test"]
    
    if not test_records:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "No test split records",
            "n_test": 0,
            "baseline_top1_acc": 0.0,
            "llm_top1_acc": 0.0,
            "baseline_top2_recall": 0.0,
            "llm_top2_recall": 0.0,
            "llm_abstention_rate": 0.0,
            "llm_improves_count": 0,
            "llm_improves_pct": 0.0,
        }
    
    metrics = {
        "n_test": len(test_records),
        "baseline_top1_acc": 0.0,
        "llm_top1_acc": 0.0,
        "baseline_top2_recall": 0.0,
        "llm_top2_recall": 0.0,
        "llm_abstention_rate": 0.0,
        "llm_improves_count": 0,
        "llm_improves_pct": 0.0,
    }
    
    baseline_top1_count = 0
    llm_top1_count = 0
    baseline_top2_count = 0
    llm_top2_count = 0
    abstention_count = 0
    llm_improves_count = 0
    
    for rec in test_records:
        if rec.get("baseline_top1_correct"):
            baseline_top1_count += 1
        if rec.get("llm_top1_correct"):
            llm_top1_count += 1
        if rec.get("top2_recall"):
            baseline_top2_count += 1
        if rec.get("llm_top2_recall"):
            llm_top2_count += 1
        if rec.get("abstention_rate"):
            abstention_count += 1
        
        # Strict improvement only: baseline wrong, LLM right.
        if rec.get("llm_top1_correct") and not rec.get("baseline_top1_correct"):
            llm_improves_count += 1

    n = len(test_records)
    metrics["baseline_top1_acc"] = baseline_top1_count / n
    metrics["llm_top1_acc"] = llm_top1_count / n
    metrics["baseline_top2_recall"] = baseline_top2_count / n
    metrics["llm_top2_recall"] = llm_top2_count / n
    metrics["llm_abstention_rate"] = abstention_count / n
    metrics["llm_improves_count"] = llm_improves_count
    metrics["llm_improves_pct"] = llm_improves_count / n

    # Gate: LLM must beat the strongest deterministic baseline on held-out top-1.
    # A saturated baseline (perfect top-1) leaves no headroom — that is still FAIL.
    gate_pass = llm_top1_count > baseline_top1_count

    if gate_pass:
        status = "GATE_PASS"
        message = (
            f"LLM top-1 accuracy: {metrics['llm_top1_acc']:.1%} "
            f"vs baseline {metrics['baseline_top1_acc']:.1%}"
        )
    elif baseline_top1_count == n and n > 0:
        status = "GATE_FAIL"
        message = (
            f"No headroom: baseline top-1 already {metrics['baseline_top1_acc']:.1%}; "
            f"LLM {metrics['llm_top1_acc']:.1%} "
            f"(abstention {metrics['llm_abstention_rate']:.1%}). "
            f"Cannot improve over strongest deterministic baseline."
        )
    else:
        status = "GATE_FAIL"
        message = (
            f"LLM did not improve over baseline. "
            f"LLM: {metrics['llm_top1_acc']:.1%}, "
            f"Baseline: {metrics['baseline_top1_acc']:.1%}"
        )

    metrics["status"] = status
    metrics["message"] = message

    return metrics


def compute_stratum_metrics(records: list[dict]) -> dict:
    """Compute metrics by position stratum."""
    test_records = [r for r in records if r.get("split") == "test"]
    
    strata = defaultdict(lambda: {
        "n": 0,
        "baseline_top1": 0,
        "llm_top1": 0,
        "llm_abstain": 0,
    })
    
    for rec in test_records:
        stratum = rec.get("position_stratum", "unknown")
        strata[stratum]["n"] += 1
        
        if rec.get("baseline_top1_correct"):
            strata[stratum]["baseline_top1"] += 1
        if rec.get("llm_top1_correct"):
            strata[stratum]["llm_top1"] += 1
        if rec.get("abstention_rate"):
            strata[stratum]["llm_abstain"] += 1
    
    # Compute percentages
    result = {}
    for stratum, counts in sorted(strata.items()):
        n = counts["n"]
        if n > 0:
            result[stratum] = {
                "n": n,
                "baseline_top1_acc": counts["baseline_top1"] / n,
                "llm_top1_acc": counts["llm_top1"] / n,
                "llm_abstention_rate": counts["llm_abstain"] / n,
            }
    
    return result


def compute_weak_anchor_metrics(records: list[dict]) -> dict:
    """Analyze performance on weak-anchor and merged cases."""
    test_records = [r for r in records if r.get("split") == "test"]
    
    weak_anchor = [r for r in test_records if r.get("anchor_class") in ("weak_or_none", "no_anchor")]
    merged = [r for r in test_records if r.get("day_segmentation") in ("under_segmented", "merged")]
    
    def compute_stats(recs):
        if not recs:
            return None
        baseline_top1 = sum(1 for r in recs if r.get("baseline_top1_correct"))
        llm_top1 = sum(1 for r in recs if r.get("llm_top1_correct"))
        return {
            "n": len(recs),
            "baseline_top1_acc": baseline_top1 / len(recs),
            "llm_top1_acc": llm_top1 / len(recs),
            "llm_improvement": (llm_top1 - baseline_top1) / len(recs),
        }
    
    return {
        "weak_anchor": compute_stats(weak_anchor),
        "merged_or_undersegmented": compute_stats(merged),
    }


def main() -> None:
    """Main entry point."""
    report_path = Path(PROJECT_ROOT) / "output" / "short_resolution_ranking_report.jsonl"
    
    if not report_path.exists():
        print(f"Error: {report_path} not found. Run build_short_resolution_ranking.py first.")
        return
    
    print("Loading ranking report...")
    meta, records = load_ranking_report(report_path)
    
    print(f"\nMetadata:")
    print(f"  Total records: {meta.get('n_enriched_resolutions', len(records))}")
    print(f"  Dry run: {meta.get('dry_run', False)}")
    print(f"  Sample mode: {meta.get('sample_mode', False)}")
    
    # Compute gate status
    print(f"\n=== GATE STATUS ===")
    gate_metrics = compute_gate_status(records)
    
    print(f"Status: {gate_metrics['status']}")
    print(f"Message: {gate_metrics['message']}")
    print(f"\nTest split metrics (n={gate_metrics['n_test']}):")
    print(f"  Baseline top-1 accuracy: {gate_metrics['baseline_top1_acc']:.1%}")
    print(f"  LLM top-1 accuracy:      {gate_metrics['llm_top1_acc']:.1%}")
    print(f"  Baseline top-2 recall:   {gate_metrics['baseline_top2_recall']:.1%}")
    print(f"  LLM top-2 recall:        {gate_metrics['llm_top2_recall']:.1%}")
    print(f"  LLM abstention rate:     {gate_metrics['llm_abstention_rate']:.1%}")
    print(f"  LLM improves baseline:   {gate_metrics['llm_improves_count']}/{gate_metrics['n_test']} ({gate_metrics['llm_improves_pct']:.1%})")
    
    # Stratum metrics
    print(f"\n=== METRICS BY STRATUM ===")
    stratum_metrics = compute_stratum_metrics(records)
    for stratum, metrics in stratum_metrics.items():
        print(f"\n{stratum} (n={metrics['n']}):")
        print(f"  Baseline top-1: {metrics['baseline_top1_acc']:.1%}")
        print(f"  LLM top-1:      {metrics['llm_top1_acc']:.1%}")
        print(f"  LLM abstain:    {metrics['llm_abstention_rate']:.1%}")
    
    # Weak anchor and merged metrics
    print(f"\n=== WEAK ANCHOR AND MERGED CASES ===")
    weak_metrics = compute_weak_anchor_metrics(records)
    
    if weak_metrics["weak_anchor"]:
        wm = weak_metrics["weak_anchor"]
        print(f"\nWeak or no anchor (n={wm['n']}):")
        print(f"  Baseline top-1: {wm['baseline_top1_acc']:.1%}")
        print(f"  LLM top-1:      {wm['llm_top1_acc']:.1%}")
        print(f"  LLM improvement: {wm['llm_improvement']:+.1%}")
    
    if weak_metrics["merged_or_undersegmented"]:
        mm = weak_metrics["merged_or_undersegmented"]
        print(f"\nMerged/under-segmented (n={mm['n']}):")
        print(f"  Baseline top-1: {mm['baseline_top1_acc']:.1%}")
        print(f"  LLM top-1:      {mm['llm_top1_acc']:.1%}")
        print(f"  LLM improvement: {mm['llm_improvement']:+.1%}")
    
    # Final recommendation
    print(f"\n=== GATE OUTCOME ===")
    if gate_metrics["status"] == "GATE_PASS":
        print("✓ GATE PASSED: LLM shows improvement over deterministic baseline")
        print("  Recommendation: Continue to Step 5 (test session-opening signal)")
    elif gate_metrics["status"] == "INSUFFICIENT_DATA":
        print("⚠ INSUFFICIENT_DATA: Cannot gate without test split records")
        print("  Recommendation: Run with full test split (not --sample-mode)")
    else:
        print("✗ GATE FAILED: LLM does not improve over deterministic baseline")
        print("  Recommendation: Do not promote; close side track or revise approach")


if __name__ == "__main__":
    main()

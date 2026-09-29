#!/usr/bin/env python3
"""
Phase 1b: Test semantic similarity weight on 50 gold days.
Sweeps over [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0] and measures lumped F1.
"""

import subprocess
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

# Weights to test
WEIGHTS = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]

def run_weight(weight: float) -> dict:
    """Run baseline and eval for a given semantic_weight."""
    print(f"\n{'='*60}")
    print(f"Testing semantic_weight = {weight}")
    print(f"{'='*60}")

    # Run baseline
    baseline_cmd = [
        "uv", "run", "python", "-m", "scripts.s4_paragraph_axis_baseline",
        f"--semantic_weight={weight}"
    ]
    result = subprocess.run(baseline_cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR in baseline: {result.stderr}")
        return None
    print(result.stdout.split('\n')[-2])  # Last meaningful line

    # Run evaluation
    eval_cmd = ["uv", "run", "python", "-m", "scripts.evaluate_s4_paragraph_axis"]
    result = subprocess.run(eval_cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR in evaluation: {result.stderr}")
        return None
    print(result.stdout.split('\n')[-2])

    # Extract metrics from evaluation output
    eval_file = OUTPUT_DIR / "s5_paragraph_axis_evaluation.jsonl"
    if not eval_file.exists():
        print(f"ERROR: {eval_file} not found")
        return None

    with open(eval_file) as f:
        lines = f.readlines()

    summary = json.loads(lines[-1])
    metrics = summary.get('metrics', {})
    boundary_metrics = metrics.get('boundary_metrics_by_tolerance', {})

    result_row = {
        'weight': weight,
        'coverage': summary.get('coverage', None),
        'predicted': summary.get('predicted_sessions', None),
        'eligible': summary.get('eligible_sessions', None),
    }

    # Extract F1 values (tol0=0, tol50=1, tol150=2)
    for tol_key, tol_label in [('0', 'tol0'), ('1', 'tol50'), ('2', 'tol150')]:
        if tol_key in boundary_metrics:
            result_row[f'lumped_f1_{tol_label}'] = boundary_metrics[tol_key]['micro_f1']

    return result_row

def main():
    results = []
    for weight in WEIGHTS:
        row = run_weight(weight)
        if row:
            results.append(row)
            # Print inline summary
            print(f"  Lumped F1@tol150: {row.get('lumped_f1_tol150', 'N/A'):.4f} | Coverage: {row.get('coverage', 'N/A'):.1%}")

    # Print summary table
    print(f"\n{'='*80}")
    print("SUMMARY: Phase 1b Semantic Weight Sweep")
    print(f"{'='*80}")
    print(f"{'Weight':>8} {'Coverage':>10} {'Lumped F1@tol0':>15} {'Lumped F1@tol50':>16} {'Lumped F1@tol150':>16}")
    print("-" * 80)
    for row in results:
        print(f"{row['weight']:>8.1f} {row.get('coverage', 0):>9.1%} "
              f"{row.get('lumped_f1_tol0', 0):>15.4f} {row.get('lumped_f1_tol50', 0):>16.4f} "
              f"{row.get('lumped_f1_tol150', 0):>16.4f}")

    # Find best weight
    best_row = max(results, key=lambda r: r.get('lumped_f1_tol150', 0))
    print(f"\nBest weight (by lumped F1@tol150): {best_row['weight']:.1f} → {best_row['lumped_f1_tol150']:.4f}")
    print(f"Baseline (weight=0.0): {results[0]['lumped_f1_tol150']:.4f}")

    if best_row['lumped_f1_tol150'] > results[0]['lumped_f1_tol150']:
        improvement = best_row['lumped_f1_tol150'] - results[0]['lumped_f1_tol150']
        print(f"✓ Improvement detected: +{improvement:.4f}")
        return 0
    else:
        print(f"✗ No improvement; semantic weight does not help at gold-day scale")
        return 1

if __name__ == '__main__':
    sys.exit(main())

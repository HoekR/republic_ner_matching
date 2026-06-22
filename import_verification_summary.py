#!/usr/bin/env python3
"""Merge manual verification verdicts into stratified ground-truth records.

Usage:
    uv run python import_verification_summary.py \\
        --verification ~/Downloads/ground_truth_verification_summary.json

    uv run python import_verification_summary.py \\
        --ground-truth output/ground_truth_stratified_matches.json \\
        --verification output/ground_truth_verification_summary.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"

VERDICT_LABELS = {
    0: "correct",
    1: "false_positive",
    "?": "uncertain",
}


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_verdict(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value in VERDICT_LABELS:
            return VERDICT_LABELS[value]  # type: ignore[index]
        if value.isdigit():
            return VERDICT_LABELS.get(int(value))
        return value
    if isinstance(value, int):
        return VERDICT_LABELS.get(value)
    return str(value)


def join_verification(
    ground_truth: list[dict[str, Any]],
    verification: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verdicts_raw = verification.get("verdicts", {})
    verdicts = {str(key): normalize_verdict(value) for key, value in verdicts_raw.items()}

    labeled: list[dict[str, Any]] = []
    for record in ground_truth:
        sample_id = str(record["sample_id"])
        verdict = verdicts.get(sample_id)
        labeled.append({**record, "verdict": verdict})

    gt_ids = {str(record["sample_id"]) for record in ground_truth}
    extra_verdict_ids = sorted(set(verdicts) - gt_ids, key=int)
    missing_verdict_ids = sorted(gt_ids - set(verdicts), key=int)

    joined_with_verdict = [record for record in labeled if record["verdict"] is not None]
    verdict_counts = Counter(record["verdict"] for record in joined_with_verdict)

    by_match_kind: dict[str, Counter[str]] = defaultdict(Counter)
    for record in joined_with_verdict:
        by_match_kind[record["verdict"]][record.get("match_kind", "unknown")] += 1

    score_by_verdict: dict[str, list[float]] = defaultdict(list)
    for record in joined_with_verdict:
        score_by_verdict[record["verdict"]].append(float(record.get("confidence_score", 0.0)))

    summary = {
        "ground_truth_samples": len(ground_truth),
        "verdicts_in_export": len(verdicts),
        "joined_samples": len(joined_with_verdict),
        "unlabeled_sample_ids": missing_verdict_ids,
        "orphan_verdict_ids": extra_verdict_ids,
        "verdict_counts": dict(verdict_counts),
        "verdict_by_match_kind": {key: dict(counter) for key, counter in by_match_kind.items()},
        "mean_confidence_score": {
            verdict: (sum(scores) / len(scores) if scores else None)
            for verdict, scores in score_by_verdict.items()
        },
        "export_metadata": {
            "total": verification.get("total"),
            "verified": verification.get("verified"),
            "correct": verification.get("correct"),
            "false_positives": verification.get("false_positives"),
            "uncertain": verification.get("uncertain"),
            "accuracy": verification.get("accuracy"),
        },
    }
    if joined_with_verdict:
        correct = verdict_counts.get("correct", 0)
        summary["precision_on_labeled"] = round(correct / len(joined_with_verdict), 4)

    return labeled, summary


def export_outputs(
    labeled: list[dict[str, Any]],
    summary: dict[str, Any],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    curated = [record for record in labeled if record.get("verdict") == "correct"]
    rejected = [record for record in labeled if record.get("verdict") == "false_positive"]
    uncertain = [record for record in labeled if record.get("verdict") == "uncertain"]

    labeled_path = output_dir / "ground_truth_labeled.json"
    curated_path = output_dir / "ground_truth_curated.json"
    rejected_path = output_dir / "ground_truth_rejected.json"
    uncertain_path = output_dir / "ground_truth_uncertain.json"
    summary_path = output_dir / "ground_truth_verification_analysis.json"
    parquet_path = output_dir / "ground_truth_labeled.parquet"

    labeled_path.write_text(json.dumps(labeled, indent=2, ensure_ascii=False), encoding="utf-8")
    curated_path.write_text(json.dumps(curated, indent=2, ensure_ascii=False), encoding="utf-8")
    rejected_path.write_text(json.dumps(rejected, indent=2, ensure_ascii=False), encoding="utf-8")
    uncertain_path.write_text(json.dumps(uncertain, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    pd.DataFrame(
        [
            {
                "sample_id": item["sample_id"],
                "verdict": item.get("verdict"),
                "enriched_id": item.get("enriched_id"),
                "flat_id": item.get("flat_id"),
                "enriched_date": item.get("enriched_date"),
                "flat_date": item.get("flat_date"),
                "match_kind": item.get("match_kind"),
                "confidence_score": item.get("confidence_score"),
                "is_summary_anchor": item.get("is_summary_anchor"),
                "place_matches": item["entities"]["places"]["matched_count"],
                "org_matches": item["entities"]["organizations"]["matched_count"],
            }
            for item in labeled
            if item.get("verdict") is not None
        ]
    ).to_parquet(parquet_path, index=False)

    print(f"✓ Labeled records: {labeled_path} ({len(labeled)} rows, {summary['joined_samples']} with verdicts)")
    print(f"✓ Curated (correct): {curated_path} ({len(curated)} rows)")
    print(f"✓ Rejected: {rejected_path} ({len(rejected)} rows)")
    print(f"✓ Uncertain: {uncertain_path} ({len(uncertain)} rows)")
    print(f"✓ Analysis: {summary_path}")
    print(f"✓ Parquet: {parquet_path}")
    print(f"  Verdict counts: {summary['verdict_counts']}")
    if summary.get("precision_on_labeled") is not None:
        print(f"  Precision on labeled: {summary['precision_on_labeled']:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import browser verification export into curated ground truth.")
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=OUTPUT_DIR / "ground_truth_stratified_matches.json",
        help="Stratified ground-truth JSON used during verification.",
    )
    parser.add_argument(
        "--verification",
        type=Path,
        required=True,
        help="Exported ground_truth_verification_summary.json from the browser UI.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for merged outputs.",
    )
    args = parser.parse_args()

    if not args.ground_truth.exists():
        raise FileNotFoundError(f"Ground truth not found: {args.ground_truth}")
    if not args.verification.exists():
        raise FileNotFoundError(f"Verification export not found: {args.verification}")

    ground_truth = load_json(args.ground_truth)
    verification = load_json(args.verification)
    if not isinstance(ground_truth, list):
        raise ValueError("Ground truth JSON must be a list of records.")

    labeled, summary = join_verification(ground_truth, verification)
    export_outputs(labeled, summary, args.output_dir)


if __name__ == "__main__":
    main()

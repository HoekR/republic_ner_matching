#!/usr/bin/env python3
"""Evaluate S4 paragraph-axis predictions against manually marked boundaries."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from data_io import load, save_semi_structured
from evaluation_harness import evaluate_segmentation_session, summarize_segmentation_evaluations


GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
REVIEW_DATASET = "boundary_gold_exception_review"
PREDICTIONS_DATASET = "s4_paragraph_axis_predictions"
OUTPUT_DATASET = "s5_paragraph_axis_evaluation"


def transition_indices(day: dict[str, Any]) -> list[int]:
    return [
        int(boundary["paragraph_stream_index"])
        for boundary in day.get("boundaries", [])
        if boundary.get("kind") in {"cut", "start"} and boundary.get("paragraph_stream_index") is not None
    ]


def review_codes() -> dict[str, str]:
    review = load(REVIEW_DATASET)
    return {
        str(row.date): str(row.review_code).strip()
        for row in review[["date", "review_code"]].dropna().itertuples(index=False)
        if str(row.review_code).strip()
    }


def main() -> None:
    gold = load(GOLD_DATASET)
    predictions = {item["date"]: item for item in load(PREDICTIONS_DATASET)}
    axis_count = Counter(record["date"] for record in load(AXIS_DATASET))
    codes = review_codes()
    eligible = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S"]
    evaluated = []
    abstentions: Counter[str] = Counter()
    for day in eligible:
        prediction = predictions[str(day["date"])]
        if prediction["status"] != "predicted":
            abstentions[str(prediction["reason"])] += 1
            continue
        evaluated.append(
            evaluate_segmentation_session(
                session_id=str(day["date"]),
                date=str(day["date"]),
                k_e=int(day["k_e"]),
                ref_boundaries=transition_indices(day),
                hyp_boundaries=[boundary["paragraph_stream_index"] for boundary in prediction["boundaries"]],
                total_length=axis_count[str(day["date"])],
                tolerances=(0, 1, 2),
            )
        )
    report = {
        "eligible_sessions": len(eligible),
        "predicted_sessions": len(evaluated),
        "coverage": len(evaluated) / len(eligible) if eligible else 0.0,
        "abstentions_by_reason": dict(abstentions),
        "metrics": summarize_segmentation_evaluations(evaluated, tolerances=(0, 1, 2)),
    }
    output = save_semi_structured([report], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote S5 evaluation to {output}; coverage={len(evaluated)} / {len(eligible)}")


if __name__ == "__main__":
    main()
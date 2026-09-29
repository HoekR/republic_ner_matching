#!/usr/bin/env python3
"""Evaluate S6c wiring: does TF-IDF similarity as position_scores help weak_separation days?

Runs the same S6c gap-filling DP on gold days with and without similarity as a position_scores
bonus. Measures paragraph-level boundary F1 to see if semantic similarity improves placement.

Design:
- Compute TF-IDF similarity matrix for each day
- Convert max-per-paragraph similarity to position_scores
- Run segment_day with and without similarity bonus
- Measure boundary F1 against gold reference

Usage:
    uv run python -m scripts.s6c_similarity_position_scores_eval
    uv run python -m scripts.s6c_similarity_position_scores_eval --scale 0.5
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from alignment_embeddings import AlignmentEmbedder
from build_alignment_new import calculate_idf_weights
from data_io import load, resolve, save_semi_structured
from evaluation_harness import evaluate_segmentation_session, summarize_segmentation_evaluations
from scripts.evaluate_s4_paragraph_axis import review_codes, transition_indices
from scripts.s4_corpus_paragraph_predictions import (
    AXIS_DATASET,
    OVERLAP_DATASETS,
    axis_for_date,
    predict,
    resolved_sessions,
    session_of,
)
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, overlap_enriched_id
from scripts.s6c_gap_segmentation import similarity_position_scores

GOLD_DATASET = "boundary_gold_sample"
OUTPUT_DATASET = "s6c_similarity_position_scores_eval"
CONDITIONS = ("baseline", "similarity")
TOLERANCES = (0, 1, 2)
EMBEDDER_BACKEND = "tfidf"


def extract_axis_texts(axis_records: list[dict[str, Any]]) -> list[str]:
    """Extract paragraph texts from axis records."""
    texts = []
    for record in axis_records:
        text = record.get("text", "") or record.get("para", "") or record.get("content", "")
        texts.append(str(text).strip() if text else " ")
    return texts


def load_enriched_texts_by_date() -> dict[str, list[str]]:
    """Load enriched resolution full texts, ordered by resolution_index per date."""
    by_date: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for item in load("enriched_resolutions_1626_1630"):
        date = str(item.get("date", ""))[:10]
        if "1626-01-01" <= date <= "1630-12-31":
            text = item.get("text", "")
            if not text or not str(text).strip():
                text = item.get("summary", "")
            if not text or not str(text).strip():
                text = item.get("title", "") or ""
            idx = item.get("resolution_index", 0)
            by_date[date].append((idx, str(text).strip() if text else " "))

    result = {}
    for date, indexed_texts in by_date.items():
        indexed_texts.sort(key=lambda x: x[0])
        result[date] = [text for _, text in indexed_texts]
    return result


def compute_similarity_matrix(
    enriched_texts: list[str],
    axis_texts: list[str],
    embedder: AlignmentEmbedder,
) -> np.ndarray | None:
    """Compute semantic similarity matrix; return None on error."""
    try:
        if not enriched_texts or not axis_texts:
            return None
        matrix = embedder.compute_similarity_matrix(enriched_texts, axis_texts)
        return matrix if matrix is not None else None
    except Exception as e:
        print(f"Warning: failed to compute similarity matrix: {e}", file=sys.stderr)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate S6c TF-IDF similarity position_scores on gold days."
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale factor for similarity bonus in position_scores (default: 1.0).",
    )
    args = parser.parse_args()

    gold = load(GOLD_DATASET)
    codes = review_codes()
    eligible = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S"]

    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)
        axis_by_session[session_of(record["flat_id"])].append(record)
    session_by_date = resolved_sessions()

    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [
        overlap.rename(columns={"naam": "name"}) if "name" not in overlap and "naam" in overlap else overlap
        for overlap in overlaps
    ]
    combined = pd.concat(overlaps, ignore_index=True)
    full_axis = [record for records in axis_by_date.values() for record in records]
    lookup = build_axis_overlap(full_axis, combined)
    idf_weights = calculate_idf_weights(combined)

    embedder = AlignmentEmbedder(backend=EMBEDDER_BACKEND)
    enriched_texts_by_date = load_enriched_texts_by_date()

    evaluated: dict[str, list[Any]] = {condition: [] for condition in CONDITIONS}
    no_axis = 0
    per_day: list[dict[str, Any]] = []

    for day in eligible:
        date = str(day["date"])
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis:
            no_axis += 1
            continue

        enriched_ids = [overlap_enriched_id(enriched_id, date) for enriched_id in day["enriched_ids"]]
        ref = transition_indices(day)

        # Compute similarity matrix
        enriched_texts = enriched_texts_by_date.get(date, [])
        axis_texts = extract_axis_texts(axis)
        similarity_matrix = None
        if enriched_texts and axis_texts:
            similarity_matrix = compute_similarity_matrix(enriched_texts, axis_texts, embedder)

        # Build position_scores from similarity if available
        sim_scores = {}
        if similarity_matrix is not None:
            sim_scores = similarity_position_scores(similarity_matrix, scale=args.scale)

        record: dict[str, Any] = {
            "date": date,
            "k_e": int(day["k_e"]),
            "paragraph_count": len(axis),
            "similarity_paragraphs_with_evidence": len(sim_scores),
        }

        for condition, scores in (("baseline", None), ("similarity", sim_scores)):
            prediction = predict(
                date,
                enriched_ids,
                axis,
                lookup,
                idf_weights,
                position_scores=scores,
                similarity_matrix=None,  # Don't wire similarity into align_session, only into position_scores
                semantic_weight=0.0,
            )
            hyp = [boundary["paragraph_stream_index"] for boundary in prediction["boundaries"]]
            record[condition] = {"hyp_count": len(hyp)}
            evaluated[condition].append(
                evaluate_segmentation_session(
                    session_id=date,
                    date=date,
                    k_e=int(day["k_e"]),
                    ref_boundaries=ref,
                    hyp_boundaries=hyp,
                    total_length=len(axis),
                    tolerances=TOLERANCES,
                )
            )
        per_day.append(record)

    scoreable = len(per_day)
    report = {
        "unit": "paragraph_stream",
        "tolerances": list(TOLERANCES),
        "scale": args.scale,
        "eligible_sessions": len(eligible),
        "scoreable_sessions": scoreable,
        "no_axis_sessions": no_axis,
        "conditions": {
            condition: {
                "predicted_sessions": len(evaluated[condition]),
                "metrics": summarize_segmentation_evaluations(evaluated[condition], tolerances=TOLERANCES),
            }
            for condition in CONDITIONS
        },
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote S6c TF-IDF similarity position_scores eval to {output}")
    print(f"  scale={args.scale} eligible={len(eligible)} scoreable={scoreable} no_axis={no_axis}")
    for condition in CONDITIONS:
        metrics = report["conditions"][condition]["metrics"]["boundary_metrics_by_tolerance"]
        scores = " ".join(f"tol{tol}={metrics[str(tol)]['micro_f1']:.3f}" for tol in TOLERANCES)
        print(f"  {condition:>9}: {scores}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run the first S4 entity-NW segmentation baseline on boundary-gold days.

The canonical flat table has no complete paragraph-ID axis, so this lower-bound
baseline can place a cut only at the start of an existing flat resolution. It
abstains instead of inventing boundaries for merged or absent HTR content.

Usage:
    uv run python -m scripts.s4_resolution_baseline
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from analyze_sequence_entity_overlap import build_resolution_overlap_lookup
from build_alignment_new import (
    align_session,
    build_paragraph_to_resolution_map,
    calculate_idf_weights,
    enriched_volgnr,
    load_data,
    paragraph_mapping_annotation_files,
    sort_key_res_id,
)
from data_io import load, save_semi_structured


GOLD_DATASET = "boundary_gold_sample"
REVIEW_DATASET = "boundary_gold_exception_review"
OUTPUT_DATASET = "s4_resolution_baseline_predictions"
REVIEW_ABSTENTION_REASONS = {"C": "cross_day_shift", "M": "missing_htr", "N": "nihil_actum", "?": "uncertain"}


def project_resolution_boundaries(
    enriched_count: int, alignments: Sequence[tuple[int | None, int | None]]
) -> list[int] | None:
    """Project enriched transitions to strictly increasing flat-resolution starts."""
    matched = {enriched_index: flat_index for enriched_index, flat_index in alignments if enriched_index is not None and flat_index is not None}
    if len(matched) != enriched_count:
        return None
    projected_indices = [matched[index] for index in range(enriched_count)]
    if not all(left < right for left, right in zip(projected_indices, projected_indices[1:])):
        return None
    return projected_indices[1:]


def review_codes() -> dict[str, str]:
    review = load(REVIEW_DATASET)
    if "review_code" not in review:
        return {}
    return {
        str(row.date): str(row.review_code).strip()
        for row in review[["date", "review_code"]].dropna().itertuples(index=False)
        if str(row.review_code).strip()
    }


def abstention(day: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "date": day["date"],
        "k_e": day["k_e"],
        "k_f": day["k_f"],
        "status": "abstained",
        "reason": reason,
        "unit": "flat_resolution_start",
        "boundaries": [],
    }


def predict_day(
    day: dict[str, Any],
    enriched_by_date: dict[str, list[dict[str, Any]]],
    overlap_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    review_code: str,
) -> dict[str, Any]:
    if review_code in REVIEW_ABSTENTION_REASONS:
        return abstention(day, REVIEW_ABSTENTION_REASONS[review_code])

    enriched = enriched_by_date.get(str(day["date"]), [])
    enriched_ids = [enriched_volgnr(item) for item in enriched]
    flat_ids = sorted(day["flat_ids"], key=sort_key_res_id)
    if len(enriched_ids) != day["k_e"] or any(identifier is None for identifier in enriched_ids):
        return abstention(day, "incomplete_enriched_input")
    if len(flat_ids) < day["k_e"]:
        return abstention(day, "insufficient_resolution_granularity")

    alignments = align_session(enriched_ids, flat_ids, overlap_lookup, idf_weights)
    boundary_indices = project_resolution_boundaries(day["k_e"], alignments)
    if boundary_indices is None:
        return abstention(day, "insufficient_entity_anchors")

    return {
        "date": day["date"],
        "k_e": day["k_e"],
        "k_f": day["k_f"],
        "status": "predicted",
        "reason": None,
        "unit": "flat_resolution_start",
        "boundaries": [
            {"flat_id": flat_ids[index], "kind": "cut", "source": "entity_nw"}
            for index in boundary_indices
        ],
    }


def main() -> None:
    gold = load(GOLD_DATASET)
    codes = review_codes()
    enriched_all, _, places_df, orgs_df, *_ = load_data()
    enriched_by_date: dict[str, list[dict[str, Any]]] = {}
    for item in enriched_all:
        enriched_by_date.setdefault(str(item.get("date", ""))[:10], []).append(item)
    for items in enriched_by_date.values():
        items.sort(key=lambda item: item.get("resolution_index", 0))

    paragraph_ids = set(places_df["paragraph_id"].dropna().astype(str)) | set(orgs_df["paragraph_id"].dropna().astype(str))
    paragraph_to_resolution = build_paragraph_to_resolution_map(paragraph_mapping_annotation_files(), paragraph_ids)
    overlap_lookup = build_resolution_overlap_lookup(places_df, orgs_df, paragraph_to_resolution)
    idf_weights = calculate_idf_weights(pd.concat([places_df, orgs_df], ignore_index=True))

    predictions = [
        predict_day(day, enriched_by_date, overlap_lookup, idf_weights, codes.get(str(day["date"]), "S"))
        for day in gold["days"]
    ]
    output = save_semi_structured(predictions, logical_name=OUTPUT_DATASET, script=__file__)
    predicted = sum(prediction["status"] == "predicted" for prediction in predictions)
    print(f"Wrote {len(predictions)} predictions to {output}; predicted={predicted}, abstained={len(predictions) - predicted}")


if __name__ == "__main__":
    main()
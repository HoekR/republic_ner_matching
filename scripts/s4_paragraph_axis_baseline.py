#!/usr/bin/env python3
"""Project entity-sequence Needleman-Wunsch matches onto the paragraph axis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
import re
from typing import Any

import pandas as pd
from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, resolve, save_semi_structured


GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
REVIEW_DATASET = "boundary_gold_exception_review"
OUTPUT_DATASET = "s4_paragraph_axis_predictions"
OVERLAP_DATASETS = ("place_overlap_1626_1630", "org_overlap_1626_1630", "per_overlap_1626_1630")
PHRASE_DATASET = "s4_opening_phrase_candidates"
REVIEW_ABSTENTION_REASONS = {"C": "cross_day_shift", "M": "missing_htr", "N": "nihil_actum", "?": "uncertain"}


def overlap_enriched_id(enriched_id: str, date: str) -> str:
    """Convert gold's file#index fallback key to the overlap workbook convention."""
    match = re.search(r"#(\d+)$", enriched_id)
    return f"{date}_{match.group(1)}" if match else enriched_id


def project_boundaries(enriched_count: int, alignments: Sequence[tuple[int | None, int | None]]) -> list[int] | None:
    matched = {enriched_index: axis_index for enriched_index, axis_index in alignments if enriched_index is not None and axis_index is not None}
    if len(matched) != enriched_count:
        return None
    positions = [matched[index] for index in range(enriched_count)]
    return positions[1:] if all(left < right for left, right in zip(positions, positions[1:])) else None


def interpolate_positions(
    enriched_count: int, axis_count: int, alignments: Sequence[tuple[int | None, int | None]]
) -> list[int] | None:
    """Fill unanchored enriched positions between strict NW entity anchors."""
    anchors = [(enriched_index, axis_index) for enriched_index, axis_index in alignments if enriched_index is not None and axis_index is not None]
    if not anchors or axis_count < enriched_count:
        return None
    if not all(left[0] < right[0] and left[1] < right[1] for left, right in zip(anchors, anchors[1:])):
        return None

    positions: list[int | None] = [None] * enriched_count
    for enriched_index, axis_index in anchors:
        positions[enriched_index] = axis_index
    endpoints = [(-1, -1), *anchors, (enriched_count, axis_count)]
    for (left_enriched, left_axis), (right_enriched, right_axis) in zip(endpoints, endpoints[1:]):
        enriched_gap = right_enriched - left_enriched - 1
        axis_gap = right_axis - left_axis - 1
        if axis_gap < enriched_gap:
            return None
        for offset in range(1, enriched_gap + 1):
            positions[left_enriched + offset] = left_axis + (offset * (right_axis - left_axis)) // (enriched_gap + 1)
    if any(position is None for position in positions):
        return None
    completed = [int(position) for position in positions]
    return completed[1:] if all(left < right for left, right in zip(completed, completed[1:])) else None


def phrase_hits(axis: list[dict[str, Any]], phrases: list[str]) -> dict[int, tuple[str, int, float]]:
    """Return the strongest recurring-opening hit in each axis paragraph."""
    searcher = FuzzyPhraseSearcher(
        phrases,
        config={"char_match_threshold": 0.85, "ngram_threshold": 0.85, "levenshtein_threshold": 0.85},
    )
    hits: dict[int, tuple[str, int, float]] = {}
    for index, record in enumerate(axis):
        matches = searcher.find_matches({"id": record["axis_id"], "text": record["text"]})
        if matches:
            best = max(matches, key=lambda match: (match.levenshtein_similarity, len(match.phrase.phrase_string)))
            hits[index] = (best.phrase.phrase_string, best.offset, best.levenshtein_similarity)
    return hits


def snap_to_phrase(position: int, hits: dict[int, tuple[str, int, float]], max_distance: int = 2) -> tuple[int, tuple[str, int, float] | None]:
    """Snap to the nearest recurring opening, but only within a local neighborhood."""
    nearby = [(index, hit) for index, hit in hits.items() if abs(index - position) <= max_distance]
    if not nearby:
        return position, None
    return min(nearby, key=lambda item: (abs(item[0] - position), -item[1][2], -len(item[1][0])))


def read_review_codes() -> dict[str, str]:
    review = load(REVIEW_DATASET)
    return {
        str(row.date): str(row.review_code).strip()
        for row in review[["date", "review_code"]].dropna().itertuples(index=False)
        if str(row.review_code).strip()
    }


def build_axis_overlap(axis: list[dict[str, Any]], overlap: pd.DataFrame) -> dict[tuple[str, str], set[str]]:
    by_source_paragraph: dict[str, list[str]] = defaultdict(list)
    for record in axis:
        for paragraph_id in record["entity_source_paragraph_ids"]:
            by_source_paragraph[paragraph_id].append(record["axis_id"])

    lookup: dict[tuple[str, str], set[str]] = defaultdict(set)
    relevant = overlap.loc[overlap["paragraph_id"].astype(str).isin(by_source_paragraph), ["volgnr", "paragraph_id", "name"]]
    for row in relevant.dropna().itertuples(index=False):
        for axis_id in by_source_paragraph[str(row.paragraph_id)]:
            lookup[(str(row.volgnr), axis_id)].add(str(row.name).strip())
    return dict(lookup)


def predict_day(day: dict[str, Any], axis: list[dict[str, Any]], lookup: dict[tuple[str, str], set[str]], idf_weights: dict[str, float], review_code: str, phrases: list[str]) -> dict[str, Any]:
    base = {"date": day["date"], "k_e": day["k_e"], "paragraph_count": len(axis), "unit": "paragraph_stream"}
    if review_code in REVIEW_ABSTENTION_REASONS:
        return {**base, "status": "abstained", "reason": REVIEW_ABSTENTION_REASONS[review_code], "boundaries": []}

    enriched_ids = [overlap_enriched_id(enriched_id, str(day["date"])) for enriched_id in day["enriched_ids"]]
    axis_ids = [record["axis_id"] for record in axis]
    alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
    positions = interpolate_positions(day["k_e"], len(axis_ids), alignments)
    if positions is None:
        return {**base, "status": "abstained", "reason": "insufficient_entity_anchors", "boundaries": []}
    snapped = [snap_to_phrase(position, phrase_hits(axis, phrases)) for position in positions]
    snapped_positions = [position for position, _ in snapped]
    if not all(left < right for left, right in zip(snapped_positions, snapped_positions[1:])):
        snapped = [(position, None) for position in positions]
    return {
        **base,
        "status": "predicted",
        "reason": None,
        "boundaries": [
            {
                "paragraph_stream_index": position,
                "char_offset": hit[1] if hit else 0,
                "kind": "cut",
                "source": "entity_nw_interpolation_phrase_snap" if hit else "entity_nw_interpolation",
                "opening_phrase": hit[0] if hit else None,
                "opening_similarity": hit[2] if hit else None,
            }
            for position, hit in snapped
        ],
    }


def main() -> None:
    gold = load(GOLD_DATASET)
    axis = load(AXIS_DATASET)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        by_date[str(record["date"])].append(record)
    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [
        overlap.rename(columns={"naam": "name"}) if "name" not in overlap and "naam" in overlap else overlap
        for overlap in overlaps
    ]
    combined = pd.concat(overlaps, ignore_index=True)
    lookup = build_axis_overlap(axis, combined)
    idf_weights = calculate_idf_weights(combined)
    phrase_candidates = load(PHRASE_DATASET)[0]["candidates"]
    phrases = [item["phrase"] for item in phrase_candidates if item["word_count"] >= 3]
    review_codes = read_review_codes()
    predictions = [
        predict_day(day, by_date[str(day["date"])], lookup, idf_weights, review_codes.get(str(day["date"]), "S"), phrases)
        for day in gold["days"]
    ]
    output = save_semi_structured(predictions, logical_name=OUTPUT_DATASET, script=__file__)
    predicted = sum(item["status"] == "predicted" for item in predictions)
    print(f"Wrote {len(predictions)} predictions to {output}; predicted={predicted}, abstained={len(predictions) - predicted}")


if __name__ == "__main__":
    main()
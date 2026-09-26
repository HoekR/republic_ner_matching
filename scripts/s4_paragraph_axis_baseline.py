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
from scripts.s6c_gap_segmentation import segment_day


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
    if enriched_count <= 1:
        return []
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


PHRASE_SEARCH_CONFIG = {"char_match_threshold": 0.85, "ngram_threshold": 0.85, "levenshtein_threshold": 0.85}


def build_phrase_searcher(phrases: list[str]) -> FuzzyPhraseSearcher:
    return FuzzyPhraseSearcher(phrases, config=PHRASE_SEARCH_CONFIG)


def phrase_hits(axis: list[dict[str, Any]], searcher: FuzzyPhraseSearcher) -> dict[int, tuple[str, int, float]]:
    """Return the strongest recurring-opening hit in each axis paragraph.

    Takes a pre-built searcher rather than a phrase list: at gold-day scale (21 days)
    rebuilding one per call was invisible, but the same call site is reused corpus-wide
    (~1,240 days) by s4_corpus_paragraph_predictions.py, where rebuilding a searcher from
    ~3,800 phrases per day would dominate runtime -- build once, reuse, per
    s6b_anchor_harvest.py's existing pattern.
    """
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


def snap_boundaries(positions: Sequence[int], hits: dict[int, tuple[str, int, float]]) -> list[tuple[int, tuple[str, int, float] | None]]:
    """Snap each position independently, keeping only snaps that preserve strict order.

    A per-day all-or-nothing revert discards every snap in a day the moment two
    positions land on the same paragraph; this accepts snaps one boundary at a
    time so a single collision only falls back for the colliding boundary.
    """
    snapped: list[tuple[int, tuple[str, int, float] | None]] = []
    prev_accepted = -1
    for index, position in enumerate(positions):
        upper_bound = positions[index + 1] if index + 1 < len(positions) else None
        candidate_position, hit = snap_to_phrase(position, hits)
        if hit is not None and prev_accepted < candidate_position and (upper_bound is None or candidate_position < upper_bound):
            snapped.append((candidate_position, hit))
            prev_accepted = candidate_position
        else:
            snapped.append((position, None))
            prev_accepted = position
    return snapped


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


def predict_day(day: dict[str, Any], axis: list[dict[str, Any]], lookup: dict[tuple[str, str], set[str]], idf_weights: dict[str, float], review_code: str, searcher: FuzzyPhraseSearcher) -> dict[str, Any]:
    base = {"date": day["date"], "k_e": day["k_e"], "paragraph_count": len(axis), "unit": "paragraph_stream"}
    if review_code in REVIEW_ABSTENTION_REASONS:
        return {**base, "status": "abstained", "reason": REVIEW_ABSTENTION_REASONS[review_code], "boundaries": []}

    if not axis:
        return {**base, "status": "abstained", "reason": "missing_htr", "boundaries": []}

    enriched_ids = [overlap_enriched_id(enriched_id, str(day["date"])) for enriched_id in day["enriched_ids"]]
    axis_ids = [record["axis_id"] for record in axis]
    alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
    hits = phrase_hits(axis, searcher)
    # S6c (docs/steps/STEP_S6_anchor_chain_alignment.md, rescoped 2026-09-21): a
    # count-constrained segmentation DP replaces interpolate_positions here so a single
    # folded anchor or a too-short axis degrades to repeated paragraph assignments
    # instead of discarding the whole day's prediction; group-C phrase hits feed it as
    # soft in-gap evidence. interpolate_positions itself is untouched -- it stays the
    # deliberately unmodified placement model s6_oracle_anchor_diagnostic.py measures.
    positions = segment_day(day["k_e"], len(axis_ids), alignments, {index: hit[2] for index, hit in hits.items()})
    snapped = snap_boundaries(positions, hits)
    return {
        **base,
        "status": "predicted",
        "reason": None,
        "boundaries": [
            {
                "paragraph_stream_index": position,
                "char_offset": hit[1] if hit else 0,
                "kind": "cut",
                "source": "s6c_gap_segmentation_phrase_snap" if hit else "s6c_gap_segmentation",
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
    searcher = build_phrase_searcher(phrases)
    review_codes = read_review_codes()
    predictions = [
        predict_day(day, by_date[str(day["date"])], lookup, idf_weights, review_codes.get(str(day["date"]), "S"), searcher)
        for day in gold["days"]
    ]
    output = save_semi_structured(predictions, logical_name=OUTPUT_DATASET, script=__file__)
    predicted = sum(item["status"] == "predicted" for item in predictions)
    print(f"Wrote {len(predictions)} predictions to {output}; predicted={predicted}, abstained={len(predictions) - predicted}")


if __name__ == "__main__":
    main()
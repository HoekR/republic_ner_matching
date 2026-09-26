#!/usr/bin/env python3
"""Does per-paragraph .find()-relocated Group-B evidence help where the blanket version didn't?

docs/DECISIONS.md 2026-09-23 ("Correction: Group-B and Group-C position_scores regressions are
not the same magnitude or mechanism") traced Group-B's -21 TP regression (vs. Group-C's milder
-2) to a concrete cause: `entity_surface_matches_1626_1630` is keyed by flat RESOLUTION id, so
every axis paragraph belonging to a multi-paragraph flat resolution gets an IDENTICAL bonus
(verified on 1626-01-08: a 4-paragraph resolution shares one score across all 4). The bonus fires
as near-uniform noise across the whole resolution span instead of marking where the matched name
actually sits.

This script relocates each match to the specific paragraph(s) whose own `text` contains it,
re-using the exact-then-fuzzy methodology `build_entity_surface_matches.py` already validated
(`FUZZY_THRESHOLD = 85`, same rapidfuzz.fuzz.partial_ratio) -- but applied per axis paragraph
instead of per whole flat-resolution text, which is the granularity fix itself. A flat
resolution's match with no paragraph whose text contains it (fuzzy variants of the resolution's
overall text that don't localize to any single paragraph) contributes no bonus anywhere, rather
than the blanket bonus every paragraph got before.

Same cheap-before-corpus-wide methodology as every prior S6 position_scores experiment this
cycle: scored through `s4_corpus_paragraph_predictions.py`'s own `predict()` codepath, restricted
to the 19/21 scoreable gold days, at paragraph granularity (docs/DECISIONS.md 2026-09-21 "S6c
target metric rescoped" -- not character-offset tolerance).

Usage:
    uv run python -m scripts.s6_group_b_relocated_position_scores_eval
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

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
from scripts.s6_group_b_position_scores_eval import group_b_position_scores

GOLD_DATASET = "boundary_gold_sample"
SURFACE_MATCH_DATASET = "entity_surface_matches_1626_1630"
OUTPUT_DATASET = "s6_group_b_relocated_position_scores_eval"
CONDITIONS = ("baseline", "group_b", "group_b_relocated")
TOLERANCES = (0, 1, 2)  # paragraph units, not characters -- see module docstring
FUZZY_THRESHOLD = 85  # matches build_entity_surface_matches.py's own validated threshold


def group_b_relocated_position_scores(
    axis: list[dict[str, Any]], matches_by_flat_id: dict[str, list[dict[str, Any]]]
) -> dict[int, float]:
    """Per-axis-paragraph bonus from surface matches confirmed against THAT paragraph's own text.

    A match only contributes where its `canonical_name` is actually findable (exact substring,
    falling back to fuzz.partial_ratio at the same threshold `build_entity_surface_matches.py`
    validated) in the specific paragraph's text -- not blanket-applied across every paragraph of
    the source flat resolution the way `group_b_position_scores` does.
    """
    scores: dict[int, float] = {}
    for index, record in enumerate(axis):
        matches = matches_by_flat_id.get(str(record.get("flat_id", "")))
        if not matches:
            continue
        text_lower = str(record.get("text", "")).lower()
        if not text_lower:
            continue
        best = 0.0
        for match in matches:
            name_lower = str(match["canonical_name"]).strip().lower()
            if not name_lower:
                continue
            if name_lower in text_lower:
                best = max(best, 100.0)
            else:
                score = fuzz.partial_ratio(name_lower, text_lower)
                if score >= FUZZY_THRESHOLD:
                    best = max(best, score)
        if best:
            scores[index] = min(1.0, best / 100.0)
    return scores


def main() -> None:
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

    surface = load(SURFACE_MATCH_DATASET)
    matches_by_flat_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in surface[["resolution_id", "entity_type", "canonical_name", "match_method", "match_score"]].itertuples(index=False):
        matches_by_flat_id[str(row.resolution_id)].append(
            {"entity_type": row.entity_type, "canonical_name": row.canonical_name, "match_method": row.match_method, "match_score": row.match_score}
        )

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
        bonus = group_b_position_scores(axis, matches_by_flat_id)
        relocated_bonus = group_b_relocated_position_scores(axis, matches_by_flat_id)

        record: dict[str, Any] = {
            "date": date,
            "k_e": int(day["k_e"]),
            "paragraph_count": len(axis),
            "group_b_paragraphs_with_evidence": len(bonus),
            "group_b_relocated_paragraphs_with_evidence": len(relocated_bonus),
        }
        for condition, scores in (("baseline", None), ("group_b", bonus), ("group_b_relocated", relocated_bonus)):
            prediction = predict(date, enriched_ids, axis, lookup, idf_weights, position_scores=scores)
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
    print(f"Wrote S6 relocated Group-B position-scores eval to {output}")
    print(f"  eligible={len(eligible)} scoreable={scoreable} no_axis={no_axis}")
    for condition in CONDITIONS:
        metrics = report["conditions"][condition]["metrics"]["boundary_metrics_by_tolerance"]
        scores = " ".join(f"tol{tol}={metrics[str(tol)]['micro_f1']:.3f}" for tol in TOLERANCES)
        print(f"  {condition:>18}: {scores}")


if __name__ == "__main__":
    main()

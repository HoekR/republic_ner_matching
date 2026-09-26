#!/usr/bin/env python3
"""Does grounding Group-B to a GAP's specific candidate resolutions beat day-level grounding?

docs/DECISIONS.md 2026-09-23 ("Day-level grounding of Group-B partially recovers") found that
restricting Group-B's bonus to entities *some* enriched resolution that date claims recovers part
of the regression (tol0 0.555 -> 0.588) but not enough -- 56% of flagged paragraphs still survive
day-level grounding, far above the 1.6% grounded share the corpus-wide two-sided sample found,
because day-level grounding lets same-day cross-resolution false positives through (a name
genuinely belonging to a *different* resolution that date still passes).

This is the cheap, non-circular test of the "full two-sided entity-overlap consolidation table"
direction (docs/state.json 2026-09-23 next_action, lever (c)): ground a match to the *specific*
candidate resolution(s) that could actually open in the gap being scored, not the whole day.
Non-circular because `segment_day`'s count-constrained DP already knows -- before choosing any
paragraph position -- exactly which enriched-resolution indices fall in each gap between two
anchors (that set IS the gap's `count`); it only needs a smarter WHERE-within-the-gap score, not a
priori WHICH-resolution knowledge. This script recomputes that same anchor backbone
(`s6c_gap_segmentation.segment_day`'s own logic, duplicated read-only here since `predict()`
doesn't expose it) to scope grounding per gap before handing a precomputed `position_scores` dict
to `predict()`'s existing extension point -- no production code changes.

Same cheap-before-corpus-wide methodology as every prior S6 position_scores experiment this cycle:
scored through `s4_corpus_paragraph_predictions.py`'s own `predict()` codepath, restricted to the
19/21 scoreable gold days, at paragraph granularity (docs/DECISIONS.md 2026-09-21 "S6c target
metric rescoped" -- not character-offset tolerance).

Usage:
    uv run python -m scripts.s6_group_b_candidate_grounded_position_scores_eval
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from build_alignment_new import (
    align_session,
    calculate_idf_weights,
    load_entity_names,
    load_institution_names,
    load_persons_info_lookup,
    resolve_enriched_entities,
    LOC_ENTITIES_FILE,
    ORG_ENTITIES_FILE,
    PER_ENTITIES_FILE,
)
from data_io import load, resolve, save_semi_structured
from evaluation_harness import evaluate_segmentation_session, summarize_segmentation_evaluations
from scripts.evaluate_s4_paragraph_axis import review_codes, transition_indices
from scripts.s4_corpus_paragraph_predictions import (
    AXIS_DATASET,
    ENRICHED_DATASET,
    OVERLAP_DATASETS,
    axis_for_date,
    enriched_key,
    predict,
    resolved_sessions,
    session_of,
)
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, overlap_enriched_id
from scripts.s6_group_b_grounded_position_scores_eval import (
    grounded_names_by_date,
    group_b_grounded_position_scores,
)
from scripts.s6_group_b_position_scores_eval import group_b_position_scores


GOLD_DATASET = "boundary_gold_sample"
SURFACE_MATCH_DATASET = "entity_surface_matches_1626_1630"
OUTPUT_DATASET = "s6_group_b_candidate_grounded_position_scores_eval"
CONDITIONS = ("baseline", "group_b", "group_b_day_grounded", "group_b_candidate_grounded")
TOLERANCES = (0, 1, 2)  # paragraph units, not characters -- see module docstring


def enriched_items_by_key(dates: set[str]) -> dict[str, dict[str, Any]]:
    """date_index-style key (same convention `overlap_enriched_id` produces for gold ids) -> item."""
    items: dict[str, dict[str, Any]] = {}
    for item in load(ENRICHED_DATASET):
        date = str(item.get("date", ""))[:10]
        if date not in dates:
            continue
        key = enriched_key(item, date)
        if key:
            items[str(key)] = item
    return items


def anchor_backbone(
    enriched_count: int, axis_count: int, alignments: list[tuple[int | None, int | None]]
) -> list[tuple[int, int]]:
    """Duplicates `s6c_gap_segmentation.segment_day`'s backbone computation (read-only, not
    exported) so gap boundaries here exactly match what `predict()` will compute internally."""
    raw_anchors = sorted(
        {
            (int(enriched_index), int(axis_index))
            for enriched_index, axis_index in alignments
            if enriched_index is not None
            and axis_index is not None
            and 0 < enriched_index < enriched_count
            and 0 <= axis_index < axis_count
        }
    )
    backbone: list[tuple[int, int]] = [(0, 0)]
    last_axis = 0
    for enriched_index, axis_index in raw_anchors:
        if enriched_index <= backbone[-1][0]:
            continue
        clipped = min(max(axis_index, last_axis), axis_count - 1)
        backbone.append((enriched_index, clipped))
        last_axis = clipped
    backbone.append((enriched_count, axis_count))
    return backbone


def group_b_candidate_grounded_position_scores(
    axis: list[dict[str, Any]],
    matches_by_flat_id: dict[str, list[dict[str, Any]]],
    backbone: list[tuple[int, int]],
    enriched_ids: list[str],
    items_by_key: dict[str, dict[str, Any]],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    persons_info: dict[str, dict[str, str]],
    institution_names: dict[str, str],
    candidate_stats: dict[str, int],
) -> dict[int, float]:
    """Per-gap bonus: a match only counts if grounded to one of THAT gap's candidate resolutions'
    own known entities, not the whole day's. Ungrounded/unmatched candidates contribute nothing."""
    scores: dict[int, float] = {}
    for (left_enriched, left_axis), (right_enriched, right_axis) in zip(backbone, backbone[1:]):
        gap = right_enriched - left_enriched - 1
        if gap <= 0:
            continue
        candidate_ids = enriched_ids[left_enriched : right_enriched - 1]
        grounded_names: set[str] = set()
        for candidate_id in candidate_ids:
            candidate_stats["candidate_slots"] += 1
            item = items_by_key.get(str(candidate_id))
            if item is None:
                continue
            candidate_stats["candidate_slots_matched"] += 1
            resolved = resolve_enriched_entities(
                item, loc_names, per_names, org_names, persons_info=persons_info, institution_names=institution_names
            )
            names = resolved["places"] + resolved["persons_canonical"] + resolved["orgs"]
            grounded_names.update(name.strip().lower() for name in names if name and str(name).strip())
        if not grounded_names:
            continue
        low = left_axis
        high = max(left_axis, right_axis - 1)
        for index in range(low, min(high, len(axis) - 1) + 1):
            record = axis[index]
            matches = matches_by_flat_id.get(str(record.get("flat_id", "")))
            if not matches:
                continue
            kept = [match for match in matches if str(match.get("canonical_name", "")).strip().lower() in grounded_names]
            if not kept:
                continue
            best = max(float(match["match_score"]) for match in kept)
            scores[index] = min(1.0, best / 100.0)
    return scores


def main() -> None:
    gold = load(GOLD_DATASET)
    codes = review_codes()
    eligible = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S"]
    eligible_dates = {str(day["date"]) for day in eligible}

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

    loc_names = load_entity_names(LOC_ENTITIES_FILE)
    per_names = load_entity_names(PER_ENTITIES_FILE)
    org_names = load_entity_names(ORG_ENTITIES_FILE)
    persons_info = load_persons_info_lookup()
    institution_names = load_institution_names()
    day_grounded_names = grounded_names_by_date(eligible_dates, loc_names, per_names, org_names, persons_info, institution_names)
    items_by_key = enriched_items_by_key(eligible_dates)

    candidate_stats = {"candidate_slots": 0, "candidate_slots_matched": 0}
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
        axis_ids = [record["axis_id"] for record in axis]
        ref = transition_indices(day)
        alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
        backbone = anchor_backbone(len(enriched_ids), len(axis_ids), alignments)

        bonus = group_b_position_scores(axis, matches_by_flat_id)
        day_grounded_bonus = group_b_grounded_position_scores(axis, matches_by_flat_id, day_grounded_names.get(date, set()))
        candidate_grounded_bonus = group_b_candidate_grounded_position_scores(
            axis, matches_by_flat_id, backbone, enriched_ids, items_by_key,
            loc_names, per_names, org_names, persons_info, institution_names, candidate_stats,
        )

        record: dict[str, Any] = {
            "date": date,
            "k_e": int(day["k_e"]),
            "paragraph_count": len(axis),
            "group_b_paragraphs_with_evidence": len(bonus),
            "group_b_day_grounded_paragraphs_with_evidence": len(day_grounded_bonus),
            "group_b_candidate_grounded_paragraphs_with_evidence": len(candidate_grounded_bonus),
        }
        for condition, scores in (
            ("baseline", None),
            ("group_b", bonus),
            ("group_b_day_grounded", day_grounded_bonus),
            ("group_b_candidate_grounded", candidate_grounded_bonus),
        ):
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
    matched_share = (
        candidate_stats["candidate_slots_matched"] / candidate_stats["candidate_slots"]
        if candidate_stats["candidate_slots"]
        else 0.0
    )
    report = {
        "unit": "paragraph_stream",
        "tolerances": list(TOLERANCES),
        "eligible_sessions": len(eligible),
        "scoreable_sessions": scoreable,
        "no_axis_sessions": no_axis,
        "candidate_id_match_rate": matched_share,
        "candidate_slots": candidate_stats["candidate_slots"],
        "candidate_slots_matched": candidate_stats["candidate_slots_matched"],
        "conditions": {
            condition: {
                "predicted_sessions": len(evaluated[condition]),
                "metrics": summarize_segmentation_evaluations(evaluated[condition], tolerances=TOLERANCES),
            }
            for condition in CONDITIONS
        },
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote S6 candidate-grounded Group-B position-scores eval to {output}")
    print(f"  eligible={len(eligible)} scoreable={scoreable} no_axis={no_axis}")
    print(
        f"  candidate_id_match_rate={matched_share:.3f} "
        f"({candidate_stats['candidate_slots_matched']}/{candidate_stats['candidate_slots']})"
    )
    for condition in CONDITIONS:
        metrics = report["conditions"][condition]["metrics"]["boundary_metrics_by_tolerance"]
        scores = " ".join(f"tol{tol}={metrics[str(tol)]['micro_f1']:.3f}" for tol in TOLERANCES)
        print(f"  {condition:>26}: {scores}")


if __name__ == "__main__":
    main()

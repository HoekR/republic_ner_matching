#!/usr/bin/env python3
"""Does a GROUNDED Group-B signal help segment_day's placement, where the ungrounded one didn't?

docs/DECISIONS.md 2026-09-23 "Group-B position_scores wiring measured negative" found that raw
`entity_surface_matches_1626_1630` bonuses regress paragraph tol0 F1 (0.644 -> 0.555). A follow-up
two-sided check (same date, "entity_surface_matches' one-sided 'new' recoveries are almost entirely
ungrounded") found only 1.6% (4/243) of its "new" recoveries name an entity that any enriched
resolution on that date actually claims via `resolve_enriched_entities` -- the other 98.4% are
floating common terms, which explains the regression as near-uniform noise rather than a dead
mechanism. This script is the natural next test that finding implies: restrict Group-B's bonus to
matches whose `canonical_name` is grounded (present in the day's own enriched entity pool) and
re-run the identical gold-day harness `s6_group_b_position_scores_eval.py` used, so a real
improvement -- or a second negative result -- is caught before any corpus-wide rerun.

Grounding is checked at day granularity (a name must belong to *some* enriched resolution active
that date), matching the two-sided check's own methodology -- not per-candidate-assignment, which
would require already knowing the placement this script is trying to evaluate.

Usage:
    uv run python -m scripts.s6_group_b_grounded_position_scores_eval
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from build_alignment_new import (
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
    predict,
    resolved_sessions,
    session_of,
)
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, overlap_enriched_id
from scripts.s6_group_b_position_scores_eval import group_b_position_scores


GOLD_DATASET = "boundary_gold_sample"
SURFACE_MATCH_DATASET = "entity_surface_matches_1626_1630"
OUTPUT_DATASET = "s6_group_b_grounded_position_scores_eval"
CONDITIONS = ("baseline", "group_b", "group_b_grounded")
TOLERANCES = (0, 1, 2)  # paragraph units, not characters -- see module docstring


def grounded_names_by_date(
    dates: set[str],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    persons_info: dict[str, dict[str, str]],
    institution_names: dict[str, str],
) -> dict[str, set[str]]:
    """Per-date set of lowercased entity names any enriched resolution that date actually claims."""
    grounded: dict[str, set[str]] = defaultdict(set)
    for item in load(ENRICHED_DATASET):
        date = str(item.get("date", ""))[:10]
        if date not in dates:
            continue
        resolved = resolve_enriched_entities(
            item, loc_names, per_names, org_names, persons_info=persons_info, institution_names=institution_names
        )
        names = resolved["places"] + resolved["persons_canonical"] + resolved["orgs"]
        grounded[date].update(name.strip().lower() for name in names if name and str(name).strip())
    return grounded


def group_b_grounded_position_scores(
    axis: list[dict[str, Any]],
    matches_by_flat_id: dict[str, list[dict[str, Any]]],
    grounded_names: set[str],
) -> dict[int, float]:
    """Same as group_b_position_scores, but only matches grounded to the day's own enriched entities."""
    filtered: dict[str, list[dict[str, Any]]] = {}
    for flat_id, matches in matches_by_flat_id.items():
        kept = [match for match in matches if str(match.get("canonical_name", "")).strip().lower() in grounded_names]
        if kept:
            filtered[flat_id] = kept
    return group_b_position_scores(axis, filtered)


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
    grounded_names = grounded_names_by_date(eligible_dates, loc_names, per_names, org_names, persons_info, institution_names)

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
        day_grounded = grounded_names.get(date, set())
        bonus = group_b_position_scores(axis, matches_by_flat_id)
        grounded_bonus = group_b_grounded_position_scores(axis, matches_by_flat_id, day_grounded)

        record: dict[str, Any] = {
            "date": date,
            "k_e": int(day["k_e"]),
            "paragraph_count": len(axis),
            "group_b_paragraphs_with_evidence": len(bonus),
            "group_b_grounded_paragraphs_with_evidence": len(grounded_bonus),
        }
        for condition, scores in (("baseline", None), ("group_b", bonus), ("group_b_grounded", grounded_bonus)):
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
    print(f"Wrote S6 grounded Group-B position-scores eval to {output}")
    print(f"  eligible={len(eligible)} scoreable={scoreable} no_axis={no_axis}")
    for condition in CONDITIONS:
        metrics = report["conditions"][condition]["metrics"]["boundary_metrics_by_tolerance"]
        scores = " ".join(f"tol{tol}={metrics[str(tol)]['micro_f1']:.3f}" for tol in TOLERANCES)
        print(f"  {condition:>17}: {scores}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Tier P — bottleneck diagnostic: evidence (Tier A–D anchors) vs placement algorithm.

Repeatable rerun of the S6 Step-1 oracle technique (docs/METRICS.md; docs/DECISIONS.md
2026-09-20). On the eligible gold-day sample:

* ``oracle_ceiling`` — perfect gold-derived anchors fed to the *unmodified*
  ``interpolate_positions`` + ``snap_boundaries`` placement model
  (same path as ``scripts/s6_oracle_anchor_diagnostic.py``).
* ``real_performance`` — NW entity anchors from the current overlap tables fed to
  the *same* unmodified placement model (not ``segment_day`` / S6c).

Decision rule (fixed before the run; feeds ``svz.py review``, does not replace it):

* ``oracle_ceiling - real_performance`` large  → Tier A–D evidence still binds
* gap small                                   → placement algorithm (Tier P) binds
* ``oracle_ceiling`` itself far below Tier O   → algorithm needs a different design

Usage:
    uv run python scripts/metrics_bottleneck_diagnostic.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, resolve, save_semi_structured
from evaluation_harness import evaluate_segmentation_session, summarize_segmentation_evaluations
from scripts.s4_paragraph_axis_baseline import (
    OVERLAP_DATASETS,
    build_axis_overlap,
    build_phrase_searcher,
    interpolate_positions,
    overlap_enriched_id,
    phrase_hits,
    snap_boundaries,
)
from scripts.s6_oracle_anchor_diagnostic import (
    CHAR_TOLERANCES,
    anchor_obstruction,
    compose_prediction,
    oracle_anchors,
)
from scripts.s6a_char_axis_evaluation import (
    REF_KINDS,
    axis_char_length,
    char_starts,
    composed_positions,
    review_codes,
)

GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
PHRASE_DATASET = "s4_opening_phrase_candidates"
OUTPUT_DATASET = "metrics_bottleneck_diagnostic"

# Coverage gap above this (oracle - real) counts as "evidence still binds".
# Chosen to match the original S6 Step-1 reading scale (oracle 0.263 vs near-zero
# real under interpolate_positions): a gap of ~0.15+ is "large".
COVERAGE_GAP_LARGE = 0.15
# Oracle coverage far below what Tier O's Global primary (~0.50 of ceiling) needs
# from predicted-day coverage on scoreable gold — 0.40 is already a redesign signal.
ORACLE_COVERAGE_REDESIGN = 0.40


def nw_anchors(
    day: dict[str, Any],
    axis: list[dict[str, Any]],
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
) -> list[tuple[int, int]]:
    """Entity-NW alignments as ``(enriched_index, axis_index)`` anchors (non-null only)."""
    enriched_ids = [overlap_enriched_id(enriched_id, str(day["date"])) for enriched_id in day["enriched_ids"]]
    axis_ids = [record["axis_id"] for record in axis]
    alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
    return [
        (int(enriched_index), int(axis_index))
        for enriched_index, axis_index in alignments
        if enriched_index is not None and axis_index is not None
    ]


def run_placement(
    *,
    k_e: int,
    axis_count: int,
    anchors: Sequence[tuple[int, int]],
    starts: Sequence[int],
    hits: dict[int, tuple[str, int, float]],
) -> dict[str, Any]:
    """Place with unmodified interpolate_positions; return status + composed hyp."""
    obstruction = anchor_obstruction(anchors, k_e, axis_count)
    if obstruction is not None:
        return {"status": "abstained", "reason": obstruction, "hyp_composed": []}
    if not anchors and k_e > 1:
        return {"status": "abstained", "reason": "no_anchors", "hyp_composed": []}
    positions = interpolate_positions(k_e, axis_count, anchors)
    if positions is None:
        return {"status": "abstained", "reason": "interpolation_failed", "hyp_composed": []}
    hyp = compose_prediction(starts, snap_boundaries(positions, hits))
    return {"status": "predicted", "reason": None, "hyp_composed": hyp}


def classify_bottleneck(
    *,
    oracle_coverage: float,
    real_coverage: float,
    coverage_gap_large: float = COVERAGE_GAP_LARGE,
    oracle_redesign: float = ORACLE_COVERAGE_REDESIGN,
) -> dict[str, Any]:
    """Decision-aid labels for svz review — not an automatic switch."""
    gap = float(oracle_coverage) - float(real_coverage)
    if oracle_coverage < oracle_redesign:
        focus = "algorithm_redesign"
        note = (
            "oracle_ceiling itself is far below what Tier O needs; "
            "more Tier A-D evidence will not unlock the sample under this placement model."
        )
    elif gap >= coverage_gap_large:
        focus = "tier_a_d_evidence"
        note = (
            "oracle_ceiling - real_performance is large: real anchors are far below "
            "what the algorithm could use — harvesting/improving Tier A-D is next."
        )
    else:
        focus = "tier_p_placement"
        note = (
            "oracle_ceiling - real_performance is small: the algorithm already extracts "
            "nearly all it can from current-quality anchors — Tier P itself is next."
        )
    return {
        "recommended_focus": focus,
        "coverage_gap": round(gap, 4),
        "coverage_gap_large_threshold": float(coverage_gap_large),
        "oracle_redesign_threshold": float(oracle_redesign),
        "note": note,
    }


def summarize_arm(
    evaluated: list[Any],
    abstentions: Counter[str],
    *,
    scoreable: int,
) -> dict[str, Any]:
    predicted = len(evaluated)
    return {
        "predicted_sessions": predicted,
        "scoreable_sessions": scoreable,
        "coverage": predicted / scoreable if scoreable else 0.0,
        "abstentions_by_reason": dict(abstentions),
        "metrics": (
            summarize_segmentation_evaluations(evaluated, tolerances=CHAR_TOLERANCES)
            if evaluated
            else {}
        ),
    }


def micro_f1(arm: dict[str, Any], tol: int = 50) -> float | None:
    metrics = arm.get("metrics") or {}
    by_tol = metrics.get("boundary_metrics_by_tolerance") or {}
    entry = by_tol.get(str(tol)) or {}
    value = entry.get("micro_f1")
    return float(value) if value is not None else None


def main() -> None:
    gold = load(GOLD_DATASET)
    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)

    phrase_candidates = load(PHRASE_DATASET)[0]["candidates"]
    phrases = [item["phrase"] for item in phrase_candidates if item["word_count"] >= 3]
    searcher = build_phrase_searcher(phrases)

    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [
        overlap.rename(columns={"naam": "name"}) if "name" not in overlap and "naam" in overlap else overlap
        for overlap in overlaps
    ]
    combined = pd.concat(overlaps, ignore_index=True)
    # Axis for lookup is the flat gold-day paragraph axis list.
    all_axis = [record for records in axis_by_date.values() for record in records]
    lookup = build_axis_overlap(all_axis, combined)
    idf_weights = calculate_idf_weights(combined)

    codes = review_codes()
    eligible = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S"]

    per_day: list[dict[str, Any]] = []
    oracle_evaluated: list[Any] = []
    real_evaluated: list[Any] = []
    oracle_abstentions: Counter[str] = Counter()
    real_abstentions: Counter[str] = Counter()

    for day in eligible:
        date = str(day["date"])
        axis = axis_by_date.get(date)
        if not axis:
            continue

        starts = char_starts(axis)
        ref = composed_positions(day, starts, REF_KINDS)
        hits = phrase_hits(axis, searcher)
        k_e = int(day["k_e"])
        axis_count = len(axis)
        total_length = axis_char_length(axis)

        record: dict[str, Any] = {
            "record_type": "day",
            "date": date,
            "k_e": k_e,
            "axis_paragraph_count": axis_count,
            "ref_composed": len(ref),
        }

        perfect = oracle_anchors(day)
        if perfect is None:
            record["oracle"] = {"status": "abstained", "reason": "gold_cut_without_paragraph_index"}
            record["real"] = {"status": "skipped", "reason": "oracle_gold_gap"}
            per_day.append(record)
            oracle_abstentions["gold_cut_without_paragraph_index"] += 1
            real_abstentions["oracle_gold_gap"] += 1
            continue

        oracle_run = run_placement(
            k_e=k_e, axis_count=axis_count, anchors=perfect, starts=starts, hits=hits
        )
        record["oracle"] = {
            "status": oracle_run["status"],
            "reason": oracle_run["reason"],
            "n_anchors": len(perfect),
            "hyp_composed": len(oracle_run["hyp_composed"]),
        }
        if oracle_run["status"] == "predicted":
            oracle_evaluated.append(
                evaluate_segmentation_session(
                    session_id=date,
                    date=date,
                    k_e=k_e,
                    ref_boundaries=ref,
                    hyp_boundaries=oracle_run["hyp_composed"],
                    total_length=total_length,
                    tolerances=CHAR_TOLERANCES,
                )
            )
        else:
            oracle_abstentions[str(oracle_run["reason"])] += 1

        real = nw_anchors(day, axis, lookup, idf_weights)
        real_run = run_placement(
            k_e=k_e, axis_count=axis_count, anchors=real, starts=starts, hits=hits
        )
        record["real"] = {
            "status": real_run["status"],
            "reason": real_run["reason"],
            "n_anchors": len(real),
            "hyp_composed": len(real_run["hyp_composed"]),
        }
        if real_run["status"] == "predicted":
            real_evaluated.append(
                evaluate_segmentation_session(
                    session_id=date,
                    date=date,
                    k_e=k_e,
                    ref_boundaries=ref,
                    hyp_boundaries=real_run["hyp_composed"],
                    total_length=total_length,
                    tolerances=CHAR_TOLERANCES,
                )
            )
        else:
            real_abstentions[str(real_run["reason"])] += 1

        per_day.append(record)

    scoreable = len(per_day)
    oracle_arm = summarize_arm(oracle_evaluated, oracle_abstentions, scoreable=scoreable)
    real_arm = summarize_arm(real_evaluated, real_abstentions, scoreable=scoreable)
    decision = classify_bottleneck(
        oracle_coverage=float(oracle_arm["coverage"]),
        real_coverage=float(real_arm["coverage"]),
    )

    meta: dict[str, Any] = {
        "record_type": "meta",
        "tier": "P",
        "placement_model": "interpolate_positions+snap_boundaries",
        "eligible_sessions": len(eligible),
        "scoreable_sessions": scoreable,
        "oracle_ceiling": {
            "coverage": round(float(oracle_arm["coverage"]), 4),
            "predicted_sessions": oracle_arm["predicted_sessions"],
            "micro_f1_tol50": micro_f1(oracle_arm, 50),
            "abstentions_by_reason": oracle_arm["abstentions_by_reason"],
        },
        "real_performance": {
            "coverage": round(float(real_arm["coverage"]), 4),
            "predicted_sessions": real_arm["predicted_sessions"],
            "micro_f1_tol50": micro_f1(real_arm, 50),
            "abstentions_by_reason": real_arm["abstentions_by_reason"],
        },
        "decision": decision,
        "oracle_arm": oracle_arm,
        "real_arm": real_arm,
        "note": (
            "Same unmodified placement model for both arms. "
            "S6c segment_day is deliberately not used here so the reading stays "
            "comparable to s6_oracle_anchor_diagnostic."
        ),
    }

    records: list[dict[str, Any]] = [meta, *per_day]
    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[GOLD_DATASET, AXIS_DATASET, PHRASE_DATASET, *OVERLAP_DATASETS],
        description=(
            "Tier P bottleneck diagnostic: oracle_ceiling (perfect gold anchors) vs "
            "real_performance (NW entity anchors) under unmodified interpolate_positions; "
            "decision aid for whether Tier A-D evidence or the placement algorithm binds."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(
        f"oracle_coverage={meta['oracle_ceiling']['coverage']:.3f} "
        f"({meta['oracle_ceiling']['predicted_sessions']}/{scoreable}) "
        f"real_coverage={meta['real_performance']['coverage']:.3f} "
        f"({meta['real_performance']['predicted_sessions']}/{scoreable}) "
        f"gap={decision['coverage_gap']:.3f} "
        f"focus={decision['recommended_focus']}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Does PER-RESOLUTION TF-IDF similarity move `separated_count`, corpus-wide?

Why a second similarity eval. `scripts/s6c_similarity_position_scores_eval.py` measured the
*collapsed* wiring: `similarity_position_scores` takes the per-paragraph max over the
(k_e x k_p) similarity matrix, which answers "does some resolution like this paragraph?" and
therefore cannot say *which* resolution goes there. It measured NEGATIVE, and the mechanism
was diagnosed (commit 8f90e4b): scale 0.5/1.0 left the DP's argmax untouched (bit-identical
output), and scale 3.0 moved placements the wrong way, because what the collapsed bonus
varies with is the absolute similarity level -- mean 0.1314, against a correct-vs-best-wrong
margin of only 0.0201.

`segment_gap`'s new `rank_scores` keeps the rows apart instead: slot `rank` of a gap is the
enriched resolution `left_anchor + rank`, so it can be scored by its own similarity row.
`similarity_rank_scores` supplies those rows under three bonus forms -- `raw` (the level, the
form already known to fail, kept as the null), `rownorm` (similarity / row max, so the level
cancels and each resolution's best paragraph scores the full scale), and `zscore` (only
paragraphs a resolution likes more than its own row mean score at all).

Scoring. `separated_count` / `separated_share` per PLAN.md's acceptance criteria and
docs/METRICS.md Tier O -- a resolution is separated iff its start paragraph is unique on its
date and its extent is <= 3 paragraphs. No boundary-F1-at-tolerance at any granularity
(docs/METRICS.md:187 demotes that family). **No gold dependency**: separation is a property of
a prediction alone, so this runs over every corpus day rather than the 19-day gold subset,
which is the whole point of re-scoring it this way -- the previous eval's 197 attributed
resolutions were too few for a real effect to show, and `separated` needs no reference
annotation to compute.

What this cannot tell you. `separated` is a *coverage* criterion, not a correctness one: a
condition can raise it by spreading placements apart while getting them wrong. Read a positive
delta here as "worth scoring for correctness next" (via `separated_accuracy_eval` on the gold
days), never as "better alignment" on its own.

Cuts -> paragraph ranges reuse `s4_resolution_concordance.resolution_paragraph_range` and the
separation predicate reuses `separated_accuracy_eval.label_separation` (itself assertion-locked
against `metrics_separation_span_table.count_separated_per_day`), so neither is re-derived here.

Cost. One NW alignment plus one TF-IDF matrix per day, and one DP per day per condition; the
matrix is computed once per day and shared. Smoke-test with `--limit` before the full corpus.

Usage:
    uv run python -m scripts.s6c_similarity_rank_scores_eval --limit 40
    uv run python -m scripts.s6c_similarity_rank_scores_eval
    uv run python -m scripts.s6c_similarity_rank_scores_eval --scale 0.5 1.0 --normalize rownorm zscore
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
from scripts.s4_corpus_paragraph_predictions import (
    AXIS_DATASET,
    OVERLAP_DATASETS,
    axis_for_date,
    compute_similarity_matrix,
    extract_axis_texts,
    grouped_enriched,
    load_enriched_texts_by_date,
    predict,
    resolved_sessions,
    session_of,
)
from scripts.s4_paragraph_axis_baseline import build_axis_overlap
from scripts.s4_resolution_concordance import resolution_paragraph_range
from scripts.s6c_gap_segmentation import RANK_NORMALIZATIONS, similarity_rank_scores
from scripts.separated_accuracy_eval import label_separation

OUTPUT_DATASET = "s6c_similarity_rank_scores_eval"
SPAN_GAP_DATASET = "metrics_span_gap_map"
EMBEDDER_BACKEND = "tfidf"
BASELINE = "baseline"


def weak_separation_dates() -> set[str]:
    """The `weak_separation` days the TF-IDF track set out to improve (secondary facet).

    Read-only and non-essential: a missing or changed `metrics_span_gap_map` costs the facet,
    not the run, because the headline metric is corpus-wide.
    """
    try:
        span_gap = load(SPAN_GAP_DATASET)
    except Exception as error:  # noqa: BLE001 - facet is optional by design
        print(f"Warning: no weak_separation facet ({error})", file=sys.stderr)
        return set()
    dates = set()
    for row in span_gap:
        if isinstance(row, dict) and row.get("nonsolid_class") == "weak_separation":
            date = str(row.get("enriched_date") or "")[:10]
            if date and date != "None":
                dates.add(date)
    return dates


def placement_rows(date: str, prediction: dict[str, Any], k_e: int) -> list[dict[str, Any]]:
    """One row per resolution, carrying the paragraph range `label_separation` needs."""
    if prediction.get("status") != "predicted":
        return []
    cuts = sorted(boundary["paragraph_stream_index"] for boundary in prediction["boundaries"])
    if len(cuts) != k_e - 1:
        return []
    paragraph_count = int(prediction["paragraph_count"])
    rows = []
    for index in range(k_e):
        start, end = resolution_paragraph_range(index, cuts, paragraph_count)
        rows.append(
            {
                "enriched_date": date,
                "resolution_index": index,
                "k_e": k_e,
                "paragraph_count": paragraph_count,
                "paragraph_start_index": start,
                "paragraph_end_index": end,
            }
        )
    return rows


def score_condition(rows: list[dict[str, Any]], weak_dates: set[str]) -> dict[str, Any]:
    """Separation counts over every scoreable row, plus the weak_separation-day facet."""
    if not rows:
        return {"attributed": 0, "separated_count": 0, "separated_share": None}
    labelled = label_separation(pd.DataFrame(rows))
    separated = int(labelled["separated"].sum())
    scored: dict[str, Any] = {
        "attributed": int(len(labelled)),
        "separated_count": separated,
        "separated_share": round(separated / len(labelled), 4),
        "loss_reasons": {
            reason: int(count) for reason, count in labelled["loss_reason"].value_counts().items()
        },
    }
    if weak_dates:
        weak = labelled.loc[labelled["enriched_date"].isin(weak_dates)]
        weak_separated = int(weak["separated"].sum())
        scored["weak_separation_facet"] = {
            "attributed": int(len(weak)),
            "separated_count": weak_separated,
            "separated_share": round(weak_separated / len(weak), 4) if len(weak) else None,
        }
    return scored


def score_weak_gated(
    baseline_rows: list[dict[str, Any]],
    condition_rows: list[dict[str, Any]],
    weak_dates: set[str],
) -> dict[str, Any]:
    """Separation if the condition were applied on weak_separation days *only*.

    Exact, not an estimate, and needs no extra run: `separated` is defined within one date
    (unique start paragraph on that date, extent <= 3), so swapping one day's placements cannot
    change another day's separation. Both row sets come from the same
    `resolution_paragraph_range` derivation, so the extent half of the predicate is comparable
    too -- reconstructing ranges by hand instead gets the extents wrong.
    """
    if not baseline_rows or not condition_rows or not weak_dates:
        return {}
    mixed = [row for row in condition_rows if row["enriched_date"] in weak_dates]
    mixed += [row for row in baseline_rows if row["enriched_date"] not in weak_dates]
    labelled = label_separation(pd.DataFrame(mixed))
    separated = int(labelled["separated"].sum())
    return {
        "attributed": int(len(labelled)),
        "separated_count": separated,
        "separated_share": round(separated / len(labelled), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scale",
        type=float,
        nargs="+",
        default=[0.5, 1.0],
        help="Bonus scales to sweep (default: 0.5 1.0). segment_gap multiplies these by "
        "phrase_weight=3.0 against a dispersion penalty of 1.0 per paragraph of drift.",
    )
    parser.add_argument(
        "--normalize",
        type=str,
        nargs="+",
        default=["rownorm", "zscore"],
        choices=list(RANK_NORMALIZATIONS),
        help="Bonus forms to sweep (default: rownorm zscore). 'raw' is the already-failed "
        "absolute-level form, kept available as the null.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Score only the first N corpus days (default: 0, all). Use for a cheap smoke run.",
    )
    args = parser.parse_args()

    axis = load(AXIS_DATASET)
    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        axis_by_date[str(record["date"])].append(record)
        axis_by_session[session_of(record["flat_id"])].append(record)
    session_by_date = resolved_sessions()

    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [
        overlap.rename(columns={"naam": "name"}) if "name" not in overlap and "naam" in overlap else overlap
        for overlap in overlaps
    ]
    combined = pd.concat(overlaps, ignore_index=True)
    lookup = build_axis_overlap(axis, combined)
    idf_weights = calculate_idf_weights(combined)

    embedder = AlignmentEmbedder(backend=EMBEDDER_BACKEND)
    enriched_texts_by_date = load_enriched_texts_by_date()
    weak_dates = weak_separation_dates()

    variants = [(scale, normalize) for normalize in args.normalize for scale in args.scale]
    conditions = [BASELINE] + [f"rank@{scale:g}/{normalize}" for scale, normalize in variants]
    rows_by_condition: dict[str, list[dict[str, Any]]] = {name: [] for name in conditions}
    per_day: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)

    days = sorted(grouped_enriched().items())
    if args.limit:
        days = days[: args.limit]

    for date, enriched_ids in days:
        axis_records = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis_records:
            skipped["no_axis"] += 1
            continue

        k_e = len(enriched_ids)
        enriched_texts = enriched_texts_by_date.get(date, [])
        axis_texts = extract_axis_texts(axis_records)
        matrix: np.ndarray | None = None
        if enriched_texts and axis_texts:
            matrix = compute_similarity_matrix(enriched_texts, axis_texts, embedder)

        record: dict[str, Any] = {
            "record_type": "day",
            "date": date,
            "k_e": k_e,
            "paragraph_count": len(axis_records),
            "weak_separation_day": date in weak_dates,
        }
        for name, variant in zip(conditions, [None, *variants]):
            if variant is None:
                scores = None
            elif matrix is None:
                skipped["no_similarity_matrix"] += 1
                continue
            else:
                scale, normalize = variant
                scores = similarity_rank_scores(matrix, scale=scale, normalize=normalize)
                record["resolutions_with_evidence"] = len(scores)

            prediction = predict(
                date,
                enriched_ids,
                axis_records,
                lookup,
                idf_weights,
                resolution_scores=scores,
            )
            rows = placement_rows(date, prediction, k_e)
            if not rows:
                skipped[f"unusable_prediction_{name}"] += 1
                continue
            rows_by_condition[name].extend(rows)
            record[name] = {
                "separated_rows": int(label_separation(pd.DataFrame(rows))["separated"].sum()),
                "starts": [row["paragraph_start_index"] for row in rows],
            }
        per_day.append(record)

    scored_by_condition = {
        name: score_condition(rows, weak_dates) for name, rows in rows_by_condition.items()
    }
    baseline_separated = scored_by_condition[BASELINE]["separated_count"]
    for name in conditions:
        if name == BASELINE:
            continue
        scored_by_condition[name]["separated_delta_vs_baseline"] = (
            scored_by_condition[name]["separated_count"] - baseline_separated
        )
        # A condition that leaves every start where the baseline put it is not "no effect on
        # separation" -- it is the bonus never clearing the dispersion penalty, which is the
        # failure mode commit 8f90e4b diagnosed for the collapsed wiring. Report the two apart.
        moved = sum(
            1
            for day in per_day
            if BASELINE in day and name in day and day[name]["starts"] != day[BASELINE]["starts"]
        )
        scored_by_condition[name]["days_with_moved_starts"] = moved
        gated = score_weak_gated(
            rows_by_condition[BASELINE], rows_by_condition[name], weak_dates
        )
        if gated:
            gated["separated_delta_vs_baseline"] = gated["separated_count"] - baseline_separated
            scored_by_condition[name]["weak_separation_gated"] = gated

    report = {
        "record_type": "report",
        "unit": "paragraph_stream",
        "metric": "separated_count / separated_share (PLAN.md acceptance criteria, docs/METRICS.md Tier O)",
        "wiring": "segment_gap rank_scores (per-resolution), via similarity_rank_scores",
        "gold_dependency": "none -- separation is computable from a prediction alone",
        "scales": list(args.scale),
        "normalizations": list(args.normalize),
        "day_limit": args.limit or None,
        "corpus_days": len(days),
        "scoreable_days": len(per_day),
        "weak_separation_days_in_scope": sum(1 for day in per_day if day["weak_separation_day"]),
        "skipped": dict(skipped),
        "comparability_note": (
            "Counts are recomputed from predictions inside this run and need not equal the "
            "published corpus baseline of 8,015 separated / 68.8% of ceiling, which comes "
            "through resolution_concordance and its extra abstention reasons. Compare "
            "conditions within this run only."
        ),
        "conditions": scored_by_condition,
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote S6c per-rank similarity separation eval to {output}")
    print(f"  corpus_days={len(days)} scoreable={len(per_day)} skipped={dict(skipped)}")
    for name in conditions:
        scored = scored_by_condition[name]
        if not scored["attributed"]:
            print(f"  {name:>20}: no usable rows")
            continue
        suffix = ""
        if name != BASELINE:
            suffix = (
                f" delta={scored['separated_delta_vs_baseline']:+d}"
                f" days_moved={scored['days_with_moved_starts']}"
            )
        print(
            f"  {name:>20}: separated={scored['separated_count']}/{scored['attributed']}"
            f" share={scored['separated_share']}{suffix}"
        )
        facet = scored.get("weak_separation_facet")
        if facet and facet["attributed"]:
            print(
                f"  {'':>20}  weak_separation days: "
                f"{facet['separated_count']}/{facet['attributed']} share={facet['separated_share']}"
            )
        gated = scored.get("weak_separation_gated")
        if gated:
            print(
                f"  {'':>20}  applied on weak days only: {gated['separated_count']}"
                f"/{gated['attributed']} share={gated['separated_share']}"
                f" delta={gated['separated_delta_vs_baseline']:+d}"
            )


if __name__ == "__main__":
    main()

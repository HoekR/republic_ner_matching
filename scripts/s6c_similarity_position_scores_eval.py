#!/usr/bin/env python3
"""Does TF-IDF similarity as `position_scores` move the *separation* metric?

Scored on PLAN.md's acceptance criteria only: a resolution is **separated** iff its start
paragraph is unique on its date and its extent is <= 3 paragraphs (`docs/METRICS.md` Tier O,
`separated_count` / `separated_share`). Boundary micro-F1 at tolerances is deliberately absent --
`docs/METRICS.md:187` demotes that family and it is not this project's target metric at any
granularity, character or paragraph.

The first version of this script (commit e3a33da) reported tol0/tol1/tol2 boundary F1 and was
re-scored for exactly that reason; the wiring it measured (`s6c_gap_segmentation.similarity_position_scores`)
is unchanged.

Method. For each scoreable gold day, run `s4_corpus_paragraph_predictions.predict()` twice -- once
with no `position_scores` (the production baseline) and once with the max-per-paragraph TF-IDF
similarity bonus -- then turn each prediction's cuts into per-resolution paragraph ranges with
`s4_resolution_concordance.resolution_paragraph_range` (the same derivation the concordance itself
uses) and label them with `separated_accuracy_eval.label_separation` (which is assertion-locked
against `metrics_separation_span_table.count_separated_per_day`). Neither the separation predicate
nor the gold-slot convention is re-derived here.

`separated` is a *coverage* criterion and cannot tell whether a placement is right, so exact
start-paragraph agreement and absolute displacement against gold are reported alongside it, via
`separated_accuracy_eval.accuracy`. Resolution 0 is held out of the accuracy figures: it starts at
paragraph 0 by construction on both sides, so scoring it hands every condition a free agreement.

Counts here are a 19-day gold subset and are NOT comparable to the corpus-wide 8,015 / 68.8%
baseline; the comparison that matters is baseline vs. similarity within this run.

Usage:
    uv run python -m scripts.s6c_similarity_position_scores_eval
    uv run python -m scripts.s6c_similarity_position_scores_eval --scale 0.5 1.0 3.0
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
from scripts.evaluate_s4_paragraph_axis import review_codes
from scripts.s4_corpus_paragraph_predictions import (
    AXIS_DATASET,
    OVERLAP_DATASETS,
    axis_for_date,
    extract_axis_texts,
    load_enriched_texts_by_date,
    predict,
    resolved_sessions,
    session_of,
)
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, overlap_enriched_id
from scripts.s4_resolution_concordance import resolution_paragraph_range
from scripts.s6c_gap_segmentation import similarity_position_scores
from scripts.separated_accuracy_eval import accuracy, gold_start_paragraphs, label_separation

GOLD_DATASET = "boundary_gold_sample"
OUTPUT_DATASET = "s6c_similarity_position_scores_eval"
EMBEDDER_BACKEND = "tfidf"
BASELINE = "baseline"


def placement_rows(
    date: str, prediction: dict[str, Any], k_e: int, gold_starts: list[int | None]
) -> list[dict[str, Any]]:
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
                "gold_start": gold_starts[index] if index < len(gold_starts) else None,
            }
        )
    return rows


def score_condition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Separation counts over every row, accuracy over resolutions 1..k_e-1 only."""
    if not rows:
        return {"attributed": 0, "separated_count": 0, "separated_share": None}
    labelled = label_separation(pd.DataFrame(rows))
    separated = int(labelled["separated"].sum())
    scoreable = labelled.loc[labelled["resolution_index"] >= 1]
    return {
        "attributed": int(len(labelled)),
        "separated_count": separated,
        "separated_share": round(separated / len(labelled), 4),
        "loss_reasons": {
            reason: int(count) for reason, count in labelled["loss_reason"].value_counts().items()
        },
        "accuracy_vs_gold": accuracy(scoreable, "paragraph_start_index"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scale",
        type=float,
        nargs="+",
        default=[0.5, 1.0, 3.0],
        help="One or more similarity bonus scales to sweep (default: 0.5 1.0 3.0).",
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

    conditions = [BASELINE] + [f"similarity@{scale:g}" for scale in args.scale]
    rows_by_condition: dict[str, list[dict[str, Any]]] = {name: [] for name in conditions}
    per_day: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)

    for day in eligible:
        date = str(day["date"])
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis:
            skipped["no_axis"] += 1
            continue

        k_e = int(day["k_e"])
        enriched_ids = [overlap_enriched_id(enriched_id, date) for enriched_id in day["enriched_ids"]]
        gold_starts = gold_start_paragraphs(day, k_e)

        enriched_texts = enriched_texts_by_date.get(date, [])
        axis_texts = extract_axis_texts(axis)
        matrix: np.ndarray | None = None
        if enriched_texts and axis_texts:
            matrix = embedder.compute_similarity_matrix(enriched_texts, axis_texts)

        record: dict[str, Any] = {"date": date, "k_e": k_e, "paragraph_count": len(axis)}
        for name in conditions:
            if name == BASELINE:
                scores = None
            elif matrix is None:
                skipped["no_similarity_matrix"] += 1
                continue
            else:
                scores = similarity_position_scores(matrix, scale=float(name.split("@")[1]))
                record["similarity_paragraphs_with_evidence"] = len(scores)

            prediction = predict(date, enriched_ids, axis, lookup, idf_weights, position_scores=scores)
            rows = placement_rows(date, prediction, k_e, gold_starts)
            if not rows:
                skipped[f"unusable_prediction_{name}"] += 1
                continue
            rows_by_condition[name].extend(rows)
            record[name] = {
                "separated_rows": int(label_separation(pd.DataFrame(rows))["separated"].sum())
            }
        per_day.append(record)

    report = {
        "unit": "paragraph_stream",
        "metric": "separated_count / separated_share (PLAN.md acceptance criteria, docs/METRICS.md Tier O)",
        "scales": list(args.scale),
        "eligible_sessions": len(eligible),
        "scoreable_sessions": len(per_day),
        "skipped": dict(skipped),
        "subset_note": (
            "19-day gold subset; NOT comparable to the corpus-wide 8,015 / 68.8% baseline. "
            "Compare conditions within this run only."
        ),
        "conditions": {name: score_condition(rows) for name, rows in rows_by_condition.items()},
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote S6c similarity separation eval to {output}")
    print(f"  eligible={len(eligible)} scoreable={len(per_day)} skipped={dict(skipped)}")
    baseline_separated = report["conditions"][BASELINE]["separated_count"]
    for name in conditions:
        scored = report["conditions"][name]
        if not scored["attributed"]:
            print(f"  {name:>16}: no usable rows")
            continue
        exact = scored["accuracy_vs_gold"]["exact_agreement"]
        delta = scored["separated_count"] - baseline_separated
        print(
            f"  {name:>16}: separated={scored['separated_count']}/{scored['attributed']}"
            f" share={scored['separated_share']} delta={delta:+d}"
            f" exact_start_agreement={exact}"
        )


if __name__ == "__main__":
    main()

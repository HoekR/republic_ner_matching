#!/usr/bin/env python3
"""Is the `weak_separation`-gated per-rank similarity gain *correct*, or only spread?

plans/TFIDF_EMBEDDINGS_TRACK.md open question 1. `s6c_similarity_rank_scores_eval` measured the
per-rank TF-IDF bonus corpus-wide on `separated_count`: NEGATIVE applied everywhere (best -25),
POSITIVE gated to `weak_separation` days (+315, 8,315 -> 8,630 at zscore/scale 3). `separated` is
a **coverage** criterion -- unique start paragraph on the date, extent <= 3 -- so a condition can
raise it by pushing placements apart while getting them wrong. This scores the same gated
condition for **correctness**, against the only reference that exists: the hand-annotated
`boundary_gold_sample` days.

The blocker named in that open question is real and bounds what this can say. Of the 50 gold days
only **12** are `weak_separation` days (3 of the 21 `review_code == S` days: 1626-01-08,
1628-04-04, 1630-03-03). The gate is defined to leave every other day at baseline, so on 38 of 50
gold days the gated condition *is* the baseline, bit for bit. Two consequences, both designed
around here rather than papered over:

* A whole-gold-subset accuracy figure is mostly unchanged rows and would dilute the effect toward
  zero. It is reported, but it is not the headline.
* The decisive statistic is **paired and restricted to rows that actually moved**: for each
  resolution whose start the gate relocated, did it move *toward* gold or *away* from it? That
  needs no large sample to be informative -- each moved row is its own before/after comparison --
  and it is the only cohort where coverage and correctness can disagree.

Scored with `separated_accuracy_eval`'s own `accuracy()` and `gold_start_paragraphs()`: exact
start-paragraph agreement and absolute displacement in **paragraphs**. No boundary-F1 at any
character or paragraph tolerance (docs/METRICS.md:187 demotes that family). `separated_count` is
reported beside the accuracy figures on the same rows, so the coverage claim and the correctness
claim can be read against each other rather than in separate runs.

Row order safety. The per-rank wiring assigns bonus row `i` to resolution `i`, so a row-order
mismatch would silently score the wrong resolution -- a risk the collapsed wiring never had.
Verified before writing this: `load_enriched_texts_by_date` (matrix rows) and `grouped_enriched`
both sort by `resolution_index`, and on all 50 gold days the gold day's own `enriched_ids` match
`grouped_enriched`'s order and length exactly. The run re-asserts the length half per day.

Ungated facet. The same run scores the condition applied to *every* gold day, including the
non-weak ones. That is track open question 3 ("why does it hurt the solid days?") answered from
the same predictions: the moved rows on non-weak days are where the corpus-wide -25 comes from.

Usage:
    uv run python -m scripts.s6c_gated_correctness_eval
    uv run python -m scripts.s6c_gated_correctness_eval --scale 1 2 3 --normalize zscore rownorm
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
    compute_similarity_matrix,
    extract_axis_texts,
    load_enriched_texts_by_date,
    predict,
    resolved_sessions,
    session_of,
)
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, overlap_enriched_id
from scripts.s4_resolution_concordance import resolution_paragraph_range
from scripts.s6c_gap_segmentation import RANK_NORMALIZATIONS, similarity_rank_scores
from scripts.s6c_similarity_rank_scores_eval import weak_separation_dates
from scripts.separated_accuracy_eval import (
    accuracy,
    gold_start_paragraphs,
    label_separation,
    uniform_start_paragraphs,
)

GOLD_DATASET = "boundary_gold_sample"
OUTPUT_DATASET = "s6c_gated_correctness_eval"
EMBEDDER_BACKEND = "tfidf"
BASELINE = "baseline"
KEY = ["enriched_date", "resolution_index"]


def placement_rows(
    date: str,
    prediction: dict[str, Any],
    k_e: int,
    gold_starts: list[int | None],
    uniform: list[int],
    review_code: str,
    weak: bool,
) -> list[dict[str, Any]]:
    """One row per resolution: the predicted range, gold's start, and the uniform null."""
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
                "review_code": review_code,
                "weak_separation_day": weak,
                "paragraph_start_index": start,
                "paragraph_end_index": end,
                "gold_start": gold_starts[index] if index < len(gold_starts) else None,
                "uniform_start": uniform[index] if index < len(uniform) else None,
            }
        )
    return rows


def score_rows(frame: pd.DataFrame) -> dict[str, Any]:
    """Coverage and correctness on the same rows.

    `separated` is computed over every row (it is a per-date property and resolution 0
    participates in the uniqueness test); accuracy holds out resolution 0, which both sides place
    at paragraph 0 by construction and which would hand every condition a free agreement.
    """
    if frame.empty:
        return {"attributed": 0, "separated_count": 0, "separated_share": None}
    labelled = label_separation(frame)
    separated = int(labelled["separated"].sum())
    scoreable = labelled.loc[labelled["resolution_index"] >= 1]
    return {
        "attributed": int(len(labelled)),
        "separated_count": separated,
        "separated_share": round(separated / len(labelled), 4),
        "loss_reasons": {
            reason: int(count) for reason, count in labelled["loss_reason"].value_counts().items()
        },
        "scoreable_rows": int(len(scoreable)),
        "gold_located_rows": int(scoreable["gold_start"].notna().sum()),
        "accuracy_vs_gold": accuracy(scoreable, "paragraph_start_index"),
        "uniform_null": accuracy(scoreable, "uniform_start"),
    }


def movement(baseline: pd.DataFrame, condition: pd.DataFrame) -> dict[str, Any]:
    """Paired before/after on the rows the condition actually relocated.

    The cohort that decides the open question: a coverage gain that comes from moving placements
    *away* from gold is spread, not alignment. Rows gold does not locate are counted as moved but
    cannot be adjudicated, and are reported separately rather than dropped silently.
    """
    merged = baseline.merge(condition, on=KEY, suffixes=("_base", "_cond"))
    if merged.empty:
        return {"paired_rows": 0, "moved_rows": 0}
    merged = merged.loc[merged["resolution_index"] >= 1]
    moved = merged.loc[merged["paragraph_start_index_base"] != merged["paragraph_start_index_cond"]]
    scored = moved.dropna(subset=["gold_start_base"])
    result: dict[str, Any] = {
        "paired_rows": int(len(merged)),
        "moved_rows": int(len(moved)),
        "moved_days": int(moved["enriched_date"].nunique()),
        "moved_rows_gold_unlocated": int(len(moved) - len(scored)),
        "adjudicable_rows": int(len(scored)),
    }
    if scored.empty:
        return result
    gold = scored["gold_start_base"].astype(int)
    before = (scored["paragraph_start_index_base"].astype(int) - gold).abs()
    after = (scored["paragraph_start_index_cond"].astype(int) - gold).abs()
    result.update(
        {
            "moved_toward_gold": int((after < before).sum()),
            "moved_away_from_gold": int((after > before).sum()),
            "moved_same_distance": int((after == before).sum()),
            "net_displacement_change": round(float((after - before).sum()), 3),
            "mean_abs_displacement_before": round(float(before.mean()), 3),
            "mean_abs_displacement_after": round(float(after.mean()), 3),
            "exact_hits_before": int((before == 0).sum()),
            "exact_hits_after": int((after == 0).sum()),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scale",
        type=float,
        nargs="+",
        default=[3.0],
        help="Bonus scales to sweep (default: 3.0, the corpus-wide gated optimum at +315).",
    )
    parser.add_argument(
        "--normalize",
        type=str,
        nargs="+",
        default=["zscore"],
        choices=list(RANK_NORMALIZATIONS),
        help="Bonus forms to sweep (default: zscore, the only form positive when gated).",
    )
    args = parser.parse_args()

    gold = load(GOLD_DATASET)
    codes = review_codes()
    weak_dates = weak_separation_dates()
    if not weak_dates:
        raise SystemExit("no weak_separation dates available -- the gate cannot be defined")

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

    variants = [(scale, normalize) for normalize in args.normalize for scale in args.scale]
    conditions = [BASELINE] + [f"rank@{scale:g}/{normalize}" for scale, normalize in variants]
    rows_by_condition: dict[str, list[dict[str, Any]]] = {name: [] for name in conditions}
    per_day: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)

    for day in sorted(gold["days"], key=lambda item: str(item["date"])):
        date = str(day["date"])
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis:
            skipped["no_axis"] += 1
            continue

        k_e = int(day["k_e"])
        enriched_ids = [overlap_enriched_id(enriched_id, date) for enriched_id in day["enriched_ids"]]
        if len(enriched_ids) != k_e:
            skipped["k_e_disagrees_with_enriched_ids"] += 1
            continue
        gold_starts = gold_start_paragraphs(day, k_e)
        uniform = uniform_start_paragraphs(len(axis), k_e)
        review_code = codes.get(date, "S")
        weak = date in weak_dates

        enriched_texts = enriched_texts_by_date.get(date, [])
        axis_texts = extract_axis_texts(axis)
        matrix: np.ndarray | None = None
        if enriched_texts and axis_texts:
            matrix = compute_similarity_matrix(enriched_texts, axis_texts, embedder)
        # Bonus row `i` is spent on resolution `i`; a shorter matrix would score the wrong rows.
        if matrix is not None and matrix.shape[0] != k_e:
            skipped["similarity_matrix_rows_disagree_with_k_e"] += 1
            matrix = None

        record: dict[str, Any] = {
            "record_type": "day",
            "date": date,
            "k_e": k_e,
            "paragraph_count": len(axis),
            "review_code": review_code,
            "weak_separation_day": weak,
            "gold_located_starts": sum(1 for start in gold_starts if start is not None),
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

            prediction = predict(date, enriched_ids, axis, lookup, idf_weights, resolution_scores=scores)
            rows = placement_rows(date, prediction, k_e, gold_starts, uniform, review_code, weak)
            if not rows:
                skipped[f"unusable_prediction_{name}"] += 1
                continue
            rows_by_condition[name].extend(rows)
            record[name] = {"starts": [row["paragraph_start_index"] for row in rows]}
        per_day.append(record)

    frames = {
        name: pd.DataFrame(rows) if rows else pd.DataFrame(columns=KEY)
        for name, rows in rows_by_condition.items()
    }
    baseline_frame = frames[BASELINE]
    if baseline_frame.empty:
        raise SystemExit("no scoreable gold days -- nothing to compare")

    gold_weak_dates = sorted(set(baseline_frame.loc[baseline_frame["weak_separation_day"], "enriched_date"]))
    results: dict[str, Any] = {}

    for name in conditions:
        if name == BASELINE:
            continue
        condition_frame = frames[name]
        if condition_frame.empty:
            results[name] = {"note": "no usable rows"}
            continue

        # The gate itself: the condition's placements on weak_separation days, the baseline's
        # everywhere else. A weak day the condition could not predict falls back to baseline,
        # which is what a gated production run would also do.
        covered = set(condition_frame["enriched_date"])
        gated_dates = {date for date in gold_weak_dates if date in covered}
        gated_frame = pd.concat(
            [
                condition_frame.loc[condition_frame["enriched_date"].isin(gated_dates)],
                baseline_frame.loc[~baseline_frame["enriched_date"].isin(gated_dates)],
            ],
            ignore_index=True,
        )

        weak_mask = baseline_frame["weak_separation_day"]
        s_mask = baseline_frame["review_code"] == "S"
        gated_weak = gated_frame.loc[gated_frame["weak_separation_day"]]
        gated_s = gated_frame.loc[gated_frame["review_code"] == "S"]

        results[name] = {
            "gated_days_applied": sorted(gated_dates),
            "gold_weak_separation_days": len(gold_weak_dates),
            # Headline: the days the gate acts on, gated vs baseline, coverage and correctness.
            "weak_gold_days": {
                "baseline": score_rows(baseline_frame.loc[weak_mask]),
                "gated": score_rows(gated_weak),
                "movement": movement(baseline_frame.loc[weak_mask], gated_weak),
            },
            # Diluted by construction (38/50 days are identical rows); reported, not headlined.
            "all_gold_days": {
                "baseline": score_rows(baseline_frame),
                "gated": score_rows(gated_frame),
                "movement": movement(baseline_frame, gated_frame),
            },
            "review_code_S_only": {
                "baseline": score_rows(baseline_frame.loc[s_mask]),
                "gated": score_rows(gated_s),
            },
            # Track open question 3: the condition applied everywhere, including solid days.
            "ungated_everywhere": {
                "condition": score_rows(condition_frame),
                "movement_all": movement(baseline_frame, condition_frame),
                "movement_non_weak_days": movement(
                    baseline_frame.loc[~weak_mask],
                    condition_frame.loc[~condition_frame["weak_separation_day"]],
                ),
            },
        }

    report = {
        "record_type": "report",
        "unit": "paragraph_stream",
        "question": (
            "plans/TFIDF_EMBEDDINGS_TRACK.md open question 1 -- is the weak_separation-gated "
            "+315 separated a correctness gain or only spread?"
        ),
        "metric": (
            "exact start-paragraph agreement and absolute paragraph displacement vs gold "
            "(separated_accuracy_eval.accuracy), beside separated_count on the same rows. No "
            "boundary-F1 at any tolerance (docs/METRICS.md:187)."
        ),
        "wiring": "segment_gap rank_scores (per-resolution), via similarity_rank_scores",
        "scales": list(args.scale),
        "normalizations": list(args.normalize),
        "gold_days_total": len(gold["days"]),
        "gold_days_scored": len(per_day),
        "gold_weak_separation_days": gold_weak_dates,
        "skipped": dict(skipped),
        "power_note": (
            f"The gate leaves non-weak days at baseline, so only {len(gold_weak_dates)} of "
            f"{len(per_day)} scored gold days can differ at all. Read the weak_gold_days cohort "
            "and the paired movement counts, not the all_gold_days figure, which is diluted by "
            "identical rows by construction."
        ),
        "subset_note": (
            "Gold-subset counts; NOT comparable to the corpus-wide 8,315 / 8,630 separated from "
            "s6c_similarity_rank_scores_eval. Compare conditions within this run only."
        ),
        "conditions": results,
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote S6c gated-correctness evaluation to {output}")
    print(
        f"  gold days scored={len(per_day)}/{len(gold['days'])}"
        f" weak_separation among them={len(gold_weak_dates)} {gold_weak_dates}"
    )
    if skipped:
        print(f"  skipped: {dict(skipped)}")
    for name in conditions:
        if name == BASELINE:
            continue
        scored = results.get(name, {})
        if "note" in scored:
            print(f"  {name}: {scored['note']}")
            continue
        for cohort in ("weak_gold_days", "all_gold_days"):
            base = scored[cohort]["baseline"]
            gate = scored[cohort]["gated"]
            move = scored[cohort]["movement"]
            print(f"  {name} [{cohort}]")
            print(
                f"      coverage : separated {base['separated_count']} -> {gate['separated_count']}"
                f" ({gate['separated_count'] - base['separated_count']:+d}) of {gate['attributed']}"
            )
            print(
                f"      correct  : exact {base['accuracy_vs_gold']['exact_agreement']} ->"
                f" {gate['accuracy_vs_gold']['exact_agreement']}"
                f" | meanDisp {base['accuracy_vs_gold']['mean_abs_displacement']} ->"
                f" {gate['accuracy_vs_gold']['mean_abs_displacement']}"
                f" (n={gate['accuracy_vs_gold']['n']})"
            )
            if move.get("moved_rows"):
                print(
                    f"      moved    : {move['moved_rows']} rows on {move['moved_days']} days,"
                    f" adjudicable {move.get('adjudicable_rows', 0)} ->"
                    f" toward gold {move.get('moved_toward_gold')},"
                    f" away {move.get('moved_away_from_gold')},"
                    f" same {move.get('moved_same_distance')}"
                    f" | net displacement {move.get('net_displacement_change')}"
                )
            else:
                print("      moved    : no rows relocated")
        ungated = scored["ungated_everywhere"]
        solid = ungated["movement_non_weak_days"]
        print(
            f"  {name} [ungated on non-weak gold days] moved={solid.get('moved_rows', 0)}"
            f" toward gold {solid.get('moved_toward_gold')}, away {solid.get('moved_away_from_gold')}"
            f" | net displacement {solid.get('net_displacement_change')}"
        )


if __name__ == "__main__":
    main()

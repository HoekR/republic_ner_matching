#!/usr/bin/env python3
"""Diagnose whether paragraph-level entity density separates gold bundled
(multi-resolution) paragraphs from clean single-resolution boundary paragraphs.

Background: boundary-level F1 for the S4 paragraph-axis baseline has been
stuck across sessions because many gold days have multiple distinct
resolution-boundary annotations collapsing onto the same paragraph -- the
paragraph the HTR text was split into actually contains more than one
resolution's worth of content (see docs/DECISIONS.md, 2026-09-18). This
script tests a candidate signal for that condition: paragraphs gold marks as
"bundled" (2+ boundary slots at the same paragraph_stream_index) should show
higher entity_annotation_count than paragraphs gold marks as a single, clean
resolution boundary.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Sequence

import numpy as np

from data_io import load, save_semi_structured

GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
REVIEW_DATASET = "boundary_gold_exception_review"
OUTPUT_DATASET = "s4_entity_density_split_diagnostic"
CONTENT_KINDS = {"cut", "start"}
DEGENERATE_UNIT = "out_of_range"
VERDICT_THRESHOLD = 0.65  # judgment call for this diagnostic, not a statistical standard


def review_codes() -> dict[str, str]:
    review = load(REVIEW_DATASET)
    return {
        str(row.date): str(row.review_code).strip()
        for row in review[["date", "review_code"]].dropna().itertuples(index=False)
        if str(row.review_code).strip()
    }


def content_boundary_indices(day: dict[str, Any]) -> list[int]:
    return [
        int(boundary["paragraph_stream_index"])
        for boundary in day.get("boundaries", [])
        if boundary.get("kind") in CONTENT_KINDS
        and boundary.get("paragraph_stream_index") is not None
        and boundary.get("unit") != DEGENERATE_UNIT
    ]


def classify_positions(indices: Sequence[int]) -> dict[int, int]:
    return dict(Counter(indices))


def label_axis_paragraphs(
    day_axis: list[dict[str, Any]], position_counts: dict[int, int], k_e: int, date: str
) -> list[dict[str, Any]]:
    rows = []
    for index, record in enumerate(day_axis):
        slot_count = position_counts.get(index, 0)
        if slot_count > 1:
            category = "bundled"
        elif slot_count == 1:
            category = "clean_single_boundary"
        else:
            category = "non_boundary"
        rows.append(
            {
                "date": date,
                "axis_id": record["axis_id"],
                "flat_id": record["flat_id"],
                "para_index": record["para_index"],
                "paragraph_stream_index": index,
                "entity_annotation_count": record["entity_annotation_count"],
                "gold_boundary_slot_count": slot_count,
                "category": category,
                "is_bundled": category == "bundled",
                "k_e": k_e,
            }
        )
    return rows


def summary_statistics(bundled_counts: Sequence[int], clean_counts: Sequence[int]) -> dict[str, Any]:
    bundled = np.asarray(bundled_counts, dtype=float)
    clean = np.asarray(clean_counts, dtype=float)

    wins = 0.0
    for b in bundled:
        wins += np.sum(clean < b) + 0.5 * np.sum(clean == b)
    common_language_effect_size = float(wins / (len(bundled) * len(clean))) if len(bundled) and len(clean) else 0.0

    clean_median = float(np.median(clean)) if len(clean) else 0.0
    clean_p75 = float(np.percentile(clean, 75)) if len(clean) else 0.0

    max_count = int(max([*bundled_counts, *clean_counts], default=0))
    best = {"threshold": 0, "tpr": 0.0, "fpr": 0.0, "youden_j": -1.0}
    for threshold in range(0, max_count + 1):
        tpr = float(np.mean(bundled >= threshold)) if len(bundled) else 0.0
        fpr = float(np.mean(clean >= threshold)) if len(clean) else 0.0
        youden_j = tpr - fpr
        if youden_j > best["youden_j"]:
            best = {"threshold": threshold, "tpr": tpr, "fpr": fpr, "youden_j": youden_j}

    return {
        "n_bundled": len(bundled_counts),
        "n_clean": len(clean_counts),
        "bundled_mean": float(np.mean(bundled)) if len(bundled) else 0.0,
        "bundled_median": float(np.median(bundled)) if len(bundled) else 0.0,
        "bundled_p25": float(np.percentile(bundled, 25)) if len(bundled) else 0.0,
        "bundled_p75": float(np.percentile(bundled, 75)) if len(bundled) else 0.0,
        "clean_mean": float(np.mean(clean)) if len(clean) else 0.0,
        "clean_median": clean_median,
        "clean_p25": float(np.percentile(clean, 25)) if len(clean) else 0.0,
        "clean_p75": clean_p75,
        "common_language_effect_size": common_language_effect_size,
        "fraction_bundled_above_clean_median": float(np.mean(bundled > clean_median)) if len(bundled) else 0.0,
        "fraction_bundled_above_clean_p75": float(np.mean(bundled >= clean_p75)) if len(bundled) else 0.0,
        "best_threshold": best,
    }


def main() -> None:
    gold = load(GOLD_DATASET)
    axis = load(AXIS_DATASET)
    codes = review_codes()

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        by_date[str(record["date"])].append(record)

    eligible = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S" and int(day["k_e"]) > 1]

    rows: list[dict[str, Any]] = []
    excluded_out_of_range = 0
    days_used = 0

    for day in eligible:
        date = str(day["date"])
        raw_indices = [
            int(boundary["paragraph_stream_index"])
            for boundary in day.get("boundaries", [])
            if boundary.get("kind") in CONTENT_KINDS and boundary.get("paragraph_stream_index") is not None
        ]
        content_indices = content_boundary_indices(day)
        excluded_out_of_range += len(raw_indices) - len(content_indices)
        day_axis = by_date.get(date, [])
        if not content_indices or not day_axis:
            continue
        days_used += 1
        position_counts = classify_positions(content_indices)
        rows.extend(label_axis_paragraphs(day_axis, position_counts, int(day["k_e"]), date))

    bundled_counts = [row["entity_annotation_count"] for row in rows if row["category"] == "bundled"]
    clean_counts = [row["entity_annotation_count"] for row in rows if row["category"] == "clean_single_boundary"]
    non_boundary_count = sum(1 for row in rows if row["category"] == "non_boundary")

    stats = summary_statistics(bundled_counts, clean_counts)
    output = save_semi_structured(rows, logical_name=OUTPUT_DATASET, script=__file__)

    cle = stats["common_language_effect_size"]
    verdict = (
        "separates well enough to pursue a split-point step"
        if cle > VERDICT_THRESHOLD
        else "signal too weak on this sample to justify a split-point step without the "
        "fuzzy-surface-form augmentation follow-up"
    )

    print(f"Wrote {len(rows)} paragraph rows to {output}")
    print(f"eligible days used={days_used}; bundled={stats['n_bundled']}; clean={stats['n_clean']}; non_boundary={non_boundary_count}")
    print(
        f"excluded out_of_range boundary slots: {excluded_out_of_range} "
        "(gold's fallback marker for a cut point with no real paragraph to land on; "
        "not counted as evidence of a genuinely entity-dense bundled paragraph -- "
        "see docs/DECISIONS.md 2026-09-18 for the unfiltered 41/179 figure this refines)"
    )
    print(
        f"bundled: mean={stats['bundled_mean']:.2f} median={stats['bundled_median']} "
        f"p25={stats['bundled_p25']} p75={stats['bundled_p75']}"
    )
    print(
        f"clean:   mean={stats['clean_mean']:.2f} median={stats['clean_median']} "
        f"p25={stats['clean_p25']} p75={stats['clean_p75']}"
    )
    print(f"common_language_effect_size={cle:.3f}")
    print(f"fraction_bundled_above_clean_median={stats['fraction_bundled_above_clean_median']:.3f}")
    print(f"fraction_bundled_above_clean_p75={stats['fraction_bundled_above_clean_p75']:.3f}")
    print(f"best_threshold={stats['best_threshold']}")
    print(
        f"\nHeadline: bundled paragraphs have median entity_annotation_count {stats['bundled_median']} "
        f"vs clean {stats['clean_median']} (common-language effect size {cle:.2f}; "
        f"{stats['fraction_bundled_above_clean_p75']:.0%} of bundled paragraphs at/above the clean group's "
        f"75th percentile). Verdict (threshold={VERDICT_THRESHOLD}, a judgment call for this diagnostic, "
        f"not a statistical standard): {verdict}."
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Reconciliation diagnostic: does the stored tier1_anchor set match production's own anchors?

`s6b_known_point_ledger.py` (and everything chained on it -- `s6b_anchor_harvest.py` Group A,
`s6d_entity_mention_gap_placement.py`'s Step 3 experiment) treats `alignment_1626_1630.parquet`'s
`confidence_tier == "tier1_anchor"` rows as the known-point backbone. Those rows are produced by
`build_alignment_new.py`'s `align_session_milestone_tiered`, scored against a **flat-resolution**
granularity Excel-overlap lookup (`build_overlap_lookups`, keyed by `(volgnr, flat_id)`).

Production's actual placement path (`s4_corpus_paragraph_predictions.py` / `s4_paragraph_axis_
baseline.py`) never reads that table. It calls the plain `align_session` fresh, every run, against
a **paragraph-axis** granularity lookup (`build_axis_overlap`, keyed by `(volgnr, axis_id)`), and
its notion of "anchor" is just any NW diagonal cell with `entity_match_score > 0` -- no `tier1_anchor`
concept exists at runtime at all.

This script does not change either path. It recomputes production's own paragraph-level anchor
for every enriched resolution on the exact day population `s6b_known_point_ledger.py` uses
(same-calendar-day axis, `session_date_status_1626_1630`'s `k_e`), and compares it against the
stored tier1_anchor's flat resolution mapped onto the same day's axis, per enriched index. This
answers: when the ledger says "resolution i is pinned by a tier-1 anchor", does production's own
alignment agree that resolution i has evidence-backed placement, and at the same paragraph?

Usage:
    uv run python -m scripts.anchor_set_reconciliation
    uv run python -m scripts.anchor_set_reconciliation --start 1626-01-01 --end 1626-12-31
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, resolve, save_semi_structured
from scripts.s4_corpus_paragraph_predictions import grouped_enriched
from scripts.s4_paragraph_axis_baseline import build_axis_overlap
from scripts.s6b_known_point_ledger import enriched_index

ALIGNMENT_DATASET = "alignment_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
LEDGER_DATASET = "session_date_status_1626_1630"
OVERLAP_DATASETS = ("place_overlap_1626_1630", "org_overlap_1626_1630", "per_overlap_1626_1630")
OUTPUT_DATASET = "anchor_set_reconciliation"
TIER1 = "tier1_anchor"
DEFAULT_START = "1626-01-01"
DEFAULT_END = "1630-12-31"


def flat_id_positions(axis: list[dict[str, Any]]) -> dict[str, int]:
    """First paragraph-stream position (0-based) of each flat resolution on this day's axis."""
    positions: dict[str, int] = {}
    for position, record in enumerate(axis):
        positions.setdefault(str(record["flat_id"]), position)
    return positions


def production_anchor_positions(
    enriched_ids: list[str],
    axis_ids: list[str],
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
) -> dict[int, int]:
    """enriched-list-index -> matched axis-index, restricted to evidence-backed (anchor) pairs.

    Mirrors `align_session`'s own `has_anchor` gate (`entity_match_score > 0`) rather than
    re-deriving a separate notion of anchor, so this is exactly what production treats as
    anchored, not a new definition.
    """
    alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
    anchored: dict[int, int] = {}
    for i, j in alignments:
        if i is None or j is None:
            continue
        shared = lookup.get((enriched_ids[i], axis_ids[j]), set())
        if shared:
            anchored[i] = j
    return anchored


def classify(
    resolution_positions: dict[int, int],
    paragraph_positions: dict[int, int],
) -> list[dict[str, Any]]:
    """Per enriched index appearing in either anchor set, the agreement class and distance."""
    rows = []
    for index in sorted(set(resolution_positions) | set(paragraph_positions)):
        r_pos = resolution_positions.get(index)
        p_pos = paragraph_positions.get(index)
        if r_pos is not None and p_pos is not None:
            rows.append({"enriched_index": index, "status": "both", "distance": abs(r_pos - p_pos)})
        elif r_pos is not None:
            rows.append({"enriched_index": index, "status": "resolution_only", "distance": None})
        else:
            rows.append({"enriched_index": index, "status": "paragraph_only", "distance": None})
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["status"] for row in rows)
    both = [row["distance"] for row in rows if row["status"] == "both"]
    total = len(rows)
    return {
        "total_either": total,
        "both": counts["both"],
        "resolution_only": counts["resolution_only"],
        "paragraph_only": counts["paragraph_only"],
        "agreement_rate": counts["both"] / total if total else 0.0,
        "exact_position_share_of_both": sum(1 for d in both if d == 0) / len(both) if both else 0.0,
        "mean_distance_of_both": sum(both) / len(both) if both else 0.0,
        "median_distance_of_both": sorted(both)[len(both) // 2] if both else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile stored tier1_anchor against production's own paragraph-level anchors.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    args = parser.parse_args()

    alignment = load(ALIGNMENT_DATASET)
    alignment = alignment[
        (alignment["date"] >= args.start)
        & (alignment["date"] <= args.end)
        & (alignment["confidence_tier"] == TIER1)
    ]
    tier1_flat_by_date: dict[str, dict[int, str]] = defaultdict(dict)
    for row in alignment[["enriched_id", "flat_id", "date"]].itertuples(index=False):
        index = enriched_index(row.enriched_id)
        if index is not None:
            tier1_flat_by_date[str(row.date)][index] = str(row.flat_id)

    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        date = str(record["date"])
        if args.start <= date <= args.end:
            axis_by_date[date].append(record)

    ledger = load(LEDGER_DATASET)
    ledger = ledger[(ledger["enriched_date"] >= args.start) & (ledger["enriched_date"] <= args.end)]
    dates = sorted(str(d) for d in ledger["enriched_date"].unique())

    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [overlap.rename(columns={"naam": "name"}) if "name" not in overlap and "naam" in overlap else overlap for overlap in overlaps]
    combined = pd.concat(overlaps, ignore_index=True)
    idf_weights = calculate_idf_weights(combined)
    enriched_by_date = grouped_enriched()

    per_day: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    for date in dates:
        axis = axis_by_date.get(date)
        enriched_ids = enriched_by_date.get(date)
        tier1_flat = tier1_flat_by_date.get(date, {})
        if not axis or not enriched_ids:
            continue

        axis_ids = [record["axis_id"] for record in axis]
        lookup = build_axis_overlap(axis, combined)
        positions = flat_id_positions(axis)

        resolution_positions = {
            index: positions[flat_id]
            for index, flat_id in tier1_flat.items()
            if flat_id in positions
        }
        paragraph_positions = production_anchor_positions(enriched_ids, axis_ids, lookup, idf_weights)

        rows = classify(resolution_positions, paragraph_positions)
        if not rows:
            continue
        for row in rows:
            row["date"] = date
        all_rows.extend(rows)
        per_day.append({"date": date, **summarize(rows)})

    corpus_summary = summarize(all_rows)
    output = save_semi_structured(
        [{"scope": "corpus", **corpus_summary}, *per_day],
        logical_name=OUTPUT_DATASET,
        script=__file__,
    )
    print(f"Wrote {len(per_day)} day rows + 1 corpus summary to {output}")
    print(f"Corpus summary: {corpus_summary}")


if __name__ == "__main__":
    main()

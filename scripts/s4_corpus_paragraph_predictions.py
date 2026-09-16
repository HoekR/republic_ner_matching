#!/usr/bin/env python3
"""Run S4 entity-NW interpolation across all 1626-1630 calendar days.

This runner is separate from the 50-day boundary-gold benchmark. It emits
corpus predictions or explicit abstentions and never reads review labels.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, resolve, save_semi_structured
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, interpolate_positions, overlap_enriched_id


AXIS_DATASET = "paragraph_axis_1626_1630"
ENRICHED_DATASET = "enriched_resolutions_1626_1630"
OUTPUT_DATASET = "s4_corpus_paragraph_predictions"
OVERLAP_DATASETS = ("place_overlap_1626_1630", "org_overlap_1626_1630", "per_overlap_1626_1630")


def enriched_key(item: dict[str, Any], date: str) -> str | None:
    value = item.get("volgnr")
    if value is None or not str(value).strip():
        index = item.get("resolution_index")
        if index is None:
            return None
        value = f"{date}_{int(index)}"
    return overlap_enriched_id(str(value).strip(), date)


def grouped_enriched() -> dict[str, list[str]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in load(ENRICHED_DATASET):
        date = str(item.get("date", ""))[:10]
        if "1626-01-01" <= date <= "1630-12-31":
            by_date[date].append(item)
    grouped: dict[str, list[str]] = {}
    for date, items in by_date.items():
        items.sort(key=lambda item: item.get("resolution_index", 0))
        keys = [enriched_key(item, date) for item in items]
        if all(keys):
            grouped[date] = [str(key) for key in keys]
    return grouped


def predict(
    date: str,
    enriched_ids: list[str],
    axis: list[dict[str, Any]],
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
) -> dict[str, Any]:
    base = {"date": date, "k_e": len(enriched_ids), "paragraph_count": len(axis), "unit": "paragraph_stream"}
    if not axis:
        return {**base, "status": "abstained", "reason": "missing_htr", "boundaries": []}
    axis_ids = [record["axis_id"] for record in axis]
    alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
    positions = interpolate_positions(len(enriched_ids), len(axis_ids), alignments)
    if positions is None:
        return {**base, "status": "abstained", "reason": "insufficient_entity_anchors", "boundaries": []}
    return {
        **base,
        "status": "predicted",
        "reason": None,
        "boundaries": [
            {"paragraph_stream_index": position, "char_offset": 0, "kind": "cut", "source": "entity_nw_interpolation"}
            for position in positions
        ],
    }


def main() -> None:
    axis = load(AXIS_DATASET)
    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        axis_by_date[str(record["date"])].append(record)
    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [overlap.rename(columns={"naam": "name"}) if "name" not in overlap and "naam" in overlap else overlap for overlap in overlaps]
    combined = pd.concat(overlaps, ignore_index=True)
    lookup = build_axis_overlap(axis, combined)
    idf_weights = calculate_idf_weights(combined)
    predictions = [
        predict(date, enriched_ids, axis_by_date[date], lookup, idf_weights)
        for date, enriched_ids in sorted(grouped_enriched().items())
    ]
    output = save_semi_structured(predictions, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(predictions)} corpus-day predictions to {output}")
    print(f"Status counts: {dict(Counter(item['status'] for item in predictions))}")
    print(f"Abstentions: {dict(Counter(item['reason'] for item in predictions if item['status'] == 'abstained'))}")


if __name__ == "__main__":
    main()
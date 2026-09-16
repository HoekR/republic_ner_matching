#!/usr/bin/env python3
"""Build the complete flat-paragraph axis for boundary-gold session days.

Every paragraph in the annotated flat stream is retained. NER annotation
references are attached only when their ``tag_text`` identifies one paragraph
uniquely within the recorded flat resolution; unresolved references are
reported rather than counted as entity-free paragraphs.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from build_alignment_new import as_text, sort_key_res_id
from data_io import load, save_semi_structured


GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
FULL_AXIS_DATASET = "paragraph_axis_1626_1630"
ANNOTATION_DATASETS = ("loc_annotations", "org_annotations", "per_annotations")
PERIOD_START = "1626-01-01"
PERIOD_END = "1630-12-31"


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", as_text(value)).strip().casefold()


def parse_paragraphs(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list):
        value = [value]
    return [as_text(paragraph).strip() for paragraph in value if as_text(paragraph).strip()]


def match_annotation_to_paragraph(tag_text: str, paragraphs: list[str]) -> int | None:
    """Return a unique local paragraph index containing the annotation text."""
    needle = normalized_text(tag_text)
    if not needle:
        return None
    matches = [index for index, paragraph in enumerate(paragraphs) if needle in normalized_text(paragraph)]
    return matches[0] if len(matches) == 1 else None


def selected_resolutions(resolutions: pd.DataFrame, scope: str, gold: dict[str, Any]) -> pd.DataFrame:
    if scope == "gold":
        flat_ids = {flat_id for day in gold["days"] for flat_id in day["flat_ids"]}
        return resolutions.loc[resolutions["id"].astype(str).isin(flat_ids), ["id", "date", "paragraph_texts"]].copy()
    dates = resolutions["date"].astype(str).str[:10]
    return resolutions.loc[dates.between(PERIOD_START, PERIOD_END), ["id", "date", "paragraph_texts"]].copy()


def build_axis(selected: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    paragraph_by_flat = {
        str(row.id): parse_paragraphs(row.paragraph_texts)
        for row in selected.itertuples(index=False)
    }

    records: list[dict[str, Any]] = []
    ordered = sorted(selected.itertuples(index=False), key=lambda row: (str(row.date)[:10], sort_key_res_id(str(row.id))))
    for row in ordered:
        flat_id = str(row.id)
        for para_index, text in enumerate(paragraph_by_flat[flat_id]):
            records.append(
                {
                    "date": str(row.date)[:10],
                    "flat_id": flat_id,
                    "para_index": para_index,
                    "axis_id": f"{flat_id}#p{para_index}",
                    "text": text,
                    "entity_annotation_count": 0,
                    "entity_source_paragraph_ids": [],
                }
            )
    return records, paragraph_by_flat


def attach_entities(records: list[dict[str, Any]], paragraph_by_flat: dict[str, list[str]]) -> Counter[str]:
    by_flat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_flat[record["flat_id"]].append(record)
    counts: Counter[str] = Counter()

    for dataset in ANNOTATION_DATASETS:
        for annotation in load(dataset):
            reference = annotation.get("reference") or {}
            flat_id = str(reference.get("resolution_id") or "").strip()
            if flat_id not in by_flat:
                continue
            para_index = match_annotation_to_paragraph(reference.get("tag_text", ""), paragraph_by_flat[flat_id])
            if para_index is None:
                counts["unresolved"] += 1
                continue
            record = by_flat[flat_id][para_index]
            record["entity_annotation_count"] += 1
            paragraph_id = str(reference.get("paragraph_id") or "").strip()
            if paragraph_id and paragraph_id not in record["entity_source_paragraph_ids"]:
                record["entity_source_paragraph_ids"].append(paragraph_id)
            counts["resolved"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a flat paragraph axis with entity attachment coverage.")
    parser.add_argument("--scope", choices=("gold", "full"), default="gold")
    args = parser.parse_args()
    gold = load(GOLD_DATASET)
    resolutions = load("resolutions_flat")
    selected = selected_resolutions(resolutions, args.scope, gold)
    records, paragraph_by_flat = build_axis(selected)
    attachment_counts = attach_entities(records, paragraph_by_flat)
    dataset = FULL_AXIS_DATASET if args.scope == "full" else AXIS_DATASET
    output = save_semi_structured(records, logical_name=dataset, script=__file__)
    with_entities = sum(record["entity_annotation_count"] > 0 for record in records)
    print(f"Wrote {len(records)} {args.scope} paragraphs to {output}")
    print(f"Entity-bearing paragraphs: {with_entities} / {len(records)}")
    print(f"Annotation attachments: resolved={attachment_counts['resolved']}, unresolved={attachment_counts['unresolved']}")


if __name__ == "__main__":
    main()
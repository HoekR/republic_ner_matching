#!/usr/bin/env python3
"""Harvest pin-validated person name aliases from confirmed manual corrections.

Only ``action: confirmed`` imports and ``source: manual_correction`` pins are used.

Usage:
    uv run python build_person_aliases_from_pins.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from build_alignment_new import (
    ENRICHED_FILE,
    OUTPUT_DIR,
    PER_OVERLAP_FILE,
    load_json,
    load_persons_info_lookup,
    enriched_volgnr,
    enriched_text,
)

WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_token(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(value or "").strip().lower())


def load_confirmed_pins(output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    state_path = output_dir / "alignment_state.json"
    corrective_path = output_dir / "corrective_ground_truth.json"

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for pin in state.get("curated_pins", []):
            if pin.get("source") == "manual_correction":
                records.append(pin)

    if corrective_path.exists():
        for item in json.loads(corrective_path.read_text(encoding="utf-8")):
            if item.get("action") == "confirmed":
                records.append(
                    {
                        "enriched_id": item.get("enriched_id"),
                        "paragraph_id": item.get("corrected_paragraph_id"),
                        "resolution_id": item.get("corrected_resolution_id"),
                        "session_id": item.get("session_id"),
                        "source": "manual_correction",
                    }
                )

    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        enriched_id = str(record.get("enriched_id", ""))
        paragraph_id = str(record.get("paragraph_id") or record.get("corrected_paragraph_id") or "")
        if not enriched_id or not paragraph_id:
            continue
        key = (enriched_id, paragraph_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def build_alias_table(
    pins: list[dict[str, Any]],
    enriched_all: list[dict[str, Any]],
    persons_info: dict[str, dict[str, str]],
    per_overlap_df: pd.DataFrame,
) -> dict[str, Any]:
    enriched_by_id = {enriched_volgnr(item) or "": item for item in enriched_all}
    overlap_by_pair: dict[tuple[str, str], pd.DataFrame] = {}
    if not per_overlap_df.empty:
        for (volgnr, paragraph_id), group in per_overlap_df.groupby(
            [per_overlap_df["volgnr"].astype(str), per_overlap_df["paragraph_id"].astype(str)]
        ):
            overlap_by_pair[(volgnr, paragraph_id)] = group

    aliases: dict[str, dict[str, Any]] = {}
    pin_records: list[dict[str, Any]] = []

    for pin in pins:
        enriched_id = str(pin.get("enriched_id", ""))
        paragraph_id = str(pin.get("paragraph_id", ""))
        enriched = enriched_by_id.get(enriched_id, {})
        person_ids = [str(pid) for pid in (enriched.get("persons") or []) if pid]
        overlap_rows = overlap_by_pair.get((enriched_id, paragraph_id))
        flat_text = enriched_text(enriched)[:2000].lower()

        for person_id in person_ids:
            canonical = persons_info.get(person_id, {}).get("canonical_name", person_id)
            entry = aliases.setdefault(
                person_id,
                {
                    "person_id": person_id,
                    "canonical_name": canonical,
                    "surface_aliases": set(),
                    "per_tag_texts": set(),
                    "pin_count": 0,
                },
            )
            entry["pin_count"] += 1
            if overlap_rows is not None and not overlap_rows.empty:
                person_rows = overlap_rows[overlap_rows["person_id"].astype(str) == person_id]
                for _, row in person_rows.iterrows():
                    surface = str(row.get("surface_name", "")).strip()
                    tag_text = str(row.get("tag_text", "")).strip()
                    if surface:
                        entry["surface_aliases"].add(surface)
                    if tag_text:
                        entry["per_tag_texts"].add(tag_text)
            for token in re.findall(r"[a-zà-ÿ]{4,}", flat_text):
                if canonical and normalize_token(token) in normalize_token(canonical):
                    entry["surface_aliases"].add(token)

        pin_records.append(
            {
                "enriched_id": enriched_id,
                "paragraph_id": paragraph_id,
                "resolution_id": pin.get("resolution_id"),
                "person_ids": person_ids,
            }
        )

    serializable_aliases = []
    for person_id, entry in sorted(aliases.items(), key=lambda item: item[0]):
        serializable_aliases.append(
            {
                "person_id": person_id,
                "canonical_name": entry["canonical_name"],
                "surface_aliases": sorted(entry["surface_aliases"]),
                "per_tag_texts": sorted(entry["per_tag_texts"]),
                "pin_count": entry["pin_count"],
            }
        )

    return {
        "alias_count": len(serializable_aliases),
        "pin_link_count": len(pin_records),
        "aliases": serializable_aliases,
        "pins": pin_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build person alias table from confirmed pins.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Alias JSON path (default: data/derived/person_aliases_from_pins.json)",
    )
    args = parser.parse_args()

    output_path = args.output or (args.output_dir / "person_aliases_from_pins.json")
    pins = load_confirmed_pins(args.output_dir)
    enriched_all = load_json(ENRICHED_FILE)
    persons_info = load_persons_info_lookup()
    per_overlap_df = pd.read_excel(PER_OVERLAP_FILE) if PER_OVERLAP_FILE.exists() else pd.DataFrame()

    payload = build_alias_table(pins, enriched_all, persons_info, per_overlap_df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✓ Person aliases: {output_path}")
    print(f"  Pins used: {payload['pin_link_count']}; persons with aliases: {payload['alias_count']}")


if __name__ == "__main__":
    main()

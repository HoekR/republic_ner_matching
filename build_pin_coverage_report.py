#!/usr/bin/env python3
"""Build year × session pin coverage grid for systematic gap-filling.

Usage:
    uv run python build_pin_coverage_report.py
    uv run python build_pin_coverage_report.py --output-dir output
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from analyze_sequence_entity_overlap import parse_paragraph_position
from build_alignment_new import (
    ENRICHED_FILE,
    ORG_OVERLAP_FILE,
    OUTPUT_DIR,
    PER_OVERLAP_FILE,
    PLACE_OVERLAP_FILE,
    enriched_volgnr,
    extract_session_id,
    load_json,
    score_typed_overlap,
)

INVENTORY_NUM_PATTERN = re.compile(r"session-\d+-num-(\d+)-")
YEAR_FROM_ENRICHED = re.compile(r"^(\d{4})-")


def calendar_year_from_enriched_id(enriched_id: str) -> int | None:
    match = YEAR_FROM_ENRICHED.match(str(enriched_id))
    return int(match.group(1)) if match else None


def inventory_num_from_paragraph(paragraph_id: str) -> int | None:
    match = INVENTORY_NUM_PATTERN.search(str(paragraph_id))
    return int(match.group(1)) if match else None


def build_coverage_grid(
    state: dict[str, Any],
    alignments: list[dict[str, Any]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    enriched_all: list[dict[str, Any]],
    year_min: int = 1626,
    year_max: int = 1630,
) -> dict[str, Any]:
    from build_alignment_new import build_overlap_lookups, calculate_idf_weights

    place_lookup, org_lookup, person_lookup, _ = build_overlap_lookups(
        places_df,
        orgs_df,
        paragraph_to_resolution,
        persons_df if not persons_df.empty else None,
    )
    overlap_frames = [
        places_df[["volgnr", "paragraph_id", "name"]],
        orgs_df[["volgnr", "paragraph_id", "name"]],
    ]
    if not persons_df.empty:
        overlap_frames.append(persons_df[["volgnr", "paragraph_id", "name"]])
    idf_weights = calculate_idf_weights(pd.concat(overlap_frames, ignore_index=True))

    pin_counts: dict[tuple[int, str], int] = defaultdict(int)
    alignment_counts: dict[tuple[int, str], int] = defaultdict(int)
    manual_pin_enriched: set[str] = set()

    for pin in state.get("curated_pins", []):
        enriched_id = str(pin.get("enriched_id", ""))
        session_id = str(pin.get("session_id") or extract_session_id(str(pin.get("paragraph_id", ""))) or "")
        year = calendar_year_from_enriched_id(enriched_id)
        if year and session_id and year_min <= year <= year_max:
            pin_counts[(year, session_id)] += 1
        if pin.get("source") == "manual_correction":
            manual_pin_enriched.add(enriched_id)

    for alignment in alignments:
        enriched_id = str(alignment.get("enriched_id", ""))
        session_id = str(alignment.get("session_id", ""))
        year = calendar_year_from_enriched_id(enriched_id)
        if year and session_id and year_min <= year <= year_max:
            alignment_counts[(year, session_id)] += 1

    sessions = sorted(
        {
            str(item.get("session_id", ""))
            for item in alignments
            if item.get("session_id")
        }
        | {session for _, session in pin_counts}
    )
    years = list(range(year_min, year_max + 1))

    cells: list[dict[str, Any]] = []
    gap_cells: list[dict[str, Any]] = []
    for year in years:
        for session_id in sessions:
            key = (year, session_id)
            cell = {
                "year": year,
                "session_id": session_id,
                "pin_count": pin_counts.get(key, 0),
                "manual_pin_count": sum(
                    1
                    for pin in state.get("curated_pins", [])
                    if pin.get("source") == "manual_correction"
                    and calendar_year_from_enriched_id(str(pin.get("enriched_id", ""))) == year
                    and str(pin.get("session_id", "")) == session_id
                ),
                "alignment_count": alignment_counts.get(key, 0),
                "has_pin": pin_counts.get(key, 0) > 0,
            }
            cells.append(cell)
            if cell["pin_count"] == 0:
                gap_cells.append(cell)

    enriched_by_id = {enriched_volgnr(item) or "": item for item in enriched_all}
    candidates: list[dict[str, Any]] = []
    confirmed_enriched = manual_pin_enriched

    for cell in gap_cells:
        year = cell["year"]
        session_id = cell["session_id"]
        for enriched_id, enriched in enriched_by_id.items():
            if not enriched_id or enriched_id in confirmed_enriched:
                continue
            if calendar_year_from_enriched_id(enriched_id) != year:
                continue
            day_places = places_df[places_df["volgnr"].astype(str) == enriched_id]
            if day_places.empty:
                continue
            best_score = 0.0
            best_resolution = ""
            for paragraph_id in day_places["paragraph_id"].astype(str):
                resolution_id = paragraph_to_resolution.get(paragraph_id)
                if not resolution_id or extract_session_id(resolution_id) != session_id:
                    continue
                anchor_score, person_score, combined = score_typed_overlap(
                    enriched_id,
                    resolution_id,
                    place_lookup,
                    org_lookup,
                    person_lookup,
                    idf_weights,
                )
                if combined > best_score:
                    best_score = combined
                    best_resolution = resolution_id
            if best_score <= 0:
                continue
            person_count = len(enriched.get("persons") or [])
            candidates.append(
                {
                    "year": year,
                    "session_id": session_id,
                    "enriched_id": enriched_id,
                    "enriched_date": str(enriched.get("date", ""))[:10],
                    "overlap_score": round(best_score, 3),
                    "best_resolution_id": best_resolution or None,
                    "person_count": person_count,
                    "rank_key": (best_score, person_count > 0, -len(str(enriched.get("text", "")))),
                }
            )

    ranked_by_gap: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        ranked_by_gap[(candidate["year"], candidate["session_id"])].append(candidate)
    placement_queue: list[dict[str, Any]] = []
    for gap in gap_cells:
        options = ranked_by_gap.get((gap["year"], gap["session_id"]), [])
        options.sort(key=lambda item: item["rank_key"], reverse=True)
        if not options:
            continue
        top = options[0]
        placement_queue.append(
            {
                "task_id": f"pin-gap-{gap['year']}-{gap['session_id']}",
                "year": gap["year"],
                "session_id": gap["session_id"],
                "enriched_id": top["enriched_id"],
                "enriched_date": top["enriched_date"],
                "overlap_score": top["overlap_score"],
                "hint_resolution_id": top["best_resolution_id"],
                "reason": "pin_placement_gap",
                "candidate_count": len(options),
            }
        )

    return {
        "years": years,
        "sessions": sessions,
        "cells": cells,
        "gap_cells": gap_cells,
        "placement_queue": placement_queue,
        "summary": {
            "total_cells": len(cells),
            "cells_with_pins": sum(1 for cell in cells if cell["has_pin"]),
            "gap_cells": len(gap_cells),
            "placement_tasks": len(placement_queue),
            "manual_pins": len(manual_pin_enriched),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build pin coverage year×session grid.")
    parser.add_argument("--state", type=Path, default=OUTPUT_DIR / "alignment_state.json")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--year-min", type=int, default=1626)
    parser.add_argument("--year-max", type=int, default=1630)
    args = parser.parse_args()

    if not args.state.exists():
        raise FileNotFoundError(f"Missing alignment state: {args.state}")

    from build_alignment_new import (
        LOC_ANNOTATIONS_FILE,
        ORG_ANNOTATIONS_FILE,
        build_paragraph_to_resolution_map,
    )

    state = json.loads(args.state.read_text(encoding="utf-8"))
    enriched_all = load_json(ENRICHED_FILE)
    places_df = pd.read_excel(PLACE_OVERLAP_FILE)
    orgs_df = pd.read_excel(ORG_OVERLAP_FILE)
    if "naam" in orgs_df.columns and "name" not in orgs_df.columns:
        orgs_df = orgs_df.rename(columns={"naam": "name"})
    persons_df = pd.read_excel(PER_OVERLAP_FILE) if PER_OVERLAP_FILE.exists() else pd.DataFrame()

    paragraph_ids = {
        str(pid).strip()
        for pid in pd.concat([places_df["paragraph_id"], orgs_df["paragraph_id"]]).dropna().astype(str)
        if str(pid).strip()
    }
    if not persons_df.empty:
        paragraph_ids.update(persons_df["paragraph_id"].dropna().astype(str))
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )

    report = build_coverage_grid(
        state,
        state.get("alignments", []),
        places_df,
        orgs_df,
        persons_df,
        paragraph_to_resolution,
        enriched_all,
        year_min=args.year_min,
        year_max=args.year_max,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "pin_coverage_report.json"
    queue_path = args.output_dir / "pin_placement_queue.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    queue_path.write_text(
        json.dumps(report["placement_queue"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = report["summary"]
    print(f"✓ Pin coverage report: {json_path}")
    print(f"✓ Pin placement queue: {queue_path} ({summary['placement_tasks']} tasks)")
    print(
        f"  Cells with pins: {summary['cells_with_pins']}/{summary['total_cells']}; "
        f"gaps: {summary['gap_cells']}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Quantify enriched↔flat calendar-date agreement on verified and entity bridges.

Use this to confirm (or refute) the observation that manually verified resolutions
usually share the same editorial and HTR calendar date before widening overlap
windows in M8.

Usage:
    uv run python analyze_resolution_date_agreement.py
    uv run python analyze_resolution_date_agreement.py --output output/date_agreement_report.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from build_alignment_new import (
    ENRICHED_FILE,
    OUTPUT_DIR,
    PLACE_OVERLAP_FILE,
    RESOLUTIONS_FILE,
    build_paragraph_to_resolution_map,
    paragraph_mapping_annotation_files,
    load_json,
    resolve_data_file,
)
from build_windowed_overlap import (
    INSTELLING_INFO_FILE,
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    attach_flat_dates,
    build_enriched_places,
    flatten_loc_annotations,
    index_flat_rows_by_date,
    load_institution_names,
    period_days,
    period_diff_days,
    windowed_place_overlap,
)
from build_alignment_new import LOC_ENTITIES_FILE, ORG_ENTITIES_FILE, load_entity_names

ALIGNMENT_STATE_FILE = OUTPUT_DIR / "alignment_state.json"
CORRECTION_SUMMARY_FILE = OUTPUT_DIR / "sequence_correction_summary.json"
GROUND_TRUTH_CANDIDATES = [
    OUTPUT_DIR / "ground_truth_stratified_matches.json",
    Path("output/ground_truth_stratified_matches.json"),
]


def resolve_optional_file(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def collect_paragraph_ids(
    state: dict[str, Any],
    correction_path: Path | None,
) -> set[str]:
    paragraph_ids: set[str] = set()
    for pin in state.get("curated_pins", []):
        if pin.get("paragraph_id"):
            paragraph_ids.add(str(pin["paragraph_id"]))
    for row in state.get("alignments", []):
        if row.get("paragraph_id"):
            paragraph_ids.add(str(row["paragraph_id"]))
    if correction_path and correction_path.exists():
        payload = load_json(correction_path)
        corrections = payload.get("corrections", {})
        if isinstance(corrections, dict):
            correction_items = corrections.values()
        else:
            correction_items = corrections
        for item in correction_items:
            paragraph_id = item.get("corrected_paragraph_id") or item.get("paragraph_id")
            if paragraph_id:
                paragraph_ids.add(str(paragraph_id))
    overlap = pd.read_excel(PLACE_OVERLAP_FILE)
    paragraph_ids.update(overlap["paragraph_id"].dropna().astype(str).tolist())
    return paragraph_ids


def enriched_date_from_id(enriched_id: str) -> str:
    return str(enriched_id)[:10]


def date_diff_days(enriched_date: str, flat_date: str) -> int | None:
    try:
        return period_diff_days(period_days(enriched_date), period_days(flat_date))
    except (ValueError, TypeError):
        return None


def summarize_diffs(diffs: list[int | None]) -> dict[str, Any]:
    valid = [value for value in diffs if value is not None]
    if not valid:
        return {
            "count": 0,
            "same_day_rate": None,
            "within_1_day_rate": None,
            "within_3_day_rate": None,
            "within_7_day_rate": None,
            "mean_days": None,
            "median_days": None,
            "max_days": None,
            "histogram": {},
        }
    arr = np.array(valid, dtype=int)
    histogram = {str(day): int(count) for day, count in sorted(Counter(valid).items())}
    return {
        "count": len(valid),
        "same_day_rate": round(float((arr == 0).mean()), 4),
        "within_1_day_rate": round(float((arr <= 1).mean()), 4),
        "within_3_day_rate": round(float((arr <= 3).mean()), 4),
        "within_7_day_rate": round(float((arr <= 7).mean()), 4),
        "mean_days": round(float(arr.mean()), 3),
        "median_days": float(np.median(arr)),
        "max_days": int(arr.max()),
        "histogram": histogram,
    }


def load_flat_dates(res_df: pd.DataFrame) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in res_df.itertuples(index=False):
        lookup[str(row.id)] = str(row.date)[:10]
    return lookup


def analyze_pins(
    state: dict[str, Any],
    paragraph_to_resolution: dict[str, str],
    flat_dates: dict[str, str],
) -> dict[str, Any]:
    diffs: list[int | None] = []
    examples: list[dict[str, Any]] = []
    for pin in state.get("curated_pins", []):
        enriched_id = str(pin.get("enriched_id", ""))
        paragraph_id = str(pin.get("paragraph_id", ""))
        resolution_id = paragraph_to_resolution.get(paragraph_id)
        if not enriched_id or not resolution_id:
            continue
        enriched_date = enriched_date_from_id(enriched_id)
        flat_date = flat_dates.get(str(resolution_id))
        if not flat_date:
            continue
        diff = date_diff_days(enriched_date, flat_date)
        diffs.append(diff)
        if diff and diff > 0 and len(examples) < 8:
            examples.append(
                {
                    "enriched_id": enriched_id,
                    "paragraph_id": paragraph_id,
                    "enriched_date": enriched_date,
                    "flat_date": flat_date,
                    "date_diff_days": diff,
                }
            )
    return {"summary": summarize_diffs(diffs), "non_same_day_examples": examples}


def analyze_alignments(
    state: dict[str, Any],
    flat_dates: dict[str, str],
) -> dict[str, Any]:
    pinned_diffs: list[int | None] = []
    propagated_diffs: list[int | None] = []
    for row in state.get("alignments", []):
        enriched_date = str(row.get("enriched_date", ""))[:10]
        resolution_id = row.get("resolution_id")
        if not enriched_date or not resolution_id:
            continue
        flat_date = flat_dates.get(str(resolution_id))
        if not flat_date:
            continue
        diff = date_diff_days(enriched_date, flat_date)
        if row.get("pinned"):
            pinned_diffs.append(diff)
        else:
            propagated_diffs.append(diff)
    return {
        "pinned": summarize_diffs(pinned_diffs),
        "propagated": summarize_diffs(propagated_diffs),
    }


def analyze_corrections(
    summary_path: Path,
    paragraph_to_resolution: dict[str, str],
    flat_dates: dict[str, str],
) -> dict[str, Any]:
    if not summary_path.exists():
        return {"available": False}
    payload = load_json(summary_path)
    corrections = payload.get("corrections", {})
    if isinstance(corrections, dict):
        correction_items = corrections.values()
    else:
        correction_items = corrections
    confirmed_diffs: list[int | None] = []
    for item in correction_items:
        if item.get("action") not in {"confirmed", "correct"} and item.get("verdict") not in {
            "confirmed",
            "correct",
        }:
            continue
        enriched_key = item.get("enriched_id")
        if not enriched_key:
            continue
        paragraph_id = item.get("corrected_paragraph_id") or item.get("paragraph_id")
        if paragraph_id:
            resolution_id = paragraph_to_resolution.get(str(paragraph_id))
        else:
            resolution_id = item.get("corrected_resolution_id") or item.get("auto_flat_id")
        if not resolution_id:
            continue
        enriched_date = enriched_date_from_id(str(enriched_key))
        flat_date = flat_dates.get(str(resolution_id))
        if not flat_date:
            continue
        confirmed_diffs.append(date_diff_days(enriched_date, flat_date))
    return {"available": True, "confirmed": summarize_diffs(confirmed_diffs)}


def analyze_ground_truth(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"available": False}
    records = load_json(path)
    diffs = [
        record.get("date_diff_days")
        for record in records
        if record.get("date_diff_days") is not None
    ]
    same_day = [bool(record.get("is_same_day")) for record in records]
    return {
        "available": True,
        "pairs": summarize_diffs(diffs),
        "is_same_day_rate": round(sum(same_day) / len(same_day), 4) if same_day else None,
    }


def analyze_entity_bridge_skew(window_days: int = 30) -> dict[str, Any]:
    """Name-only entity bridges across a wide window — independent of same-day join."""
    enriched_all = load_json(ENRICHED_FILE)
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    loc_names = load_entity_names(LOC_ENTITIES_FILE)
    institution_names = load_institution_names(INSTELLING_INFO_FILE)

    enriched_places = build_enriched_places(enriched_all)
    loc_df = attach_flat_dates(flatten_loc_annotations(LOC_ANNOTATIONS_FILE, loc_names), res_df)
    place_window, place_stats = windowed_place_overlap(
        enriched_places,
        index_flat_rows_by_date(loc_df),
        window_days,
    )
    diffs = place_window["date_diff_days"].astype(int).tolist() if len(place_window) else []
    same_day_rows = int((place_window["date_diff_days"] == 0).sum()) if len(place_window) else 0
    return {
        "window_days": window_days,
        "place_bridge_rows": len(place_window),
        "same_day_rows": same_day_rows,
        "cross_day_rows": len(place_window) - same_day_rows,
        "canonical_matches": place_stats.get("canonical_matches", 0),
        "tag_text_matches": place_stats.get("tag_text_matches", 0),
        "date_diff_summary": summarize_diffs(diffs),
        "interpretation": (
            "Among place-name entity bridges allowed within the window, "
            "the share with date_diff_days==0 estimates how often editorial and HTR "
            "dates agree when entities co-occur, without forcing a same-day join."
        ),
    }


def analyze_legacy_overlap_dates(
    overlap_path: Path,
    paragraph_to_resolution: dict[str, str],
    flat_dates: dict[str, str],
) -> dict[str, Any]:
    """Attach independent flat resolution dates to legacy same-day overlap rows."""
    if not overlap_path.exists():
        return {"available": False}
    overlap = pd.read_excel(overlap_path)
    diffs: list[int | None] = []
    for row in overlap.itertuples(index=False):
        enriched_date = str(row.volgnr)[:10]
        resolution_id = paragraph_to_resolution.get(str(row.paragraph_id))
        if not resolution_id:
            continue
        flat_date = flat_dates.get(str(resolution_id))
        if not flat_date:
            continue
        diffs.append(date_diff_days(enriched_date, flat_date))
    return {"available": True, "independent_flat_dates": summarize_diffs(diffs)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze enriched↔flat date agreement")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR / "date_agreement_report.json",
    )
    parser.add_argument("--entity-window-days", type=int, default=30)
    args = parser.parse_args()

    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    flat_dates = load_flat_dates(res_df)
    state = load_json(ALIGNMENT_STATE_FILE) if ALIGNMENT_STATE_FILE.exists() else {}
    paragraph_ids = collect_paragraph_ids(state, CORRECTION_SUMMARY_FILE)
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        paragraph_mapping_annotation_files(),
        paragraph_ids,
    )
    ground_truth_path = resolve_optional_file(GROUND_TRUTH_CANDIDATES)
    report: dict[str, Any] = {
        "question": "How often do verified enriched↔flat pairs share the same calendar date?",
        "sources": {
            "curated_pins": analyze_pins(state, paragraph_to_resolution, flat_dates),
            "chain_alignments": analyze_alignments(state, flat_dates),
            "confirmed_corrections": analyze_corrections(
                CORRECTION_SUMMARY_FILE,
                paragraph_to_resolution,
                flat_dates,
            ),
            "ground_truth_labeled_50": analyze_ground_truth(ground_truth_path)
            if ground_truth_path
            else {"available": False},
            "legacy_place_overlap_independent_dates": analyze_legacy_overlap_dates(
                PLACE_OVERLAP_FILE,
                paragraph_to_resolution,
                flat_dates,
            ),
            "place_entity_bridge_skew": analyze_entity_bridge_skew(args.entity_window_days),
        },
        "how_to_read": [
            "curated_pins and confirmed_corrections are the strongest human-validated signals.",
            "legacy_place_overlap_independent_dates checks whether same-day Excel joins still imply matching flat resolution dates.",
            "place_entity_bridge_skew measures date spread among name-matched bridges without requiring same-day joins.",
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== Resolution date agreement ===")
    for source_name, payload in report["sources"].items():
        print(f"\n[{source_name}]")
        if not payload.get("available", True):
            print("  (not available)")
            continue
        if "summary" in payload:
            summary = payload["summary"]
        elif "confirmed" in payload:
            summary = payload["confirmed"]
        elif "pinned" in payload:
            summary = payload["pinned"]
            print(
                f"  pinned: n={summary['count']}, same_day={summary['same_day_rate']}, "
                f"<=3d={summary['within_3_day_rate']}"
            )
            propagated = payload["propagated"]
            print(
                f"  propagated: n={propagated['count']}, same_day={propagated['same_day_rate']}, "
                f"<=3d={propagated['within_3_day_rate']}"
            )
            continue
        elif "date_diff_summary" in payload:
            summary = payload["date_diff_summary"]
            print(f"  bridge_rows={payload['place_bridge_rows']}, same_day_rows={payload['same_day_rows']}")
        elif "independent_flat_dates" in payload:
            summary = payload["independent_flat_dates"]
        elif "pairs" in payload:
            summary = payload["pairs"]
            print(f"  is_same_day_rate={payload.get('is_same_day_rate')}")
        else:
            continue
        print(
            f"  n={summary['count']}, same_day={summary['same_day_rate']}, "
            f"<=1d={summary['within_1_day_rate']}, <=3d={summary['within_3_day_rate']}, "
            f"mean={summary['mean_days']}, max={summary['max_days']}"
        )

    print(f"\n✓ Wrote {args.output}")


if __name__ == "__main__":
    main()

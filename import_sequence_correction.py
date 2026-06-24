#!/usr/bin/env python3
"""Import manual sequence corrections into alignment state and corrective ground truth.

Usage:
    uv run python import_sequence_correction.py \\
        --correction output/sequence_correction_summary.json

    # Import every export in output/ (dated filenames included):
    uv run python import_sequence_correction.py --import-all
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from analyze_sequence_entity_overlap import resolve_pin_paragraph_id
from build_alignment_new import (
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    ORG_OVERLAP_FILE,
    OUTPUT_DIR,
    PLACE_OVERLAP_FILE,
    build_paragraph_to_resolution_map,
    load_json,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = OUTPUT_DIR / "alignment_state.json"
CORRECTION_GLOB = "sequence_correction_summary*.json"


def discover_correction_exports(output_dir: Path) -> list[Path]:
    paths = sorted(output_dir.glob(CORRECTION_GLOB), key=lambda path: path.stat().st_mtime)
    return paths


def load_pin_resolution_context() -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame]:
    places_df = pd.read_excel(PLACE_OVERLAP_FILE)
    orgs_df = pd.read_excel(ORG_OVERLAP_FILE)
    if "naam" in orgs_df.columns and "name" not in orgs_df.columns:
        orgs_df = orgs_df.rename(columns={"naam": "name"})
    if "naam" in places_df.columns and "name" not in places_df.columns:
        places_df = places_df.rename(columns={"naam": "name"})

    paragraph_ids: set[str] = set()
    for path in (LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE):
        for item in load_json(path):
            ref = item.get("reference") or {}
            paragraph_id = ref.get("paragraph_id")
            if paragraph_id is not None:
                paragraph_ids.add(str(paragraph_id).strip())

    paragraph_to_resolution = build_paragraph_to_resolution_map(
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )
    return paragraph_to_resolution, places_df, orgs_df


def merge_correction_exports(exports: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {"corrections": {}}
    for export in exports:
        corrections = export.get("corrections", {})
        if not isinstance(corrections, dict):
            raise ValueError("corrections must be a dict keyed by correction_id")
        merged["corrections"].update(corrections)
    return merged


def merge_corrections(
    state: dict[str, Any],
    correction_export: dict[str, Any],
    *,
    paragraph_to_resolution: dict[str, str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    corrections_raw = correction_export.get("corrections", {})
    if not isinstance(corrections_raw, dict):
        raise ValueError("corrections must be a dict keyed by correction_id")

    curated_pins: list[dict[str, str]] = list(state.get("curated_pins", []))
    rejected_pairs: list[dict[str, str]] = list(state.get("rejected_pairs", []))
    corrective_records: list[dict[str, Any]] = []

    pin_keys = {(p["enriched_id"], p.get("paragraph_id")) for p in curated_pins}
    reject_keys = {(p["enriched_id"], p.get("flat_id")) for p in rejected_pairs}

    counts = {"confirmed": 0, "rejected": 0, "uncertain": 0}
    unresolved_confirmed = 0

    for _cid, item in corrections_raw.items():
        action = item.get("action")
        enriched_id = str(item.get("enriched_id", ""))
        session_id = str(item.get("session_id", ""))
        counts[action] = counts.get(action, 0) + 1

        resolved_paragraph_id = None
        if action == "confirmed":
            resolution_id = item.get("corrected_resolution_id") or item.get("auto_flat_id")
            resolved_paragraph_id = resolve_pin_paragraph_id(
                enriched_id=enriched_id,
                resolution_id=resolution_id,
                paragraph_id=item.get("corrected_paragraph_id"),
                auto_paragraph_id=item.get("auto_paragraph_id"),
                paragraph_to_resolution=paragraph_to_resolution,
                places_df=places_df,
                orgs_df=orgs_df,
            )
            if not resolved_paragraph_id:
                unresolved_confirmed += 1

        record = {
            "enriched_id": enriched_id,
            "session_id": session_id,
            "action": action,
            "corrected_paragraph_id": resolved_paragraph_id or item.get("corrected_paragraph_id"),
            "corrected_resolution_id": item.get("corrected_resolution_id"),
            "auto_paragraph_id": item.get("auto_paragraph_id"),
            "auto_flat_id": item.get("auto_flat_id"),
            "prior_verdict": item.get("prior_verdict"),
            "source": "manual_sequence_correction",
            "timestamp": item.get("timestamp"),
        }
        corrective_records.append(record)

        if action == "confirmed" and resolved_paragraph_id:
            paragraph_id = str(resolved_paragraph_id)
            key = (enriched_id, paragraph_id)
            if key not in pin_keys:
                curated_pins.append(
                    {
                        "enriched_id": enriched_id,
                        "paragraph_id": paragraph_id,
                        "resolution_id": item.get("corrected_resolution_id"),
                        "session_id": session_id,
                        "source": "manual_correction",
                        "place_score": item.get("place_score"),
                        "org_score": item.get("org_score"),
                        "signal": item.get("signal"),
                    }
                )
                pin_keys.add(key)
        elif action == "rejected" and item.get("auto_flat_id"):
            flat_id = str(item["auto_flat_id"])
            key = (enriched_id, flat_id)
            if key not in reject_keys:
                rejected_pairs.append({"enriched_id": enriched_id, "flat_id": flat_id})
                reject_keys.add(key)

    state["version"] = int(state.get("version", 0)) + 1
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["curated_pins"] = curated_pins
    state["rejected_pairs"] = rejected_pairs
    state["manual_corrections"] = corrective_records

    summary = {
        "corrections_imported": len(corrections_raw),
        "confirmed": counts.get("confirmed", 0),
        "rejected": counts.get("rejected", 0),
        "uncertain": counts.get("uncertain", 0),
        "confirmed_pins_added": sum(1 for item in corrective_records if item.get("action") == "confirmed" and item.get("corrected_paragraph_id")),
        "unresolved_confirmed": unresolved_confirmed,
        "total_curated_pins": len(curated_pins),
        "total_rejected_pairs": len(rejected_pairs),
    }
    return state, corrective_records, summary


def import_correction_files(
    correction_paths: list[Path],
    *,
    state_path: Path = DEFAULT_STATE,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    if not correction_paths:
        raise FileNotFoundError("No correction export files provided.")

    paragraph_to_resolution, places_df, orgs_df = load_pin_resolution_context()
    exports = [load_json(path) for path in correction_paths]
    correction_export = merge_correction_exports(exports) if len(exports) > 1 else exports[0]

    state = load_json(state_path) if state_path.exists() else {
        "version": 0,
        "curated_pins": [],
        "rejected_pairs": [],
        "alignments": [],
    }

    state, corrective_records, summary = merge_corrections(
        state,
        correction_export,
        paragraph_to_resolution=paragraph_to_resolution,
        places_df=places_df,
        orgs_df=orgs_df,
    )
    summary["source_files"] = [str(path) for path in correction_paths]
    summary["state_version"] = state["version"]

    output_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    corrective_path = output_dir / "corrective_ground_truth.json"
    summary_path = output_dir / "correction_import_summary.json"
    corrective_path.write_text(json.dumps(corrective_records, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def auto_import_corrections(output_dir: Path, *, state_path: Path | None = None) -> dict[str, Any] | None:
    """Import correction export(s). Prefers output/sequence_correction_summary.json when present."""
    canonical = output_dir / "sequence_correction_summary.json"
    if canonical.exists():
        exports = [canonical]
    else:
        exports = discover_correction_exports(output_dir)
    if not exports:
        downloads = Path.home() / "Downloads" / "sequence_correction_summary.json"
        if downloads.exists():
            exports = [downloads]
    if not exports:
        return None
    return import_correction_files(
        exports,
        state_path=state_path or output_dir / "alignment_state.json",
        output_dir=output_dir,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import sequence correction export into alignment state.")
    parser.add_argument("--correction", type=Path, action="append", default=[])
    parser.add_argument("--import-all", action="store_true", help=f"Import all {CORRECTION_GLOB} in output dir")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    correction_paths = list(args.correction)
    if args.import_all:
        correction_paths = discover_correction_exports(args.output_dir)
    elif not correction_paths:
        default = args.output_dir / "sequence_correction_summary.json"
        if default.exists():
            correction_paths = [default]
        else:
            correction_paths = discover_correction_exports(args.output_dir)

    if not correction_paths:
        raise FileNotFoundError(
            "No correction export found. Pass --correction PATH or export from verify_resolution_search.html."
        )

    summary = import_correction_files(
        correction_paths,
        state_path=args.state,
        output_dir=args.output_dir,
    )

    print(f"✓ Updated alignment state: {args.state} (v{summary['state_version']})")
    print(f"✓ Corrective ground truth: {args.output_dir / 'corrective_ground_truth.json'}")
    print(f"✓ Import summary: {args.output_dir / 'correction_import_summary.json'}")
    print(
        f"  Confirmed: {summary['confirmed']} "
        f"({summary['confirmed_pins_added']} pinned; {summary['unresolved_confirmed']} unresolved); "
        f"rejected: {summary['rejected']}; uncertain: {summary['uncertain']}"
    )


if __name__ == "__main__":
    main()

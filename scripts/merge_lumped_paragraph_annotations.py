#!/usr/bin/env python3
"""Merge exported lumped-paragraph annotations into verified gold.

Usage:
    uv run python scripts/merge_lumped_paragraph_annotations.py [--annotator NAME]

Reads ``output/lumped_paragraph_gold_annotations.json`` (UI export), strips
``|||CUT|||`` markers to recover char offsets, and writes
``lumped_paragraph_boundary_gold``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve, save_semi_structured
from scripts.build_lumped_paragraph_annotation_ui import MARKER

SCAFFOLD_DATASET = "lumped_paragraph_gold_scaffold"
ANNOTATIONS_FILE = PROJECT_ROOT / "output" / "lumped_paragraph_gold_annotations.json"
OUTPUT_DATASET = "lumped_paragraph_boundary_gold"


def parse_cut_offsets(annotated_text: str, marker: str = MARKER) -> tuple[str, list[int]]:
    """Return (clean_text, cut_offsets in clean_text)."""
    offsets: list[int] = []
    parts = annotated_text.split(marker)
    clean = "".join(parts)
    running = 0
    for part in parts[:-1]:
        running += len(part)
        offsets.append(running)
    return clean, offsets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotator", default=None)
    args = parser.parse_args()

    if not ANNOTATIONS_FILE.exists():
        raise FileNotFoundError(
            f"{ANNOTATIONS_FILE} not found. Export from lumped_paragraph_annotation_ui.html first."
        )

    resolve(SCAFFOLD_DATASET)
    scaffold = [r for r in load(SCAFFOLD_DATASET) if r.get("record_type") == "candidate"]
    by_id = {str(r["example_id"]): r for r in scaffold}
    exported = json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    marker = exported.get("marker", MARKER)
    annotations = exported.get("annotations") or {}
    now = datetime.now(timezone.utc).isoformat()

    gold_rows: list[dict[str, Any]] = []
    skipped = 0
    for example_id, state in annotations.items():
        base = by_id.get(str(example_id))
        if base is None:
            continue
        if state.get("skip"):
            skipped += 1
            continue
        if not state.get("labelled", True):
            # UI always sets labelled=true on save; skip incomplete drafts.
            continue
        annotated_text = str(state.get("text") or "")
        clean, offsets = parse_cut_offsets(annotated_text, marker)
        expected = int(base.get("expected_cuts") or 0)
        if len(offsets) != expected:
            raise ValueError(
                f"{example_id}: expected {expected} cuts, found {len(offsets)}. "
                "Fix in the UI or mark skip."
            )
        row = {
            "record_type": "gold",
            "example_id": example_id,
            "date": base["date"],
            "paragraph_stream_index": base["paragraph_stream_index"],
            "flat_id": base.get("flat_id"),
            "para_index": base.get("para_index"),
            "text": clean if clean else base.get("text"),
            "text_char_len": len(clean) if clean else base.get("text_char_len"),
            "n_resolutions": base["n_resolutions"],
            "expected_cuts": expected,
            "gold_offsets": offsets,
            "n_cuts": len(offsets),
            "resolution_ids": base.get("resolution_ids"),
            "resolution_indices": base.get("resolution_indices"),
            "uncertain": bool(state.get("uncertain")),
            "clutter": bool(state.get("clutter")),
            "paragraph_notes": str(state.get("paragraph_notes") or ""),
            "cut_notes": str(state.get("cut_notes") or ""),
            "review_status": "verified",
            "annotator": args.annotator,
            "annotated_at": now,
            "stratum": base.get("stratum"),
        }
        gold_rows.append(row)

    meta = {
        "record_type": "meta",
        "track": "lumped_paragraph_boundary_gold",
        "description": "Hand-labeled mid_paragraph cuts inside lumped HTR paragraphs.",
        "parent_datasets": [SCAFFOLD_DATASET],
        "n_gold": len(gold_rows),
        "n_skipped": skipped,
        "annotator": args.annotator,
        "merged_at": now,
    }
    path = save_semi_structured([meta, *gold_rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Merged {len(gold_rows)} gold paragraphs ({skipped} skipped) → {path}")


if __name__ == "__main__":
    main()

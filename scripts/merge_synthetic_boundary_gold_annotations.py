#!/usr/bin/env python3
"""Merge exported synthetic boundary gold annotations into ``synthetic_boundary_gold``.

Expected export JSON: a list of objects with at least::

    {
      "candidate_id": "sbgs-a-00001",
      "gold_boundaries": [1234],
      "review_status": "verified",
      "annotator": "NAME",
      "notes": ""
    }

Only ``review_status`` in ``verified`` or ``corrected`` are written to the gold file.
``rejected`` items are recorded in the merge report but omitted from gold.

Usage:
    uv run python scripts/merge_synthetic_boundary_gold_annotations.py \\
        --annotations republic_ner_matching/output/synthetic_boundary_gold_annotations.json
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

SCAFFOLD_DATASET = "synthetic_boundary_gold_scaffold"
ANNOTATIONS_DATASET = "synthetic_boundary_gold_annotations"
OUTPUT_DATASET = "synthetic_boundary_gold"

ACCEPT_STATUSES = frozenset({"verified", "corrected"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge synthetic boundary gold annotations.")
    parser.add_argument(
        "--annotations",
        type=str,
        default="",
        help="Path to annotations JSON (defaults to manifest synthetic_boundary_gold_annotations).",
    )
    args = parser.parse_args()

    scaffold_records = load(SCAFFOLD_DATASET)
    meta = next((r for r in scaffold_records if r.get("record_type") == "meta"), None)
    candidates = {r["candidate_id"]: r for r in scaffold_records if r.get("record_type") == "candidate"}

    ann_path = Path(args.annotations) if args.annotations else resolve(ANNOTATIONS_DATASET)
    if not ann_path.exists():
        raise FileNotFoundError(f"Annotations file not found: {ann_path}")

    annotations: list[dict[str, Any]] = json.loads(ann_path.read_text(encoding="utf-8"))
    if not isinstance(annotations, list):
        raise ValueError("Annotations JSON must be a list of objects")

    gold_rows: list[dict[str, Any]] = []
    rejected: list[str] = []
    missing: list[str] = []

    for ann in annotations:
        cid = str(ann.get("candidate_id", "")).strip()
        if not cid:
            continue
        base = candidates.get(cid)
        if base is None:
            missing.append(cid)
            continue
        status = str(ann.get("review_status", "")).strip().lower()
        if status == "rejected":
            rejected.append(cid)
            continue
        if status not in ACCEPT_STATUSES:
            continue
        boundaries = ann.get("gold_boundaries")
        if not isinstance(boundaries, list) or not boundaries:
            raise ValueError(f"{cid}: gold_boundaries must be a non-empty list of integers")
        gold_rows.append(
            {
                **base,
                "record_type": "gold",
                "gold_boundaries": [int(x) for x in boundaries],
                "review_status": status,
                "annotator": ann.get("annotator"),
                "notes": ann.get("notes") or "",
                "merged_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    out_meta = {
        "record_type": "meta",
        "track": "synthetic_boundary_encoder",
        "description": "Hand-verified merge boundary gold (benchmark; never used for training).",
        "parent_datasets": [SCAFFOLD_DATASET, ANNOTATIONS_DATASET],
        "scaffold_meta": meta,
        "merge_stats": {
            "annotations_read": len(annotations),
            "gold_written": len(gold_rows),
            "rejected": len(rejected),
            "unknown_candidate_id": len(missing),
        },
    }

    output = save_semi_structured([out_meta, *gold_rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(gold_rows)} gold items to {output}")
    if rejected:
        print(f"  Rejected (omitted): {len(rejected)}")
    if missing:
        print(f"  Unknown candidate_id (skipped): {len(missing)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Prebuild paragraph_id -> resolution_id mapping parquet from annotation JSONs.

Reads LOC, ORG, and PER annotation JSON files and outputs a fast Parquet lookup
table to avoid reparsing ~4.3 GB of JSON on every alignment run.

Usage:
    uv run python prebuild_paragraph_resolution_map.py
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from build_alignment_new import (
    DATADIR,
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    PER_ANNOTATIONS_FILE,
    PLACE_OVERLAP_FILE,
    ORG_OVERLAP_FILE,
    PER_OVERLAP_FILE,
)

OUTPUT_FILE = DATADIR / "derived" / "paragraph_to_resolution.parquet"


def main() -> None:
    print("Reading overlap spreadsheets to identify needed paragraph IDs...")
    needed_ids: set[str] = set()
    for file in (PLACE_OVERLAP_FILE, ORG_OVERLAP_FILE, PER_OVERLAP_FILE):
        if file.exists():
            df = pd.read_excel(file)
            if "paragraph_id" in df.columns:
                needed_ids.update(df["paragraph_id"].dropna().astype(str).str.strip())

    print(f"✓ Found {len(needed_ids)} target paragraph IDs across overlap files.")

    mapping: dict[str, str] = {}
    remaining = set(needed_ids)

    for path in (LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE, PER_ANNOTATIONS_FILE):
        if not remaining:
            break
        if not path.exists():
            continue
        print(f"Scanning {path.name} ({path.stat().st_size / (1024*1024):.1f} MB)...")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                ref = item.get("reference") or {}
                p_id = ref.get("paragraph_id")
                r_id = ref.get("resolution_id")
                if p_id is not None and r_id is not None:
                    p_key = str(p_id).strip()
                    if p_key in remaining:
                        mapping[p_key] = str(r_id).strip()
                        remaining.discard(p_key)

    print(f"✓ Resolved {len(mapping)} / {len(needed_ids)} paragraph IDs ({len(remaining)} unmapped).")

    df_out = pd.DataFrame(
        list(mapping.items()),
        columns=["paragraph_id", "resolution_id"],
    )
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(OUTPUT_FILE, index=False)
    print(f"✓ Saved fast lookup to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

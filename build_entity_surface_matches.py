#!/usr/bin/env python3
"""
Build a per-flat-resolution cache of confirmed LOC/PER canonical entity names,
for the 1626-1630 window only.

STRATEGY: candidate shortlist (from LOC-/PER-annotations.json), then verify
==========================================================================

`matched_entity_names` in build_alignment_new.py checks every resolved
canonical name against a flat resolution's text with a literal substring
scan -- orthography-blind (misses spelling variants like "Uijtrecht" for
"Utrecht") and, if done against the full ~10,876-name LOC+PER+ORG
dictionary per resolution, does not scale (fuzzy_search.FuzzyTokenSearcher
benchmarked this session: >4.5 min / 3.7GB RAM on the full dictionary,
without finishing).

LOC-/PER-annotations.json already link resolution_id -> entity_id for the
whole resolutions_flat.parquet corpus. Their character offsets are ~50%
wrong (documented, unfixed elsewhere in this repo) and some entity
assignments are noisy/duplicated, so they are used here *only* as a
candidate shortlist -- narrowing each resolution's fuzzy-match search from
~10,876 names down to a handful -- never trusted for exact spans or
membership alone. Every candidate is confirmed against the resolution's
real text (data.bak-free: uses the clean `resolutions_text` column, not the
bracket-wrapped `paragraph_texts` string) via exact substring first, falling
back to rapidfuzz.fuzz.partial_ratio (fast, no per-call index construction,
well-suited to a handful of short candidates per resolution) only for
candidates that fail the exact check.

Usage:
    uv run python build_entity_surface_matches.py
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import pandas as pd
from rapidfuzz import fuzz
from tqdm import tqdm

from data_io import load, save_parquet

from build_alignment_new import LOC_ENTITIES_FILE, PER_ENTITIES_FILE
from build_alignment_new import load_entity_names as load_entity_names_from_path

FUZZY_THRESHOLD = 85  # rapidfuzz.fuzz.partial_ratio; see session benchmark:
# true spelling variants ("Uijtrecht"/"utrecht": 85.7, "Wassenaer"/"wassenaar
# text": 88.9) score above unrelated names ("Rotterdam" vs unrelated text:
# 75) at this threshold.

WINDOW_BUFFER_DAYS = 30


def load_confined_resolutions() -> pd.DataFrame:
    """Flat resolutions confined to the enriched 1626-1630 date envelope."""
    enriched = load("enriched_resolutions_1626_1630")
    res_df: pd.DataFrame = load("resolutions_flat")
    res_df["date_period"] = pd.PeriodIndex(res_df["date"].astype(str), freq="D")

    enriched_dates = []
    for item in enriched:
        raw = item.get("date")
        if raw:
            try:
                enriched_dates.append(pd.Period(str(raw)[:10], freq="D"))
            except (TypeError, ValueError):
                pass

    min_date = min(enriched_dates) - WINDOW_BUFFER_DAYS
    max_date = max(enriched_dates) + WINDOW_BUFFER_DAYS
    mask = (res_df["date_period"] >= min_date) & (res_df["date_period"] <= max_date)
    return res_df[mask].copy().reset_index(drop=True)


def build_candidate_shortlist(
    annotations_logical_name: str, target_resolution_ids: set[str]
) -> dict[str, set[str]]:
    """resolution_id -> set(entity_id), filtered to target_resolution_ids.

    Offsets are ignored entirely -- presence of an (resolution_id, entity_id)
    pair in the annotation file is treated as "an annotator once associated
    this entity with this resolution," nothing stronger.
    """
    print(f"  Loading {annotations_logical_name} (large file, one-time cost)...")
    records = load(annotations_logical_name)
    print(f"  Loaded {len(records)} annotation records; filtering to {len(target_resolution_ids)} target resolutions...")

    shortlist: dict[str, set[str]] = defaultdict(set)
    for rec in tqdm(records, desc=f"Scanning {annotations_logical_name}", unit="rec", leave=False):
        ref = rec.get("reference") or {}
        resolution_id = ref.get("resolution_id")
        entity_id = rec.get("entity")
        if resolution_id in target_resolution_ids and entity_id:
            shortlist[resolution_id].add(entity_id)
    return dict(shortlist)


def confirm_candidates(
    res_df: pd.DataFrame,
    shortlist: dict[str, set[str]],
    entity_names: dict[str, str],
    entity_type: str,
) -> list[dict]:
    """For each resolution's candidate entities, confirm presence in its real
    text: exact substring first, rapidfuzz.fuzz.partial_ratio fallback."""
    text_by_id = dict(zip(res_df["id"], res_df["resolutions_text"]))
    rows: list[dict] = []

    for resolution_id, entity_ids in tqdm(shortlist.items(), desc=f"Confirming {entity_type}", unit="res"):
        text = text_by_id.get(resolution_id)
        if not text:
            continue
        text_lower = text.lower()

        fuzzy_candidates: list[tuple[str, str]] = []  # (entity_id, name)
        for entity_id in entity_ids:
            name = entity_names.get(entity_id)
            if not name:
                continue
            if name.lower() in text_lower:
                rows.append(
                    {
                        "resolution_id": resolution_id,
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "canonical_name": name,
                        "match_method": "exact",
                        "match_score": 100.0,
                    }
                )
            else:
                fuzzy_candidates.append((entity_id, name))

        for entity_id, name in fuzzy_candidates:
            score = fuzz.partial_ratio(name.lower(), text_lower)
            if score >= FUZZY_THRESHOLD:
                rows.append(
                    {
                        "resolution_id": resolution_id,
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "canonical_name": name,
                        "match_method": "fuzzy",
                        "match_score": score,
                    }
                )

    return rows


def main():
    start = datetime.now()
    print("=" * 70)
    print("Building entity surface-form matches (1626-1630)")
    print(f"Started: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print("\n[1/4] Loading confined flat resolutions...")
    res_df = load_confined_resolutions()
    target_ids = set(res_df["id"])
    print(f"  {len(target_ids)} flat resolutions in window")

    print("\n[2/4] Loading canonical entity name dictionaries...")
    loc_names = load_entity_names_from_path(LOC_ENTITIES_FILE)
    per_names = load_entity_names_from_path(PER_ENTITIES_FILE)
    print(f"  {len(loc_names)} LOC names, {len(per_names)} PER names")

    print("\n[3/4] Building candidate shortlists and confirming against real text...")
    loc_shortlist = build_candidate_shortlist("loc_annotations", target_ids)
    loc_rows = confirm_candidates(res_df, loc_shortlist, loc_names, "LOC")
    print(f"  LOC: {len(loc_rows)} confirmed matches across {len(loc_shortlist)} candidate resolutions")

    per_shortlist = build_candidate_shortlist("per_annotations", target_ids)
    per_rows = confirm_candidates(res_df, per_shortlist, per_names, "PER")
    print(f"  PER: {len(per_rows)} confirmed matches across {len(per_shortlist)} candidate resolutions")

    print("\n[4/4] Saving cache...")
    df = pd.DataFrame(loc_rows + per_rows)
    exact_count = int((df["match_method"] == "exact").sum()) if not df.empty else 0
    fuzzy_count = int((df["match_method"] == "fuzzy").sum()) if not df.empty else 0
    print(f"  {len(df)} total rows ({exact_count} exact, {fuzzy_count} fuzzy)")

    path = save_parquet(
        df,
        logical_name="entity_surface_matches_1626_1630",
        parent_sources=["loc_annotations", "per_annotations", "resolutions_flat"],
        script=__file__,
    )
    print(f"  Saved to {path}")

    duration = (datetime.now() - start).total_seconds()
    print("\n" + "=" * 70)
    print(f"Completed in {duration:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()

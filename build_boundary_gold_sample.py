#!/usr/bin/env python3
"""S3 — boundary gold sample builder (docs/SEGMENTATION_TRANSFER.md §10).

Prepares (does not itself hand-label) the ~50 session-day boundary-gold sample:

1. Recomputes per-session-day K_e / K_f / |K_e - K_f| (same logic as D1 in
   run_diagnostics.py) for the 1626-1630 window.
2. Draws a stratified sample of ~50 session-days across |K_e - K_f| bins so the
   hardest (largest-mismatch) days are represented, not just the easy ones.
3. Cross-checks the upstream `res_start` ground truth
   (~/develop/republicgit/ground_truth/resolutions/res_start/*.xlsx) for any
   scan_id overlap with the sampled session-days' inventories.
4. Writes an annotation scaffold to output/boundary_gold_sample.json with an
   empty "boundaries" list per day for an expert annotator to fill in
   (~2-4 h expert time per docs/SEGMENTATION_TRANSFER.md — not automatable).

Usage:
    uv run python build_boundary_gold_sample.py
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from build_alignment_new import OUTPUT_DIR, load_data

SAMPLE_SIZE = 50
RANDOM_SEED = 42
RES_START_DIR = Path(
    "/Users/rikhoekstra/develop/republicgit/ground_truth/resolutions/res_start"
)
OUT_FILE = OUTPUT_DIR / "boundary_gold_sample.json"

# Bins on |K_e - K_f|: exact match, off-by-one, off-by-two, large mismatch.
BIN_EDGES = [0, 1, 2, 3, float("inf")]
BIN_LABELS = ["diff_0", "diff_1", "diff_2", "diff_3plus"]


def bin_for_diff(abs_diff: int) -> str:
    for label, lo, hi in zip(BIN_LABELS, BIN_EDGES[:-1], BIN_EDGES[1:]):
        if lo <= abs_diff < hi:
            return label
    return BIN_LABELS[-1]


def compute_session_stats(
    enriched_all: list[dict[str, Any]], res_df: pd.DataFrame
) -> list[dict[str, Any]]:
    """Per session-day K_e / K_f, mirroring run_d1_structure_vs_evidence."""
    enriched_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in enriched_all:
        d_str = str(e.get("date", ""))[:10]
        if len(d_str) == 10 and d_str.startswith("16"):
            enriched_by_date[d_str].append(e)

    res_df_valid = res_df[res_df["date_str"].isin(enriched_by_date)].copy()

    stats = []
    for date_str, e_list in enriched_by_date.items():
        f_rows = res_df_valid[res_df_valid["date_str"] == date_str]
        k_e = len(e_list)
        k_f = len(f_rows)
        stats.append(
            {
                "date": date_str,
                "k_e": k_e,
                "k_f": k_f,
                "diff_ke_kf": k_e - k_f,
                "enriched_ids": [
                    str(e.get("volgnr") or f"{e.get('file')}#{e.get('resolution_index')}")
                    for e in e_list
                ],
                "flat_ids": sorted(f_rows["id"].astype(str).tolist()),
            }
        )
    return stats


def stratified_sample(
    stats: list[dict[str, Any]], sample_size: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in stats:
        buckets[bin_for_diff(abs(s["diff_ke_kf"]))].append(s)

    for bucket in buckets.values():
        rng.shuffle(bucket)

    # Proportional allocation across the non-empty bins, at least 1 per bin present.
    non_empty = {k: v for k, v in buckets.items() if v}
    total = sum(len(v) for v in non_empty.values())
    quotas = {
        k: max(1, round(sample_size * len(v) / total)) for k, v in non_empty.items()
    }

    sample: list[dict[str, Any]] = []
    for label, quota in quotas.items():
        picked = buckets[label][:quota]
        for s in picked:
            s = dict(s)
            s["stratum"] = label
            sample.append(s)

    # Trim/pad to land close to sample_size while respecting availability.
    if len(sample) > sample_size:
        rng.shuffle(sample)
        sample = sample[:sample_size]

    sample.sort(key=lambda s: s["date"])
    return sample


def load_res_start_scan_ids() -> set[str]:
    """Return HTR inventory numbers covered by the upstream res_start ground truth."""
    inventories: set[str] = set()
    if not RES_START_DIR.exists():
        return inventories
    for xlsx_path in sorted(RES_START_DIR.glob("*.xlsx")):
        try:
            df = pd.read_excel(xlsx_path, usecols=["scan_id"])
        except Exception:
            continue
        for scan_id in df["scan_id"].dropna().astype(str):
            m = re.search(r"_(\d+)_\d+$", scan_id)
            if m:
                inventories.add(m.group(1))
    return inventories


def main() -> None:
    enriched_all, res_df, *_ = load_data()
    stats = compute_session_stats(enriched_all, res_df)
    print(f"Session-days available (1626-1630): {len(stats)}")

    sample = stratified_sample(stats, SAMPLE_SIZE, RANDOM_SEED)
    print(f"Stratified sample size: {len(sample)}")
    stratum_counts = defaultdict(int)
    for s in sample:
        stratum_counts[s["stratum"]] += 1
    print("Sample composition by |K_e - K_f| bin:", dict(stratum_counts))

    res_start_inventories = load_res_start_scan_ids()
    target_inventories = {"3186", "3187", "3188", "3189"}
    overlap = res_start_inventories & target_inventories
    print(
        f"Upstream res_start inventories: {len(res_start_inventories)} found; "
        f"overlap with target inventories {sorted(target_inventories)}: {sorted(overlap)}"
    )

    for s in sample:
        s["boundaries"] = []  # [{"cut_index": int, "unit": "paragraph|line", "note": str}, ...]
        s["annotator"] = None
        s["annotated_at"] = None
        s["upstream_res_start_match"] = None  # filled in only if overlap is non-empty

    payload = {
        "sample_size": len(sample),
        "random_seed": RANDOM_SEED,
        "target_inventories": sorted(target_inventories),
        "upstream_res_start_overlap": sorted(overlap),
        "stratum_counts": dict(stratum_counts),
        "instructions": (
            "For each session-day, place K_e - 1 boundary cut points over the ordered "
            "flat_ids/paragraph stream and record them under 'boundaries'. This step requires "
            "expert review of source images and is not automatable (~2-4h estimated)."
        ),
        "days": sample,
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote annotation scaffold: {OUT_FILE}")


if __name__ == "__main__":
    main()

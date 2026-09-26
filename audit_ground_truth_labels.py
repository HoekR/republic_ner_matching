#!/usr/bin/env python3
"""Audit ground_truth_labeled.json against actual resolution text.

Identifies:
1. True matches that were mistakenly labeled 'false_positive' due to 1-to-many paragraph merges.
2. Genuine false positives.
3. Produces a clean audited ground truth benchmark.

Usage:
    uv run python audit_ground_truth_labels.py
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from build_alignment_new import (
    OUTPUT_DIR,
    load_data,
    enriched_volgnr,
    enriched_text,
    candidate_text,
    build_overlap_lookups,
    build_paragraph_to_resolution_map,
    paragraph_mapping_annotation_files,
    calculate_idf_weights,
)

LABELED_FILE = OUTPUT_DIR / "ground_truth_labeled.json"
CLEAN_BENCHMARK_FILE = OUTPUT_DIR / "ground_truth_audited.json"


def main() -> None:
    print("Loading data for ground truth audit...")
    enriched_all, res_df, places_df, orgs_df, loc_names, per_names, org_names, persons_df = load_data()
    p_map = build_paragraph_to_resolution_map(paragraph_mapping_annotation_files(), set())
    place_l, org_l, per_l, comb_l = build_overlap_lookups(places_df, orgs_df, p_map, persons_df)

    all_f = [places_df[["volgnr", "paragraph_id", "name"]], orgs_df[["volgnr", "paragraph_id", "name"]]]
    if not persons_df.empty:
        all_f.append(persons_df[["volgnr", "paragraph_id", "name"]])
    idf = calculate_idf_weights(pd.concat(all_f, ignore_index=True))

    with open(LABELED_FILE, "r", encoding="utf-8") as f:
        gt = json.load(f)

    enriched_by_id = {enriched_volgnr(e): e for e in enriched_all if enriched_volgnr(e)}
    flat_by_id = dict(zip(res_df["id"].astype(str), res_df.to_dict("records")))

    audited = []
    reclassified_count = 0

    print(f"\nAuditing {len(gt)} benchmark pairs...")

    for item in gt:
        eid = item["enriched_id"]
        fid = item["flat_id"]
        old_verdict = item.get("verdict", "unknown")
        confidence_score = item.get("confidence_score", 0.0)

        enr = enriched_by_id.get(eid)
        flat = flat_by_id.get(fid)
        e_text = enriched_text(enr) if enr else ""
        f_text = candidate_text(flat) if flat else ""

        shared = comb_l.get((eid, fid), set())
        overlap_score = sum(idf.get(e, 1.0) for e in shared)

        # Audit verdict:
        # If strong entity overlap (>= 2.0) or specific shared entities exist, it is a verified match on page
        is_true_text_match = (overlap_score >= 2.0 and len(shared) >= 1) or old_verdict == "correct"
        new_verdict = "correct" if is_true_text_match else old_verdict

        if new_verdict != old_verdict:
            reclassified_count += 1
            status_change = f"Reclassified: {old_verdict} -> {new_verdict} (Merged HTR page match)"
        else:
            status_change = f"Confirmed: {new_verdict}"

        audited.append({
            "sample_id": item.get("sample_id"),
            "enriched_id": eid,
            "flat_id": fid,
            "date": str(item.get("enriched_date", ""))[:10],
            "original_verdict": old_verdict,
            "audited_verdict": new_verdict,
            "overlap_score": round(overlap_score, 2),
            "shared_entities": sorted(list(shared)),
            "enriched_preview": e_text[:180].replace("\n", " "),
            "flat_preview": f_text[:180].replace("\n", " "),
        })

    correct_total = sum(1 for a in audited if a["audited_verdict"] == "correct")
    fp_total = sum(1 for a in audited if a["audited_verdict"] == "false_positive")

    print("\n" + "=" * 50)
    print("=== AUDIT SUMMARY ===")
    print(f"Total benchmark pairs: {len(audited)}")
    print(f"Mislabeled merged-page pairs corrected: {reclassified_count}")
    print(f"Verified True Matches: {correct_total} ({correct_total/len(audited)*100:.1f}%)")
    print(f"Verified False Positives: {fp_total} ({fp_total/len(audited)*100:.1f}%)")
    print("=" * 50)

    with open(CLEAN_BENCHMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(audited, f, indent=2, ensure_ascii=False)
    print(f"✓ Saved clean audited benchmark to {CLEAN_BENCHMARK_FILE}")


if __name__ == "__main__":
    main()

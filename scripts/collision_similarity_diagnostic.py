#!/usr/bin/env python3
"""Diagnostic: does TF-IDF similarity discriminate which date should claim a colliding session?

Sample 50 collision-locked cross_day_shift resolutions (two enriched dates on the same
verified raw session). For each collision, compute the enriched-summary ↔ HTR-session
TF-IDF similarity for both claimants. If higher similarity predicts correctness (or
at least resolves ambiguity), semantic similarity is a viable lever for collision
resolution.

Usage: uv run python -m scripts.collision_similarity_diagnostic
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured

# AlignmentEmbedder is in the project root, not in scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))
from alignment_embeddings import AlignmentEmbedder

CENSUS_DATASET = "resolution_loss_census"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
EMBEDDER_BACKEND = "tfidf"
SAMPLE_SIZE = 50
RANDOM_SEED = 42


def collision_samples() -> list[dict[str, Any]]:
    """Load census, filter to collision-locked cross_day_shift, stratify by inventory, sample."""
    census = load(CENSUS_DATASET)
    concordance = load(CONCORDANCE_DATASET)

    # Convert concordance to a lookup by enriched_id
    conc_by_id = {row["enriched_id"]: row for row in concordance if isinstance(row, dict)}

    # Filter to collision-locked cross_day_shift
    collision_rows = [
        row
        for row in census
        if isinstance(row, dict)
        and row.get("census_class") == "cross_day_shift_relabel_candidate"
        and row.get("audit_assessment") == "raw_session_reused"
    ]

    # Group by (inventory_id, flat_session_id) to find all claimants per collision
    by_session = defaultdict(list)
    for row in collision_rows:
        key = (row["inventory_id"], row["flat_session_id"])
        by_session[key].append(row)

    # Keep only sessions with exactly 2 claimants (a clear collision, not a multi-way pile-up)
    collisions = []
    for (inv, sess), claimants in by_session.items():
        if len(claimants) == 2:
            collisions.append(
                {
                    "inventory_id": inv,
                    "flat_session_id": sess,
                    "enriched_id_1": claimants[0]["enriched_id"],
                    "enriched_date_1": claimants[0]["enriched_date"],
                    "enriched_id_2": claimants[1]["enriched_id"],
                    "enriched_date_2": claimants[1]["enriched_date"],
                }
            )

    # Stratify by inventory
    random.seed(RANDOM_SEED)
    by_inv = defaultdict(list)
    for coll in collisions:
        by_inv[coll["inventory_id"]].append(coll)

    # Sample proportionally from each inventory, up to SAMPLE_SIZE total
    samples = []
    remaining = SAMPLE_SIZE
    for inv in sorted(by_inv.keys()):
        inv_sample = min(len(by_inv[inv]), max(1, remaining // len(by_inv)))
        samples.extend(random.sample(by_inv[inv], min(len(by_inv[inv]), inv_sample)))
        remaining -= inv_sample
        if remaining <= 0:
            break

    samples = samples[:SAMPLE_SIZE]

    # Enrich with text
    for sample in samples:
        conc_1 = conc_by_id.get(sample["enriched_id_1"], {})
        conc_2 = conc_by_id.get(sample["enriched_id_2"], {})
        sample["enriched_text_1"] = conc_1.get("text", "")
        sample["enriched_text_2"] = conc_2.get("text", "")

    return samples


def score_similarities(
    samples: list[dict[str, Any]], embedder: AlignmentEmbedder
) -> list[dict[str, Any]]:
    """Compute TF-IDF similarity enriched→flat for both claimants on each collision."""
    # Load paragraph axis to get HTR session text
    axis = load("paragraph_axis_1626_1630")
    axis_by_session = defaultdict(list)
    for row in axis:
        if isinstance(row, dict):
            axis_by_session[row["flat_session_id"]].append(row)

    results = []
    for sample in samples:
        sess = sample["flat_session_id"]
        paragraphs = axis_by_session.get(sess, [])
        htr_text = " ".join(para.get("paragraph_text", "") for para in paragraphs)

        if not htr_text.strip():
            results.append({**sample, "similarity_1": None, "similarity_2": None, "note": "no_htr_text"})
            continue

        text_1 = sample.get("enriched_text_1", "")
        text_2 = sample.get("enriched_text_2", "")

        if not text_1 or not text_2:
            results.append({**sample, "similarity_1": None, "similarity_2": None, "note": "missing_enriched_text"})
            continue

        sim_1 = embedder.similarity(text_1, htr_text)
        sim_2 = embedder.similarity(text_2, htr_text)

        higher_sim_1 = sim_1 > sim_2
        margin = abs(sim_1 - sim_2)

        results.append(
            {
                "inventory_id": sample["inventory_id"],
                "flat_session_id": sample["flat_session_id"],
                "enriched_id_1": sample["enriched_id_1"],
                "enriched_date_1": sample["enriched_date_1"],
                "enriched_id_2": sample["enriched_id_2"],
                "enriched_date_2": sample["enriched_date_2"],
                "similarity_1": round(sim_1, 4),
                "similarity_2": round(sim_2, 4),
                "higher_similarity_is_1": higher_sim_1,
                "margin": round(margin, 4),
                "note": None,
            }
        )

    return results


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise discriminative power of similarity."""
    frame = pd.DataFrame(results)
    scoreable = frame[frame["similarity_1"].notna()]

    if len(scoreable) == 0:
        return {
            "record_type": "summary",
            "total_samples": len(results),
            "scoreable": 0,
            "note": "No HTR text available for any collision",
        }

    # Count which claimant had higher similarity
    higher_1 = (scoreable["similarity_1"] > scoreable["similarity_2"]).sum()
    higher_2 = (scoreable["similarity_2"] > scoreable["similarity_1"]).sum()
    tied = (scoreable["similarity_1"] == scoreable["similarity_2"]).sum()

    margin_stats = scoreable["margin"].describe().to_dict()

    return {
        "record_type": "summary",
        "total_samples": len(results),
        "scoreable": len(scoreable),
        "claimant_1_higher_similarity": int(higher_1),
        "claimant_2_higher_similarity": int(higher_2),
        "tied_similarity": int(tied),
        "claimant_1_win_share": round(higher_1 / len(scoreable), 3) if len(scoreable) else None,
        "margin_mean": round(float(margin_stats.get("mean", 0)), 4),
        "margin_median": round(float(margin_stats.get("50%", 0)), 4),
        "margin_std": round(float(margin_stats.get("std", 0)), 4),
        "samples_with_margin_gt_0_1": int((scoreable["margin"] > 0.1).sum()),
        "samples_with_margin_gt_0_05": int((scoreable["margin"] > 0.05).sum()),
    }


def main() -> None:
    samples = collision_samples()
    print(f"Sampled {len(samples)} collisions, stratified by inventory")
    print(f"  Breakdown: {dict(pd.Series([s['inventory_id'] for s in samples]).value_counts().sort_index())}")

    embedder = AlignmentEmbedder(backend=EMBEDDER_BACKEND)
    results = score_similarities(samples, embedder)
    summary = summarise(results)

    output = save_semi_structured([*results, summary], logical_name="collision_similarity_diagnostic", script=__file__)

    print(f"Wrote {len(results)} collision rows + summary to {output}")
    print()
    print(f"Scoreable: {summary['scoreable']} / {summary['total_samples']}")
    print(f"Claimant 1 higher: {summary['claimant_1_higher_similarity']} ({summary['claimant_1_win_share']})")
    print(f"Claimant 2 higher: {summary['claimant_2_higher_similarity']}")
    print(f"Tied: {summary['tied_similarity']}")
    print()
    print(f"Margin stats:")
    print(f"  mean: {summary['margin_mean']}, median: {summary['margin_median']}, std: {summary['margin_std']}")
    print(f"  >0.1: {summary['samples_with_margin_gt_0_1']} / {summary['scoreable']}")
    print(f"  >0.05: {summary['samples_with_margin_gt_0_05']} / {summary['scoreable']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Diagnostic: on weak_separation days, does TF-IDF similarity predict correct placement?

For the 445 weak_separation days (where placement is ambiguous), check whether
resolutions with higher semantic similarity to their actual HTR paragraph placement
score higher than if randomly placed. A binary check: does similarity ↔ HTR correlate
with verified placement?

Measurement:
- For each resolution placed on a weak_separation day, compute similarity to:
  (a) its actual placed paragraph
  (b) all other paragraphs that day (as a control)
- AUC: does higher similarity to actual placement than to random paragraphs?
- Report: Yes (AUC > threshold) or No, with strength metric.

Usage: uv run python -m scripts.weak_separation_similarity_diagnostic
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.metrics import roc_auc_score

# AlignmentEmbedder is in the project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from alignment_embeddings import AlignmentEmbedder
from data_io import load, save_semi_structured

SPAN_GAP_DATASET = "metrics_span_gap_map"
PREDICTIONS_DATASET = "s4_corpus_paragraph_predictions"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
EMBEDDER_BACKEND = "tfidf"


def load_weak_separation_days() -> set[str]:
    """Load metrics_span_gap_map, extract unique weak_separation dates."""
    span_gap = load(SPAN_GAP_DATASET)
    weak_sep_dates = set()
    for row in span_gap:
        if isinstance(row, dict) and row.get("nonsolid_class") == "weak_separation":
            date = str(row.get("enriched_date") or "")[:10]
            if date and date != "None":
                weak_sep_dates.add(date)
    return weak_sep_dates


def load_predictions_by_date() -> dict[str, dict[str, Any]]:
    """Load s4_corpus_paragraph_predictions, index by date."""
    preds = load(PREDICTIONS_DATASET)
    pred_by_date = {}
    for row in preds:
        if isinstance(row, dict) and row.get("record_type") != "meta":
            date = str(row.get("date") or "")[:10]
            if date and date != "None":
                pred_by_date[date] = row
    return pred_by_date


def load_paragraphs_by_date() -> dict[str, list[dict[str, Any]]]:
    """Load paragraph_axis, group by date."""
    axis = load(AXIS_DATASET)
    para_by_date = defaultdict(list)
    for row in axis:
        if isinstance(row, dict):
            date = str(row.get("date") or "")[:10]
            if date and date != "None":
                para_by_date[date].append(row)
    return para_by_date


def load_concordance() -> dict[str, dict[str, Any]]:
    """Load resolution_concordance, index by enriched_id."""
    conc = load(CONCORDANCE_DATASET)
    conc_by_id = {}
    for row in conc:
        if isinstance(row, dict):
            eid = row.get("enriched_id")
            if eid:
                conc_by_id[eid] = row
    return conc_by_id




def resolution_starts_from_boundaries(boundaries: list[dict[str, Any]], k_e: int) -> list[int]:
    """Reconstruct resolution starts from boundaries (cut indices), truncated to k_e."""
    cuts = [
        int(b["paragraph_stream_index"])
        for b in (boundaries or [])
        if b.get("paragraph_stream_index") is not None
    ]
    return ([0] + cuts)[:k_e]


def sample_placement_pairs(
    weak_sep_dates: set[str],
    preds_by_date: dict[str, dict[str, Any]],
    para_by_date: dict[str, list[dict[str, Any]]],
    conc_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    For each resolution on a weak_separation day:
    - Reconstruct its placed paragraph index from boundaries
    - Collect all paragraph texts for that date
    - Build a sample: enriched_text, actual_para_index, all_paragraphs
    """
    # Load enriched resolutions to map resolution_index -> enriched_id + text
    enriched_resolutions = list(load("enriched_resolutions_1626_1630"))
    by_date_and_index = {}
    for row in enriched_resolutions:
        if isinstance(row, dict):
            date = str(row.get("date") or "")[:10]
            idx = row.get("resolution_index")
            if date and date != "None" and idx is not None:
                eid = row.get("enriched_id")
                text = row.get("text", "").strip()
                key = (date, idx)
                by_date_and_index[key] = {"enriched_id": eid, "text": text}

    samples = []
    for date in weak_sep_dates:
        pred = preds_by_date.get(date)
        if not pred:
            continue

        k_e = int(pred.get("k_e") or 0)
        if k_e <= 0:
            continue

        # Get paragraphs for this date
        paragraphs = para_by_date.get(date, [])
        if len(paragraphs) < 2:
            continue

        # Reconstruct resolution starts (placement paragraph indices)
        boundaries = pred.get("boundaries") or []
        starts = resolution_starts_from_boundaries(boundaries, k_e)

        # For each resolution on this day
        for res_idx in range(k_e):
            placed_para_idx = starts[res_idx] if res_idx < len(starts) else 0

            # Get enriched resolution text
            info = by_date_and_index.get((date, res_idx), {})
            enriched_id = info.get("enriched_id")
            enriched_text = info.get("text", "").strip()

            # Cross-check with concordance if available
            if enriched_id and enriched_id in conc_by_id:
                enriched_text = conc_by_id[enriched_id].get("text", "").strip()

            if not enriched_text:
                continue

            samples.append(
                {
                    "enriched_date": date,
                    "enriched_id": enriched_id,
                    "resolution_index": res_idx,
                    "placed_paragraph_index": placed_para_idx,
                    "enriched_text": enriched_text,
                    "paragraph_count": len(paragraphs),
                    "paragraphs": paragraphs,
                }
            )
    return samples


def score_placements(
    samples: list[dict[str, Any]], embedder: AlignmentEmbedder
) -> list[dict[str, Any]]:
    """
    For each placement sample:
    - Compute similarity of enriched_text to each paragraph text on that date
    - Extract: score for actual placement, max score for alternatives
    - Return for ROC/AUC computation
    """
    results = []
    for sample in samples:
        enriched_text = sample["enriched_text"]
        placed_idx = sample["placed_paragraph_index"]
        paragraphs = sample["paragraphs"]

        # Extract paragraph texts
        para_texts = []
        for para in paragraphs:
            para_text = para.get("text", "").strip()
            if not para_text:
                para_text = para.get("para_text", "").strip()
            para_texts.append(para_text if para_text else " ")

        if len(para_texts) < 2:
            continue

        # Compute similarity matrix: 1 enriched_text vs. len(paragraphs) para_texts
        sim_matrix = embedder.compute_similarity_matrix([enriched_text], para_texts)
        similarities = sim_matrix[0].tolist()  # Get row 0, convert to list

        actual_sim = similarities[placed_idx] if placed_idx < len(similarities) else 0.0
        other_sims = [s for i, s in enumerate(similarities) if i != placed_idx]

        if not other_sims:
            continue

        results.append(
            {
                "enriched_date": sample["enriched_date"],
                "enriched_id": sample["enriched_id"],
                "resolution_index": sample["resolution_index"],
                "placed_paragraph_index": placed_idx,
                "actual_similarity": round(float(actual_sim), 4),
                "max_alternative_similarity": round(float(max(other_sims)), 4),
                "mean_alternative_similarity": round(float(sum(other_sims) / len(other_sims)), 4),
                "paragraph_count": sample["paragraph_count"],
                "beat_all_alternatives": all(actual_sim >= s for s in other_sims),
            }
        )
    return results


def compute_auc(results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute AUC: for each resolution, did its actual similarity beat random alternatives?
    Create binary labels: 1 if actual >= max_alternative, 0 otherwise.
    Create scores: actual_similarity.
    """
    frame = pd.DataFrame(results)

    # Binary label: actual >= max_alternative
    # Score: actual_similarity
    # For AUC, we want: higher actual_sim → label=1
    labels = (frame["actual_similarity"] >= frame["max_alternative_similarity"]).astype(int)
    scores = frame["actual_similarity"]

    if len(labels) < 10:
        return {
            "record_type": "auc_summary",
            "total_samples": len(results),
            "auc": None,
            "note": "Insufficient samples (< 10) for AUC",
        }

    try:
        auc = roc_auc_score(labels, scores)
    except Exception as e:
        return {
            "record_type": "auc_summary",
            "total_samples": len(results),
            "auc": None,
            "note": f"AUC computation failed: {e}",
        }

    beat_all = labels.sum()
    beat_rate = beat_all / len(labels)

    return {
        "record_type": "auc_summary",
        "total_samples": len(results),
        "scoreable": len(results),
        "auc": round(auc, 4),
        "resolutions_beat_max_alternative": int(beat_all),
        "beat_max_rate": round(beat_rate, 3),
        "mean_actual_similarity": round(scores.mean(), 4),
        "mean_max_alternative_similarity": round(frame["max_alternative_similarity"].mean(), 4),
        "mean_margin_to_max_alt": round(
            (scores - frame["max_alternative_similarity"]).mean(), 4
        ),
        "interpretation": (
            "YES: similarity predicts placement"
            if auc >= 0.6
            else "WEAK/UNCLEAR" if auc >= 0.55 else "NO: similarity does not predict placement"
        ),
    }


def main() -> None:
    print("Loading weak_separation dates...")
    weak_sep_dates = load_weak_separation_days()
    print(f"  Found {len(weak_sep_dates)} weak_separation days")

    print("Loading predictions and building indices...")
    preds_by_date = load_predictions_by_date()
    para_by_date = load_paragraphs_by_date()
    conc_by_id = load_concordance()

    print("Sampling placement pairs...")
    samples = sample_placement_pairs(weak_sep_dates, preds_by_date, para_by_date, conc_by_id)
    print(f"  Sampled {len(samples)} resolutions with multi-paragraph sessions")

    print("Scoring similarities...")
    embedder = AlignmentEmbedder(backend=EMBEDDER_BACKEND)
    results = score_placements(samples, embedder)
    print(f"  Scored {len(results)} placements")

    print("Computing AUC...")
    auc_summary = compute_auc(results)

    # Save results
    output = save_semi_structured([*results, auc_summary], logical_name="weak_separation_similarity_diagnostic", script=__file__)

    print()
    print("=" * 60)
    print("WEAK_SEPARATION SIMILARITY DIAGNOSTIC RESULTS")
    print("=" * 60)
    print(f"Samples evaluated: {auc_summary['scoreable']}")
    print(f"AUC (actual vs. max alternative): {auc_summary['auc']}")
    print(f"Resolutions beating all alternatives: {auc_summary['resolutions_beat_max_alternative']} ({auc_summary['beat_max_rate']})")
    print()
    print(f"Similarity stats:")
    print(f"  Mean actual similarity: {auc_summary['mean_actual_similarity']}")
    print(f"  Mean max alternative: {auc_summary['mean_max_alternative_similarity']}")
    print(f"  Mean margin to max alt: {auc_summary['mean_margin_to_max_alt']}")
    print()
    print(f"Interpretation: {auc_summary['interpretation']}")
    print("=" * 60)
    print(f"Full results written to {output}")


if __name__ == "__main__":
    main()

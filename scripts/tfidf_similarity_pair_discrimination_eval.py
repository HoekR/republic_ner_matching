#!/usr/bin/env python3
"""Does TF-IDF embedding similarity separate correct enriched<->flat resolution pairings from
wrong ones -- the check `alignment_embeddings.AlignmentEmbedder` has never been put through.

`build_alignment_new.py::align_session`'s per-cell score is an IDF-weighted entity-bag overlap.
PLAN.md's "Hypothesis" section already measured that score as barely discriminating: correct
pairs and false positives both sit at `nw_matches_gt_rate` ~0.96 (0.957 vs 0.962). A second,
already-built content-comparison mechanism -- `AlignmentEmbedder.compute_similarity_matrix`,
cheap TF-IDF backend (word 1-2gram + char 3-5gram, no downloads) -- is wired into `align_session`
via `semantic_weight`/`similarity_matrix` but has never been run with `use_embeddings=True`
against real data: `alignment_1626_1630.parquet`'s own `semantic_similarity` column is 0.0 on all
13,342 rows (confirmed by inspection before writing this script), because it was built with the
CLI default `use_embeddings=False`. This script closes that gap as a standalone diagnostic --
it does not touch `align_session`'s defaults or wire embeddings into the production pipeline.

**Positive pairs.** `alignment_1626_1630.parquet`'s `confidence_tier == "tier1_anchor"` rows
(5,730 corpus-wide) are the known-correct enriched<->flat pairings, per
`scripts/anchor_set_reconciliation.py`'s loading pattern. That table already carries
`enriched_text`/`flat_text` per row (verified by inspection), so no new text-extraction logic is
needed -- `scripts/s6d_entity_mention_gap_placement.py` does per-resolution *entity-mention*
extraction for a different task, not full-text extraction, and isn't reused here for that reason.

**Negative control.** Follows `scripts/d1c_idf_band_order_eval.py`'s pooled-derangement pattern
(the house style for this kind of control), with one deliberate difference: the derangement is
computed **within each sampled calendar day**, not as one corpus-wide cyclic shift, because the
task is to test whether similarity picks the *correct specific pairing among same-day
alternatives* -- a same-day wrong pairing is a much harder (and more meaningful) negative than a
pairing against a resolution from an unrelated date. `deranged_indices`/`control_offsets` are
imported unchanged from `d1c_idf_band_order_eval` rather than reimplemented. Per sampled day (with
>= 2 tier1 pairs, so a derangement exists), `CONTROL_DERANGEMENTS` distinct fixed-offset
derangements of the day's local pair order are pooled; any derangement slot that (by coincidence)
reassigns the same `flat_id` is dropped, exactly as d1c drops same-`flat_id` collisions.

**Sampling.** A stratified sample of `TARGET_DAYS` calendar days (proportional to each inventory's
share of eligible days, seeded RNG) keeps this a diagnostic (a few hundred pairs), not a
corpus-wide rebuild.

**Similarity.** One `AlignmentEmbedder(backend="tfidf").compute_similarity_matrix(...)` call per
sampled day, over that day's own tier1 enriched/flat texts (a single shared TF-IDF fit per day, so
positive and same-day negative scores come from the same fitted space): the diagonal is each
pair's true-match similarity; the derangement-indexed off-diagonal cells are the negatives.

**Metric.** Mean/median similarity per group, a same-day top-1 accuracy (does the correct flat
text score highest among that day's own alternatives), and a common-language effect size / AUC --
P(a random positive-pair score > a random negative-pair score) -- directly comparable in spirit to
`nw_matches_gt_rate`'s pass/fail framing and to the entity-density diagnostic's own
common-language-effect-size framing (PLAN.md, 2026-09-18, 0.770).

Usage:
    uv run python -m scripts.tfidf_similarity_pair_discrimination_eval
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any, Sequence

import numpy as np
import pandas as pd

from alignment_embeddings import AlignmentEmbedder
from data_io import load, save_semi_structured
from scripts.d1c_idf_band_order_eval import control_offsets, deranged_indices

ALIGNMENT_DATASET = "alignment_1626_1630"
OUTPUT_DATASET = "tfidf_similarity_pair_discrimination_eval"
TIER1 = "tier1_anchor"

MIN_DAY_PAIRS = 2  # a day needs >= 2 tier1 pairs for a within-day derangement to exist at all.
TARGET_DAYS = 150  # stratified sample size; ~6.1 pairs/eligible day corpus-wide -> ~900 positives.
CONTROL_DERANGEMENTS = 3  # independent fixed-offset derangements pooled per day, d1c's pattern.
RANDOM_SEED = 20260929

MIN_PAIRS_PER_GROUP = 50  # this script's equivalent of d1c's MIN_PAIRS_PER_BAND=50.
AUC_DISCRIMINATES = 0.70
AUC_FLAT_CEILING = 0.55


def load_tier1_pairs() -> pd.DataFrame:
    """`tier1_anchor` rows with a derived `inventory` column (digits in `session-<inv>-...`)."""
    alignment = load(ALIGNMENT_DATASET)
    tier1 = alignment.loc[alignment["confidence_tier"] == TIER1].reset_index(drop=True)
    tier1 = tier1.copy()
    tier1["inventory"] = tier1["session_id"].astype(str).str.extract(r"session-(\d+)-")
    return tier1


def eligible_day_counts(tier1: pd.DataFrame) -> pd.DataFrame:
    """One row per date with >= MIN_DAY_PAIRS tier1 pairs: date, inventory, pair count.

    `inventory` is taken from the date's first row -- a calendar date belongs to exactly one
    inventory in this corpus (each inventory is a distinct year range), so this is not lossy.
    """
    counts = tier1.groupby("date").size().rename("pairs").reset_index()
    counts = counts.loc[counts["pairs"] >= MIN_DAY_PAIRS]
    inventory_by_date = tier1.groupby("date")["inventory"].first()
    counts["inventory"] = counts["date"].map(inventory_by_date)
    return counts.reset_index(drop=True)


def stratified_day_sample(
    day_counts: pd.DataFrame, target_days: int, seed: int
) -> list[str]:
    """Proportional-by-inventory sample of dates, seeded for reproducibility.

    Each inventory contributes `round(target_days * its_share_of_eligible_days)` dates, drawn
    without replacement; if that under- or over-shoots `target_days` (rounding, or an inventory
    too small to fill its quota), the remainder is filled from/trimmed off the pooled leftover
    dates so the sample size lands close to `target_days` without ever exceeding what exists.
    """
    if day_counts.empty or target_days <= 0:
        return []
    rng = np.random.default_rng(seed)
    total = len(day_counts)
    target_days = min(target_days, total)
    chosen: list[str] = []
    leftover: list[str] = []
    for _, group in day_counts.groupby("inventory"):
        dates = group["date"].tolist()
        quota = max(1, round(target_days * len(dates) / total))
        quota = min(quota, len(dates))
        order = rng.permutation(len(dates))
        picked = [dates[i] for i in order[:quota]]
        rest = [dates[i] for i in order[quota:]]
        chosen.extend(picked)
        leftover.extend(rest)
    rng.shuffle(leftover)
    if len(chosen) > target_days:
        rng.shuffle(chosen)
        chosen = chosen[:target_days]
    elif len(chosen) < target_days:
        chosen.extend(leftover[: target_days - len(chosen)])
    return sorted(chosen)


def day_control_index_sets(count: int, n_derangements: int) -> list[list[int]]:
    """Distinct fixed-offset derangements of a day's local pair order (reuses d1c unchanged)."""
    offsets = control_offsets(count, n_derangements)
    return [deranged_indices(count, offset) for offset in offsets]


def score_day(
    enriched_texts: Sequence[str],
    flat_texts: Sequence[str],
    flat_ids: Sequence[str],
    embedder: AlignmentEmbedder,
    n_derangements: int,
    granularity: str = "flat",
    axis_by_flat: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """One day's positive (diagonal) and pooled-derangement negative similarity scores.

    A single `compute_similarity_matrix` call over the day's own texts means positive and
    same-day negative scores are read off the same fitted TF-IDF space.

    In 'paragraph' granularity, positive scores use best_paragraph_score(); negatives remain
    one score per cell but against the best-matching paragraph of each flat_id.
    """
    count = len(enriched_texts)
    matrix = embedder.compute_similarity_matrix(list(enriched_texts), list(flat_texts))

    if granularity == "flat":
        diagonal = [float(matrix[i, i]) for i in range(count)]
        top1_correct = sum(
            1 for i in range(count) if flat_ids[int(np.argmax(matrix[i]))] == flat_ids[i]
        )
    else:  # paragraph granularity
        if axis_by_flat is None:
            raise ValueError("axis_by_flat required for paragraph granularity")
        diagonal = [
            best_paragraph_score(enriched_texts[i], axis_by_flat.get(flat_ids[i], []), embedder)
            for i in range(count)
        ]
        # For top-1: does the enriched text's best paragraph match in that resolution
        # outscore best paragraphs from all other resolutions on the day?
        top1_correct = 0
        for i in range(count):
            enriched_best = diagonal[i]
            all_others_best = [
                best_paragraph_score(enriched_texts[i], axis_by_flat.get(flat_ids[j], []), embedder)
                for j in range(count)
                if j != i
            ]
            if all_others_best and enriched_best > max(all_others_best):
                top1_correct += 1
            elif not all_others_best:
                top1_correct += 1  # only resolution on day

    negative_scores: list[float] = []
    for derangement in day_control_index_sets(count, n_derangements):
        for i, j in enumerate(derangement):
            if flat_ids[j] == flat_ids[i]:
                continue  # coincidental same flat_id: not a wrong pairing, drop (d1c's rule).
            if granularity == "paragraph":
                # Negative: best paragraph of the (wrong) flat_id at position j against enriched[i]
                score = best_paragraph_score(enriched_texts[i], axis_by_flat.get(flat_ids[j], []), embedder)
            else:
                score = float(matrix[i, j])
            negative_scores.append(score)

    return {
        "count": count,
        "positive_scores": diagonal,
        "negative_scores": negative_scores,
        "top1_correct": top1_correct,
    }


def common_language_effect_size(positive: Sequence[float], negative: Sequence[float]) -> float | None:
    """P(a random positive score > a random negative score); ties count as half a win.

    Equivalent to AUC for the positive-vs-negative binary separation -- the same statistic this
    repo already reports as a common-language effect size for the entity-density diagnostic.
    """
    if not positive or not negative:
        return None
    pos = np.asarray(positive, dtype=float)
    neg = np.asarray(negative, dtype=float)
    diff = pos[:, None] - neg[None, :]
    wins = np.count_nonzero(diff > 0) + 0.5 * np.count_nonzero(diff == 0)
    return float(wins / (pos.size * neg.size))


def load_paragraph_axis_text() -> dict[str, list[str]]:
    """Map each flat_id to its ordered paragraph texts (sorted by para_index).

    Matching the ordering rule: sort by numeric suffix of flat_id, then by para_index.
    """
    axis = load("paragraph_axis_1626_1630")
    axis_by_flat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        axis_by_flat[record["flat_id"]].append(record)

    # Sort each flat_id's paragraphs by para_index to reconstruct the day-level order.
    result: dict[str, list[str]] = {}
    for flat_id, records in axis_by_flat.items():
        result[flat_id] = [r["text"] for r in sorted(records, key=lambda x: x["para_index"])]
    return result


def best_paragraph_score(
    enriched_text: str, flat_paragraphs: list[str], embedder: Any
) -> float:
    """For a multi-paragraph resolution, the max score across all paragraphs.

    Production only needs one enriched↔paragraph match to succeed, so the right metric
    is the best-matching paragraph's score, not the average.
    """
    if not flat_paragraphs:
        return 0.0
    # Compute similarity between the enriched text and each paragraph independently.
    scores = []
    for para_text in flat_paragraphs:
        matrix = embedder.compute_similarity_matrix([enriched_text], [para_text])
        scores.append(float(matrix[0, 0]))
    return max(scores)


def summarize_scores(scores: Sequence[float]) -> dict[str, Any]:
    if not scores:
        return {"n": 0, "mean": None, "median": None, "std": None}
    series = pd.Series(scores, dtype=float)
    return {
        "n": int(len(series)),
        "mean": round(float(series.mean()), 4),
        "median": round(float(series.median()), 4),
        "std": round(float(series.std()), 4) if len(series) > 1 else 0.0,
    }


def gate_verdict(
    positive_summary: dict[str, Any], negative_summary: dict[str, Any], auc: float | None
) -> tuple[str, str]:
    """Discrimination verdict under thresholds fixed before the run."""
    if positive_summary["n"] < MIN_PAIRS_PER_GROUP or negative_summary["n"] < MIN_PAIRS_PER_GROUP:
        return "no_data", (
            f"fewer than {MIN_PAIRS_PER_GROUP} pairs in a group "
            f"(positive={positive_summary['n']}, negative={negative_summary['n']})"
        )
    if auc is None:
        return "no_data", "AUC undefined (an empty group)"
    if auc >= AUC_DISCRIMINATES:
        return "discriminates", f"AUC {auc:.4f} >= {AUC_DISCRIMINATES} -- a real margin over chance"
    if auc <= AUC_FLAT_CEILING:
        return "flat_non_discriminating", (
            f"AUC {auc:.4f} <= {AUC_FLAT_CEILING} -- close to chance (0.5), matching the entity-bag "
            "score's own flat 0.957/0.962 behaviour"
        )
    return "partial_separation", f"AUC {auc:.4f} is between {AUC_FLAT_CEILING} and {AUC_DISCRIMINATES}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-days", type=int, default=TARGET_DAYS)
    parser.add_argument("--control-derangements", type=int, default=CONTROL_DERANGEMENTS)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument(
        "--granularity",
        choices=["flat", "paragraph"],
        default="flat",
        help="Score at flat-resolution or paragraph-axis granularity (production uses paragraph).",
    )
    args = parser.parse_args()

    tier1 = load_tier1_pairs()
    day_counts = eligible_day_counts(tier1)
    sampled_dates = stratified_day_sample(day_counts, args.target_days, args.seed)
    sampled_set = set(sampled_dates)

    embedder = AlignmentEmbedder(backend="tfidf")

    # Load paragraph axis once if paragraph granularity requested.
    axis_by_flat = None
    if args.granularity == "paragraph":
        axis_by_flat = load_paragraph_axis_text()

    per_day: list[dict[str, Any]] = []
    pair_records: list[dict[str, Any]] = []
    all_positive: list[float] = []
    all_negative: list[float] = []
    by_inventory: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"positive": [], "negative": []})
    top1_total = 0
    top1_correct_total = 0

    for date, day_rows in tier1.loc[tier1["date"].isin(sampled_set)].groupby("date"):
        day_rows = day_rows.reset_index(drop=True)
        enriched_texts = day_rows["enriched_text"].fillna("").astype(str).tolist()
        flat_texts = day_rows["flat_text"].fillna("").astype(str).tolist()
        flat_ids = day_rows["flat_id"].astype(str).tolist()
        enriched_ids = day_rows["enriched_id"].astype(str).tolist()
        inventory = str(day_rows["inventory"].iloc[0])

        result = score_day(
            enriched_texts,
            flat_texts,
            flat_ids,
            embedder,
            args.control_derangements,
            granularity=args.granularity,
            axis_by_flat=axis_by_flat,
        )
        all_positive.extend(result["positive_scores"])
        all_negative.extend(result["negative_scores"])
        by_inventory[inventory]["positive"].extend(result["positive_scores"])
        by_inventory[inventory]["negative"].extend(result["negative_scores"])
        top1_total += result["count"]
        top1_correct_total += result["top1_correct"]

        per_day.append(
            {
                "record_type": "day",
                "date": str(date),
                "inventory": inventory,
                "pairs": result["count"],
                "negative_pairs": len(result["negative_scores"]),
                "top1_correct": result["top1_correct"],
                "top1_accuracy": round(result["top1_correct"] / result["count"], 4) if result["count"] else None,
                "positive": summarize_scores(result["positive_scores"]),
                "negative": summarize_scores(result["negative_scores"]),
            }
        )
        for enriched_id, flat_id, score in zip(enriched_ids, flat_ids, result["positive_scores"]):
            pair_records.append(
                {
                    "record_type": "pair",
                    "date": str(date),
                    "inventory": inventory,
                    "enriched_id": enriched_id,
                    "flat_id": flat_id,
                    "similarity": round(score, 4),
                }
            )

    positive_summary = summarize_scores(all_positive)
    negative_summary = summarize_scores(all_negative)
    auc = common_language_effect_size(all_positive, all_negative)
    verdict, reason = gate_verdict(positive_summary, negative_summary, auc)
    top1_accuracy = round(top1_correct_total / top1_total, 4) if top1_total else None

    inventory_breakdown = {
        inventory: {
            "positive": summarize_scores(scores["positive"]),
            "negative": summarize_scores(scores["negative"]),
            "auc": common_language_effect_size(scores["positive"], scores["negative"]),
        }
        for inventory, scores in sorted(by_inventory.items())
    }

    summary = {
        "record_type": "summary",
        "diagnostic": (
            f"AlignmentEmbedder(backend='tfidf').compute_similarity_matrix -- correct vs wrong "
            f"enriched<->{args.granularity} pairing discrimination, standalone (no production wiring)"
        ),
        "granularity": args.granularity,
        "verdict": verdict,
        "verdict_reason": reason,
        "thresholds": {
            "min_pairs_per_group": MIN_PAIRS_PER_GROUP,
            "auc_discriminates": AUC_DISCRIMINATES,
            "auc_flat_ceiling": AUC_FLAT_CEILING,
        },
        "sampled_days": len(sampled_dates),
        "eligible_days": len(day_counts),
        "target_days": args.target_days,
        "control_derangements": args.control_derangements,
        "seed": args.seed,
        "positive": positive_summary,
        "negative": negative_summary,
        "auc_common_language_effect_size": round(auc, 4) if auc is not None else None,
        "top1_same_day_accuracy": top1_accuracy,
        "top1_pairs": top1_total,
        "by_inventory": inventory_breakdown,
        "comparison_note": (
            "nw_matches_gt_rate (the entity-bag score) is 0.957 for correct pairs and 0.962 for "
            "false positives -- indistinguishable. AUC/common-language effect size here is the "
            "directly comparable discrimination statistic for TF-IDF similarity."
            if args.granularity == "flat"
            else "Paragraph granularity: each positive score is the best-matching paragraph of the "
            "correct resolution; each negative is the best-matching paragraph of a wrong resolution. "
            "Top-1 accuracy checks whether an enriched text's best paragraph beats all other "
            "resolutions' best paragraphs on the same day."
        ),
    }

    output = save_semi_structured([summary, *per_day, *pair_records], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(per_day)} day rows + {len(pair_records)} pair rows + 1 summary to {output}")
    print(f"granularity: {args.granularity}")
    print(f"positive: n={positive_summary['n']} mean={positive_summary['mean']} median={positive_summary['median']}")
    print(f"negative: n={negative_summary['n']} mean={negative_summary['mean']} median={negative_summary['median']}")
    print(f"AUC / common-language effect size: {summary['auc_common_language_effect_size']}")
    print(f"top-1 same-day accuracy: {top1_accuracy} ({top1_correct_total}/{top1_total})")
    print(f"GATE: {verdict} -- {reason}")


if __name__ == "__main__":
    main()

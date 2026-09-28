#!/usr/bin/env python3
"""Build the hand-verification scaffold for synthetic merge boundary gold.

Track: encoder fine-tuning (GysBERT / GloBERTise) on artificial 2- and 4-resolution merges.
This step comes *before* synthetic train/val/test construction. Outputs are machine-suggested
boundaries only; ``review_status=verified`` lives in ``synthetic_boundary_gold`` after merge.

Candidate pool: consecutive enriched resolutions on the same calendar day that are **separated**
under PLAN.md (unique start paragraph, extent <= 3), with HTR text sliced from
``paragraph_axis_1626_1630`` via concordance paragraph attribution. Session-day rows already in
``boundary_gold_sample`` are excluded so this track stays on a separate annotation line from S3.

Usage:
    uv run python scripts/build_synthetic_boundary_gold_scaffold.py
    uv run python scripts/build_synthetic_boundary_gold_scaffold.py --min-length-ratio 1.5
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.s4_corpus_paragraph_predictions import axis_for_date, resolved_sessions, session_of
from scripts.synthetic_boundary_common import (
    MIN_LENGTH_RATIO_DEFAULT,
    boundaries_from_segment_lengths,
    concat_segments,
    label_separation,
    length_ratio,
    length_ratio_band,
    passes_length_heterogeneity,
    resolution_htr_text,
    year_band,
)

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
BOUNDARY_GOLD_DATASET = "boundary_gold_sample"
OUTPUT_DATASET = "synthetic_boundary_gold_scaffold"

TARGET_STAGE_A = 35
TARGET_STAGE_B = 20
RANDOM_SEED = 42


def load_axis_indexes(records: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        date = str(record.get("date", ""))[:10]
        flat_id = str(record.get("flat_id", ""))
        if not date or not flat_id:
            continue
        by_date[date].append(record)
        by_session[session_of(flat_id)].append(record)
    return dict(by_date), dict(by_session)


def boundary_gold_dates() -> set[str]:
    gold = load(BOUNDARY_GOLD_DATASET)
    return {str(day["date"])[:10] for day in gold.get("days", [])}


def separated_frame(concordance: pd.DataFrame) -> pd.DataFrame:
    required = {
        "enriched_date",
        "resolution_index",
        "enriched_id",
        "paragraph_start_index",
        "paragraph_end_index",
        "status",
    }
    missing = required - set(concordance.columns)
    if missing:
        raise ValueError(f"{CONCORDANCE_DATASET} missing columns: {sorted(missing)}")

    work = concordance.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    attributed = work["paragraph_start_index"].notna() & work["paragraph_end_index"].notna()
    work = work.loc[attributed].copy()
    work["paragraph_start_index"] = work["paragraph_start_index"].astype(int)
    work["paragraph_end_index"] = work["paragraph_end_index"].astype(int)
    work = label_separation(work)
    return work.loc[work["separated"]].sort_values(["enriched_date", "resolution_index"])


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, pd.Series):
        return row[key]
    return getattr(row, key)


def build_segment_row(
    row: Any,
    axis: list[dict[str, Any]],
) -> dict[str, Any] | None:
    start = int(_row_value(row, "paragraph_start_index"))
    end = int(_row_value(row, "paragraph_end_index"))
    if end < start or not axis:
        return None
    text = resolution_htr_text(axis, start, end)
    if not text.strip():
        return None
    return {
        "enriched_id": str(_row_value(row, "enriched_id")),
        "resolution_index": int(_row_value(row, "resolution_index")),
        "paragraph_start_index": start,
        "paragraph_end_index": end,
        "htr_char_len": len(text),
        "htr_text": text,
    }


def enumerate_pairs(separated: pd.DataFrame, excluded_dates: set[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for date, group in separated.groupby("enriched_date", sort=True):
        if date in excluded_dates:
            continue
        rows = group.sort_values("resolution_index")
        indices = rows["resolution_index"].tolist()
        by_index = {int(r.resolution_index): r for r in rows.itertuples(index=False)}
        for left, right in zip(indices, indices[1:]):
            if right != left + 1:
                continue
            pair_rows = [by_index[left], by_index[right]]
            candidates.append({"enriched_date": date, "rows": pair_rows})
    return candidates


def enumerate_quads(separated: pd.DataFrame, excluded_dates: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for date, group in separated.groupby("enriched_date", sort=True):
        if date in excluded_dates:
            continue
        rows = group.sort_values("resolution_index")
        indices = rows["resolution_index"].tolist()
        by_index = {int(r.resolution_index): r for r in rows.itertuples(index=False)}
        for i in range(len(indices) - 3):
            block = indices[i : i + 4]
            if block != list(range(block[0], block[0] + 4)):
                continue
            out.append({"enriched_date": date, "rows": [by_index[j] for j in block]})
    return out


def materialize_candidate(
    *,
    stage: int,
    enriched_date: str,
    rows: list[Any],
    axis: list[dict[str, Any]],
    min_ratio: float,
) -> dict[str, Any] | None:
    segments = [build_segment_row(row, axis) for row in rows]
    if any(s is None for s in segments):
        return None
    assert segments
    typed_segments: list[dict[str, Any]] = [s for s in segments if s is not None]
    lens = [s["htr_char_len"] for s in typed_segments]
    if not passes_length_heterogeneity(lens, min_ratio):
        return None
    texts = [s["htr_text"] for s in typed_segments]
    concat = concat_segments(texts)
    suggested = boundaries_from_segment_lengths(lens)
    ratio = length_ratio(lens)
    return {
        "record_type": "candidate",
        "stage": stage,
        "enriched_date": enriched_date,
        "resolution_ids": [s["enriched_id"] for s in typed_segments],
        "resolution_indices": [s["resolution_index"] for s in typed_segments],
        "segment_htr_lens": lens,
        "segment_texts": texts,
        "length_ratio": round(ratio, 4),
        "concat_text": concat,
        "concat_char_len": len(concat),
        "suggested_boundaries": suggested,
        "gold_boundaries": None,
        "review_status": "pending",
        "annotator": None,
        "notes": "",
        "stratum": {
            "year_band": year_band(enriched_date),
            "length_ratio_band": length_ratio_band(ratio),
        },
    }


def stratified_sample(pool: list[dict[str, Any]], target: int, rng: random.Random) -> list[dict[str, Any]]:
    if len(pool) <= target:
        return list(pool)
    by_stratum: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in pool:
        key = (item["stratum"]["year_band"], item["stratum"]["length_ratio_band"])
        by_stratum[key].append(item)
    strata = list(by_stratum.keys())
    rng.shuffle(strata)
    chosen: list[dict[str, Any]] = []
    while len(chosen) < target and any(by_stratum[k] for k in strata):
        for key in strata:
            bucket = by_stratum[key]
            if not bucket or len(chosen) >= target:
                continue
            chosen.append(bucket.pop(rng.randrange(len(bucket))))
    return chosen


def assign_candidate_ids(candidates: list[dict[str, Any]]) -> None:
    stage_counts: Counter[int] = Counter()
    for item in candidates:
        stage = int(item["stage"])
        stage_counts[stage] += 1
        prefix = "sbgs-a" if stage == 2 else "sbgs-b"
        item["candidate_id"] = f"{prefix}-{stage_counts[stage]:05d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build synthetic boundary gold annotation scaffold.")
    parser.add_argument("--min-length-ratio", type=float, default=MIN_LENGTH_RATIO_DEFAULT)
    parser.add_argument("--target-stage-a", type=int, default=TARGET_STAGE_A)
    parser.add_argument("--target-stage-b", type=int, default=TARGET_STAGE_B)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()

    concordance = load(CONCORDANCE_DATASET)
    axis_records = load(AXIS_DATASET)
    by_date, by_session = load_axis_indexes(axis_records)
    session_by_date = resolved_sessions()
    excluded = boundary_gold_dates()

    separated = separated_frame(concordance)
    pair_specs = enumerate_pairs(separated, excluded)
    quad_specs = enumerate_quads(separated, excluded)

    pool_a: list[dict[str, Any]] = []
    pool_b: list[dict[str, Any]] = []

    for spec in pair_specs:
        date = spec["enriched_date"]
        axis = axis_for_date(date, by_date, by_session, session_by_date)
        item = materialize_candidate(stage=2, enriched_date=date, rows=spec["rows"], axis=axis, min_ratio=args.min_length_ratio)
        if item:
            pool_a.append(item)

    for spec in quad_specs:
        date = spec["enriched_date"]
        axis = axis_for_date(date, by_date, by_session, session_by_date)
        item = materialize_candidate(stage=4, enriched_date=date, rows=spec["rows"], axis=axis, min_ratio=args.min_length_ratio)
        if item:
            pool_b.append(item)

    rng = random.Random(args.seed)
    rng.shuffle(pool_a)
    rng.shuffle(pool_b)
    sampled_a = stratified_sample(pool_a, args.target_stage_a, rng)
    sampled_b = stratified_sample(pool_b, args.target_stage_b, rng)
    candidates = sampled_a + sampled_b
    assign_candidate_ids(candidates)

    meta = {
        "record_type": "meta",
        "track": "synthetic_boundary_encoder",
        "description": "Hand-verification scaffold for 2- and 4-resolution merge boundary gold (separate from boundary_gold_sample).",
        "parent_datasets": [CONCORDANCE_DATASET, AXIS_DATASET, BOUNDARY_GOLD_DATASET],
        "parameters": {
            "min_length_ratio": args.min_length_ratio,
            "target_stage_a": args.target_stage_a,
            "target_stage_b": args.target_stage_b,
            "random_seed": args.seed,
            "excluded_boundary_gold_dates": sorted(excluded),
        },
        "pool_counts": {
            "eligible_pairs_after_filters": len(pool_a),
            "eligible_quads_after_filters": len(pool_b),
            "sampled_stage_a": len(sampled_a),
            "sampled_stage_b": len(sampled_b),
        },
        "stratum_counts": {
            f"{year}|{ratio}": count
            for (year, ratio), count in Counter(
                (c["stratum"]["year_band"], c["stratum"]["length_ratio_band"]) for c in candidates
            ).items()
        },
    }

    output = save_semi_structured([meta, *candidates], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(candidates)} scaffold candidates to {output}")
    print(f"  Stage A (2-resolution): {len(sampled_a)} (pool {len(pool_a)})")
    print(f"  Stage B (4-resolution): {len(sampled_b)} (pool {len(pool_b)})")
    print(f"  Excluded {len(excluded)} boundary_gold_sample calendar dates")


if __name__ == "__main__":
    main()

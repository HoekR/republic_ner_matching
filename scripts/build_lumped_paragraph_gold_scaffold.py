#!/usr/bin/env python3
"""Build a scaffold of lumped (bundled) paragraph candidates for mid-cut gold.

Unlike ``synthetic_boundary_gold_scaffold`` (concat of *separated* slices), these
candidates are single continuous HTR paragraphs where concordance attributes
2+ resolutions to the same ``paragraph_start_index`` (extent 1 paragraph).

Excludes dates already in ``boundary_gold_sample`` so this expands beyond the
existing 22 mid_paragraph positions.

Usage:
    uv run python scripts/build_lumped_paragraph_gold_scaffold.py
    uv run python scripts/build_lumped_paragraph_gold_scaffold.py --target 80
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.build_synthetic_boundary_gold_scaffold import (
    AXIS_DATASET,
    BOUNDARY_GOLD_DATASET,
    CONCORDANCE_DATASET,
    boundary_gold_dates,
    load_axis_indexes,
)
from scripts.s4_corpus_paragraph_predictions import axis_for_date, resolved_sessions
from scripts.synthetic_boundary_common import label_separation, year_band

OUTPUT_DATASET = "lumped_paragraph_gold_scaffold"
SEED = 42
TARGET_DEFAULT = 80
MIN_TEXT_CHARS = 80
MAX_TEXT_CHARS = 4000


def attributed_frame(concordance: pd.DataFrame) -> pd.DataFrame:
    required = {
        "enriched_date",
        "resolution_index",
        "enriched_id",
        "paragraph_start_index",
        "paragraph_end_index",
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
    return label_separation(work)


def enumerate_lumped(
    frame: pd.DataFrame,
    excluded_dates: set[str],
) -> list[dict[str, Any]]:
    """One candidate per (date, paragraph_start) with n_share≥2 and single-paragraph extent."""
    candidates: list[dict[str, Any]] = []
    single = frame.loc[frame["paragraph_start_index"] == frame["paragraph_end_index"]]
    for (date, start), group in single.groupby(["enriched_date", "paragraph_start_index"], sort=True):
        if str(date) in excluded_dates:
            continue
        if len(group) < 2:
            continue
        rows = group.sort_values("resolution_index")
        candidates.append(
            {
                "enriched_date": str(date)[:10],
                "paragraph_stream_index": int(start),
                "n_resolutions": int(len(rows)),
                "expected_cuts": int(len(rows) - 1),
                "resolution_ids": [str(r) for r in rows["enriched_id"].tolist()],
                "resolution_indices": [int(i) for i in rows["resolution_index"].tolist()],
            }
        )
    return candidates


def materialize(
    spec: dict[str, Any],
    *,
    by_date: dict[str, list[dict[str, Any]]],
    by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
) -> dict[str, Any] | None:
    date = spec["enriched_date"]
    index = int(spec["paragraph_stream_index"])
    axis = axis_for_date(date, by_date, by_session, session_by_date)
    if index < 0 or index >= len(axis):
        return None
    record = axis[index]
    text = str(record.get("text") or "")
    if len(text) < MIN_TEXT_CHARS or len(text) > MAX_TEXT_CHARS:
        return None
    return {
        "record_type": "candidate",
        "example_id": f"{date}#p{index}",
        "date": date,
        "paragraph_stream_index": index,
        "flat_id": record.get("flat_id"),
        "para_index": record.get("para_index"),
        "text": text,
        "text_char_len": len(text),
        "n_resolutions": spec["n_resolutions"],
        "expected_cuts": spec["expected_cuts"],
        "resolution_ids": spec["resolution_ids"],
        "resolution_indices": spec["resolution_indices"],
        "gold_offsets": None,
        "review_status": "pending",
        "annotator": None,
        "paragraph_notes": "",
        "cut_notes": [],
        "uncertain": False,
        "clutter": False,
        "stratum": {"year_band": year_band(date)},
    }


def stratified_sample(pool: list[dict[str, Any]], target: int, rng: random.Random) -> list[dict[str, Any]]:
    if len(pool) <= target:
        return list(pool)
    by_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in pool:
        by_band[item["stratum"]["year_band"]].append(item)
    for bucket in by_band.values():
        rng.shuffle(bucket)
    bands = list(by_band.keys())
    rng.shuffle(bands)
    chosen: list[dict[str, Any]] = []
    while len(chosen) < target and any(by_band[b] for b in bands):
        for band in bands:
            if len(chosen) >= target:
                break
            if by_band[band]:
                chosen.append(by_band[band].pop())
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold lumped-paragraph mid-cut gold candidates.")
    parser.add_argument("--target", type=int, default=TARGET_DEFAULT)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--include-boundary-gold-dates",
        action="store_true",
        help="Also sample from boundary_gold_sample dates (default: exclude).",
    )
    args = parser.parse_args()

    excluded = set() if args.include_boundary_gold_dates else boundary_gold_dates()
    concordance = load(CONCORDANCE_DATASET)
    frame = attributed_frame(concordance)
    specs = enumerate_lumped(frame, excluded)
    by_date, by_session = load_axis_indexes(load(AXIS_DATASET))
    session_by_date = resolved_sessions()

    pool: list[dict[str, Any]] = []
    for spec in specs:
        item = materialize(spec, by_date=by_date, by_session=by_session, session_by_date=session_by_date)
        if item is not None:
            pool.append(item)

    rng = random.Random(args.seed)
    sample = stratified_sample(pool, args.target, rng)

    meta = {
        "record_type": "meta",
        "track": "lumped_paragraph_boundary_gold",
        "description": (
            "Lumped/bundled single-paragraph HTR candidates for mid_paragraph cut labeling. "
            "Concordance n_share≥2 on one paragraph; excludes boundary_gold_sample dates by default."
        ),
        "parent_datasets": [CONCORDANCE_DATASET, AXIS_DATASET, BOUNDARY_GOLD_DATASET],
        "parameters": {
            "target": args.target,
            "seed": args.seed,
            "exclude_boundary_gold_dates": not args.include_boundary_gold_dates,
            "n_excluded_dates": len(excluded),
            "min_text_chars": MIN_TEXT_CHARS,
            "max_text_chars": MAX_TEXT_CHARS,
        },
        "counts": {
            "n_lumped_specs": len(specs),
            "n_materialized": len(pool),
            "n_sampled": len(sample),
        },
    }
    path = save_semi_structured([meta, *sample], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(sample)} candidates (from {len(pool)} materialized / {len(specs)} specs) to {path}")


if __name__ == "__main__":
    main()

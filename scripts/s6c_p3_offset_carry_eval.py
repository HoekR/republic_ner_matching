#!/usr/bin/env python3
"""Track P P3 — score offset-carry through re-paragraph + segment_gap.

Primary gold: ``synthetic_boundary_folds`` (proven consecutive-separated pairs;
P2 redirected here). Each example is one lumped paragraph (= concatenated HTR)
with known interior cuts. Carrying those offsets through ``segment_day_with_offsets``
must unlock unique start paragraphs on the successor axis; the paragraph-only
path and ``uniform_start_paragraphs`` on the *pre-split* axis remain collided.

Scores ``separated`` vs the uniform null (exact start agreement only — no
tolerance bands). Does not write a production axis successor; diagnostic only.

Usage:
    uv run python -m scripts.s6c_p3_offset_carry_eval
    uv run python -m scripts.s6c_p3_offset_carry_eval --split test
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_io import load, save_semi_structured
from scripts.s6c_gap_segmentation import segment_day
from scripts.s6c_reparagraph import (
    AXIS_VERSION_P3,
    extents_from_starts,
    segment_day_with_offsets,
    starts_from_segment_positions,
)
from scripts.separated_accuracy_eval import label_separation, uniform_start_paragraphs
from scripts.synthetic_boundary_common import MAX_EXTENT_PARAGRAPHS

FOLDS_DATASET = "synthetic_boundary_folds"
OUTPUT_DATASET = "s6c_p3_offset_carry_eval"


def _example_axis(concat_text: str) -> list[dict[str, Any]]:
    return [
        {
            "text": concat_text,
            "para_index": 0,
            "axis_id": "synthetic#p0",
            "flat_id": "synthetic-resolution-0",
        }
    ]


def _gold_boundaries(row: dict[str, Any]) -> list[int]:
    raw = row.get("gold_boundaries") or row.get("suggested_boundaries") or []
    return sorted(int(x) for x in raw)


def score_example(row: dict[str, Any]) -> dict[str, Any] | None:
    """One synthetic fold → offset-carry / plain / uniform separation counts."""
    text = str(row.get("concat_text") or "")
    cuts = _gold_boundaries(row)
    if not text or not cuts:
        return None
    k_e = len(cuts) + 1
    axis = _example_axis(text)

    # Offset-bearing anchors: each cut opens the next resolution.
    alignments = [(rank, 0, offset) for rank, offset in enumerate(cuts, start=1)]
    carried = segment_day_with_offsets(
        k_e,
        axis,
        alignments,
        version=AXIS_VERSION_P3,
        parent_dataset=FOLDS_DATASET,
    )
    successor_n = len(carried["successor"]["axis"])
    offset_starts = starts_from_segment_positions(carried["positions"])
    gold_starts = list(range(k_e))  # one start per successor piece, in order
    # Exact agreement on the successor stream (diagnostic).
    exact = (
        len(offset_starts) == k_e
        and all(s is not None for s in offset_starts)
        and list(offset_starts) == gold_starts
    )

    offset_spans = extents_from_starts(offset_starts, successor_n)
    plain_positions = segment_day(k_e, 1, [(rank, 0) for rank in range(1, k_e)])
    plain_starts = starts_from_segment_positions(plain_positions)
    plain_spans = extents_from_starts(plain_starts, 1)
    uniform = uniform_start_paragraphs(1, k_e)
    uniform_spans = extents_from_starts(uniform, 1)

    def _frame(
        date: str, spans: list[tuple[int | None, int | None]]
    ) -> pd.DataFrame:
        rows = []
        for index, (start, end) in enumerate(spans):
            if start is None or end is None:
                continue
            rows.append(
                {
                    "enriched_date": date,
                    "resolution_index": index,
                    "paragraph_start_index": int(start),
                    "paragraph_end_index": int(end),
                }
            )
        return pd.DataFrame(rows)

    date = str(row.get("enriched_date") or row.get("example_id") or "synthetic")
    offset_sep = int(label_separation(_frame(date, offset_spans))["separated"].sum()) if offset_spans else 0
    plain_sep = int(label_separation(_frame(date, plain_spans))["separated"].sum()) if plain_spans else 0
    uniform_sep = (
        int(label_separation(_frame(date, uniform_spans))["separated"].sum())
        if uniform_spans
        else 0
    )

    # Extent risk on successor: any span with extent > MAX after re-paragraph.
    extents = [
        (end - start + 1)
        for start, end in offset_spans
        if start is not None and end is not None
    ]
    n_extent_gt_max = sum(1 for extent in extents if extent > MAX_EXTENT_PARAGRAPHS)

    return {
        "record_type": "example",
        "example_id": row.get("example_id"),
        "enriched_date": date,
        "split": row.get("split"),
        "stage": row.get("stage"),
        "k_e": k_e,
        "n_cuts": len(cuts),
        "n_paragraphs_after": successor_n,
        "exact_start_agreement": exact,
        "separated_offset_carry": offset_sep,
        "separated_plain": plain_sep,
        "separated_uniform_presplit": uniform_sep,
        "n_extent_gt_max": n_extent_gt_max,
        "beats_uniform": offset_sep > uniform_sep,
        "beats_plain": offset_sep > plain_sep,
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n_examples": 0}
    sep_offset = sum(r["separated_offset_carry"] for r in rows)
    sep_plain = sum(r["separated_plain"] for r in rows)
    sep_uniform = sum(r["separated_uniform_presplit"] for r in rows)
    k_e_total = sum(r["k_e"] for r in rows)
    return {
        "n_examples": n,
        "k_e_total": k_e_total,
        "exact_start_agreement_rate": round(
            sum(1 for r in rows if r["exact_start_agreement"]) / n, 4
        ),
        "separated_offset_carry": sep_offset,
        "separated_plain": sep_plain,
        "separated_uniform_presplit": sep_uniform,
        "separated_offset_carry_share_of_ke": round(sep_offset / k_e_total, 4)
        if k_e_total
        else None,
        "separated_uniform_share_of_ke": round(sep_uniform / k_e_total, 4)
        if k_e_total
        else None,
        "examples_beating_uniform": sum(1 for r in rows if r["beats_uniform"]),
        "examples_beating_plain": sum(1 for r in rows if r["beats_plain"]),
        "n_extent_gt_max_total": sum(r["n_extent_gt_max"] for r in rows),
        "by_split": dict(Counter(str(r.get("split")) for r in rows)),
        "by_stage": dict(Counter(str(r.get("stage")) for r in rows)),
        "max_extent_paragraphs": MAX_EXTENT_PARAGRAPHS,
        "axis_version": AXIS_VERSION_P3,
        "note": (
            "Offset-carry re-paragraphs at gold cuts then runs segment_day on the "
            "successor; plain/uniform stay on the pre-split 1-paragraph axis. "
            "separated vs uniform_start_paragraphs; exact agreement only."
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        choices=("train", "val", "test", "all"),
        default="all",
        help="Restrict to one fold split (default: all).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on examples (0 = no cap).",
    )
    args = parser.parse_args(argv)

    folds = load(FOLDS_DATASET)
    examples = [
        row
        for row in folds
        if row.get("record_type") == "example"
        and (args.split == "all" or row.get("split") == args.split)
    ]
    if args.limit > 0:
        examples = examples[: args.limit]

    scored: list[dict[str, Any]] = []
    for row in examples:
        result = score_example(row)
        if result is not None:
            scored.append(result)

    summary = summarise(scored)
    payload = [
        {
            "record_type": "meta",
            "track": "track-p-subparagraph-division",
            "step": "P3",
            "parent_datasets": [FOLDS_DATASET],
            "summary": summary,
            "parameters": {"split": args.split, "limit": args.limit},
        },
        *scored,
    ]
    path = save_semi_structured(payload, logical_name=OUTPUT_DATASET, script=__file__)
    print(
        f"P3 offset-carry: {summary.get('n_examples')} examples; "
        f"exact={summary.get('exact_start_agreement_rate')}; "
        f"separated offset/plain/uniform="
        f"{summary.get('separated_offset_carry')}/"
        f"{summary.get('separated_plain')}/"
        f"{summary.get('separated_uniform_presplit')} "
        f"(of k_e={summary.get('k_e_total')}); wrote {path}"
    )


if __name__ == "__main__":
    main()

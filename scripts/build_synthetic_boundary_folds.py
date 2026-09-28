#!/usr/bin/env python3
"""Build synthetic train/val/test folds for merge-boundary recovery.

Excludes every resolution id present in ``synthetic_boundary_gold``. Also excludes
``boundary_gold_sample`` calendar dates (same pool rule as the scaffold). Splits by
enriched date (~70/15/15). Caps concat length so examples fit a 512-token encoder.

With ``--hard-openings``, strips leading opening-formula text on segments 2..n
(using ``s4_opening_phrase_candidates``) before concat so gold cuts no longer sit
on clean formulaic onsets. Writes ``synthetic_boundary_folds_hard``.

Usage:
    uv run python scripts/build_synthetic_boundary_folds.py
    uv run python scripts/build_synthetic_boundary_folds.py --hard-openings
    uv run python scripts/build_synthetic_boundary_folds.py --max-train-pairs 1200 --max-train-quads 600
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.build_synthetic_boundary_gold_scaffold import (
    BOUNDARY_GOLD_DATASET,
    CONCORDANCE_DATASET,
    AXIS_DATASET,
    boundary_gold_dates,
    enumerate_pairs,
    enumerate_quads,
    load_axis_indexes,
    materialize_candidate,
    separated_frame,
)
from scripts.s4_corpus_paragraph_predictions import axis_for_date, resolved_sessions
from scripts.synthetic_boundary_common import (
    MIN_LENGTH_RATIO_DEFAULT,
    concat_segments,
    date_split_bucket,
    gold_resolution_ids,
    hard_merge_segment_texts,
)

OUTPUT_DATASET = "synthetic_boundary_folds"
OUTPUT_DATASET_HARD = "synthetic_boundary_folds_hard"
MAX_CHARS_DEFAULT = 2500
SEED = 42
PHRASE_DATASET = "s4_opening_phrase_candidates"
PHRASE_SEARCH_CONFIG = {
    "char_match_threshold": 0.85,
    "ngram_threshold": 0.85,
    "levenshtein_threshold": 0.85,
}


def build_opening_searcher() -> FuzzyPhraseSearcher:
    phrase_candidates = load(PHRASE_DATASET)[0]["candidates"]
    phrases = [item["phrase"] for item in phrase_candidates if item["word_count"] >= 3]
    return FuzzyPhraseSearcher(phrases, config=PHRASE_SEARCH_CONFIG)


def phrase_match_spans(text: str, searcher: FuzzyPhraseSearcher) -> list[tuple[int, int]]:
    matches = searcher.find_matches({"id": "segment", "text": text})
    spans: list[tuple[int, int]] = []
    for match in matches:
        start = int(match.offset)
        end = start + len(match.phrase.phrase_string)
        if end > start:
            spans.append((start, min(end, len(text))))
    return spans


def _row_ids(rows: list[Any]) -> list[str]:
    out: list[str] = []
    for row in rows:
        if hasattr(row, "enriched_id"):
            out.append(str(row.enriched_id))
        else:
            out.append(str(row["enriched_id"]))
    return out


def apply_hard_openings(item: dict[str, Any], searcher: FuzzyPhraseSearcher) -> dict[str, Any]:
    texts = list(item.get("segment_texts") or [])
    if len(texts) < 2:
        item["hard_openings"] = False
        item["n_segments_stripped"] = 0
        return item
    matches = [phrase_match_spans(text, searcher) for text in texts]
    new_texts, lengths, bounds, n_stripped = hard_merge_segment_texts(texts, matches)
    item["segment_texts"] = new_texts
    item["segment_htr_lens"] = lengths
    item["concat_text"] = concat_segments(new_texts)
    item["concat_char_len"] = len(item["concat_text"])
    item["suggested_boundaries"] = bounds
    item["gold_boundaries"] = list(bounds)
    item["n_cuts"] = len(bounds)
    item["hard_openings"] = True
    item["n_segments_stripped"] = n_stripped
    return item


def materialize_pool(
    *,
    stage: int,
    specs: list[dict[str, Any]],
    blocked_ids: set[str],
    by_date: dict[str, list[dict[str, Any]]],
    by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
    min_ratio: float,
    max_chars: int,
    hard_searcher: FuzzyPhraseSearcher | None = None,
) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for spec in specs:
        ids = _row_ids(spec["rows"])
        if any(i in blocked_ids for i in ids):
            continue
        date = spec["enriched_date"]
        axis = axis_for_date(date, by_date, by_session, session_by_date)
        item = materialize_candidate(
            stage=stage,
            enriched_date=date,
            rows=spec["rows"],
            axis=axis,
            min_ratio=min_ratio,
        )
        if item is None:
            continue
        if hard_searcher is not None:
            item = apply_hard_openings(item, hard_searcher)
        if int(item["concat_char_len"]) > max_chars:
            continue
        item["split"] = date_split_bucket(date, seed=SEED)
        item["gold_boundaries"] = list(item["suggested_boundaries"])
        item["n_cuts"] = len(item["gold_boundaries"])
        pool.append(item)
    return pool


def assign_ids(items: list[dict[str, Any]], prefix: str) -> None:
    for index, item in enumerate(items, start=1):
        item["example_id"] = f"{prefix}-{index:05d}"
        item["record_type"] = "example"


def cap_train(pool: list[dict[str, Any]], max_train: int, rng: random.Random) -> list[dict[str, Any]]:
    if max_train <= 0:
        return pool
    train = [x for x in pool if x["split"] == "train"]
    hold = [x for x in pool if x["split"] != "train"]
    if len(train) <= max_train:
        return pool
    rng.shuffle(train)
    return train[:max_train] + hold


def main() -> None:
    parser = argparse.ArgumentParser(description="Build synthetic boundary train/val/test folds.")
    parser.add_argument("--min-length-ratio", type=float, default=MIN_LENGTH_RATIO_DEFAULT)
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS_DEFAULT)
    parser.add_argument("--max-train-pairs", type=int, default=1200)
    parser.add_argument("--max-train-quads", type=int, default=600)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--hard-openings",
        action="store_true",
        help="Strip leading opening formulas on segments 2..n; write folds_hard.",
    )
    args = parser.parse_args()

    blocked = gold_resolution_ids()
    excluded_dates = boundary_gold_dates()
    concordance = load(CONCORDANCE_DATASET)
    separated = separated_frame(concordance)
    by_date, by_session = load_axis_indexes(load(AXIS_DATASET))
    session_by_date = resolved_sessions()
    hard_searcher = build_opening_searcher() if args.hard_openings else None
    output_name = OUTPUT_DATASET_HARD if args.hard_openings else OUTPUT_DATASET

    pair_specs = enumerate_pairs(separated, excluded_dates)
    quad_specs = enumerate_quads(separated, excluded_dates)

    pairs = materialize_pool(
        stage=2,
        specs=pair_specs,
        blocked_ids=blocked,
        by_date=by_date,
        by_session=by_session,
        session_by_date=session_by_date,
        min_ratio=args.min_length_ratio,
        max_chars=args.max_chars,
        hard_searcher=hard_searcher,
    )
    quads = materialize_pool(
        stage=4,
        specs=quad_specs,
        blocked_ids=blocked,
        by_date=by_date,
        by_session=by_session,
        session_by_date=session_by_date,
        min_ratio=args.min_length_ratio,
        max_chars=args.max_chars,
        hard_searcher=hard_searcher,
    )

    rng = random.Random(args.seed)
    pairs = cap_train(pairs, args.max_train_pairs, rng)
    quads = cap_train(quads, args.max_train_quads, rng)
    assign_ids(pairs, "sbf-a")
    assign_ids(quads, "sbf-b")
    examples = pairs + quads

    split_counts = Counter((e["stage"], e["split"]) for e in examples)
    n_stripped = sum(int(e.get("n_segments_stripped") or 0) for e in examples)
    meta = {
        "record_type": "meta",
        "track": "synthetic_boundary_encoder",
        "description": (
            "Synthetic merge-boundary folds for encoder fine-tuning. "
            "Excludes synthetic_boundary_gold resolution ids and boundary_gold_sample dates."
            + (" Hard openings: strip formulaic onsets on segments 2..n." if args.hard_openings else "")
        ),
        "parent_datasets": [
            CONCORDANCE_DATASET,
            AXIS_DATASET,
            BOUNDARY_GOLD_DATASET,
            "synthetic_boundary_gold",
            *([PHRASE_DATASET] if args.hard_openings else []),
        ],
        "parameters": {
            "min_length_ratio": args.min_length_ratio,
            "max_chars": args.max_chars,
            "max_train_pairs": args.max_train_pairs,
            "max_train_quads": args.max_train_quads,
            "seed": args.seed,
            "hard_openings": args.hard_openings,
            "n_blocked_gold_resolution_ids": len(blocked),
            "n_excluded_boundary_gold_dates": len(excluded_dates),
            "n_segments_stripped_total": n_stripped,
        },
        "counts": {
            "n_examples": len(examples),
            "by_stage_split": {f"stage{s}|{sp}": n for (s, sp), n in sorted(split_counts.items())},
        },
    }

    path = save_semi_structured([meta, *examples], logical_name=output_name, script=__file__)
    print(f"Wrote {len(examples)} examples to {path}")
    for key, count in sorted(meta["counts"]["by_stage_split"].items()):
        print(f"  {key}: {count}")
    print(f"  Blocked gold resolution ids: {len(blocked)}")
    if args.hard_openings:
        print(f"  Segments stripped of leading openings: {n_stripped}")


if __name__ == "__main__":
    main()

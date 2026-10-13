#!/usr/bin/env python3
"""Compare boundary-cut selection approaches with evaluation.

Hypothesis: global top-k on noisy encoder logits places cuts in unpredictable
spots; equal-distance behaviour may come from even-split fallback or from
per-bin selection. This script compares cutters on (a) synthetic test folds
and (b) 50-day bundled gold transfer, and reports F1@tol plus distance-to-even.

Cutters:
  even_split              — equal char intervals (null)
  encoder_topk            — current production path (global top-n_cuts)
  encoder_min_gap         — top-k with non-max suppression (min gap)
  encoder_per_bin         — best score inside each equal-width bin
  opening_phrase          — top opening-formula hits (no encoder)
  encoder_topk+phrase_snap — topk then snap to nearby opening phrase

Usage:
    uv run python scripts/eval_boundary_cutter_approaches.py
    uv run python scripts/eval_boundary_cutter_approaches.py --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

import torch
from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher
from transformers import AutoModelForTokenClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from evaluation_harness import compute_boundary_prf
from scripts.eval_synthetic_boundary_encoder import load_eval_examples, score_set
from scripts.eval_synthetic_boundary_on_gold50 import (
    build_opening_searcher,
    positions_to_examples,
    snap_predictions,
)
from scripts.s4_bundled_split_poc import (
    PHRASE_SNAP_MAX_DISTANCE,
    bundled_positions,
    phrase_offsets,
)
from scripts.s4_entity_density_split_diagnostic import AXIS_DATASET, GOLD_DATASET, review_codes
from scripts.synthetic_boundary_common import even_split_boundaries
from scripts.train_synthetic_boundary_encoder import (
    DEFAULT_MAX_LENGTH,
    output_dir_for,
    pick_device,
)

OUTPUT_DATASET = "boundary_cutter_approaches_eval"
MODEL_NAME = "globalise/GloBERTise"
TOLERANCES = (0, 50, 150)


def load_encoder(model_name: str = MODEL_NAME) -> dict[str, Any]:
    final_dir = output_dir_for(model_name) / "final"
    if not final_dir.exists():
        raise FileNotFoundError(f"missing checkpoint: {final_dir}")
    device = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(final_dir)
    model = AutoModelForTokenClassification.from_pretrained(final_dir)
    model.to(device)
    model.eval()
    return {
        "model_name": model_name,
        "checkpoint": str(final_dir),
        "device": device,
        "tokenizer": tokenizer,
        "model": model,
    }


def token_boundary_scores(
    text: str,
    *,
    encoder: dict[str, Any],
    max_length: int = DEFAULT_MAX_LENGTH,
) -> list[tuple[int, float]]:
    """Return (char_pos, score) candidates — char_pos = token end offset."""
    tokenizer = encoder["tokenizer"]
    model = encoder["model"]
    device = encoder["device"]
    encoded = tokenizer(
        text,
        truncation=True,
        max_length=max_length,
        return_offsets_mapping=True,
        return_tensors="pt",
    )
    offsets = [(int(a), int(b)) for a, b in encoded.pop("offset_mapping")[0].tolist()]
    encoded = {k: v.to(device) for k, v in encoded.items()}
    with torch.no_grad():
        logits = model(**encoded).logits[0]
    scores = logits[:, 1] - logits[:, 0]
    best: dict[int, float] = {}
    for index, (start, end) in enumerate(offsets):
        if end == 0 and start == 0:
            continue
        if end <= 0 or end >= len(text):
            continue
        score = float(scores[index].item())
        if end not in best or score > best[end]:
            best[end] = score
    return sorted(best.items(), key=lambda item: item[0])


def select_topk(scored: list[tuple[int, float]], n_cuts: int) -> list[int]:
    ranked = sorted(scored, key=lambda item: (-item[1], item[0]))
    return sorted(pos for pos, _ in ranked[:n_cuts])


def select_min_gap(
    scored: list[tuple[int, float]],
    n_cuts: int,
    *,
    char_len: int,
) -> list[int]:
    """Greedy top score with suppression radius ≈ half an even bin."""
    if n_cuts <= 0:
        return []
    gap = max(20, char_len // (2 * (n_cuts + 1)))
    ranked = sorted(scored, key=lambda item: (-item[1], item[0]))
    chosen: list[int] = []
    for pos, _score in ranked:
        if all(abs(pos - c) >= gap for c in chosen):
            chosen.append(pos)
        if len(chosen) >= n_cuts:
            break
    return sorted(chosen)


def select_per_bin(
    scored: list[tuple[int, float]],
    n_cuts: int,
    *,
    char_len: int,
) -> list[int]:
    """One cut per equal-width interior bin (local max). Forces near-even spacing."""
    if n_cuts <= 0 or char_len <= 0:
        return []
    by_pos = {pos: score for pos, score in scored}
    cuts: list[int] = []
    for rank in range(n_cuts):
        lo = ((rank + 1) * char_len) // (n_cuts + 1) - char_len // (2 * (n_cuts + 1))
        hi = ((rank + 1) * char_len) // (n_cuts + 1) + char_len // (2 * (n_cuts + 1))
        lo = max(1, lo)
        hi = min(char_len - 1, hi)
        window = [(p, s) for p, s in by_pos.items() if lo <= p <= hi]
        if not window:
            # fallback: nearest scored pos to bin centre
            centre = ((rank + 1) * char_len) // (n_cuts + 1)
            if by_pos:
                p = min(by_pos, key=lambda x: abs(x - centre))
                cuts.append(p)
            continue
        cuts.append(max(window, key=lambda item: item[1])[0])
    return sorted(set(cuts))[:n_cuts]


def select_opening_phrase(
    text: str,
    n_cuts: int,
    searcher: FuzzyPhraseSearcher,
) -> list[int]:
    """Interior opening-formula starts as cuts (skip offset 0)."""
    hits = sorted({off for off, _phrase, _sim in phrase_offsets(text, searcher) if off > 0})
    if len(hits) <= n_cuts:
        return hits[:n_cuts]
    # Prefer hits that are well spread: greedy farthest from already chosen / ends.
    chosen: list[int] = []
    anchors = [0, len(text)]
    remaining = list(hits)
    while remaining and len(chosen) < n_cuts:
        def spread(p: int) -> int:
            return min(abs(p - a) for a in anchors + chosen)

        best = max(remaining, key=spread)
        chosen.append(best)
        remaining.remove(best)
    return sorted(chosen)


Cutter = Callable[[dict[str, Any]], list[int]]


def build_cutters(
    encoder: dict[str, Any],
    searcher: FuzzyPhraseSearcher,
) -> dict[str, Cutter]:
    cache: dict[str, list[tuple[int, float]]] = {}

    def scored_for(example: dict[str, Any]) -> list[tuple[int, float]]:
        text = str(example["concat_text"])
        key = example.get("example_id") or text[:80]
        if key not in cache:
            cache[str(key)] = token_boundary_scores(text, encoder=encoder)
        return cache[str(key)]

    def even_split(example: dict[str, Any]) -> list[int]:
        n = int(example.get("n_cuts") or 0)
        return even_split_boundaries(int(example["concat_char_len"]), n)

    def encoder_topk(example: dict[str, Any]) -> list[int]:
        n = int(example.get("n_cuts") or 0)
        return select_topk(scored_for(example), n)

    def encoder_min_gap(example: dict[str, Any]) -> list[int]:
        n = int(example.get("n_cuts") or 0)
        return select_min_gap(
            scored_for(example), n, char_len=int(example["concat_char_len"])
        )

    def encoder_per_bin(example: dict[str, Any]) -> list[int]:
        n = int(example.get("n_cuts") or 0)
        return select_per_bin(
            scored_for(example), n, char_len=int(example["concat_char_len"])
        )

    def opening_phrase(example: dict[str, Any]) -> list[int]:
        n = int(example.get("n_cuts") or 0)
        return select_opening_phrase(str(example["concat_text"]), n, searcher)

    def encoder_topk_phrase_snap(example: dict[str, Any]) -> list[int]:
        raw = encoder_topk(example)
        snapped = snap_predictions(
            [example], [raw], searcher, max_distance=PHRASE_SNAP_MAX_DISTANCE
        )[0]
        return snapped

    return {
        "even_split": even_split,
        "encoder_topk": encoder_topk,
        "encoder_min_gap": encoder_min_gap,
        "encoder_per_bin": encoder_per_bin,
        "opening_phrase": opening_phrase,
        "encoder_topk+phrase_snap": encoder_topk_phrase_snap,
    }


def mean_evenness(examples: list[dict[str, Any]], preds: list[list[int]]) -> float:
    """Mean |pred−even| / char_len over paired cuts (0 = identical to even-split)."""
    dists: list[float] = []
    for example, hyp in zip(examples, preds, strict=True):
        n = int(example.get("n_cuts") or 0)
        length = int(example["concat_char_len"])
        if n <= 0 or length <= 0:
            continue
        even = even_split_boundaries(length, n)
        for e, h in zip(even, sorted(hyp)[:n]):
            dists.append(abs(e - h) / length)
    return round(sum(dists) / len(dists), 4) if dists else 0.0


def evaluate_cutter(
    name: str,
    cutter: Cutter,
    examples: list[dict[str, Any]],
) -> dict[str, Any]:
    preds = [cutter(ex) for ex in examples]
    scored = score_set(examples, preds)
    row = {
        "record_type": "result",
        "cutter": name,
        "n_examples": len(examples),
        "evenness_mean": mean_evenness(examples, preds),
    }
    for tol in TOLERANCES:
        key = f"tol_{tol}"
        metrics = scored.get(key) or {}
        row[f"f1@{tol}"] = metrics.get("f1")
        row[f"p@{tol}"] = metrics.get("precision")
        row[f"r@{tol}"] = metrics.get("recall")
    return row


def gold50_examples() -> list[dict[str, Any]]:
    gold = load(GOLD_DATASET)
    axis = load(AXIS_DATASET)
    codes = review_codes(gold)
    positions = bundled_positions(gold, axis, codes)
    return positions_to_examples(positions)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--sets",
        default="synthetic_test,gold50",
        help="comma list: synthetic_test,gold50",
    )
    args = parser.parse_args(argv)

    encoder = load_encoder()
    searcher = build_opening_searcher()
    cutters = build_cutters(encoder, searcher)

    sets: dict[str, list[dict[str, Any]]] = {}
    wanted = {s.strip() for s in args.sets.split(",") if s.strip()}
    if "synthetic_test" in wanted:
        sets["synthetic_test"] = load_eval_examples()["synthetic_test"]
    if "gold50" in wanted:
        sets["gold50"] = gold50_examples()

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "model_name": encoder["model_name"],
            "checkpoint": encoder["checkpoint"],
            "device": encoder["device"],
            "cutters": list(cutters),
            "sets": list(sets),
            "note": (
                "evenness_mean = mean |cut−even_split| / char_len; "
                "lower ⇒ closer to equal-distance null. "
                "encoder_per_bin deliberately near-even; encoder_topk is current path."
            ),
        }
    ]

    print(
        f"checkpoint={encoder['checkpoint']} device={encoder['device']}\n"
        f"{'set':<16} {'cutter':<28} {'F1@50':>7} {'F1@150':>7} {'evenness':>9}"
    )
    print("-" * 72)
    for set_name, examples in sets.items():
        if not examples:
            print(f"{set_name}: empty")
            continue
        for cutter_name, cutter in cutters.items():
            result = evaluate_cutter(cutter_name, cutter, examples)
            result["eval_set"] = set_name
            rows.append(result)
            print(
                f"{set_name:<16} {cutter_name:<28} "
                f"{result.get('f1@50') or 0:7.3f} "
                f"{result.get('f1@150') or 0:7.3f} "
                f"{result['evenness_mean']:9.3f}"
            )

    if args.write:
        path = save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[
                "synthetic_boundary_folds",
                GOLD_DATASET,
                AXIS_DATASET,
            ],
            description=(
                "Boundary cutter approach comparison: even_split / encoder_topk / "
                "min_gap / per_bin / opening_phrase / phrase_snap on synthetic_test "
                "+ gold50 bundled. F1@tol + evenness vs equal-distance null."
            ),
        )
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()

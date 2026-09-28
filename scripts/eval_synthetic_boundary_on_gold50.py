#!/usr/bin/env python3
"""Transfer test: synthetic boundary encoders on the 50-day gold bundled paragraphs.

The encoder was trained on artificial concatenations of *already-separated* HTR
slices. This script asks whether it recovers real interior cuts on
``boundary_gold_sample`` paragraphs where gold places 2+ mid_paragraph cuts
(same units as ``s4_bundled_split_poc``).

Predictors: even-split baseline, fine-tuned GysBERT / GloBERTise.
Metric: ``compute_boundary_prf`` at tol 0 / 50 / 150 on within-paragraph
char offsets (gold ``mid_paragraph`` offsets).

Usage:
    uv run python scripts/eval_synthetic_boundary_on_gold50.py
    uv run python scripts/eval_synthetic_boundary_on_gold50.py --models globalise/GloBERTise
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import torch
from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher
from transformers import AutoModelForTokenClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from evaluation_harness import compute_boundary_prf
from scripts.eval_synthetic_boundary_encoder import predict_even_split, predict_model, score_set
from scripts.s4_bundled_split_poc import (
    PHRASE_DATASET,
    PHRASE_SNAP_MAX_DISTANCE,
    bundled_positions,
    phrase_offsets,
    snap_predicted_cuts,
)
from scripts.s4_entity_density_split_diagnostic import AXIS_DATASET, GOLD_DATASET, review_codes
from scripts.train_synthetic_boundary_encoder import DEFAULT_MAX_LENGTH, output_dir_for, pick_device

OUTPUT_DATASET = "synthetic_boundary_gold50_transfer"
TOLERANCES = (0, 50, 150)
DEFAULT_MODELS = ("emanjavacas/GysBERT", "globalise/GloBERTise")
REPORT_PATH = PROJECT_ROOT / "docs" / "SYNTHETIC_BOUNDARY_GOLD50_TRANSFER.md"
PHRASE_SEARCH_CONFIG = {
    "char_match_threshold": 0.85,
    "ngram_threshold": 0.85,
    "levenshtein_threshold": 0.85,
}


def build_opening_searcher() -> FuzzyPhraseSearcher:
    phrase_candidates = load(PHRASE_DATASET)[0]["candidates"]
    phrases = [item["phrase"] for item in phrase_candidates if item["word_count"] >= 3]
    return FuzzyPhraseSearcher(phrases, config=PHRASE_SEARCH_CONFIG)


def snap_predictions(
    examples: list[dict[str, Any]],
    preds: list[list[int]],
    searcher: FuzzyPhraseSearcher,
    *,
    max_distance: int = PHRASE_SNAP_MAX_DISTANCE,
) -> list[list[int]]:
    snapped: list[list[int]] = []
    for example, hyp in zip(examples, preds, strict=True):
        offsets = phrase_offsets(str(example["concat_text"]), searcher)
        snapped.append(
            [cut for cut, _ in snap_predicted_cuts(hyp, offsets, max_distance=max_distance)]
        )
    return snapped


def positions_to_examples(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map bundled POC positions into the encoder example schema."""
    examples: list[dict[str, Any]] = []
    for position in positions:
        text = str(position["text"])
        gold = [int(x) for x in position["gold_offsets"]]
        examples.append(
            {
                "example_id": (
                    f"{position['date']}#p{position['paragraph_stream_index']}"
                ),
                "date": position["date"],
                "paragraph_stream_index": position["paragraph_stream_index"],
                "flat_id": position["flat_id"],
                "concat_text": text,
                "concat_char_len": len(text),
                "gold_boundaries": gold,
                "n_cuts": len(gold),
                "target_splits": position["target_splits"],
            }
        )
    return examples


def load_poc_recall() -> dict[str, Any] | None:
    """Optional comparison numbers from the existing bundled-split POC."""
    try:
        rows = load("s4_bundled_split_poc")
    except Exception:
        return None
    if isinstance(rows, list) and rows and "stage" in rows[0]:
        # Prefer meta/summary if present
        meta = next((r for r in rows if r.get("record_type") == "meta"), None)
        if meta:
            return meta
    return None


def write_markdown(
    *,
    n_positions: int,
    n_cuts: int,
    results: list[dict[str, Any]],
    device: str,
    model_tag: str,
) -> None:
    lines = [
        "# Synthetic boundary encoder — transfer on 50-day gold bundled paragraphs",
        "<!-- doc-status: active -->",
        "",
        "Transfer test: fine-tuned merge-boundary encoders (trained on synthetic "
        "separated-slice concatenations) scored on real gold **bundled** paragraphs "
        "from `boundary_gold_sample` (same units as `s4_bundled_split_poc`: mid_paragraph "
        "char offsets inside paragraphs that carry 2+ gold cut slots).",
        "",
        "## Setup",
        "",
        f"- Device: `{device}`",
        f"- Model tag: `{model_tag or 'default'}`",
        f"- Bundled paragraphs with mid_paragraph gold: **{n_positions}**",
        f"- Gold interior cuts: **{n_cuts}**",
        f"- Tolerances: {', '.join(str(t) for t in TOLERANCES)}",
        "- Predictors: even-split (knows `n_cuts`) · encoders · encoder+phrase_snap "
        f"(snap distance {PHRASE_SNAP_MAX_DISTANCE})",
        "",
        "## Results (micro P/R/F1 via `compute_boundary_prf`)",
        "",
        "| predictor | F1@0 | F1@50 | F1@150 | P@50 | R@50 | exact-count |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        s = result["sets"]["bundled_mid_paragraph"]
        lines.append(
            f"| `{result['predictor']}` | "
            f"{s['tol0']['f1']:.3f} | {s['tol50']['f1']:.3f} | {s['tol150']['f1']:.3f} | "
            f"{s['tol50']['precision']:.3f} | {s['tol50']['recall']:.3f} | "
            f"{s['exact_count_rate']:.3f} |"
        )
    ranked = sorted(results, key=lambda r: r["sets"]["bundled_mid_paragraph"]["tol50"]["f1"], reverse=True)
    best = ranked[0]
    baseline = next(r for r in results if r["predictor"] == "even_split_baseline")
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- Best @tol50: **`{best['predictor']}`** "
            f"(F1={best['sets']['bundled_mid_paragraph']['tol50']['f1']:.3f}) vs even-split "
            f"(F1={baseline['sets']['bundled_mid_paragraph']['tol50']['f1']:.3f}).",
            "- Compare against `s4_bundled_split_poc` NER/dictionary heuristics "
            "(previously ~0–15% recall @tol50 on the same 22-position family).",
            "",
            "## Caveats",
            "",
            "- This is **transfer / OOD**: train distribution was concat of separated "
            "resolution slices; test is a single HTR paragraph that gold says contains "
            "multiple resolutions.",
            "- `n_cuts` is taken from gold (oracle count), same privilege the even-split "
            "baseline and the earlier POC had.",
            "- Encoder `max_length=512` may truncate long paragraphs.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=list(DEFAULT_MODELS))
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument(
        "--model-tag",
        default="",
        help="Suffix for model checkpoint dir (e.g. 'hard' → .../GloBERTise_hard).",
    )
    parser.add_argument(
        "--no-phrase-snap",
        action="store_true",
        help="Skip opening-phrase snap postprocess rows.",
    )
    args = parser.parse_args()

    gold = load(GOLD_DATASET)
    axis = load(AXIS_DATASET)
    codes = review_codes()
    positions = bundled_positions(gold, axis, codes)
    examples = positions_to_examples(positions)
    if not examples:
        raise SystemExit("No bundled mid_paragraph positions found on the 50-day gold set")

    device = pick_device()
    results: list[dict[str, Any]] = []
    searcher = None if args.no_phrase_snap else build_opening_searcher()

    even_preds = [predict_even_split(ex) for ex in examples]
    results.append(
        {
            "predictor": "even_split_baseline",
            "sets": {"bundled_mid_paragraph": score_set(examples, even_preds)},
        }
    )

    detail_by_predictor: dict[str, list[list[int]]] = {}
    for model_name in args.models:
        final_dir = output_dir_for(model_name, tag=args.model_tag) / "final"
        if not final_dir.exists():
            raise FileNotFoundError(f"Missing trained model at {final_dir}")
        tokenizer = AutoTokenizer.from_pretrained(final_dir)
        model = AutoModelForTokenClassification.from_pretrained(final_dir)
        model.to(device)
        model.eval()

        def _predict(example: dict[str, Any], _model=model, _tok=tokenizer) -> list[int]:
            return predict_model(
                example,
                model=_model,
                tokenizer=_tok,
                device=device,
                max_length=args.max_length,
            )

        preds = [_predict(ex) for ex in examples]
        results.append(
            {
                "predictor": model_name,
                "sets": {"bundled_mid_paragraph": score_set(examples, preds)},
            }
        )
        detail_by_predictor[model_name] = preds

        if searcher is not None:
            snapped = snap_predictions(examples, preds, searcher)
            snap_name = f"{model_name}+phrase_snap"
            results.append(
                {
                    "predictor": snap_name,
                    "sets": {"bundled_mid_paragraph": score_set(examples, snapped)},
                }
            )
            detail_by_predictor[snap_name] = snapped

    n_cuts = sum(ex["n_cuts"] for ex in examples)
    meta = {
        "record_type": "meta",
        "track": "synthetic_boundary_encoder",
        "eval": "gold50_bundled_transfer",
        "device": device,
        "model_tag": args.model_tag or None,
        "phrase_snap": not args.no_phrase_snap,
        "phrase_snap_max_distance": PHRASE_SNAP_MAX_DISTANCE,
        "n_bundled_paragraphs": len(examples),
        "n_gold_cuts": n_cuts,
        "tolerances": list(TOLERANCES),
        "models": args.models,
        "parent_poc": "s4_bundled_split_poc",
    }
    records: list[dict[str, Any]] = [meta]
    for result in results:
        records.append({"record_type": "result", **result})
    best_name = max(results, key=lambda r: r["sets"]["bundled_mid_paragraph"]["tol50"]["f1"])[
        "predictor"
    ]
    if best_name in detail_by_predictor:
        for example, hyp in zip(examples, detail_by_predictor[best_name], strict=True):
            ref = example["gold_boundaries"]
            records.append(
                {
                    "record_type": "example",
                    "predictor": best_name,
                    "example_id": example["example_id"],
                    "date": example["date"],
                    "n_cuts": example["n_cuts"],
                    "gold_boundaries": ref,
                    "hyp_boundaries": hyp,
                    "tol50": compute_boundary_prf(ref, hyp, tolerance=50).__dict__,
                }
            )

    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    write_markdown(
        n_positions=len(examples),
        n_cuts=n_cuts,
        results=results,
        device=device,
        model_tag=args.model_tag,
    )
    print(f"Wrote {path}")
    print(f"Wrote {REPORT_PATH}")
    print(f"bundled_paragraphs={len(examples)} gold_cuts={n_cuts}")
    for result in results:
        s = result["sets"]["bundled_mid_paragraph"]
        print(
            f"  {result['predictor']}: "
            f"F1@0={s['tol0']['f1']:.3f} F1@50={s['tol50']['f1']:.3f} F1@150={s['tol150']['f1']:.3f}"
        )


if __name__ == "__main__":
    main()

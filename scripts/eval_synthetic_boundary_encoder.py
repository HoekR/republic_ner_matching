#!/usr/bin/env python3
"""Evaluate boundary predictors on synthetic test + synthetic_boundary_gold.

Compares even-split baseline and one or more fine-tuned HF models via
``evaluation_harness.compute_boundary_prf`` at tolerances 0 / 50 / 150.

Usage:
    uv run python scripts/eval_synthetic_boundary_encoder.py \\
        --models emanjavacas/GysBERT globalise/GloBERTise
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from evaluation_harness import compute_boundary_prf
from scripts.synthetic_boundary_common import even_split_boundaries
from scripts.train_synthetic_boundary_encoder import (
    DEFAULT_MAX_LENGTH,
    model_slug,
    output_dir_for,
    pick_device,
)

FOLDS_DATASET = "synthetic_boundary_folds"
GOLD_DATASET = "synthetic_boundary_gold"
OUTPUT_DATASET = "synthetic_boundary_eval_report"
TOLERANCES = (0, 50, 150)


def load_eval_examples() -> dict[str, list[dict[str, Any]]]:
    folds = [r for r in load(FOLDS_DATASET) if r.get("record_type") == "example" and r.get("split") == "test"]
    gold = [r for r in load(GOLD_DATASET) if r.get("record_type") == "gold"]
    # Normalize gold rows to the same keys used in prediction.
    for row in gold:
        row = row  # noqa: PLW0127 — clarity
        if "n_cuts" not in row:
            row["n_cuts"] = len(row.get("gold_boundaries") or [])
    return {"synthetic_test": folds, "gold": gold}


def predict_even_split(example: dict[str, Any]) -> list[int]:
    n_cuts = int(example.get("n_cuts") or len(example.get("gold_boundaries") or []))
    return even_split_boundaries(int(example.get("concat_char_len") or len(example.get("concat_text") or "")), n_cuts)


def predict_model(
    example: dict[str, Any],
    *,
    model: Any,
    tokenizer: Any,
    device: str,
    max_length: int,
) -> list[int]:
    text = str(example["concat_text"])
    n_cuts = int(example.get("n_cuts") or len(example.get("gold_boundaries") or []))
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
        logits = model(**encoded).logits[0]  # (seq, 2)
    scores = logits[:, 1] - logits[:, 0]
    candidates: list[tuple[float, int]] = []
    for index, (start, end) in enumerate(offsets):
        if end == 0 and start == 0:
            continue
        # Boundary char position = token end offset in the (possibly truncated) string.
        char_pos = end
        if char_pos <= 0 or char_pos >= len(text):
            continue
        candidates.append((float(scores[index].item()), char_pos))
    # Deduplicate char positions keeping best score.
    best: dict[int, float] = {}
    for score, pos in candidates:
        if pos not in best or score > best[pos]:
            best[pos] = score
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    chosen = sorted(pos for pos, _ in ranked[:n_cuts])
    return chosen


def score_set(
    examples: list[dict[str, Any]],
    predictions: list[list[int]],
) -> dict[str, Any]:
    totals = {tol: {"tp": 0, "fp": 0, "fn": 0} for tol in TOLERANCES}
    exact_count = 0
    for example, hyp in zip(examples, predictions, strict=True):
        ref = [int(x) for x in (example.get("gold_boundaries") or [])]
        if len(hyp) == len(ref):
            exact_count += 1
        for tol in TOLERANCES:
            metrics = compute_boundary_prf(ref, hyp, tolerance=tol)
            totals[tol]["tp"] += metrics.tp
            totals[tol]["fp"] += metrics.fp
            totals[tol]["fn"] += metrics.fn
    out: dict[str, Any] = {
        "n_examples": len(examples),
        "exact_count_rate": round(exact_count / len(examples), 4) if examples else 0.0,
    }
    for tol in TOLERANCES:
        tp, fp, fn = totals[tol]["tp"], totals[tol]["fp"], totals[tol]["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out[f"tol{tol}"] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
    return out


def evaluate_predictor(
    name: str,
    examples_by_set: dict[str, list[dict[str, Any]]],
    predict_fn,
) -> dict[str, Any]:
    result: dict[str, Any] = {"predictor": name, "sets": {}}
    for set_name, examples in examples_by_set.items():
        preds = [predict_fn(ex) for ex in examples]
        result["sets"][set_name] = score_set(examples, preds)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=[], help="HF model ids with local final/ checkpoints")
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    args = parser.parse_args()

    device = pick_device()
    examples_by_set = load_eval_examples()
    reports: list[dict[str, Any]] = []

    reports.append(
        evaluate_predictor("even_split_baseline", examples_by_set, predict_even_split)
    )

    for model_name in args.models:
        final_dir = output_dir_for(model_name) / "final"
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

        reports.append(evaluate_predictor(model_name, examples_by_set, _predict))

    meta = {
        "record_type": "meta",
        "track": "synthetic_boundary_encoder",
        "device": device,
        "tolerances": list(TOLERANCES),
        "n_synthetic_test": len(examples_by_set["synthetic_test"]),
        "n_gold": len(examples_by_set["gold"]),
        "models": args.models,
    }
    records: list[dict[str, Any]] = [meta]
    for report in reports:
        records.append({"record_type": "result", **report})

    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote eval report to {path}")
    for report in reports:
        print(f"\n== {report['predictor']} ==")
        for set_name, scores in report["sets"].items():
            f1s = ", ".join(f"tol{t} F1={scores[f'tol{t}']['f1']:.3f}" for t in TOLERANCES)
            print(f"  {set_name} (n={scores['n_examples']}): {f1s}")


if __name__ == "__main__":
    main()

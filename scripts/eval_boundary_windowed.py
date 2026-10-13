#!/usr/bin/env python3
"""Evaluate sliding-window boundary setups vs truncation baseline.

Primary target: ``overflow_cut_gold`` (long flats where 512 truncates).
Control: short overflow flats from ``fingerprint_overflow_split_proof`` that fit
in 512 tokens (windowing should not hurt).

Usage:
    uv run python scripts/eval_boundary_windowed.py
    uv run python scripts/eval_boundary_windowed.py --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from transformers import AutoModelForTokenClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from evaluation_harness import compute_boundary_prf
from scripts.boundary_windowed_infer import (
    SETUPS,
    n_windows_for,
    predict_cuts,
)
from scripts.corpus_scope import scope_meta
from scripts.train_synthetic_boundary_encoder import output_dir_for, pick_device

OUTPUT_DATASET = "boundary_windowed_eval"
MODEL_NAME = "globalise/GloBERTise"
TOLERANCES = (0, 50, 150, 300)
AXIS = "paragraph_axis_1626_1630"
OVERFLOW_GOLD = "overflow_cut_gold"
OVERFLOW_PROOF = "fingerprint_overflow_split_proof"


def load_encoder(
    model_name: str = MODEL_NAME,
    *,
    checkpoint: str | Path | None = None,
) -> dict[str, Any]:
    final_dir = Path(checkpoint) if checkpoint else (output_dir_for(model_name) / "final")
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


def flat_text(flat_id: str, axis_by_flat: dict[str, str]) -> str:
    return axis_by_flat.get(flat_id, "")


def build_axis_index() -> dict[str, str]:
    """Concatenate paragraph_axis rows per flat_id in para order."""
    buckets: dict[str, list[tuple[int, str]]] = {}
    for row in load(AXIS):
        flat = str(row.get("flat_id") or "")
        if not flat:
            continue
        para = int(row.get("para_index") or 0)
        buckets.setdefault(flat, []).append((para, str(row.get("text") or "")))
    out: dict[str, str] = {}
    for flat, parts in buckets.items():
        parts.sort(key=lambda item: item[0])
        out[flat] = "".join(text for _para, text in parts)
    return out


def overflow_gold_examples(axis_by_flat: dict[str, str]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in load(OVERFLOW_GOLD):
        if row.get("record_type") != "cut_proposal":
            continue
        flat = str(row["flat_id"])
        text = flat_text(flat, axis_by_flat)
        gold = [int(x) for x in (row.get("gold_offsets") or [])]
        if not text or not gold:
            continue
        examples.append({
            "example_id": flat,
            "flat_id": flat,
            "set": "overflow_gold",
            "concat_text": text,
            "concat_char_len": len(text),
            "gold_boundaries": gold,
            "n_cuts": len(gold),
            "uncertain": bool(row.get("uncertain")),
            "is_gold": bool(row.get("is_gold")),
        })
    return examples


def short_overflow_controls(axis_by_flat: dict[str, str]) -> list[dict[str, Any]]:
    """Short proof flats (fit in 512): use encoder_cuts from proof as pseudo-ref
    only for stability (window == trunc). Prefer gold when present — here none,
    so we score agreement with trunc_512 itself as a self-consistency check
    reported separately; for PRF we need gold. Skip PRF — report cut identity.
    """
    examples: list[dict[str, Any]] = []
    for row in load(OVERFLOW_PROOF):
        if row.get("record_type") != "split_proposal":
            continue
        flat = str(row.get("flat_id") or "")
        text = flat_text(flat, axis_by_flat)
        if not text:
            continue
        n_tok_est = len(text) / 4.0
        if n_tok_est > 480:
            continue
        n_cuts = int(row.get("n_cuts") or 0)
        if n_cuts <= 0:
            continue
        examples.append({
            "example_id": flat,
            "flat_id": flat,
            "set": "short_control",
            "concat_text": text,
            "concat_char_len": len(text),
            "gold_boundaries": list(row.get("encoder_cuts") or []),
            "n_cuts": n_cuts,
            "note": "pseudo-gold = stored trunc encoder_cuts; for identity check",
        })
    return examples


def score_example(gold: list[int], hyp: list[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tol in TOLERANCES:
        m = compute_boundary_prf(gold, hyp, tolerance=tol)
        out[f"f1@{tol}"] = m.f1
        out[f"p@{tol}"] = m.precision
        out[f"r@{tol}"] = m.recall
    return out


def mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def run_setup(
    setup: str,
    examples: list[dict[str, Any]],
    encoder: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ex in examples:
        text = ex["concat_text"]
        n_cuts = int(ex["n_cuts"])
        hyp = predict_cuts(
            text,
            n_cuts,
            model=encoder["model"],
            tokenizer=encoder["tokenizer"],
            device=encoder["device"],
            setup=setup,
        )
        n_win = (
            1
            if setup == "even_split"
            else n_windows_for(
                text,
                encoder["tokenizer"],
                max_length=int(SETUPS.get(setup, {}).get("max_length") or 512),
                stride=SETUPS.get(setup, {}).get("stride"),
            )
        )
        metrics = score_example(ex["gold_boundaries"], hyp)
        beyond = [
            g for g in ex["gold_boundaries"]
            if all(abs(g - h) > 150 for h in hyp)
        ]
        rows.append({
            "record_type": "prediction",
            "setup": setup,
            "eval_set": ex["set"],
            "example_id": ex["example_id"],
            "flat_id": ex.get("flat_id"),
            "concat_char_len": ex["concat_char_len"],
            "n_cuts": n_cuts,
            "n_windows": n_win,
            "gold_boundaries": ex["gold_boundaries"],
            "pred_boundaries": hyp,
            "gold_unmatched_at_150": beyond,
            "uncertain": ex.get("uncertain"),
            **metrics,
        })
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--checkpoint",
        default="",
        help="HF dir to load (default: synthetic GloBERTise final)",
    )
    args = parser.parse_args(argv)

    encoder = load_encoder(
        checkpoint=args.checkpoint or None,
    )
    axis_by_flat = build_axis_index()
    gold_ex = overflow_gold_examples(axis_by_flat)
    short_ex = short_overflow_controls(axis_by_flat)

    setups = ["even_split", *SETUPS.keys()]
    all_preds: list[dict[str, Any]] = []

    print(
        f"checkpoint={encoder['checkpoint']} device={encoder['device']}\n"
        f"overflow_gold={len(gold_ex)} short_control={len(short_ex)}\n"
    )
    header = (
        f"{'set':<14} {'setup':<18} {'F1@50':>7} {'F1@150':>7} {'F1@300':>7} "
        f"{'n_win':>5}"
    )
    print(header)
    print("-" * len(header))

    summary_rows: list[dict[str, Any]] = []
    for eval_set, examples in (
        ("overflow_gold", gold_ex),
        ("short_control", short_ex),
    ):
        if not examples:
            continue
        for setup in setups:
            preds = run_setup(setup, examples, encoder)
            all_preds.extend(preds)
            mean_win = mean_metric(preds, "n_windows")
            row = {
                "record_type": "summary",
                "eval_set": eval_set,
                "setup": setup,
                "n_examples": len(preds),
                "f1@50": mean_metric(preds, "f1@50"),
                "f1@150": mean_metric(preds, "f1@150"),
                "f1@300": mean_metric(preds, "f1@300"),
                "mean_n_windows": mean_win,
            }
            summary_rows.append(row)
            print(
                f"{eval_set:<14} {setup:<18} "
                f"{(row['f1@50'] or 0):7.3f} "
                f"{(row['f1@150'] or 0):7.3f} "
                f"{(row['f1@300'] or 0):7.3f} "
                f"{(mean_win or 0):5.1f}"
            )

    # Per-example detail for overflow gold under trunc vs best window
    print("\nPer-example overflow_gold (trunc_512 vs win_512_s256):")
    for ex in gold_ex:
        for setup in ("trunc_512", "win_512_s256", "win_512_s256_gap"):
            pred = next(
                r for r in all_preds
                if r["example_id"] == ex["example_id"] and r["setup"] == setup
            )
            print(
                f"  {ex['example_id'][-30:]} {setup}: "
                f"pred={pred['pred_boundaries']} gold={ex['gold_boundaries']} "
                f"F1@150={pred['f1@150']:.2f} unmatched@150={pred['gold_unmatched_at_150']}"
            )

    records = [
        {
            "record_type": "meta",
            "model_name": encoder["model_name"],
            "checkpoint": encoder["checkpoint"],
            "device": encoder["device"],
            "setups": setups,
            "n_overflow_gold": len(gold_ex),
            "n_short_control": len(short_ex),
            "note": (
                "Sliding-window inference vs 512 truncation. Primary = overflow_cut_gold. "
                "short_control uses stored trunc encoder_cuts as pseudo-gold (identity)."
            ),
            **scope_meta(),
        },
        *summary_rows,
        *all_preds,
    ]

    if args.write:
        path = save_semi_structured(
            records,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[OVERFLOW_GOLD, OVERFLOW_PROOF, AXIS],
            description=(
                "Boundary windowed-inference eval: trunc_512 vs win_512_s256/s128/"
                "s256_gap vs even_split on overflow_cut_gold + short controls."
            ),
        )
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()

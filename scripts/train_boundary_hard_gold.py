#!/usr/bin/env python3
"""Continue-finetune the synthetic boundary encoder on scarce hard gold.

Loads ``globalise/GloBERTise`` weights from the existing ``final`` checkpoint,
then trains on:
  - ``lumped_paragraph_boundary_gold`` (cuts + no_cut)
  - ``overflow_cut_gold`` (human cut_proposal; text from paragraph_axis)

Writes a **new** tagged checkpoint (does not overwrite the synthetic ``final``).

Usage:
    uv run python scripts/train_boundary_hard_gold.py
    caffeinate -dims uv run python scripts/train_boundary_hard_gold.py --write-meta
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
    Trainer,
    TrainingArguments,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.corpus_scope import scope_meta
from scripts.train_synthetic_boundary_encoder import (
    DEFAULT_MAX_LENGTH,
    BoundaryDataset,
    output_dir_for,
    pick_device,
)

BASE_MODEL = "globalise/GloBERTise"
TAG = "hardgold"
LUMPED = "lumped_paragraph_boundary_gold"
OVERFLOW = "overflow_cut_gold"
AXIS = "paragraph_axis_1626_1630"
OUTPUT_DATASET = "boundary_hard_gold_train_report"
DEFAULT_EPOCHS = 20.0
DEFAULT_BATCH = 2
DEFAULT_LR = 5e-6  # low LR continue-train


def axis_flat_text() -> dict[str, str]:
    buckets: dict[str, list[tuple[int, str]]] = {}
    for row in load(AXIS):
        flat = str(row.get("flat_id") or "")
        if not flat:
            continue
        buckets.setdefault(flat, []).append(
            (int(row.get("para_index") or 0), str(row.get("text") or ""))
        )
    out: dict[str, str] = {}
    for flat, parts in buckets.items():
        parts.sort(key=lambda item: item[0])
        out[flat] = "".join(t for _i, t in parts)
    return out


def load_hard_examples() -> list[dict[str, Any]]:
    """Build encoder-schema examples from lumped + overflow gold."""
    examples: list[dict[str, Any]] = []
    for row in load(LUMPED):
        if row.get("record_type") != "gold":
            continue
        text = str(row.get("text") or "")
        if not text.strip():
            continue
        offs = [int(x) for x in (row.get("gold_offsets") or [])]
        examples.append({
            "example_id": str(row.get("example_id") or row.get("date")),
            "source": LUMPED,
            "split": "train",
            "concat_text": text,
            "concat_char_len": len(text),
            "gold_boundaries": offs,
            "n_cuts": len(offs),
            "verdict": row.get("verdict"),
            "uncertain": bool(row.get("uncertain")),
        })

    flats = axis_flat_text()
    for row in load(OVERFLOW):
        if row.get("record_type") != "cut_proposal":
            continue
        if not row.get("is_gold"):
            continue
        flat = str(row["flat_id"])
        text = flats.get(flat, "")
        if not text.strip():
            continue
        offs = [int(x) for x in (row.get("gold_offsets") or [])]
        examples.append({
            "example_id": flat,
            "source": OVERFLOW,
            "split": "train",
            "concat_text": text,
            "concat_char_len": len(text),
            "gold_boundaries": offs,
            "n_cuts": len(offs),
            "uncertain": bool(row.get("uncertain")),
        })
    return examples


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--epochs", type=float, default=DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--lr", type=float, default=DEFAULT_LR)
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument("--tag", default=TAG)
    parser.add_argument(
        "--base-checkpoint",
        default="",
        help="HF dir to continue from (default: synthetic final)",
    )
    parser.add_argument("--write-meta", action="store_true", help=f"write {OUTPUT_DATASET}")
    args = parser.parse_args(argv)

    device = pick_device()
    base = Path(args.base_checkpoint) if args.base_checkpoint else (
        output_dir_for(BASE_MODEL) / "final"
    )
    if not base.exists():
        raise FileNotFoundError(f"base checkpoint missing: {base}")

    examples = load_hard_examples()
    n_cut = sum(1 for e in examples if e["n_cuts"] > 0)
    n_nocut = sum(1 for e in examples if e["n_cuts"] == 0)
    print(
        f"hard-gold continue-train  device={device}\n"
        f"  base={base}\n"
        f"  examples={len(examples)} (cuts={n_cut} no_cut={n_nocut})\n"
        f"  epochs={args.epochs} batch={args.batch_size} lr={args.lr}"
    )
    if len(examples) < 2:
        raise RuntimeError("need at least 2 hard-gold examples")

    tokenizer = AutoTokenizer.from_pretrained(base)
    model = AutoModelForTokenClassification.from_pretrained(base)
    train_ds = BoundaryDataset(examples, tokenizer, args.max_length)

    out_dir = output_dir_for(BASE_MODEL, tag=args.tag)
    out_dir.mkdir(parents=True, exist_ok=True)
    phase_dir = out_dir / "continue"
    targs = TrainingArguments(
        output_dir=str(phase_dir),
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        num_train_epochs=args.epochs,
        eval_strategy="no",
        save_strategy="epoch",
        logging_steps=5,
        report_to=[],
        seed=42,
        use_mps_device=(device == "mps"),
        use_cpu=(device == "cpu"),
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train_ds,
        data_collator=DataCollatorForTokenClassification(tokenizer),
        processing_class=tokenizer,
    )
    train_result = trainer.train()
    model = trainer.model

    final_dir = out_dir / "final"
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    meta = {
        "mode": "hard_gold_continue",
        "base_checkpoint": str(base),
        "model_name": BASE_MODEL,
        "tag": args.tag,
        "n_examples": len(examples),
        "n_cut": n_cut,
        "n_nocut": n_nocut,
        "example_ids": [e["example_id"] for e in examples],
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "max_length": args.max_length,
        "device": device,
        "train_loss": float(train_result.training_loss),
        **scope_meta(),
    }
    (final_dir / "train_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved continued model to {final_dir}")
    print(f"train_loss={meta['train_loss']:.4f}")

    if args.write_meta:
        path = save_semi_structured(
            [
                {"record_type": "meta", **meta},
                *[
                    {
                        "record_type": "train_example",
                        "example_id": e["example_id"],
                        "source": e["source"],
                        "n_cuts": e["n_cuts"],
                        "concat_char_len": e["concat_char_len"],
                        "uncertain": e.get("uncertain"),
                    }
                    for e in examples
                ],
            ],
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[LUMPED, OVERFLOW, AXIS],
            description=(
                "Hard-gold continue-train report: lumped_paragraph_boundary_gold + "
                "overflow_cut_gold into GloBERTise_hardgold checkpoint."
            ),
        )
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

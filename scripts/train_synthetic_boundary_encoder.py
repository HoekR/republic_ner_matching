#!/usr/bin/env python3
"""Fine-tune a HF encoder for synthetic merge-boundary token tagging.

Binary token labels: 1 = a gold cut falls at the end character of this token.
Curriculum: train stage-2 pairs first, then continue on stage-4 quads (optional joint).

Usage:
    uv run python scripts/train_synthetic_boundary_encoder.py --model emanjavacas/GysBERT
    uv run python scripts/train_synthetic_boundary_encoder.py --model globalise/GloBERTise --epochs 2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset
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

from data_io import load, resolve

FOLDS_DATASET = "synthetic_boundary_folds"
DEFAULT_MAX_LENGTH = 512
LABEL_ALL = -100


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_split_examples(
    split: str,
    stages: set[int] | None = None,
    *,
    folds_dataset: str = FOLDS_DATASET,
) -> list[dict[str, Any]]:
    rows = load(folds_dataset)
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("record_type") != "example":
            continue
        if row.get("split") != split:
            continue
        if stages is not None and int(row.get("stage") or 0) not in stages:
            continue
        out.append(row)
    return out


def char_boundaries_to_token_labels(
    offset_mapping: list[tuple[int, int]],
    boundaries: list[int],
    *,
    seq_len: int,
) -> list[int]:
    """Mark the token whose character span ends at / covers each boundary."""
    labels = [LABEL_ALL] * seq_len
    for index, (start, end) in enumerate(offset_mapping):
        if index >= seq_len:
            break
        if end == 0 and start == 0:
            labels[index] = LABEL_ALL  # special tokens
            continue
        labels[index] = 0
    remaining = set(int(b) for b in boundaries)
    # Prefer exact end==boundary; else first token with start < b <= end.
    for index, (start, end) in enumerate(offset_mapping):
        if labels[index] == LABEL_ALL:
            continue
        hit = {b for b in remaining if end == b or (start < b <= end)}
        if hit:
            labels[index] = 1
            remaining -= hit
    return labels


class BoundaryDataset(Dataset):
    def __init__(
        self,
        examples: list[dict[str, Any]],
        tokenizer: Any,
        max_length: int,
    ) -> None:
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        example = self.examples[index]
        text = str(example["concat_text"])
        encoded = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            return_offsets_mapping=True,
            return_tensors=None,
        )
        offsets = [(int(a), int(b)) for a, b in encoded.pop("offset_mapping")]
        labels = char_boundaries_to_token_labels(
            offsets,
            list(example.get("gold_boundaries") or []),
            seq_len=len(encoded["input_ids"]),
        )
        item = {key: torch.tensor(val) for key, val in encoded.items()}
        item["labels"] = torch.tensor(labels)
        return item


def model_slug(model_name: str) -> str:
    return model_name.replace("/", "__")


def output_dir_for(model_name: str, *, tag: str = "") -> Path:
    slug = model_slug(model_name)
    if tag:
        slug = f"{slug}_{tag}"
    return PROJECT_ROOT / "output" / "synthetic_boundary_models" / slug


def train_model(
    *,
    model_name: str,
    epochs: float,
    batch_size: int,
    max_length: int,
    lr: float,
    curriculum: bool,
    folds_dataset: str = FOLDS_DATASET,
    tag: str = "",
) -> Path:
    device = pick_device()
    print(f"Device: {device}; model: {model_name}; folds: {folds_dataset}; tag: {tag or 'default'}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name, num_labels=2)

    if curriculum:
        phases = [
            ("stage2", {2}),
            ("stage4", {2, 4}),
        ]
    else:
        phases = [("joint", {2, 4})]

    out_dir = output_dir_for(model_name, tag=tag)
    out_dir.mkdir(parents=True, exist_ok=True)

    for phase_name, stages in phases:
        train_ex = load_split_examples("train", stages, folds_dataset=folds_dataset)
        val_ex = load_split_examples("val", stages, folds_dataset=folds_dataset)
        print(f"Phase {phase_name}: train={len(train_ex)} val={len(val_ex)}")
        if not train_ex:
            raise RuntimeError(f"No train examples for phase {phase_name}")

        train_ds = BoundaryDataset(train_ex, tokenizer, max_length)
        val_ds = BoundaryDataset(val_ex, tokenizer, max_length) if val_ex else None
        phase_dir = out_dir / phase_name
        args = TrainingArguments(
            output_dir=str(phase_dir),
            learning_rate=lr,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            num_train_epochs=epochs,
            eval_strategy="epoch" if val_ds else "no",
            save_strategy="epoch",
            load_best_model_at_end=bool(val_ds),
            metric_for_best_model="eval_loss" if val_ds else None,
            greater_is_better=False if val_ds else None,
            logging_steps=25,
            report_to=[],
            seed=42,
            use_mps_device=(device == "mps"),
            use_cpu=(device == "cpu"),
        )

        collator = DataCollatorForTokenClassification(tokenizer)
        trainer = Trainer(
            model=model,
            args=args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            data_collator=collator,
            processing_class=tokenizer,
        )
        trainer.train()
        model = trainer.model

    final_dir = out_dir / "final"
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    meta = {
        "model_name": model_name,
        "folds_dataset": folds_dataset,
        "tag": tag or None,
        "max_length": max_length,
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "curriculum": curriculum,
        "device": device,
    }
    (final_dir / "train_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Saved model to {final_dir}")
    return final_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="HF model id")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--no-curriculum", action="store_true")
    parser.add_argument("--folds-dataset", default=FOLDS_DATASET)
    parser.add_argument(
        "--tag",
        default="",
        help="Output-dir suffix (e.g. 'hard' → .../GloBERTise_hard).",
    )
    args = parser.parse_args()
    resolve(args.folds_dataset)
    train_model(
        model_name=args.model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        max_length=args.max_length,
        lr=args.lr,
        curriculum=not args.no_curriculum,
        folds_dataset=args.folds_dataset,
        tag=args.tag,
    )


if __name__ == "__main__":
    main()

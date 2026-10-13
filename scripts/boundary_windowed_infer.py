#!/usr/bin/env python3
"""Sliding-window boundary inference for long HTR (past 512-token truncation).

Uses the tokenizer's ``return_overflowing_tokens`` so each window keeps
character offsets in the *original* string. Scores are max-pooled per char
position across windows; cuts are selected by a named strategy.

Setups (name → kwargs):
  trunc_512          — current behaviour (one window, truncate)
  win_512_s256       — 512-tok windows, stride 256, global top-k
  win_512_s128       — denser overlap
  win_512_s256_gap   — stride 256 + min-gap NMS selection
  even_split         — equal-distance null (no model)

Usage (library):
    from scripts.boundary_windowed_infer import predict_cuts, SETUPS
"""

from __future__ import annotations

from typing import Any

import torch

from scripts.synthetic_boundary_common import even_split_boundaries
from scripts.train_synthetic_boundary_encoder import DEFAULT_MAX_LENGTH

LABEL_MARGIN = True  # score = logit_1 - logit_0


def _score_windows(
    text: str,
    *,
    model: Any,
    tokenizer: Any,
    device: str,
    max_length: int,
    stride: int | None,
) -> dict[int, float]:
    """Max-pooled boundary scores keyed by character end offset."""
    if not text:
        return {}
    encode_kwargs: dict[str, Any] = {
        "truncation": True,
        "max_length": max_length,
        "return_offsets_mapping": True,
        "return_tensors": None,
    }
    if stride is None:
        # Single truncated window (legacy path).
        batch = tokenizer(text, **encode_kwargs)
        window_ids = [batch["input_ids"]]
        window_mask = [batch["attention_mask"]]
        window_offs = [batch["offset_mapping"]]
    else:
        batch = tokenizer(
            text,
            stride=int(stride),
            return_overflowing_tokens=True,
            **encode_kwargs,
        )
        window_ids = batch["input_ids"]
        window_mask = batch["attention_mask"]
        window_offs = batch["offset_mapping"]
        # HF may return a single window as a flat list when no overflow.
        if window_ids and isinstance(window_ids[0], int):
            window_ids = [window_ids]
            window_mask = [window_mask]
            window_offs = [window_offs]

    best: dict[int, float] = {}
    model.eval()
    with torch.no_grad():
        for ids, mask, offs in zip(window_ids, window_mask, window_offs, strict=True):
            input_ids = torch.tensor([ids], device=device)
            attention_mask = torch.tensor([mask], device=device)
            logits = model(input_ids=input_ids, attention_mask=attention_mask).logits[0]
            scores = logits[:, 1] - logits[:, 0]
            for index, (start, end) in enumerate(offs):
                start_i, end_i = int(start), int(end)
                if end_i == 0 and start_i == 0:
                    continue
                if end_i <= 0 or end_i >= len(text):
                    continue
                score = float(scores[index].item())
                if end_i not in best or score > best[end_i]:
                    best[end_i] = score
    return best


def select_topk(scored: dict[int, float], n_cuts: int) -> list[int]:
    ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
    return sorted(pos for pos, _ in ranked[:n_cuts])


def select_min_gap(
    scored: dict[int, float],
    n_cuts: int,
    *,
    char_len: int,
) -> list[int]:
    if n_cuts <= 0:
        return []
    gap = max(20, char_len // (2 * (n_cuts + 1)))
    ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
    chosen: list[int] = []
    for pos, _score in ranked:
        if all(abs(pos - c) >= gap for c in chosen):
            chosen.append(pos)
        if len(chosen) >= n_cuts:
            break
    return sorted(chosen)


SETUPS: dict[str, dict[str, Any]] = {
    "trunc_512": {
        "max_length": DEFAULT_MAX_LENGTH,
        "stride": None,
        "select": "topk",
    },
    "win_512_s256": {
        "max_length": DEFAULT_MAX_LENGTH,
        "stride": 256,
        "select": "topk",
    },
    "win_512_s128": {
        "max_length": DEFAULT_MAX_LENGTH,
        "stride": 128,
        "select": "topk",
    },
    "win_512_s256_gap": {
        "max_length": DEFAULT_MAX_LENGTH,
        "stride": 256,
        "select": "min_gap",
    },
}


def predict_cuts(
    text: str,
    n_cuts: int,
    *,
    model: Any,
    tokenizer: Any,
    device: str,
    setup: str = "win_512_s256",
) -> list[int]:
    """Predict ``n_cuts`` character offsets under a named setup."""
    if setup == "even_split":
        return even_split_boundaries(len(text), n_cuts)
    if setup not in SETUPS:
        raise KeyError(f"unknown setup {setup!r}; choose from {sorted(SETUPS)}")
    cfg = SETUPS[setup]
    scored = _score_windows(
        text,
        model=model,
        tokenizer=tokenizer,
        device=device,
        max_length=int(cfg["max_length"]),
        stride=cfg["stride"],
    )
    if cfg["select"] == "min_gap":
        return select_min_gap(scored, n_cuts, char_len=len(text))
    return select_topk(scored, n_cuts)


def n_windows_for(text: str, tokenizer: Any, *, max_length: int, stride: int | None) -> int:
    """How many encoder forwards a setup would run (diagnostic)."""
    if stride is None:
        return 1
    batch = tokenizer(
        text,
        truncation=True,
        max_length=max_length,
        stride=int(stride),
        return_overflowing_tokens=True,
        return_tensors=None,
    )
    ids = batch["input_ids"]
    if ids and isinstance(ids[0], int):
        return 1
    return len(ids)

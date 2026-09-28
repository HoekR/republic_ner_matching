"""Shared helpers for the synthetic resolution-merge / boundary-recovery track.

Separate from session-day ``boundary_gold_sample`` (S3 segmentation transfer). Uses the S6a
char axis: segment texts concatenated with no separator; internal cuts are cumulative lengths.
"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

import pandas as pd

MAX_EXTENT_PARAGRAPHS = 3
MIN_LENGTH_RATIO_DEFAULT = 1.5


def boundaries_from_segment_lengths(lengths: Sequence[int]) -> list[int]:
    """Cumulative char offsets after each segment except the last."""
    if len(lengths) < 2:
        return []
    running = 0
    out: list[int] = []
    for length in lengths[:-1]:
        running += int(length)
        out.append(running)
    return out


def concat_segments(segments: Sequence[str]) -> str:
    return "".join(segments)


def length_ratio(lengths: Sequence[int]) -> float:
    values = [int(x) for x in lengths if int(x) > 0]
    if len(values) < 2:
        return 1.0
    return max(values) / min(values)


def passes_length_heterogeneity(lengths: Sequence[int], min_ratio: float) -> bool:
    return length_ratio(lengths) >= min_ratio


def resolution_htr_text(axis: list[dict[str, Any]], start_index: int, end_index: int) -> str:
    """Paragraph-slice HTR text for one resolution (inclusive paragraph indices)."""
    parts: list[str] = []
    for index in range(start_index, end_index + 1):
        if index < 0 or index >= len(axis):
            continue
        parts.append(str(axis[index].get("text") or ""))
    return concat_segments(parts)


def label_separation(frame: pd.DataFrame) -> pd.DataFrame:
    """Row-level ``separated`` flag (PLAN.md acceptance criteria)."""
    work = frame.copy()
    work["extent"] = (work["paragraph_end_index"] - work["paragraph_start_index"] + 1).astype(int)
    shares = (
        work.groupby(["enriched_date", "paragraph_start_index"], sort=False)
        .size()
        .rename("n_share")
        .reset_index()
    )
    work = work.merge(shares, on=["enriched_date", "paragraph_start_index"], how="left")
    work["separated"] = (work["n_share"] == 1) & (work["extent"] <= MAX_EXTENT_PARAGRAPHS)
    return work


def length_ratio_band(ratio: float) -> str:
    if ratio < 1.5:
        return "ratio_lt_1_5"
    if ratio < 2.5:
        return "ratio_1_5_2_5"
    return "ratio_ge_2_5"


def year_band(date_str: str) -> str:
    year = int(str(date_str)[:4])
    return "1626_1627" if year <= 1627 else "1628_1630"


def gold_resolution_ids(gold_records: Sequence[dict[str, Any]] | None = None) -> set[str]:
    """Resolution ids that must never enter synthetic train/val/test."""
    if gold_records is None:
        from data_io import load

        gold_records = load("synthetic_boundary_gold")
    out: set[str] = set()
    for row in gold_records:
        if row.get("record_type") not in {"gold", "candidate"}:
            continue
        for rid in row.get("resolution_ids") or []:
            out.add(str(rid))
    return out


def even_split_boundaries(char_len: int, n_cuts: int) -> list[int]:
    """Null baseline: place ``n_cuts`` cuts at equal character intervals."""
    if n_cuts <= 0 or char_len <= 0:
        return []
    return [((rank + 1) * char_len) // (n_cuts + 1) for rank in range(n_cuts)]


def strip_leading_opening(
    text: str,
    phrase_matches: Sequence[tuple[int, int]],
    *,
    max_prefix: int = 120,
) -> tuple[str, int]:
    """Remove a leading opening-formula span if it starts within ``max_prefix`` chars.

    ``phrase_matches`` are ``(start, end)`` character spans already found in ``text``.
    Returns ``(stripped_text, n_chars_removed)``.
    """
    if not text:
        return text, 0
    leading = [
        (start, end)
        for start, end in phrase_matches
        if 0 <= int(start) <= max_prefix and int(end) > int(start)
    ]
    if not leading:
        return text, 0
    _start, end = max(leading, key=lambda span: (span[1], -span[0]))
    end = min(int(end), len(text))
    return text[end:], end


def hard_merge_segment_texts(
    texts: Sequence[str],
    phrase_matches_per_segment: Sequence[Sequence[tuple[int, int]]],
    *,
    max_prefix: int = 120,
) -> tuple[list[str], list[int], list[int], int]:
    """Strip openings on segments 2..n, recompute lengths and cumulative boundaries.

    Returns ``(new_texts, new_lengths, gold_boundaries, n_segments_stripped)``.
    """
    if len(texts) != len(phrase_matches_per_segment):
        raise ValueError("texts and phrase_matches_per_segment must align")
    new_texts: list[str] = []
    stripped = 0
    for index, text in enumerate(texts):
        if index == 0:
            new_texts.append(str(text))
            continue
        cleaned, removed = strip_leading_opening(
            str(text),
            phrase_matches_per_segment[index],
            max_prefix=max_prefix,
        )
        if removed:
            stripped += 1
        new_texts.append(cleaned if cleaned.strip() else str(text))
    lengths = [len(t) for t in new_texts]
    return new_texts, lengths, boundaries_from_segment_lengths(lengths), stripped


def windowed_predict_model(
    text: str,
    n_cuts: int,
    *,
    model: Any,
    tokenizer: Any,
    device: str,
    max_length: int,
    stride: int = 64,
) -> list[int]:
    """Top-``n_cuts`` boundary prediction, scored over the whole text via overlapping windows.

    Unlike a single truncated pass, no char position past ``max_length`` tokens is structurally
    unreachable: ``max_length``-token windows step by ``max_length - 2 - stride`` tokens (2
    reserved for CLS/SEP), and each char position keeps the max score seen across every window
    it falls in. Selection rule matches the non-windowed predictor (top-n_cuts by score).
    """
    import torch

    full = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    input_ids = full["input_ids"]
    offsets = full["offset_mapping"]
    n_tokens = len(input_ids)

    window = max_length - 2
    step = max(1, window - stride)
    cls_id, sep_id = tokenizer.cls_token_id, tokenizer.sep_token_id

    best: dict[int, float] = {}
    start = 0
    while True:
        end = min(start + window, n_tokens)
        chunk_ids = [cls_id, *input_ids[start:end], sep_id]
        input_tensor = torch.tensor([chunk_ids], device=device)
        attention_mask = torch.ones_like(input_tensor)
        with torch.no_grad():
            logits = model(input_ids=input_tensor, attention_mask=attention_mask).logits[0]
        scores = logits[:, 1] - logits[:, 0]
        for local_idx, (_char_start, char_end) in enumerate(offsets[start:end]):
            if char_end <= 0 or char_end >= len(text):
                continue
            score = float(scores[local_idx + 1].item())  # +1 for CLS
            if char_end not in best or score > best[char_end]:
                best[char_end] = score
        if end == n_tokens:
            break
        start += step

    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    return sorted(pos for pos, _ in ranked[:n_cuts])


def date_split_bucket(date_str: str, *, seed: int = 42) -> str:
    """Deterministic train/val/test assignment by calendar date (~70/15/15)."""
    digest = hashlib.md5(f"{seed}:{str(date_str)[:10]}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "val"
    return "test"
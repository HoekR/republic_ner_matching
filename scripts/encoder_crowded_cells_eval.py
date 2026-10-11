#!/usr/bin/env python3
"""Encoder on residual crowded cells after duplicate-session split wire.

Crowded = exclusive wired span with k_e > room (paragraph pigeonhole). At paragraph
granularity, ``separated`` cannot exceed ``room``, so the encoder is scored as:

1. **Separated gate (production criterion):** re-pack crowded dates with encoder-ordered
   cuts mapped to paragraph indices vs the wired sequential pack. Go only if corpus/slice
   separated rises (expected: no — structural ceiling).
2. **Lumped-gold smoke (12-row in-distribution check):** GloBERTise vs even-split on
   ``lumped_paragraph_boundary_gold`` cut-bearing rows — diagnostic only, not expanded.

Usage:
    uv run python -m scripts.encoder_crowded_cells_eval
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from evaluation_harness import compute_boundary_prf
from scripts.apply_duplicate_session_splits_eval import (
    _place_in_range,
    separated_total,
    slice_separated,
)
from scripts.corpus_scope import scope_meta
from scripts.eval_synthetic_boundary_encoder import predict_even_split, predict_model
from scripts.s6_duplicate_session_date_headings import session_paragraphs
from scripts.train_synthetic_boundary_encoder import (
    DEFAULT_MAX_LENGTH,
    output_dir_for,
    pick_device,
)

WIRE_REPORT = "duplicate_session_splits_wire_report"
CONCORDANCE = "resolution_concordance_1626_1630"
LUMPED_GOLD = "lumped_paragraph_boundary_gold"
OUTPUT = "encoder_crowded_cells_eval"
MODEL_ID = "globalise/GloBERTise"
MODEL_TAG = "hard"
TOLERANCES = (0, 50, 150)


def _crowded_from_wire(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r
        for r in report
        if r.get("record_type") == "date_wire"
        and r.get("wired")
        and int(r.get("k_e") or 0) > int(r.get("room") or 0)
    ]


def _span_text(
    by_session: dict[str, list[dict[str, Any]]], session: str, lo: int, hi: int
) -> tuple[str, list[tuple[int, int, int]]]:
    """Concat paragraphs [lo, hi]; return text and (para_pos, char_start, char_end) map."""
    paras = by_session.get(session) or []
    chunks: list[str] = []
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    for pos in range(lo, hi + 1):
        if pos >= len(paras):
            break
        text = str(paras[pos].get("text") or "")
        spans.append((pos, cursor, cursor + len(text)))
        chunks.append(text)
        cursor += len(text)
    return "".join(chunks), spans


def _cuts_to_paragraph_starts(
    cuts: list[int], spans: list[tuple[int, int, int]], lo: int, k: int
) -> list[int]:
    """Map char cuts + start → k paragraph start indices (monotone, in-span)."""
    # Boundaries: 0 + cuts + end → k segments; each segment's start char → paragraph
    bounds = [0, *sorted(cuts), spans[-1][2] if spans else 0]
    starts: list[int] = []
    for i in range(min(k, max(0, len(bounds) - 1))):
        char_s = bounds[i]
        para = lo
        for pos, a, b in spans:
            if a <= char_s < b or (char_s == b and pos == spans[-1][0]):
                para = pos
                break
            if char_s >= b:
                para = pos
        starts.append(para)
    while len(starts) < k:
        starts.append(starts[-1] if starts else lo)
    # Enforce non-decreasing
    for i in range(1, len(starts)):
        if starts[i] < starts[i - 1]:
            starts[i] = starts[i - 1]
    return starts


def _apply_starts(
    concordance: pd.DataFrame,
    session: str,
    date: str,
    starts: list[int],
) -> pd.DataFrame:
    out = concordance
    mask = (out["enriched_date"] == date) & (out["resolved_session_id"] == session)
    order = out.loc[mask].sort_values("resolution_index").index
    if len(order) != len(starts):
        return out
    out.loc[order, "paragraph_start_index"] = starts
    out.loc[order, "paragraph_end_index"] = starts
    out.loc[order, "paragraph_prediction_status"] = "encoder_crowded_repack"
    return out


def lumped_gold_smoke(model, tokenizer, device: str) -> dict[str, Any]:
    """In-distribution smoke on lumped_paragraph_boundary_gold (do not expand by hand)."""
    rows = [
        r
        for r in load(LUMPED_GOLD)
        if r.get("record_type") in (None, "gold", "annotation")
        or "gold_boundaries" in r
        or "cuts" in r
    ]
    # Accept several shapes from merge scripts
    examples: list[dict[str, Any]] = []
    for r in load(LUMPED_GOLD):
        text = r.get("concat_text") or r.get("paragraph_text") or r.get("text")
        gold = r.get("gold_boundaries") or r.get("boundaries") or r.get("cut_char_offsets")
        if not text or not gold:
            # cuts as markers in some exports
            if r.get("review_status") in ("cuts", "no_cut") and text:
                gold = r.get("gold_boundaries") or []
            else:
                continue
        if isinstance(gold, list) and gold and isinstance(gold[0], dict):
            gold = [int(g.get("char_offset") or g.get("offset")) for g in gold]
        gold = [int(x) for x in gold]
        if not gold and r.get("review_status") == "no_cut":
            continue  # skip empty for PRF
        examples.append(
            {
                "concat_text": str(text),
                "concat_char_len": len(str(text)),
                "gold_boundaries": gold,
                "n_cuts": len(gold),
            }
        )

    if not examples:
        # Fall back: count rows only
        all_rows = load(LUMPED_GOLD)
        return {
            "smoke": "lumped_paragraph_boundary_gold",
            "n_examples": 0,
            "n_source_rows": len(all_rows),
            "note": "no cut-bearing rows with text+gold_boundaries found; smoke skipped",
            "encoder_beats_even_split_tol50": None,
        }

    even_pred = [predict_even_split(ex) for ex in examples]
    enc_pred = [
        predict_model(
            ex, model=model, tokenizer=tokenizer, device=device, max_length=DEFAULT_MAX_LENGTH
        )
        for ex in examples
    ]
    golds = [ex["gold_boundaries"] for ex in examples]
    even_scores = {
        t: compute_boundary_prf(golds, even_pred, tolerance=t) for t in TOLERANCES
    }
    enc_scores = {
        t: compute_boundary_prf(golds, enc_pred, tolerance=t) for t in TOLERANCES
    }
    return {
        "smoke": "lumped_paragraph_boundary_gold",
        "n_examples": len(examples),
        "even_split_f1": {str(t): even_scores[t].get("f1") for t in TOLERANCES},
        "encoder_f1": {str(t): enc_scores[t].get("f1") for t in TOLERANCES},
        "encoder_beats_even_split_tol50": (
            float(enc_scores[50].get("f1") or 0) > float(even_scores[50].get("f1") or 0)
        ),
    }


def main() -> None:
    report = load(WIRE_REPORT)
    crowded = _crowded_from_wire(report)
    concordance = load(CONCORDANCE)
    concordance = concordance.copy()
    concordance["enriched_date"] = concordance["enriched_date"].astype(str).str.slice(0, 10)

    axis = load("paragraph_axis_1626_1630")
    by_session = session_paragraphs(axis)

    device = pick_device()
    model_dir = output_dir_for(MODEL_ID, tag=MODEL_TAG) / "final"
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForTokenClassification.from_pretrained(model_dir)
    model.to(device)
    model.eval()

    before = concordance.copy()
    after = concordance.copy()
    crowded_dates = {c["enriched_date"] for c in crowded}
    cell_logs: list[dict[str, Any]] = []

    for cell in crowded:
        session = cell["session"]
        date = cell["enriched_date"]
        lo, hi = cell["paragraph_range"]
        k = int(cell["k_e"])
        text, spans = _span_text(by_session, session, lo, hi)
        n_cuts = max(0, min(k - 1, max(0, len(text) - 1)))
        example = {
            "concat_text": text,
            "concat_char_len": len(text),
            "n_cuts": n_cuts,
            "gold_boundaries": [],
        }
        even_cuts = predict_even_split(example)
        enc_cuts = predict_model(
            example,
            model=model,
            tokenizer=tokenizer,
            device=device,
            max_length=DEFAULT_MAX_LENGTH,
        )
        enc_starts = _cuts_to_paragraph_starts(enc_cuts, spans, lo, k)
        after = _apply_starts(after, session, date, enc_starts)
        cell_logs.append(
            {
                "record_type": "crowded_cell",
                "session": session,
                "enriched_date": date,
                "room": cell["room"],
                "k_e": k,
                "n_cuts": n_cuts,
                "even_cuts": even_cuts,
                "encoder_cuts": enc_cuts,
                "encoder_paragraph_starts": enc_starts,
                "n_unique_encoder_starts": len(set(enc_starts)),
                "separated_ceiling_room": cell["room"],
            }
        )

    before_slice = slice_separated(before, crowded_dates) if crowded_dates else {
        "separated": 0, "attributed": 0, "n_dates": 0, "n_resolutions": 0
    }
    after_slice = slice_separated(after, crowded_dates) if crowded_dates else before_slice
    before_corpus = separated_total(before)
    after_corpus = separated_total(after)
    delta_slice = after_slice["separated"] - before_slice["separated"]
    delta_corpus = after_corpus - before_corpus
    separated_go = delta_slice > 0 and delta_corpus >= 0

    smoke = lumped_gold_smoke(model, tokenizer, device)

    meta = {
        "record_type": "meta",
        "model": MODEL_ID,
        "model_tag": MODEL_TAG,
        "n_crowded_cells": len(crowded),
        "before_slice": before_slice,
        "after_slice": after_slice,
        "delta_separated_slice": delta_slice,
        "before_corpus_separated": before_corpus,
        "after_corpus_separated": after_corpus,
        "delta_corpus_separated": delta_corpus,
        "separated_go": separated_go,
        "separated_go_rule": (
            "go iff crowded-slice separated rises and corpus does not fall; "
            "paragraph pigeonhole caps separated at room, so go is expected false "
            "until P3 credits sub-paragraph offsets"
        ),
        "lumped_smoke": smoke,
        "no_production_write": True,
        **scope_meta(),
    }
    save_semi_structured(
        [meta, *cell_logs],
        logical_name=OUTPUT,
        script=__file__,
        description=(
            "Encoder (GloBERTise_hard) on residual crowded exclusive split spans after "
            "wire_duplicate_session_splits; separated gate + lumped_paragraph_boundary_gold "
            "smoke. Diagnostic only — no concordance write."
        ),
        parent_sources=[WIRE_REPORT, CONCORDANCE, LUMPED_GOLD],
    )
    print(
        f"encoder_crowded: cells={len(crowded)} "
        f"separated_go={separated_go} "
        f"slice Δ{delta_slice:+d} corpus Δ{delta_corpus:+d} "
        f"lumped_smoke_n={smoke.get('n_examples')} "
        f"encoder_beats_even@50={smoke.get('encoder_beats_even_split_tol50')}"
    )


if __name__ == "__main__":
    main()

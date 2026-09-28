#!/usr/bin/env python3
"""Try the trained boundary-splitter model on real fold-in sessions.

``fold_in_candidates()`` (scripts/s4_day_status_resolution.py) resolves
``?``-status ledger rows by detecting that a date's content was folded into a
neighboring session rather than genuinely missing. Resolving day_status is
only half the job: the neighbor session's paragraphs still need to be split
between the two dates that now share it. Unlike the original lumped-paragraph
gold task (which had no reliable signal for how many real cuts existed), this
is a well-defined instance of exactly what globalise/GloBERTise was trained
for: exactly one real cut, with each side's expected resolution count (k_e)
known in advance to sanity-check the prediction against.

For each fold-in session this reconstructs the full session text (in true
paragraph order, from paragraph_axis_1626_1630), runs the trained model with
n_cuts=1, and writes a markdown report with ~150 chars of context on each
side of the predicted cut -- so a human can eyeball whether it lands on a
real day-boundary formula (e.g. "President ... Present den ...") rather than
mid-sentence.

Usage:
    uv run python scripts/eval_fold_in_boundary_split.py
    uv run python scripts/eval_fold_in_boundary_split.py --model globalise/GloBERTise
"""

from __future__ import annotations

import argparse
import json
import re
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
from scripts.s4_day_status_resolution import fold_in_candidates
from scripts.synthetic_boundary_common import windowed_predict_model
from scripts.train_synthetic_boundary_encoder import DEFAULT_MAX_LENGTH, output_dir_for, pick_device

LEDGER_DATASET = "session_date_status_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
OUTPUT_DATASET = "fold_in_boundary_split_eval"
REPORT_PATH = PROJECT_ROOT / "output" / "fold_in_boundary_split_report.md"

SESSION_PREFIX_RE = re.compile(r"^(.*)-resolution-(\d+)$")
CONTEXT_CHARS = 150


def session_text(axis_by_session: dict[str, list[dict[str, Any]]], session_id: str) -> tuple[str, list[int]]:
    """Full session text in true paragraph order, plus each paragraph's start offset."""
    rows = axis_by_session.get(session_id, [])

    def sort_key(row: dict[str, Any]) -> tuple[int, int]:
        m = SESSION_PREFIX_RE.match(row["flat_id"])
        ordinal = int(m.group(2)) if m else 0
        return (ordinal, int(row["para_index"]))

    rows = sorted(rows, key=sort_key)
    parts: list[str] = []
    starts: list[int] = []
    offset = 0
    for row in rows:
        starts.append(offset)
        text = str(row.get("text") or "")
        parts.append(text)
        offset += len(text) + 1  # joined by single newline below
    return "\n".join(parts), starts


def build_axis_index(axis_records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in axis_records:
        m = SESSION_PREFIX_RE.match(str(row.get("flat_id") or ""))
        if not m:
            continue
        index.setdefault(m.group(1), []).append(row)
    return index


def build_targets(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    """One target per fold-in session: the (date, k_e) pairs sharing it."""
    fold_in = fold_in_candidates(ledger)
    indexed = ledger.set_index(["inventory_id", "enriched_date"])
    row_by_key = {str(r["session_date_key"]): r for r in ledger.to_dict(orient="records")}

    by_session: dict[str, dict[str, dict[str, Any]]] = {}
    for key, info in fold_in.items():
        row = row_by_key[key]
        offset = -1 if info["fold_in_side"] == "previous" else 1
        anchor_date = str(pd.Period(row["enriched_date"], freq="D") + offset)
        parties = by_session.setdefault(info["resolved_session_id"], {})
        parties[row["enriched_date"]] = {"enriched_date": row["enriched_date"], "k_e": int(row["enriched_count"])}
        try:
            anchor_row = indexed.loc[(row["inventory_id"], anchor_date)]
            parties[anchor_date] = {"enriched_date": anchor_date, "k_e": int(anchor_row["enriched_count"])}
        except KeyError:
            pass

    return [
        {"resolved_session_id": session_id, "parties": sorted(parties.values(), key=lambda p: p["enriched_date"])}
        for session_id, parties in by_session.items()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="globalise/GloBERTise")
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LENGTH)
    parser.add_argument("--stride", type=int, default=64, help="token overlap between windows")
    args = parser.parse_args()

    ledger = pd.DataFrame(load(LEDGER_DATASET))
    axis_records = load(AXIS_DATASET)
    axis_by_session = build_axis_index(axis_records)
    targets = build_targets(ledger)

    final_dir = output_dir_for(args.model) / "final"
    if not final_dir.exists():
        raise FileNotFoundError(f"Missing trained model at {final_dir}")
    device = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(final_dir)
    model = AutoModelForTokenClassification.from_pretrained(final_dir).to(device)
    model.eval()

    records: list[dict[str, Any]] = []
    report_lines = [f"# Fold-in boundary split eval ({args.model}, windowed inference)\n"]
    n_windowed = 0
    for target in targets:
        session_id = target["resolved_session_id"]
        text, para_starts = session_text(axis_by_session, session_id)
        if not text.strip():
            continue

        n_cuts = max(1, len(target["parties"]) - 1)
        n_tokens = len(tokenizer(text, add_special_tokens=False)["input_ids"])
        windowed = n_tokens > args.max_length - 2
        n_windowed += int(windowed)
        cuts = windowed_predict_model(
            text, n_cuts, model=model, tokenizer=tokenizer, device=device, max_length=args.max_length, stride=args.stride
        )

        cut_contexts = [
            {
                "cut": cut,
                "context_before": text[max(0, cut - CONTEXT_CHARS):cut],
                "context_after": text[cut:cut + CONTEXT_CHARS],
            }
            for cut in cuts
        ]

        records.append(
            {
                "resolved_session_id": session_id,
                "parties": target["parties"],
                "n_cuts_expected": n_cuts,
                "predicted_cuts": cut_contexts,
                "n_tokens": n_tokens,
                "windowed": windowed,
            }
        )

        parties_desc = ", ".join(f"{p['enriched_date']} (k_e={p['k_e']})" for p in target["parties"])
        report_lines.append(f"## {session_id}\n")
        report_lines.append(f"Dates sharing this session: {parties_desc}\n")
        if windowed:
            report_lines.append(f"**Session has {n_tokens} tokens -- scored via overlapping {args.max_length}-token windows.**\n")
        if not cut_contexts:
            report_lines.append("No cut predicted.\n")
        for entry in cut_contexts:
            report_lines.append(f"Predicted cut at char {entry['cut']}:\n")
            report_lines.append(f"> ...{entry['context_before']}**|||CUT|||**{entry['context_after']}...\n")
        report_lines.append("")

    REPORT_PATH.write_text("\n".join(report_lines))
    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, parent_sources=[LEDGER_DATASET, AXIS_DATASET], script=__file__)

    print(f"Wrote {len(records)} predictions to {path}")
    print(f"Wrote human-readable report to {REPORT_PATH}")
    print(f"Sessions requiring more than one window: {n_windowed}/{len(records)}")


if __name__ == "__main__":
    main()

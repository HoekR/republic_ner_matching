#!/usr/bin/env python3
"""Diagnostically apply gate-eligible duplicate-session splits; score separated.

Reads ``duplicate_session_date_splits`` (machine-gated proposals). For each
``gate_eligible`` session, places each claimant date with an *exclusive*
``proposed_ranges`` entry into that paragraph span (session-local indices).
Dates that share an undivided earlier range (3+ claimant sessions) are abstained.

Placement inside a span (diagnostic, not a new NW pass):
- ``k_e <= room`` → sequential unique starts, extent 1 (maximises separated).
- ``k_e > room`` → pack starts across the room (pigeonhole; not all can separate).

Does **not** write concordance, PINNED_TO, or predictions. Persists an eval report.

Usage:
    uv run python -m scripts.apply_duplicate_session_splits_eval
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.corpus_scope import scope_meta
from scripts.metrics_separation_span_table import (
    CEILING_SEPARABLE,
    MAX_EXTENT_PARAGRAPHS,
    count_separated_per_day,
)

SPLITS_DATASET = "duplicate_session_date_splits"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "duplicate_session_splits_apply_eval"


def _place_in_range(k: int, lo: int, hi: int) -> list[tuple[int, int]]:
    """Return k (start, end) pairs inside [lo, hi], session-local inclusive."""
    if k <= 0 or hi < lo:
        return []
    room = hi - lo + 1
    if k <= room:
        return [(lo + i, lo + i) for i in range(k)]
    # Pack: spread starts across room; extent 1 still (sharing starts kills separated).
    starts = [lo + min(room - 1, (i * room) // k) for i in range(k)]
    return [(s, s) for s in starts]


def load_eligible_proposals() -> list[dict[str, Any]]:
    rows = load(SPLITS_DATASET)
    return [r for r in rows if r.get("gate_eligible") and r.get("proposed_ranges")]


def apply_splits(
    concordance: pd.DataFrame, proposals: list[dict[str, Any]]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Return a copy of concordance with exclusive-range dates re-placed, plus per-date log."""
    out = concordance.copy()
    out["enriched_date"] = out["enriched_date"].astype(str).str.slice(0, 10)
    log: list[dict[str, Any]] = []

    for prop in proposals:
        session = prop["session"]
        for date, info in sorted(prop["proposed_ranges"].items()):
            date = str(date)[:10]
            undivided = list(info.get("undivided_among") or [])
            lo, hi = info["paragraph_range"]
            mask = (out["enriched_date"] == date) & (out["resolved_session_id"] == session)
            n = int(mask.sum())
            entry: dict[str, Any] = {
                "record_type": "date_apply",
                "session": session,
                "enriched_date": date,
                "paragraph_range": [lo, hi],
                "room": hi - lo + 1,
                "k_e": n,
                "undivided_among": undivided,
                "applied": False,
                "reason": "",
            }
            if undivided:
                entry["reason"] = "abstain_undivided_shared_range"
                log.append(entry)
                continue
            if n == 0:
                entry["reason"] = "no_concordance_rows"
                log.append(entry)
                continue
            placements = _place_in_range(n, lo, hi)
            order = out.loc[mask].sort_values("resolution_index").index
            starts = [p[0] for p in placements]
            ends = [p[1] for p in placements]
            out.loc[order, "paragraph_start_index"] = starts
            out.loc[order, "paragraph_end_index"] = ends
            out.loc[order, "paragraph_prediction_status"] = "duplicate_split_apply"
            entry["applied"] = True
            entry["reason"] = "placed"
            entry["n_unique_starts"] = len(set(starts))
            log.append(entry)
    return out, log


def separated_total(concordance: pd.DataFrame) -> int:
    per_day = count_separated_per_day(concordance)
    return int(per_day["separated_count"].sum()) if len(per_day) else 0


def slice_separated(concordance: pd.DataFrame, dates: set[str]) -> dict[str, int]:
    """Separated / attributed counts restricted to a date set."""
    work = concordance.loc[
        concordance["enriched_date"].astype(str).str.slice(0, 10).isin(dates)
    ].copy()
    per_day = count_separated_per_day(work)
    attributed = int(
        work["paragraph_start_index"].notna().sum()
    )
    return {
        "separated": int(per_day["separated_count"].sum()) if len(per_day) else 0,
        "attributed": attributed,
        "n_dates": len(dates),
        "n_resolutions": len(work),
    }


def run_eval() -> list[dict[str, Any]]:
    proposals = load_eligible_proposals()
    concordance = load(CONCORDANCE_DATASET)
    before_frame = concordance.copy()
    before_frame["enriched_date"] = before_frame["enriched_date"].astype(str).str.slice(0, 10)

    after_frame, date_log = apply_splits(concordance, proposals)
    applied_dates = {e["enriched_date"] for e in date_log if e["applied"]}
    abstained_dates = {e["enriched_date"] for e in date_log if not e["applied"]}
    all_claimant_dates = {e["enriched_date"] for e in date_log}

    before_slice = slice_separated(before_frame, applied_dates)
    after_slice = slice_separated(after_frame, applied_dates)
    before_all_claimants = slice_separated(before_frame, all_claimant_dates)
    after_all_claimants = slice_separated(after_frame, all_claimant_dates)
    before_corpus = separated_total(before_frame)
    after_corpus = separated_total(after_frame)

    delta_slice = after_slice["separated"] - before_slice["separated"]
    delta_corpus = after_corpus - before_corpus
    # Go if the applied-date slice gains separated and corpus does not regress.
    go = delta_slice > 0 and delta_corpus >= 0

    meta = {
        "record_type": "meta",
        "n_eligible_sessions": len(proposals),
        "n_date_rows": len(date_log),
        "n_dates_applied": len(applied_dates),
        "n_dates_abstained": len(abstained_dates),
        "before_slice": before_slice,
        "after_slice": after_slice,
        "delta_separated_slice": delta_slice,
        "before_all_claimants": before_all_claimants,
        "after_all_claimants": after_all_claimants,
        "before_corpus_separated": before_corpus,
        "after_corpus_separated": after_corpus,
        "delta_corpus_separated": delta_corpus,
        "ceiling": CEILING_SEPARABLE,
        "max_extent": MAX_EXTENT_PARAGRAPHS,
        "go": go,
        "go_rule": (
            "go iff separated on applied exclusive-range dates increases "
            "AND corpus-wide separated does not fall"
        ),
        "no_production_write": True,
        **scope_meta(),
    }
    return [meta, *date_log]


def main() -> None:
    records = run_eval()
    save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        script=__file__,
        description=(
            "Diagnostic apply of gate-eligible duplicate_session_date_splits onto a concordance "
            "copy: exclusive proposed_ranges get sequential/packed paragraph placement; undivided "
            "3+ earlier dates abstain. Scores separated (unique start, extent<=3) before/after on "
            "the applied-date slice and corpus-wide. No concordance/PINNED_TO write. go=true only "
            "if slice separated rises and corpus does not fall."
        ),
        parent_sources=[SPLITS_DATASET, CONCORDANCE_DATASET],
    )
    meta = records[0]
    print(
        f"apply_eval: go={meta['go']} "
        f"slice {meta['before_slice']['separated']} → {meta['after_slice']['separated']} "
        f"(Δ{meta['delta_separated_slice']:+d}) "
        f"corpus {meta['before_corpus_separated']} → {meta['after_corpus_separated']} "
        f"(Δ{meta['delta_corpus_separated']:+d}) "
        f"applied_dates={meta['n_dates_applied']} abstained={meta['n_dates_abstained']}"
    )
    if meta["go"]:
        print("GO: wire many-to-many ranges for exclusive dates is worth a production step.")
    else:
        print("NO-GO: do not promote to production; inspect date_apply abstentions / packing.")


if __name__ == "__main__":
    main()

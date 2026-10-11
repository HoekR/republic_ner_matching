#!/usr/bin/env python3
"""Production-wire gate-eligible exclusive duplicate-session split ranges.

Writes updated ``resolution_concordance_1626_1630`` (versioned via provenance parents)
and a change report. Undivided 3+ earlier dates abstain. Prefers existing in-range
paragraph starts; fills NaN / out-of-range with sequential slots in the exclusive span.

Usage:
    uv run python -m scripts.wire_duplicate_session_splits
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_parquet, save_semi_structured
from scripts.apply_duplicate_session_splits_eval import (
    _place_in_range,
    load_eligible_proposals,
    separated_total,
    slice_separated,
)
from scripts.corpus_scope import scope_meta

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
REPORT_DATASET = "duplicate_session_splits_wire_report"


def _place_prefer_existing(
    group: pd.DataFrame, lo: int, hi: int
) -> list[tuple[int, int]]:
    """Keep in-range starts when possible; fill the rest with free slots in [lo, hi]."""
    ordered = group.sort_values("resolution_index")
    k = len(ordered)
    room = hi - lo + 1
    assigned: list[tuple[int, int] | None] = [None] * k
    used: set[int] = set()

    starts = ordered["paragraph_start_index"].tolist()
    ends = ordered["paragraph_end_index"].tolist()
    for i, (start, end) in enumerate(zip(starts, ends)):
        if pd.isna(start) or pd.isna(end):
            continue
        s, e = int(start), int(end)
        if lo <= s <= hi:
            e = min(max(e, s), hi)
            assigned[i] = (s, e)
            used.add(s)

    free = [p for p in range(lo, hi + 1) if p not in used]
    fill = _place_in_range(sum(1 for a in assigned if a is None), lo, hi)
    # Prefer unused starts from fill
    fill_iter = iter(
        (s, e) for s, e in fill if s not in used or True
    )
    free_iter = iter(free)
    for i in range(k):
        if assigned[i] is not None:
            continue
        try:
            slot = next(free_iter)
            assigned[i] = (slot, slot)
            used.add(slot)
        except StopIteration:
            # Overfull: pack onto lo..hi
            s = lo + (i % room)
            assigned[i] = (s, s)
    return [a if a is not None else (lo, lo) for a in assigned]


def wire_concordance(
    concordance: pd.DataFrame, proposals: list[dict[str, Any]]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    out = concordance.copy()
    out["enriched_date"] = out["enriched_date"].astype(str).str.slice(0, 10)
    log: list[dict[str, Any]] = []

    for prop in proposals:
        session = prop["session"]
        for date, info in sorted(prop["proposed_ranges"].items()):
            date = str(date)[:10]
            undivided = list(info.get("undivided_among") or [])
            lo, hi = (int(x) for x in info["paragraph_range"])
            mask = (out["enriched_date"] == date) & (out["resolved_session_id"] == session)
            n = int(mask.sum())
            entry: dict[str, Any] = {
                "record_type": "date_wire",
                "session": session,
                "enriched_date": date,
                "paragraph_range": [lo, hi],
                "room": hi - lo + 1,
                "k_e": n,
                "undivided_among": undivided,
                "wired": False,
                "reason": "",
                "n_kept_in_range": 0,
                "n_filled": 0,
                "n_status_promoted": 0,
            }
            if undivided:
                entry["reason"] = "abstain_undivided_shared_range"
                log.append(entry)
                continue
            if n == 0:
                entry["reason"] = "no_concordance_rows"
                log.append(entry)
                continue

            group = out.loc[mask]
            before_na = int(group["paragraph_start_index"].isna().sum())
            kept = 0
            for _, row in group.iterrows():
                s = row["paragraph_start_index"]
                if pd.notna(s) and lo <= int(s) <= hi:
                    kept += 1
            placements = _place_prefer_existing(group, lo, hi)
            order = group.sort_values("resolution_index").index
            out.loc[order, "paragraph_start_index"] = [p[0] for p in placements]
            out.loc[order, "paragraph_end_index"] = [p[1] for p in placements]
            out.loc[order, "paragraph_prediction_status"] = "duplicate_split_wire"
            promoted = 0
            status_mask = mask & (out["status"] == "cross_day_shift")
            promoted = int(status_mask.sum())
            out.loc[status_mask, "status"] = "resolved_auto"
            entry.update(
                {
                    "wired": True,
                    "reason": "wired",
                    "n_kept_in_range": kept,
                    "n_filled": before_na,
                    "n_status_promoted": promoted,
                }
            )
            log.append(entry)
    return out, log


def main() -> None:
    proposals = load_eligible_proposals()
    before = load(CONCORDANCE_DATASET)
    before = before.copy()
    before["enriched_date"] = before["enriched_date"].astype(str).str.slice(0, 10)

    after, log = wire_concordance(before, proposals)
    applied_dates = {e["enriched_date"] for e in log if e["wired"]}
    before_slice = slice_separated(before, applied_dates)
    after_slice = slice_separated(after, applied_dates)
    before_corpus = separated_total(before)
    after_corpus = separated_total(after)
    delta_slice = after_slice["separated"] - before_slice["separated"]
    delta_corpus = after_corpus - before_corpus

    save_parquet(
        after,
        logical_name=CONCORDANCE_DATASET,
        script=__file__,
        parent_sources=[
            CONCORDANCE_DATASET,
            "duplicate_session_date_splits",
        ],
        description=(
            "resolution_concordance after production wire of gate-eligible exclusive "
            "duplicate-session split ranges (scripts/wire_duplicate_session_splits.py). "
            "cross_day_shift rows that received paragraph attribution promoted to resolved_auto. "
            "Undivided 3+ earlier dates left untouched."
        ),
    )

    meta = {
        "record_type": "meta",
        "n_eligible_sessions": len(proposals),
        "n_dates_wired": len(applied_dates),
        "n_dates_abstained": sum(1 for e in log if not e["wired"]),
        "before_slice": before_slice,
        "after_slice": after_slice,
        "delta_separated_slice": delta_slice,
        "before_corpus_separated": before_corpus,
        "after_corpus_separated": after_corpus,
        "delta_corpus_separated": delta_corpus,
        "n_status_promoted": sum(e.get("n_status_promoted", 0) for e in log),
        "go_confirmed": delta_slice > 0 and delta_corpus >= 0,
        **scope_meta(),
    }
    save_semi_structured(
        [meta, *log],
        logical_name=REPORT_DATASET,
        script=__file__,
        description=(
            "Change report for wire_duplicate_session_splits: per-date wire log + separated "
            "before/after on wired exclusive dates and corpus-wide."
        ),
        parent_sources=[CONCORDANCE_DATASET, "duplicate_session_date_splits"],
    )
    print(
        f"wired: dates={meta['n_dates_wired']} abstained={meta['n_dates_abstained']} "
        f"slice {before_slice['separated']}→{after_slice['separated']} (Δ{delta_slice:+d}) "
        f"corpus {before_corpus}→{after_corpus} (Δ{delta_corpus:+d}) "
        f"status_promoted={meta['n_status_promoted']} go={meta['go_confirmed']}"
    )


if __name__ == "__main__":
    main()

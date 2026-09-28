#!/usr/bin/env python3
"""Explorer for the missing-ordinary-session problem (?/status ledger rows).

Traced case: 1626-03-28 (inv 3185) got ledger status_code="?" -- no same-day
HTR session was matched, session numbering skips straight from the previous
day's session to the next day's -- and resolve_row() has no recovery path for
"?" (unlike "N"), so the date silently falls through to day_status="uncertain"
even when another inventory (e.g. the secret register) resolves and masks it.

This prints, per "?"-status ledger row: the session-number gap between the
previous- and next-day candidate sessions, and whether the enriched_date was
ultimately rescued by a different inventory. A gap of 0 (adjacent session
numbers, e.g. num-56 -> num-57) means no physical page was ever assigned to
this date at all -- the day's content, if any, is most likely embedded inside
one of the two adjacent sessions rather than genuinely lost, which is the
case worth checking first for automatic (not just manual) recovery.

Usage:
    uv run python scripts/explore_missing_session_candidates.py
    uv run python scripts/explore_missing_session_candidates.py --date 1626-03-28
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load

LEDGER_DATASET = "session_date_status_1626_1630"
RESOLUTION_DATASET = "s4_day_status_resolution"

SESSION_NUM_RE = re.compile(r"-num-(\d+)$")


def _session_num(session_id: object) -> int | None:
    if not isinstance(session_id, str):
        return None
    m = SESSION_NUM_RE.search(session_id)
    return int(m.group(1)) if m else None


def build_frame() -> pd.DataFrame:
    ledger = pd.DataFrame(load(LEDGER_DATASET))
    resolution = pd.DataFrame(load(RESOLUTION_DATASET))

    uncertain = ledger.loc[ledger["status_code"] == "?"].copy()
    uncertain["prev_session_id"] = uncertain["previous_day_session_ids"].apply(
        lambda ids: ids[-1] if len(ids) else None
    )
    uncertain["next_session_id"] = uncertain["next_day_session_ids"].apply(
        lambda ids: ids[0] if len(ids) else None
    )
    uncertain["prev_num"] = uncertain["prev_session_id"].apply(_session_num)
    uncertain["next_num"] = uncertain["next_session_id"].apply(_session_num)
    uncertain["gap"] = uncertain["next_num"] - uncertain["prev_num"] - 1

    day_status_by_date = resolution.groupby("enriched_date")["day_status"].apply(
        lambda s: "resolved_auto" if (s == "resolved_auto").any() else s.iloc[0]
    )
    uncertain["date_rescued_by_other_inventory"] = (
        uncertain["enriched_date"].map(day_status_by_date) == "resolved_auto"
    )
    return uncertain


def print_summary(frame: pd.DataFrame) -> None:
    n_total = len(frame)
    n_rescued = int(frame["date_rescued_by_other_inventory"].sum())
    n_adjacent_gap = int((frame["gap"] == 0).sum())
    print(f"'?'-status ledger rows: {n_total}")
    print(f"  rescued by a different inventory (masked, but this inventory's content still lost): {n_rescued}")
    print(f"  truly unresolved for the date (no inventory resolved): {n_total - n_rescued}")
    print(f"  adjacent session-number gap (gap=0, e.g. num-56 -> num-57): {n_adjacent_gap}")
    print(f"  non-adjacent gap (candidate sessions further apart): {n_total - n_adjacent_gap}")
    print()
    print(frame["gap"].value_counts(dropna=False).sort_index().to_string())
    print()
    cols = [
        "enriched_date", "inventory_id", "prev_session_id", "next_session_id",
        "gap", "date_rescued_by_other_inventory",
    ]
    print(frame[cols].sort_values("enriched_date").head(20).to_string(index=False))


def print_date_detail(frame: pd.DataFrame, date: str) -> None:
    rows = frame.loc[frame["enriched_date"] == date]
    if rows.empty:
        print(f"No '?'-status row for {date}")
        return
    for _, row in rows.iterrows():
        print(row.to_dict())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Show detail for one enriched_date (YYYY-MM-DD)")
    args = parser.parse_args()

    frame = build_frame()
    if args.date:
        print_date_detail(frame, args.date)
    else:
        print_summary(frame)


if __name__ == "__main__":
    main()

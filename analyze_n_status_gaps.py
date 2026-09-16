#!/usr/bin/env python3
"""Diagnose whether N-status session-date rows are true gaps or a too-narrow search window."""

from __future__ import annotations

from collections import Counter

import pandas as pd

from data_io import load
from scripts.build_session_date_ledger import _dates_in_scope, _session_parts

LEDGER_DATASET = "session_date_status_1626_1630"
FLAT_DATASET = "resolutions_flat"
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MAX_OFFSET_DAYS = 14
EXTRA_OFFSETS = [o for o in range(-MAX_OFFSET_DAYS, MAX_OFFSET_DAYS + 1) if o not in (-1, 0, 1)]


def direct_sessions(flat: pd.DataFrame) -> set[tuple[int, str]]:
    flat = flat.copy()
    flat["date"] = _dates_in_scope(flat["date"])
    parts = _session_parts(flat["id"])
    flat["inventory_id"] = parts["inventory_id"].astype(int)
    return set(zip(flat["inventory_id"], flat["date"]))


def nearest_recovery_offset(inventory_id: int, period: pd.Period, known: set[tuple[int, str]]) -> int | None:
    for offset in EXTRA_OFFSETS:
        if (inventory_id, str(period + offset)) in known:
            return offset
    return None


def main() -> None:
    ledger = load(LEDGER_DATASET)
    n_rows = ledger.loc[ledger["status_code"] == "N", ["inventory_id", "enriched_date"]].copy()
    n_rows["enriched_period"] = pd.PeriodIndex(n_rows["enriched_date"], freq="D")
    n_rows["weekday"] = [WEEKDAY_NAMES[d] for d in n_rows["enriched_period"].dayofweek]

    print(f"N-status rows: {len(n_rows)}")
    print("Weekday distribution:")
    for name, count in Counter(n_rows["weekday"]).most_common():
        print(f"  {name}: {count} ({count / len(n_rows):.1%})")

    known = direct_sessions(load(FLAT_DATASET))
    n_rows["nearest_offset"] = [
        nearest_recovery_offset(int(r.inventory_id), r.enriched_period, known) for r in n_rows.itertuples(index=False)
    ]

    recovered = n_rows.loc[n_rows["nearest_offset"].notna()]
    print(f"\nRows with a same-inventory HTR session within +/-{MAX_OFFSET_DAYS} days "
          f"(beyond the +/-1 window already checked): {len(recovered)} / {len(n_rows)}")
    if not recovered.empty:
        print("Offset distribution among recovered rows:")
        for offset, count in Counter(recovered["nearest_offset"]).most_common():
            print(f"  {offset:+d} day(s): {count}")

    unrecovered = n_rows.loc[n_rows["nearest_offset"].isna()]
    print(f"\nRows with NO same-inventory HTR session within +/-{MAX_OFFSET_DAYS} days: {len(unrecovered)} / {len(n_rows)}")
    print("Weekday distribution of unrecovered rows:")
    for name, count in Counter(unrecovered["weekday"]).most_common():
        print(f"  {name}: {count} ({count / len(unrecovered):.1%})")


if __name__ == "__main__":
    main()
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
EXTRA_OFFSETS = sorted(
    (o for o in range(-MAX_OFFSET_DAYS, MAX_OFFSET_DAYS + 1) if o not in (-1, 0, 1)),
    key=lambda o: (abs(o), o),
)

# The "modest window widen" follow-up from docs/CANDIDATE_SCORING_AND_CONCORDANCE.md
# Step 1: score candidates only for the front-loaded +/-2..+/-7 band (523/753
# recoverable N rows, 16.4% of the N population), not the full +/-14 tested
# by the diagnostic above -- recoveries past +/-7 are too speculative to
# treat as scoring candidates.
WIDE_WINDOW_MAX_DAYS = 7
WIDE_WINDOW_OFFSETS = sorted(
    (o for o in EXTRA_OFFSETS if abs(o) <= WIDE_WINDOW_MAX_DAYS), key=lambda o: (abs(o), o)
)


def direct_session_ids(flat: pd.DataFrame) -> dict[tuple[int, str], list[str]]:
    """Map (inventory_id, date) to its HTR session ids, per the resolutions_flat corpus."""
    flat = flat.copy()
    flat["date"] = _dates_in_scope(flat["date"])
    parts = _session_parts(flat["id"])
    flat["inventory_id"] = parts["inventory_id"].astype(int)
    flat["session_id"] = parts[0]
    grouped = flat.groupby(["inventory_id", "date"])["session_id"].agg(lambda values: sorted(set(values)))
    return dict(grouped.items())


def direct_sessions(flat: pd.DataFrame) -> set[tuple[int, str]]:
    return set(direct_session_ids(flat))


def nearest_recovery_offset(inventory_id: int, period: pd.Period, known: set[tuple[int, str]]) -> int | None:
    for offset in EXTRA_OFFSETS:
        if (inventory_id, str(period + offset)) in known:
            return offset
    return None


def nearest_recovery_candidates(
    inventory_id: int,
    period: pd.Period,
    known: dict[tuple[int, str], list[str]],
    offsets: list[int] = WIDE_WINDOW_OFFSETS,
) -> tuple[int, list[str]] | None:
    """Return the nearest offset (within ``offsets``) and its HTR session ids, if any."""
    for offset in offsets:
        session_ids = known.get((inventory_id, str(period + offset)))
        if session_ids:
            return offset, session_ids
    return None


def main() -> None:
    ledger = load(LEDGER_DATASET)
    n_rows = ledger.loc[ledger["status_code"] == "N", ["inventory_id", "enriched_date"]].copy()
    n_rows["enriched_period"] = pd.PeriodIndex(n_rows["enriched_date"], freq="D")
    n_rows["weekday"] = [WEEKDAY_NAMES[d] for d in n_rows["enriched_period"].dt.dayofweek]

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
            print(f"  {int(offset):+d} day(s): {count}")

    unrecovered = n_rows.loc[n_rows["nearest_offset"].isna()]
    print(f"\nRows with NO same-inventory HTR session within +/-{MAX_OFFSET_DAYS} days: {len(unrecovered)} / {len(n_rows)}")
    print("Weekday distribution of unrecovered rows:")
    for name, count in Counter(unrecovered["weekday"]).most_common():
        print(f"  {name}: {count} ({count / len(unrecovered):.1%})")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""Tier V — nihil-actum invariant check (docs/METRICS.md).

A day whose concordance ``day_status`` is ``nihil_actum`` is authoritative:
its attributed-resolution count (rows with a non-null ``resolved_session_id``)
must be exactly 0. Any nonzero count is a proven date/session attribution
error and blocks trusting Tier O/D numbers for that day.

Also emits the shared per-day ``K_e`` series that Tier D (and later Tier O)
reuse: one ``day`` record per enriched calendar date, with ``k_e_signal`` set
to 0 on nihil days so drift diagnostics treat them as structural zeros rather
than 1-row formula entries.

Usage:
    uv run python scripts/metrics_nihil_actum_invariant.py
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

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
DAY_STATUS_DATASET = "s4_day_status_resolution"
OUTPUT_DATASET = "metrics_nihil_actum_invariant"

NIHIL_STATUS = "nihil_actum"


def build_day_series(concordance: pd.DataFrame) -> pd.DataFrame:
    """One row per enriched_date with K_e, attribution counts, and invariant flags."""
    required = {"enriched_date", "day_status", "resolved_session_id"}
    missing = required - set(concordance.columns)
    if missing:
        raise ValueError(f"concordance missing columns: {sorted(missing)}")

    work = concordance.loc[:, ["enriched_date", "day_status", "resolved_session_id"]].copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    work["attributed"] = work["resolved_session_id"].notna()

    grouped = (
        work.groupby("enriched_date", sort=True)
        .agg(
            k_e=("enriched_date", "size"),
            attributed_count=("attributed", "sum"),
            day_status=("day_status", "first"),
            n_distinct_day_status=("day_status", "nunique"),
        )
        .reset_index()
    )
    grouped["attributed_count"] = grouped["attributed_count"].astype(int)
    grouped["is_nihil_actum"] = grouped["day_status"].astype(str) == NIHIL_STATUS
    grouped["invariant_ok"] = (~grouped["is_nihil_actum"]) | (grouped["attributed_count"] == 0)
    # Structural zero for drift/span consumers: nihil days are not 1-resolution workdays.
    grouped["k_e_signal"] = grouped["k_e"].where(~grouped["is_nihil_actum"], 0).astype(int)
    return grouped


def ledger_nihil_session_violations(day_status_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ledger-level check: every nihil_actum day_status row must lack a resolved session."""
    violations: list[dict[str, Any]] = []
    for row in day_status_rows:
        if row.get("day_status") != NIHIL_STATUS:
            continue
        if row.get("resolved_session_id"):
            violations.append(
                {
                    "record_type": "ledger_violation",
                    "session_date_key": row.get("session_date_key"),
                    "enriched_date": str(row.get("enriched_date") or "")[:10],
                    "inventory_id": row.get("inventory_id"),
                    "resolved_session_id": row.get("resolved_session_id"),
                    "resolution_source": row.get("resolution_source"),
                }
            )
    return violations


def build_output_records(
    day_series: pd.DataFrame,
    ledger_violations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble meta + day rows + concordance/ledger violations."""
    nihil = day_series.loc[day_series["is_nihil_actum"]]
    concordance_violations = day_series.loc[~day_series["invariant_ok"]]
    invariant_passed = concordance_violations.empty and not ledger_violations

    meta: dict[str, Any] = {
        "record_type": "meta",
        "tier": "V",
        "n_days": int(len(day_series)),
        "n_nihil_days": int(len(nihil)),
        "n_concordance_violations": int(len(concordance_violations)),
        "n_ledger_violations": int(len(ledger_violations)),
        "n_violations": int(len(concordance_violations) + len(ledger_violations)),
        "invariant_passed": bool(invariant_passed),
        "nihil_share_of_days": round(float(len(nihil) / len(day_series)), 4) if len(day_series) else 0.0,
        "parent_sources": [CONCORDANCE_DATASET, DAY_STATUS_DATASET],
        "note": (
            "Pass/fail gate: nihil_actum days must have attributed_count == 0. "
            "Day rows are the shared K_e series for Tier D/O; k_e_signal is 0 on nihil days."
        ),
    }

    records: list[dict[str, Any]] = [meta]
    for row in day_series.itertuples(index=False):
        records.append(
            {
                "record_type": "day",
                "enriched_date": row.enriched_date,
                "k_e": int(row.k_e),
                "k_e_signal": int(row.k_e_signal),
                "attributed_count": int(row.attributed_count),
                "day_status": str(row.day_status),
                "n_distinct_day_status": int(row.n_distinct_day_status),
                "is_nihil_actum": bool(row.is_nihil_actum),
                "invariant_ok": bool(row.invariant_ok),
            }
        )

    for row in concordance_violations.itertuples(index=False):
        records.append(
            {
                "record_type": "violation",
                "source": "concordance",
                "enriched_date": row.enriched_date,
                "k_e": int(row.k_e),
                "attributed_count": int(row.attributed_count),
                "day_status": str(row.day_status),
                "resolved_note": "nihil_actum day has nonzero attributed resolutions",
            }
        )
    records.extend(ledger_violations)
    return records


def main() -> None:
    concordance = load(CONCORDANCE_DATASET)
    if not isinstance(concordance, pd.DataFrame):
        concordance = pd.DataFrame(concordance)

    day_status_rows = load(DAY_STATUS_DATASET)
    if isinstance(day_status_rows, pd.DataFrame):
        day_status_rows = day_status_rows.to_dict(orient="records")

    day_series = build_day_series(concordance)
    ledger_violations = ledger_nihil_session_violations(day_status_rows)
    records = build_output_records(day_series, ledger_violations)
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[CONCORDANCE_DATASET, DAY_STATUS_DATASET],
        description=(
            "Tier V nihil-actum invariant: per-day K_e series plus pass/fail check that "
            "nihil_actum days have zero attributed resolutions. Shared parent for Tier D "
            "K_e drift and (later) Tier O span table."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(
        f"invariant_passed={meta['invariant_passed']} "
        f"nihil_days={meta['n_nihil_days']} "
        f"violations={meta['n_violations']}"
    )


if __name__ == "__main__":
    main()

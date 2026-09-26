#!/usr/bin/env python3
"""Tier D — per-day K_e drift-comparison diagnostic (docs/METRICS.md).

Consumes the shared day series from Tier V (``metrics_nihil_actum_invariant``):
nihil days already carry ``k_e_signal == 0`` and ``invariant_ok``. Drift is
scored on ``k_e_signal`` over consecutive calendar days (``pd.Period`` freq=D).

A day is flagged when its absolute deviation from the median of its ±WINDOW
calendar neighbors exceeds ``DRIFT_ABS_THRESHOLD``. Nihil days are never
flagged as mis-attribution candidates (they are authoritative structural
zeros); if Tier V reports violations, those dates are listed as blocked and
excluded from the ranked candidate list.

Usage:
    uv run python scripts/metrics_ke_drift_diagnostic.py
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

PARENT_DATASET = "metrics_nihil_actum_invariant"
OUTPUT_DATASET = "metrics_ke_drift_diagnostic"

# Absolute |k_e_signal - neighbor_median| above this flags a candidate.
# Chosen near ~1.5× the corpus K_e std (~6.6) so ordinary day-to-day
# variation stays quiet while double-digit jumps surface.
DRIFT_ABS_THRESHOLD = 10
NEIGHBOR_WINDOW_DAYS = 3


def load_day_series(records: list[dict[str, Any]]) -> tuple[dict[str, Any], pd.DataFrame]:
    """Split V output into meta + day frame; refuse to proceed without day rows."""
    meta = next((r for r in records if r.get("record_type") == "meta"), None)
    if meta is None:
        raise ValueError(f"{PARENT_DATASET} has no meta record")
    days = [r for r in records if r.get("record_type") == "day"]
    if not days:
        raise ValueError(f"{PARENT_DATASET} has no day records for K_e drift")
    frame = pd.DataFrame(days)
    required = {"enriched_date", "k_e", "k_e_signal", "is_nihil_actum", "invariant_ok"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"day series missing columns: {sorted(missing)}")
    return meta, frame


def score_drift(
    day_series: pd.DataFrame,
    *,
    window_days: int = NEIGHBOR_WINDOW_DAYS,
    threshold: int = DRIFT_ABS_THRESHOLD,
) -> pd.DataFrame:
    """Attach neighbor medians and drift flags; nihil days stay unflagged."""
    work = day_series.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    work["period"] = pd.PeriodIndex(work["enriched_date"], freq="D")
    work = work.sort_values("period").reset_index(drop=True)

    signal = work.set_index("period")["k_e_signal"].astype(int)
    # Dense calendar index so gaps are visible as missing neighbors.
    full_index = pd.period_range(signal.index.min(), signal.index.max(), freq="D")
    signal_full = signal.reindex(full_index)

    neighbor_medians: list[float | None] = []
    neighbor_counts: list[int] = []
    abs_devs: list[float | None] = []
    for period, value in zip(work["period"], work["k_e_signal"], strict=True):
        lo = period - window_days
        hi = period + window_days
        window = signal_full.loc[lo:hi].drop(labels=[period], errors="ignore").dropna()
        if window.empty:
            neighbor_medians.append(None)
            neighbor_counts.append(0)
            abs_devs.append(None)
            continue
        median = float(window.median())
        neighbor_medians.append(median)
        neighbor_counts.append(int(len(window)))
        abs_devs.append(abs(float(value) - median))

    work["neighbor_median"] = neighbor_medians
    work["neighbor_count"] = neighbor_counts
    work["abs_dev_from_neighbors"] = abs_devs
    work["drift_flag"] = (
        (~work["is_nihil_actum"].astype(bool))
        & work["invariant_ok"].astype(bool)
        & work["abs_dev_from_neighbors"].notna()
        & (work["abs_dev_from_neighbors"] >= threshold)
        & (work["neighbor_count"] > 0)
    )
    work["drift_direction"] = "none"
    flagged = work["drift_flag"] & work["neighbor_median"].notna()
    work.loc[flagged & (work["k_e_signal"] > work["neighbor_median"]), "drift_direction"] = "spike"
    work.loc[flagged & (work["k_e_signal"] < work["neighbor_median"]), "drift_direction"] = "dip"
    return work.drop(columns=["period"])


def build_output_records(
    parent_meta: dict[str, Any],
    scored: pd.DataFrame,
    *,
    threshold: int = DRIFT_ABS_THRESHOLD,
    window_days: int = NEIGHBOR_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Meta + ranked candidate rows + blocked violation dates from Tier V."""
    blocked = scored.loc[~scored["invariant_ok"].astype(bool), "enriched_date"].astype(str).tolist()
    candidates = scored.loc[scored["drift_flag"]].sort_values(
        "abs_dev_from_neighbors", ascending=False
    )

    meta: dict[str, Any] = {
        "record_type": "meta",
        "tier": "D",
        "parent": PARENT_DATASET,
        "parent_invariant_passed": bool(parent_meta.get("invariant_passed")),
        "n_days": int(len(scored)),
        "n_nihil_days": int(scored["is_nihil_actum"].astype(bool).sum()),
        "n_blocked_by_v_violations": int(len(blocked)),
        "n_drift_candidates": int(len(candidates)),
        "drift_abs_threshold": int(threshold),
        "neighbor_window_days": int(window_days),
        "blocked_dates": sorted(blocked),
        "note": (
            "Uses k_e_signal from Tier V (0 on nihil days). "
            "Flagged days are mis-attribution candidates, not proven errors."
        ),
    }

    records: list[dict[str, Any]] = [meta]
    for rank, row in enumerate(candidates.itertuples(index=False), start=1):
        records.append(
            {
                "record_type": "candidate",
                "rank": rank,
                "enriched_date": row.enriched_date,
                "k_e": int(row.k_e),
                "k_e_signal": int(row.k_e_signal),
                "day_status": str(row.day_status),
                "neighbor_median": None
                if row.neighbor_median is None or pd.isna(row.neighbor_median)
                else round(float(row.neighbor_median), 2),
                "neighbor_count": int(row.neighbor_count),
                "abs_dev_from_neighbors": None
                if row.abs_dev_from_neighbors is None or pd.isna(row.abs_dev_from_neighbors)
                else round(float(row.abs_dev_from_neighbors), 2),
                "drift_direction": str(row.drift_direction),
            }
        )

    # Full scored series for audit / Tier O reuse of the same K_e parent.
    for row in scored.itertuples(index=False):
        records.append(
            {
                "record_type": "day",
                "enriched_date": row.enriched_date,
                "k_e": int(row.k_e),
                "k_e_signal": int(row.k_e_signal),
                "day_status": str(row.day_status),
                "is_nihil_actum": bool(row.is_nihil_actum),
                "invariant_ok": bool(row.invariant_ok),
                "neighbor_median": None
                if row.neighbor_median is None or pd.isna(row.neighbor_median)
                else round(float(row.neighbor_median), 2),
                "neighbor_count": int(row.neighbor_count),
                "abs_dev_from_neighbors": None
                if row.abs_dev_from_neighbors is None or pd.isna(row.abs_dev_from_neighbors)
                else round(float(row.abs_dev_from_neighbors), 2),
                "drift_flag": bool(row.drift_flag),
                "drift_direction": str(row.drift_direction),
            }
        )
    return records


def main() -> None:
    parent_records = load(PARENT_DATASET)
    if isinstance(parent_records, pd.DataFrame):
        parent_records = parent_records.to_dict(orient="records")

    parent_meta, day_series = load_day_series(parent_records)
    scored = score_drift(day_series)
    records = build_output_records(parent_meta, scored)
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[PARENT_DATASET],
        description=(
            "Tier D per-day K_e drift diagnostic over the Tier V day series: "
            "flags calendar days whose k_e_signal jumps implausibly vs ±3-day "
            "neighbor median. Nihil days excluded from candidates; V violations blocked."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(
        f"drift_candidates={meta['n_drift_candidates']} "
        f"blocked_by_v={meta['n_blocked_by_v_violations']} "
        f"parent_invariant_passed={meta['parent_invariant_passed']}"
    )


if __name__ == "__main__":
    main()

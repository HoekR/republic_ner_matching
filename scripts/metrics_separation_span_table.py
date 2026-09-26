#!/usr/bin/env python3
"""Tier O — consecutive-day separation span table (docs/METRICS.md; PLAN.md Global, spans).

Consumes the Tier V day series (``k_e`` / ``k_e_signal``) and counts separated
resolutions from ``resolution_concordance_1626_1630``. A resolution is
**separated** iff its start paragraph is unique on its date and its extent
(``end - start + 1``) is ≤ 3 paragraphs — the definition that reproduces the
1,961 baseline cited in PLAN.md / docs/DECISIONS.md.

A day is **solid** when ``separated_share = separated / k_e_signal >= 0.5``.
Nihil days (``k_e_signal == 0``) and dates failing the Tier V invariant are
never solid. Maximal solid runs tolerate at most ``gap`` consecutive non-solid
session-days for ``gap ∈ {0,1,2}``; calendar length is
``(end_date - start_date) + 1`` in ``Period`` days. Qualifying threshold for
the Global, spans criterion is ≥ 30 calendar days; 7/14/60 are reported as a
diagnostic curve.

Usage:
    uv run python scripts/metrics_separation_span_table.py
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

PARENT_V_DATASET = "metrics_nihil_actum_invariant"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "metrics_separation_span_table"

SOLID_SHARE_THRESHOLD = 0.5
MAX_EXTENT_PARAGRAPHS = 3
GAPS = (0, 1, 2)
# Primary Global, spans threshold, plus diagnostic curve thresholds.
LENGTH_THRESHOLDS = (7, 14, 30, 60)
PRIMARY_LENGTH_THRESHOLD = 30
# Cited PLAN.md ceiling (pigeonhole); not recomputed here — see METRICS Known gaps.
CEILING_SEPARABLE = 11_644


def load_day_series(records: list[dict[str, Any]]) -> tuple[dict[str, Any], pd.DataFrame]:
    """Split V output into meta + day frame."""
    meta = next((r for r in records if r.get("record_type") == "meta"), None)
    if meta is None:
        raise ValueError(f"{PARENT_V_DATASET} has no meta record")
    days = [r for r in records if r.get("record_type") == "day"]
    if not days:
        raise ValueError(f"{PARENT_V_DATASET} has no day records")
    frame = pd.DataFrame(days)
    required = {"enriched_date", "k_e", "k_e_signal", "is_nihil_actum", "invariant_ok"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"day series missing columns: {sorted(missing)}")
    return meta, frame


def count_separated_per_day(concordance: pd.DataFrame) -> pd.DataFrame:
    """Per-day separated resolution counts under the PLAN.md definition."""
    required = {"enriched_date", "paragraph_start_index", "paragraph_end_index"}
    missing = required - set(concordance.columns)
    if missing:
        raise ValueError(f"concordance missing columns: {sorted(missing)}")

    work = concordance.loc[:, ["enriched_date", "paragraph_start_index", "paragraph_end_index"]].copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    attributed = work["paragraph_start_index"].notna() & work["paragraph_end_index"].notna()
    sub = work.loc[attributed].copy()
    if sub.empty:
        return pd.DataFrame(columns=["enriched_date", "separated_count", "paragraph_attributed_count"])

    sub["extent"] = (sub["paragraph_end_index"] - sub["paragraph_start_index"] + 1).astype(int)
    start_counts = (
        sub.groupby(["enriched_date", "paragraph_start_index"], sort=False)
        .size()
        .rename("n_share")
        .reset_index()
    )
    sub = sub.merge(start_counts, on=["enriched_date", "paragraph_start_index"], how="left")
    sub["separated"] = (sub["n_share"] == 1) & (sub["extent"] <= MAX_EXTENT_PARAGRAPHS)

    per_day = (
        sub.groupby("enriched_date", sort=True)
        .agg(
            separated_count=("separated", "sum"),
            paragraph_attributed_count=("separated", "size"),
        )
        .reset_index()
    )
    per_day["separated_count"] = per_day["separated_count"].astype(int)
    per_day["paragraph_attributed_count"] = per_day["paragraph_attributed_count"].astype(int)
    return per_day


def attach_separation(
    day_series: pd.DataFrame,
    separated_per_day: pd.DataFrame,
    *,
    solid_threshold: float = SOLID_SHARE_THRESHOLD,
) -> pd.DataFrame:
    """Join Tier V K_e with separated counts; mark solid days."""
    work = day_series.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    merged = work.merge(separated_per_day, on="enriched_date", how="left")
    merged["separated_count"] = merged["separated_count"].fillna(0).astype(int)
    merged["paragraph_attributed_count"] = merged["paragraph_attributed_count"].fillna(0).astype(int)

    signal = merged["k_e_signal"].astype(int)
    # Nihil / structural zero: share is 0, never solid.
    share = pd.Series(0.0, index=merged.index, dtype=float)
    positive = signal > 0
    share.loc[positive] = merged.loc[positive, "separated_count"].astype(float) / signal.loc[positive]
    merged["separated_share"] = share
    merged["is_solid"] = (
        merged["invariant_ok"].astype(bool)
        & (~merged["is_nihil_actum"].astype(bool))
        & (signal > 0)
        & (share >= solid_threshold)
    )
    return merged.sort_values("enriched_date").reset_index(drop=True)


def find_solid_runs(
    day_frame: pd.DataFrame,
    *,
    max_gap: int,
) -> list[dict[str, Any]]:
    """Maximal solid runs tolerating at most ``max_gap`` consecutive non-solid session-days.

    Walks the ordered Tier V session-day series (not a dense calendar). Calendar
    length uses ``Period`` day ordinals between the first and last date of the run.
    Trailing non-solid days are trimmed so every run starts and ends solid.
    """
    if max_gap < 0:
        raise ValueError("max_gap must be >= 0")
    if day_frame.empty:
        return []

    work = day_frame.copy()
    work["period"] = pd.PeriodIndex(work["enriched_date"].astype(str).str.slice(0, 10), freq="D")
    work = work.sort_values("period").reset_index(drop=True)

    runs: list[dict[str, Any]] = []
    run_start_idx: int | None = None
    last_solid_idx: int | None = None
    gap_streak = 0

    def close_run() -> None:
        nonlocal run_start_idx, last_solid_idx, gap_streak
        if run_start_idx is None or last_solid_idx is None:
            run_start_idx = None
            last_solid_idx = None
            gap_streak = 0
            return
        slice_ = work.iloc[run_start_idx : last_solid_idx + 1]
        start_period = slice_.iloc[0]["period"]
        end_period = slice_.iloc[-1]["period"]
        calendar_days = int(end_period.ordinal - start_period.ordinal) + 1
        n_session_days = int(len(slice_))
        n_solid = int(slice_["is_solid"].astype(bool).sum())
        n_non_solid = n_session_days - n_solid
        runs.append(
            {
                "start_date": str(slice_.iloc[0]["enriched_date"])[:10],
                "end_date": str(slice_.iloc[-1]["enriched_date"])[:10],
                "calendar_days": calendar_days,
                "n_session_days": n_session_days,
                "n_solid_days": n_solid,
                "n_non_solid_days": n_non_solid,
                "separated_in_run": int(slice_["separated_count"].sum()),
                "k_e_signal_in_run": int(slice_["k_e_signal"].sum()),
            }
        )
        run_start_idx = None
        last_solid_idx = None
        gap_streak = 0

    for idx, row in enumerate(work.itertuples(index=False)):
        solid = bool(row.is_solid)
        if solid:
            if run_start_idx is None:
                run_start_idx = idx
            last_solid_idx = idx
            gap_streak = 0
            continue
        # Non-solid session-day.
        if run_start_idx is None:
            continue
        gap_streak += 1
        if gap_streak > max_gap:
            close_run()

    close_run()
    return runs


def summarize_runs(
    runs: list[dict[str, Any]],
    *,
    max_gap: int,
    thresholds: tuple[int, ...] = LENGTH_THRESHOLDS,
) -> dict[str, Any]:
    """Per-gap summary: qualifying counts at each length threshold."""
    by_threshold: dict[str, dict[str, int]] = {}
    for threshold in thresholds:
        qualifying = [r for r in runs if int(r["calendar_days"]) >= threshold]
        by_threshold[str(threshold)] = {
            "n_spans": int(len(qualifying)),
            "days_covered": int(sum(int(r["calendar_days"]) for r in qualifying)),
            "n_session_days_covered": int(sum(int(r["n_session_days"]) for r in qualifying)),
        }
    primary = by_threshold[str(PRIMARY_LENGTH_THRESHOLD)]
    return {
        "gap": int(max_gap),
        "n_runs_any_length": int(len(runs)),
        "longest_calendar_days": int(max((r["calendar_days"] for r in runs), default=0)),
        "by_min_length": by_threshold,
        "global_spans_n_spans": primary["n_spans"],
        "global_spans_days_covered": primary["days_covered"],
        "global_spans_criterion_met": bool(
            primary["n_spans"] >= 6 and primary["days_covered"] >= 180
        ),
    }


def build_output_records(
    parent_meta: dict[str, Any],
    day_frame: pd.DataFrame,
    *,
    n_all_resolutions: int,
    n_htr_reachable: int,
    gaps: tuple[int, ...] = GAPS,
    thresholds: tuple[int, ...] = LENGTH_THRESHOLDS,
) -> list[dict[str, Any]]:
    """Meta + gap summaries + qualifying span rows + per-day solid flags."""
    blocked = (
        day_frame.loc[~day_frame["invariant_ok"].astype(bool), "enriched_date"]
        .astype(str)
        .tolist()
    )
    n_separated = int(day_frame["separated_count"].sum())
    n_solid = int(day_frame["is_solid"].astype(bool).sum())

    gap_summaries: list[dict[str, Any]] = []
    span_rows: list[dict[str, Any]] = []
    for gap in gaps:
        runs = find_solid_runs(day_frame, max_gap=gap)
        summary = summarize_runs(runs, max_gap=gap, thresholds=thresholds)
        gap_summaries.append(summary)
        for rank, run in enumerate(
            sorted(runs, key=lambda r: (-int(r["calendar_days"]), r["start_date"])),
            start=1,
        ):
            if int(run["calendar_days"]) < min(thresholds):
                continue
            span_rows.append(
                {
                    "record_type": "span",
                    "gap": int(gap),
                    "rank_by_length": rank,
                    **run,
                    "qualifies_at_30": bool(int(run["calendar_days"]) >= PRIMARY_LENGTH_THRESHOLD),
                }
            )

    meta: dict[str, Any] = {
        "record_type": "meta",
        "tier": "O",
        "parent": PARENT_V_DATASET,
        "parent_invariant_passed": bool(parent_meta.get("invariant_passed")),
        "solid_share_threshold": float(SOLID_SHARE_THRESHOLD),
        "max_extent_paragraphs": int(MAX_EXTENT_PARAGRAPHS),
        "n_days": int(len(day_frame)),
        "n_solid_days": n_solid,
        "n_blocked_by_v_violations": int(len(blocked)),
        "blocked_dates": sorted(blocked),
        "n_separated": n_separated,
        "n_all_resolutions": int(n_all_resolutions),
        "n_htr_reachable": int(n_htr_reachable),
        "ceiling_separable": int(CEILING_SEPARABLE),
        "separated_share_of_all": round(n_separated / n_all_resolutions, 4) if n_all_resolutions else 0.0,
        "separated_share_of_htr_reachable": (
            round(n_separated / n_htr_reachable, 4) if n_htr_reachable else 0.0
        ),
        "separated_share_of_ceiling": (
            round(n_separated / CEILING_SEPARABLE, 4) if CEILING_SEPARABLE else 0.0
        ),
        "gap_summaries": gap_summaries,
        "note": (
            "Solid day: separated_share >= 0.5 using k_e_signal from Tier V. "
            "Global, spans criterion: >=6 spans of >=30 calendar days totalling >=180 days."
        ),
    }

    records: list[dict[str, Any]] = [meta]
    for summary in gap_summaries:
        records.append({"record_type": "gap_summary", **summary})
    records.extend(span_rows)

    for row in day_frame.itertuples(index=False):
        records.append(
            {
                "record_type": "day",
                "enriched_date": row.enriched_date,
                "k_e": int(row.k_e),
                "k_e_signal": int(row.k_e_signal),
                "day_status": str(row.day_status) if hasattr(row, "day_status") else None,
                "is_nihil_actum": bool(row.is_nihil_actum),
                "invariant_ok": bool(row.invariant_ok),
                "separated_count": int(row.separated_count),
                "paragraph_attributed_count": int(row.paragraph_attributed_count),
                "separated_share": round(float(row.separated_share), 4),
                "is_solid": bool(row.is_solid),
            }
        )
    return records


def main() -> None:
    parent_records = load(PARENT_V_DATASET)
    if isinstance(parent_records, pd.DataFrame):
        parent_records = parent_records.to_dict(orient="records")

    concordance = load(CONCORDANCE_DATASET)
    if not isinstance(concordance, pd.DataFrame):
        concordance = pd.DataFrame(concordance)

    parent_meta, day_series = load_day_series(parent_records)
    separated = count_separated_per_day(concordance)
    day_frame = attach_separation(day_series, separated)

    n_all = int(len(concordance))
    day_status = concordance["day_status"].astype(str) if "day_status" in concordance.columns else None
    if day_status is not None:
        n_htr = int((day_status != "missing_htr").sum())
    else:
        n_htr = int(concordance["resolved_session_id"].notna().sum()) if "resolved_session_id" in concordance.columns else n_all

    records = build_output_records(
        parent_meta,
        day_frame,
        n_all_resolutions=n_all,
        n_htr_reachable=n_htr,
    )
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[PARENT_V_DATASET, CONCORDANCE_DATASET],
        description=(
            "Tier O consecutive-day separation span table: per-day separated_share on the "
            "Tier V k_e_signal series; solid-day runs at gap in {0,1,2}; qualifying spans "
            "at 7/14/30/60 calendar-day thresholds (Global, spans uses >=30)."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(
        f"separated={meta['n_separated']} "
        f"({meta['separated_share_of_ceiling']:.1%} of ceiling) "
        f"solid_days={meta['n_solid_days']}/{meta['n_days']}"
    )
    for summary in meta["gap_summaries"]:
        print(
            f"  gap={summary['gap']}: "
            f"spans@30={summary['global_spans_n_spans']} "
            f"days_covered={summary['global_spans_days_covered']} "
            f"criterion_met={summary['global_spans_criterion_met']} "
            f"longest={summary['longest_calendar_days']}"
        )


if __name__ == "__main__":
    main()

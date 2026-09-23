#!/usr/bin/env python3
"""Tier D — windowed K_e-vs-K_f shift-signature diagnostic (docs/METRICS.md).

User-proposed diagnostic: does session/date drift (a resolution attributed to the
wrong calendar day) explain the long `weak_separation`-dominated stretches that
metrics_span_gap_map.py's breaking gaps flag, as opposed to a genuine in-day
placement-quality gap? Corpus-wide K_e-vs-K_f comparison over every day would be
noise; this is scoped to the specific windows metrics_span_gap_map already ranked
as the longest solid-day breaks.

For each flagged window (a breaking gap's ``[left_solid_date, right_solid_date]``,
which by construction starts and ends on a solid day), compares per-day
``k_e`` (enriched resolution count) against ``paragraph_count`` (the HTR-side
axis capacity for that date, the K_f-role proxy already used by
metrics_weak_separation_headroom_diagnostic.py). A genuine date-drift signature
looks like alternating over-/under-attribution between adjacent days (one day
short on editorial demand, its neighbor short on HTR capacity, roughly
cancelling) -- captured here as lag-1 autocorrelation of the residual and a
count of sign-flipping adjacent pairs. A uniform shortfall (residual
persistently positive, no compensating neighbor) is evidence of a real
capacity/placement gap instead, not a mapping error.

Usage:
    uv run python scripts/metrics_ke_kf_window_drift_diagnostic.py
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

GAP_DATASET = "metrics_span_gap_map"
PREDICTIONS_DATASET = "s4_corpus_paragraph_predictions"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "metrics_ke_kf_window_drift_diagnostic"

MIN_GAP_SESSION_DAYS = 8
MIN_RESIDUAL_MAGNITUDE = 2
SHIFT_AUTOCORR_THRESHOLD = -0.3
SHIFT_COMPLEMENTARY_SHARE_THRESHOLD = 0.4


def load_predictions_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    """date -> k_e / paragraph_count / status / reason, one row per corpus day."""
    if isinstance(records, pd.DataFrame):
        records = records.to_dict(orient="records")
    frame = pd.DataFrame(
        [
            {
                "date": str(r.get("date") or "")[:10],
                "k_e": int(r.get("k_e") or 0),
                "paragraph_count": int(r.get("paragraph_count") or 0),
                "status": r.get("status"),
                "reason": r.get("reason"),
            }
            for r in records
        ]
    )
    required = {"date", "k_e", "paragraph_count"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"predictions frame missing columns: {sorted(missing)}")
    return frame.sort_values("date").reset_index(drop=True)


def select_windows(
    gap_records: list[dict[str, Any]],
    *,
    min_gap_session_days: int = MIN_GAP_SESSION_DAYS,
) -> list[dict[str, Any]]:
    """Breaking gaps at or above the session-day threshold, dominated by weak_separation."""
    if isinstance(gap_records, pd.DataFrame):
        gap_records = gap_records.to_dict(orient="records")
    gaps = [r for r in gap_records if r.get("record_type") == "gap"]
    return [
        g
        for g in gaps
        if int(g.get("n_nonsolid_session_days") or 0) >= min_gap_session_days
        and str(g.get("dominant_class")) != "adjacent_solid"
    ]


def session_collision_dates(concordance_records: list[dict[str, Any]]) -> set[str]:
    """Enriched dates whose ``resolved_session_id`` is independently claimed by another date.

    ``resolve_row`` (scripts/s4_day_status_resolution.py) picks each ledger row's
    (i.e. each enriched date's) best-matching session independently, with no
    constraint that a session can be claimed by only one date -- two different
    calendar dates can and do resolve to the identical session.
    """
    if isinstance(concordance_records, pd.DataFrame):
        concordance_records = concordance_records.to_dict(orient="records")
    frame = pd.DataFrame(
        [
            {
                "enriched_date": str(r.get("enriched_date") or "")[:10],
                "day_status": r.get("day_status"),
                "resolved_session_id": r.get("resolved_session_id"),
            }
            for r in concordance_records
        ]
    )
    resolved = frame.loc[
        (frame["day_status"] == "resolved_auto") & frame["resolved_session_id"].notna(),
        ["enriched_date", "resolved_session_id"],
    ].drop_duplicates()
    session_date_counts = resolved.groupby("resolved_session_id")["enriched_date"].nunique()
    collided_sessions = set(session_date_counts[session_date_counts > 1].index)
    return set(resolved.loc[resolved["resolved_session_id"].isin(collided_sessions), "enriched_date"])


def collision_weak_separation_crosstab(
    day_frame: pd.DataFrame,
    *,
    resolved_dates: set[str],
    collision_dates: set[str],
) -> dict[str, Any]:
    """Corpus-wide check: are session-collision dates disproportionately weak_separation?

    Scoped to ``resolved_dates`` (Tier O days with a resolved_auto session) since
    a collision is only defined among those. Reports the weak_separation rate for
    collision vs. non-collision dates, and what share of ALL weak_separation days
    (not just the flagged windows) are collision-involved -- the corpus-wide,
    population-level version of the per-window shift-signature check above.
    """
    work = day_frame.loc[day_frame["enriched_date"].isin(resolved_dates)].copy()
    work["is_collision"] = work["enriched_date"].isin(collision_dates)
    work["is_weak_separation"] = work["nonsolid_class"] == "weak_separation"

    n_collision = int(work["is_collision"].sum())
    n_noncollision = int((~work["is_collision"]).sum())
    collision_weak_rate = (
        float(work.loc[work["is_collision"], "is_weak_separation"].mean()) if n_collision else 0.0
    )
    noncollision_weak_rate = (
        float(work.loc[~work["is_collision"], "is_weak_separation"].mean()) if n_noncollision else 0.0
    )
    n_weak_separation_total = int(work["is_weak_separation"].sum())
    n_weak_separation_collision = int((work["is_collision"] & work["is_weak_separation"]).sum())
    weak_separation_collision_share = (
        (n_weak_separation_collision / n_weak_separation_total) if n_weak_separation_total else 0.0
    )
    return {
        "record_type": "corpus_collision_crosstab",
        "n_resolved_auto_days": int(len(work)),
        "n_collision_days": n_collision,
        "n_noncollision_days": n_noncollision,
        "collision_weak_separation_rate": round(collision_weak_rate, 4),
        "noncollision_weak_separation_rate": round(noncollision_weak_rate, 4),
        "n_weak_separation_days_total": n_weak_separation_total,
        "n_weak_separation_days_collision_involved": n_weak_separation_collision,
        "weak_separation_days_collision_share": round(weak_separation_collision_share, 4),
        "note": (
            "collision_weak_separation_rate vs. noncollision_weak_separation_rate is the "
            "effect-size check (a collision date should be far more likely to be "
            "weak_separation if the mechanism is real). weak_separation_days_collision_share "
            "is the population-level answer to 'how much of the weak_separation days "
            "blocking spans does this one mapping bug explain' -- corpus-wide, not just "
            "the top-ranked windows above."
        ),
    }


def residual_series(window_frame: pd.DataFrame) -> pd.Series:
    """k_e - paragraph_count per day; positive means editorial demand exceeds HTR capacity."""
    return (window_frame["k_e"] - window_frame["paragraph_count"]).astype(int)


def lag1_autocorrelation(residuals: pd.Series) -> float | None:
    """Lag-1 autocorrelation of the residual series; None when too short to be meaningful."""
    if len(residuals) < 4:
        return None
    value = residuals.astype(float).autocorr(lag=1)
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def complementary_adjacent_pairs(
    residuals: pd.Series,
    *,
    min_magnitude: int = MIN_RESIDUAL_MAGNITUDE,
) -> tuple[int, int]:
    """(n_complementary, n_adjacent) -- sign-flipping pairs vs. all adjacent pairs.

    A pair is complementary when consecutive residuals have opposite sign and
    both exceed ``min_magnitude`` -- one day short on editorial demand, its
    neighbor short on HTR capacity, the classic footprint of a day-boundary
    misattribution rather than an independent, unrelated shortfall on each day.
    """
    values = residuals.tolist()
    n_adjacent = max(0, len(values) - 1)
    n_complementary = 0
    for a, b in zip(values, values[1:], strict=False):
        if abs(a) >= min_magnitude and abs(b) >= min_magnitude and (a > 0) != (b > 0):
            n_complementary += 1
    return n_complementary, n_adjacent


def classify_shift_signature(
    *,
    autocorr: float | None,
    complementary_share: float | None,
    mean_residual: float,
) -> str:
    """One of shift_candidate / uniform_shortfall / inconclusive."""
    is_shift = (autocorr is not None and autocorr <= SHIFT_AUTOCORR_THRESHOLD) or (
        complementary_share is not None and complementary_share >= SHIFT_COMPLEMENTARY_SHARE_THRESHOLD
    )
    if is_shift:
        return "shift_candidate"
    if autocorr is None and complementary_share is None:
        return "inconclusive"
    if mean_residual > 0:
        return "uniform_shortfall"
    return "inconclusive"


def summarize_window(
    gap: dict[str, Any],
    window_frame: pd.DataFrame,
) -> dict[str, Any]:
    residuals = residual_series(window_frame)
    autocorr = lag1_autocorrelation(residuals)
    n_complementary, n_adjacent = complementary_adjacent_pairs(residuals)
    complementary_share = (n_complementary / n_adjacent) if n_adjacent else None
    mean_residual = round(float(residuals.mean()), 4) if len(residuals) else 0.0
    signature = classify_shift_signature(
        autocorr=autocorr,
        complementary_share=complementary_share,
        mean_residual=mean_residual,
    )
    return {
        "record_type": "window",
        "left_solid_date": gap["left_solid_date"],
        "right_solid_date": gap["right_solid_date"],
        "n_nonsolid_session_days": int(gap["n_nonsolid_session_days"]),
        "dominant_class": gap.get("dominant_class"),
        "n_window_days": int(len(window_frame)),
        "mean_residual": mean_residual,
        "lag1_autocorr": autocorr,
        "n_complementary_adjacent_pairs": n_complementary,
        "n_adjacent_pairs": n_adjacent,
        "complementary_share": round(complementary_share, 4) if complementary_share is not None else None,
        "shift_signature": signature,
        "days": [
            {
                "date": row.date,
                "k_e": int(row.k_e),
                "paragraph_count": int(row.paragraph_count),
                "residual": int(row.k_e - row.paragraph_count),
                "status": row.status,
                "reason": row.reason,
            }
            for row in window_frame.itertuples(index=False)
        ],
    }


def build_output_records(
    windows: list[dict[str, Any]],
    predictions: pd.DataFrame,
    *,
    day_frame: pd.DataFrame,
    resolved_dates: set[str],
    collision_dates: set[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for gap in windows:
        window_frame = predictions.loc[
            (predictions["date"] >= gap["left_solid_date"]) & (predictions["date"] <= gap["right_solid_date"])
        ].sort_values("date")
        summary = summarize_window(gap, window_frame)
        summaries.append(summary)

    signature_counts = pd.Series([s["shift_signature"] for s in summaries]).value_counts().to_dict()
    crosstab = collision_weak_separation_crosstab(
        day_frame, resolved_dates=resolved_dates, collision_dates=collision_dates
    )
    meta = {
        "record_type": "meta",
        "tier": "D",
        "parent": GAP_DATASET,
        "n_windows_inspected": len(summaries),
        "min_gap_session_days": MIN_GAP_SESSION_DAYS,
        "min_residual_magnitude": MIN_RESIDUAL_MAGNITUDE,
        "shift_autocorr_threshold": SHIFT_AUTOCORR_THRESHOLD,
        "shift_complementary_share_threshold": SHIFT_COMPLEMENTARY_SHARE_THRESHOLD,
        "shift_signature_counts": {str(k): int(v) for k, v in signature_counts.items()},
        "n_session_collision_dates_corpus": len(collision_dates),
        "weak_separation_days_collision_share": crosstab["weak_separation_days_collision_share"],
        "note": (
            "Scoped to metrics_span_gap_map's longest breaking gaps (>= "
            f"{MIN_GAP_SESSION_DAYS} non-solid session-days), not corpus-wide. "
            "shift_candidate windows show an alternating over-/under-attribution "
            "pattern (negative lag-1 residual autocorrelation and/or a high share "
            "of sign-flipping adjacent day pairs) consistent with day-boundary "
            "misattribution -- worth checking against the session-date mapping "
            "queue. uniform_shortfall windows show persistently positive residual "
            "with no compensating neighbor -- evidence of a real capacity/"
            "placement gap, not a mapping error. K_f is proxied by paragraph_count "
            "(HTR axis capacity), the same proxy metrics_weak_separation_headroom_"
            "diagnostic.py already uses -- not a literal resolutions_flat count. "
            "See the corpus_collision_crosstab record for the population-level "
            "(not just top-window) version of the session-collision check."
        ),
    }
    records.append(meta)
    records.append(crosstab)
    records.extend(summaries)
    return records


def load_gap_day_frame(gap_records: list[dict[str, Any]]) -> pd.DataFrame:
    """Tier O per-day rows (nonsolid_class, day_status) from metrics_span_gap_map's output."""
    if isinstance(gap_records, pd.DataFrame):
        gap_records = gap_records.to_dict(orient="records")
    day_frame = pd.DataFrame([r for r in gap_records if r.get("record_type") == "day"])
    day_frame["enriched_date"] = day_frame["enriched_date"].astype(str).str.slice(0, 10)
    return day_frame


def main() -> None:
    gap_records = load(GAP_DATASET)
    predictions_records = load(PREDICTIONS_DATASET)
    concordance_records = load(CONCORDANCE_DATASET)
    predictions = load_predictions_frame(predictions_records)
    windows = select_windows(gap_records)
    day_frame = load_gap_day_frame(gap_records)

    collision_dates = session_collision_dates(concordance_records)
    resolved_dates = set(day_frame.loc[day_frame["day_status"] == "resolved_auto", "enriched_date"])

    records = build_output_records(
        windows,
        predictions,
        day_frame=day_frame,
        resolved_dates=resolved_dates,
        collision_dates=collision_dates,
    )
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[GAP_DATASET, PREDICTIONS_DATASET, CONCORDANCE_DATASET],
        description=(
            "Tier D windowed K_e-vs-paragraph_count shift-signature diagnostic, scoped to "
            "metrics_span_gap_map's longest weak_separation-dominated breaking gaps."
        ),
        script=__file__,
    )

    crosstab = next(r for r in records if r["record_type"] == "corpus_collision_crosstab")
    print(f"Wrote {len(records)} records to {path}")
    print(f"n_windows_inspected={meta['n_windows_inspected']}")
    print(f"shift_signature_counts={meta['shift_signature_counts']}")
    print(
        f"corpus_collision_crosstab: n_collision_days={crosstab['n_collision_days']} "
        f"collision_weak_sep_rate={crosstab['collision_weak_separation_rate']} "
        f"noncollision_weak_sep_rate={crosstab['noncollision_weak_separation_rate']} "
        f"weak_separation_days_collision_share={crosstab['weak_separation_days_collision_share']} "
        f"({crosstab['n_weak_separation_days_collision_involved']}/{crosstab['n_weak_separation_days_total']})"
    )
    for window in (r for r in records if r["record_type"] == "window"):
        print(
            f"  {window['left_solid_date']}..{window['right_solid_date']} "
            f"(nonsolid={window['n_nonsolid_session_days']}, dominant={window['dominant_class']}): "
            f"signature={window['shift_signature']} autocorr={window['lag1_autocorr']} "
            f"complementary={window['n_complementary_adjacent_pairs']}/{window['n_adjacent_pairs']} "
            f"mean_residual={window['mean_residual']}"
        )


if __name__ == "__main__":
    main()

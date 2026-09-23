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
            "diagnostic.py already uses -- not a literal resolutions_flat count."
        ),
    }
    records.append(meta)
    records.extend(summaries)
    return records


def main() -> None:
    gap_records = load(GAP_DATASET)
    predictions_records = load(PREDICTIONS_DATASET)
    predictions = load_predictions_frame(predictions_records)
    windows = select_windows(gap_records)
    records = build_output_records(windows, predictions)
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[GAP_DATASET, PREDICTIONS_DATASET],
        description=(
            "Tier D windowed K_e-vs-paragraph_count shift-signature diagnostic, scoped to "
            "metrics_span_gap_map's longest weak_separation-dominated breaking gaps."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(f"n_windows_inspected={meta['n_windows_inspected']}")
    print(f"shift_signature_counts={meta['shift_signature_counts']}")
    for window in records[1:]:
        print(
            f"  {window['left_solid_date']}..{window['right_solid_date']} "
            f"(nonsolid={window['n_nonsolid_session_days']}, dominant={window['dominant_class']}): "
            f"signature={window['shift_signature']} autocorr={window['lag1_autocorr']} "
            f"complementary={window['n_complementary_adjacent_pairs']}/{window['n_adjacent_pairs']} "
            f"mean_residual={window['mean_residual']}"
        )


if __name__ == "__main__":
    main()

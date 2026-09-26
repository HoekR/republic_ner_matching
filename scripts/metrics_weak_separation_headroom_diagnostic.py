#!/usr/bin/env python3
"""Tier O — weak_separation headroom diagnostic: axis ceiling vs. placement quality.

``metrics_span_gap_map`` shows bridging ``weak_separation`` days alone cannot reach a
30-calendar-day Global span (longest 12d) — the lever is *converting* weak_separation
days to solid (``separated_share >= 0.5``), not merely bridging them
(``docs/DECISIONS.md`` 2026-09-21/23). Before scoping a placement-quality fix (e.g. S6e
weight fitting), this asks a cheaper question first: for each weak_separation day, is
0.5 even *reachable* given how coarse its paragraph axis is?

A resolution is "separated" only if its start paragraph is unique on that date
(``metrics_separation_span_table``). With ``paragraph_count`` (P) distinct axis
positions and ``k_e_signal`` (K) resolutions needing placement, at most ``min(P, K)``
resolutions can ever get a unique start — regardless of algorithm, and this ignores the
extent<=3 constraint, which can only lower the true ceiling further. So
``structural_ceiling_share = min(1.0, P / K)`` is a strict upper bound on
``separated_share``.

Two mutually exclusive buckets per weak_separation day:

* ``structurally_capped`` — ceiling < 0.5: no placement algorithm can make this day
  solid; only a finer axis (the blocked line-level track) could.
* ``headroom_available`` — ceiling >= 0.5: solid is reachable in principle, so today's
  separated_share below 0.5 reflects placement quality, not axis coarseness — this is
  the population a placement-quality fix (S6e weight fitting or similar) could move.

Usage:
    uv run python scripts/metrics_weak_separation_headroom_diagnostic.py
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

SPAN_GAP_DATASET = "metrics_span_gap_map"
PRED_DATASET = "s4_corpus_paragraph_predictions"
OUTPUT_DATASET = "metrics_weak_separation_headroom_diagnostic"

SOLID_SHARE_THRESHOLD = 0.5
HEADROOM_CLASSES = ("structurally_capped", "headroom_available")


def structural_ceiling_share(k_e_signal: int, paragraph_count: int) -> float:
    """Strict upper bound on separated_share given axis coarseness alone."""
    if k_e_signal <= 0:
        return 0.0
    if paragraph_count <= 0:
        return 0.0
    return min(1.0, paragraph_count / k_e_signal)


def classify_headroom(ceiling: float, *, threshold: float = SOLID_SHARE_THRESHOLD) -> str:
    """Mutually exclusive bucket: can this day structurally reach solid at all?"""
    return "structurally_capped" if ceiling < threshold else "headroom_available"


def weak_separation_day_record(
    span_day: dict[str, Any],
    pred_by_date: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Per-day record for one ``weak_separation`` day, or None if not that class."""
    if span_day.get("nonsolid_class") != "weak_separation":
        return None
    date = str(span_day.get("enriched_date") or "")[:10]
    k_e_signal = int(span_day.get("k_e_signal") or 0)
    separated_share = float(span_day.get("separated_share") or 0.0)

    pred = pred_by_date.get(date)
    paragraph_count = int(pred.get("paragraph_count") or 0) if pred is not None else 0
    ceiling = structural_ceiling_share(k_e_signal, paragraph_count)

    return {
        "record_type": "day",
        "enriched_date": date,
        "k_e_signal": k_e_signal,
        "paragraph_count": paragraph_count,
        "separated_share": round(separated_share, 4),
        "structural_ceiling_share": round(ceiling, 4),
        "headroom": round(max(0.0, ceiling - separated_share), 4),
        "headroom_class": classify_headroom(ceiling),
        "has_prediction": pred is not None,
        "day_status": span_day.get("day_status"),
    }


def summarize(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Meta record with bucket shares and a recommended next focus."""
    n = len(days)
    n_capped = sum(1 for d in days if d["headroom_class"] == "structurally_capped")
    n_headroom = n - n_capped
    capped_share = (n_capped / n) if n else 0.0
    headroom_days = [d for d in days if d["headroom_class"] == "headroom_available"]
    mean_headroom = (
        sum(d["headroom"] for d in headroom_days) / len(headroom_days) if headroom_days else 0.0
    )
    n_missing_pred = sum(1 for d in days if not d.get("has_prediction", True))

    if n == 0:
        recommended = "no_weak_separation_days"
    elif capped_share >= 0.5:
        recommended = "finer_axis_needed_most_days_structurally_capped"
    else:
        recommended = "placement_quality_fix_viable_headroom_dominates"

    return {
        "record_type": "meta",
        "n_weak_separation_days": n,
        "solid_share_threshold": SOLID_SHARE_THRESHOLD,
        "n_structurally_capped": n_capped,
        "structurally_capped_share": round(capped_share, 4),
        "n_headroom_available": n_headroom,
        "headroom_available_share": round(1.0 - capped_share, 4) if n else 0.0,
        "mean_headroom_on_headroom_days": round(mean_headroom, 4),
        "n_missing_prediction_join": n_missing_pred,
        "recommended_focus": recommended,
        "note": (
            "structural_ceiling_share = min(1, paragraph_count / k_e_signal) is a strict "
            "upper bound on separated_share (ignores the extent<=3 constraint, which can "
            "only lower the true ceiling). structurally_capped days need a finer axis "
            "(blocked line-level track) to ever reach solid; headroom_available days are "
            "where a placement-quality fix (e.g. S6e weight fitting) has real room to move "
            "separated_share without new axis granularity."
        ),
    }


def build_records(
    span_gap_records: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble meta + per-day weak_separation headroom records."""
    pred_by_date = {str(row.get("date") or "")[:10]: row for row in predictions}

    days: list[dict[str, Any]] = []
    for row in span_gap_records:
        if row.get("record_type") != "day":
            continue
        day = weak_separation_day_record(row, pred_by_date)
        if day is not None:
            days.append(day)
    days.sort(key=lambda d: (d["headroom_class"], -d["headroom"], d["enriched_date"]))

    meta = summarize(days)
    return [meta, *days]


def main() -> None:
    span_gap = load(SPAN_GAP_DATASET)
    if isinstance(span_gap, pd.DataFrame):
        span_gap = span_gap.to_dict(orient="records")

    predictions = load(PRED_DATASET)
    if isinstance(predictions, pd.DataFrame):
        predictions = predictions.to_dict(orient="records")

    records = build_records(span_gap, predictions)
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[SPAN_GAP_DATASET, PRED_DATASET],
        description=(
            "Tier O weak_separation headroom diagnostic: per-day structural ceiling on "
            "separated_share (min(1, paragraph_count/k_e_signal)) for weak_separation "
            "days, splitting structurally_capped (no algorithm can reach solid) from "
            "headroom_available (a placement-quality fix could)."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(
        f"weak_separation_days={meta['n_weak_separation_days']} "
        f"structurally_capped={meta['n_structurally_capped']} "
        f"({meta['structurally_capped_share']:.1%}) "
        f"headroom_available={meta['n_headroom_available']} "
        f"({meta['headroom_available_share']:.1%})"
    )
    print(f"mean_headroom_on_headroom_days={meta['mean_headroom_on_headroom_days']}")
    print(f"n_missing_prediction_join={meta['n_missing_prediction_join']}")
    print(f"recommended_focus={meta['recommended_focus']}")


if __name__ == "__main__":
    main()

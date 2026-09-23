#!/usr/bin/env python3
"""S6c severe-collapse autopsy: why ≥7 resolutions share one paragraph start.

Reopened 2026-09-22 after ``metrics_span_gap_map`` set
``severe_collapse_implicated=True`` (43/171 breaking gaps contain a collapse
day). This diagnostic does **not** claim to unlock Global spans — bridging all
``weak_separation`` still caps longest solid run at 12 calendar days
(``docs/DECISIONS.md`` 2026-09-22). It stratifies the collapse days themselves
so the next local lever is chosen against evidence rather than habit.

Cause classes (mutually exclusive, from prediction fields only — no NW re-run):

* ``pigeonhole_forced`` — ``ceil(k_e / paragraph_count) >= 7``: even an optimal
  assignment must severe-collapse; finer axis (blocked line-level track) or
  accept.
* ``axis_requires_repeats`` — ``paragraph_count < k_e`` but the pigeonhole floor
  is still ``< 7``: some repeats are inevitable, but the observed pile-up is
  worse than the floor.
* ``room_on_axis`` — ``paragraph_count >= k_e``: a strictly increasing assignment
  exists in principle; S6c's anchor-backbone gaps (or soft evidence) chose
  repeats anyway.

Also joins Tier O span-gap day flags so we can see how many collapse days sit
inside ``weak_separation`` interrupters vs elsewhere.

Usage:
    uv run python scripts/s6c_severe_collapse_autopsy.py
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.metrics_span_gap_map import SEVERE_COLLAPSE_MIN, severe_collapse_dates

PRED_DATASET = "s4_corpus_paragraph_predictions"
SPAN_GAP_DATASET = "metrics_span_gap_map"
OUTPUT_DATASET = "s6c_severe_collapse_autopsy"

CAUSE_CLASSES = (
    "pigeonhole_forced",
    "axis_requires_repeats",
    "room_on_axis",
)


def resolution_starts(row: dict[str, Any]) -> list[int]:
    """``[0] + cut_indices`` truncated to ``k_e`` (same reconstruction as span-gap map)."""
    k_e = int(row.get("k_e") or 0)
    cuts = [
        int(b["paragraph_stream_index"])
        for b in (row.get("boundaries") or [])
        if b.get("paragraph_stream_index") is not None
    ]
    return ([0] + cuts)[:k_e]


def pigeonhole_floor(k_e: int, paragraph_count: int) -> int:
    """Minimum achievable max-load under non-decreasing assignment onto ``paragraph_count`` paras."""
    if paragraph_count <= 0:
        return int(k_e)
    return int(math.ceil(k_e / paragraph_count))


def classify_cause(*, k_e: int, paragraph_count: int) -> str:
    """Mutually exclusive structural cause (independent of observed max-load)."""
    if paragraph_count <= 0:
        return "pigeonhole_forced"
    floor = pigeonhole_floor(k_e, paragraph_count)
    if floor >= SEVERE_COLLAPSE_MIN:
        return "pigeonhole_forced"
    if paragraph_count < k_e:
        return "axis_requires_repeats"
    return "room_on_axis"


def collapse_day_record(row: dict[str, Any]) -> dict[str, Any] | None:
    """Per-day autopsy fields for one predicted row, or None if not severe-collapse."""
    if row.get("status") != "predicted":
        return None
    k_e = int(row.get("k_e") or 0)
    if k_e < SEVERE_COLLAPSE_MIN:
        return None
    starts = resolution_starts(row)
    if not starts:
        return None
    counts = Counter(starts)
    max_on = int(max(counts.values()))
    if max_on < SEVERE_COLLAPSE_MIN:
        return None
    paragraph_count = int(row.get("paragraph_count") or 0)
    floor = pigeonhole_floor(k_e, paragraph_count)
    date = str(row.get("date") or "")[:10]
    return {
        "record_type": "day",
        "enriched_date": date,
        "k_e": k_e,
        "paragraph_count": paragraph_count,
        "max_on_paragraph": max_on,
        "n_distinct_start_paragraphs": int(len(counts)),
        "pigeonhole_floor": floor,
        "excess_over_floor": int(max_on - floor),
        "cause_class": classify_cause(k_e=k_e, paragraph_count=paragraph_count),
        "axis_shorter_than_k_e": bool(paragraph_count < k_e),
    }


def load_span_gap_day_index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map enriched_date -> span-gap day flags."""
    out: dict[str, dict[str, Any]] = {}
    for row in records:
        if row.get("record_type") != "day":
            continue
        date = str(row.get("enriched_date") or "")[:10]
        if not date:
            continue
        out[date] = {
            "nonsolid_class": row.get("nonsolid_class"),
            "is_solid": bool(row.get("is_solid")),
            "separated_share": float(row.get("separated_share") or 0.0),
            "day_status": row.get("day_status"),
            "k_e_signal": int(row.get("k_e_signal") or 0),
            "is_drift_candidate": bool(row.get("is_drift_candidate")),
        }
    return out


def gaps_touching_collapse(
    records: list[dict[str, Any]],
    collapse_dates: set[str],
    day_by_date: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Breaking-gap rows that contain at least one severe-collapse day."""
    day_by_date = day_by_date or {}
    out: list[dict[str, Any]] = []
    for row in records:
        if row.get("record_type") != "gap":
            continue
        if not bool(row.get("has_severe_collapse")):
            continue
        between = [
            str(d)[:10]
            for d in (row.get("nonsolid_dates") or [])
            if str(d)[:10] in collapse_dates
        ]
        cause_totals = Counter(
            day_by_date[d]["cause_class"] for d in between if d in day_by_date
        )
        out.append(
            {
                "record_type": "implicated_gap",
                "left_solid_date": row.get("left_solid_date"),
                "right_solid_date": row.get("right_solid_date"),
                "calendar_gap_days": row.get("calendar_gap_days"),
                "n_nonsolid_session_days": row.get("n_nonsolid_session_days"),
                "dominant_class": row.get("dominant_class"),
                "class_counts": row.get("class_counts"),
                "collapse_dates_in_gap": between,
                "n_collapse_days_in_gap": len(between),
                "collapse_cause_totals": dict(cause_totals),
            }
        )
    return out


def attach_span_gap_flags(
    day: dict[str, Any],
    span_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge Tier O day flags onto an autopsy day record."""
    flags = span_index.get(day["enriched_date"], {})
    return {
        **day,
        "nonsolid_class": flags.get("nonsolid_class"),
        "is_solid": bool(flags.get("is_solid", False)),
        "separated_share": round(float(flags.get("separated_share", 0.0)), 4),
        "day_status": flags.get("day_status"),
        "k_e_signal": int(flags.get("k_e_signal") or 0),
        "is_drift_candidate": bool(flags.get("is_drift_candidate", False)),
        "in_span_gap_series": bool(flags),
    }


def summarize(
    days: list[dict[str, Any]],
    implicated_gaps: list[dict[str, Any]],
    *,
    n_predicted: int,
    parent_span_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Meta record with cause/class totals and a recommended next focus."""
    cause_totals = Counter(d["cause_class"] for d in days)
    nonsolid_totals = Counter(
        (d["nonsolid_class"] if d.get("nonsolid_class") is not None else "solid_or_missing")
        for d in days
    )
    n = len(days)
    n_pigeon = int(cause_totals.get("pigeonhole_forced", 0))
    n_room = int(cause_totals.get("room_on_axis", 0))
    n_weak = int(nonsolid_totals.get("weak_separation", 0))
    pigeon_share = (n_pigeon / n) if n else 0.0
    room_share = (n_room / n) if n else 0.0
    weak_share = (n_weak / n) if n else 0.0

    # Local lever: if most collapses are pigeonhole-forced, algorithm retunes won't help.
    # If room_on_axis dominates, placement/anchor work is still locally relevant.
    if n == 0:
        recommended = "no_severe_collapse_days"
    elif pigeon_share >= 0.5:
        recommended = "accept_structural_or_finer_axis"
    elif room_share >= 0.5:
        recommended = "local_placement_or_anchor_redesign"
    else:
        recommended = "mixed_structural_and_placement"

    # Global spans reminder — densifying weak_separation remains binding regardless.
    global_spans_note = (
        "Autopsy is a local quality lever. Global spans still require raising "
        "separated_share on weak_separation days (bridge ceiling longest=12d)."
    )

    max_load = max((int(d["max_on_paragraph"]) for d in days), default=0)
    mean_excess = (
        sum(int(d["excess_over_floor"]) for d in days) / n if n else 0.0
    )

    return {
        "record_type": "meta",
        "n_severe_collapse_days": n,
        "n_predicted_days": int(n_predicted),
        "severe_collapse_share_of_predicted": round((n / n_predicted) if n_predicted else 0.0, 4),
        "severe_collapse_min": SEVERE_COLLAPSE_MIN,
        "cause_class_totals": {c: int(cause_totals.get(c, 0)) for c in CAUSE_CLASSES},
        "nonsolid_class_totals": dict(sorted(nonsolid_totals.items())),
        "n_collapse_days_weak_separation": n_weak,
        "weak_separation_share_of_collapse": round(weak_share, 4),
        "n_collapse_days_solid": int(sum(1 for d in days if d.get("is_solid"))),
        "n_implicated_breaking_gaps": len(implicated_gaps),
        "implicated_gap_dominant_class_totals": dict(
            Counter(g.get("dominant_class") or "unknown" for g in implicated_gaps)
        ),
        "max_on_paragraph_corpus_max": max_load,
        "mean_excess_over_pigeonhole_floor": round(mean_excess, 3),
        "pigeonhole_forced_share": round(pigeon_share, 4),
        "room_on_axis_share": round(room_share, 4),
        "recommended_focus": recommended,
        "global_spans_note": global_spans_note,
        "parent_span_gap_implicated": (
            bool(parent_span_meta.get("severe_collapse_implicated"))
            if parent_span_meta
            else None
        ),
        "parent_breaking_gaps_with_collapse": (
            parent_span_meta.get("n_breaking_gaps_with_severe_collapse")
            if parent_span_meta
            else None
        ),
    }


def build_records(
    predictions: list[dict[str, Any]],
    span_gap_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble meta + day + implicated-gap records."""
    collapse_set = severe_collapse_dates(predictions)
    span_index = load_span_gap_day_index(span_gap_records)
    parent_meta = next(
        (r for r in span_gap_records if r.get("record_type") == "meta"),
        None,
    )

    days: list[dict[str, Any]] = []
    for row in predictions:
        day = collapse_day_record(row)
        if day is None:
            continue
        days.append(attach_span_gap_flags(day, span_index))
    days.sort(key=lambda d: (-int(d["max_on_paragraph"]), d["enriched_date"]))
    day_by_date = {d["enriched_date"]: d for d in days}
    implicated = gaps_touching_collapse(span_gap_records, collapse_set, day_by_date)

    n_predicted = sum(1 for r in predictions if r.get("status") == "predicted")
    meta = summarize(
        days,
        implicated,
        n_predicted=n_predicted,
        parent_span_meta=parent_meta,
    )
    return [meta, *days, *implicated]


def main() -> None:
    predictions = load(PRED_DATASET)
    if isinstance(predictions, pd.DataFrame):
        predictions = predictions.to_dict(orient="records")

    span_gap = load(SPAN_GAP_DATASET)
    if isinstance(span_gap, pd.DataFrame):
        span_gap = span_gap.to_dict(orient="records")

    records = build_records(predictions, span_gap)
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[PRED_DATASET, SPAN_GAP_DATASET],
        description=(
            "S6c severe-collapse autopsy: per-day max-on-paragraph, pigeonhole "
            "floor, mutually exclusive cause class, and Tier O nonsolid flags for "
            "days where ≥7 predicted resolutions share one paragraph start."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(
        f"severe_collapse_days={meta['n_severe_collapse_days']}/"
        f"{meta['n_predicted_days']} "
        f"(share={meta['severe_collapse_share_of_predicted']})"
    )
    print(f"cause_class_totals={meta['cause_class_totals']}")
    print(f"nonsolid_class_totals={meta['nonsolid_class_totals']}")
    print(
        f"weak_separation_share_of_collapse="
        f"{meta['weak_separation_share_of_collapse']} "
        f"solid_collapse_days={meta['n_collapse_days_solid']}"
    )
    print(
        f"implicated_breaking_gaps={meta['n_implicated_breaking_gaps']} "
        f"dominant={meta['implicated_gap_dominant_class_totals']}"
    )
    print(
        f"max_on_paragraph={meta['max_on_paragraph_corpus_max']} "
        f"mean_excess_over_floor={meta['mean_excess_over_pigeonhole_floor']}"
    )
    print(f"recommended_focus={meta['recommended_focus']}")
    print(meta["global_spans_note"])


if __name__ == "__main__":
    main()

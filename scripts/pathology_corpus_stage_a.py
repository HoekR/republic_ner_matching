#!/usr/bin/env python3
"""Pathology corpus -- Step 2, Stage A: forced vs. chosen collapse, scoped.

Per-SPAN (one anchor-bracketed gap in `segment_day`'s backbone, not the whole day)
pigeonhole-floor gate: a gap holding `k` unanchored resolutions in `room` paragraphs
of axis is **provably unseparable** at paragraph granularity whenever
`ceil(k / room) > 1` -- that is arithmetic, not a defect, and is *not* mined.
Classifies each gap:

* ``forced``  -- `observed_pile == pigeonhole_floor`: the DP piled exactly as much as
  arithmetic required. A defensible abstention.
* ``chosen``  -- `observed_pile > pigeonhole_floor`: the DP collapsed further than the
  room forced it to. Only this residue is worth Stage B's classifier (row_tie_divergence /
  column_contention -- not implemented here).

Reuses `align_session` (no similarity wiring, matching production's default
`semantic_weight=0.0`) to get the same anchors `segment_day` would see, and
`s6c_gap_segmentation.build_anchor_backbone` / `segment_gap` directly -- so span
accounting walks the identical backbone and DP that production's placement runs,
never a re-derived approximation of it.

Deliberately scoped, never corpus-wide in one call, per the 2026-09-30 runlog decision: three
ledger defects at Step 1 were invisible in summaries and appeared only on reading raw rows; at
corpus scale (~1,100 days) they would have produced silently wrong classification with no obvious
signal. Two scopes:

* ``--month YYYY-MM`` -- one calendar month.
* ``--severe-collapse-ambiguous`` -- the 58 of 83 `s6c_severe_collapse_autopsy` days whose
  `cause_class` is `axis_requires_repeats` or `room_on_axis` (i.e. day-level floor < 7 but the
  day-level metric still reports nonzero `excess_over_floor`). The other 25 (`pigeonhole_forced`,
  day-level floor already >= 7) are not ambiguous at the day level and are skipped. This is the
  exact population where the 1630-02-22 finding (whole-day floor overstates "chosen" collapse
  because it ignores where the anchors actually sit) could recur -- prints the day-level
  `cause_class` / `excess_over_floor` alongside the span-level result for direct comparison.

Read the raw output before widening further -- see `plans/PATHOLOGY_CORPUS_RUNLOG.md`.

No dataset write, no manifest entry -- diagnostic only, same posture as Step 1.

Usage:
    PYTHONPATH=. uv run python -m scripts.pathology_corpus_stage_a --month 1630-02
    PYTHONPATH=. uv run python -m scripts.pathology_corpus_stage_a --severe-collapse-ambiguous
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from typing import Any

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, resolve
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.s4_corpus_paragraph_predictions import OVERLAP_DATASETS, axis_for_date, grouped_enriched
from scripts.s4_paragraph_axis_baseline import build_axis_overlap
from scripts.s6c_gap_segmentation import build_anchor_backbone, segment_gap

import pandas as pd

SEVERE_COLLAPSE_DATASET = "s6c_severe_collapse_autopsy"
AMBIGUOUS_CAUSE_CLASSES = ("axis_requires_repeats", "room_on_axis")


def load_combined_overlap() -> pd.DataFrame:
    frames = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    frames = [
        frame.rename(columns={"naam": "name"}) if "name" not in frame and "naam" in frame else frame
        for frame in frames
    ]
    return pd.concat(frames, ignore_index=True)


def spans_for_day(
    enriched_count: int,
    axis_count: int,
    alignments: list[tuple[int | None, int | None]],
) -> list[dict[str, Any]]:
    """One record per anchor-bracketed gap with >0 unanchored resolutions.

    `room` mirrors `segment_gap`'s own slot count exactly (`max(low, high_anchor - 1) -
    low + 1`, i.e. `max(1, right_axis - left_axis)`) -- computed independently here would
    risk drifting from the DP it is meant to describe.
    """
    backbone = build_anchor_backbone(enriched_count, axis_count, alignments)
    spans: list[dict[str, Any]] = []
    for (left_e, left_a), (right_e, right_a) in zip(backbone, backbone[1:]):
        gap = right_e - left_e - 1
        if gap <= 0:
            continue
        room = max(1, right_a - left_a)
        floor = math.ceil(gap / room)
        chosen = segment_gap(left_a, right_a, gap)
        pile = max(Counter(chosen).values()) if chosen else 0
        spans.append({
            "left_enriched": left_e,
            "right_enriched": right_e,
            "left_axis": left_a,
            "right_axis": right_a,
            "unanchored_count": gap,
            "paragraph_room": room,
            "pigeonhole_floor": floor,
            "observed_pile": pile,
            "excess_over_floor": pile - floor,
            "collapse_class": "forced" if pile <= floor else "chosen",
        })
    return spans


def severe_collapse_ambiguous_days() -> dict[str, dict[str, Any]]:
    """Day-level context for the 58 `s6c_severe_collapse_autopsy` days whose `cause_class`
    is `axis_requires_repeats` or `room_on_axis` -- see module docstring."""
    records = load(SEVERE_COLLAPSE_DATASET)
    days = [
        r for r in records
        if r.get("record_type") == "day" and r.get("cause_class") in AMBIGUOUS_CAUSE_CLASSES
    ]
    return {str(r["enriched_date"]): r for r in days}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--month",
        help="Calendar month to scope this run to, e.g. 1630-02. Per the runlog: read one "
             "month's raw output before widening to an inventory or the corpus.",
    )
    scope.add_argument(
        "--severe-collapse-ambiguous",
        action="store_true",
        help="Scope to the 58 s6c_severe_collapse_autopsy days with cause_class "
             "axis_requires_repeats or room_on_axis -- the day-level-ambiguous population.",
    )
    args = parser.parse_args()

    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    combined_overlap = load_combined_overlap()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_by_date = grouped_enriched()

    day_context: dict[str, dict[str, Any]] = {}
    if args.month:
        month = args.month
        if len(month) != 7 or month[4] != "-":
            parser.error("--month must be YYYY-MM, e.g. 1630-02")
        dates = sorted(date for date in enriched_by_date if date.startswith(month))
        if not dates:
            print(f"No enriched resolutions found for month {month}.")
            return
    else:
        day_context = severe_collapse_ambiguous_days()
        dates = sorted(d for d in day_context if d in enriched_by_date)
        print(f"Scoped to {len(dates)} severe-collapse-ambiguous days (of {len(day_context)} flagged).")

    total_spans = total_forced = total_chosen = 0
    chosen_resolutions = 0
    missing_htr_days = 0
    day_level_disagreements = 0

    for date in dates:
        enriched_ids = enriched_by_date[date]
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis:
            missing_htr_days += 1
            print(f"{date}: missing_htr ({len(enriched_ids)} resolutions, no axis)")
            continue
        axis_ids = [record["axis_id"] for record in axis]
        lookup = build_axis_overlap(axis, combined_overlap)
        alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
        spans = spans_for_day(len(enriched_ids), len(axis_ids), alignments)

        forced = [s for s in spans if s["collapse_class"] == "forced"]
        chosen = [s for s in spans if s["collapse_class"] == "chosen"]
        total_spans += len(spans)
        total_forced += len(forced)
        total_chosen += len(chosen)
        chosen_resolutions += sum(s["unanchored_count"] for s in chosen)

        day_note = ""
        ctx = day_context.get(date)
        if ctx is not None:
            day_note = (
                f" | day-level cause_class={ctx['cause_class']} "
                f"day_excess_over_floor={ctx['excess_over_floor']}"
            )
            if not chosen and ctx["excess_over_floor"] > 0:
                day_level_disagreements += 1
                day_note += "  <-- day-level claims excess, span-level says all forced"

        print(
            f"{date}: k_e={len(enriched_ids)} paragraphs={len(axis_ids)} "
            f"spans={len(spans)} forced={len(forced)} chosen={len(chosen)}{day_note}"
        )
        for span in chosen:
            print(
                f"    CHOSEN gap [{span['left_enriched']}..{span['right_enriched']}] "
                f"axis[{span['left_axis']}..{span['right_axis']}) "
                f"unanchored={span['unanchored_count']} room={span['paragraph_room']} "
                f"floor={span['pigeonhole_floor']} observed={span['observed_pile']} "
                f"excess={span['excess_over_floor']}"
            )

    scope_label = args.month or "severe-collapse-ambiguous"
    print(
        f"\n{scope_label} summary: {len(dates)} days ({missing_htr_days} missing_htr), "
        f"{total_spans} spans, forced={total_forced}, chosen={total_chosen}, "
        f"resolutions in chosen spans={chosen_resolutions}"
    )
    if day_context:
        print(
            f"day-level-claims-excess-but-span-level-all-forced: {day_level_disagreements} "
            f"of {len(dates) - missing_htr_days} days checked"
        )


if __name__ == "__main__":
    main()

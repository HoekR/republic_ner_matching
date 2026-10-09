#!/usr/bin/env python3
"""Reconcile the physical scan sequence with the logical date/resolution sequence.

Answers the user's question of 2026-10-08 (*"have we now reconciled the session sequence
(physical) with the logical resolutions sequence?"* — answer: not before this script) by building
the correspondence out of the links that are **observed** rather than inferred, and reporting
exactly where it still blocks.

**The chain, and the single break.** `scan -> date` is observed (a heading on the page, parsed from
the region's own text, never consulting session attribution): 1,054 in-scope anchors, monotone,
median bracket 2-3 scans. `session -> its scans` is observed in the region metadata via
`resolution_archival_provenance`. `session -> HTR resolutions -> paragraphs` is a `flat_id` fact.
`enriched date -> enriched resolutions` is a fact. **Only `session -> enriched date` is inferred,
and the 2026-10-08 page reads showed that is the broken link.** So the physical side already
resolves to days, not years — the user's point that an inventory/year mapping with a 365-day gap is
always available is the floor, and we are far above it.

**What this produces.** For every session with an observed scan, a date range derived *physically*
— the bracket of scan->date anchors its paper falls in — set against the date the pipeline has
inferred for it. Three verdicts:

* `reconciled` — the inferred label lies inside the physically implied range.
* `contradicted` — it does not. The physical coordinate and the label disagree, and since the
  physical side is observed, these are misattribution candidates named one at a time.
* `unconstrained` — the session's paper falls outside any anchor bracket, so the physical side
  says nothing. Reported, never silently dropped.

**Direction of the comparison matters.** The physical range is evidence and the label is a
hypothesis, so a contradiction is not scored as "the physical side is wrong". But neither is it
scored as proof the label is wrong: a bracket is only as good as its two anchors, and the scan
track measured 1.3% loose-parse error, so `anchor_set` is carried per row and the strict-only
subset is the clean population.

**No placement change.** This writes a reconciliation table and changes nothing. Any eventual
re-dating writes to a new reviewable dataset, never in place.

Usage:
    uv run python scripts/reconcile_sequences.py
    uv run python scripts/reconcile_sequences.py --strict-only
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from running_axis.axis import RunningAxis
from scripts.build_unplaced_date_review import iiif_url
from scripts.corpus_scope import (
    MAIN_SERIES,
    SIDELINED_INVENTORIES,
    assert_no_sidelined,
    in_scope,
    is_main_series,
    is_sidelined,
    scope_meta,
    series_meta,
    sidelined_dates,
)
from scripts.measure_scans_per_day import observations

OUTPUT_DATASET = "sequence_reconciliation"
# A reconciliation is evidence only at a width where it could have failed. At 700 days (inventory
# 4562) any label falls inside, which is why the headline population is narrow windows only.
NARROW_WINDOW_DAYS = 2


def monotone_anchors(with_bootstrap: bool) -> tuple[dict[str, list[tuple[int, pd.Period]]], int]:
    """`inventory -> [(scan, date)]`, ascending in both, non-monotone observations dropped.

    Monotonicity is the free error filter this coordinate has and the session layer never did: a
    scan-keyed date running backwards is detectably wrong with no extra evidence.
    """
    first: dict[str, dict[pd.Period, int]] = defaultdict(dict)
    for inventory, scan, date, _src in observations(with_bootstrap):
        prev = first[inventory].get(date)
        if prev is None or scan < prev:
            first[inventory][date] = scan
    out: dict[str, list[tuple[int, pd.Period]]] = {}
    dropped = 0
    for inventory, by_date in first.items():
        kept: list[tuple[int, pd.Period]] = []
        high = -1
        for date in sorted(by_date):
            scan = by_date[date]
            if scan < high:
                dropped += 1
                continue
            high = scan
            kept.append((scan, date))
        out[inventory] = kept
    return out, dropped


def session_scans() -> dict[str, tuple[int, int]]:
    """`session_id -> (first_scan, last_scan)` observed, never inferred."""
    seen: dict[str, list[int]] = defaultdict(list)
    for row in load("resolution_archival_provenance"):
        if not row.get("found") or not row.get("scan_ids"):
            continue
        for scan in row["scan_ids"]:
            seen[row["session_id"]].append(int(str(scan).split("_")[-1]))
    return {s: (min(v), max(v)) for s, v in seen.items() if v}


def implied_range(
    points: list[tuple[int, pd.Period]], scan: int
) -> tuple[pd.Period | None, pd.Period | None]:
    """The anchor bracket a scan falls in: (left date, right date).

    The forward-claim rule — nothing ever explicitly ends, so the left anchor claims forward to
    the next one. A scan at or after the last anchor is bounded on the left only; before the
    first, on the right only.
    """
    left = right = None
    for a_scan, a_date in points:
        if a_scan <= scan:
            left = a_date
        else:
            right = a_date
            break
    return left, right


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-only", action="store_true",
                        help="drop the bracket-bootstrap anchors (clean, 0% loose parse)")
    args = parser.parse_args()
    with_bootstrap = not args.strict_only
    anchor_set = "strict" if args.strict_only else "strict+bootstrap"

    anchors, dropped = monotone_anchors(with_bootstrap)
    scans = session_scans()
    axis = RunningAxis.load()
    # Sidelined at ingest (user, 2026-10-08): "all of them, and only those". Stated provenance
    # only -- a session id names its inventory, so this is a fact, not a candidate guess.
    all_spans = dict(axis.sessions)
    spans = {s: v for s, v in all_spans.items() if not is_sidelined(s)}
    print(f"sidelined at ingest: {len(all_spans) - len(spans)} sessions of the secret series "
          f"dropped from the sequence ({len(sidelined_dates())} enriched dates go with them)")

    print(f"anchor set {anchor_set}: "
          f"{sum(len(v) for v in anchors.values()):,} monotone anchors "
          f"({dropped} non-monotone observations dropped)")
    on_axis = {s: v for s, v in scans.items() if s in spans}
    print(f"sessions: {len(spans):,} on the axis, {len(on_axis):,} with an observed scan "
          f"({len(on_axis)/max(1,len(spans)):.1%}); {len(scans) - len(on_axis):,} scanned "
          f"sessions are not on the axis at all (post-bar or non-axis inventories)")

    rows: list[dict[str, Any]] = []
    for session_id, span in spans.items():
        obs = scans.get(session_id)
        points = anchors.get(span.inventory, [])
        label_dates = [d for d in span.label_dates if in_scope(d)]
        resolved = [d for d in span.resolved_dates if in_scope(d)]
        row: dict[str, Any] = {
            "record_type": "session",
            "anchor_set": anchor_set,
            "session_id": session_id,
            "inventory": span.inventory,
            "session_num": span.session_num,
            "paragraph_count": span.paragraph_count,
            "char_length": span.char_length,
            "label_dates": label_dates,
            "resolved_dates": resolved,
            "is_shared": span.is_shared,
            "main_series": is_main_series(session_id),
            "first_scan": obs[0] if obs else None,
            "last_scan": obs[1] if obs else None,
        }
        if not obs or not points:
            row.update({"verdict": "no_observed_scan" if not obs else "no_anchors",
                        "implied_date_lo": None, "implied_date_hi": None,
                        "implied_window_days": None})
            rows.append(row)
            continue

        lo, hi = implied_range(points, obs[0])
        row["implied_date_lo"] = str(lo) if lo is not None else None
        row["implied_date_hi"] = str(hi) if hi is not None else None
        row["implied_window_days"] = (hi - lo).n if (lo is not None and hi is not None) else None

        check = resolved or label_dates
        if lo is None and hi is None:
            row["verdict"] = "unconstrained"
        elif not check:
            row["verdict"] = "no_label_to_check"
        else:
            inside = [
                d for d in check
                if (lo is None or str(lo) <= d) and (hi is None or d <= str(hi))
            ]
            row["verdict"] = "reconciled" if inside else "contradicted"
            row["labels_inside_implied_range"] = len(inside)
            if not inside:
                # How far off, in days, measured to the nearer edge of the implied window.
                offs = []
                for d in check:
                    p = pd.Period(d, freq="D")
                    if lo is not None and p < lo:
                        offs.append((p - lo).n)
                    elif hi is not None and p > hi:
                        offs.append((p - hi).n)
                row["offset_days"] = min(offs, key=abs) if offs else None
        row["images"] = [u for u in [iiif_url(f"NL-HaNA_1.01.02_{span.inventory}_{obs[0]:04d}")] if u]
        rows.append(row)

    frame = pd.DataFrame(rows)

    # A crowded implied window is the bad-ANCHOR signature: several contradicted sessions all
    # pointing at one bracket means the bracket is wrong, not that every session moved. Checked
    # BEFORE window width, since a bad anchor is usually what made the window wide.
    frame["implied_window"] = (frame["implied_date_lo"].astype(str) + ".."
                               + frame["implied_date_hi"].astype(str))
    crowd = frame.loc[frame["verdict"] == "contradicted", "implied_window"].value_counts()
    frame["sessions_sharing_implied_window"] = (
        frame["implied_window"].map(crowd).fillna(0).astype(int))

    def problem_type(r: pd.Series) -> str:
        if r["verdict"] == "no_observed_scan":
            return "T6_no_scan_observed"
        if r["verdict"] == "no_label_to_check":
            return "T7_nothing_inferred"
        if r["verdict"] == "reconciled":
            return "T0_anchor"
        if r["sessions_sharing_implied_window"] >= 3:
            return "T4_anchor_bracket_suspect"
        window = r["implied_window_days"]
        offset = r.get("offset_days")
        if pd.isna(window) or window > NARROW_WINDOW_DAYS or pd.isna(offset):
            return "T5_window_too_wide_to_judge"
        off = abs(offset)
        if off <= 2:
            return "T1_offset_1_2_days"
        return "T2_offset_3_7_days" if off <= 7 else "T3_offset_over_7_days"

    frame["problem_type"] = frame.apply(problem_type, axis=1)
    counts = frame["verdict"].value_counts().to_dict()

    main = frame[frame["main_series"]]
    types = (main.groupby("problem_type")
             .agg(sessions=("session_id", "size"), paragraphs=("paragraph_count", "sum")))
    types["share"] = (types["sessions"] / len(main)).round(3)
    print(f"\nPROBLEM TYPES, main series 3185-3189 only "
          f"({len(main):,} sessions; {sorted(SIDELINED_INVENTORIES)} sidelined):")
    print(types.to_string())
    typology = {k: {"sessions": int(v["sessions"]), "paragraphs": int(v["paragraphs"]),
                    "share": float(v["share"])} for k, v in types.iterrows()}
    print("\nRECONCILIATION VERDICTS:")
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<20}{n:>6}  ({n/len(frame):>5.1%})")

    assert_no_sidelined(frame, "session_id")
    decided = frame[frame["verdict"].isin(["reconciled", "contradicted"])]
    if len(decided):
        agree = (decided["verdict"] == "reconciled").mean()
        print(f"\n  MAIN SERIES: of {len(decided):,} decidable sessions, {agree:.1%} reconcile "
              f"with the physical coordinate and {1-agree:.1%} contradict it")
        win = decided["implied_window_days"].dropna()
        print(f"  granularity achieved: implied window median {win.median():.0f} days, "
              f"p25 {win.quantile(.25):.0f}, p75 {win.quantile(.75):.0f} "
              f"(the user's 365-day floor is {365/max(1,win.median()):.0f}x coarser)")
        contra = decided[decided["verdict"] == "contradicted"]
        if len(contra) and contra["offset_days"].notna().any():
            off = contra["offset_days"].dropna()
            print(f"  contradicted offsets: median {off.median():+.0f} days, "
                  f"{(off < 0).mean():.0%} label EARLIER than the paper allows, "
                  f"|offset| <= 2 in {(off.abs() <= 2).mean():.0%}")

    # The unifying frame (user, 2026-10-08: "how does the available evidence consolidate to
    # anchor/gaps terms"). Every session is exactly one of three things, and a reconciliation is
    # only evidence at a width where it could have failed -- a 700-day window reconciles trivially,
    # which is why the headline is the <= NARROW_WINDOW_DAYS population.
    main = frame[frame["main_series"]]
    narrow = main[main["implied_window_days"].notna()
                  & (main["implied_window_days"] <= NARROW_WINDOW_DAYS)
                  & main["verdict"].isin(["reconciled", "contradicted"])]
    hard = narrow[narrow["verdict"] == "reconciled"]
    bounded = narrow[narrow["verdict"] == "contradicted"]
    unconstrained = frame[frame["verdict"].isin(
        ["no_observed_scan", "no_anchors", "unconstrained", "no_label_to_check"])]
    consolidation = {
        "hard_anchors": {
            "sessions": int(len(hard)), "paragraphs": int(hard["paragraph_count"].sum()),
            "meaning": (
                f"label agrees with the observed paper inside a <= {NARROW_WINDOW_DAYS}-day window "
                "-- a pin, not a hypothesis"
            ),
        },
        "bounded_gaps": {
            "sessions": int(len(bounded)), "paragraphs": int(bounded["paragraph_count"].sum()),
            "median_offset_days": (
                float(bounded["offset_days"].median()) if bounded["offset_days"].notna().any() else None
            ),
            "share_within_7_days": (
                float((bounded["offset_days"].abs() <= 7).mean())
                if bounded["offset_days"].notna().any() else None
            ),
            "meaning": "physically placed but logically mis-dated: a gap with a measured bound",
        },
        "unconstrained_gaps": {
            "sessions": int(len(unconstrained)),
            "paragraphs": int(unconstrained["paragraph_count"].sum()),
            "meaning": "no physical evidence or nothing inferred to check -- an open gap",
        },
    }
    print(f"\nCONSOLIDATED INTO ANCHOR/GAP TERMS "
          f"(window <= {NARROW_WINDOW_DAYS} days; secret series already gone):")
    for name, block in consolidation.items():
        print(f"  {name:<20}{block['sessions']:>5} sessions  "
              f"{block['paragraphs']:>6,} paragraphs  -- {block['meaning']}")
    if consolidation["bounded_gaps"]["median_offset_days"] is not None:
        print(f"    bounded-gap offsets: median "
              f"{consolidation['bounded_gaps']['median_offset_days']:+.0f} days, "
              f"{consolidation['bounded_gaps']['share_within_7_days']:.0%} within a week")

    print("\nRECONCILIATION RATE BY IMPLIED WINDOW WIDTH -- a wide window reconciles trivially,")
    print("so the rate is only evidence where it could have failed:")
    dec = frame[frame["verdict"].isin(["reconciled", "contradicted"])
                & frame["implied_window_days"].notna()].copy()
    dec["band"] = pd.cut(dec["implied_window_days"], [0, 1, 2, 3, 7, 30, 10**4],
                         labels=["1", "2", "3", "4-7", "8-30", "31+"], include_lowest=True)
    for band, sub in dec.groupby("band", observed=True):
        print(f"    {str(band):<6}{len(sub):>5}  reconciled {(sub['verdict']=='reconciled').mean():>6.1%}"
)

    print("\nWHERE IT STILL BLOCKS:")
    for name, why in [
        ("no_observed_scan", "no resolution of this session carries a scan id in provenance"),
        ("no_anchors", "its inventory has no parsed scan->date anchor at all"),
        ("unconstrained", "its paper falls outside every anchor bracket"),
        ("no_label_to_check", "nothing inferred for it, so there is nothing to reconcile against"),
    ]:
        n = counts.get(name, 0)
        if n:
            sub = frame[frame["verdict"] == name]
            print(f"  {name:<20}{n:>6}  {int(sub['paragraph_count'].sum()):>7,} paragraphs  -- {why}")

    print("\nBIGGEST CONTRADICTIONS (physical paper vs inferred label):")
    cols = ["session_id", "first_scan", "implied_date_lo", "implied_date_hi",
            "resolved_dates", "label_dates", "offset_days", "paragraph_count"]
    contra = frame[frame["verdict"] == "contradicted"]
    if len(contra):
        print(contra.reindex(contra["offset_days"].abs().sort_values(ascending=False).index)
              .head(12)[cols].to_string(index=False))

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Reconciliation of the physical scan sequence with the logical date sequence. For each "
            "HTR session, a date range derived from OBSERVED scan->date anchors, set against the "
            "date the pipeline infers for it. Verdicts: reconciled / contradicted / blocked."
        ),
        "parent_datasets": [
            "scan_anchor_bootstrap", "session_region_text_1626_1630",
            "resolution_archival_provenance", "running_axis_snapshot",
        ],
        **scope_meta(),
        "anchor_set": anchor_set,
        "monotone_anchors": sum(len(v) for v in anchors.values()),
        "non_monotone_dropped": dropped,
        "sessions_on_axis": len(spans),
        "sessions_with_observed_scan": len(scans),
        "verdicts": counts,
        "verdicts_main_series": frame[frame["main_series"]]["verdict"].value_counts().to_dict(),
        **series_meta(),
        "the_single_break": (
            "scan->date is observed, session->scans is observed, session->resolutions->paragraphs "
            "is a flat_id fact, and date->enriched resolutions is a fact. Only session->enriched "
            "date is inferred, and the 2026-10-08 page reads showed that is the broken link. So "
            "the physical side resolves to days rather than years: an inventory/year mapping with "
            "a 365-day gap is the floor, not the starting point."
        ),
        "direction_of_evidence": (
            "The physical range is evidence and the label is a hypothesis, so a contradiction is "
            "not scored as the physical side being wrong -- but neither is it proof the label is "
            "wrong, because a bracket is only as good as its two anchors and the bootstrap carries "
            "a measured 1.3% loose-parse error. Run --strict-only for the clean population."
        ),
        "consolidation_in_anchor_gap_terms": consolidation,
        "problem_typology_main_series": typology,
        "problem_type_legend": {
            "T0_anchor": "label agrees with the observed paper inside a <= 2-day window: a pin",
            "T1_offset_1_2_days": "off by 1-2 days -- the benign nihil-Sunday-glued-to-Monday shape",
            "T2_offset_3_7_days": "off by 3-7 days: inside one week's paper",
            "T3_offset_over_7_days": "off by more than a week: a real displacement",
            "T4_anchor_bracket_suspect": (
                "3+ contradicted sessions share one implied window, so the BRACKET is wrong rather "
                "than every session in it -- an anchor-repair item, not a re-dating item"
            ),
            "T5_window_too_wide_to_judge": "the physical side does not constrain it tightly enough",
            "T6_no_scan_observed": "no resolution of this session carries a scan id",
            "T7_nothing_inferred": "nothing inferred for it, so there is nothing to reconcile",
        },
        "narrow_window_days": NARROW_WINDOW_DAYS,
        "width_confound": (
            "Reconciliation rate by implied window width is 43.9/46.1/32.8/38.1% at 1/2/3/4-7 days "
            "and then 63.0/71.4% at 8-30/31+ days -- but those wide bands are 70% and 100% "
            "inventory 4562, so the apparent 'pathological inventory reconciles better' is purely "
            "the width artefact: a 700-day window cannot fail. Quote the narrow bands only."
        ),
        "not_claimed": "No placement change. Any re-dating writes to a new reviewable dataset.",
    }
    records = [meta] + frame.to_dict(orient="records")
    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {len(frame):,} sessions to {path}")


if __name__ == "__main__":
    main()

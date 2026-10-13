#!/usr/bin/env python3
"""Both layers' business on one bracket: what the edition requires vs what the paper carries.

Track: `plans/archive/SCAN_SEQUENCE_TRACK.md`. Answers the question put by the user (2026-10-08) in the
order it was put: per bracket, start and end date, the resolutions on it, and how that compares
with `k_e`; then the biggest gaps by dates/sessions, by cumulative resolutions and by resolutions
per date; then where a separation would have to be proposed, expressed in paragraphs.

**Why this is the first bracket measurement that can carry the HTR side.** Every earlier one
compared physical room (scans) against logical business (`k_e`). Room in scans is a weak unit — a
scan holds ~14 resolutions and the span model's residual sd is ~2 scans against a median bracket
of 3. `resolution_archival_provenance` gives the missing join: `flat_id -> scan_ids`, so HTR
resolutions can be put on the same axis and the comparison becomes resolution-to-resolution.

**Sessions are assigned to brackets, not resolutions.** Only 9,145 of 12,811 axis resolutions have
a scan (71.4%), so counting resolutions-with-a-scan per bracket would deflate the HTR side by
~29% in a way that varies between brackets. Instead a **session** is placed by the first scan any
of its resolutions is observed on, and then *all* of that session's axis resolutions and paragraphs
are counted. Sessions sit on contiguous paper, so the placement is sound even when the per-
resolution coverage is patchy, and `k_f` stops being a coverage artefact.

**The misattribution check falls out for free, which is the point.** A bracket's date range is
*observed* — two headings on the paper. A session's date label is *inferred*, and the 2026-10-08
page reads showed that inference is the broken link. So a session whose axis label lies outside the
date range of the bracket its own paper sits in is a localised, checkable misattribution candidate,
and this is the first instrument in the project that can name them one by one.

**What is NOT claimed here.** No placement changes and no cut is applied. Cut *candidates* are
proposed, each with the evidence that implies it, and `paragraphs < k_e` brackets are reported as
pigeonhole-blocked rather than given proposals they cannot satisfy.

Scope bar applied at ingest on both the anchors and the paragraph axis (the axis carries 2,284
post-bar paragraphs; see `scripts/corpus_scope.py`).

Usage:
    uv run python scripts/bracket_business_ledger.py
    uv run python scripts/bracket_business_ledger.py --with-bootstrap --top 15
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.build_unplaced_date_review import iiif_url
from scripts.corpus_scope import (
    assert_no_sidelined,
    in_scope,
    is_sidelined,
    scope_meta,
    series_meta,
)
from scripts.measure_scans_per_day import calendar, observations

OUTPUT_DATASET = "bracket_business_ledger"


def session_of(flat_id: str) -> str:
    return str(flat_id).rsplit("-resolution-", 1)[0]


def htr_layer() -> dict[str, dict[str, Any]]:
    """`session_id -> {first_scan, k_f, paragraphs, axis_dates}` for the HTR side.

    `k_f` and the paragraph count come from the axis (complete); `first_scan` comes from
    provenance (71.4% of resolutions, but a session needs only one). `axis_dates` is this corpus's
    own inferred label — carried to be *checked against* the bracket, never to place anything.
    """
    scan_of: dict[str, int] = {}
    for row in load("resolution_archival_provenance"):
        if not row.get("found") or not row.get("scan_ids"):
            continue
        scans = [int(str(s).split("_")[-1]) for s in row["scan_ids"]]
        scan_of[row["flat_id"]] = min(scans)

    sessions: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"first_scan": None, "resolutions": set(), "paragraphs": 0,
                 "axis_dates": Counter(), "out_of_scope_paragraphs": 0}
    )
    for row in load("paragraph_axis_1626_1630"):
        if row.get("record_type") == "meta" or not row.get("flat_id"):
            continue
        session = session_of(row["flat_id"])
        entry = sessions[session]
        # Scope bar at ingest: the axis runs to 1630-12-31 while the edition ends 1630-05-14.
        if not in_scope(row.get("date")):
            entry["out_of_scope_paragraphs"] += 1
            continue
        entry["resolutions"].add(row["flat_id"])
        entry["paragraphs"] += 1
        entry["axis_dates"][str(row["date"])[:10]] += 1
        scan = scan_of.get(row["flat_id"])
        if scan is not None and (entry["first_scan"] is None or scan < entry["first_scan"]):
            entry["first_scan"] = scan
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-bootstrap", action="store_true",
                        help="add the loose-parse anchors (denser, 1.3% anchor error)")
    parser.add_argument("--top", type=int, default=10, help="rows per ranking")
    args = parser.parse_args()

    k_e, nihil, edition_end = calendar()
    obs = observations(args.with_bootstrap)
    sessions = htr_layer()

    placed = {s: e for s, e in sessions.items() if e["first_scan"] is not None and e["paragraphs"]}
    print(f"HTR layer: {len(sessions):,} sessions on the axis, {len(placed):,} placeable on a scan "
          f"({sum(e['paragraphs'] for e in placed.values()):,} paragraphs, "
          f"{sum(len(e['resolutions']) for e in placed.values()):,} resolutions)")
    dropped = sum(e["out_of_scope_paragraphs"] for e in sessions.values())
    print(f"  scope bar at ingest: dropped {dropped:,} post-{edition_end} axis paragraphs")

    # Sessions by inventory, so a bracket only ever claims paper from its own volume.
    by_inventory: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for session, entry in placed.items():
        parts = str(session).split("-")
        inventory = parts[1] if len(parts) > 1 else "?"
        by_inventory[inventory].append((entry["first_scan"], session))
    for inventory in by_inventory:
        by_inventory[inventory].sort()

    anchors: dict[str, dict[int, pd.Period]] = defaultdict(dict)
    for inventory, scan, date, _src in obs:
        anchors[inventory].setdefault(scan, date)

    rows: list[dict[str, Any]] = []
    for inventory, by_scan in sorted(anchors.items()):
        # `observations` already sidelines at source; this is the guard, not a second filter.
        assert not is_sidelined(inventory), inventory
        points = sorted(by_scan.items())
        for (scan_a, date_a), (scan_b, date_b) in zip(points, points[1:]):
            if scan_b <= scan_a or (date_b - date_a).n <= 0:
                continue
            days = list(pd.period_range(date_a, date_b - 1, freq="D"))
            day_keys = [str(d) for d in days]
            sitting = [d for d in day_keys if d not in nihil and k_e.get(d, 0) > 0]
            ke_total = sum(k_e.get(d, 0) for d in day_keys)

            # The HTR side: sessions whose paper starts inside this bracket.
            here = [s for scan, s in by_inventory.get(inventory, [])
                    if scan_a <= scan < scan_b]
            kf_total = sum(len(placed[s]["resolutions"]) for s in here)
            paragraphs = sum(placed[s]["paragraphs"] for s in here)
            labels = Counter()
            for s in here:
                labels.update(placed[s]["axis_dates"])
            # Observed range vs inferred label: the misattribution check.
            outside = sorted({d for d in labels if not (str(date_a) <= d <= str(date_b))})

            rows.append({
                "record_type": "bracket",
                "inventory": inventory,
                "from_scan": scan_a,
                "to_scan": scan_b,
                "start_date": str(date_a),
                "end_date": str(date_b),
                "room_scans": scan_b - scan_a,
                # --- what the edition requires
                "calendar_days": len(days),
                "sitting_days": len(sitting),
                "nihil_days": sum(1 for d in day_keys if d in nihil),
                "k_e": ke_total,
                # --- what the paper carries
                "htr_sessions": len(here),
                "k_f": kf_total,
                "paragraphs": paragraphs,
                # --- the three comparisons asked for
                "gap_sessions": len(sitting) - len(here),
                "gap_resolutions": ke_total - kf_total,
                "ke_per_sitting_day": round(ke_total / len(sitting), 2) if sitting else None,
                "kf_per_session": round(kf_total / len(here), 2) if here else None,
                "gap_resolutions_per_date": (
                    round(ke_total / len(sitting) - kf_total / len(here), 2)
                    if sitting and here else None
                ),
                # --- can a paragraph-level separation even succeed here
                "paragraphs_per_ke": round(paragraphs / ke_total, 2) if ke_total else None,
                "paragraph_slack": paragraphs - ke_total,
                "pigeonhole_blocked": bool(ke_total and paragraphs < ke_total),
                # --- misattribution, localised
                "session_labels_outside_bracket": outside,
                "sessions_mislabelled": len(outside),
                "session_ids": here,
                "images": [u for u in (iiif_url(f"NL-HaNA_1.01.02_{inventory}_{s:04d}")
                                       for s in (scan_a, scan_b)) if u],
            })

    frame = pd.DataFrame(rows)
    assert_no_sidelined(frame, "inventory")
    print(f"\n{len(frame):,} brackets (secret series sidelined at source), "
          f"{frame['k_e'].sum():,} k_e vs {frame['k_f'].sum():,} k_f, "
          f"{frame['paragraphs'].sum():,} paragraphs")

    # ---------------------------------------------------------------- the typology
    def classify(r: pd.Series) -> str:
        if r["k_e"] == 0 and r["k_f"] > 0:
            return "F_paper_edition_does_not_record"
        if r["k_f"] == 0 and r["k_e"] > 0:
            return "E_no_htr_text_at_all"
        if r["pigeonhole_blocked"]:
            return "D_pigeonhole_blocked"
        if r["gap_sessions"] > 0:
            return "A_one_session_several_dates"
        if r["gap_resolutions"] > 0:
            return "B_edition_splits_finer_than_htr"
        if r["gap_resolutions"] < 0:
            return "C_htr_splits_finer_than_edition"
        return "G_balanced"

    frame["problem_class"] = frame.apply(classify, axis=1)
    print("\nPROBLEM CLASSES -- what kind of work each bracket needs:")
    legend = {
        "A_one_session_several_dates": "SESSION separation: fewer sessions than sitting days",
        "B_edition_splits_finer_than_htr": "RESOLUTION separation: k_e > k_f, cuts inside paragraphs",
        "C_htr_splits_finer_than_edition": "over-split or foreign paper: k_f > k_e",
        "D_pigeonhole_blocked": "paragraphs < k_e -- no paragraph-level separation can succeed",
        "E_no_htr_text_at_all": "edition records business, paper carries none",
        "F_paper_edition_does_not_record": "paper carries business the edition does not",
        "G_balanced": "counts agree",
    }
    for name, n in frame["problem_class"].value_counts().items():
        sub = frame[frame["problem_class"] == name]
        print(f"  {name:<34}{n:>5}  k_e {sub['k_e'].sum():>6}  k_f {sub['k_f'].sum():>6}"
              f"   {legend[name]}")

    # ---------------------------------------------------------------- the rankings
    show = ["inventory", "from_scan", "to_scan", "start_date", "end_date",
            "sitting_days", "htr_sessions", "k_e", "k_f", "paragraphs"]
    print(f"\n1) BIGGEST GAPS IN DATES/SESSIONS (sitting days the paper has no session for):")
    print(frame.nlargest(args.top, "gap_sessions")[
        show + ["gap_sessions", "gap_resolutions"]].to_string(index=False))
    print(f"\n2) BIGGEST GAPS IN RESOLUTIONS, CUMULATIVE (k_e - k_f):")
    print(frame.nlargest(args.top, "gap_resolutions")[
        show + ["gap_resolutions", "paragraph_slack", "pigeonhole_blocked"]].to_string(index=False))
    print(f"\n3) BIGGEST GAPS IN RESOLUTIONS PER DATE (k_e/sitting day - k_f/session):")
    ranked = frame.dropna(subset=["gap_resolutions_per_date"])
    print(ranked.nlargest(args.top, "gap_resolutions_per_date")[
        show + ["ke_per_sitting_day", "kf_per_session", "gap_resolutions_per_date"]
    ].to_string(index=False))

    # ------------------------------------------------- where separation is proposed
    print("\nWHERE TO SEPARATE, in paragraphs")
    sep_sessions = frame[frame["gap_sessions"] > 0]
    sep_res = frame[(frame["gap_resolutions"] > 0) & ~frame["pigeonhole_blocked"]]
    blocked = frame[frame["pigeonhole_blocked"]]
    print(f"  SESSION cuts proposed in {len(sep_sessions):,} brackets: "
          f"{int(sep_sessions['gap_sessions'].sum()):,} sitting days need a session boundary "
          f"inside {sep_sessions['paragraphs'].sum():,} paragraphs")
    print(f"  RESOLUTION cuts proposed in {len(sep_res):,} brackets: "
          f"{int(sep_res['gap_resolutions'].sum()):,} enriched resolutions need a cut inside an "
          f"existing HTR resolution, with {int(sep_res['paragraph_slack'].sum()):,} spare "
          f"paragraphs available")
    print(f"  BLOCKED in {len(blocked):,} brackets: {int(blocked['k_e'].sum()):,} k_e against "
          f"{int(blocked['paragraphs'].sum()):,} paragraphs -- fewer paragraphs than resolutions, "
          f"so no paragraph-level cut can separate them at all")
    print(f"  MISATTRIBUTION candidates: {int((frame['sessions_mislabelled'] > 0).sum()):,} "
          f"brackets hold a session whose own label falls outside the dates observed on its paper")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Both layers' business on one bracket: what the edition requires (sitting days, k_e) "
            "against what the paper carries (sessions, k_f, paragraphs), plus the three gap "
            "rankings and where a separation would have to be proposed, in paragraphs."
        ),
        "parent_datasets": [
            "resolution_archival_provenance", "paragraph_axis_1626_1630",
            "enriched_resolutions_1626_1630", "session_region_text_1626_1630",
            "scan_anchor_bootstrap",
        ],
        **scope_meta(),
        **series_meta(),
        "with_bootstrap_anchors": args.with_bootstrap,
        "brackets": len(frame),
        "totals": {
            "k_e": int(frame["k_e"].sum()),
            "k_f": int(frame["k_f"].sum()),
            "paragraphs": int(frame["paragraphs"].sum()),
            "sitting_days": int(frame["sitting_days"].sum()),
            "htr_sessions": int(frame["htr_sessions"].sum()),
        },
        "session_placement": {
            "rule": (
                "A session is placed by the first scan any of its resolutions is observed on, then "
                "ALL its axis resolutions and paragraphs are counted. Per-resolution scan coverage "
                "is 71.4%, so counting only resolutions-with-a-scan would deflate k_f unevenly "
                "between brackets; sessions sit on contiguous paper, so placing the session and "
                "counting the whole of it removes that artefact."
            ),
            "sessions_on_axis": len(sessions),
            "sessions_placeable": len(placed),
        },
        "problem_class_legend": legend,
        "problem_class_counts": frame["problem_class"].value_counts().to_dict(),
        "separation": {
            "session_cut_brackets": len(sep_sessions),
            "session_cuts_needed": int(sep_sessions["gap_sessions"].sum()),
            "resolution_cut_brackets": len(sep_res),
            "resolution_cuts_needed": int(sep_res["gap_resolutions"].sum()),
            "pigeonhole_blocked_brackets": len(blocked),
            "pigeonhole_blocked_ke": int(blocked["k_e"].sum()),
            "misattribution_candidate_brackets": int((frame["sessions_mislabelled"] > 0).sum()),
        },
        "not_claimed": (
            "No placement change and no cut applied. Cut candidates are proposals carrying their "
            "own evidence; pigeonhole-blocked brackets get none, because no paragraph-level cut "
            "can separate more resolutions than there are paragraphs."
        ),
    }
    records = [meta] + frame.to_dict(orient="records")
    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {len(frame):,} brackets to {path}")


if __name__ == "__main__":
    main()

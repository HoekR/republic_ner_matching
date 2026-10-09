#!/usr/bin/env python3
"""Brackets on the PHYSICAL scan axis: room available against business the calendar requires.

Track: `plans/SCAN_SEQUENCE_TRACK.md` (opened 2026-10-08).

**The structural principle this rests on** (user, 2026-10-08): *sessions never explicitly end —
they implicitly end when another session begins, and the same is true of resolutions.* So an end
is not a missing datum that better data could supply; **it is not a thing that exists**. Every
start claims forward until the next start. Three consequences, all encoded here rather than
left in prose:

1. **The bracket is the natural unit, not an approximation.** The scan axis is a partition by
   start points, so comparing inside a bracket is comparing where the structure actually is.
2. **There is no such thing as an unclaimed scan between two anchors** — the earlier anchor
   claims it. The 2026-10-06 orphan-page error (420 scans that looked unclaimed, all in fact
   belonging to the left bracketing session) came from computing an extent as `max(page_ids)`
   instead of "forward to the next start". That is a modelling error, not a data gap, and
   `ES metadata.page_ids` recording only starts is therefore COMPLETE information, not partial.
3. **A bracket cannot be "compressed".** Room is fixed by the anchors, so `room < predicted`
   can only mean non-contiguous anchors, absent pages, or a wrong anchor — never that the same
   business was squeezed into fewer pages.

Where the comparison happens, and why only here: the bracket is the one place both layers are
simultaneously constrained. The **physical** side supplies room (`s2 - s1` scans). The **logical**
side — the XML sitting-day calendar, which has no physical grounding of its own — supplies the
days that must fall in between and their `k_e`. Nothing is compared globally.

Anchors are parsed from each `date` region's own text and keyed by `scan_id`, **never consulting
session attribution**, which the 2026-10-08 page reads showed to be the broken link (the dates
were never the problem, the coordinate was).

Span model, refitted here with sitting-days and `k_e` as separate predictors. An earlier
single-predictor fit (`scans ~ 1.42 + 0.107*k_e`) had its per-BRACKET intercept applied per DAY,
which inflated multi-day predictions and manufactured a spurious "less room than business" class.
With both predictors the picture changes: **a sitting day costs ~1.3 scans almost regardless of
how much business it holds**, while `k_e` adds ~0.036 scans per resolution (~28 resolutions to a
scan). Most of what `k_e` appeared to explain was "more days means more resolutions". That is what
the implicit-end model predicts: the per-day cost is heading, attendance and layout -- fixed
overhead claimed forward.

The model is fitted on the well-behaved core only, so pathological brackets cannot set the
coefficients, and is then applied to all brackets.

Diagnostic only: writes one dataset, changes no placement.

Usage:
    uv run python scripts/build_scan_anchor_brackets.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, scope_meta
from scripts.h_session_date_vs_heading import read_heading
from scripts.s4_candidate_scoring import is_nihil_actum

OUTPUT_DATASET = "scan_anchor_brackets"
REGION_DATASET = "session_region_text_1626_1630"

# A bracket is "core" -- usable for fitting -- when its anchors plausibly bracket contiguous
# material. Inventory 4562 fails this wholesale (8 anchors spread over the whole period, so
# consecutive anchors sit 700 days apart on adjacent scans) and is excluded from the fit by the
# same rule rather than by name.
CORE_MAX_ROOM = 25
CORE_MAX_DAYS = 25
FIT_TOLERANCE = 2.5  # |residual| within this counts as `fits`; ~1 residual sd


def scan_date_anchors() -> dict[str, dict[int, pd.Period]]:
    """`(inventory, scan) -> date`, from each date region's own text. Session id never consulted."""
    anchors: dict[str, dict[int, pd.Period]] = defaultdict(dict)
    for row in load(REGION_DATASET):
        if row.get("record_type") != "region" or row.get("region_class") != "date":
            continue
        reading = read_heading(row["text"], row["inventory"])
        if None in (reading["day"], reading["month"], reading["year"]):
            continue
        try:
            date = pd.Period(
                year=reading["year"], month=reading["month"], day=reading["day"], freq="D"
            )
        except ValueError:
            continue
        # Internal consistency: the heading's own weekday must match its own numeral. A property
        # of the page, independent of any label (plans/SEQUENCE_ALIGNMENT_TRACK.md 2026-10-06).
        if reading["weekday"] is not None and date.dayofweek != reading["weekday"]:
            continue
        # Scope bar, at the source: nothing after the XML baseline's last date (user, 2026-09-25,
        # FULL STOP 2026-10-08). See scripts/corpus_scope.py.
        if not in_scope(date):
            continue
        scan = int(str(row["scan_id"]).split("_")[-1])
        anchors[row["inventory"]].setdefault(scan, date)
    return anchors


def calendar() -> tuple[dict[str, int], set[str]]:
    """`k_e` per date, and the dates the edition records as nihil actum (no sitting)."""
    k_e: dict[str, int] = defaultdict(int)
    text: dict[str, str] = defaultdict(str)
    for record in load("enriched_resolutions_1626_1630"):
        date = str(record.get("date"))[:10]
        k_e[date] += 1
        text[date] += " " + str(record.get("text") or "")
    return k_e, {d for d, t in text.items() if is_nihil_actum(t)}


def main() -> None:
    anchors = scan_date_anchors()
    k_e, nihil = calendar()

    rows: list[dict[str, Any]] = []
    for inventory, by_scan in anchors.items():
        points = sorted(by_scan.items())
        for (scan_a, date_a), (scan_b, date_b) in zip(points, points[1:]):
            room = scan_b - scan_a
            span = (date_b - date_a).n
            if room <= 0 or span <= 0:
                continue
            days = list(pd.period_range(date_a, date_b - 1, freq="D"))
            sitting = sum(1 for d in days if str(d) not in nihil)
            rows.append({
                "record_type": "bracket",
                "inventory": inventory,
                "from_scan": scan_a,
                "to_scan": scan_b,
                "from_date": str(date_a),
                "to_date": str(date_b),
                "room_scans": room,
                "calendar_days": len(days),
                "sitting_days": sitting,
                "nihil_days": len(days) - sitting,
                "k_e": sum(k_e.get(str(d), 0) for d in days),
            })

    frame = pd.DataFrame(rows)
    core = frame[(frame["room_scans"] <= CORE_MAX_ROOM) & (frame["calendar_days"] <= CORE_MAX_DAYS)]
    design = np.c_[np.ones(len(core)), core["sitting_days"].values, core["k_e"].values]
    beta = np.linalg.lstsq(design, core["room_scans"].values, rcond=None)[0]
    residual_core = core["room_scans"].values - design @ beta

    full = np.c_[np.ones(len(frame)), frame["sitting_days"].values, frame["k_e"].values]
    frame["predicted_scans"] = (full @ beta).round(2)
    frame["residual_scans"] = (frame["room_scans"] - frame["predicted_scans"]).round(2)
    frame["bracket_type"] = np.where(
        frame["residual_scans"].abs() <= FIT_TOLERANCE, "fits",
        np.where(frame["residual_scans"] > FIT_TOLERANCE,
                 "more_room_than_business", "less_room_than_business"),
    )
    frame["in_core"] = (frame["room_scans"] <= CORE_MAX_ROOM) & (frame["calendar_days"] <= CORE_MAX_DAYS)

    counts = frame["bracket_type"].value_counts().to_dict()
    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Brackets between consecutive scan->date anchors: physical room against the business "
            "the XML calendar requires. The comparison happens inside the bracket because that is "
            "the only place the physical and logical layers are both constrained."
        ),
        "parent_datasets": [REGION_DATASET, "enriched_resolutions_1626_1630"],
        **scope_meta(),
        "implicit_end_principle": (
            "Sessions and resolutions never explicitly end; they end when the next one begins "
            "(user, 2026-10-08). So an end is not missing data -- every start claims forward to "
            "the next start. The bracket is therefore the natural unit, no scan between two "
            "anchors is ever unclaimed, and a bracket cannot be compressed: room < predicted "
            "means non-contiguous anchors, absent pages or a wrong anchor, never squeezed business."
        ),
        "anchors": sum(len(v) for v in anchors.values()),
        "brackets": len(frame),
        "span_model": {
            "form": "room_scans ~ intercept + b_day*sitting_days + b_res*k_e",
            "intercept": round(float(beta[0]), 3),
            "scans_per_sitting_day": round(float(beta[1]), 3),
            "scans_per_resolution": round(float(beta[2]), 4),
            "fitted_on_core_brackets": len(core),
            "core_mae_scans": round(float(np.abs(residual_core).mean()), 3),
            "core_residual_sd": round(float(residual_core.std()), 3),
            "reading": (
                "A sitting DAY costs ~1.3 scans almost regardless of how much business it holds, "
                "while a resolution adds ~0.04 (about 28 resolutions to a scan). A k_e-only fit "
                "overstates k_e's role because most of what it captured was 'more days means more "
                "resolutions'. The model NARROWS a bracket and never determines it: residual sd "
                "~2 scans against a median bracket of 3, so it is a resolver inside a bracket, "
                "never a global detector."
            ),
        },
        "bracket_type_counts": counts,
        "fit_tolerance_scans": FIT_TOLERANCE,
    }

    records = [meta] + frame.to_dict(orient="records")
    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(frame):,} brackets ({meta['anchors']:,} anchors) to {path}")
    print(f"  room ~ {beta[0]:.2f} + {beta[1]:.3f}*sitting_days + {beta[2]:.3f}*k_e"
          f"   (core MAE {np.abs(residual_core).mean():.2f}, sd {residual_core.std():.2f})")
    for name, n in counts.items():
        print(f"    {name:<26}{n:>5}")
    print("\n  biggest MORE-room brackets -- where to look for an unread heading:")
    cols = ["inventory", "from_scan", "to_scan", "from_date", "to_date",
            "room_scans", "sitting_days", "k_e", "predicted_scans", "residual_scans"]
    print(frame.nlargest(6, "residual_scans")[cols].to_string(index=False))


if __name__ == "__main__":
    main()

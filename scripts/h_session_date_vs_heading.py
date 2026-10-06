#!/usr/bin/env python3
"""Check every session's recorded date against the date its own page states.

Possible only since `session_region_text_1626_1630` ingested the `date`-class regions the
corpus had never imported (1,275 of 1,316 sessions carry one). Before that the headings were
absent and this channel looked weak: 23 of 24 "no signal" on the contested dates, 25 of 67
decided on duplicate sessions.

Four error sources, and the point of the design is that they leave different signatures.
Three were established by the user reading manuscript images on 2026-10-06, each on a named
session; the fourth is the user's caution that the page is not infallible either.

1. **Our correction.** Heading internally consistent and disagreeing with our label.
   `session-3185-num-98`: `Mercurij den xxen. Maij 1626`, Wednesday the 20th, and
   1626-05-20 is a Wednesday, against our label of 30 May -- which would be a Saturday. The
   page's weekday pins the physical day, so our label is simply wrong.
2. **HTR.** A dropped stroke. `session-3185-num-72` carries three consecutive sittings and
   the HTR read `Luna den xijen` (12) for Monday the 13th and `Martis den xiijen` (13) for
   Tuesday the 14th -- one stroke short each time -- while reading both weekdays correctly.
   Hence the rule below: **where numeral and weekday disagree, the weekday wins**, because it
   is the constraint HTR got right in every verified case.
3. **Calendar style.** Heading equals our label plus the 10-day Julian-Gregorian offset *and
   the weekday agrees*, meaning both name the same physical day. `session-3189-num-77`:
   page `sabbathi den 6 Aprilis 1630`, our label 27 March, and Julian 27 March 1630 is
   Gregorian 6 April 1630 -- a Saturday either way. Our label is Old Style, not wrong. The
   weekday is what separates this from (1): at `session-3185-num-98` a style difference would
   have preserved the weekday and did not.
4. **The clerk** (user, 2026-10-06: "occasionally the clerk makes mistakes as well"). An
   internally *inconsistent* heading is the visible case. The invisible case -- a consistent
   but wrong date -- cannot be detected here at all, so **internal consistency is reported as
   strong evidence and never as proof.** It matters most at a one-day disagreement, where a
   clerk slip and an edition slip are indistinguishable: `session-3186-num-178` reads
   `martis den xxviijen septembris 1627` (Tuesday the 28th, and 1627-09-28 is a Tuesday)
   against an enriched date of 27 September.

Also detected, not assumed: a session carrying **several** day headings is a multi-day block,
which is the "sessions as anchors, not containers" hypothesis. `session-3185-num-72` holds 13,
14 and 15 April 1626 on one page.

Diagnostic only: reports verdicts, changes no placement. Verdict classes are fixed here
before the run.

Usage:
    uv run python scripts/h_session_date_vs_heading.py
    uv run python scripts/h_session_date_vs_heading.py --max-numeral-slip 2
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.s6_duplicate_session_date_headings import (
    DAY_TOKENS,
    MONTH_TOKENS,
    WEEKDAY_LOOKUP,
    parse_day_token,
)

OUTPUT_DATASET = "h_session_date_vs_heading"
REGION_DATASET = "session_region_text_1626_1630"
JULIAN_OFFSET = 10  # Julian-Gregorian gap for the whole 1626-1630 window

BACK_REFERENCE = re.compile(r"qui\s+heri|praesentibus\s+qui", re.IGNORECASE)

# Local additions to REPUBLIC's copied weekday table, kept separate rather than edited into
# `_republic_date_vocab.py` so a later sync cannot silently revert them or make them look
# like REPUBLIC's own. `mercuri`/`mercurii` are standard Latin spellings absent from the
# copied set (which has only `mercurij`, `mercury`); `duna` is HTR for `luna`.
LOCAL_WEEKDAYS = {"mercuri": 2, "mercurii": 2, "duna": 0, "jouis": 3, "sabbati": 5}

MONTH_BY_TOKEN = {
    token.lower(): month for month, tokens in MONTH_TOKENS.items() for token in tokens
}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

VERDICTS = (
    "agrees",                 # heading and our label name the same day
    "our_date_wrong",         # heading internally consistent, disagrees with our label
    "old_style_label",        # heading == our label + Julian offset, weekday agrees
    "heading_inconsistent",   # numeral and weekday contradict -- clerk or HTR
    "multi_day_block",        # several distinct day headings in one session
    "unreadable",             # no heading, or no day and no weekday recoverable
)


def read_heading(text: str) -> dict[str, Any]:
    """Day, month and weekday as the page states them, each independently.

    The weekday is taken from the token preceding the day phrase and is kept even when the
    numeral is unreadable, because it is the constraint HTR gets right.
    """
    lowered = " " + re.sub(r"[^a-z0-9 .]", " ", text.lower()) + " "
    weekday = None
    for name, index in {**WEEKDAY_LOOKUP, **LOCAL_WEEKDAYS}.items():
        if f" {name}" in lowered:
            weekday = index
            break
    month = next((m for token, m in MONTH_BY_TOKEN.items() if f" {token.lower()}" in lowered), None)
    day = None
    for token in re.split(r"\s+", text.strip()):
        parsed = parse_day_token(token)
        if parsed is not None:
            day = parsed
            break
    year = None
    match = re.search(r"\b(16[23]\d)\b", text)
    if match:
        year = int(match.group(1))
    return {"day": day, "month": month, "weekday": weekday, "year": year,
            "back_reference": bool(BACK_REFERENCE.search(text))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-numeral-slip", type=int, default=2,
                        help="how far a weekday may move a contradicted numeral (dropped strokes)")
    args = parser.parse_args()

    print(__doc__.split("Usage:")[0].rstrip())
    print(f"\nverdict classes, fixed before the run: {', '.join(VERDICTS)}")
    print(f"weekday-over-numeral tolerance: +/-{args.max_numeral_slip} days\n")

    regions = [
        row for row in load(REGION_DATASET)
        if isinstance(row, dict) and row.get("record_type") == "region"
        and row.get("region_class") == "date" and row.get("has_letters")
    ]
    # Session's own date comes from the flat id's session, read off the axis.
    axis = load("paragraph_axis_1626_1630")
    recorded: dict[str, str] = {}
    for record in axis:
        session = str(record["flat_id"]).rsplit("-resolution-", 1)[0]
        recorded.setdefault(session, str(record["date"])[:10])

    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in regions:
        by_session.setdefault(row["session_id"], []).append(row)
    for rows in by_session.values():
        rows.sort(key=lambda r: (str(r["scan_id"]), r["reading_order"] or 0))

    out: list[dict[str, Any]] = []
    for session, rows in sorted(by_session.items()):
        ours = recorded.get(session)
        if not ours:
            continue
        ours_period = pd.Period(ours, freq="D")

        readings = [read_heading(r["text"]) for r in rows]
        distinct_days = {r["day"] for r in readings if r["day"] is not None}
        opening = readings[0]

        day, weekday = opening["day"], opening["weekday"]
        month = opening["month"] or ours_period.month
        year = opening["year"] if opening["year"] in (ours_period.year,) else ours_period.year

        stated: pd.Period | None = None
        weekday_corrected = False
        if day is not None:
            try:
                stated = pd.Period(f"{year}-{month:02d}-{day:02d}", freq="D")
            except ValueError:
                stated = None
        if stated is not None and weekday is not None and stated.dayofweek != weekday:
            # The weekday wins: search a small window for the date it names. HTR dropped a
            # single stroke in every verified case, so the true day is near the read one.
            for delta in range(1, args.max_numeral_slip + 1):
                for candidate in (stated + delta, stated - delta):
                    if candidate.dayofweek == weekday and candidate.month == month:
                        stated, weekday_corrected = candidate, True
                        break
                if weekday_corrected:
                    break
        if stated is None and weekday is not None:
            # No numeral at all: the weekday alone pins a date if only one nearby day fits.
            near = [ours_period + d for d in range(-14, 15) if (ours_period + d).dayofweek == weekday]
            if len(near) == 1:
                stated, weekday_corrected = near[0], True

        if opening["back_reference"] and stated is not None:
            stated = stated + 1

        if stated is None:
            verdict = "unreadable"
        elif len(distinct_days) > 1:
            verdict = "multi_day_block"
        elif stated == ours_period:
            verdict = "agrees"
        elif (ours_period + JULIAN_OFFSET) == stated and stated.dayofweek == (weekday if weekday is not None else stated.dayofweek):
            verdict = "old_style_label"
        elif weekday is not None and stated.dayofweek != weekday:
            verdict = "heading_inconsistent"
        else:
            verdict = "our_date_wrong"

        out.append({
            "record_type": "session",
            "session_id": session,
            "inventory": rows[0]["inventory"],
            "recorded_date": ours,
            "heading_text": rows[0]["text"][:160],
            "n_date_regions": len(rows),
            "distinct_days_stated": sorted(d for d in distinct_days),
            "stated_date": None if stated is None else str(stated),
            "stated_weekday": None if weekday is None else WEEKDAYS[weekday],
            "offset_days": None if stated is None else int((stated - ours_period).n),
            "weekday_corrected_numeral": weekday_corrected,
            "back_reference": opening["back_reference"],
            "verdict": verdict,
        })

    counts = Counter(r["verdict"] for r in out)
    print(f"sessions with a readable date region: {len(out):,}\n")
    for name in VERDICTS:
        if counts.get(name):
            print(f"  {name:<22}{counts[name]:>6}")
    disagree = [r for r in out if r["verdict"] in ("our_date_wrong", "old_style_label")]
    print(f"\noffsets where heading and label disagree ({len(disagree)} sessions):")
    print("  ", dict(sorted(Counter(r["offset_days"] for r in disagree).items())))
    print(f"  weekday corrected a contradicted numeral in {sum(1 for r in out if r['weekday_corrected_numeral']):,} sessions")
    print(f"  back-reference (`qui heri`) headings: {sum(1 for r in out if r['back_reference']):,}")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "verdict_classes": list(VERDICTS),
        "verdict_counts": dict(counts),
        "sessions_checked": len(out),
        "julian_offset_days": JULIAN_OFFSET,
        "max_numeral_slip": args.max_numeral_slip,
        "local_weekday_additions": sorted(LOCAL_WEEKDAYS),
        "caveat": (
            "Internal consistency of a heading is strong evidence, never proof: a clerk may "
            "write a consistent but wrong date, which this check cannot detect. Matters most "
            "at one-day disagreements."
        ),
    }
    path = save_semi_structured([meta, *out], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()

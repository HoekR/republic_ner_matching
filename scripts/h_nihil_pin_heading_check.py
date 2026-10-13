#!/usr/bin/env python3
"""CONFIRM ON THE PAGE: the 34 XML-literal-nihil dates with a `T`/`E`-status HTR pin anyway.

`scripts/h_xml_nihil_vs_feast_calendar.py` found 34 dates where the enriched edition's own XML
reads only "Nihil Actum[: reason]." in full, yet `s4_day_status_resolution.py`'s ledger status
`E` ("one direct exact-date HTR session candidate") pins a real, substantial HTR session to that
exact date anyway (680 paragraphs / 354,154 chars total) -- because `T`/`E` rows bypass the nihil
check entirely. `docs/writeup_mechanism_anchors.md` flagged this as "a strong candidate instance
of the same heuristic-drift problem... not yet confirmed on the page" (user, 2026-10-07).

This script confirms it the way the project already confirms headings elsewhere (non-circular:
compare the session's OWN embedded heading against the enriched date, never against this
corpus's own derived `session_date`): pull each of the 34 sessions' opening `date`-class region
from `session_region_text_1626_1630` (already-ingested ES text, no live query) and parse it
directly -- weekday, day, month, year -- using the same vocabulary and exact-lookup day parser
`s6_duplicate_session_date_headings.parse_day_token` already uses, plus the same `qui heri`
back-reference shift and weekday-internal-consistency check already established as non-circular
(`plans/archive/SEQUENCE_ALIGNMENT_TRACK.md` 2026-10-06, "A non-circular rate does exist").

Verdict per session:
  confirms_pin     heading's own date == the exact-date pin (edition likely omitted real
                    business on a day it also labelled Nihil Actum -- not drift)
  contradicts_pin   heading names a different, weekday-consistent date (supports drift: the
                    ledger's exact-date match pinned a session to the wrong calendar day)
  inconsistent      heading found but its own day number and weekday disagree -- not usable
  no_signal         no parseable heading in this session's date regions

Diagnostic only: no placement change, no production code touched.

Usage:
    uv run python scripts/h_nihil_pin_heading_check.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from running_axis.axis import RunningAxis
from scripts._republic_date_vocab import MONTH_NAMES, WEEKDAY_NAMES
from scripts.s6_duplicate_session_date_headings import parse_day_token

NIHIL_AUDIT_DATASET = "h_xml_nihil_vs_feast_calendar"
REGION_DATASET = "session_region_text_1626_1630"
OUTPUT_DATASET = "h_nihil_pin_heading_check"

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_LOOKUP = {name.lower(): index for name, index in WEEKDAY_NAMES.items()}
MONTH_LOOKUP = {name.lower(): index for name, index in MONTH_NAMES.items()}
YEAR_RE = re.compile(r"\b1[5-7]\d{2}\b")
TOKEN_RE = re.compile(r"[A-Za-z]+\.?|\d+\.?")

# Names YESTERDAY's sitting -- shift the parsed date one day forward (same rule as
# h_weekday_date_attribution.py, from the user's manuscript reading 2026-10-06).
BACK_REFERENCE = re.compile(r"qui\s+heri|praesentibus\s+qui", re.IGNORECASE)


def parse_heading(text: str) -> dict[str, Any]:
    """Weekday/day/month/year off one heading's own text, exact lookup not fuzzy search."""
    weekday = day = month = None
    for token in TOKEN_RE.findall(text):
        clean = token.strip(".")
        low = clean.lower()
        if weekday is None and low in WEEKDAY_LOOKUP:
            weekday = WEEKDAY_LOOKUP[low]
            continue
        if month is None and low in MONTH_LOOKUP:
            month = MONTH_LOOKUP[low]
            continue
        if day is None:
            parsed = parse_day_token(token)
            if parsed is not None:
                day = parsed
    year_match = YEAR_RE.search(text)
    year = int(year_match.group()) if year_match else None
    return {"weekday": weekday, "day": day, "month": month, "year": year}


def resolve_period(parsed: dict[str, Any]) -> pd.Period | None:
    """Turn a parsed day/month/year into a real date. `day` 0/-1 are REPUBLIC's "lesten"/
    "naestlesten" -- last and second-to-last day of the month, resolved via the month's own
    length rather than a literal number."""
    month, year = parsed["month"], parsed["year"]
    day = parsed["day"]
    if month is None or year is None or day is None:
        return None
    if day <= 0:
        last_day = (pd.Period(year=year, month=month, day=1, freq="D") + 1).asfreq("M").end_time.day
        day = last_day + day  # day=0 -> last_day, day=-1 -> last_day-1
    try:
        return pd.Period(year=year, month=month, day=day, freq="D")
    except ValueError:
        return None


def session_date_regions() -> dict[str, list[dict[str, Any]]]:
    rows = load(REGION_DATASET)
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("record_type") != "region" or row.get("region_class") != "date":
            continue
        by_session.setdefault(row["session_id"], []).append(row)
    for session_id, regions in by_session.items():
        regions.sort(key=lambda r: (r["scan_id"], r.get("reading_order") or 0))
    return by_session


def main() -> None:
    audit = load(NIHIL_AUDIT_DATASET)
    meta = next(row for row in audit if row.get("record_type") == "meta")
    target_dates: list[str] = meta["xml_nihil_not_in_concordance"]
    print(f"Target dates (XML-literal nihil, not caught by the concordance status): {len(target_dates)}")

    axis = RunningAxis.load()
    by_session = session_date_regions()

    rows: list[dict[str, Any]] = []
    for date in sorted(target_dates):
        state = axis.dates.get(date)
        pinned = pd.Period(date, freq="D")
        session_id = state.resolved_session_id if state else None
        regions = by_session.get(session_id, []) if session_id else []

        best: dict[str, Any] | None = None
        for region in regions:
            text = str(region.get("text") or "")
            if not text:
                continue
            parsed = parse_heading(text)
            back_ref = bool(BACK_REFERENCE.search(text))
            resolved = resolve_period(parsed)
            if back_ref and resolved is not None:
                resolved = resolved + 1
            if resolved is None:
                continue
            weekday_consistent = (
                None if parsed["weekday"] is None else parsed["weekday"] == resolved.dayofweek
            )
            best = {
                "heading_text": text,
                "parsed_date": str(resolved),
                "parsed_weekday": None if parsed["weekday"] is None else WEEKDAYS[parsed["weekday"]],
                "weekday_consistent": weekday_consistent,
                "back_reference": back_ref,
                "offset_days": int((resolved - pinned).n),
            }
            break  # first region with a resolvable date is the session's opening heading

        if best is None:
            verdict = "no_signal"
        elif best["weekday_consistent"] is False:
            verdict = "inconsistent"
        elif best["offset_days"] == 0:
            verdict = "confirms_pin"
        else:
            verdict = "contradicts_pin"

        rows.append({
            "record_type": "case",
            "nihil_date": date,
            "session_id": session_id,
            "paragraph_count": axis.sessions[session_id].paragraph_count if session_id in axis.sessions else None,
            **(best or {"heading_text": None, "parsed_date": None, "parsed_weekday": None,
                        "weekday_consistent": None, "back_reference": None, "offset_days": None}),
            "verdict": verdict,
        })

    print(f"\n{'nihil date':<12}{'session':<22}{'heading':<42}{'parsed':<12}{'off':>5}  verdict")
    for row in rows:
        heading = (row["heading_text"] or "-")[:40]
        print(
            f"{row['nihil_date']:<12}{(row['session_id'] or '-'):<22}{heading:<42}"
            f"{(row['parsed_date'] or '-'):<12}{str(row['offset_days'] if row['offset_days'] is not None else '-'):>5}  "
            f"{row['verdict']}"
        )

    from collections import Counter
    counts = Counter(row["verdict"] for row in rows)
    contradicts = [r for r in rows if r["verdict"] == "contradicts_pin"]
    print("\nVERDICT COUNTS", dict(counts))
    if contradicts:
        offsets = [r["offset_days"] for r in contradicts]
        print(f"contradicts_pin offsets: {sorted(offsets)}")
        print(f"  all negative (heading earlier than the pin, i.e. 'recorded dates run ahead'): "
              f"{sum(1 for o in offsets if o < 0)}/{len(offsets)}")

    meta_out = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Confirms-on-the-page check for the 34 XML-literal-nihil dates with a T/E-status "
            "HTR pin, per docs/writeup_mechanism_anchors.md's 2026-10-07 note. Parses each "
            "session's own opening date-class heading (session_region_text_1626_1630, "
            "already-ingested ES text) directly, non-circularly against the enriched/nihil "
            "date -- never against this corpus's own derived session_date."
        ),
        "parent_datasets": [NIHIL_AUDIT_DATASET, REGION_DATASET, "running_axis_snapshot"],
        "n_targets": len(target_dates),
        "verdict_counts": dict(counts),
    }
    path = save_semi_structured([meta_out, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()

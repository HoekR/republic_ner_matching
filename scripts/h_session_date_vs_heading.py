#!/usr/bin/env python3
"""Check whether each session's opening date heading is internally consistent, then compare it
to the session's recorded date.

**Why this replaced the old script.** The previous version compared the heading's date directly
against our recorded date and reported `our_date_wrong: 610` of 1,140 -- and that number is
CIRCULAR, so it must never be reported. Sampled 6 of 6: the heading's date equals ES's own
uncorrected `metadata.session_date`, because **ES segmented the sessions using those headings in
the first place.** Heading and ES are one witness, not two, so "heading disagrees with our label"
just restates "ES disagrees with our label" under a different name.

**The non-circular substitute.** Internal consistency -- does the heading's stated weekday match
its own stated day numeral under the Gregorian calendar? -- is a property of the manuscript text
alone. It does not reference ES, our correction, or any external authority, so it is not
vulnerable to the circularity above. Only a heading that passes this check is then compared
against our recorded date, and even then the comparison is reported as a source conflict, not as
a verdict on which side is right (see CAVEAT below).

Four error sources, each with a distinct signature, three established by the user reading
manuscript images on 2026-10-06:

1. **Our correction.** Heading internally consistent and disagreeing with our label.
   `session-3185-num-98`: `Mercurij den xxen. Maij 1626` -- Wednesday the 20th, and 1626-05-20
   is in fact a Wednesday -- against our recorded label of 30 May, which would be a Saturday.
   The heading's weekday pins the physical day; our label is the outlier here.
2. **HTR dropping a stroke.** `session-3185-num-72` (scan `NL-HaNA_1.01.02_3185_0123`) carries
   two sittings back to back in one region: `Luna den xijen. Aprilis 1626` (12) for what is
   really Monday the 13th, and, later in the same text, `Martis den xiijen. Aprilis 1626` (13)
   for what is really Tuesday the 14th -- each numeral one stroke short, each weekday read
   correctly. Hence the rule below: **where numeral and weekday disagree, the weekday wins**,
   because it is the constraint HTR got right in every verified case.
3. **HTR adding a stroke, plus an L/D confusion.** `session-3186-num-148`: `Duna den xvijen.
   Augusti 1627`. `Duna` is HTR's L/D misread of `Luna` (Monday) -- already carried as a LOCAL
   weekday variant below -- and the numeral `xvijen` (17) has one stroke more than `xvien` (16):
   16 August 1627 is the Monday, 17 August a Tuesday. The same weekday-wins correction that
   fixes source 2's dropped strokes fixes this added one, in the other direction.
4. **The clerk's own slip.** Same session and scan as source 2 -- `session-3185-num-72`, scan
   `0123` -- but the *second* phrase in that text, read on its own: `Martis den xiijen.
   Aprilis 1626` taken literally names the 13th, and 13 April 1626 was a Monday, not a Tuesday.
   Read this way the numeral is correct and the weekday word is the clerk's mistake, which is
   the mirror image of source 2's reading of the very same words (numeral wrong, weekday
   right). Both readings are internally self-consistent; nothing in the text says which is
   the error. **That is the caveat, made concrete:** a one-day weekday/numeral disagreement
   is strong evidence for "HTR dropped a stroke," never proof, because "the clerk misnamed the
   weekday" explains the identical text equally well. This check cannot tell the two apart, so
   it matters most exactly where it is applied here -- at one-day disagreements.

**CAVEAT, stated once and binding throughout:** internal consistency is strong evidence that a
heading names the day it claims to, and it is never proof -- a clerk can write a fully consistent
but wrong date, which this check cannot detect by construction. It is strongest evidence at
one-day disagreements and weakest (see source 4) at exactly the same place.

**What this script does NOT claim.** A `disagrees` verdict does not mean our recorded date is
wrong. What the historical date-correction pipeline based its label on is not established here;
if it rests on some external authority independent of the heading, then a `disagrees` row is a
conflict between that authority and the manuscript's own heading, not a finding that either side
is wrong. Report it as a source conflict.

Verdict classes, fixed here before the run:

* `agrees`               -- heading internally consistent AND names the recorded date
* `disagrees`            -- heading internally consistent AND names a different date
* `heading_inconsistent` -- weekday and day numeral contradict each other even after the
                            weekday-wins numeral-slip search (HTR slip or clerk slip, source
                            unknown)
* `back_reference`       -- heading matched by `qui heri` / `praesentibus qui`: the formula
                            names YESTERDAY's sitting, so the session itself is the day after.
                            Excluded from `agrees`/`disagrees` on principle, not folded in.
* `unreadable`           -- weekday, day numeral, month or year could not be parsed from the
                            heading text at all

Diagnostic only: reports verdicts, changes no placement.

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
    MONTH_TOKENS,
    WEEKDAY_LOOKUP,
    parse_day_token,
)

OUTPUT_DATASET = "h_session_date_vs_heading"
REGION_DATASET = "session_region_text_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"

BACK_REFERENCE = re.compile(r"qui\s+heri|praesentibus\s+qui", re.IGNORECASE)

# Local additions to REPUBLIC's copied weekday table (`scripts/_republic_date_vocab.py`), kept
# here rather than edited into that file so a later sync of the copied table cannot silently
# revert them or make them look like REPUBLIC's own. `mercuri`/`mercurii` are standard Latin
# spellings absent from the copied set (which has only `Mercurij`/`Mercury`); `duna` is HTR's
# L/D confusion for `luna` (source 3 above); `jouis` is an HTR variant of `Jovis`; `sabbati` is
# a single-`b` spelling distinct from the copied `Sabati`/`Sabbathi`; `lunae` duplicates the
# copied table's own `Lunae` and is kept anyway so this LOCAL set is the complete, self-standing
# list rather than one that silently depends on what the copy happens to contain.
LOCAL_WEEKDAYS = {"mercuri": 2, "mercurii": 2, "duna": 0, "jouis": 3, "sabbati": 5, "lunae": 0}

MONTH_BY_TOKEN = {
    token.lower(): month for month, tokens in MONTH_TOKENS.items() for token in tokens
}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

VERDICTS = (
    "agrees",                 # heading consistent, names the recorded date
    "disagrees",              # heading consistent, names a different date
    "heading_inconsistent",   # numeral and weekday contradict even after correction
    "back_reference",         # "qui heri" names yesterday; excluded from agrees/disagrees
    "unreadable",             # weekday, day, month or year could not be parsed
)


def read_heading(text: str) -> dict[str, Any]:
    """Day, month, year and weekday as the page states them, each parsed independently.

    No field ever falls back to a substituted value here -- that is left to the caller, which
    must turn any unparseable field into `unreadable` rather than manufacture a date the page
    never states (the two bugs this script replaces: a month silently borrowed from the
    recorded date, and a year forced to the recorded date's year whenever they disagreed).
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
    return {
        "day": day, "month": month, "weekday": weekday, "year": year,
        "back_reference": bool(BACK_REFERENCE.search(text)),
    }


def classify_heading(text: str, ours: pd.Period, max_numeral_slip: int) -> dict[str, Any]:
    """Verdict for one session's opening heading against its recorded date.

    An unparseable weekday, day, month or year yields `unreadable` directly -- never a
    substituted value. Only once all four parse and combine into a valid calendar date does
    internal consistency get checked at all.
    """
    reading = read_heading(text)
    day, month, year, weekday = reading["day"], reading["month"], reading["year"], reading["weekday"]
    back_reference = reading["back_reference"]
    base = {
        "stated": None, "weekday": weekday, "weekday_corrected_numeral": False,
        "back_reference": back_reference,
    }

    if day is None or month is None or year is None or weekday is None:
        return {**base, "verdict": "unreadable"}

    try:
        stated = pd.Period(f"{year}-{month:02d}-{day:02d}", freq="D")
    except ValueError:
        return {**base, "verdict": "unreadable"}

    weekday_corrected = False
    if stated.dayofweek != weekday:
        # The weekday wins: HTR got it right in every verified case (sources 2 and 3 above),
        # whether it dropped a stroke from the numeral or added one. Search a small symmetric
        # window within the same month for the date whose weekday matches.
        corrected = None
        for delta in range(1, max_numeral_slip + 1):
            for candidate in (stated + delta, stated - delta):
                if candidate.month == month and candidate.dayofweek == weekday:
                    corrected = candidate
                    break
            if corrected is not None:
                break
        if corrected is not None:
            stated, weekday_corrected = corrected, True
        else:
            return {**base, "stated": stated, "verdict": "heading_inconsistent"}

    if back_reference:
        # Names YESTERDAY's sitting; the session itself is the day after. Excluded from
        # agrees/disagrees regardless of how well it would otherwise match.
        stated = stated + 1
        return {
            **base, "stated": stated, "weekday_corrected_numeral": weekday_corrected,
            "verdict": "back_reference",
        }

    verdict = "agrees" if stated == ours else "disagrees"
    return {
        **base, "stated": stated, "weekday_corrected_numeral": weekday_corrected,
        "verdict": verdict,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-numeral-slip", type=int, default=2,
                        help="how far a weekday may move a contradicted numeral (dropped/added strokes)")
    args = parser.parse_args()

    print(__doc__.split("Usage:")[0].rstrip())
    print(f"\nverdict classes, fixed before the run: {', '.join(VERDICTS)}")
    print(f"weekday-over-numeral tolerance: +/-{args.max_numeral_slip} days\n")

    regions = [
        row for row in load(REGION_DATASET)
        if isinstance(row, dict) and row.get("record_type") == "region"
        and row.get("region_class") == "date"
    ]
    # Session's own recorded date comes from the flat axis, not from any ES heading -- this is
    # what keeps the comparison non-circular.
    axis = load(AXIS_DATASET)
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
        opening = rows[0]

        result = classify_heading(opening["text"], ours_period, args.max_numeral_slip)
        stated = result["stated"]

        out.append({
            "record_type": "session",
            "session_id": session,
            "inventory": opening["inventory"],
            "recorded_date": ours,
            "heading_text": opening["text"][:160],
            "n_date_regions": len(rows),
            "stated_date": None if stated is None else str(stated),
            "stated_weekday": None if result["weekday"] is None else WEEKDAYS[result["weekday"]],
            "recorded_weekday": WEEKDAYS[ours_period.dayofweek],
            "offset_days": None if stated is None else int((stated - ours_period).n),
            "weekday_corrected_numeral": result["weekday_corrected_numeral"],
            "back_reference": result["back_reference"],
            "verdict": result["verdict"],
        })

    counts = Counter(r["verdict"] for r in out)
    print(f"sessions with a readable date heading: {len(out):,}\n")
    for name in VERDICTS:
        print(f"  {name:<22}{counts.get(name, 0):>6}")

    decidable = [r for r in out if r["verdict"] in ("agrees", "disagrees")]
    disagrees = [r for r in out if r["verdict"] == "disagrees"]
    if decidable:
        print(
            f"\ndecidable (agrees + disagrees): {len(decidable):,}; "
            f"disagrees share: {len(disagrees) / len(decidable):.1%}"
        )
    offset_counts = dict(sorted(Counter(r["offset_days"] for r in disagrees).items()))
    print(f"\noffsets where heading and label disagree ({len(disagrees)} sessions):")
    print("  ", offset_counts)
    print(f"  weekday corrected a contradicted numeral in "
          f"{sum(1 for r in out if r['weekday_corrected_numeral']):,} sessions")
    print(f"  back-reference (`qui heri`) headings: {sum(1 for r in out if r['back_reference']):,}")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "verdict_classes": {
            "agrees": "heading internally consistent AND names the recorded date",
            "disagrees": "heading internally consistent AND names a different date",
            "heading_inconsistent": "weekday and day numeral contradict each other even after "
                "the weekday-wins numeral-slip search",
            "back_reference": "heading matched by qui heri / praesentibus qui; names "
                "YESTERDAY's sitting, excluded from agrees/disagrees",
            "unreadable": "weekday, day numeral, month or year could not be parsed",
        },
        "verdict_counts": dict(counts),
        "sessions_checked": len(out),
        "decidable_sessions": len(decidable),
        "disagrees_share_of_decidable": (len(disagrees) / len(decidable)) if decidable else None,
        "offset_distribution_disagrees": {str(k): v for k, v in offset_counts.items()},
        "max_numeral_slip": args.max_numeral_slip,
        "local_weekday_additions": sorted(LOCAL_WEEKDAYS),
        "circularity_finding": (
            "The previous version of this check compared the heading's date directly against "
            "our recorded date and reported our_date_wrong=610/1140. That number is circular "
            "and must not be cited: sampled 6 of 6, the heading's date equals ES's own "
            "uncorrected metadata.session_date, because ES segmented the sessions using those "
            "headings. This version instead requires the heading to be internally consistent "
            "(its stated weekday matches its stated day numeral under the Gregorian calendar) "
            "before comparing it to the recorded date at all."
        ),
        "caveat": (
            "Internal consistency of a heading is strong evidence, never proof: a clerk may "
            "write a consistent but wrong date, which this check cannot detect. It is "
            "strongest at one-day disagreements and weakest there too -- session-3185-num-72 "
            "scan 0123 shows the same ambiguous text supporting either 'HTR dropped a stroke' "
            "(numeral wrong, weekday right) or 'the clerk misnamed the weekday' (numeral "
            "right, weekday wrong) with nothing in the page itself to decide between them."
        ),
        "not_a_claim": (
            "A disagrees verdict does not show that our recorded date is wrong. What the "
            "historical date-correction pipeline based its label on is not established here; "
            "if it rests on an external authority independent of the heading, a disagrees row "
            "is a conflict between that authority and the manuscript's own heading, not a "
            "finding that either side is incorrect."
        ),
    }
    path = save_semi_structured(
        [meta, *out],
        logical_name=OUTPUT_DATASET,
        parent_sources=[REGION_DATASET, AXIS_DATASET],
        description=(
            "Non-circular internal-consistency check of each session's opening date heading "
            "against its recorded date; supersedes the circular heading-vs-recorded comparison."
        ),
        script=__file__,
    )
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()

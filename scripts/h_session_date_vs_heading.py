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

**Which side is heuristic.** `paragraph_axis_1626_1630`'s recorded session date comes from this
corpus's own REPUBLIC-derived date-correction heuristics, segmented and labelled HTR session by
HTR session. The enriched edition's source XML, by contrast, is normative for the CALENDAR: it
records every day in sequence, including non-session days as `nihil actum`, so it cannot itself
drop or duplicate a day the way a per-session heuristic can. Put plainly: the XML day sequence is
normative, the recorded HTR session date is heuristic, and where the two disagree the heuristic
is the suspect party by construction -- not proven wrong, but the one without the calendar's own
backing.

**Conditional on legibility, not on outcome.** `unreadable` and `heading_inconsistent` sessions
are excluded from the decidable pool below, and nothing here shows they behave like the sessions
that DO parse. That is a real limitation (the rate is only measured where the heading happens to
be legible), but it is a limitation on COVERAGE, not on validity: readability is checked before
the recorded date is ever consulted, so excluding on it does not select for agreement or
disagreement the way the old circular check did. That is what makes this rate usable where the
old `our_date_wrong=610` was not.

Verdict classes, fixed here before the run:

* `agrees`               -- heading internally consistent AND names the recorded date
* `disagrees`            -- heading internally consistent AND names a different date
* `heading_inconsistent` -- weekday and day numeral contradict each other even after the
                            weekday-wins numeral-slip search (HTR slip or clerk slip, source
                            unknown)
* `unreadable`           -- weekday, day numeral, month or year could not be parsed from the
                            heading text at all

`has_attendance_formula` (`qui heri` / `praesentibus qui`) is tracked as a boolean FLAG on each
row, not a verdict -- see `has_attendance_formula()` below for why a +1-day dating rule was
proposed, withdrawn, and finally left as an open question rather than resolved either way.

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
from scripts.corpus_scope import in_scope, scope_meta
from scripts.s6_duplicate_session_date_headings import (
    MONTH_TOKENS,
    WEEKDAY_LOOKUP,
    parse_day_token,
)

OUTPUT_DATASET = "h_session_date_vs_heading"
REGION_DATASET = "session_region_text_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"

# The five annual `ordinaris` registers each hold exactly one calendar year's sessions
# (plans/SEQUENCE_ALIGNMENT_TRACK.md 2026-10-06/07: "volumes are annual", the constraint flagged
# as not-yet-applied). 4562/4861 are the secret series and span many years, so they get no
# nominal-year check at all. A parsed year outside [nominal-1, nominal+1] -- the +/-1 tolerance
# covers a genuine year-boundary session carrying the adjacent year -- is OCR/HTR digit noise,
# not data: this is what was producing decade-scale "offsets" like the regression case below.
INVENTORY_NOMINAL_YEAR = {"3185": 1626, "3186": 1627, "3187": 1628, "3188": 1629, "3189": 1630}

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
ALL_WEEKDAY_TOKENS = {**WEEKDAY_LOOKUP, **LOCAL_WEEKDAYS}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# A region's text is not always a single heading: multi-day blocks and attendance lists put
# several weekday/month/year tokens in one blob (e.g. a Sunday "Nihil Actum" notice followed
# by the next day's own heading, or an attendee surname that happens to contain a month
# token). Matching each field independently and taking "the first occurrence of each kind
# anywhere in the text" lets fields from DIFFERENT date mentions get stitched together into a
# date nobody wrote -- the structural cause of this script's wrong-year outliers (e.g. day/
# weekday from one date, year from another, hundreds or thousands of days apart). This single
# structured pattern instead requires weekday, "den", day, month and year to co-occur in that
# order within one short span, so a match is always one coherent date statement; if the FIRST
# date mention in the text does not fit the pattern (e.g. a mangled month spelling such as
# "Juni" where the vocabulary only has "Junij"/"Juny"), the regex engine naturally advances to
# the next weekday occurrence rather than fabricating a date from mismatched fields.
_WEEKDAY_ALT = "|".join(re.escape(token) for token in ALL_WEEKDAY_TOKENS)
_MONTH_ALT = "|".join(re.escape(token) for token in MONTH_BY_TOKEN)
DATE_PHRASE = re.compile(
    rf"\b(?P<weekday>{_WEEKDAY_ALT})\b[^a-zA-Z0-9]{{0,3}}den\b\s+"
    rf"(?P<day>[a-zA-Z0-9]+)\.?\s*"
    rf"\b(?P<month>{_MONTH_ALT})\b\.?[^\d]{{0,20}}"
    rf"(?P<year>16[23]\d)\b",
    re.IGNORECASE,
)

VERDICTS = (
    "agrees",                 # heading consistent, names the recorded date
    "disagrees",              # heading consistent, names a different date
    "heading_inconsistent",   # numeral and weekday contradict even after correction
    "unreadable",             # weekday, day, month or year could not be parsed
    "stated_out_of_scope",    # heading parses to a date past the corpus scope bar (1630-05-14)
)


def has_attendance_formula(text: str) -> bool:
    """True if the heading carries the `qui heri` / `praesentibus qui` attendance formula.

    **UNSETTLED, not a rule -- left open deliberately (2026-10-06).** Three passes on this
    question landed in three different places: shift the stated date +1 day (named date =
    yesterday's sitting); never shift (the formula is about attendance, not dating); and finally,
    on the user's own caution, that a +1 reading "may still hold in places" even though it does
    not hold everywhere. This function and its column therefore do NOT encode a dating rule --
    they only flag which rows carry the formula, so they stay identifiable and revisitable.

    The default elsewhere in this module is NO SHIFT: classify the session on the date its own
    heading states, unchanged. That default is what the one worked example here supports --
    inventory 3188, scans 0619-0621, four consecutive sessions:

        num-283  "Dominica den 2 Decembris 1629. Nihil Actum" + "Luna den iijen"   -> Sun 2 / Mon 3
        num-284  "Martis den iiijen. Decembris 1629"                               -> Tue 4
        num-285  "Preside et Presentibus qui heri met Mercury den 6en. Decemb"     -> Wed 5 (HTR
                 misread the numeral; the image reads "Mercurii den v")
        num-286  "Preside et Presentibus qui heri met Linden Jovis den vjen"       -> Thu 6

    December 1629: 2nd Sunday, 3rd Monday, 4th Tuesday, 5th Wednesday, 6th Thursday -- every
    heading's own weekday matches its own numeral, and the run is consecutive (2/3, 4, 5, 6) only
    under no-shift; a +1 shift gives 2/3, 4, 6, 7, which skips the 5th. But the user's own caution
    is explicit: this one example does not settle every case, elsewhere the formula may still name
    yesterday's sitting. **Do not generalize past this one test.** Anyone revisiting a disagreement
    on a flagged row should run the same consecutive-sequence check against neighbouring sessions
    before assuming either the no-shift default or a +1 shift; this module deliberately does not
    make that call for them. All verdicts in this run rest on the no-shift default.
    """
    return bool(BACK_REFERENCE.search(text))


def read_heading(text: str, inventory: str | None = None) -> dict[str, Any]:
    """Day, month, year and weekday as the page states them, read as ONE coherent date phrase.

    No field ever falls back to a substituted value here -- that is left to the caller, which
    must turn any unparseable field into `unreadable` rather than manufacture a date the page
    never states (the two bugs this script replaces: a month silently borrowed from the
    recorded date, and a year forced to the recorded date's year whenever they disagreed). Nor
    are the fields searched for independently: `DATE_PHRASE` requires weekday, day, month and
    year to co-occur in the structural order this corpus always uses, so a match can never mix
    fields pulled from two different date mentions in the same region text.

    A parsed year that falls outside its inventory's nominal year +/- 1 (e.g. "1636" or "1619"
    in an inventory 3188/3189 session nominally 1629/1630) is OCR/HTR digit noise on the year
    token specifically, not a real decade-scale date -- fixing the bug `PLAN.md` and
    `plans/SEQUENCE_ALIGNMENT_TRACK.md` (2026-10-07) flagged: "a heading parsed into another
    decade is wrong by construction". It is replaced with the volume's own nominal year, NOT
    with the recorded date's year (`ours`) -- substituting `ours` is the other bug this script
    already rejects elsewhere ("a year forced to the recorded date's year whenever they
    disagreed"), because `ours` is this specific session's own heuristic label, exactly what is
    under test. The nominal year is a structural fact about which physical volume the page sits
    in, independent of any one session's label, so using it is not circular the same way.
    Weekday/day/month still get checked against it below, so a heading whose OTHER fields are
    also wrong still comes out `heading_inconsistent`, not silently `agrees`.
    """
    match = DATE_PHRASE.search(text)
    weekday = ALL_WEEKDAY_TOKENS.get(match.group("weekday").lower()) if match else None
    month = MONTH_BY_TOKEN.get(match.group("month").lower()) if match else None
    day = parse_day_token(match.group("day")) if match else None
    year = int(match.group("year")) if match else None
    nominal = INVENTORY_NOMINAL_YEAR.get(inventory or "")
    year_corrected = year is not None and nominal is not None and abs(year - nominal) > 1
    if year_corrected:
        year = nominal
    return {"day": day, "month": month, "weekday": weekday, "year": year, "year_corrected": year_corrected}


def classify_heading(
    text: str, ours: pd.Period, max_numeral_slip: int, inventory: str | None = None
) -> dict[str, Any]:
    """Verdict for one session's opening heading against its recorded date.

    An unparseable weekday, day, month or year yields `unreadable` directly -- never a
    substituted value. Only once all four parse and combine into a valid calendar date does
    internal consistency get checked at all.
    """
    reading = read_heading(text, inventory)
    day, month, year, weekday = reading["day"], reading["month"], reading["year"], reading["weekday"]
    base = {
        "stated": None, "weekday": weekday, "weekday_corrected_numeral": False,
        "year_corrected_to_nominal": reading["year_corrected"],
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

    # `qui heri` / `praesentibus qui` ("attendance formula") headings are classified the same as
    # any other: no dating shift is applied by default (see `has_attendance_formula()` -- the
    # question of whether such a heading ever names yesterday's sitting is left open, not decided
    # here). The flag is carried on the output row, not folded into this verdict.
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
    out_of_scope = 0
    for session, rows in sorted(by_session.items()):
        ours = recorded.get(session)
        if not ours:
            continue
        # Scope bar (user, 2026-09-25, FULL STOP 2026-10-08): the enriched edition ends
        # 1630-05-14 and the axis runs to 1630-12-31, so a session recorded past the bar has no
        # sitting the edition could record and must not enter this population -- it would sit in
        # the `decidable` denominator behind the cited disagreement rate. See scripts/corpus_scope.
        if not in_scope(ours):
            out_of_scope += 1
            continue
        ours_period = pd.Period(ours, freq="D")
        opening = rows[0]

        result = classify_heading(
            opening["text"], ours_period, args.max_numeral_slip, opening.get("inventory")
        )
        stated = result["stated"]
        # Scope bar applies to the date a heading CLAIMS, not only to the recorded label. A
        # heading parsing to a post-bar date cannot be a date this project reconsiders, so it is
        # not a `disagrees` with a 358-day offset -- that would be a date claim past the bar.
        # The two real cases are session-3188-num-234/235, already named as outliers.
        verdict = result["verdict"]
        if stated is not None and not in_scope(stated):
            verdict = "stated_out_of_scope"

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
            "year_corrected_to_nominal": result["year_corrected_to_nominal"],
            "has_attendance_formula": has_attendance_formula(opening["text"]),
            "verdict": verdict,
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
    year_corrected = [r for r in out if r["year_corrected_to_nominal"]]
    print(f"  year replaced with the volume's nominal year (OCR digit noise) in "
          f"{len(year_corrected):,} sessions; their verdicts: "
          f"{dict(Counter(r['verdict'] for r in year_corrected))}")
    attendance_formula_count = sum(1 for r in out if r["has_attendance_formula"])
    print(f"  attendance-formula (`qui heri`) headings: {attendance_formula_count:,} -- "
          f"flagged only, classified on the no-shift default (see has_attendance_formula())")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "verdict_classes": {
            "agrees": "heading internally consistent AND names the recorded date",
            "disagrees": "heading internally consistent AND names a different date",
            "heading_inconsistent": "weekday and day numeral contradict each other even after "
                "the weekday-wins numeral-slip search",
            "unreadable": "weekday, day numeral, month or year could not be parsed",
        },
        **scope_meta(),
        "sessions_excluded_past_scope_bar": out_of_scope,
        "verdict_counts": dict(counts),
        "sessions_checked": len(out),
        "decidable_sessions": len(decidable),
        "disagrees_share_of_decidable": (len(disagrees) / len(decidable)) if decidable else None,
        "offset_distribution_disagrees": {str(k): v for k, v in offset_counts.items()},
        "max_numeral_slip": args.max_numeral_slip,
        "local_weekday_additions": sorted(LOCAL_WEEKDAYS),
        "attendance_formula": {
            "flagged_rows": attendance_formula_count,
            "note": (
                "`qui heri` / `praesentibus qui` headings are flagged via "
                "has_attendance_formula, not given their own verdict. Whether this formula ever "
                "shifts the named date by one day is UNSETTLED (proposed, then withdrawn, then "
                "left open on the user's own caution -- see has_attendance_formula()'s "
                "docstring). All verdicts above, including for these flagged rows, rest on the "
                "NO-SHIFT default: the session is classified on the date its heading literally "
                "states."
            ),
        },
        "heuristic_vs_normative": (
            "paragraph_axis_1626_1630's recorded session date is produced by this corpus's own "
            "REPUBLIC-derived date-correction heuristics. The enriched edition's source XML is "
            "normative for the calendar sequence (every day recorded, non-session days as "
            "nihil actum). Where heading and recorded date disagree, the recorded date is the "
            "heuristic side and the suspect party by construction -- not proven wrong here."
        ),
        "legibility_conditioning": (
            f"{counts.get('unreadable', 0):,} unreadable and "
            f"{counts.get('heading_inconsistent', 0):,} heading_inconsistent sessions are "
            "excluded from the decidable pool, and nothing here shows they behave like the "
            "sessions that do parse. Readability is checked before the recorded date is ever "
            "consulted, so this exclusion is conditional on legibility, not on outcome -- unlike "
            "the old our_date_wrong=610 figure, which is why this rate is usable and that one "
            "was not."
        ),
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

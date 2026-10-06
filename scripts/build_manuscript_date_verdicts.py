#!/usr/bin/env python3
"""Manuscript date readings, taken off the images by a human. Ground truth.

These are the only date evidence in this project independent of the HTR pipeline. Everything
else -- the axis, `resolutions_flat`, ES `session_date`, the ES `date`-class regions -- derives
from one dump and from the headings themselves, so none of it can arbitrate against our own
corrected dates. Established the hard way on 2026-10-06: the corpus-wide heading check found
610 of 1,140 sessions disagreeing with their recorded date, and in every sampled case the
heading's date equalled ES's own uncorrected `session_date` exactly, because ES segmented the
sessions *using those headings*. One witness counted twice.

So a human reading the page is the arbiter, and these readings are expensive. Recorded here
with what each one settles.

Four error sources, all four now observed:

* **our correction** -- `session-3186-num-148`, page `Luna den xvien Augusti 1627` (Monday the
  16th, and the 16th was a Monday) against a recorded 31 August: 15 days wrong.
* **HTR, bidirectionally** -- the same heading was read `Duna den xvijen` (an L/D confusion,
  and a stroke *added*), while `session-3185-num-72` was read `Luna den xijen` / `Martis den
  xiijen` for the 13th and 14th, strokes *dropped*. Hence a symmetric correction window.
* **a 10-day error, in both directions** -- `session-3189-num-77`, page `sabbathi den 6
  Aprilis 1630` against a recorded 27 March, is 10 days early; `session-3185-num-98`, page
  Wednesday 20 May 1626 against a recorded 30 May, is 10 days late. A calendar-style
  explanation was proposed for the first (Julian 27 March 1630 is Gregorian 6 April 1630, the
  same Saturday) and **withdrawn: the dates in this corpus are always modern style** (user,
  2026-10-06), so neither is an Old Style label. Both are plain errors that happen to be 10
  days. Two hand-verified cases differing by exactly 10 in opposite directions is suggestive
  of a calendar conversion applied somewhere it was not needed, or applied with the sign
  reversed -- recorded here as a hypothesis with no evidence beyond the coincidence, and
  explicitly not a finding.
* **the clerk** -- `session-3185-num-72` scan 0123 reads `martis den xiijen aprilis`: Tuesday
  *the 13th*, but the 13th of April 1626 was a Monday. Read off the paper, so this is the
  clerk's own slip, not the HTR's. It is also the strongest argument for the weekday-beats-
  numeral rule, since here the numeral is wrong on the page itself.

`session-3185-num-72` further carries `Luna` (13th), `Martis` (14th) and, on scan 0125,
`mercurii den xven aprilis 1626` (Wednesday the 15th, internally consistent) -- a multi-day
block, which is the "sessions as anchors, not containers" hypothesis read off the page.

Usage:
    uv run python scripts/build_manuscript_date_verdicts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import save_semi_structured

OUTPUT_DATASET = "manuscript_date_verdicts"
ANNOTATOR = "rik"
READ_ON = "2026-10-06"

# scan -> exactly what the image says, transcribed by the annotator.
VERDICTS = [
    {
        "session_id": "session-3185-num-16",
        "scan_id": "NL-HaNA_1.01.02_3185_0023",
        "heading_as_read": "Praeside et Praesentibus qui heri Martis den xxen. Januarij 1626 excepto Duick",
        "date_named": "1626-01-20",
        "session_date": "1626-01-21",
        "recorded_date": "1626-01-21",
        "enriched_date": "1626-01-20",
        "mechanism": "back_reference",
        "note": "`qui heri` names yesterday's sitting, so the session is the day after the "
                "date named. The recorded date is right here *because of* the formula; a "
                "channel ignoring it dates every such session a day early.",
    },
    {
        "session_id": "session-3185-num-72",
        "scan_id": "NL-HaNA_1.01.02_3185_0123",
        "heading_as_read": "martis den xiijen aprilis 1626",
        "date_named": "1626-04-13",
        "session_date": "1626-04-14",
        "recorded_date": "1626-04-18",
        "enriched_date": "1626-04-14",
        "mechanism": "clerk_error_plus_multi_day",
        "note": "Tuesday the 13th, but 13 April 1626 was a Monday -- the clerk's own slip, "
                "read off the paper. Weekday beats numeral, giving the 14th. HTR read this "
                "`Martis den xiijen` and the preceding `Luna` heading `den xijen`, both one "
                "stroke short.",
    },
    {
        "session_id": "session-3185-num-72",
        "scan_id": "NL-HaNA_1.01.02_3185_0125",
        "heading_as_read": "mercurii den xven aprilis 1626",
        "date_named": "1626-04-15",
        "session_date": "1626-04-15",
        "recorded_date": "1626-04-18",
        "enriched_date": None,
        "mechanism": "multi_day_block",
        "note": "Wednesday the 15th, and the 15th was a Wednesday: internally consistent. A "
                "second sitting in the same session, so the block spans at least 13-15 April.",
    },
    {
        "session_id": "session-3185-num-98",
        "scan_id": "NL-HaNA_1.01.02_3185_0174",
        "heading_as_read": "Heeren Grave, Rantwijck, De Bie, Halewijn, Mercurij den xxen. Maij 1626",
        "date_named": "1626-05-20",
        "session_date": "1626-05-20",
        "recorded_date": "1626-05-30",
        "enriched_date": "1626-05-20",
        "mechanism": "recorded_date_wrong",
        "note": "Wednesday the 20th, and the 20th was a Wednesday. Recorded date 10 days "
                "late; `session-3189-num-77` is 10 days early. Not a calendar-style "
                "difference: this corpus' dates are always modern style, and a style change "
                "would anyway have preserved the weekday, which 30 May (a Saturday) does not.",
    },
    {
        "session_id": "session-3186-num-148",
        "scan_id": "NL-HaNA_1.01.02_3186_0354",
        "heading_as_read": "Luna den xvien Augusti 1627",
        "date_named": "1627-08-16",
        "session_date": "1627-08-16",
        "recorded_date": "1627-08-31",
        "enriched_date": "1627-08-16",
        "mechanism": "recorded_date_wrong",
        "note": "Monday the 16th, and the 16th was a Monday. HTR read `Duna den xvijen`: an "
                "L/D confusion and a stroke *added*, the opposite direction to num-72, so the "
                "numeral-correction window must be symmetric.",
    },
    {
        "session_id": "session-3186-num-178",
        "scan_id": "NL-HaNA_1.01.02_3186_0412",
        "heading_as_read": "martis den xxviijen septembris 1627",
        "date_named": "1627-09-28",
        "session_date": "1627-09-28",
        "recorded_date": "1627-10-18",
        "enriched_date": "1627-09-27",
        "mechanism": "recorded_date_wrong",
        "note": "Tuesday the 28th, and 1627-09-28 was a Tuesday; read as Old Style the day "
                "would be Gregorian 8 October, a Friday, so the page is New Style. Recorded "
                "date 20 days off. The enriched date is one day off, where a clerk slip and "
                "an edition slip cannot be separated -- not settled.",
    },
    {
        "session_id": "session-3189-num-77",
        "scan_id": "NL-HaNA_1.01.02_3189_0143",
        "heading_as_read": "sabbathi den 6 Aprilis 1630",
        "date_named": "1630-04-06",
        "session_date": "1630-04-06",
        "recorded_date": "1630-03-27",
        "enriched_date": "1630-03-25",
        "mechanism": "recorded_date_wrong",
        "note": "Saturday 6 April, and 1630-04-06 was a Saturday. An Old Style reading was "
                "proposed (Julian 27 March 1630 is Gregorian 6 April 1630, the same Saturday) "
                "and withdrawn: this corpus' dates are always modern style (user). So the "
                "recorded date is 10 days early, and `session-3185-num-98` is 10 days late -- "
                "the same magnitude, opposite signs. The enriched 25 March is 12 days off.",
    },
]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def main() -> None:
    rows = []
    for verdict in VERDICTS:
        named = pd.Period(verdict["date_named"], freq="D")
        session = pd.Period(verdict["session_date"], freq="D")
        recorded = pd.Period(verdict["recorded_date"], freq="D")
        enriched = (
            pd.Period(verdict["enriched_date"], freq="D") if verdict["enriched_date"] else None
        )
        rows.append({
            "record_type": "verdict",
            **verdict,
            "date_named_weekday": WEEKDAYS[named.dayofweek],
            "session_date_weekday": WEEKDAYS[session.dayofweek],
            "recorded_date_weekday": WEEKDAYS[recorded.dayofweek],
            "recorded_minus_session_days": int((recorded - session).n),
            "enriched_minus_session_days": None if enriched is None else int((enriched - session).n),
            "recorded_date_agrees": recorded == session,
            "enriched_date_agrees": enriched is not None and enriched == session,
            "annotator": ANNOTATOR,
            "read_on": READ_ON,
            "evidence": "manuscript image",
        })

    agree_recorded = sum(1 for r in rows if r["recorded_date_agrees"])
    scored = [r for r in rows if r["enriched_minus_session_days"] is not None]
    agree_enriched = sum(1 for r in scored if r["enriched_date_agrees"])
    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": "Human readings of session date headings from manuscript images. The "
                       "only date evidence in this project independent of the HTR pipeline.",
        "parent_datasets": ["session_region_text_1626_1630"],
        "n_verdicts": len(rows),
        "n_sessions": len({r["session_id"] for r in rows}),
        "recorded_date_agrees": agree_recorded,
        "enriched_date_agrees": f"{agree_enriched} of {len(scored)} where an enriched date exists",
        "mechanisms": sorted({r["mechanism"] for r in rows}),
        "annotator": ANNOTATOR,
        "caveat": "n is small and these are not a random sample -- they were selected because "
                  "the automated channel could not settle them, so they over-represent hard "
                  "cases and cannot give a corpus rate.",
    }
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(rows)} manuscript verdicts over {meta['n_sessions']} sessions to {path}")
    print(f"  recorded date agrees with the page: {agree_recorded} of {len(rows)}")
    print(f"  enriched date agrees: {agree_enriched} of {len(scored)}")
    print()
    print(f"{'session':<22}{'page':<12}{'recorded':<12}{'off':>5}  mechanism")
    for r in rows:
        print(f"{r['session_id']:<22}{r['session_date']:<12}{r['recorded_date']:<12}"
              f"{r['recorded_minus_session_days']:>+5}  {r['mechanism']}")


if __name__ == "__main__":
    main()

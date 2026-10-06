#!/usr/bin/env python3
"""HYPOTHESIS TEST: do the session headings say which date is right, for the 24 contested cases?

Predictions are fixed here before the run, per the project's standing practice, so nothing
below can be fitted to the result.

Population
----------
The 24 enriched dates that resolve to no HTR session, are not XML-flagged secret, and for
which the ES `full_resolutions` index dates a session to that day -- where that session is
present in this corpus under a **later** date (23 of 24 later, by 1, 2, 3, 4, 5, 6, 10, 11,
15, 16 or 21 days). ES is upstream of `resolutions_flat`, so this is a date-attribution
question, not missing text: ES carries the uncorrected first-pass `session_date`, this corpus
the corrected one, and for these 24 the correction moved the session away from the date the
enriched edition records.

Hypotheses, mutually exclusive per case
---------------------------------------
H0  The correction is right. The heading's own day token and weekday both agree with **our
    corrected label**, and the enriched date has no session for a reason unrelated to dating.

H1  The correction moved the session wrongly. The heading's day token and weekday both agree
    with the **enriched date**.

H2  Julian/Gregorian. 10 days is the gap in this period, the Republic used both styles by
    province, and Old Style appears in this very HTR (`in dato 13e. lestleden ouden styls`,
    Gelderland). The discriminating prediction, and the reason this is testable rather than
    merely plausible: **a weekday is a property of the physical day and does not shift
    between styles, while the day number does.** So if the page is dated Old Style and the
    correction converted it to New Style, the heading's day token matches the **enriched**
    date while its weekday matches **our corrected label**. That split signature belongs to
    no other explanation. Expected at offset exactly 10 if anywhere.

Stated in advance
-----------------
* **Undecidable by weekday when the offset is a multiple of 7**, because both candidate dates
  then fall on the same weekday. That is the single 21-day case, excluded from the verdict
  counts rather than silently resolved.
* **Most cases are expected to yield nothing.** The heading channel was already measured mute
  on this population: of 14 cases probed, 2 matched only the ES date, 0 only our label, 10
  carried no findable heading and 2 matched both. So a result of "no heading" on the majority
  **confirms** that earlier measurement and is not a failure of this test.
* **A verdict needs n to mean anything.** With an expected handful of readable headings, any
  count below ~5 in one class is a direction, not a finding, and must be reported as such.
* H2 is not supported merely by an offset of 10. It requires the split signature. Three cases
  carry a 10-day offset, so even a clean sweep is n=3.

Diagnostic only: no placement change, no tolerance-family metric.

Usage:
    uv run python scripts/h_weekday_date_attribution.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The ES client lives in the sibling `formulation` project, as it does for
# scripts/build_resolution_archival_provenance.py.
FORMULATION = Path("/Users/rikhoekstra/develop/formulation")
if FORMULATION.exists() and str(FORMULATION) not in sys.path:
    sys.path.insert(0, str(FORMULATION))

from data_io import load, save_semi_structured
from scripts.s6_duplicate_session_date_headings import find_headings

OUTPUT_DATASET = "h_weekday_date_attribution"
REVIEW_DATASET = "unplaced_date_review"
ES_HOST = "annotation.republic-caf.diginfra.org"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# A heading introduced by this formula names YESTERDAY's sitting, not this one: "with the
# President and those present who sat yesterday, Tuesday 20 January 1626, except Duick".
# Without it the channel dates a session systematically one day early -- confirmed on
# session-3185-num-16, where the image reads 20 January and this corpus label of the 21st is
# the correct one precisely because of this formula (user, 2026-10-06).
BACK_REFERENCE = re.compile(r"qui\s+heri|praesentibus\s+qui", re.IGNORECASE)

# Dates read off the manuscript images by the user, 2026-10-06. Ground truth, and the check
# on this test: a run that cannot reproduce these is not working.
HUMAN_VERDICTS = {
    "session-3185-num-16": ("1626-01-21", "H0", "heading names yesterday via `qui heri`"),
    "session-3185-num-72": ("1626-04-14", "H1", "image reads Martis 14 April; HTR has xiijen (13)"),
    "session-3185-num-98": ("1626-05-20", "H1", "Mercurij den xxen Maij 1626, offset 10, kills H2"),
}

PREDICTIONS = [
    "H0  correction right      : heading day == our label AND heading weekday == our label",
    "H1  correction wrong      : heading day == enriched  AND heading weekday == enriched",
    "H2  Julian/Gregorian      : heading day == enriched  AND heading weekday == our label",
    "    (weekday is physical and does not shift between styles; the day number does)",
    "undecidable               : offset divisible by 7 -- both dates share a weekday",
    "no signal                 : no readable heading, or day/weekday point different ways",
]


def classify(
    heading_day: int | None,
    heading_weekday: int | None,
    enriched: pd.Period,
    ours: pd.Period,
) -> str:
    day_enriched = heading_day == enriched.day
    day_ours = heading_day == ours.day
    wd_enriched = heading_weekday == enriched.dayofweek
    wd_ours = heading_weekday == ours.dayofweek

    if heading_day is None and heading_weekday is None:
        return "no signal"
    if day_ours and wd_ours:
        return "H0"
    if day_enriched and wd_enriched:
        return "H1"
    if day_enriched and wd_ours:
        return "H2"
    # One constraint readable only: a direction, recorded separately so it cannot be counted
    # toward a hypothesis it does not establish.
    if heading_weekday is None:
        return "day_only_enriched" if day_enriched else ("day_only_ours" if day_ours else "no signal")
    if heading_day is None:
        return "weekday_only_enriched" if wd_enriched else ("weekday_only_ours" if wd_ours else "no signal")
    return "no signal"


def main() -> None:
    print(__doc__.split("Usage:")[0].rstrip())
    print("\nPREDICTIONS, fixed before the run:")
    for line in PREDICTIONS:
        print("  " + line)
    print()

    from formulation.republic_es import ElasticsearchConfig, RepublicEsClient

    review = [
        row
        for row in load(REVIEW_DATASET)
        if isinstance(row, dict) and row.get("record_type") == "review" and row.get("es_has_resolutions")
    ]
    cases = [row for row in review if row.get("our_axis_label")]

    # THE HEADING SOURCE. Not the paragraph axis: that is built from resolutions_flat, which
    # carries resolution-class text only, so the date headings are simply not in it -- which
    # is why an earlier run of this test came back 23 of 24 "no signal". ES classes text
    # regions, and the headings live in `date`-class ones, alongside `attendance` regions
    # this corpus also lacks. Measured: session-3185-num-98's heading reads `Heeren Grave,
    # Rantwijck, De Bie, Halewijn, Mercurij den xxen. Maij 1626` in ES and appears nowhere on
    # the axis.
    client = RepublicEsClient(config=ElasticsearchConfig(host=ES_HOST))
    index = client.config.session_text_regions_index
    wanted = sorted({row["es_session_id"] for row in cases})
    by_session: dict[str, list[dict[str, Any]]] = {}
    for start in range(0, len(wanted), 25):
        chunk = wanted[start : start + 25]
        body = {
            "size": 500,
            "query": {
                "bool": {
                    "must": [
                        {"terms": {"metadata.session_id.keyword": chunk}},
                        {"term": {"metadata.text_region_class.keyword": "date"}},
                    ]
                }
            },
            "_source": ["metadata.session_id", "metadata.scan_id", "metadata.reading_order",
                        "lines.text"],
        }
        response = client._request_json("POST", f"{index}/_search", body=body)
        for hit in response.get("hits", {}).get("hits") or []:
            source = hit.get("_source") or {}
            meta = source.get("metadata") or {}
            text = " ".join(str(line.get("text") or "") for line in (source.get("lines") or []))
            if not any(ch.isalpha() for ch in text):
                continue  # pure OCR rubble like `4153 114 1550.`
            by_session.setdefault(str(meta.get("session_id")), []).append(
                {
                    "text": text,
                    "axis_id": str(meta.get("scan_id")),
                    "scan_id": str(meta.get("scan_id")),
                    "reading_order": meta.get("reading_order") or 0,
                }
            )
    for regions in by_session.values():
        regions.sort(key=lambda r: (r["scan_id"], r["reading_order"]))

    rows: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda r: r["enriched_date"]):
        enriched = pd.Period(case["enriched_date"], freq="D")
        ours = pd.Period(case["our_axis_label"][0], freq="D")
        offset = (ours - enriched).n
        paragraphs = by_session.get(case["es_session_id"]) or []

        # Search under both candidate dates; parsed_day and weekday_found are properties of
        # the page text, not of the query, so they can arbitrate between the two.
        hits = find_headings(paragraphs, str(enriched)) + find_headings(paragraphs, str(ours))
        # The session's own date is its FIRST heading. A first version took max(score) and on
        # 1626-01-20 picked `den xxijen. Januarij 1626` from further into the session --
        # ordinary text, not the session's date, the session-3185-num-56 phenomenon.
        best = min(hits, key=lambda h: (h["paragraph_position"], h["offset"])) if hits else None
        heading_day = best["parsed_day"] if best else None
        heading_weekday = best["weekday_found"] if best else None

        # A `qui heri` heading names yesterday, so the session is the day after it.
        back_reference = bool(best and BACK_REFERENCE.search(
            paragraphs[best["paragraph_position"]]["text"][: best["offset"] + 1]
        ))
        if back_reference and heading_day is not None:
            named = pd.Period(f"{enriched.year}-{enriched.month:02d}-{heading_day:02d}", freq="D")
            shifted = named + 1
            heading_day, heading_weekday = shifted.day, shifted.dayofweek

        verdict = (
            "undecidable"
            if offset % 7 == 0
            else classify(heading_day, heading_weekday, enriched, ours)
        )
        rows.append(
            {
                "record_type": "case",
                "enriched_date": str(enriched),
                "our_label": str(ours),
                "offset_days": int(offset),
                "session_id": case["es_session_id"],
                "k_e": case["k_e"],
                "n_headings_found": len(hits),
                "heading_matched": best["matched"] if best else None,
                "heading_day": heading_day,
                "heading_weekday": None if heading_weekday is None else WEEKDAYS[heading_weekday],
                "enriched_weekday": WEEKDAYS[enriched.dayofweek],
                "our_weekday": WEEKDAYS[ours.dayofweek],
                "heading_is_back_reference": back_reference,
                "verdict": verdict,
                "human_date": (HUMAN_VERDICTS.get(case["es_session_id"]) or (None,))[0],
                "human_verdict": (HUMAN_VERDICTS.get(case["es_session_id"]) or (None, None))[1],
            }
        )

    counts = Counter(row["verdict"] for row in rows)
    decidable = [r for r in rows if r["verdict"] != "undecidable"]

    print(f"{'enriched':<12}{'ours':<12}{'off':>4}  {'heading':<26}{'day':>4} {'wd':>4} "
          f"{'enr':>4} {'our':>4}  verdict")
    for row in rows:
        print(
            f"{row['enriched_date']:<12}{row['our_label']:<12}{row['offset_days']:>4}  "
            f"{(row['heading_matched'] or '-')[:26]:<26}"
            f"{str(row['heading_day'] or '-'):>4} {str(row['heading_weekday'] or '-'):>4} "
            f"{row['enriched_weekday']:>4} {row['our_weekday']:>4}  {row['verdict']}"
        )

    print("\nVERDICT COUNTS")
    for name in ("H0", "H1", "H2", "day_only_enriched", "day_only_ours",
                 "weekday_only_enriched", "weekday_only_ours", "no signal", "undecidable"):
        if counts.get(name):
            print(f"  {name:<24}{counts[name]}")

    print(f"\ncases {len(rows)} | decidable {len(decidable)}")
    julian = [r for r in rows if r["offset_days"] == 10]
    print(f"10-day offset cases: {len(julian)}, verdicts {Counter(r['verdict'] for r in julian)}")
    strongest = max((counts.get(h, 0) for h in ("H0", "H1", "H2")), default=0)
    print(
        "\nREADING: "
        + (
            f"no hypothesis reaches n=5; the largest class holds {strongest} case(s), which is a "
            "direction at most. The stated expectation that this channel is mute on this "
            "population is what the result confirms."
            if strongest < 5
            else f"largest hypothesis class holds {strongest} cases -- report with its n and "
            "against the uniform expectation before treating it as established."
        )
    )

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "hypotheses": PREDICTIONS,
        "population": "enriched dates with no session, non-secret, ES dates a session to them",
        "n_cases": len(rows),
        "n_decidable": len(decidable),
        "verdict_counts": dict(counts),
        "predictions_fixed_before_run": True,
    }
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()

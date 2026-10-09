#!/usr/bin/env python3
"""AUDIT: does the XML-native nihil-actum extraction already cover feast days?

NEXT STEP from plans/SEQUENCE_ALIGNMENT_TRACK.md (user, 2026-10-07): before computing a
feast-day calendar as a new anchor source for the weekly-walk window count, check the XML
*directly* for its own ``nihil actum`` markers, because the day-status pipeline already
claims a nihil count (``resolution_concordance_1626_1630``'s ``status`` column, consumed by
``running_axis`` and ``session_offset_eval.py``: 127 dates). The question is whether that
figure is already the XML's own signal or an undercount this script can close.

Three nihil counts exist before this script runs, over three different populations:

* **162** / 1,595 -- ``scripts/s4_candidate_scoring.is_nihil_actum`` applied to
  ``enriched_resolutions_1626_1630`` text, concatenated per date.
* **127** / 1,594 -- ``resolution_concordance_1626_1630``'s ``status`` column, the
  authoritative figure production actually uses (``running_axis.axis.RunningAxis.load``,
  ``session_offset_eval.py``).
* **125** -- of those 127, the ones with no axis paragraph label either (the
  ``nihil_actum`` addressability bucket in ``running_axis``; the other 2 carry a label from
  some other paragraph despite a nihil status).

None of these three reads the day XML's own ``<resolutie><p>Nihil Actum...`` markers
directly -- they all route through derived text. This script does, against
``enriched_resolutions_xml_source`` (the 1,594 real day files, excluding the ``NihilActum.xml``
template), using the same anchored pattern (``is_nihil_actum``, imported rather than
reimplemented) applied to each file's own resolutie text instead of the derived corpus.

Then, only once that comparison is in hand, it computes the feast-day calendar (Easter +1,
Pentecost +1, Christmas +1 -- six dates per year, Gregorian/"modern style" per the user's
2026-10-06 withdrawal of the calendar-style hypothesis) as a cross-check, not a primary
source, and sizes how many of those feast dates are already nihil or already Sunday --
i.e. how much NEW anchor density feast days would add beyond what Sundays and the existing
nihil-actum anchors already give the weekly-walk rule.

Diagnostic only: no placement change, no tolerance-family metric.

Usage:
    uv run python scripts/h_xml_nihil_vs_feast_calendar.py
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
from dateutil.easter import easter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve, save_semi_structured
from running_axis.axis import RunningAxis
from scripts.build_session_date_mapping_review_ui import enriched_text_by_date
from scripts.s4_candidate_scoring import is_nihil_actum

OUTPUT_DATASET = "h_xml_nihil_vs_feast_calendar"
SOURCE_DATASET = "enriched_resolutions_xml_source"

TAG_RE = re.compile(r"<[^>]+>")
RESOLUTIE_RE = re.compile(r"<resolutie[^>]*>(.*?)</resolutie>", re.DOTALL | re.IGNORECASE)
ZITTINGSDAG_RE = re.compile(r"<zittingsdag\b([^>]*)>", re.IGNORECASE)
ATTR_RE = re.compile(r'(dag|maand|jaar)\s*=\s*"([^"]*)"', re.IGNORECASE)

# Years the XML calendar covers (coverage-wide, running_axis.axis.RunningAxis.coverage).
YEARS = (1626, 1627, 1628, 1629, 1630)
# Feast days per the track's framing: Easter and Pentecost are moveable (Easter Sunday is
# dateutil's `easter()`; Pentecost Sunday is Easter + 49 days by definition), Christmas
# fixed. Each contributes the Sunday/feast day itself plus its Monday, matching the user's
# "2 days" framing (Easter, Pentecost, Christmas).
FIXED_CHRISTMAS = (12, 25)


def day_files(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as bundle:
        return [
            name
            for name in bundle.namelist()
            if name.endswith(".xml")
            and "__MACOSX" not in name
            and "svn" not in name
            and "NihilActum.xml" not in name
        ]


def file_date(raw: str) -> str | None:
    """Parse ``dag``/``maand``/``jaar`` off ``<zittingsdag>`` regardless of attribute order."""
    match = ZITTINGSDAG_RE.search(raw)
    if not match:
        return None
    attrs = {key.lower(): value.strip() for key, value in ATTR_RE.findall(match.group(1))}
    if not {"dag", "maand", "jaar"} <= attrs.keys():
        return None
    try:
        day, month, year = int(attrs["dag"]), int(attrs["maand"]), int(attrs["jaar"])
    except ValueError:
        return None
    try:
        return str(pd.Period(year=year, month=month, day=day, freq="D"))
    except ValueError:
        return None


def file_resolutie_text(raw: str) -> str:
    blocks = RESOLUTIE_RE.findall(raw)
    texts = [" ".join(TAG_RE.sub(" ", block).split()) for block in blocks]
    return " ".join(text for text in texts if text)


def scan_xml(archive: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive) as bundle:
        for name in day_files(archive):
            raw = bundle.read(name).decode("utf-8", "replace")
            date = file_date(raw)
            text = file_resolutie_text(raw)
            rows.append(
                {
                    "file": name.split("/")[-1],
                    "date": date,
                    "xml_nihil": is_nihil_actum(text),
                    "xml_text_len": len(text),
                }
            )
    return pd.DataFrame(rows)


def feast_dates() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for year in YEARS:
        easter_sunday = pd.Period(easter(year).isoformat(), freq="D")
        pentecost_sunday = easter_sunday + 49
        christmas = pd.Period(year=year, month=FIXED_CHRISTMAS[0], day=FIXED_CHRISTMAS[1], freq="D")
        for feast, anchor in (
            ("easter", easter_sunday),
            ("pentecost", pentecost_sunday),
            ("christmas", christmas),
        ):
            for offset, label in ((0, "day1"), (1, "day2")):
                day = anchor + offset
                rows.append(
                    {
                        "date": str(day),
                        "feast": feast,
                        "feast_day": label,
                        "weekday": day.dayofweek,
                        "is_sunday": day.dayofweek == 6,
                    }
                )
    return pd.DataFrame(rows)


def main() -> None:
    archive = Path(resolve(SOURCE_DATASET))
    xml = scan_xml(archive)
    xml_dated = xml.dropna(subset=["date"]).copy()
    print(f"XML day files: {len(xml):,} (template excluded); dated: {len(xml_dated):,}")
    print(f"  XML-native literal nihil-actum days: {int(xml_dated['xml_nihil'].sum()):,}")

    # --- Action 1: does the production nihil figure already capture the XML's own signal? ---
    axis = RunningAxis.load()
    concordance_nihil = {date for date, state in axis.dates.items() if state.is_nihil}

    enriched_records = load("enriched_resolutions_1626_1630")
    text_by_date = enriched_text_by_date(enriched_records)
    candidate_scoring_nihil = {date for date, text in text_by_date.items() if is_nihil_actum(text)}

    xml_nihil_dates = set(xml_dated.loc[xml_dated["xml_nihil"], "date"])

    captured_by_concordance = xml_nihil_dates & concordance_nihil
    xml_only = xml_nihil_dates - concordance_nihil
    concordance_only = concordance_nihil - xml_nihil_dates

    print()
    print("Action 1 -- XML-native nihil vs. the production status column:")
    print(f"  candidate_scoring (162 figure) nihil dates: {len(candidate_scoring_nihil):,}")
    print(f"  resolution_concordance status==nihil_actum: {len(concordance_nihil):,}")
    print(f"  XML day-file literal nihil-actum dates:     {len(xml_nihil_dates):,}")
    print(
        f"  captured by concordance: {len(captured_by_concordance):,} "
        f"({len(captured_by_concordance) / len(xml_nihil_dates):.1%} of XML nihil)"
    )
    print(f"  XML-nihil but NOT concordance-nihil: {len(xml_only):,} {sorted(xml_only)[:10]}")
    print(f"  concordance-nihil but NOT XML-literal: {len(concordance_only):,} {sorted(concordance_only)[:10]}")

    # --- Action 2: feast-day calendar, cross-check only ---
    feasts = feast_dates()
    coverage = axis.coverage
    in_window = feasts[(feasts["date"] >= coverage.start) & (feasts["date"] <= coverage.end)].copy()
    in_window["already_sunday"] = in_window["is_sunday"]
    in_window["already_xml_nihil"] = in_window["date"].isin(xml_nihil_dates)
    in_window["already_concordance_nihil"] = in_window["date"].isin(concordance_nihil)
    in_window["new_anchor"] = ~(
        in_window["already_sunday"] | in_window["already_xml_nihil"] | in_window["already_concordance_nihil"]
    )

    print()
    print(f"Action 2 -- feast-day calendar in window {coverage.start}..{coverage.end}:")
    print(f"  computed feast dates: {len(in_window):,}")
    print(f"  already Sunday:            {int(in_window['already_sunday'].sum()):,}")
    print(f"  already XML-literal nihil: {int(in_window['already_xml_nihil'].sum()):,}")
    print(f"  already concordance nihil: {int(in_window['already_concordance_nihil'].sum()):,}")
    print(f"  NEW anchors (none of the above): {int(in_window['new_anchor'].sum()):,}")
    if in_window["new_anchor"].any():
        print(f"    {in_window.loc[in_window['new_anchor'], ['date', 'feast', 'feast_day']].to_dict('records')}")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "XML-native nihil-actum audit against the production status column, plus a "
            "feast-day calendar cross-check, per plans/SEQUENCE_ALIGNMENT_TRACK.md's "
            "2026-10-07 NEXT step."
        ),
        "parent_datasets": [
            SOURCE_DATASET,
            "resolution_concordance_1626_1630",
            "enriched_resolutions_1626_1630",
        ],
        "xml_day_files": len(xml),
        "xml_day_files_dated": len(xml_dated),
        "xml_native_nihil_count": len(xml_nihil_dates),
        "candidate_scoring_nihil_count": len(candidate_scoring_nihil),
        "concordance_nihil_count": len(concordance_nihil),
        "xml_nihil_captured_by_concordance": len(captured_by_concordance),
        "xml_nihil_captured_share": (
            len(captured_by_concordance) / len(xml_nihil_dates) if xml_nihil_dates else None
        ),
        "xml_nihil_not_in_concordance": sorted(xml_only),
        "concordance_nihil_not_in_xml_literal": sorted(concordance_only),
        "feast_dates_in_window": len(in_window),
        "feast_new_anchors": int(in_window["new_anchor"].sum()),
    }
    rows = [
        {"record_type": "xml_day", **row}
        for row in xml_dated.to_dict("records")
    ] + [
        {"record_type": "feast_day", **row}
        for row in in_window.to_dict("records")
    ]
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote audit to {path}")


if __name__ == "__main__":
    main()

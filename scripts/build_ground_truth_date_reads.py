#!/usr/bin/env python3
"""Parse the filled page-read workbook into a durable dataset. The reads are the arbiter.

`ground_truth_date_sample` is an `.xlsx` a human fills in; a workbook is fragile (an open Excel
session overwrote a regenerated copy once already), so the transcriptions are lifted here into
jsonl and the workbook is kept only as the input artefact.

Companion to `manuscript_date_verdicts` (7 readings, 2026-10-06) rather than an extension of it:
those were selected **because the automated channel could not settle them**, so they
over-represent hard cases, while these 14 were selected to **discriminate between two named
hypotheses** (see `build_ground_truth_date_sample.py`). Different sampling, different caveat,
separate dataset -- and `.cursorrules` requires versioning reference data rather than mutating it.

Transcription conventions (annotator rik, 2026-10-08), recorded so the parser is not re-derived
by guesswork later: the `en` suffix of a day numeral is **split off** because it is written in
uppercase on the page (`xxviii en May`), the abbreviation period under the numeral is **omitted**
as it is easily missed and carries no information, and several dates on one page are separated by
newlines in the cell. Roman numerals are written with terminal `ii`, not the `ij` of REPUBLIC's
`DAY_TOKENS`, so a real roman parser is used here instead of that lookup.

Usage:
    uv run python scripts/build_ground_truth_date_reads.py
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

from data_io import resolve, save_semi_structured

SOURCE_DATASET = "ground_truth_date_sample"
OUTPUT_DATASET = "ground_truth_date_reads"

MONTHS = {
    "januari": 1, "january": 1, "januarij": 1, "februari": 2, "februarij": 2,
    "martii": 3, "martij": 3, "maart": 3, "aprilis": 4, "april": 4,
    "may": 5, "mai": 5, "maij": 5, "mey": 5, "junii": 6, "junij": 6, "juni": 6, "junj": 6,
    "jullj": 7, "julii": 7, "julij": 7, "juli": 7, "july": 7, "augusti": 8,
    "september": 9, "septembris": 9, "october": 10, "octobris": 10,
    "november": 11, "novembris": 11, "december": 12, "decembris": 12,
}
ROMAN = {"i": 1, "j": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def roman_day(token: str) -> int | None:
    """Day number from a roman numeral as transcribed (`xxviii`, `vii`, terminal `j` = `i`)."""
    text = token.lower().replace("j", "i")
    if not text or any(ch not in "ivxlc" for ch in text):
        return None
    total = 0
    for i, ch in enumerate(text):
        value = ROMAN[ch]
        nxt = ROMAN[text[i + 1]] if i + 1 < len(text) else 0
        total += -value if value < nxt else value
    return total if 1 <= total <= 31 else None


def dates_in(text: Any, year: int) -> list[str]:
    """Every `<day> <month>` the transcription states, in order, deduplicated."""
    if not isinstance(text, str):
        return []
    found: list[str] = []
    day: int | None = None
    for token in re.findall(r"[A-Za-z]+|\d+", text):
        low = token.lower()
        if low in ("en", "den"):
            continue
        if token.isdigit():
            number = int(token)
            if 1 <= number <= 31:
                day = number
            continue
        if low in MONTHS:
            if day is not None:
                try:
                    found.append(str(pd.Period(year=year, month=MONTHS[low], day=day, freq="D")))
                except ValueError:
                    pass
                day = None
            continue
        parsed = roman_day(low)
        if parsed is not None:
            day = parsed
    return list(dict.fromkeys(found))


def main() -> None:
    frame = pd.read_excel(Path(resolve(SOURCE_DATASET)))
    rows: list[dict[str, Any]] = []
    for _, r in frame.iterrows():
        label = str(r["recorded_label_R"])[:10]
        heading = str(r["heading_HTR_read_H"])[:10]
        year = int(label[:4])
        transcript = r.get("ACTUAL_DATE_ON_SCAN")
        second = r.get("DATE_OF_2ND_SITTING_IF_ANY")
        page_dates = dates_in(transcript, year) + dates_in(second, year)
        page_dates = list(dict.fromkeys(page_dates))
        label_on_page = label in page_dates
        heading_on_page = heading in page_dates
        rows.append({
            "record_type": "page_read",
            "annotator": "rik",
            "read_on": "2026-10-08",
            "case_class": r["case"],
            "session_id": r["session_id"],
            "inventory": str(r["inventory"]),
            "recorded_label": label,
            "htr_heading_date": heading if heading != "(unreada" else None,
            "offset_days_heading_minus_label": (
                None if pd.isna(r["offset_days_H_minus_R"]) else int(r["offset_days_H_minus_R"])
            ),
            "content_best_date": (
                None if pd.isna(r["content_best_date"]) else str(r["content_best_date"])[:10]
            ),
            "transcription": None if pd.isna(transcript) else str(transcript),
            "second_sitting_transcription": None if pd.isna(second) else str(second),
            "dates_written_on_page": page_dates,
            "label_is_on_page": label_on_page,
            "htr_heading_is_on_page": heading_on_page,
            "page_carries_nihil_actum": "nihil" in str(transcript).lower(),
            "page_carries_postprandium": "prandium" in f"{transcript} {second}".lower(),
            "notes": None if pd.isna(r.get("NOTES")) else str(r["NOTES"]),
            # The split that matters: whether the label exists on the page at all.
            "verdict": (
                "both_dates_on_page" if label_on_page and heading_on_page
                else "only_heading_on_page" if heading_on_page
                else "only_label_on_page" if label_on_page
                else "neither_on_page"
            ),
        })

    from collections import Counter
    verdicts = Counter(r["verdict"] for r in rows)
    heading_ok = sum(1 for r in rows if r["htr_heading_is_on_page"])
    label_ok = sum(1 for r in rows if r["label_is_on_page"])

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "14 human page reads (annotator rik, 2026-10-08) from the strategic sample, lifted "
            "out of the .xlsx. Selected to discriminate H-drift from H-attribution, NOT "
            "representative -- no corpus rate may be derived from them."
        ),
        "parent_datasets": [SOURCE_DATASET],
        "n_reads": len(rows),
        "htr_heading_date_written_on_page": heading_ok,
        "recorded_label_written_on_page": label_ok,
        "verdict_counts": dict(verdicts),
        "transcription_conventions": (
            "`en` split off the numeral (uppercase on the page); abbreviation period omitted; "
            "multiple dates separated by newlines; roman numerals with terminal `ii` not `ij`."
        ),
        "caveat": (
            "n=14, chosen to discriminate between hypotheses and deliberately weighted to large "
            "offsets and structurally odd sessions. Not a random sample; gives no corpus rate."
        ),
    }
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(rows)} page reads to {path}")
    print(f"  HTR heading date written on the page: {heading_ok}/{len(rows)}")
    print(f"  recorded label written on the page:   {label_ok}/{len(rows)}")
    print(f"  verdicts: {dict(verdicts)}")
    for r in rows:
        print(f"    {r['session_id']:<22}{r['recorded_label']}  page={','.join(r['dates_written_on_page']) or '-':<34}{r['verdict']}")


if __name__ == "__main__":
    main()

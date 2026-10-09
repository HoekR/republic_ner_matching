#!/usr/bin/env python3
"""A STRATEGIC page-read sample: my inference, the scan link, and a field for the real date.

Why this exists (user, 2026-10-07): page reads are the only true arbiter of the dating question
(`manuscript_date_verdicts`, 7 readings so far, "that is what i meant with more ground truth"),
and they are expensive, so the sample must **discriminate between the live hypotheses** rather
than be representative. Each row states which hypothesis it tests and what each hypothesis
predicts, so one read settles something.

The two live hypotheses, after 2026-10-07:

* **H-drift** -- the recorded label is wrong and the heading is right; the session really sits
  where its heading says. This is what the quarter-by-quarter page-offset measurement and the
  80.9% heading-disagreement rate were read as supporting.
* **H-attribution** -- the recorded label is right and the `date` region attributed to the session
  is **not that session's heading** (ES region->session attribution, or a scan<->session offset).
  Raised 2026-10-07 when the content channel, profiled non-circularly across a date window,
  backed the label in 6 of 6 sampled disagreeing sessions and the heading in 0 of 6. The
  session-index check adds a signature: a disagreeing session's heading date usually matches the
  label of a session **earlier in the same volume** by a volume-specific offset (3186: -10/-11;
  3188: -5; 3189: -3/-4/-5).

The discriminating question for most rows is therefore NOT "what is the date on this scan" alone
but **"is the business on this scan the business the edition dates to the label?"** -- so each row
carries both the label's date and the heading's date, and asks for the date actually written plus
(where cheap to see) whether the page's content looks like the label's business.

Content column: `content_best_date` is the enriched date whose summaries best match this session's
HTR text, by distinctive-proper-name matching over a +/-12-day window (fuzzy >=85 to absorb HTR
spelling, e.g. `Carraro`/`Corraro`). It never consults the label, so it is independent of it.

Diagnostic only; writes one `explore`-phase workbook for human transcription, changes nothing.

Usage:
    uv run python scripts/build_ground_truth_date_sample.py
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rapidfuzz import fuzz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve
from scripts._republic_date_vocab import MONTH_NAMES
from scripts.h_session_date_vs_heading import INVENTORY_NOMINAL_YEAR

OUTPUT_DATASET = "ground_truth_date_sample"
# Same IIIF base this project already uses (scripts/build_unplaced_date_review.py:67).
IIIF = "https://images.diginfra.net/iiif/NL-HaNA_1.01.02/{inv}/NL-HaNA_1.01.02_{inv}_{scan:04d}.jpg/full/full/0/default.jpg"

STOP = set(
    """heeft hebben wordt worden zullen haer haar deze hunne volgens inzake verzoek verzocht
    betaling brief missive resolutie resoluties staten generaal gedeputeerden compagnie regiment
    gulden ontvangen gelezen advies raad state holland zeeland conform gecommitteerde
    gecommitteerden gedeputeerde college commies kapitein amsterdam amsterdamse engeland""".split()
)


def iiif_url(scan_id: str) -> str | None:
    parts = str(scan_id).split("_")
    if len(parts) < 2 or not parts[-1].isdigit():
        return None
    return IIIF.format(inv=parts[-2], scan=int(parts[-1]))


def probes(texts: list[str]) -> set[str]:
    out: set[str] = set()
    for text in texts:
        for token in re.findall(r"[A-Z][a-zA-Z]{4,}", text):
            if token.lower() not in STOP:
                out.add(token)
    return out


def main() -> None:
    sessions = {
        r["session_id"]: r
        for r in load("h_session_date_vs_heading")
        if r.get("record_type") == "session"
    }
    regions = [r for r in load("session_region_text_1626_1630") if r.get("record_type") == "region"]
    by_session: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"date": [], "attendance": []}
    )
    for row in regions:
        by_session[row["session_id"]][row["region_class"]].append(row)
    postprandium = {
        str(r.get("date")) for r in load("postprandium_days") if r.get("record_type") == "postprandium_day"
    }

    axis = load("paragraph_axis_1626_1630")
    session_text: dict[str, str] = defaultdict(str)
    for record in axis:
        sid = str(record["flat_id"]).rsplit("-resolution-", 1)[0]
        session_text[sid] += " " + str(record.get("text") or "")

    enriched_by_date: dict[str, list[str]] = defaultdict(list)
    for record in load("enriched_resolutions_1626_1630"):
        enriched_by_date[str(record.get("date"))[:10]].append(str(record.get("text") or ""))
    probe_cache = {d: probes(t) for d, t in enriched_by_date.items()}

    # How many dates each name appears under, so the sheet can lead with the RARE ones. Sorting
    # alphabetically surfaced `Allen`/`Alles`/`Bovendien` -- ordinary Dutch words capitalised at
    # the start of a sentence -- which are useless for telling two days apart.
    name_doc_freq: dict[str, int] = defaultdict(int)
    for names in probe_cache.values():
        for name in names:
            name_doc_freq[name] += 1

    def names_for(date: str | None, limit: int = 7) -> str:
        """The most distinctive proper names the edition records under one date.

        Put in the sheet so 'whose business is on this page' is answerable by eye, without
        needing the edition open alongside -- the reader just looks for these names on the scan.
        Rarest first: a name appearing under one date discriminates, one appearing under 200 does not.
        """
        if not date:
            return ""
        names = probe_cache.get(str(date), set())
        ranked = sorted(names, key=lambda n: (name_doc_freq.get(n, 0), n))
        return ", ".join(ranked[:limit])

    def content_best(sid: str, centre: str, span: int = 12) -> tuple[str, float] | None:
        tokens = {t for t in re.findall(r"[A-Za-z]{5,}", session_text.get(sid, ""))}
        if not tokens:
            return None
        scored = []
        c = pd.Period(centre, freq="D")
        for day in pd.period_range(c - span, c + span, freq="D"):
            pr = probe_cache.get(str(day), set())
            if len(pr) < 15:
                continue
            n = sum(1 for p in pr if any(fuzz.ratio(p.lower(), s.lower()) >= 85 for s in tokens))
            scored.append((n / len(pr), str(day)))
        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][1], scored[0][0]

    # --- strategic selection -----------------------------------------------------------------
    picked: list[dict[str, Any]] = []

    def add(sid: str, klass: str, tests: str, predicts: str) -> None:
        if any(p["session_id"] == sid for p in picked) or sid not in sessions:
            return
        picked.append({"session_id": sid, "case_class": klass, "tests": tests, "predicts": predicts})

    # A. the worked example -- user already read 0190=28 May, 0192=29 May; content says 12 June
    add("session-3185-num-103", "A worked example",
        "H-drift vs H-attribution, the case already partly read",
        "H-drift: this scan's business is the 28/29 May business. "
        "H-attribution: the business here is what the edition dates 12 June, so the heading "
        "belongs to another session.")

    by_inv: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in sessions.values():
        by_inv[r["inventory"]].append(r)
    for rows in by_inv.values():
        rows.sort(key=lambda r: int(r["session_id"].rsplit("-num-", 1)[1]))

    # B. large offset in the two severe volumes
    for inv in ("3185", "3186"):
        cands = [r for r in by_inv[inv] if r["verdict"] == "disagrees" and (r["offset_days"] or 0) <= -12]
        for r in cands[:2]:
            add(r["session_id"], "B large offset, severe volume",
                "whether a 2-week offset is drift or a misattributed heading",
                "H-drift: page reads the heading's date. H-attribution: page reads the label's date.")

    # C. heading date matches NO session label in the volume
    for inv in ("3185", "3186", "3189"):
        labels = {r["recorded_date"] for r in by_inv[inv]}
        cands = [r for r in by_inv[inv]
                 if r["verdict"] == "disagrees" and r["stated_date"] and r["stated_date"] not in labels]
        for r in cands[:1]:
            add(r["session_id"], "C heading matches no label",
                "a heading naming a date no session claims -- a genuinely unclaimed sitting day?",
                "H-drift: a real sitting day the corpus lost. H-attribution: an HTR misread, or a "
                "heading from a neighbouring page.")

    # D. the +/-1 day class -- the largest single group, untested by the content profile
    for inv in ("3185", "3188"):
        cands = [r for r in by_inv[inv] if r["verdict"] == "disagrees" and abs(r["offset_days"] or 0) == 1]
        for r in cands[:1]:
            add(r["session_id"], "D one-day offset",
                "the largest disagreement class (111 of 567 within +/-1 day), where content cannot resolve it",
                "the ambiguous case by construction: HTR dropped/added a stroke, or the clerk "
                "misnamed the weekday (see h_session_date_vs_heading source 4).")

    # E. control -- the clean volume, where label and heading agree
    cands = [r for r in by_inv["3187"] if r["verdict"] == "agrees"]
    for r in cands[:1]:
        add(r["session_id"], "E control (clean volume)",
            "that the instrument reads correctly where everything already agrees",
            "both hypotheses predict the page reads the label's date. A miss here invalidates the "
            "whole instrument.")

    # F. the user's own rule: 2+ attendance lists, NOT a postprandium date, second heading MISSING
    cands = [
        sid for sid, v in by_session.items()
        if len(v["attendance"]) >= 2 and len(v["date"]) < 2
        and sessions.get(sid, {}).get("recorded_date") not in postprandium
    ]
    for sid in sorted(cands)[:3]:
        add(sid, "F attendance implies a next day",
            "the user's rule (2026-10-07): a 2nd attendance list on a non-postprandium day implies "
            "a new sitting, so posit a next-day anchor. Validated at only 25% where a 2nd heading "
            "is readable -- these are the cases where it is NOT readable, i.e. where the rule matters.",
            "rule holds: a 2nd date, one day after the first, is written near the 2nd attendance "
            "list. rule fails: same day (an unmarked afternoon sitting), or no date at all.")

    # G. a nihil-pinned Sunday from the 2026-10-07 audit
    add("session-3188-num-119", "G nihil-pinned Sunday",
        "the nihil audit's 3 'confirms_pin' cases: a Sunday the XML calls Nihil Actum carrying a "
        "pinned session, with a Monday attendance list inside it",
        "the Sunday is genuinely empty and the business is Monday's, so the pin is a day-boundary "
        "error, not an edition omission.")

    # --- build rows --------------------------------------------------------------------------
    out: list[dict[str, Any]] = []
    for case in picked:
        sid = case["session_id"]
        s = sessions[sid]
        v = by_session.get(sid, {"date": [], "attendance": []})
        scans = sorted({r["scan_id"] for r in v["date"] + v["attendance"]})
        best = content_best(sid, s["recorded_date"])
        label = s["recorded_date"]
        heading = s["stated_date"]
        inference = []
        if best:
            bd, rate = best
            if bd == label:
                inference.append(f"content matches the LABEL ({label}) at {rate:.0%} -> H-attribution")
            elif heading and bd == heading:
                inference.append(f"content matches the HEADING ({heading}) at {rate:.0%} -> H-drift")
            else:
                inference.append(f"content peaks at {bd} ({rate:.0%}), neither label nor heading")
        if s["verdict"] == "agrees":
            inference.append("label and heading already agree")
        out.append({
            "case": case["case_class"],
            "session_id": sid,
            "inventory": s["inventory"],
            "recorded_label_R": label,
            "heading_HTR_read_H": heading or "(unreadable)",
            "heading_text_as_HTR_read_it": (s["heading_text"] or "")[:90],
            "offset_days_H_minus_R": s["offset_days"],
            "content_best_date": best[0] if best else "",
            "content_best_rate": f"{best[1]:.0%}" if best else "",
            "my_inference": "; ".join(inference) or "no content signal",
            "hypothesis_tested": case["tests"],
            "what_each_predicts": case["predicts"],
            "n_date_regions": len(v["date"]),
            "n_attendance_regions": len(v["attendance"]),
            "scans": ", ".join(s.split("_")[-1] for s in scans),
            "scan_url_1": iiif_url(scans[0]) if scans else "",
            "scan_url_2": iiif_url(scans[1]) if len(scans) > 1 else "",
            "names_the_edition_files_under_LABEL_date": names_for(label),
            "names_the_edition_files_under_HEADING_date": names_for(heading),
            "ACTUAL_DATE_WRITTEN_ON_SCAN": "",
            "DATE_OF_2ND_SITTING_IF_ANY": "",
            "WHICH_NAMES_APPEAR_label_or_heading_or_neither": "",
            "NOTES": "",
        })

    frame = pd.DataFrame(out).sort_values(["case", "session_id"]).reset_index(drop=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "page reads"
    headers = list(frame.columns)
    ws.append(headers)
    fill_input = PatternFill("solid", fgColor="FFF2CC")
    fill_head = PatternFill("solid", fgColor="D9E2F3")
    for i, name in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True)
        c.fill = fill_head
        c.alignment = Alignment(wrap_text=True, vertical="top")
    inputs = {"ACTUAL_DATE_WRITTEN_ON_SCAN", "DATE_OF_2ND_SITTING_IF_ANY",
              "WHICH_NAMES_APPEAR_label_or_heading_or_neither", "NOTES"}
    for _, row in frame.iterrows():
        ws.append([row[h] for h in headers])
        r = ws.max_row
        for i, h in enumerate(headers, start=1):
            cell = ws.cell(row=r, column=i)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if h in inputs:
                cell.fill = fill_input
            if h.startswith("scan_url") and row[h]:
                cell.hyperlink = row[h]
                cell.value = "open scan"
                cell.font = Font(color="0563C1", underline="single")
    widths = {"case": 26, "session_id": 22, "heading_text_as_HTR_read_it": 40, "my_inference": 44,
              "hypothesis_tested": 50, "what_each_predicts": 54, "NOTES": 30,
              "names_the_edition_files_under_LABEL_date": 46,
              "names_the_edition_files_under_HEADING_date": 46,
              "ACTUAL_DATE_WRITTEN_ON_SCAN": 22, "DATE_OF_2ND_SITTING_IF_ANY": 20,
              "WHICH_NAMES_APPEAR_label_or_heading_or_neither": 26}
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(h, 15)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    path = Path(resolve(OUTPUT_DATASET))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    print(f"Wrote {len(frame)} strategic page-read cases to {path}")
    print(frame[["case", "session_id", "recorded_label_R", "heading_HTR_read_H",
                 "offset_days_H_minus_R", "content_best_date", "content_best_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()

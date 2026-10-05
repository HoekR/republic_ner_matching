#!/usr/bin/env python3
"""S3 — merge exported boundary annotations back into output/boundary_gold_sample.json.

Usage:
    uv run python merge_boundary_annotations.py [--annotator NAME]

Reads output/boundary_gold_annotations.json (exported from the annotation UI's
"Export annotations" button). For each day, the exported text is the flat
paragraph stream with three optional inline markers:

  - CUT ("|||CUT|||"): a plain resolution boundary — the next resolution
    starts immediately after.
  - END ("|||END|||"): marks where a resolution's content truly ends. Used
    alone at the very end of the text, it marks the true end of the last
    (K_e-th) resolution when that is before the end of the visible text
    (trailing text is spillover belonging elsewhere). Used immediately before
    a START marker, it brackets a boilerplate/header gap (e.g. a session
    heading) that belongs to no resolution.
  - START ("|||START RES|||"): marks where the next resolution's content
    truly begins, after a gap bracketed by a preceding END marker. Counts as
    an internal boundary the same way a CUT marker does.

A "startsMid" flag records whether the first fragment is a continuation from
a previous day (no position, since no earlier text is available).

This script strips the markers, diffs against the original paragraph stream
to recover each marker's exact position, and maps the resulting boundaries
(and any gaps) into output/boundary_gold_sample.json's "boundaries" field.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_alignment_new import OUTPUT_DIR, load_data
from build_boundary_annotation_ui import (
    MARKER,
    MARKER_DATE_END,
    MARKER_DATE_START,
    MARKER_END,
    MARKER_NOTEXT,
    MARKER_START,
    NOTE_PATTERN,
    NOTEXT_PATTERN,
    SEPARATOR,
    flat_paragraph_stream,
)

SAMPLE_FILE = OUTPUT_DIR / "boundary_gold_sample.json"
ANNOTATIONS_FILE = OUTPUT_DIR / "boundary_gold_annotations.json"


def expand_notext_counts(annotated_text: str) -> str:
    """Rewrite ``|||NOTEXT:6|||`` into six plain ``|||NOTEXT|||`` markers.

    Annotators mark a contiguous run of absent resolutions once and give its size,
    rather than repeating the bare marker. Expanding before :func:`parse_markers`
    keeps that function's single-pass catalog scan unchanged; because a recognised
    marker contributes nothing to ``base_pos``, all N expanded markers resolve to
    the same base offset, which is exactly the intent -- N consecutive unlocated
    slots at one position.
    """
    return re.sub(NOTEXT_PATTERN, lambda m: MARKER_NOTEXT * int(m.group(1)), annotated_text)


def strip_notes(annotated_text: str) -> tuple[str, list[str]]:
    """Remove ``|||NOTE: ...|||`` comments, returning the cleaned text and the notes.

    Must run before :func:`parse_markers`. An unrecognised ``|||...|||`` string would
    otherwise be walked as ordinary base text, advancing ``base_pos`` by its own length
    and silently displacing every later marker's recovered position.
    """
    notes = [m.group(0)[len("|||NOTE:") : -3].strip() for m in re.finditer(NOTE_PATTERN, annotated_text)]
    return re.sub(NOTE_PATTERN, "", annotated_text), notes


def parse_markers(
    annotated_text: str,
    cut_marker: str,
    end_marker: str,
    start_marker: str,
    date_end_marker: str = MARKER_DATE_END,
    date_start_marker: str = MARKER_DATE_START,
    notext_marker: str = MARKER_NOTEXT,
    base_text: str | None = None,
) -> list[tuple[int, str]]:
    """Single-pass scan: ordered (base_offset, type) tokens with all markers removed.

    type is one of "cut", "end", "start", "date_end", "date_start", "notext". Longer
    date markers are matched before END / START RES so prefixes do not collide.

    Pass ``base_text`` (the unannotated paragraph stream) to recover offsets by
    alignment rather than by counting every non-marker character. Without it, any
    character the annotator added -- newlines around a marker, a mistyped
    ``|||CUT|`` fragment -- inflates the recovered offset of every later marker,
    which relocates cuts into the wrong paragraph with no error raised.
    """
    # Longest-first so DATE_END does not match as END, etc.
    catalog = sorted(
        [
            (date_end_marker, "date_end"),
            (date_start_marker, "date_start"),
            (start_marker, "start"),
            (end_marker, "end"),
            (cut_marker, "cut"),
            (notext_marker, "notext"),
        ],
        key=lambda item: len(item[0]),
        reverse=True,
    )
    tokens: list[tuple[int, str]] = []
    base_pos = 0
    i = 0
    n = len(annotated_text)
    base_n = len(base_text) if base_text is not None else 0
    while i < n:
        matched = False
        for marker, kind in catalog:
            if marker and annotated_text.startswith(marker, i):
                tokens.append((base_pos, kind))
                i += len(marker)
                matched = True
                break
        if matched:
            continue
        if base_text is None:
            base_pos += 1
            i += 1
            continue
        # Align against the real base text. Annotators type markers on their own
        # lines, and that added whitespace is not in the paragraph stream; counting
        # it would advance base_pos past where every later marker actually sits,
        # silently relocating cuts into the wrong paragraph.
        if base_pos < base_n and annotated_text[i] == base_text[base_pos]:
            base_pos += 1
            i += 1
        elif annotated_text[i].isspace():
            i += 1  # inserted whitespace: consume it, do not advance the base cursor
        else:
            base_pos += 1
            i += 1
    return tokens


def locate_cut(base_offset: int, paragraphs: list[dict[str, Any]], separator: str) -> dict[str, Any]:
    """Map a base-text offset to a paragraph index + in-paragraph character offset."""
    cursor = 0
    for i, p in enumerate(paragraphs):
        text_len = len(p["text"])
        start, end = cursor, cursor + text_len
        if start <= base_offset < end:
            return {
                "paragraph_stream_index": i,
                "flat_id": p["flat_id"],
                "para_index": p["para_index"],
                "char_offset": base_offset - start,
                "unit": "mid_paragraph",
            }
        if base_offset == end:
            return {
                "paragraph_stream_index": i,
                "flat_id": p["flat_id"],
                "para_index": p["para_index"],
                "char_offset": text_len,
                "unit": "paragraph_boundary",
            }
        if end < base_offset < end + len(separator) and i + 1 < len(paragraphs):
            # The offset fell strictly inside the inter-paragraph separator (e.g. between
            # the two newlines of "\n\n"). The annotator meant the break itself, so snap
            # forward to the next paragraph's start rather than reporting out_of_range --
            # which would discard a correctly placed cut.
            nxt = paragraphs[i + 1]
            return {
                "paragraph_stream_index": i + 1,
                "flat_id": nxt["flat_id"],
                "para_index": nxt["para_index"],
                "char_offset": 0,
                "unit": "paragraph_boundary",
            }
        cursor = end + len(separator)
    return {"paragraph_stream_index": len(paragraphs) - 1, "unit": "out_of_range", "char_offset": None}


def build_boundaries(
    tokens: list[tuple[int, str]], paragraphs: list[dict[str, Any]], separator: str, base_len: int
) -> list[dict[str, Any]]:
    """Turn ordered markers into boundary records: cuts, gaps, date cuts, trailing end."""
    boundaries: list[dict[str, Any]] = []

    # A leading NOTEXT run means the day's FIRST resolutions are absent. Two things
    # follow, and neither is expressible by the plain per-resolution slot alone:
    # resolution 1 must abstain (``gold_start_paragraphs`` otherwise defaults it to
    # paragraph 0, inventing a placement for text that is not here), and the first
    # resolution that *is* present opens at paragraph 0 -- there is no marker for it
    # because there is no earlier text to put one in. So emit an unlocated ``start``
    # for resolution 1, unlocated cuts for the rest of the run, then a located cut at
    # paragraph 0 for the first present resolution.
    leading = 0
    while leading < len(tokens) and tokens[leading][1] == "notext":
        leading += 1
    if leading and paragraphs:
        boundaries.append(
            {"paragraph_stream_index": None, "flat_id": None, "char_offset": None, "unit": "no_htr_text", "kind": "start"}
        )
        for _ in range(leading - 1):
            boundaries.append(
                {"paragraph_stream_index": None, "flat_id": None, "char_offset": None, "unit": "no_htr_text", "kind": "cut"}
            )
        first = paragraphs[0]
        boundaries.append(
            {
                "paragraph_stream_index": 0,
                "flat_id": first["flat_id"],
                "para_index": first["para_index"],
                "char_offset": 0,
                "unit": "paragraph_boundary",
                "kind": "cut",
            }
        )
        tokens = tokens[leading:]

    for i, (offset, kind) in enumerate(tokens):
        if kind == "cut":
            boundaries.append({**locate_cut(offset, paragraphs, separator), "kind": "cut"})
        elif kind == "notext":
            # An enriched resolution with no text in this HTR at all. Occupies its
            # positional cut slot so later resolutions stay aligned, but is deliberately
            # unlocated -- `separated_accuracy_eval.is_located` scores it as None rather
            # than as a placement, which is the honest outcome (no fabricated precision).
            boundaries.append(
                {
                    "paragraph_stream_index": None,
                    "flat_id": None,
                    "char_offset": None,
                    "unit": "no_htr_text",
                    "kind": "cut",
                }
            )
        elif kind == "start":
            preceded_by_gap = i > 0 and tokens[i - 1][1] == "end"
            entry = {**locate_cut(offset, paragraphs, separator), "kind": "start"}
            entry["preceded_by_gap"] = preceded_by_gap
            if preceded_by_gap:
                gap_start_offset = tokens[i - 1][0]
                entry["gap_start"] = locate_cut(gap_start_offset, paragraphs, separator)
                entry["gap_char_length"] = offset - gap_start_offset
            boundaries.append(entry)
        elif kind == "date_start":
            preceded = i > 0 and tokens[i - 1][1] == "date_end"
            entry = {**locate_cut(offset, paragraphs, separator), "kind": "date_start"}
            entry["preceded_by_date_gap"] = preceded
            if preceded:
                gap_start_offset = tokens[i - 1][0]
                entry["date_gap_start"] = locate_cut(gap_start_offset, paragraphs, separator)
                entry["date_gap_char_length"] = offset - gap_start_offset
            boundaries.append(entry)
        elif kind == "date_end":
            # Paired date_start consumes the gap; a lone trailing DATE_END is recorded below.
            if i + 1 >= len(tokens) or tokens[i + 1][1] != "date_start":
                if i == len(tokens) - 1:
                    continue  # handled after loop
                boundaries.append({**locate_cut(offset, paragraphs, separator), "kind": "date_end"})
        # "end" tokens pair with start via lookahead; trailing end handled below.

    if tokens and tokens[-1][1] == "end":
        end_offset, _ = tokens[-1]
        end_cut = {**locate_cut(end_offset, paragraphs, separator), "kind": "end_of_last_resolution"}
        end_cut["has_trailing_spillover"] = end_offset < base_len
        boundaries.append(end_cut)

    if tokens and tokens[-1][1] == "date_end":
        end_offset, _ = tokens[-1]
        end_cut = {**locate_cut(end_offset, paragraphs, separator), "kind": "date_end"}
        end_cut["has_trailing_spillover"] = end_offset < base_len
        boundaries.append(end_cut)

    return boundaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotator", default=None, help="Name/initials to record against annotated days")
    parser.add_argument(
        "--sample",
        type=Path,
        default=SAMPLE_FILE,
        help="Sample JSON to merge into (default: boundary_gold_sample.json).",
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=ANNOTATIONS_FILE,
        help="Exported annotations JSON.",
    )
    parser.add_argument(
        "--allow-blanking",
        action="store_true",
        help=(
            "Permit replacing a day that already has opening slots with an export carrying none. "
            "Off by default: the UI stores every rendered day under one shared localStorage key, so "
            "an export routinely contains unmarked base text for days the annotator never touched, "
            "and merging that would silently erase existing hand annotations."
        ),
    )
    args = parser.parse_args()

    if not args.annotations.exists():
        raise FileNotFoundError(
            f"{args.annotations} not found. Export from boundary_annotation_ui.html first."
        )

    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    exported = json.loads(args.annotations.read_text(encoding="utf-8"))
    marker = exported.get("marker", MARKER)
    marker_end = exported.get("marker_end", MARKER_END)
    marker_start = exported.get("marker_start", MARKER_START)
    marker_date_end = exported.get("marker_date_end", MARKER_DATE_END)
    marker_date_start = exported.get("marker_date_start", MARKER_DATE_START)
    separator = exported.get("separator", SEPARATOR)
    annotated_by_date = exported.get("annotations", {})

    _, res_df, *_ = load_data()

    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    skipped: list[tuple[str, int]] = []
    for day in sample["days"]:
        state = annotated_by_date.get(day["date"])
        if state is None:
            continue
        annotated_text, notes = strip_notes(state.get("text", ""))
        annotated_text = expand_notext_counts(annotated_text)

        paragraphs = flat_paragraph_stream(res_df, day["flat_ids"])
        base_len = sum(len(p["text"]) for p in paragraphs) + len(separator) * max(0, len(paragraphs) - 1)
        tokens = parse_markers(
            annotated_text,
            marker,
            marker_end,
            marker_start,
            marker_date_end,
            marker_date_start,
            base_text=separator.join(p["text"] for p in paragraphs),
        )
        boundaries = build_boundaries(tokens, paragraphs, separator, base_len)

        existing_openings = len([b for b in (day.get("boundaries") or []) if b.get("kind") in ("cut", "start")])
        new_openings = len([b for b in boundaries if b.get("kind") in ("cut", "start")])
        if existing_openings and not new_openings and not args.allow_blanking:
            skipped.append((day["date"], existing_openings))
            continue

        day["boundaries"] = boundaries
        if notes:
            day["annotator_notes"] = notes
        day["starts_mid_resolution"] = bool(state.get("startsMid", False))
        day["annotator"] = args.annotator
        day["annotated_at"] = now
        updated += 1

    args.sample.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Merged {updated} annotated day(s) into {args.sample}")
    if skipped:
        print(
            f"PROTECTED {len(skipped)} already-annotated day(s) whose export carried no openings "
            f"(pass --allow-blanking to overwrite them anyway):"
        )
        for date, n in skipped:
            print(f"  {date}: kept {n} existing opening slot(s)")

    def transitions(day: dict[str, Any]) -> list[dict[str, Any]]:
        return [b for b in (day.get("boundaries") or []) if b.get("kind") in ("cut", "start")]

    def expected_slots(day: dict[str, Any]) -> int:
        """K_e - 1 cuts, plus one more when an explicit leading ``start`` slot is present.

        ``gold_start_paragraphs`` consumes a leading ``start`` as resolution 1's own
        position rather than as a transition, so such a day carries K_e slots.
        """
        slots = transitions(day)
        return day["k_e"] if slots and slots[0].get("kind") == "start" else day["k_e"] - 1

    complete = sum(1 for d in sample["days"] if len(transitions(d)) == expected_slots(d))
    mid_paragraph = sum(1 for d in sample["days"] for b in transitions(d) if b.get("unit") == "mid_paragraph")
    gaps = sum(1 for d in sample["days"] for b in (d.get("boundaries") or []) if b.get("preceded_by_gap"))
    date_cuts = sum(
        1
        for d in sample["days"]
        for b in (d.get("boundaries") or [])
        if b.get("kind") in ("date_start", "date_end")
    )
    starts_mid = sum(1 for d in sample["days"] if d.get("starts_mid_resolution"))
    has_end_marker = sum(
        1
        for d in sample["days"]
        for b in (d.get("boundaries") or [])
        if b.get("kind") == "end_of_last_resolution"
    )
    print(f"Days with exactly K_e - 1 transitions (cut + START): {complete} / {len(sample['days'])}")
    print(f"Mid-paragraph transitions recorded: {mid_paragraph}")
    print(f"Boilerplate gaps (END..START) recorded: {gaps}")
    print(f"Date cuts (DATE_END/DATE_START) recorded: {date_cuts}")
    print(f"Days flagged starts_mid_resolution: {starts_mid}")
    print(f"Days with an explicit trailing END marker: {has_end_marker}")


if __name__ == "__main__":
    main()

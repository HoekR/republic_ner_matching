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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_alignment_new import OUTPUT_DIR, load_data
from build_boundary_annotation_ui import (
    MARKER,
    MARKER_DATE_END,
    MARKER_DATE_START,
    MARKER_END,
    MARKER_START,
    SEPARATOR,
    flat_paragraph_stream,
)

SAMPLE_FILE = OUTPUT_DIR / "boundary_gold_sample.json"
ANNOTATIONS_FILE = OUTPUT_DIR / "boundary_gold_annotations.json"


def parse_markers(
    annotated_text: str,
    cut_marker: str,
    end_marker: str,
    start_marker: str,
    date_end_marker: str = MARKER_DATE_END,
    date_start_marker: str = MARKER_DATE_START,
) -> list[tuple[int, str]]:
    """Single-pass scan: ordered (base_offset, type) tokens with all markers removed.

    type is one of "cut", "end", "start", "date_end", "date_start". Longer date
    markers are matched before END / START RES so prefixes do not collide.
    """
    # Longest-first so DATE_END does not match as END, etc.
    catalog = sorted(
        [
            (date_end_marker, "date_end"),
            (date_start_marker, "date_start"),
            (start_marker, "start"),
            (end_marker, "end"),
            (cut_marker, "cut"),
        ],
        key=lambda item: len(item[0]),
        reverse=True,
    )
    tokens: list[tuple[int, str]] = []
    base_pos = 0
    i = 0
    n = len(annotated_text)
    while i < n:
        matched = False
        for marker, kind in catalog:
            if marker and annotated_text.startswith(marker, i):
                tokens.append((base_pos, kind))
                i += len(marker)
                matched = True
                break
        if not matched:
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
        cursor = end + len(separator)
    return {"paragraph_stream_index": len(paragraphs) - 1, "unit": "out_of_range", "char_offset": None}


def build_boundaries(
    tokens: list[tuple[int, str]], paragraphs: list[dict[str, Any]], separator: str, base_len: int
) -> list[dict[str, Any]]:
    """Turn ordered markers into boundary records: cuts, gaps, date cuts, trailing end."""
    boundaries: list[dict[str, Any]] = []
    for i, (offset, kind) in enumerate(tokens):
        if kind == "cut":
            boundaries.append({**locate_cut(offset, paragraphs, separator), "kind": "cut"})
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
    for day in sample["days"]:
        state = annotated_by_date.get(day["date"])
        if state is None:
            continue
        annotated_text = state.get("text", "")

        paragraphs = flat_paragraph_stream(res_df, day["flat_ids"])
        base_len = sum(len(p["text"]) for p in paragraphs) + len(separator) * max(0, len(paragraphs) - 1)
        tokens = parse_markers(
            annotated_text,
            marker,
            marker_end,
            marker_start,
            marker_date_end,
            marker_date_start,
        )
        boundaries = build_boundaries(tokens, paragraphs, separator, base_len)

        day["boundaries"] = boundaries
        day["starts_mid_resolution"] = bool(state.get("startsMid", False))
        day["annotator"] = args.annotator
        day["annotated_at"] = now
        updated += 1

    args.sample.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Merged {updated} annotated day(s) into {args.sample}")

    def transitions(day: dict[str, Any]) -> list[dict[str, Any]]:
        return [b for b in (day.get("boundaries") or []) if b.get("kind") in ("cut", "start")]

    complete = sum(1 for d in sample["days"] if len(transitions(d)) == d["k_e"] - 1)
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

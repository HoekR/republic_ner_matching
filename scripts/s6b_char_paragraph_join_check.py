#!/usr/bin/env python3
"""Step 2 of plans/archive/STAGED_ANCHOR_CONSOLIDATION.md: verify the char-to-paragraph join.

`scripts/s6b_anchor_harvest.py` records every anchor (groups A/B/C/D) as a `char_position`
into the concatenation of one day's `axis_for_date(...)` paragraphs, with no separator
between paragraphs (`scripts.s6a_char_axis_evaluation.char_starts`). The DP
(`build_alignment_new.align_session`) and the pathology-corpus span tooling
(`scripts/pathology_corpus_stage_a.py`) both key off paragraph INDEX, not char position --
so before any anchor tier beyond group A can be wired into either, this mapping has to be
checked, not assumed (guardrail 6 in the plan doc).

Two things verified here, on the three pathology-corpus seed days only (cheap, same idiom as
`plans/PATHOLOGY_CORPUS_RUNLOG.md` Step 1):

1. `axis_for_date` (what the DP actually scores against) is identical, paragraph-for-paragraph,
   to the same-calendar-day axis grouping `s6b_anchor_harvest.py` used to compute char
   positions. If these diverge for a date, the harvest's char_position for that date is in the
   wrong coordinate space and cannot be reused as-is.
2. Every harvested anchor's char_position resolves to exactly one in-bounds paragraph index
   (or, for the two `session_boundary` sentinels, to "before paragraph 0" / "at end of axis").
   Group A (`tier1_entity_nw`) results are additionally cross-checked against the paragraph
   indices already hand-verified for 1630-02-22 in the pathology-corpus Step 1 ledger
   (enriched index -> paragraph: 9->1, 11->4, 12->5, 14->7, 23->8, 25->10, 26->11).

Usage:
    PYTHONPATH=. uv run python -m scripts.s6b_char_paragraph_join_check
"""

from __future__ import annotations

import bisect
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.s4_corpus_paragraph_predictions import axis_for_date
from scripts.s6a_char_axis_evaluation import char_starts

HARVEST_DATASET = "s6b_anchor_harvest"

SEED_DAYS = ["1630-02-22", "1629-06-03", "1627-10-06"]

# Pathology-corpus Step 1 ledger, already gated against production (plans/PATHOLOGY_CORPUS_RUNLOG.md).
EXPECTED_1630_02_22 = {9: 1, 11: 4, 12: 5, 14: 7, 23: 8, 25: 10, 26: 11}


def resolve_paragraph(char_position: int, starts: list[int], n_paragraphs: int, total_chars: int) -> str:
    """Map a char_position to a paragraph index, or a named boundary sentinel."""
    if char_position == total_chars:
        return "end_of_axis"
    if char_position < 0 or char_position > total_chars:
        return "out_of_bounds"
    index = bisect.bisect_right(starts, char_position) - 1
    if not 0 <= index < n_paragraphs:
        return "out_of_bounds"
    return str(index)


def check_day(
    date: str,
    axis_by_date: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
    harvest_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_axis = axis_by_date.get(date, [])
    resolved_axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
    raw_ids = [r["axis_id"] for r in raw_axis]
    resolved_ids = [r["axis_id"] for r in resolved_axis]
    axes_match = raw_ids == resolved_ids

    starts = char_starts(resolved_axis)
    total_chars = (starts[-1] + len(resolved_axis[-1]["text"])) if resolved_axis else 0
    n_paragraphs = len(resolved_axis)

    rows = [r for r in harvest_rows if r["date"] == date]
    by_channel: dict[str, dict[str, Any]] = {}
    out_of_bounds_examples: list[dict[str, Any]] = []
    for row in rows:
        channel = row["channel"]
        bucket = by_channel.setdefault(channel, {"n": 0, "mapped": 0, "out_of_bounds": 0})
        bucket["n"] += 1
        label = resolve_paragraph(row["char_position"], starts, n_paragraphs, total_chars)
        if label == "out_of_bounds":
            bucket["out_of_bounds"] += 1
            if len(out_of_bounds_examples) < 5:
                out_of_bounds_examples.append(row)
        else:
            bucket["mapped"] += 1

    # Cross-check group A against the already-verified ledger, where we have one.
    tier1_check = None
    if date == "1630-02-22":
        mismatches = []
        seen = set()
        for row in rows:
            if row["channel"] != "tier1_entity_nw":
                continue
            enriched_index = row["payload"].get("enriched_index")
            if enriched_index not in EXPECTED_1630_02_22:
                continue
            seen.add(enriched_index)
            label = resolve_paragraph(row["char_position"], starts, n_paragraphs, total_chars)
            expected = str(EXPECTED_1630_02_22[enriched_index])
            if label != expected:
                mismatches.append({"enriched_index": enriched_index, "got": label, "expected": expected})
        tier1_check = {
            "expected_indices": sorted(EXPECTED_1630_02_22),
            "seen_indices": sorted(seen),
            "mismatches": mismatches,
        }

    return {
        "date": date,
        "axes_match": axes_match,
        "raw_paragraph_count": len(raw_ids),
        "resolved_paragraph_count": len(resolved_ids),
        "n_paragraphs": n_paragraphs,
        "by_channel": by_channel,
        "out_of_bounds_examples": out_of_bounds_examples,
        "tier1_check": tier1_check,
    }


def main() -> None:
    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    harvest_rows = [r for r in load(HARVEST_DATASET) if r.get("date") in SEED_DAYS]

    results = [
        check_day(date, axis_by_date, axis_by_session, session_by_date, harvest_rows)
        for date in SEED_DAYS
    ]

    all_axes_match = all(r["axes_match"] for r in results)
    all_in_bounds = all(
        sum(b["out_of_bounds"] for b in r["by_channel"].values()) == 0 for r in results
    )
    # NOT part of the join-mechanics gate: a tier1_entity_nw mismatch here means the HARVEST's
    # group A (read from the stored `alignment_1626_1630` TIER1 rows) disagrees with production's
    # live align_session anchors -- already measured at 62.9% exact-position agreement corpus-wide
    # (docs/DECISIONS.md 2026-09-29, anchor_set_reconciliation.py) and explicitly NOT fixed by that
    # decision's rebuild, which left s6b_anchor_harvest.py's group A untouched. A mismatch here is
    # expected, not a join bug: it means any future wiring of groups B/C/D alongside group A must
    # recompute group A live (as scripts/pathology_corpus_stage_a.py / span_verdict_for_day already
    # do) rather than reuse the harvest file's tier1_entity_nw rows.
    tier1_stale_count = sum(
        len(r["tier1_check"]["mismatches"]) + len(set(r["tier1_check"]["expected_indices"]) - set(r["tier1_check"]["seen_indices"]))
        for r in results
        if r["tier1_check"]
    )

    print(f"seed_days={SEED_DAYS}")
    for r in results:
        print(f"\n{r['date']}: axes_match={r['axes_match']} "
              f"(raw={r['raw_paragraph_count']}, resolved={r['resolved_paragraph_count']})")
        for channel, bucket in sorted(r["by_channel"].items()):
            print(f"  {channel}: n={bucket['n']} mapped={bucket['mapped']} "
                  f"out_of_bounds={bucket['out_of_bounds']}")
        if r["out_of_bounds_examples"]:
            print(f"  out_of_bounds_examples={r['out_of_bounds_examples']}")
        if r["tier1_check"]:
            print(f"  tier1_check: expected={r['tier1_check']['expected_indices']} "
                  f"seen={r['tier1_check']['seen_indices']} "
                  f"mismatches={r['tier1_check']['mismatches']}")

    print(f"\nJOIN-MECHANICS GATE: axes_match_all_seeds={all_axes_match} "
          f"all_anchors_in_bounds={all_in_bounds}")
    print("PASS" if (all_axes_match and all_in_bounds) else "FAIL")
    print(f"\nKNOWN-ISSUE CHECK (informational, not part of the gate above): "
          f"harvest tier1_entity_nw vs. live production anchors, "
          f"stale/missing/mismatched count on 1630-02-22 = {tier1_stale_count} / "
          f"{len(EXPECTED_1630_02_22)} checked -- expected nonzero, see docs/DECISIONS.md "
          f"2026-09-29. Group A must be recomputed live for any B/C/D wiring, not read from "
          f"this harvest file's tier1_entity_nw rows.")


if __name__ == "__main__":
    main()

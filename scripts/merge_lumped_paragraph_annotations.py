#!/usr/bin/env python3
"""Merge exported lumped-paragraph annotations into verified gold.

Usage:
    uv run python scripts/merge_lumped_paragraph_annotations.py [--annotator NAME]

Reads ``output/lumped_paragraph_gold_annotations.json`` (UI export), strips
``|||CUT|||`` markers to recover char offsets, and writes
``lumped_paragraph_boundary_gold``.

Verdict handling (``lumped_paragraph_labeller.store.VERDICTS``, v2 export):

- ``cuts``       → gold row with the human's offsets. ``expected_cuts`` (from the
                   concordance's ``n_share``) is *not* enforced: it is the prediction
                   under test, so constraining gold by it would bake the hypothesis
                   into the gold. Mismatches are flagged ``expected_cuts_disagrees``
                   and reported, not rejected.
- ``no_cut``     → gold row with ``gold_offsets: []``. An informative negative: the
                   concordance claimed ``n_share>=2`` on this paragraph and the human
                   says there is no interior cut, so the lump is spurious. Kept as
                   gold, not dropped.
- ``false_lump`` → ``record_type: "false_lump"`` quarantine row, written to the same
                   file so the judgement is not discarded, but excluded from gold.
- ``skip``       → not emitted; counted in meta.

Legacy v1 rows (``skip``/``labelled`` only) are normalised through the store, which
infers a verdict from cut count and notes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve, save_semi_structured
from lumped_paragraph_labeller.store import START_MARKER, normalize_annotation
from scripts.build_lumped_paragraph_annotation_ui import MARKER

SCAFFOLD_DATASET = "lumped_paragraph_gold_scaffold"
ANNOTATIONS_FILE = PROJECT_ROOT / "output" / "lumped_paragraph_gold_annotations.json"
OUTPUT_DATASET = "lumped_paragraph_boundary_gold"
FOREIGN_MARKER_RE = re.compile(r"\|\|\|[A-Z_]+\|\|\|")


def parse_markers(
    annotated_text: str, marker: str = MARKER, start_marker: str = START_MARKER
) -> tuple[str, list[int], list[int]]:
    """Return ``(clean_text, cut_offsets, start_offsets)``, all offsets in clean_text.

    Both markers are stripped in one pass so every offset indexes the same clean
    text; splitting on them separately would leave the other marker's characters in
    the string and shift everything after it.
    """
    pattern = re.compile(f"{re.escape(marker)}|{re.escape(start_marker)}")
    cuts: list[int] = []
    starts: list[int] = []
    clean_parts: list[str] = []
    running = 0
    pos = 0
    for match in pattern.finditer(annotated_text):
        chunk = annotated_text[pos : match.start()]
        clean_parts.append(chunk)
        running += len(chunk)
        (starts if match.group() == start_marker else cuts).append(running)
        pos = match.end()
    clean_parts.append(annotated_text[pos:])
    return "".join(clean_parts), cuts, starts


def parse_cut_offsets(annotated_text: str, marker: str = MARKER) -> tuple[str, list[int]]:
    """Back-compat wrapper: ``(clean_text, cut_offsets)`` only."""
    clean, cuts, _ = parse_markers(annotated_text, marker)
    return clean, cuts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotator", default=None)
    args = parser.parse_args()

    if not ANNOTATIONS_FILE.exists():
        raise FileNotFoundError(
            f"{ANNOTATIONS_FILE} not found. Export from lumped_paragraph_annotation_ui.html first."
        )

    resolve(SCAFFOLD_DATASET)
    scaffold = [r for r in load(SCAFFOLD_DATASET) if r.get("record_type") == "candidate"]
    by_id = {str(r["example_id"]): r for r in scaffold}
    exported = json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    marker = exported.get("marker", MARKER)
    annotations = exported.get("annotations") or {}
    now = datetime.now(timezone.utc).isoformat()

    gold_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    problems: list[str] = []
    disagreements: list[str] = []
    skipped = 0
    by_verdict: dict[str, int] = {}
    for example_id, state in annotations.items():
        base = by_id.get(str(example_id))
        if base is None:
            continue
        if not isinstance(state, dict):
            continue
        state = normalize_annotation(state)
        verdict = str(state.get("verdict") or "cuts")
        if verdict == "skip":
            skipped += 1
            by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
            continue
        if not state.get("labelled", True):
            # UI always sets labelled=true on save; skip incomplete drafts.
            continue
        annotated_text = str(state.get("text") or "")
        clean, offsets, starts = parse_markers(annotated_text, marker)
        expected = int(base.get("expected_cuts") or 0)
        if len(starts) > 1:
            problems.append(f"  {example_id}: {len(starts)} start markers; at most one is meaningful")
            continue
        head_offset = starts[0] if starts else None
        # A marker the merge does not know (e.g. the hand-typed |||START||| in the
        # 2026-09-28 rows) would otherwise be baked into the gold text as literal
        # characters and shift every offset after it.
        foreign = FOREIGN_MARKER_RE.findall(clean)
        if foreign:
            problems.append(f"  {example_id}: unrecognised marker(s) {', '.join(sorted(set(foreign)))}")
            continue
        if verdict == "cuts" and not offsets:
            problems.append(f"  {example_id}: verdict 'cuts' but no cut marker present")
            continue
        if verdict == "cuts" and len(offsets) != expected:
            # NOT an error. ``expected_cuts`` is derived from the concordance's
            # ``n_share``, which is exactly what P3 is testing; letting it constrain
            # the gold would make the gold agree with the hypothesis by construction
            # (same contamination shape as the ``para_index == 0`` case). The human
            # is the gold, the concordance is the prediction. Recorded, reported,
            # never enforced.
            disagreements.append(f"  {example_id}: concordance expected {expected}, human cut {len(offsets)}")
        if verdict in {"no_cut", "false_lump"} and offsets:
            problems.append(
                f"  {example_id}: verdict {verdict!r} but {len(offsets)} cut marker(s) present"
            )
            continue
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
        row = {
            "record_type": "gold" if verdict in {"cuts", "no_cut"} else "false_lump",
            "verdict": verdict,
            "example_id": example_id,
            "date": base["date"],
            "paragraph_stream_index": base["paragraph_stream_index"],
            "flat_id": base.get("flat_id"),
            "para_index": base.get("para_index"),
            "text": clean if clean else base.get("text"),
            "text_char_len": len(clean) if clean else base.get("text_char_len"),
            "n_resolutions": base["n_resolutions"],
            "expected_cuts": expected,
            "gold_offsets": offsets,
            "n_cuts": len(offsets),
            "expected_cuts_disagrees": len(offsets) != expected,
            # Where resolution text begins; text before it is non-resolution matter
            # (attendance list, heading). None = the paragraph starts in resolution
            # text. Never a cut: it is the paragraph's head, not an interior start.
            "head_offset": head_offset,
            "resolution_ids": base.get("resolution_ids"),
            "resolution_indices": base.get("resolution_indices"),
            "uncertain": bool(state.get("uncertain")),
            "clutter": bool(state.get("clutter")),
            "paragraph_notes": str(state.get("paragraph_notes") or ""),
            "cut_notes": str(state.get("cut_notes") or ""),
            "review_status": "verified",
            "annotator": args.annotator,
            "annotated_at": now,
            "stratum": base.get("stratum"),
        }
        if row["record_type"] == "gold":
            gold_rows.append(row)
        else:
            quarantine_rows.append(row)

    if problems:
        raise SystemExit(
            f"{len(problems)} annotation(s) inconsistent with their verdict — nothing written:\n"
            + "\n".join(problems)
            + "\nFix each in the UI (adjust the cuts, or change the verdict), then re-run."
        )

    meta = {
        "record_type": "meta",
        "track": "lumped_paragraph_boundary_gold",
        "description": "Hand-labeled mid_paragraph cuts inside lumped HTR paragraphs.",
        "parent_datasets": [SCAFFOLD_DATASET],
        "n_gold": len(gold_rows),
        "n_false_lump": len(quarantine_rows),
        "n_skipped": skipped,
        "n_scaffold_candidates": len(scaffold),
        "by_verdict": by_verdict,
        "n_expected_cuts_disagree": len(disagreements),
        "annotator": args.annotator,
        "merged_at": now,
    }
    path = save_semi_structured(
        [meta, *gold_rows, *quarantine_rows], logical_name=OUTPUT_DATASET, script=__file__
    )
    n_with_cuts = sum(1 for r in gold_rows if r["n_cuts"])
    print(
        f"Merged {len(gold_rows)} gold paragraphs "
        f"({n_with_cuts} with cuts, {len(gold_rows) - n_with_cuts} no_cut), "
        f"{len(quarantine_rows)} false_lump quarantined, {skipped} skipped "
        f"of {len(scaffold)} candidates → {path}"
    )
    if disagreements:
        print(
            f"{len(disagreements)} paragraph(s) where the human cut count differs from the "
            "concordance (kept as gold, flagged expected_cuts_disagrees):"
        )
        print("\n".join(disagreements))


if __name__ == "__main__":
    main()

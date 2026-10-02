#!/usr/bin/env python3
"""Step 4 redirect, control test (plans/STAGED_ANCHOR_CONSOLIDATION.md): is the TF-IDF
diagonal-relaxation gain measured by `s6c_semantic_anchor_isolation_check.py` real content
signal, or just whichever direction an entity-score tie happens to break in?

That script found: (1) zero genuinely new hard anchors form from the semantic path anywhere
in the 50 `boundary_gold_sample` days -- the gate's `min_semantic_threshold=0.35` is never
cleared by real TF-IDF similarity in this population (observed values ~0.001-0.003); (2) the
entire +6-fixes/0-breaks gain comes from re-ranking cells *already tied on entity evidence*,
using a `sem_sim` value far below the channel's own measured noise floor (0.0201 margin,
`docs/DECISIONS.md` 2026-09-29 TF-IDF discrimination eval). Two hand-inspected examples
(1629-10-15, 1626-01-08) disagreed on whether that tie-break looks like real content
discrimination or coincidental direction.

This control replaces real `sem_sim` with a synthetic matrix that is deterministic,
content-blind, and strictly decreasing in enriched-resolution row index `i` -- i.e. "when
tied on entity evidence, always prefer the earlier-numbered resolution" -- scaled small
enough (max ~0.001) that it can only move an exact entity-score tie, never outweigh a real
entity_match_score difference or clear the 0.35 anchor-eligibility gate. If this content-free
rule reproduces the same ~6 fixes / 0 breaks, the measured TF-IDF gain is an artifact of
*which* direction ties happen to resolve, not of semantic content. If it does not, the real
`sem_sim` values are doing something a row-order rule can't.

No dataset write, no manifest entry -- diagnostic only.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6c_tiebreak_control_check
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import numpy as np

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.pathology_corpus_stage_a import load_combined_overlap
from scripts.s4_corpus_paragraph_predictions import axis_for_date, grouped_enriched
from scripts.s4_paragraph_axis_baseline import build_axis_overlap
from scripts.s6c_gap_segmentation import build_anchor_backbone, segment_day
from scripts.separated_accuracy_eval import gold_start_paragraphs

GOLD_DATASET = "boundary_gold_sample"
SEMANTIC_WEIGHT = 0.5  # same magnitude as production, so the DP's score landscape is comparable
MIN_SEMANTIC_THRESHOLD = 0.35  # unchanged -- the control must never clear this either


def earliest_row_matrix(n_rows: int, n_cols: int) -> np.ndarray:
    """Strictly decreasing in row index, identical across columns, max value ~0.001 --
    large enough to break an exact entity-score tie via `sem_score = sem_sim * 0.5`,
    small enough (<0.0005 contribution) to never outweigh a real entity_match_score
    difference (idf weights are >= 1.0) or approach the 0.35 anchor-eligibility gate."""
    row_values = (n_rows - np.arange(n_rows)) / (n_rows * 1000.0)
    return np.tile(row_values[:, None], (1, n_cols))


def classify_backbone(
    backbone: list[tuple[int, int]],
    enriched_ids: list[str],
    axis_ids: list[str],
    overlap_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    enriched_count: int,
) -> dict[int, str]:
    category: dict[int, str] = {}
    for enriched_index, axis_index in backbone:
        if not (0 < enriched_index < enriched_count):
            continue
        shared = overlap_lookup.get((enriched_ids[enriched_index], axis_ids[axis_index]), set())
        entity_match_score = sum(idf_weights.get(e, 1.0) for e in shared)
        category[enriched_index] = "entity_anchor" if entity_match_score > 0 else "semantic_new_anchor"
    return category


def check_day(
    date: str,
    day: dict[str, Any],
    axis_by_date: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
    combined_overlap,
    idf_weights: dict[str, float],
    enriched_by_date: dict[str, list[str]],
) -> dict[str, Any]:
    axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
    enriched_ids = enriched_by_date.get(date)
    result: dict[str, Any] = {"date": date, "by_class": defaultdict(Counter)}
    if not axis or not enriched_ids:
        result["skipped"] = "missing_htr_or_enriched"
        return result

    k_e = len(enriched_ids)
    gold_starts = gold_start_paragraphs(day, k_e)
    axis_ids = [record["axis_id"] for record in axis]
    overlap_lookup = build_axis_overlap(axis, combined_overlap)

    entity_only_alignments = align_session(enriched_ids, axis_ids, overlap_lookup, idf_weights)

    fake_sim = earliest_row_matrix(k_e, len(axis_ids))
    faketie_alignments = align_session(
        enriched_ids, axis_ids, overlap_lookup, idf_weights,
        similarity_matrix=fake_sim,
        semantic_weight=SEMANTIC_WEIGHT,
        min_semantic_threshold=MIN_SEMANTIC_THRESHOLD,
    )

    backbone_faketie = build_anchor_backbone(k_e, len(axis_ids), faketie_alignments)
    category = classify_backbone(backbone_faketie, enriched_ids, axis_ids, overlap_lookup, idf_weights, k_e)
    assert all(v == "entity_anchor" for v in category.values()), (
        "control leaked past the anchor-eligibility gate -- scale earlier_row_matrix down"
    )

    positions_entity_only = segment_day(k_e, len(axis_ids), entity_only_alignments)
    positions_faketie = segment_day(k_e, len(axis_ids), faketie_alignments)

    for absolute_index in range(1, k_e):
        gold_position = gold_starts[absolute_index] if absolute_index < len(gold_starts) else None
        if gold_position is None:
            continue
        klass = category.get(absolute_index, "gap_filled")
        pos_only = positions_entity_only[absolute_index - 1]
        pos_fake = positions_faketie[absolute_index - 1]
        bucket = result["by_class"][klass]
        bucket["scored"] += 1
        bucket["only_exact"] += pos_only == gold_position
        bucket["fake_exact"] += pos_fake == gold_position
        if pos_only != pos_fake:
            bucket["changed"] += 1
            if pos_fake == gold_position and pos_only != gold_position:
                bucket["fixes"] += 1
            if pos_only == gold_position and pos_fake != gold_position:
                bucket["breaks"] += 1
    return result


def main() -> None:
    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    combined_overlap = load_combined_overlap()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_by_date = grouped_enriched()

    gold = load(GOLD_DATASET)
    days_by_date = {str(day["date"]): day for day in gold["days"]}
    dates = sorted(days_by_date)
    print(f"gold days: {len(dates)}")

    totals: dict[str, Counter] = defaultdict(Counter)
    for date in dates:
        r = check_day(
            date, days_by_date[date], axis_by_date, axis_by_session, session_by_date,
            combined_overlap, idf_weights, enriched_by_date,
        )
        if r.get("skipped"):
            continue
        changed_any = any(c["changed"] for c in r["by_class"].values())
        for klass, counts in r["by_class"].items():
            totals[klass].update(counts)
        if changed_any:
            line = [date] + [
                f"{klass}: scored={c['scored']} only={c['only_exact']} fake={c['fake_exact']} "
                f"fixes={c['fixes']} breaks={c['breaks']}"
                for klass, c in r["by_class"].items() if c["changed"]
            ]
            print(" | ".join(line))

    print("\n=== earliest-row control: summary across 50 gold days ===")
    total_fixes = total_breaks = total_changed = 0
    for klass in ("entity_anchor", "gap_filled"):
        counts = totals[klass]
        scored = counts["scored"] or 1
        total_fixes += counts["fixes"]
        total_breaks += counts["breaks"]
        total_changed += counts["changed"]
        print(
            f"{klass}: scored={counts['scored']} entity_only_exact={counts['only_exact']} "
            f"({counts['only_exact'] / scored:.1%}) faketie_exact={counts['fake_exact']} "
            f"({counts['fake_exact'] / scored:.1%}) changed={counts['changed']} "
            f"fixes={counts['fixes']} breaks={counts['breaks']}"
        )
    print(f"\nTOTAL changed={total_changed} fixes={total_fixes} breaks={total_breaks}")
    print("(compare to real TF-IDF sem_sim: changed=14 fixes=6 breaks=0, from s6c_semantic_anchor_isolation_check.py)")


if __name__ == "__main__":
    main()

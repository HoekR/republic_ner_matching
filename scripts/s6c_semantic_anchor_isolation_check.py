#!/usr/bin/env python3
"""Step 4 redirect (plans/archive/STAGED_ANCHOR_CONSOLIDATION.md): isolate what the already-shipped
TF-IDF diagonal relaxation actually contributes as a *hard anchor* channel.

`align_session`'s `anchor_only_diagonal` gate (`build_alignment_new.py:938`) already accepts a
diagonal move when `entity_match_score > 0` **or** `sem_sim >= min_semantic_threshold` -- i.e. 4b's
"relax the gate to accept any channel that clears a threshold" is not a proposal here, it is
`docs/DECISIONS.md` 2026-09-29's shipped production default (`semantic_backend=tfidf,
semantic_weight=0.5`), measured corpus-wide (+69 resolutions, +0.9% of ceiling) and on gold days
(lumped F1@tol150 +0.0112). But that prior measurement used lumped-paragraph F1 at a tolerance,
not this track's exact-start-paragraph convention, and it never separated two different effects:

1. **Genuinely new hard anchors** -- a cell with zero entity overlap that TF-IDF similarity alone
   made eligible for a diagonal (`entity_match_score == 0` at the chosen cell -- the gate's own
   `has_anchor` definition means this can only have happened via the semantic branch).
2. **Re-ranking among already-anchored cells** -- entity overlap already made the cell eligible;
   `semantic_weight` only changed which already-legal diagonal scored best.

Only (1) is the thing Step 4a/4b's framing was actually asking about: can a non-entity channel
contribute real, independent hard anchors. (2) is a different, already-settled question. This
script classifies every backbone anchor the production config produces into one of
`entity_anchor` / `semantic_new_anchor` / `gap_filled` (not a direct NW anchor at all), and scores
each class's exact-start-paragraph agreement against the 50 `boundary_gold_sample` days, alongside
the entity-only (`semantic_weight=0.0`) baseline for the same resolutions -- guardrail 5: gap-mass
is implicit in how many `semantic_new_anchor` cells exist at all; correctness is reported
separately and is the deciding number.

No dataset write, no manifest entry -- diagnostic only, same posture as the Group B/C pre-checks.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6c_semantic_anchor_isolation_check
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from alignment_embeddings import AlignmentEmbedder
from build_alignment_new import align_session, calculate_idf_weights
from data_io import load
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.pathology_corpus_stage_a import load_combined_overlap
from scripts.s4_corpus_paragraph_predictions import axis_for_date, grouped_enriched
from scripts.s4_paragraph_axis_baseline import (
    build_axis_overlap,
    compute_similarity_matrix,
    extract_axis_texts,
    load_enriched_texts_by_date,
)
from scripts.s6c_gap_segmentation import build_anchor_backbone, segment_day
from scripts.separated_accuracy_eval import gold_start_paragraphs

GOLD_DATASET = "boundary_gold_sample"
SEMANTIC_WEIGHT = 0.5  # production default, docs/DECISIONS.md 2026-09-29
MIN_SEMANTIC_THRESHOLD = 0.35  # production default


def classify_backbone(
    backbone: list[tuple[int, int]],
    enriched_ids: list[str],
    axis_ids: list[str],
    overlap_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    enriched_count: int,
) -> dict[int, str]:
    """enriched_index -> 'entity_anchor' | 'semantic_new_anchor', for interior backbone points only."""
    category: dict[int, str] = {}
    for enriched_index, axis_index in backbone:
        if not (0 < enriched_index < enriched_count):
            continue  # sentinel
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
    embedder: AlignmentEmbedder,
    enriched_texts_by_date: dict[str, dict[str, str]],
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

    axis_texts = extract_axis_texts(axis)
    enriched_texts = enriched_texts_by_date.get(date, [])
    similarity_matrix = (
        compute_similarity_matrix(enriched_texts, axis_texts, embedder)
        if axis_texts and len(enriched_texts) == k_e
        else None
    )
    if similarity_matrix is None:
        result["skipped"] = "enriched_text_count_mismatch"
        return result
    entity_semantic_alignments = align_session(
        enriched_ids, axis_ids, overlap_lookup, idf_weights,
        similarity_matrix=similarity_matrix,
        semantic_weight=SEMANTIC_WEIGHT,
        min_semantic_threshold=MIN_SEMANTIC_THRESHOLD,
    )

    backbone_semantic = build_anchor_backbone(k_e, len(axis_ids), entity_semantic_alignments)
    category = classify_backbone(backbone_semantic, enriched_ids, axis_ids, overlap_lookup, idf_weights, k_e)

    positions_entity_only = segment_day(k_e, len(axis_ids), entity_only_alignments)
    positions_entity_semantic = segment_day(k_e, len(axis_ids), entity_semantic_alignments)

    for absolute_index in range(1, k_e):
        gold_position = gold_starts[absolute_index] if absolute_index < len(gold_starts) else None
        if gold_position is None:
            continue
        klass = category.get(absolute_index, "gap_filled")
        pos_only = positions_entity_only[absolute_index - 1]
        pos_sem = positions_entity_semantic[absolute_index - 1]
        bucket = result["by_class"][klass]
        bucket["scored"] += 1
        bucket["only_exact"] += pos_only == gold_position
        bucket["sem_exact"] += pos_sem == gold_position
        if pos_only != pos_sem:
            bucket["changed"] += 1
            if pos_sem == gold_position and pos_only != gold_position:
                bucket["fixes"] += 1
            if pos_only == gold_position and pos_sem != gold_position:
                bucket["breaks"] += 1
    return result


def main() -> None:
    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    combined_overlap = load_combined_overlap()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_by_date = grouped_enriched()
    embedder = AlignmentEmbedder(backend="tfidf")
    enriched_texts_by_date = load_enriched_texts_by_date()

    gold = load(GOLD_DATASET)
    days_by_date = {str(day["date"]): day for day in gold["days"]}
    dates = sorted(days_by_date)
    print(f"gold days: {len(dates)}")

    totals: dict[str, Counter] = defaultdict(Counter)
    for date in dates:
        r = check_day(
            date, days_by_date[date], axis_by_date, axis_by_session, session_by_date,
            combined_overlap, idf_weights, enriched_by_date, embedder, enriched_texts_by_date,
        )
        if r.get("skipped"):
            print(f"{date}: skipped ({r['skipped']})")
            continue
        line = [date]
        for klass, counts in r["by_class"].items():
            totals[klass].update(counts)
            line.append(f"{klass}: scored={counts['scored']} only={counts['only_exact']} sem={counts['sem_exact']}")
        print(" | ".join(line))

    print("\n=== summary across 50 gold days ===")
    for klass in ("entity_anchor", "semantic_new_anchor", "gap_filled"):
        counts = totals[klass]
        scored = counts["scored"] or 1
        print(
            f"{klass}: scored={counts['scored']} "
            f"entity_only_exact={counts['only_exact']} ({counts['only_exact'] / scored:.1%}) "
            f"entity_semantic_exact={counts['sem_exact']} ({counts['sem_exact'] / scored:.1%}) "
            f"changed={counts['changed']} fixes={counts['fixes']} breaks={counts['breaks']}"
        )


if __name__ == "__main__":
    main()

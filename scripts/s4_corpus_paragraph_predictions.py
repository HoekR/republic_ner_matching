#!/usr/bin/env python3
"""Run S4 entity-NW interpolation across all 1626-1630 calendar days.

This runner is separate from the 50-day boundary-gold benchmark. It emits
corpus predictions or explicit abstentions and never reads review labels.

Optional: wire semantic similarity into the alignment via --semantic_backend and --semantic_weight.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Ensure root directory is in path for imports
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from alignment_embeddings import AlignmentEmbedder, EmbeddingBackend
from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, resolve, save_semi_structured
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, overlap_enriched_id
from scripts.s6c_gap_segmentation import (
    RANK_NORMALIZATIONS,
    segment_day,
    similarity_position_scores,
    similarity_rank_scores,
)


AXIS_DATASET = "paragraph_axis_1626_1630"
ENRICHED_DATASET = "enriched_resolutions_1626_1630"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "s4_corpus_paragraph_predictions"
OVERLAP_DATASETS = ("place_overlap_1626_1630", "org_overlap_1626_1630", "per_overlap_1626_1630")


def enriched_key(item: dict[str, Any], date: str) -> str | None:
    value = item.get("volgnr")
    if value is None or not str(value).strip():
        index = item.get("resolution_index")
        if index is None:
            return None
        value = f"{date}_{int(index)}"
    return overlap_enriched_id(str(value).strip(), date)


def grouped_enriched() -> dict[str, list[str]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in load(ENRICHED_DATASET):
        date = str(item.get("date", ""))[:10]
        if "1626-01-01" <= date <= "1630-12-31":
            by_date[date].append(item)
    grouped: dict[str, list[str]] = {}
    for date, items in by_date.items():
        items.sort(key=lambda item: item.get("resolution_index", 0))
        keys = [enriched_key(item, date) for item in items]
        if all(keys):
            grouped[date] = [str(key) for key in keys]
    return grouped


def session_of(flat_id: str) -> str:
    return str(flat_id).split("-resolution-", 1)[0]


def resolved_sessions() -> dict[str, str]:
    """Best day-level resolved HTR session per enriched date, from the day-status-resolution
    track (`resolution_concordance_1626_1630`, "accepted final" per docs/DECISIONS.md).

    Built independently of this predictor's own raw calendar-date axis grouping, and already
    resolves some cross-day/candidate-scored session mappings (confident entity-overlap
    scoring over ledger `-1`/`+1`/`?` rows, `docs/CANDIDATE_SCORING_AND_CONCORDANCE.md`) that
    grouping by calendar date alone cannot see -- this was the orphan STEP_S6 section 1(b)
    warned about: several resolution mechanisms built and not talking to each other. Human-
    approved `-1`/`+1` decisions are not yet included (`docs/SESSION_DATE_MAPPING_REVIEW.md`:
    review still pending), so this only recovers what candidate scoring already resolved
    automatically.
    """
    concordance = load(CONCORDANCE_DATASET)
    resolved = concordance.loc[concordance["day_status"] == "resolved_auto", ["enriched_date", "resolved_session_id"]]
    resolved = resolved.dropna().drop_duplicates("enriched_date")
    return {str(row.enriched_date): str(row.resolved_session_id) for row in resolved.itertuples(index=False)}


def axis_for_date(
    date: str,
    axis_by_date: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
) -> list[dict[str, Any]]:
    """The concordance-resolved session's paragraphs when one exists; otherwise same-calendar-day
    paragraphs.

    `session_by_date` only holds dates with `day_status == "resolved_auto"` -- the accepted-final
    day-mapping track (`resolution_concordance_1626_1630`). A non-empty same-day axis is not by
    itself proof the sitting belongs on that calendar date: `resolutions_flat`'s session numbering
    has drifted from the archive (`docs/DECISIONS.md` 2026-09-21 "S4f review"), so a thin
    same-calendar stub can coexist with a richer session that concordance has already resolved to a
    neighboring date. Preferring the resolved session over an unconditional same-day check corrects
    that (`docs/DECISIONS.md` 2026-09-22 "axis_for_date must not treat non-empty same_day as a day
    cutoff"). Falls back to the same-calendar-day axis when no resolved session is recorded for this
    date, or its axis is empty (a dataset gap, not evidence the calendar date is wrong)."""
    session_id = session_by_date.get(date)
    if session_id:
        resolved_axis = axis_by_session.get(session_id, [])
        if resolved_axis:
            return resolved_axis
    return axis_by_date.get(date, [])


def load_enriched_texts_by_date() -> dict[str, list[str]]:
    """Load enriched resolution full texts (as summaries), ordered by resolution_index per date."""
    by_date: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for item in load(ENRICHED_DATASET):
        date = str(item.get("date", ""))[:10]
        if "1626-01-01" <= date <= "1630-12-31":
            # Use 'text' field if available; otherwise fall back to concatenating 'title' + other fields
            text = item.get("text", "")
            if not text or not str(text).strip():
                text = item.get("summary", "")
            if not text or not str(text).strip():
                text = item.get("title", "") or ""
            idx = item.get("resolution_index", 0)
            by_date[date].append((idx, str(text).strip() if text else " "))

    result = {}
    for date, indexed_texts in by_date.items():
        indexed_texts.sort(key=lambda x: x[0])
        result[date] = [text for _, text in indexed_texts]
    return result


def extract_axis_texts(axis_records: list[dict[str, Any]]) -> list[str]:
    """Extract paragraph texts from axis records, maintaining order."""
    texts = []
    for record in axis_records:
        # Priority: 'text', 'para', or 'content' field names common in paragraph_axis
        text = record.get("text", "") or record.get("para", "") or record.get("content", "")
        texts.append(str(text).strip() if text else " ")
    return texts


def compute_similarity_matrix(
    enriched_texts: list[str],
    axis_texts: list[str],
    embedder: AlignmentEmbedder,
) -> np.ndarray | None:
    """Compute semantic similarity matrix; return None on error (graceful degradation)."""
    try:
        if not enriched_texts or not axis_texts:
            return None
        matrix = embedder.compute_similarity_matrix(enriched_texts, axis_texts)
        return matrix if matrix is not None else None
    except Exception as e:
        print(f"Warning: failed to compute similarity matrix: {e}", file=sys.stderr)
        return None


def predict(
    date: str,
    enriched_ids: list[str],
    axis: list[dict[str, Any]],
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    position_scores: dict[int, float] | None = None,
    similarity_matrix: np.ndarray | None = None,
    semantic_weight: float = 0.0,
    min_semantic_threshold: float = 0.35,
    similarity_position_scale: float = 0.0,
    similarity_rank_scale: float = 0.0,
    similarity_rank_normalize: str = "rownorm",
    resolution_scores: dict[int, dict[int, float]] | None = None,
) -> dict[str, Any]:
    base = {"date": date, "k_e": len(enriched_ids), "paragraph_count": len(axis), "unit": "paragraph_stream"}
    if not axis:
        return {**base, "status": "abstained", "reason": "missing_htr", "boundaries": []}
    axis_ids = [record["axis_id"] for record in axis]
    # Wire semantic similarity into align_session if available
    alignments = align_session(
        enriched_ids,
        axis_ids,
        lookup,
        idf_weights,
        similarity_matrix=similarity_matrix,
        semantic_weight=semantic_weight,
        min_semantic_threshold=min_semantic_threshold,
    )
    # S6c count-constrained segmentation DP (scripts/s6c_gap_segmentation.py) replaces
    # interpolate_positions here, same as the gold-day baseline -- see that module's
    # docstring. Group-C phrase-hit evidence was tried and measured NEGATIVE on the
    # gold-day sample (docs/DECISIONS.md 2026-09-21): net worse tol0 F1 (0.644 -> 0.622)
    # and WindowDiff, only marginal tol1/tol2 gains -- not wired in here. Do not re-add
    # without new evidence; see that decision for the full comparison and why
    # snap_boundaries (the gold pipeline's second phrase-evidence stage) didn't rescue it.
    # `position_scores` defaults to None (empty) so the live default is unchanged; it exists
    # so scripts/s6_group_b_position_scores_eval.py can pass Group-B evidence through this
    # exact codepath without duplicating it -- see that script before wiring anything live.
    # If similarity_position_scale > 0, build position_scores from the similarity matrix.
    if similarity_position_scale > 0 and similarity_matrix is not None:
        sim_scores = similarity_position_scores(similarity_matrix, scale=similarity_position_scale)
        if position_scores is None:
            position_scores = sim_scores
        else:
            # Merge with existing position_scores, preferring higher value
            position_scores = {**position_scores, **{k: max(position_scores.get(k, 0), v) for k, v in sim_scores.items()}}
    # Per-rank (per-resolution) similarity is the other wiring of the same matrix: it keeps
    # the rows apart instead of taking the per-paragraph max, so the DP scores each slot with
    # its own resolution's profile. An explicit `resolution_scores` from a caller wins over
    # rebuilding one here, the same way `position_scores` does.
    if resolution_scores is None and similarity_rank_scale > 0 and similarity_matrix is not None:
        resolution_scores = similarity_rank_scores(
            similarity_matrix, scale=similarity_rank_scale, normalize=similarity_rank_normalize
        )
    positions = segment_day(
        len(enriched_ids), len(axis_ids), alignments, position_scores, resolution_scores
    )
    return {
        **base,
        "status": "predicted",
        "reason": None,
        "boundaries": [
            {"paragraph_stream_index": position, "char_offset": 0, "kind": "cut", "source": "s6c_gap_segmentation"}
            for position in positions
            if position is not None
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run S4 corpus paragraph predictions with optional semantic similarity wiring.",
    )
    parser.add_argument(
        "--semantic_backend",
        type=str,
        default="tfidf",
        choices=["tfidf", "ollama", "transformers"],
        help="Backend for semantic similarity computation (default: tfidf). Set to 'tfidf' for fast TF-IDF baseline.",
    )
    parser.add_argument(
        "--semantic_weight",
        type=float,
        default=0.0,
        help="Weight for semantic similarity in the NW aligner (default: 0.0, off). Range: 0.0-5.0 for testing.",
    )
    parser.add_argument(
        "--min_semantic_threshold",
        type=float,
        default=0.35,
        help="Minimum semantic similarity to allow a diagonal match in NW anchor gate (default: 0.35).",
    )
    parser.add_argument(
        "--similarity_position_scale",
        type=float,
        default=0.0,
        help="Scale factor for TF-IDF similarity as position_scores bonus in S6c gap-filling (default: 0.0, off). Test with 0.5-1.0.",
    )
    parser.add_argument(
        "--similarity_rank_scale",
        type=float,
        default=0.0,
        help="Scale factor for PER-RESOLUTION TF-IDF similarity as S6c rank_scores (default: 0.0, off). Unlike --similarity_position_scale this keeps the matrix's rows apart instead of taking the per-paragraph max.",
    )
    parser.add_argument(
        "--similarity_rank_normalize",
        type=str,
        default="rownorm",
        choices=list(RANK_NORMALIZATIONS),
        help="How to turn a similarity row into a bonus for --similarity_rank_scale (default: rownorm, each resolution's best paragraph scores the full scale).",
    )
    args = parser.parse_args()

    axis = load(AXIS_DATASET)
    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        axis_by_date[str(record["date"])].append(record)
        axis_by_session[session_of(record["flat_id"])].append(record)
    session_by_date = resolved_sessions()
    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [overlap.rename(columns={"naam": "name"}) if "name" not in overlap and "naam" in overlap else overlap for overlap in overlaps]
    combined = pd.concat(overlaps, ignore_index=True)
    lookup = build_axis_overlap(axis, combined)
    idf_weights = calculate_idf_weights(combined)

    # Initialize semantic similarity if any of the three consumers of the matrix is active
    # (the NW aligner's semantic_weight, the per-paragraph position_scores bonus, or the
    # per-resolution rank_scores bonus).
    needs_similarity = (
        args.semantic_weight > 0
        or args.similarity_position_scale > 0
        or args.similarity_rank_scale > 0
    )
    embedder: AlignmentEmbedder | None = None
    enriched_texts_by_date: dict[str, list[str]] = {}
    if needs_similarity:
        print(f"Initializing semantic similarity: backend={args.semantic_backend}, weight={args.semantic_weight}, position_scale={args.similarity_position_scale}, rank_scale={args.similarity_rank_scale} ({args.similarity_rank_normalize})")
        embedder = AlignmentEmbedder(backend=args.semantic_backend)
        enriched_texts_by_date = load_enriched_texts_by_date()
        print(f"Loaded enriched texts for {len(enriched_texts_by_date)} dates")

    predictions = []
    for date, enriched_ids in sorted(grouped_enriched().items()):
        axis_records = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)

        # Compute similarity matrix if any consumer of it is active
        similarity_matrix = None
        if needs_similarity and embedder is not None:
            enriched_texts = enriched_texts_by_date.get(date, [])
            axis_texts = extract_axis_texts(axis_records)
            if enriched_texts and axis_texts:
                similarity_matrix = compute_similarity_matrix(enriched_texts, axis_texts, embedder)

        pred = predict(
            date,
            enriched_ids,
            axis_records,
            lookup,
            idf_weights,
            position_scores=None,
            similarity_matrix=similarity_matrix,
            semantic_weight=args.semantic_weight,
            min_semantic_threshold=args.min_semantic_threshold,
            similarity_position_scale=args.similarity_position_scale,
            similarity_rank_scale=args.similarity_rank_scale,
            similarity_rank_normalize=args.similarity_rank_normalize,
        )
        predictions.append(pred)

    output = save_semi_structured(predictions, logical_name=OUTPUT_DATASET, script=__file__)
    recovered = sum(
        1
        for date in grouped_enriched()
        if not axis_by_date.get(date) and axis_by_session.get(session_by_date.get(date, ""))
    )
    # "Overridden" only counts days where the resolved session's axis actually differs in
    # content from the same-day stub -- for most resolved_auto dates the two agree (the
    # resolved session IS that date's own session, just reached via a different key), so
    # comparing axis_ids rather than mere truthiness avoids inflating this figure with
    # cosmetic routing changes (docs/DECISIONS.md 2026-09-22).
    overridden = sum(
        1
        for date in grouped_enriched()
        if (same_day := axis_by_date.get(date))
        and (resolved := axis_by_session.get(session_by_date.get(date, "")))
        and [r["axis_id"] for r in same_day] != [r["axis_id"] for r in resolved]
    )
    print(f"Wrote {len(predictions)} corpus-day predictions to {output}")
    print(f"Status counts: {dict(Counter(item['status'] for item in predictions))}")
    print(f"Abstentions: {dict(Counter(item['reason'] for item in predictions if item['status'] == 'abstained'))}")
    print(f"Days recovered via resolution_concordance_1626_1630's resolved_session_id (no same-day axis otherwise): {recovered}")
    print(f"Days where the resolved session's axis differs from the same-day stub (docs/DECISIONS.md 2026-09-22): {overridden}")
    if needs_similarity:
        print(f"Semantic similarity: backend={args.semantic_backend}, weight={args.semantic_weight}, position_scale={args.similarity_position_scale}, rank_scale={args.similarity_rank_scale} ({args.similarity_rank_normalize})")


if __name__ == "__main__":
    main()
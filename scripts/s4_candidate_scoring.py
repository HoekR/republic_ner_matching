#!/usr/bin/env python3
"""Score HTR session candidates for A/X/?/-1/+1-status session-date ledger rows.

Prototype for Step 2 of ``docs/CANDIDATE_SCORING_AND_CONCORDANCE.md``: rank
each row's candidate sessions by combined entity-IDF overlap and dense
text similarity against the row's enriched resolution text. Produces ranked
suggestions for human review; it does not auto-select a candidate.

Extended (Step 3) to the nearby-candidate statuses ``-1``/``+1`` (one
previous- or next-day session candidate) and ``?`` (multiple previous-
and/or next-day candidates, unioned) using the same ``score_candidates``
core -- no new matching logic.
"""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz

from alignment_embeddings import AlignmentEmbedder
from build_entity_surface_matches import FUZZY_THRESHOLD
from scripts.build_session_date_mapping_review_ui import _candidate_text
from scripts.s4_session_date_mapping_predictions import _as_list


STATUS_CANDIDATE_COLUMNS = {
    "A": "trusted_session_ids",
    "X": "exact_date_session_ids",
    "-1": "previous_day_session_ids",
    "+1": "next_day_session_ids",
}
# "?" rows are ambiguous across both nearby-day columns rather than one, so
# they are unioned instead of looked up via STATUS_CANDIDATE_COLUMNS.
AMBIGUOUS_NEARBY_STATUS = "?"
AMBIGUOUS_NEARBY_COLUMNS = ("previous_day_session_ids", "next_day_session_ids")

# Data-driven floor from the 7-row A/X verification set (2 Sep 2026): every
# correct top candidate had entity_overlap_score in [30.7, 107.1]; every
# problem case (2 nihil actum, 1 genuinely missing HTR content) had exactly
# 0.0, with no borderline values in between. Zero entity overlap is treated
# as "no confident match" -- dense similarity alone did not separate the
# cases (0.20-0.28 for correct rows, but also 0.20 for the wrong one).
#
# Raised 0.0 -> 5.0 after eyeballing a stratified sample of the 603
# ?/-1/+1 rows (17 Sep 2026): top picks with entity_overlap_score under 5
# were consistently not good matches, so the original 7-row floor was too
# permissive at this larger scale. See docs/CANDIDATE_SCORING_AND_CONCORDANCE.md.
MIN_CONFIDENT_ENTITY_OVERLAP = 5.0

# Eyeballing the 603 ?/-1/+1 rows (17 Sep 2026) found a day's enriched text is
# formulaic -- "Nihil Actum" or "Nihil Actum: <reason>." -- for 146/610 rows
# (23.9%), concentrated in ?/+1. Confirmed corpus-wide: 162/1595 enriched
# dates are purely "Nihil Actum" with no mixed nihil/real-content dates, so
# these carry no real content to match. Scoring them anyway produced a
# spurious top pick from real HTR content on that date in nearly every case
# (matched HTR was itself flagged nihil actum only once) -- not a scoring
# failure to tune, a category that should abstain rather than be scored.
NIHIL_ACTUM_PATTERN = re.compile(r"^\s*nihil\s+actum\b", re.IGNORECASE)


def is_nihil_actum(enriched_text: str) -> bool:
    """True when a date's enriched text is the formulaic 'nothing done' entry."""
    return bool(NIHIL_ACTUM_PATTERN.match(enriched_text.strip()))


def session_text(records: list[dict[str, Any]]) -> str:
    """Concatenate flat resolution text for one candidate session."""
    return " ".join(text for text in (_candidate_text(record) for record in records) if text)


def shared_entities(
    enriched_ids: list[str],
    axis_ids: list[str],
    overlap_lookup: dict[tuple[str, str], set[str]],
) -> set[str]:
    """Union of entities a row's enriched resolutions share with one candidate session."""
    result: set[str] = set()
    for enriched_id in enriched_ids:
        for axis_id in axis_ids:
            result |= overlap_lookup.get((enriched_id, axis_id), set())
    return result


def score_candidates(
    enriched_text: str,
    candidate_texts: dict[str, str],
    idf_weights: dict[str, float] | None = None,
    candidate_entities: dict[str, set[str]] | None = None,
    embedder: AlignmentEmbedder | None = None,
    min_confident_entity_overlap: float = MIN_CONFIDENT_ENTITY_OVERLAP,
) -> list[dict[str, Any]]:
    """Rank candidates by combined entity-IDF overlap and dense text similarity.

    Entity overlap is an unbounded IDF-weighted sum and is the dominant
    signal when present; dense TF-IDF cosine similarity is bounded to
    [0, 1] and acts as a secondary signal, breaking ties among candidates
    with equal or absent entity evidence. The top-ranked candidate is
    marked ``low_confidence`` when its entity overlap does not clear
    ``min_confident_entity_overlap`` -- a suggestion only, never auto-selected.
    """
    idf_weights = idf_weights or {}
    candidate_entities = candidate_entities or {}
    session_ids = list(candidate_texts)
    embedder = embedder or AlignmentEmbedder(backend="tfidf")
    similarity = embedder.compute_similarity_matrix(
        [enriched_text], [candidate_texts[session_id] for session_id in session_ids]
    )
    dense_similarities = similarity[0] if similarity.size else [0.0] * len(session_ids)

    scored = []
    for session_id, dense_similarity in zip(session_ids, dense_similarities):
        entities = candidate_entities.get(session_id, set())
        entity_overlap_score = sum(idf_weights.get(entity, 1.0) for entity in entities)
        scored.append(
            {
                "session_id": session_id,
                "entity_overlap_score": entity_overlap_score,
                "shared_entities": sorted(entities),
                "dense_similarity": float(dense_similarity),
                "combined_score": entity_overlap_score + float(dense_similarity),
                "low_confidence": entity_overlap_score <= min_confident_entity_overlap,
            }
        )
    return sorted(scored, key=lambda item: item["combined_score"], reverse=True)


def text_confirmed_names(names: list[str], text: str, threshold: int = FUZZY_THRESHOLD) -> set[str]:
    """Names confirmed present in ``text``: exact substring first, rapidfuzz
    ``partial_ratio`` fallback -- same method and threshold as
    ``build_entity_surface_matches.py``'s ``confirm_candidates``, applied
    directly to a caller-supplied name list instead of an annotation-derived
    shortlist.

    Used for the window-widen follow-up: the axis-based ``overlap_lookup``
    (this module's normal entity source, built from pre-built Excel overlap
    tables) does literal substring matching at build time and therefore
    misses spelling variants (e.g. "Carleton" in flat text vs. "Carlisle" as
    the enriched resolution's canonical name) -- confirmed by spot-check to
    silently zero out real matches for wide-window candidates. See
    docs/CANDIDATE_SCORING_AND_CONCORDANCE.md.
    """
    text_lower = text.lower()
    confirmed: set[str] = set()
    for name in names:
        if not name:
            continue
        name_lower = name.lower()
        if name_lower in text_lower or fuzz.partial_ratio(name_lower, text_lower) >= threshold:
            confirmed.add(name)
    return confirmed


def candidate_session_ids(row: dict[str, Any]) -> list[str]:
    """Return one ledger row's candidate session ids for its status code.

    ``?`` rows are ambiguous across the previous- and next-day columns
    (rather than one column, as for the other statuses), so they are
    unioned and deduplicated. Unsupported statuses return an empty list.
    """
    status = str(row.get("status_code"))
    if status == AMBIGUOUS_NEARBY_STATUS:
        ids: list[str] = []
        for column in AMBIGUOUS_NEARBY_COLUMNS:
            ids.extend(_as_list(row.get(column)))
        return sorted(set(ids))
    column = STATUS_CANDIDATE_COLUMNS.get(status)
    return _as_list(row.get(column)) if column else []


def score_ledger_row(
    row: dict[str, Any],
    enriched_text_by_date: dict[str, str],
    flat_by_session: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    overlap_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    embedder: AlignmentEmbedder | None = None,
    min_confident_entity_overlap: float = MIN_CONFIDENT_ENTITY_OVERLAP,
    candidate_ids: list[str] | None = None,
    enriched_entity_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Score one ledger row's candidates; empty for unsupported statuses or a
    nihil actum enriched date (see ``is_nihil_actum``).

    ``candidate_ids`` overrides the status-code-based ``candidate_session_ids``
    lookup -- used for the window-widen follow-up, where a row's candidates
    come from a wider-offset recovery lookup rather than a ledger column.

    ``enriched_entity_names``, when given, replaces the axis-based
    ``overlap_lookup`` entity source with a direct ``text_confirmed_names``
    check of these names against each candidate's text -- also for the
    window-widen follow-up, since wide-window candidates are cross-day pairs
    the Excel overlap tables were never built against.
    """
    session_ids = candidate_ids if candidate_ids is not None else candidate_session_ids(row)
    if not session_ids:
        return []
    enriched_text = enriched_text_by_date.get(str(row["enriched_date"]), "")
    if is_nihil_actum(enriched_text):
        return []
    candidate_texts = {session_id: session_text(flat_by_session.get(session_id, [])) for session_id in session_ids}
    if enriched_entity_names is not None:
        candidate_entities = {
            session_id: text_confirmed_names(enriched_entity_names, candidate_texts[session_id])
            for session_id in session_ids
        }
    else:
        enriched_ids = _as_list(row.get("enriched_ids"))
        candidate_entities = {
            session_id: shared_entities(
                enriched_ids,
                [record["axis_id"] for record in axis_by_session.get(session_id, [])],
                overlap_lookup,
            )
            for session_id in session_ids
        }
    return score_candidates(
        enriched_text, candidate_texts, idf_weights, candidate_entities, embedder, min_confident_entity_overlap
    )

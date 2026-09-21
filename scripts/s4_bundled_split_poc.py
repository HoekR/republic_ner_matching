#!/usr/bin/env python3
"""POC: place interior split points inside gold "bundled" paragraphs.

Background: `s4_entity_density_split_diagnostic.py` confirmed that gold
"bundled" paragraphs (where 2+ resolution-boundary annotations collapse onto
one paragraph-axis position) have measurably higher entity_annotation_count
than clean single-boundary paragraphs (common-language effect size 0.770).
This script tests the next step named in PLAN.md: can that entity signal
actually place the interior cut point(s), not just flag the paragraph?

Gold boundary annotations of unit "mid_paragraph" carry an exact in-text
`char_offset`, so those 22 bundled positions have real character-level
ground truth to score against (unlike the paragraph-index-only boundaries
used elsewhere in S4).

Two stages are compared on the same 22-position batch, per the current
session's plan:
  1. Baseline -- entity spans from the existing LOC-/ORG-/PER-annotations
     layer only (the same upstream tagger already used everywhere else).
  2. Augmented -- baseline spans plus a scoped dictionary lookup against
     `entity_surface_matches_1626_1630` (canonical LOC/PER names already
     confirmed present somewhere in that flat resolution's text), to recover
     entities the upstream tagger missed, restricted to just these flagged
     paragraphs.

The delta between stage 1 and stage 2 hit rates is the thing this POC exists
to measure -- not an attempt to solve split-point placement outright.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Sequence

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

from data_io import load, save_semi_structured
from scripts.build_boundary_gold_paragraph_axis import match_annotation_to_paragraph
from scripts.s4_entity_density_split_diagnostic import (
    AXIS_DATASET,
    CONTENT_KINDS,
    GOLD_DATASET,
    classify_positions,
    content_boundary_indices,
    review_codes,
)

OUTPUT_DATASET = "s4_bundled_split_poc"
ANNOTATION_DATASETS = ("loc_annotations", "org_annotations", "per_annotations")
SURFACE_MATCH_DATASET = "entity_surface_matches_1626_1630"
PHRASE_DATASET = "s4_opening_phrase_candidates"
MID_PARAGRAPH_UNIT = "mid_paragraph"
TOLERANCES = (50, 150)
MIN_DICTIONARY_NAME_LENGTH = 3
PHRASE_SNAP_MAX_DISTANCE = 150


def locate_span(text: str, needle: str, start: int = 0) -> tuple[int, int] | None:
    """Find `needle` in `text` at or after `start`; whitespace-flexible fallback."""
    needle = needle.strip()
    if not needle:
        return None
    pos = text.casefold().find(needle.casefold(), start)
    if pos != -1:
        return pos, pos + len(needle)
    pattern = re.compile(r"\s+".join(re.escape(word) for word in needle.split()), re.IGNORECASE)
    match = pattern.search(text, start)
    return (match.start(), match.end()) if match else None


def locate_instances(text: str, tag_texts: Sequence[str]) -> list[tuple[int, int]]:
    """Locate one span per tag_text occurrence, advancing per-needle cursors for repeats."""
    cursors: dict[str, int] = defaultdict(int)
    spans: list[tuple[int, int]] = []
    for needle in tag_texts:
        key = needle.casefold().strip()
        if not key:
            continue
        span = locate_span(text, needle, cursors[key])
        if span is None:
            continue
        spans.append(span)
        cursors[key] = span[1]
    return sorted(set(spans))


def locate_dictionary_matches(
    text: str, canonical_names: Sequence[str], min_length: int = MIN_DICTIONARY_NAME_LENGTH
) -> list[tuple[int, int]]:
    """Scan `text` for every occurrence of any canonical name (word-boundary, case-insensitive)."""
    spans: list[tuple[int, int]] = []
    for name in canonical_names:
        name = name.strip()
        if len(name) < min_length:
            continue
        pattern = re.compile(r"\b" + r"\s+".join(re.escape(word) for word in name.split()) + r"\b", re.IGNORECASE)
        spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
    return spans


def merge_spans(*span_lists: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Union spans across sources, keeping only non-overlapping additions in call order."""
    merged: list[tuple[int, int]] = []
    for spans in span_lists:
        for span in spans:
            if any(span[0] < existing[1] and span[1] > existing[0] for existing in merged):
                continue
            merged.append(span)
    return sorted(merged)


def propose_cuts(spans: Sequence[tuple[int, int]], k: int) -> list[int] | None:
    """Split `spans` into k+1 contiguous groups; return the k gap midpoints, or None if too few spans."""
    if k <= 0:
        return []
    ordered = sorted(spans)
    if len(ordered) < k + 1:
        return None
    n = len(ordered)
    cuts = []
    for i in range(1, k + 1):
        split_idx = max(1, min(n - 1, round(i * n / (k + 1))))
        prev_end = ordered[split_idx - 1][1]
        next_start = ordered[split_idx][0]
        cut = (prev_end + next_start) // 2 if next_start > prev_end else next_start
        cuts.append(cut)
    return cuts


def phrase_offsets(text: str, searcher: FuzzyPhraseSearcher) -> list[tuple[int, str, float]]:
    """Return every recurring-opening phrase match's (offset, phrase_string, similarity) in `text`."""
    matches = searcher.find_matches({"id": "paragraph", "text": text})
    return [(match.offset, match.phrase.phrase_string, match.levenshtein_similarity) for match in matches]


def snap_cut_to_phrase(
    cut: int, offsets: Sequence[tuple[int, str, float]], max_distance: int = PHRASE_SNAP_MAX_DISTANCE
) -> tuple[int, tuple[str, float] | None]:
    """Snap `cut` to the nearest phrase-match offset, but only within a local neighborhood."""
    nearby = [offset for offset in offsets if abs(offset[0] - cut) <= max_distance]
    if not nearby:
        return cut, None
    position, phrase, similarity = min(nearby, key=lambda item: (abs(item[0] - cut), -item[2], -len(item[1])))
    return position, (phrase, similarity)


def snap_predicted_cuts(
    cuts: Sequence[int], offsets: Sequence[tuple[int, str, float]], max_distance: int = PHRASE_SNAP_MAX_DISTANCE
) -> list[tuple[int, tuple[str, float] | None]]:
    """Snap each cut independently, keeping only snaps that preserve strict increasing order.

    Mirrors `s4_paragraph_axis_baseline.snap_boundaries`'s per-boundary, order-preserving
    approach so a single collision only falls back for the colliding cut, not the whole day.
    """
    snapped: list[tuple[int, tuple[str, float] | None]] = []
    prev_accepted = -1
    for index, cut in enumerate(cuts):
        upper_bound = cuts[index + 1] if index + 1 < len(cuts) else None
        candidate, hit = snap_cut_to_phrase(cut, offsets, max_distance)
        if hit is not None and prev_accepted < candidate and (upper_bound is None or candidate < upper_bound):
            snapped.append((candidate, hit))
            prev_accepted = candidate
        else:
            snapped.append((cut, None))
            prev_accepted = cut
    return snapped


def score_predicted_cuts(predicted: Sequence[int], gold: Sequence[int], tolerance: int) -> int:
    """Greedy nearest-match count of predicted cuts within `tolerance` chars of a distinct gold cut."""
    remaining = list(gold)
    hits = 0
    for cut in predicted:
        if not remaining:
            break
        nearest = min(remaining, key=lambda g: abs(g - cut))
        if abs(nearest - cut) <= tolerance:
            hits += 1
            remaining.remove(nearest)
    return hits


def bundled_positions(gold: dict[str, Any], axis: list[dict[str, Any]], codes: dict[str, str]) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        by_date[str(record["date"])].append(record)

    eligible = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S" and int(day["k_e"]) > 1]

    positions: list[dict[str, Any]] = []
    for day in eligible:
        date = str(day["date"])
        day_axis = by_date.get(date, [])
        content_indices = content_boundary_indices(day)
        if not content_indices or not day_axis:
            continue
        for index, count in classify_positions(content_indices).items():
            if count <= 1 or index >= len(day_axis):
                continue
            mid_offsets = sorted(
                int(boundary["char_offset"])
                for boundary in day.get("boundaries", [])
                if boundary.get("kind") in CONTENT_KINDS
                and boundary.get("paragraph_stream_index") == index
                and boundary.get("unit") == MID_PARAGRAPH_UNIT
                and boundary.get("char_offset") is not None
            )
            if not mid_offsets:
                continue
            record = day_axis[index]
            positions.append(
                {
                    "date": date,
                    "paragraph_stream_index": index,
                    "flat_id": record["flat_id"],
                    "para_index": record["para_index"],
                    "text": record["text"],
                    "target_splits": len(mid_offsets),
                    "gold_offsets": mid_offsets,
                }
            )
    return positions


def match_annotations_to_positions(target_flat_ids: set[str]) -> dict[tuple[str, int], list[str]]:
    axis = load(AXIS_DATASET)
    paragraph_by_flat: dict[str, list[str]] = defaultdict(list)
    for record in axis:
        if record["flat_id"] in target_flat_ids:
            paragraph_by_flat[record["flat_id"]].append(record["text"])

    matches: dict[tuple[str, int], list[str]] = defaultdict(list)
    for dataset in ANNOTATION_DATASETS:
        for annotation in load(dataset):
            reference = annotation.get("reference") or {}
            flat_id = str(reference.get("resolution_id") or "").strip()
            if flat_id not in target_flat_ids:
                continue
            para_index = match_annotation_to_paragraph(reference.get("tag_text", ""), paragraph_by_flat[flat_id])
            if para_index is None:
                continue
            matches[(flat_id, para_index)].append(str(reference.get("tag_text", "")))
    return matches


def dictionary_names_by_flat(target_flat_ids: set[str]) -> dict[str, list[str]]:
    surface = load(SURFACE_MATCH_DATASET)
    surface = surface[surface["resolution_id"].isin(target_flat_ids)]
    names: dict[str, list[str]] = defaultdict(list)
    for row in surface.itertuples(index=False):
        names[str(row.resolution_id)].append(str(row.canonical_name))
    return names


def main() -> None:
    gold = load(GOLD_DATASET)
    axis = load(AXIS_DATASET)
    codes = review_codes()

    phrase_candidates = load(PHRASE_DATASET)[0]["candidates"]
    phrases = [item["phrase"] for item in phrase_candidates if item["word_count"] >= 3]
    searcher = FuzzyPhraseSearcher(
        phrases,
        config={"char_match_threshold": 0.85, "ngram_threshold": 0.85, "levenshtein_threshold": 0.85},
    )

    positions = bundled_positions(gold, axis, codes)
    target_flat_ids = {position["flat_id"] for position in positions}
    tag_matches = match_annotations_to_positions(target_flat_ids)
    dict_names = dictionary_names_by_flat(target_flat_ids)

    stages = ("stage1_ner_only", "stage2_ner_plus_dictionary", "stage1_phrase_snapped", "stage2_phrase_snapped")
    rows: list[dict[str, Any]] = []
    tally = {stage: {"abstain": 0, **{f"hits_tol{t}": 0 for t in TOLERANCES}} for stage in stages}
    total_gold_cuts = 0

    for position in positions:
        text = position["text"]
        k = position["target_splits"]
        gold_offsets = position["gold_offsets"]
        total_gold_cuts += k

        stage1_spans = locate_instances(text, tag_matches.get((position["flat_id"], position["para_index"]), []))
        dictionary_spans = locate_dictionary_matches(text, dict_names.get(position["flat_id"], []))
        stage2_spans = merge_spans(stage1_spans, dictionary_spans)

        stage1_cuts = propose_cuts(stage1_spans, k)
        stage2_cuts = propose_cuts(stage2_spans, k)
        offsets = phrase_offsets(text, searcher)
        stage1_snapped = [cut for cut, _ in snap_predicted_cuts(stage1_cuts, offsets)] if stage1_cuts is not None else None
        stage2_snapped = [cut for cut, _ in snap_predicted_cuts(stage2_cuts, offsets)] if stage2_cuts is not None else None

        predicted = {
            "stage1_ner_only": stage1_cuts,
            "stage2_ner_plus_dictionary": stage2_cuts,
            "stage1_phrase_snapped": stage1_snapped,
            "stage2_phrase_snapped": stage2_snapped,
        }

        row = {
            "date": position["date"],
            "flat_id": position["flat_id"],
            "para_index": position["para_index"],
            "target_splits": k,
            "gold_offsets": gold_offsets,
            "n_entities_stage1": len(stage1_spans),
            "n_entities_stage2": len(stage2_spans),
            "n_phrase_hits": len(offsets),
        }
        for stage, cuts in predicted.items():
            row[f"{stage}_predicted"] = cuts
            if cuts is None:
                tally[stage]["abstain"] += 1
            else:
                for tolerance in TOLERANCES:
                    row[f"{stage}_hits_tol{tolerance}"] = score_predicted_cuts(cuts, gold_offsets, tolerance)
                    tally[stage][f"hits_tol{tolerance}"] += row[f"{stage}_hits_tol{tolerance}"]
        rows.append(row)

    output = save_semi_structured(rows, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(rows)} bundled-position rows to {output}")
    print(f"positions={len(positions)}; total interior gold cuts={total_gold_cuts}")
    for stage, counts in tally.items():
        attempted = len(positions) - counts["abstain"]
        print(f"\n{stage}: attempted {attempted}/{len(positions)} (abstained {counts['abstain']})")
        for tolerance in TOLERANCES:
            hits = counts[f"hits_tol{tolerance}"]
            print(f"  tol={tolerance}: {hits}/{total_gold_cuts} gold cuts recovered ({hits / total_gold_cuts:.1%})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Evaluate S2 opening signals at manually annotated resolution starts."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

from build_alignment_new import OPENING_FORMULA
from data_io import load, save_semi_structured


GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
PHRASE_DATASET = "s4_opening_phrase_candidates"
OUTPUT_DATASET = "s4_opening_phrase_cut_evaluation_full"
FUZZY_PHRASE_THRESHOLD = 0.85


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def text_after_cut(axis: list[dict[str, Any]], paragraph_index: int, char_offset: int | None) -> str:
    """Return text beginning at a gold cut, continuing into the next paragraph if needed."""
    offset = char_offset or 0
    following = axis[paragraph_index]["text"][offset:]
    if following.strip():
        return following
    return " ".join(record["text"] for record in axis[paragraph_index + 1 : paragraph_index + 3])


def matching_phrase(text: str, phrases: list[str]) -> str | None:
    normalized = normalized_text(text)
    matches = [phrase for phrase in phrases if normalized.startswith(phrase)]
    return max(matches, key=len) if matches else None


def fuzzy_matching_phrase(text: str, phrases: list[str]) -> tuple[str, float] | None:
    """Find the strongest fuzzy_search phrase match beginning at the cut."""
    exact = matching_phrase(text, phrases)
    if exact:
        return exact, 1.0
    searcher = FuzzyPhraseSearcher(
        phrases,
        config={
            "char_match_threshold": FUZZY_PHRASE_THRESHOLD,
            "ngram_threshold": FUZZY_PHRASE_THRESHOLD,
            "levenshtein_threshold": FUZZY_PHRASE_THRESHOLD,
        },
    )
    matches = [match for match in searcher.find_matches({"id": "cut", "text": normalized_text(text)}) if match.offset == 0]
    if not matches:
        return None
    best = max(matches, key=lambda match: (match.levenshtein_similarity, len(match.phrase.phrase_string)))
    return best.phrase.phrase_string, best.levenshtein_similarity


def main() -> None:
    gold = load(GOLD_DATASET)
    phrase_data = load(PHRASE_DATASET)[0]
    phrases = sorted(
        (normalized_text(item["phrase"]) for item in phrase_data["candidates"]),
        key=len,
        reverse=True,
    )
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        by_date[str(record["date"])].append(record)

    observations: list[dict[str, Any]] = []
    for day in gold["days"]:
        axis = by_date[str(day["date"])]
        for boundary in day.get("boundaries", []):
            if boundary.get("kind") not in {"cut", "start"}:
                continue
            index = boundary.get("paragraph_stream_index")
            if index is None or not 0 <= int(index) < len(axis):
                continue
            text = text_after_cut(axis, int(index), boundary.get("char_offset"))
            phrase = matching_phrase(text, phrases)
            fuzzy_match = fuzzy_matching_phrase(text, phrases)
            observations.append(
                {
                    "date": day["date"],
                    "paragraph_stream_index": int(index),
                    "char_offset": boundary.get("char_offset"),
                    "unit": boundary.get("unit"),
                    "kind": boundary["kind"],
                    "opening_formula_hit": bool(OPENING_FORMULA.match(text.strip())),
                    "full_phrase": phrase,
                    "full_fuzzy_phrase": fuzzy_match[0] if fuzzy_match else None,
                    "full_fuzzy_score": fuzzy_match[1] if fuzzy_match else None,
                    "opening_text": text[:240],
                }
            )

    formula_hits = sum(item["opening_formula_hit"] for item in observations)
    phrase_hits = sum(item["full_phrase"] is not None for item in observations)
    fuzzy_phrase_hits = sum(item["full_fuzzy_phrase"] is not None for item in observations)
    summary = {
        "boundary_count": len(observations),
        "opening_formula_hits": formula_hits,
        "opening_formula_rate": formula_hits / len(observations) if observations else 0.0,
        "full_phrase_hits": phrase_hits,
        "full_phrase_rate": phrase_hits / len(observations) if observations else 0.0,
        "full_fuzzy_phrase_hits": fuzzy_phrase_hits,
        "full_fuzzy_phrase_rate": fuzzy_phrase_hits / len(observations) if observations else 0.0,
        "by_unit": {
            unit: {
                "count": len(items),
                "formula_rate": sum(item["opening_formula_hit"] for item in items) / len(items),
                "phrase_rate": sum(item["full_phrase"] is not None for item in items) / len(items),
                "fuzzy_phrase_rate": sum(item["full_fuzzy_phrase"] is not None for item in items) / len(items),
            }
            for unit, items in ((unit, [item for item in observations if item["unit"] == unit]) for unit in {item["unit"] for item in observations})
        },
        "matched_phrases": dict(Counter(item["full_phrase"] for item in observations if item["full_phrase"])),
        "observations": observations,
    }
    output = save_semi_structured([summary], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(observations)} cut observations to {output}")
    print(
        f"Opening regex: {formula_hits} / {len(observations)}; "
        f"full-candidates exact: {phrase_hits} / {len(observations)}; "
        f"full-candidates fuzzy: {fuzzy_phrase_hits} / {len(observations)}"
    )


if __name__ == "__main__":
    main()
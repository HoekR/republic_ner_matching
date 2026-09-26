#!/usr/bin/env python3
"""Derive recurring opening-phrase candidates without training on gold days."""

from __future__ import annotations

import re
from collections import Counter

from data_io import load, save_semi_structured


ALIGNMENT_DATASET = "alignment_1626_1630"
GOLD_DATASET = "boundary_gold_sample"
OUTPUT_DATASET = "s4_opening_phrase_candidates"
MIN_FREQUENCY = 5


def normalized_words(text: str) -> list[str]:
    return re.sub(r"\s+", " ", text).strip().casefold().split()


def leading_phrases(text: str) -> list[str]:
    words = normalized_words(text)
    return [" ".join(words[:size]) for size in range(2, min(5, len(words)) + 1)]


def main() -> None:
    gold_dates = {str(day["date"]) for day in load(GOLD_DATASET)["days"]}
    alignment = load(ALIGNMENT_DATASET)
    tier1 = alignment.loc[
        alignment["confidence_tier"].eq("tier1_anchor") & ~alignment["date"].astype(str).isin(gold_dates),
        ["flat_id", "flat_text"],
    ].drop_duplicates("flat_id")
    counts: Counter[str] = Counter()
    for text in tier1["flat_text"].dropna().astype(str):
        counts.update(leading_phrases(text))
    candidates = [
        {"phrase": phrase, "count": count, "word_count": len(phrase.split())}
        for phrase, count in counts.most_common()
        if count >= MIN_FREQUENCY
    ]
    report = {
        "tier1_unique_flat_rows": len(tier1),
        "excluded_gold_dates": len(gold_dates),
        "minimum_frequency": MIN_FREQUENCY,
        "candidates": candidates,
    }
    output = save_semi_structured([report], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(candidates)} opening candidates from {len(tier1)} tier-1 flat rows to {output}")


if __name__ == "__main__":
    main()
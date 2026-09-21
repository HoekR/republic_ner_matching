#!/usr/bin/env python3
"""
Align short, "no resolution taken" enriched resolutions to their HTR counterparts.

STRATEGY: Formulaic open/close boilerplate matching
====================================================

Many resolutions are short receipt-of-correspondence items that were read out
but produced no decision (e.g. "Ontfangen een Missive van ... waerop egeen
resolutie is gevallen."). These are easy to recognize on both sides of the
corpus without needing entity overlap:

- Enriched side: the modern editorial abstract is short and/or uses a small,
  closed vocabulary of "no decision" markers ("geen resolutie", "geen
  besluit", "vereist geen").
- HTR side: the original text opens with a receipt formula ("Ontfangen een
  Missive/Requeste...") and closes with a "no resolution" formula ("...waerop
  egeen resolutie is gevallen."). Both formula sets are the empirical top
  opening/closing phrases from output/s2_anchor_phrase_inventory.json (S2
  anchor harvesting, see PLAN.md).

Within a shared date, short-flagged enriched resolutions are paired in order
with short-flagged HTR resolutions (ordered by their embedded
session/resolution sequence number, not parquet row order, which is a
lexicographic artifact of the id string). This sidesteps needing an
open-vocabulary canonical-name matcher (which does not scale to the ~10K-name
LOC/PER/ORG dictionaries with fuzzy_search's FuzzyTokenSearcher, see
docs/notes on that below) and instead anchors on a small, fast phrase model.

Usage:
    uv run python align_short_resolutions.py
"""

import json
import re
from collections import defaultdict
from datetime import datetime

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

from align_resolutions import (
    DATADIR,
    load_enriched_resolutions,
    load_resolutions_flat,
)

OUTPUT_ALIGNMENT = DATADIR / "short_resolution_alignment_1626_1630.json"
OUTPUT_STATS = DATADIR / "short_resolution_alignment_stats.json"

# ----------------------------------------------------------------------------
# Enriched side: "no decision taken" / short-text detector
# ----------------------------------------------------------------------------

NO_DECISION_RE = re.compile(
    r"\b(geen resolutie|geen besluit|vereist geen|geen beslissing)\b", re.IGNORECASE
)
SHORT_TEXT_CHAR_LIMIT = 100


def classify_enriched(resolution: dict) -> str | None:
    """Return a match reason if the enriched resolution looks like a short,
    no-decision item, else None."""
    text = resolution.get("text") or ""
    if NO_DECISION_RE.search(text):
        return "no_decision_marker"
    if 0 < len(text) < SHORT_TEXT_CHAR_LIMIT:
        return "short_text"
    return None


# ----------------------------------------------------------------------------
# HTR side: opening/closing formula detector
# ----------------------------------------------------------------------------

# Empirical top opening/closing phrases from output/s2_anchor_phrase_inventory.json
# (S2 anchor harvesting over 5,725 tier-1 anchors), restricted to phrases that
# signal (a) receipt of correspondence and (b) explicitly *no* resolution.
OPENING_PHRASES = [
    "ontfangen een missive",
    "ontfangen een missiue",
    "ontfangen eenige missiven",
    "ontfangen een requeste",
    "is gelesen de requeste",
    "opt versouck",
    "opt versoeck",
]
CLOSING_PHRASES = [
    "egeen resolutie is gevallen",
    "geen resolutie is gevallen",
    "waerop egeen resolutie is gevallen",
    "waerop geen resolutie is gevallen",
    "egeen resolutie is genomen",
    "geen resolutie is genomen",
    "sonder resolutie",
]

FUZZY_CONFIG = {
    "char_match_threshold": 0.8,
    "ngram_threshold": 0.8,
    "levenshtein_threshold": 0.8,
    "ignorecase": True,
}

# Only look at the head of the text and a window right after the opening
# match. HTR "resolutions" are frequently under-segmented (a short
# receipt-without-decision item is merged into the same flat record as the
# substantive resolution that follows it, see PLAN.md's K_f < K_e finding),
# so the closing formula for THIS item can sit well before the end of the
# raw text -- scanning the tail of the whole record misses it and lets the
# wrong (merged) record win the day's 1:1 slot instead.
OPEN_WINDOW = 60
CLOSE_WINDOW = 250

RESOLUTION_ID_RE = re.compile(r"^(?P<session>.+)-resolution-(?P<order>\d+)$")


def build_formula_searchers() -> tuple[FuzzyPhraseSearcher, FuzzyPhraseSearcher]:
    opener = FuzzyPhraseSearcher(OPENING_PHRASES, config=FUZZY_CONFIG)
    closer = FuzzyPhraseSearcher(CLOSING_PHRASES, config=FUZZY_CONFIG)
    return opener, closer


def detect_flat_short_candidates(res_df, opener, closer) -> list[dict]:
    """Find HTR resolutions that open with a receipt formula and close with a
    no-resolution formula. Returns one record per match with formula scores
    and the resolution's true sequence order within its session."""
    records = []
    for _, row in res_df.iterrows():
        text = str(row.get("resolutions_text") or "").strip()
        if not text:
            continue

        open_matches = opener.find_matches({"id": str(row["id"]), "text": text[:OPEN_WINDOW]})
        if not open_matches:
            continue
        open_end = max(match.end for match in open_matches)
        close_matches = closer.find_matches(
            {"id": str(row["id"]), "text": text[open_end : open_end + CLOSE_WINDOW]}
        )
        if not close_matches:
            continue

        m = RESOLUTION_ID_RE.match(str(row["id"]))
        session_key = m.group("session") if m else str(row["id"])
        order = int(m.group("order")) if m else 0

        records.append(
            {
                "resolution_id": row["id"],
                "date": str(row["date"]),
                "session_key": session_key,
                "order": order,
                "open_score": max(match.levenshtein_similarity for match in open_matches),
                "close_score": max(match.levenshtein_similarity for match in close_matches),
                "text_len": len(text),
            }
        )
    return records


# ----------------------------------------------------------------------------
# Alignment
# ----------------------------------------------------------------------------


def collect_enriched_short(enriched: list[dict]) -> list[dict]:
    short = []
    for resolution in enriched:
        reason = classify_enriched(resolution)
        if not reason:
            continue
        short.append(
            {
                "enriched_id": f"{resolution.get('file')}::{resolution.get('resolution_index')}",
                "date": str(resolution.get("date")),
                "resolution_index": resolution.get("resolution_index"),
                "reason": reason,
                "text": resolution.get("text"),
            }
        )
    return short


def group_by_date(records: list[dict]) -> dict[str, list[dict]]:
    by_date = defaultdict(list)
    for record in records:
        by_date[record["date"]].append(record)
    return by_date


def align_short_resolutions(enriched_short: list[dict], flat_short: list[dict]) -> list[dict]:
    enriched_by_date = group_by_date(enriched_short)
    flat_by_date = group_by_date(flat_short)

    alignments = []
    for date, enr_list in enriched_by_date.items():
        flat_list = flat_by_date.get(date)
        if not flat_list:
            continue

        enr_sorted = sorted(enr_list, key=lambda r: r["resolution_index"] or 0)
        flat_sorted = sorted(flat_list, key=lambda r: (r["session_key"], r["order"]))
        counts_matched = len(enr_sorted) == len(flat_sorted)

        for enr, flat in zip(enr_sorted, flat_sorted):
            formula_confidence = (flat["open_score"] + flat["close_score"]) / 2
            count_confidence = 0.9 if counts_matched else 0.55
            confidence = round(0.5 * count_confidence + 0.5 * formula_confidence, 4)
            alignments.append(
                {
                    "enriched_id": enr["enriched_id"],
                    "enriched_date": enr["date"],
                    "enriched_reason": enr["reason"],
                    "matched_resolution_id": flat["resolution_id"],
                    "confidence": confidence,
                    "counts_matched": counts_matched,
                    "enriched_short_count": len(enr_sorted),
                    "flat_short_count": len(flat_sorted),
                    "open_score": flat["open_score"],
                    "close_score": flat["close_score"],
                }
            )

    return alignments


def save_alignments(alignments: list[dict], total_enriched: int, total_enriched_short: int, total_flat_short: int):
    print("\n=== Saving short-resolution alignments ===")

    with open(OUTPUT_ALIGNMENT, "w") as f:
        json.dump(alignments, f, indent=2, default=str)
    print(f"  Saved {len(alignments)} alignments to {OUTPUT_ALIGNMENT}")

    stats = {
        "total_alignments": len(alignments),
        "total_enriched_resolutions": total_enriched,
        "total_enriched_short_candidates": total_enriched_short,
        "total_flat_short_candidates": total_flat_short,
        "coverage_of_enriched": len(alignments) / total_enriched if total_enriched else 0.0,
        "coverage_of_enriched_short": (
            len(alignments) / total_enriched_short if total_enriched_short else 0.0
        ),
        "confidence_distribution": {
            "high (>0.8)": sum(1 for a in alignments if a["confidence"] > 0.8),
            "medium (0.5-0.8)": sum(1 for a in alignments if 0.5 <= a["confidence"] <= 0.8),
            "low (<0.5)": sum(1 for a in alignments if a["confidence"] < 0.5),
        },
        "counts_matched": {
            "1:1 days": sum(1 for a in alignments if a["counts_matched"]),
            "ambiguous days": sum(1 for a in alignments if not a["counts_matched"]),
        },
        "enriched_reason": {
            "no_decision_marker": sum(1 for a in alignments if a["enriched_reason"] == "no_decision_marker"),
            "short_text": sum(1 for a in alignments if a["enriched_reason"] == "short_text"),
        },
    }

    with open(OUTPUT_STATS, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"  Saved statistics to {OUTPUT_STATS}")

    print("\n=== Short-Resolution Alignment Statistics ===")
    print(f"  Total enriched resolutions: {stats['total_enriched_resolutions']}")
    print(f"  Enriched short/no-decision candidates: {stats['total_enriched_short_candidates']}")
    print(f"  Flat open+close formula candidates: {stats['total_flat_short_candidates']}")
    print(f"  Total alignments: {stats['total_alignments']}")
    print(f"  Coverage of all enriched: {stats['coverage_of_enriched']:.1%}")
    print(f"  Coverage of enriched short candidates: {stats['coverage_of_enriched_short']:.1%}")
    print("\n  Confidence distribution:")
    for level, count in stats["confidence_distribution"].items():
        print(f"    {level}: {count}")
    print("\n  Day count agreement:")
    for level, count in stats["counts_matched"].items():
        print(f"    {level}: {count}")


def main():
    start_time = datetime.now()
    print("=" * 70)
    print("Short-Resolution Alignment (formulaic open/close boilerplate)")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    print("[1/4] Loading data...")
    enriched = load_enriched_resolutions()
    res_df = load_resolutions_flat(enriched=enriched)
    print()

    print("[2/4] Classifying enriched short/no-decision candidates...")
    enriched_short = collect_enriched_short(enriched)
    print(f"  Found {len(enriched_short)} of {len(enriched)} enriched resolutions")
    print()

    print("[3/4] Detecting HTR open+close formula candidates...")
    opener, closer = build_formula_searchers()
    flat_short = detect_flat_short_candidates(res_df, opener, closer)
    print(f"  Found {len(flat_short)} of {len(res_df)} flat resolutions")
    print()

    print("[4/4] Aligning by date + sequence order...")
    alignments = align_short_resolutions(enriched_short, flat_short)
    save_alignments(alignments, len(enriched), len(enriched_short), len(flat_short))

    end_time = datetime.now()
    duration = end_time - start_time
    print("\n" + "=" * 70)
    print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {duration.total_seconds():.1f} seconds")
    print("=" * 70)


if __name__ == "__main__":
    main()

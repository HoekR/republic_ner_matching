#!/usr/bin/env python3
"""Full-dictionary fuzzy surface-form scan over every 1626-1630 paragraph.

PLAN.md's deferred "next candidate" (see the 2026-09-18 entity-density session
note): entity_surface_matches_1626_1630 only *confirms* entities the upstream
NER tagger already linked to a resolution via annotation co-occurrence -- it
cannot find an entity the tagger missed entirely (zero link). Recovering those
requires checking the full LOC/PER/ORG name dictionaries against every
paragraph's raw text, which is what this script does.

This is exactly the thing PLAN.md's prior session flagged as not scaling
(fuzzy_search.FuzzyTokenSearcher over the ~10,876-name dictionary, benchmarked
that session at >4.5 min / 3.7 GB RAM without finishing). Re-benchmarked
2026-09-18 before writing this script: that number was for
index_vocabulary_pairs=True (the default). With it set to False, LOC alone
(2,459 names) drops from 60s/3.7GB to 12s/1.2GB, and full PER (8,076 names)
completes in 185s/6.3GB -- so per-category indexing is tractable, but
per-paragraph *querying* against 21,519 paragraphs is the real cost: measured
~300ms/paragraph for LOC (~1.8h total) and ~880ms/paragraph for PER (~5.3h
total); ORG (341 names) should be faster than both. Total estimated runtime
for all three categories over the full 1626-1630 paragraph axis: roughly
7-9 hours. This is a real multi-hour job, meant to run unattended overnight
or over a weekend, not interactively.

Also re-benchmarked: FuzzyTokenSearcher's default levenshtein_threshold=0.6
produces mostly garbage (common words like "ende"/"heeren"/"Staten" matching
short place names at 0.6-0.8 similarity). Raised to 0.85 (matching this
codebase's existing FuzzyPhraseSearcher convention elsewhere) plus a 4-char
minimum match length to cut the worst short-token false positives; real place
names (Amsterdam, Rotterdam, Deventer) then match correctly at 0.88-1.0.
Even so, treat this script's output as unreviewed candidates, not ground
truth -- it has no human review pass.

Checkpointed: writes one JSON record per match as it goes (flushed
immediately) so a kill/crash partway through a category doesn't lose prior
progress. --resume skips (axis_id, category) pairs already present in the
output file.

Usage:
    uv run python -m scripts.s4_fuzzy_surface_form_scan
    uv run python -m scripts.s4_fuzzy_surface_form_scan --limit 200   # smoke test
    uv run python -m scripts.s4_fuzzy_surface_form_scan --resume      # continue after a kill
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from fuzzy_search.search.token_searcher import FuzzyTokenSearcher

from data_io import load, resolve
from data_io.provenance import ProvenanceRecord, git_commit_hash, write_sidecar

CATEGORY_DATASETS = {
    "LOC": "loc_entities",
    "PER": "per_entities",
    "ORG": "org_entities",
}
SEARCH_CONFIG = {"levenshtein_threshold": 0.85, "char_match_threshold": 0.8, "ngram_threshold": 0.6}
MIN_MATCH_LENGTH = 4
OUTPUT_LOGICAL_NAME = "s4_fuzzy_surface_form_scan"


def load_category_names(logical_name: str) -> tuple[list[str], dict[str, str]]:
    records = load(logical_name)
    names: list[str] = []
    name_to_id: dict[str, str] = {}
    for record in records:
        name = record.get("name")
        if not name:
            continue
        names.append(name)
        name_to_id.setdefault(name, record.get("id", ""))
    return names, name_to_id


def load_known_entities() -> dict[str, set[str]]:
    """(flat_id -> set of entity_id) already confirmed by entity_surface_matches_1626_1630."""
    matches = load("entity_surface_matches_1626_1630")
    known: dict[str, set[str]] = {}
    for row in matches.itertuples(index=False):
        known.setdefault(row.resolution_id, set()).add(row.entity_id)
    return known


def already_processed_keys(output_path: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not output_path.exists():
        return keys
    with output_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            keys.add((record["axis_id"], record["category"]))
    return keys


def scan_category(
    category: str,
    logical_name: str,
    paragraphs: list[dict[str, Any]],
    known: dict[str, set[str]],
    done: set[tuple[str, str]],
    out_handle: Any,
    limit: int | None,
) -> int:
    names, name_to_id = load_category_names(logical_name)
    print(f"[{category}] building index over {len(names)} names (index_vocabulary_pairs=False)...")
    t0 = time.time()
    searcher = FuzzyTokenSearcher(phrase_list=names, index_vocabulary_pairs=False, config=SEARCH_CONFIG)
    print(f"[{category}] index built in {time.time() - t0:.1f}s")

    written = 0
    scanned = 0
    scan_start = time.time()
    for paragraph in paragraphs:
        if limit is not None and scanned >= limit:
            break
        axis_id = paragraph["axis_id"]
        if (axis_id, category) in done:
            continue
        text = paragraph.get("text", "")
        scanned += 1
        matches = searcher.find_matches(text) if text else []
        for match in matches:
            if len(match.string) < MIN_MATCH_LENGTH:
                continue
            canonical_name = match.phrase.phrase_string
            entity_id = name_to_id.get(canonical_name, "")
            already_known = entity_id in known.get(paragraph["flat_id"], set())
            record = {
                "axis_id": axis_id,
                "flat_id": paragraph["flat_id"],
                "para_index": paragraph["para_index"],
                "date": paragraph["date"],
                "category": category,
                "matched_text": match.string,
                "offset": match.offset,
                "canonical_name": canonical_name,
                "entity_id": entity_id,
                "levenshtein_similarity": match.levenshtein_similarity,
                "already_known": already_known,
            }
            out_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
        out_handle.flush()
        if scanned % 500 == 0:
            elapsed = time.time() - scan_start
            rate = scanned / elapsed
            remaining = (len(paragraphs) - scanned) / rate if rate else float("inf")
            print(
                f"[{category}] scanned {scanned}/{len(paragraphs)} paragraphs, "
                f"{written} matches so far, {rate:.2f} paragraphs/s, ETA {remaining / 60:.1f} min"
            )
    print(f"[{category}] done: {scanned} paragraphs scanned, {written} matches written")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Full-dictionary fuzzy surface-form scan over 1626-1630 paragraphs.")
    parser.add_argument("--categories", nargs="+", default=list(CATEGORY_DATASETS), choices=list(CATEGORY_DATASETS))
    parser.add_argument("--limit", type=int, default=None, help="Cap paragraphs scanned per category (smoke test).")
    parser.add_argument("--resume", action="store_true", help="Skip (axis_id, category) pairs already in the output file.")
    args = parser.parse_args()

    output_path = resolve(OUTPUT_LOGICAL_NAME)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done = already_processed_keys(output_path) if args.resume else set()
    if not args.resume and output_path.exists():
        output_path.unlink()

    print("Loading paragraph axis and known-entity lookup...")
    paragraphs = load("paragraph_axis_1626_1630")
    known = load_known_entities()
    print(f"{len(paragraphs)} paragraphs, {sum(len(v) for v in known.values())} already-known entity confirmations")

    total_written = 0
    mode = "a" if args.resume else "w"
    with output_path.open(mode, encoding="utf-8") as out_handle:
        for category in args.categories:
            total_written += scan_category(
                category, CATEGORY_DATASETS[category], paragraphs, known, done, out_handle, args.limit
            )

    with output_path.open("r", encoding="utf-8") as handle:
        total_records = sum(1 for _ in handle)

    write_sidecar(
        output_path,
        ProvenanceRecord(
            logical_name=OUTPUT_LOGICAL_NAME,
            phase="semi",
            parent_sources=["paragraph_axis_1626_1630", "loc_entities", "per_entities", "org_entities"],
            description=(
                "Per-paragraph LOC/PER/ORG surface-form matches from a full-dictionary "
                "FuzzyTokenSearcher scan, flagged already_known vs newly_recovered against "
                "entity_surface_matches_1626_1630."
            ),
            created_by_script=__file__,
            record_count=total_records,
            git_commit=git_commit_hash(output_path.parent),
        ),
    )
    print(f"Done. {total_written} new match records this run, {total_records} total in {output_path}")


if __name__ == "__main__":
    main()

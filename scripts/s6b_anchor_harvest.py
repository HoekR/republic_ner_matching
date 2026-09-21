#!/usr/bin/env python3
"""S6b -- anchor harvest across all four provenance groups.

`scripts/s6b_known_point_ledger.py` already chains group A (tier-1 entity-NW anchors)
plus gold boundaries and session sentinels, but STEP_S6_anchor_chain_alignment.md section
2.2 specifies a harvest spanning all four groups:

    A -- tagger entity layer (already in the ledger, as `tier1_entity_nw`)
    B -- dictionary / fuzzy surface recovery of what the tagger missed
         (`entity_surface_matches_1626_1630`, `s4_fuzzy_surface_form_scan`)
    C -- formulaic text, independent of the tagger
         (`s2_anchor_phrase_inventory`, `s4_opening_phrase_candidates`)
    D -- structural / temporal: session start/end sentinels, plus `session_day_find` (an
         internal "President de Heer X, Present de <weekday> den <date>" session-start
         formula found past a day's own opening, signalling two real sessions merged into
         one HTR-parsed block -- docs/DECISIONS.md 2026-09-21 S4f review). DAT date hooks
         and `para_start` are not wired in yet -- no registered dataset maps them to this
         axis. `session_date_verified` (the other planned Group-D channel, keyed off
         s6b_session_fingerprint_match) is not built here.

This script builds the literal `(date, inventory, char_position, channel, group, weight,
payload)` table and reports two things: per-channel anchor density, and an anchor-SUPPLY
proxy for how many corpus days that previously abstained with reason
`insufficient_entity_anchors` (815 corpus-wide) had zero group-A anchors at all and now gain
at least one anchor from groups B/C. That proxy says nothing about whether a chaining
algorithm could actually RESOLVE a B/C anchor to a valid enriched-index-pinned placement --
the S6 Step 1 oracle diagnostic already showed placement, not anchor supply, is often the
binding constraint (docs/DECISIONS.md 2026-09-20), so this number is upstream of that
question, not an answer to it.

Positions are unresolved to an enriched index for groups B/C/D -- only group A anchors carry
one, inherited from the pre-existing tier-1 alignment. Turning a B/C position into an
enriched-index-pinned known point is exactly the chaining step S6c still has to do.

Parallelized across days (fork-based ProcessPoolExecutor -- each day's harvest only reads
shared, already-built lookups/searchers, so workers inherit them via copy-on-write instead of
re-pickling per task) and checkpointed the same way as `s4_fuzzy_surface_form_scan.py`: rows are
flushed to a `.checkpoint.jsonl` scratch file as each day completes, `--resume` skips days already
marked done there, and the final canonical output is assembled from that file once the whole
window is processed.

Usage:
    uv run python -m scripts.s6b_anchor_harvest
    uv run python -m scripts.s6b_anchor_harvest --start 1626-01-01 --end 1626-03-31
    uv run python -m scripts.s6b_anchor_harvest --workers 10
    uv run python -m scripts.s6b_anchor_harvest --resume      # continue after a kill
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

from data_io import load, resolve, save_semi_structured
from scripts.s6a_char_axis_evaluation import char_starts
from scripts.s6b_known_point_ledger import (
    DEFAULT_END,
    DEFAULT_START,
    TIER1,
    flat_id_char_starts,
    inventory_of,
    tier1_points,
)


ALIGNMENT_DATASET = "alignment_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
SURFACE_MATCH_DATASET = "entity_surface_matches_1626_1630"
FUZZY_SCAN_DATASET = "s4_fuzzy_surface_form_scan"
S2_PHRASE_DATASET = "s2_anchor_phrase_inventory"
S4_PHRASE_DATASET = "s4_opening_phrase_candidates"
CORPUS_PREDICTIONS_DATASET = "s4_corpus_paragraph_predictions"
OUTPUT_DATASET = "s6b_anchor_harvest"

PHRASE_SEARCH_CONFIG = {"char_match_threshold": 0.85, "ngram_threshold": 0.85, "levenshtein_threshold": 0.85}

# Per-CHANNEL, not flat-per-row: group A is already the output of an existing NW alignment
# and carries the highest confidence; group B recovers what the tagger missed; group C is
# text-derived and tagger-independent; group D is structural. STEP_S6 section 2.2.
CHANNEL_GROUP = {
    "tier1_entity_nw": "A",
    "entity_surface_matches": "B",
    "fuzzy_surface_scan": "B",
    "s2_anchor_phrases": "C",
    "s4_opening_phrase_candidates": "C",
    "session_boundary": "D",
    "session_day_find": "D",
}
CHANNEL_WEIGHT = {
    "tier1_entity_nw": 3.0,
    "entity_surface_matches": 1.5,
    "fuzzy_surface_scan": 1.0,
    "s2_anchor_phrases": 2.0,
    "s4_opening_phrase_candidates": 1.5,
    "session_boundary": 5.0,
    "session_day_find": 4.0,
}

# STEP_S6 section 2.2, group D: an internal "President de Heer X, Present de <weekday>
# den <date>" session-start formula found PAST a day's own leading text signals two real
# sessions merged into one HTR-parsed block (docs/DECISIONS.md 2026-09-21, S4f review).
# President-family list grounded in a corpus-wide frequency scan over
# paragraph_axis_1626_1630 (top forms, ~98% of "presid*" occurrences). Present-family list
# is narrower and grounded differently: of 830 "presid*" occurrences, only 237 have any
# "presen*" word within 60 chars after, and of those 94.5% are present/presentibus/
# praesentibus/presentie/presente -- the corpus-wide-frequent presentatie/presenterende/
# presenteren/presenteert (generic "presentation"/attendance usage) occur zero times in
# that actual formula context and were excluded to avoid diluting the searcher with forms
# that only ever co-occur by coincidence.
SESSION_START_PRESIDENT_PHRASES = [
    "president", "presiderende", "preside", "praeside", "presideren",
    "presidenten", "praesident", "presideert",
]
SESSION_START_PRESENT_PHRASES = ["present", "presentibus", "praesentibus", "presentie", "presente"]
SESSION_START_LEADING_BUFFER_CHARS = 80  # skip the day's own opening, not an internal merge
SESSION_START_PRESENT_WINDOW_CHARS = 60
# Deliberately its own config, not a reuse of PHRASE_SEARCH_CONFIG, and NOT just for
# ignorecase (FuzzyPhraseSearcher defaults to case-sensitive, and these phrases sit
# mid-sentence where sentence-initial capitalization -- "Preside et Presentibus..." -- is
# common; without it the fuzzy version undercounted the s4_session_start_scan.py stem-regex
# baseline, 210 hits/167 sessions, by 4x). The threshold also had to rise from
# PHRASE_SEARCH_CONFIG's 0.85 to 0.95: at 0.85, single short words like "present" (7 chars)
# fuzzy-match unrelated nearby substrings often enough that most "hits" were generic
# "de heer President ..." mentions coincidentally paired with matching noise, not the
# formula (spot-checked at 0.85: mostly false positives; at 0.95, 25/25 sampled hits were
# genuine). Final count: 154 hits / 130 sessions (vs regex's 210/167, unvalidated for
# precision) -- lower recall, but every sampled hit is real. The existing s2/s4 phrase
# channels below keep PHRASE_SEARCH_CONFIG unchanged since their measured metrics predate
# this finding -- worth a separate look, not silently folded in here.
SESSION_START_PHRASE_SEARCH_CONFIG = {
    "char_match_threshold": 0.95,
    "ngram_threshold": 0.95,
    "levenshtein_threshold": 0.95,
    "ignorecase": True,
}


def harvest_row(date: str, inventory: str, channel: str, char_position: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": date,
        "inventory": inventory,
        "channel": channel,
        "group": CHANNEL_GROUP[channel],
        "char_position": char_position,
        "weight": CHANNEL_WEIGHT[channel],
        "payload": payload,
    }


def session_boundary_rows(date: str, inventory: str, total_chars: int) -> list[dict[str, Any]]:
    return [
        harvest_row(date, inventory, "session_boundary", 0, {"kind": "start"}),
        harvest_row(date, inventory, "session_boundary", total_chars, {"kind": "end"}),
    ]


def tier1_rows(date: str, inventory: str, points: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        harvest_row(date, inventory, "tier1_entity_nw", point["char_position"], {"enriched_index": point["enriched_index"]})
        for point in points
    ]


def surface_match_rows(
    date: str, inventory: str, flat_id_starts: dict[str, int], matches_by_flat_id: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    rows = []
    for flat_id, start in flat_id_starts.items():
        for match in matches_by_flat_id.get(flat_id, []):
            rows.append(
                harvest_row(
                    date,
                    inventory,
                    "entity_surface_matches",
                    start,
                    {"flat_id": flat_id, **match},
                )
            )
    return rows


def fuzzy_scan_rows(
    date: str, inventory: str, axis_starts_by_id: dict[str, int], records: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        start = axis_starts_by_id.get(record["axis_id"])
        if start is None:
            continue
        rows.append(
            harvest_row(
                date,
                inventory,
                "fuzzy_surface_scan",
                start + int(record["offset"]),
                {
                    "flat_id": record["flat_id"],
                    "category": record["category"],
                    "entity_id": record["entity_id"],
                    "canonical_name": record["canonical_name"],
                    "matched_text": record["matched_text"],
                    "already_known": record["already_known"],
                },
            )
        )
    return rows


def phrase_rows(
    date: str, inventory: str, axis: Sequence[dict[str, Any]], starts: Sequence[int], searcher: FuzzyPhraseSearcher, channel: str
) -> list[dict[str, Any]]:
    rows = []
    for index, record in enumerate(axis):
        matches = searcher.find_matches({"id": record["axis_id"], "text": record["text"]})
        if not matches:
            continue
        best = max(matches, key=lambda match: (match.levenshtein_similarity, len(match.phrase.phrase_string)))
        rows.append(
            harvest_row(
                date,
                inventory,
                channel,
                starts[index] + best.offset,
                {"phrase": best.phrase.phrase_string, "similarity": best.levenshtein_similarity, "para_index": index},
            )
        )
    return rows


def phrase_hits(
    axis: Sequence[dict[str, Any]], starts: Sequence[int], searcher: FuzzyPhraseSearcher
) -> list[tuple[int, float, str]]:
    """All (char_position, similarity, phrase) hits of `searcher` over one day's axis."""
    hits = []
    for index, record in enumerate(axis):
        for match in searcher.find_matches({"id": record["axis_id"], "text": record["text"]}):
            hits.append((starts[index] + match.offset, match.levenshtein_similarity, match.phrase.phrase_string))
    return hits


def session_day_find_rows(
    date: str,
    inventory: str,
    president_hits: Sequence[tuple[int, float, str]],
    present_hits: Sequence[tuple[int, float, str]],
) -> list[dict[str, Any]]:
    """Pair a 'president' hit with a nearby 'present' hit past the day's own opening.

    Two independent phrase hits within `SESSION_START_PRESENT_WINDOW_CHARS` of each
    other, past `SESSION_START_LEADING_BUFFER_CHARS`, reproduce the session-start
    formula mid-axis -- s4_session_start_scan.py's validated signal, fuzzy-matched
    instead of stem-regex-matched.
    """
    rows = []
    for position, similarity, phrase in sorted(president_hits):
        if position < SESSION_START_LEADING_BUFFER_CHARS:
            continue
        window_end = position + SESSION_START_PRESENT_WINDOW_CHARS
        nearby = [hit for hit in present_hits if position <= hit[0] <= window_end]
        if not nearby:
            continue
        best_present = max(nearby, key=lambda hit: hit[1])
        rows.append(
            harvest_row(
                date,
                inventory,
                "session_day_find",
                position,
                {
                    "president_phrase": phrase,
                    "president_similarity": similarity,
                    "present_phrase": best_present[2],
                    "present_similarity": best_present[1],
                },
            )
        )
    return rows


def density_report(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-channel: anchor count, days touched, and distinct (date, char_position) positions."""
    counts: Counter[str] = Counter()
    days: dict[str, set[str]] = defaultdict(set)
    positions: dict[str, set[tuple[str, int]]] = defaultdict(set)
    group_of: dict[str, str] = {}
    for row in rows:
        channel = row["channel"]
        counts[channel] += 1
        days[channel].add(row["date"])
        positions[channel].add((row["date"], row["char_position"]))
        group_of[channel] = row["group"]
    return {
        channel: {
            "group": group_of[channel],
            "anchors": counts[channel],
            "days": len(days[channel]),
            "distinct_positions": len(positions[channel]),
        }
        for channel in sorted(counts)
    }


def abstention_supply_gain(rows: Sequence[dict[str, Any]], abstained_dates: Sequence[str]) -> dict[str, Any]:
    """Anchor-SUPPLY proxy only -- see module docstring for what this does not claim."""
    channels_by_date: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        channels_by_date[row["date"]].add(row["channel"])

    zero_group_a = [date for date in abstained_dates if "tier1_entity_nw" not in channels_by_date.get(date, set())]
    non_a_channels = set(CHANNEL_GROUP) - {"tier1_entity_nw", "session_boundary"}
    gains_other_channel = [date for date in zero_group_a if channels_by_date.get(date, set()) & non_a_channels]
    return {
        "abstained_days_in_window": len(abstained_dates),
        "zero_group_a_anchor_days": len(zero_group_a),
        "of_those_gaining_a_non_group_a_anchor": len(gains_other_channel),
    }


# Populated once in main() before the ProcessPoolExecutor forks, so worker processes inherit it
# via copy-on-write instead of having it re-pickled per task.
_SHARED: dict[str, Any] = {}

DONE_KEY = "__done_date__"


def _harvest_date_worker(date: str) -> list[dict[str, Any]]:
    axis = _SHARED["axis_by_date"][date]
    starts = char_starts(axis)
    total_chars = starts[-1] + len(axis[-1]["text"])
    inventory = inventory_of(axis)
    flat_starts = flat_id_char_starts(axis)
    axis_starts_by_id = {record["axis_id"]: starts[index] for index, record in enumerate(axis)}

    rows: list[dict[str, Any]] = []
    rows.extend(session_boundary_rows(date, inventory, total_chars))
    rows.extend(tier1_rows(date, inventory, tier1_points(_SHARED["tier1_by_date"].get(date, []), flat_starts)))
    rows.extend(surface_match_rows(date, inventory, flat_starts, _SHARED["surface_by_flat_id"]))
    rows.extend(fuzzy_scan_rows(date, inventory, axis_starts_by_id, _SHARED["fuzzy_by_date"].get(date, [])))
    rows.extend(phrase_rows(date, inventory, axis, starts, _SHARED["searcher_s2"], "s2_anchor_phrases"))
    rows.extend(phrase_rows(date, inventory, axis, starts, _SHARED["searcher_s4"], "s4_opening_phrase_candidates"))
    rows.extend(
        session_day_find_rows(
            date,
            inventory,
            phrase_hits(axis, starts, _SHARED["searcher_president"]),
            phrase_hits(axis, starts, _SHARED["searcher_present"]),
        )
    )
    return rows


def checkpoint_path_for(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.checkpoint.jsonl")


def read_done_dates(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                marker = json.loads(line).get(DONE_KEY)
                if marker:
                    done.add(marker)
    return done


def read_checkpoint_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                record = json.loads(line)
                if "channel" in record:
                    rows.append(record)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="S6b anchor harvest across provenance groups A-D.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 4) - 2),
        help="Parallel worker processes, one date per task (default: cpu_count - 2).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip dates already marked done in the .checkpoint.jsonl scratch file (continue after a kill).",
    )
    args = parser.parse_args()

    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        date = str(record["date"])
        if args.start <= date <= args.end:
            axis_by_date[date].append(record)

    alignment = load(ALIGNMENT_DATASET)
    alignment = alignment[
        (alignment["date"] >= args.start) & (alignment["date"] <= args.end) & (alignment["confidence_tier"] == TIER1)
    ]
    tier1_by_date: dict[str, list[Any]] = defaultdict(list)
    for row in alignment[["enriched_id", "flat_id", "date"]].itertuples(index=False):
        tier1_by_date[str(row.date)].append(row)

    surface = load(SURFACE_MATCH_DATASET)
    surface_by_flat_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in surface[["resolution_id", "entity_type", "entity_id", "canonical_name", "match_method"]].itertuples(index=False):
        surface_by_flat_id[str(row.resolution_id)].append(
            {"entity_type": row.entity_type, "entity_id": row.entity_id, "canonical_name": row.canonical_name, "match_method": row.match_method}
        )

    fuzzy_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(FUZZY_SCAN_DATASET):
        date = str(record.get("date", ""))
        if args.start <= date <= args.end:
            fuzzy_by_date[date].append(record)

    s2_phrases = [entry["phrase"] for entry in load(S2_PHRASE_DATASET)["opening_phrases_top_20"]]
    s4_candidates = [entry["phrase"] for entry in load(S4_PHRASE_DATASET)[0]["candidates"]]
    searcher_s2 = FuzzyPhraseSearcher(s2_phrases, config=PHRASE_SEARCH_CONFIG)
    searcher_s4 = FuzzyPhraseSearcher(s4_candidates, config=PHRASE_SEARCH_CONFIG)
    searcher_president = FuzzyPhraseSearcher(SESSION_START_PRESIDENT_PHRASES, config=SESSION_START_PHRASE_SEARCH_CONFIG)
    searcher_present = FuzzyPhraseSearcher(SESSION_START_PRESENT_PHRASES, config=SESSION_START_PHRASE_SEARCH_CONFIG)

    _SHARED["axis_by_date"] = axis_by_date
    _SHARED["tier1_by_date"] = tier1_by_date
    _SHARED["surface_by_flat_id"] = surface_by_flat_id
    _SHARED["fuzzy_by_date"] = fuzzy_by_date
    _SHARED["searcher_s2"] = searcher_s2
    _SHARED["searcher_s4"] = searcher_s4
    _SHARED["searcher_president"] = searcher_president
    _SHARED["searcher_present"] = searcher_present

    output_path = resolve(OUTPUT_DATASET)
    checkpoint_path = checkpoint_path_for(output_path)
    if not args.resume and checkpoint_path.exists():
        checkpoint_path.unlink()

    done_dates = read_done_dates(checkpoint_path) if args.resume else set()
    all_dates = sorted(axis_by_date)
    pending_dates = [date for date in all_dates if date not in done_dates]
    print(
        f"{len(all_dates)} days in window, {len(done_dates)} already checkpointed, "
        f"{len(pending_dates)} to process with {args.workers} workers"
    )

    if pending_dates:
        fork_ctx = multiprocessing.get_context("fork")
        start_time = time.time()
        completed = 0
        with (
            checkpoint_path.open("a", encoding="utf-8") as out_handle,
            ProcessPoolExecutor(max_workers=args.workers, mp_context=fork_ctx) as executor,
        ):
            futures = {executor.submit(_harvest_date_worker, date): date for date in pending_dates}
            for future in as_completed(futures):
                date = futures[future]
                lines = [json.dumps(row, ensure_ascii=False) for row in future.result()]
                lines.append(json.dumps({DONE_KEY: date}, ensure_ascii=False))
                out_handle.write("\n".join(lines) + "\n")
                out_handle.flush()
                completed += 1
                if completed % 50 == 0 or completed == len(pending_dates):
                    elapsed = time.time() - start_time
                    rate = completed / elapsed
                    remaining = (len(pending_dates) - completed) / rate if rate else float("inf")
                    print(f"  {completed}/{len(pending_dates)} days done, {rate:.2f} days/s, ETA {remaining / 60:.1f} min")

    rows = read_checkpoint_rows(checkpoint_path)
    density = density_report(rows)

    abstained_dates = [
        str(item["date"])
        for item in load(CORPUS_PREDICTIONS_DATASET)
        if args.start <= str(item["date"]) <= args.end and item["status"] == "abstained" and item.get("reason") == "insufficient_entity_anchors"
    ]
    supply_gain = abstention_supply_gain(rows, abstained_dates)

    summary = {
        "window": {"start": args.start, "end": args.end},
        "days": len(all_dates),
        "total_anchors": len(rows),
        "density_by_channel": density,
        "insufficient_entity_anchors_supply_gain": supply_gain,
    }
    output = save_semi_structured([summary, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    checkpoint_path.unlink(missing_ok=True)
    print(f"Wrote {len(rows)} anchor rows over {len(all_dates)} days to {output}")
    for channel, entry in density.items():
        print(f"  {channel:26} group {entry['group']}  anchors {entry['anchors']:>7}  days {entry['days']:>5}  distinct positions {entry['distinct_positions']:>7}")
    print(f"  insufficient_entity_anchors in window: {supply_gain['abstained_days_in_window']}")
    print(f"    zero group-A anchors:                {supply_gain['zero_group_a_anchor_days']}")
    print(f"    of those, gain a non-A anchor:        {supply_gain['of_those_gaining_a_non_group_a_anchor']}")


if __name__ == "__main__":
    main()

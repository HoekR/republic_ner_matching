#!/usr/bin/env python3
"""Pathology corpus -- Step 1: anchor contribution ledger on the three seed days.

Builds the per-(resolution, paragraph) anchor record with entity-level
decomposition and both orderings (sequence / strength), for the three seed
days `1630-02-22`, `1629-06-03`, `1627-10-06` only. Nominal axis, width 0 --
no widened window (that is Step 3 of the approved pathology-corpus plan).

Deliberately does NOT: register a dataset in data_manifest.toml, call
save_semi_structured, or implement span segmentation/classification -- those
are later steps. This module prints the ledger and verifies the gate on
1630-02-22.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any

import pandas as pd

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, resolve
from scripts.s4_corpus_paragraph_predictions import (
    AXIS_DATASET,
    OVERLAP_DATASETS,
    axis_for_date,
    resolved_sessions,
    session_of,
)
from scripts.s4_paragraph_axis_baseline import build_axis_overlap


SEED_DATES = ("1630-02-22", "1629-06-03", "1627-10-06")
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"

# Entity type per overlap dataset, in the same order as OVERLAP_DATASETS.
OVERLAP_TYPES = ("place", "org", "person")

# align_session_milestone_tiered's tier1 anchor gate (build_alignment_new.py:801, default
# argument `anchor_threshold=2.0`). Used ONLY for the tiered-path monotonic filter below --
# production's align_session (:900) has no such threshold; its diagonal gate is
# `entity_match_score > 0` (`anchor_only_diagonal`, :938-940).
TIERED_ANCHOR_THRESHOLD = 2.0

# Gate: hand-verified anchor scores on 1630-02-22 (see the approved pathology-corpus
# plan, Step 1). best_j is None where there is no shared entity with any paragraph at
# all (score 0.0); scores are rounded to 3dp.
GATE_DATE = "1630-02-22"
GATE_EXPECTED: dict[int, tuple[int | None, float]] = {
    0: (None, 0.0), 1: (None, 0.0), 2: (None, 0.0), 3: (None, 0.0),
    4: (None, 0.0), 5: (None, 0.0), 6: (None, 0.0),
    7: (1, 3.688), 8: (1, 3.688),
    9: (1, 16.224),
    10: (2, 18.784),
    11: (1, 5.673),
    12: (5, 28.734),
    13: (None, 0.0),
    14: (7, 4.227),
    15: (None, 0.0), 16: (None, 0.0), 17: (None, 0.0), 18: (None, 0.0),
    19: (None, 0.0), 20: (None, 0.0), 21: (None, 0.0), 22: (None, 0.0),
    23: (8, 7.961),
    24: (None, 0.0),
    25: (10, 10.269),
    26: (11, 6.352),
    27: (None, 0.0),
}


def load_axis_indexes() -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, str]]:
    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)
        axis_by_session[session_of(record["flat_id"])].append(record)
    session_by_date = resolved_sessions()
    return axis_by_date, axis_by_session, session_by_date


def load_overlap_frames() -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    """Combined overlap frame (for scoring) plus the per-type source frames (for typing).

    CRITICAL correctness trap (per the plan): `build_axis_overlap` discards entity type
    when called on the combined/union frame. Score must still come from the combined/union
    lookup exactly as production does it -- a name shared across two source files is
    deduplicated by the union `set` there, but would be double-counted if scores were summed
    per type. The per-type frames below are used ONLY to recover which type(s) each shared
    name matched under, never to compute or re-sum scores.
    """
    frames = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    frames = [
        frame.rename(columns={"naam": "name"}) if "name" not in frame and "naam" in frame else frame
        for frame in frames
    ]
    combined = pd.concat(frames, ignore_index=True)
    return combined, frames


def enriched_ids_by_date() -> dict[str, list[str]]:
    concordance = load(CONCORDANCE_DATASET)
    concordance = concordance.copy()
    concordance["enriched_date"] = concordance["enriched_date"].astype(str).str[:10]
    result: dict[str, list[str]] = {}
    for date in SEED_DATES:
        day = concordance.loc[concordance["enriched_date"] == date].sort_values("resolution_index")
        result[date] = day["enriched_id"].tolist()
    return result


def build_ledger_for_date(
    date: str,
    enriched_ids: list[str],
    axis_by_date: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
    combined_overlap: pd.DataFrame,
    type_frames: list[pd.DataFrame],
    idf_weights: dict[str, float],
) -> list[dict[str, Any]]:
    axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
    axis_ids = [record["axis_id"] for record in axis]
    lookup = build_axis_overlap(axis, combined_overlap)
    type_lookups = [build_axis_overlap(axis, frame) for frame in type_frames]

    # The per-cell anchor test, mirroring build_alignment_new.py:930-931 exactly: for every
    # (resolution, paragraph) cell, score = sum of IDF weights of the entities shared between
    # that enriched resolution and that axis paragraph, read from the combined/union lookup.
    per_resolution: list[dict[str, Any]] = []
    for i, e_id in enumerate(enriched_ids):
        best_j: int | None = None
        best_score = 0.0
        best_shared: set[str] = set()
        cell_scores: dict[int, float] = {}
        cell_shared: dict[int, set[str]] = {}
        for j, f_id in enumerate(axis_ids):
            shared = lookup.get((e_id, f_id), set())
            score = sum(idf_weights.get(e, 1.0) for e in shared)
            cell_scores[j] = score
            cell_shared[j] = shared
            # Unchanged: strict >, so the leftmost paragraph wins `paragraph`/`score` on a
            # tie -- this is the existing row-local argmax behaviour the gate depends on.
            if score > best_score:
                best_score = score
                best_j = j
                best_shared = shared

        entities = []
        if best_j is not None:
            f_id = axis_ids[best_j]
            for name in sorted(best_shared):
                types = [
                    type_name
                    for type_name, type_lookup in zip(OVERLAP_TYPES, type_lookups)
                    if name in type_lookup.get((e_id, f_id), set())
                ]
                entities.append({
                    "name": name,
                    "type": types,
                    "idf": round(idf_weights.get(name, 1.0), 3),
                })

        # tied_paragraphs: every paragraph achieving best_score (compared at the same 3dp
        # precision the ledger reports scores at, to avoid float-noise false ties/non-ties).
        # None when there is no anchor at all (best_j is None); length 1 is the common,
        # non-tied case; length > 1 is a genuine tie the row-local argmax above silently
        # broke leftward. This is the fact the earlier ledger discarded.
        tied_paragraphs: list[int] | None = None
        tied_entities_identical: bool | None = None
        if best_j is not None:
            rounded_best = round(best_score, 3)
            tied_paragraphs = sorted(j for j, s in cell_scores.items() if round(s, 3) == rounded_best)
            if len(tied_paragraphs) > 1:
                tied_sets = [cell_shared[j] for j in tied_paragraphs]
                # Same entity set at every tied paragraph (one recurring entity firing in
                # several paragraphs, the "'s Hertogenbosch" shape) vs. different sets that
                # happen to sum to the same score (a numerical coincidence) -- cheap to tell
                # apart since cell_shared already holds the raw sets per paragraph.
                tied_entities_identical = all(s == tied_sets[0] for s in tied_sets)

        per_resolution.append({
            "resolution_index": i,
            "enriched_id": e_id,
            "paragraph": best_j,
            "score": round(best_score, 3),
            "entities": entities,
            "tied_paragraphs": tied_paragraphs,
            "is_tied": bool(tied_paragraphs) and len(tied_paragraphs) > 1,
            "tied_entities_identical": tied_entities_identical,
        })

    # sequence_rank: left-to-right order along the stream (by paragraph, then resolution
    # index), strength_rank: rank by score descending. Both are defined only over
    # resolutions that carry an anchor at all (paragraph is not None).
    anchored = [r for r in per_resolution if r["paragraph"] is not None]
    for rank, record in enumerate(sorted(anchored, key=lambda r: (r["paragraph"], r["resolution_index"]))):
        record["sequence_rank"] = rank
    for rank, record in enumerate(sorted(anchored, key=lambda r: (-r["score"], r["resolution_index"]))):
        record["strength_rank"] = rank
    for record in per_resolution:
        record.setdefault("sequence_rank", None)
        record.setdefault("strength_rank", None)

    # Two DISTINCT order facts -- corrected after an earlier mislabel. These are known to
    # disagree (data_manifest.toml:271: only 65.7% agreement, 62.9% exact-position agreement
    # between the two paths corpus-wide), so both are recorded rather than picking one.

    # (1) THE PRODUCTION FACT. s4_corpus_paragraph_predictions.predict() calls align_session
    # (build_alignment_new.py:900), the NW core, not align_session_milestone_tiered.
    # align_session has no clean_anchors and no anchor_threshold; its diagonal gate is
    # `entity_match_score > 0` (`anchor_only_diagonal`, :938-940), and monotonicity falls out
    # of the NW traceback itself, not an explicit post-hoc filter. Run it once for the whole
    # day (no similarity matrix / semantic_weight, matching this ledger's plain entity-overlap
    # scoring).
    #
    # Two SEPARATE facts, not one collapsed bool -- a single `taken_by_nw_traceback` flag
    # conflated "NW placed this resolution nowhere" (idx 7/8: nw_diagonal_paragraph is None)
    # with "NW placed it, just at the OTHER tied paragraph" (idx 11: NW picked 4, ledger's
    # row-local argmax picked 1) -- both read as False, but they are opposite situations a
    # Step 2 classifier must not bucket together.
    nw_alignments = align_session(enriched_ids, axis_ids, lookup, idf_weights)
    nw_diagonal_by_resolution: dict[int, int] = {
        e_idx: f_idx for e_idx, f_idx in nw_alignments if e_idx is not None and f_idx is not None
    }
    for record in per_resolution:
        i = record["resolution_index"]
        nw_paragraph = nw_diagonal_by_resolution.get(i)
        record["nw_diagonal_paragraph"] = nw_paragraph
        record["nw_anchored"] = nw_paragraph is not None
        record["nw_agrees_with_ledger"] = (nw_paragraph == record["paragraph"]) if nw_paragraph is not None else None
        # Kept only to avoid churn elsewhere; NOT what the printed output leads with.
        record["taken_by_nw_traceback"] = bool(record["nw_anchored"] and record["nw_agrees_with_ledger"])

    # (2) survived_tiered_monotonic_filter -- describes align_session_milestone_tiered's path
    # (build_alignment_new.py:795-897, `clean_anchors` at :838-851), which populates
    # alignment_1626_1630.parquet and is NOT what predict() runs. Mirrors that function's own
    # two-stage gate: a resolution only becomes a tier1 anchor candidate if its best score
    # meets TIERED_ANCHOR_THRESHOLD (2.0, :801/:835); candidates are then walked in
    # resolution_index order and kept only if paragraph is non-decreasing relative to the
    # last KEPT candidate (a dropped candidate does not advance curr_j). On this seed data
    # every nonzero score already exceeds 2.0, so the threshold stage is untested here --
    # only the monotonic stage bites (see idx 11 on 1630-02-22).
    curr_j = -1
    for record in per_resolution:
        if record["paragraph"] is None or record["score"] < TIERED_ANCHOR_THRESHOLD:
            record["survived_tiered_monotonic_filter"] = None
            continue
        if record["paragraph"] >= curr_j:
            record["survived_tiered_monotonic_filter"] = True
            curr_j = record["paragraph"]
        else:
            record["survived_tiered_monotonic_filter"] = False

    return per_resolution


def print_ledger(date: str, ledger: list[dict[str, Any]]) -> None:
    paragraphs = {r["paragraph"] for r in ledger if r["paragraph"] is not None}
    print(f"\n=== {date} ({len(ledger)} resolutions, {len(paragraphs)} distinct anchored paragraphs) ===")
    for record in ledger:
        entity_desc = ", ".join(
            f"{e['name']}[{'/'.join(e['type']) or '?'}]={e['idf']}" for e in record["entities"]
        ) or "(none)"
        print(
            f"  idx {record['resolution_index']:>2} -> paragraph {str(record['paragraph']):>4} "
            f"score={record['score']:>8.3f} seq_rank={str(record['sequence_rank']):>4} "
            f"strength_rank={str(record['strength_rank']):>4}"
        )
        print(
            f"       nw_anchored={record['nw_anchored']} "
            f"nw_agrees_with_ledger={record['nw_agrees_with_ledger']} "
            f"(nw_diagonal_paragraph={record['nw_diagonal_paragraph']})  "
            f"survived_tiered_monotonic_filter={record['survived_tiered_monotonic_filter']}"
        )
        if record["is_tied"]:
            print(
                f"       TIED across paragraphs {record['tied_paragraphs']} at score {record['score']} "
                f"(same entity set at every tied paragraph: {record['tied_entities_identical']})"
            )
        print(f"       entities: {entity_desc}")
    dropped = sum(1 for r in ledger if r["survived_tiered_monotonic_filter"] is False)
    anchored_nw = sum(1 for r in ledger if r["nw_anchored"])
    agree_nw = sum(1 for r in ledger if r["nw_agrees_with_ledger"])
    tiered_survived = sum(1 for r in ledger if r["survived_tiered_monotonic_filter"] is True)
    tied = [r for r in ledger if r["is_tied"]]
    print(
        f"  nw_anchored: {anchored_nw}/{len(ledger)}; nw_agrees_with_ledger: {agree_nw}; "
        f"survived_tiered_monotonic_filter: {tiered_survived} (dropped: {dropped}); "
        f"tied resolutions: {len(tied)}"
    )
    if tied:
        print("  tied resolutions detail:")
        for r in tied:
            print(
                f"    idx {r['resolution_index']}: tied_paragraphs={r['tied_paragraphs']} "
                f"score={r['score']} same_entity_set={r['tied_entities_identical']}"
            )

    # Placement-based disagreement detector -- compares WHERE each path places a resolution,
    # not two booleans. Comparing booleans hid idx 11's case: nw_agrees_with_ledger=False and
    # survived_tiered_monotonic_filter=False agree as booleans (both "False"), but for opposite
    # reasons -- NW placed it (at paragraph 4, the other tied paragraph) while the tiered path
    # dropped it entirely (order violation against idx 10). Comparing the actual placements
    # (None = unplaced/dropped) surfaces that as the sharp disagreement it is.
    disagreements = []
    for r in ledger:
        if r["paragraph"] is None:
            continue  # no anchor at all under this ledger's own reading; nothing to compare
        nw_place = r["nw_diagonal_paragraph"]  # None = NW leaves it unplaced
        tiered_place = r["paragraph"] if r["survived_tiered_monotonic_filter"] else None  # None = dropped
        if nw_place == tiered_place:
            continue
        if nw_place is not None and tiered_place is None:
            kind = "nw_placed_tiered_dropped"
        elif nw_place is None and tiered_place is not None:
            kind = "tiered_kept_nw_unplaced"
        else:
            kind = "both_placed_different_paragraph"
        disagreements.append((r, kind, nw_place, tiered_place))

    if disagreements:
        print("  disagreements between the two paths (placement-based):")
        for r, kind, nw_place, tiered_place in disagreements:
            print(
                f"    idx {r['resolution_index']}: {kind} -- "
                f"nw_diagonal_paragraph={nw_place}, tiered_placement={tiered_place} "
                f"(ledger paragraph {r['paragraph']}, score {r['score']})"
            )


def verify_gate(ledger: list[dict[str, Any]]) -> bool:
    ok = True
    by_index = {r["resolution_index"]: r for r in ledger}
    for idx, (expected_j, expected_score) in GATE_EXPECTED.items():
        record = by_index.get(idx)
        if record is None:
            print(f"GATE MISMATCH idx {idx}: missing from ledger")
            ok = False
            continue
        actual_j = record["paragraph"]
        actual_score = round(record["score"], 3)
        if actual_j != expected_j or abs(actual_score - expected_score) > 0.0005:
            print(
                f"GATE MISMATCH idx {idx}: expected (best_j={expected_j}, score={expected_score}), "
                f"got (best_j={actual_j}, score={actual_score})"
            )
            ok = False
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds",
        action="store_true",
        help="Build and print the ledger for the three seed days and verify the 1630-02-22 gate.",
    )
    args = parser.parse_args()
    if not args.seeds:
        parser.print_help()
        return

    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    combined_overlap, type_frames = load_overlap_frames()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_ids = enriched_ids_by_date()

    ledgers: dict[str, list[dict[str, Any]]] = {}
    for date in SEED_DATES:
        ledger = build_ledger_for_date(
            date,
            enriched_ids[date],
            axis_by_date,
            axis_by_session,
            session_by_date,
            combined_overlap,
            type_frames,
            idf_weights,
        )
        ledgers[date] = ledger
        print_ledger(date, ledger)

    gate_ok = verify_gate(ledgers[GATE_DATE])
    print(f"\nGate on {GATE_DATE}: {'PASS' if gate_ok else 'FAIL'}")
    if not gate_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

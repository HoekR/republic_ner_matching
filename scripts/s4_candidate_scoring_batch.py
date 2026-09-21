#!/usr/bin/env python3
"""Persist Step 2/3 candidate scoring as a dataset (Step 4A of
``docs/CANDIDATE_SCORING_AND_CONCORDANCE.md``).

Runs ``score_ledger_row`` over every ``A``/``X``/``-1``/``+1``/``?`` row in
``session_date_status_1626_1630`` and writes one row per ledger key so that
Step 4B's day-level join has something to join against. Same loading
machinery as ``notebooks/candidate_scoring_prototype.ipynb`` and
``scripts/s4_session_date_mapping_predictions.py`` -- no new matching logic.

Also runs the window-widen follow-up (Step 1's "modest window widen"): for
``N``-status rows with a same-inventory HTR session at a +/-2..+/-7-day
offset (``analyze_n_status_gaps.nearest_recovery_candidates``,
``WIDE_WINDOW_OFFSETS``), scores that wider-offset session the same way,
via ``score_ledger_row``'s ``candidate_ids`` override. These rows are
cross-day by construction, so a confident match here is what activates
``cross_day_shift`` in the Step C concordance -- previously always zero
because no ``-1``/``+1``/``?`` row had produced a confident automatic
candidate yet.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from analyze_n_status_gaps import (
    WIDE_WINDOW_MAX_DAYS,
    WIDE_WINDOW_OFFSETS,
    direct_session_ids,
    nearest_recovery_candidates,
)
from build_alignment_new import (
    LOC_ENTITIES_FILE,
    ORG_ENTITIES_FILE,
    PER_ENTITIES_FILE,
    calculate_idf_weights,
    load_entity_names,
    load_institution_names,
    load_persons_info_lookup,
    resolve_enriched_entities,
)
from data_io import load, resolve, save_semi_structured
from scripts.s4_candidate_scoring import candidate_session_ids, is_nihil_actum, score_ledger_row
from scripts.s4_corpus_paragraph_predictions import OVERLAP_DATASETS
from scripts.s4_paragraph_axis_baseline import build_axis_overlap

LEDGER_DATASET = "session_date_status_1626_1630"
FLAT_DATASET = "resolutions_flat"
OUTPUT_DATASET = "s4_candidate_scoring_predictions"
CANDIDATE_STATUSES = ("A", "X", "-1", "+1", "?")
WIDE_WINDOW_STATUS = "N"


def load_lookups() -> tuple[
    dict[str, str],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[tuple[str, str], set[str]],
    dict[str, float],
    dict[str, list[str]],
]:
    """Build the enriched-text, flat-session, axis-session, overlap, IDF, and
    enriched-entity-name lookups."""
    enriched_records = load("enriched_resolutions_1626_1630")
    flat = load("resolutions_flat")
    axis = load("paragraph_axis_1626_1630")

    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [
        frame.rename(columns={"naam": "name"}) if "name" not in frame and "naam" in frame else frame
        for frame in overlaps
    ]
    combined_overlap = pd.concat(overlaps, ignore_index=True)
    overlap_lookup = build_axis_overlap(axis, combined_overlap)
    idf_weights = calculate_idf_weights(combined_overlap)

    enriched_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in enriched_records:
        enriched_by_date[str(record.get("date", ""))[:10]].append(record)
    enriched_text_by_date: dict[str, str] = defaultdict(str)
    for date, records in enriched_by_date.items():
        records.sort(key=lambda item: item.get("resolution_index", 0))
        enriched_text_by_date[date] = " ".join(str(item.get("text", "")) for item in records if item.get("text"))

    flat_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in flat.to_dict(orient="records"):
        session_id = str(record.get("id", "")).split("-resolution-", 1)[0]
        flat_by_session[session_id].append(record)

    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        session_id = str(record.get("flat_id", "")).split("-resolution-", 1)[0]
        axis_by_session[session_id].append(record)

    loc_names = load_entity_names(LOC_ENTITIES_FILE)
    per_names = load_entity_names(PER_ENTITIES_FILE)
    org_names = load_entity_names(ORG_ENTITIES_FILE)
    persons_info = load_persons_info_lookup()
    institution_names = load_institution_names()
    enriched_entity_names_by_date: dict[str, list[str]] = {}
    for date, records in enriched_by_date.items():
        names: set[str] = set()
        for record in records:
            resolved = resolve_enriched_entities(
                record, loc_names, per_names, org_names,
                persons_info=persons_info, institution_names=institution_names,
            )
            names.update(resolved["places"], resolved["persons"], resolved["orgs"])
        enriched_entity_names_by_date[date] = sorted(names)

    return (
        enriched_text_by_date, flat_by_session, axis_by_session, overlap_lookup, idf_weights,
        enriched_entity_names_by_date,
    )


def score_row(
    row: dict[str, Any],
    enriched_text_by_date: dict[str, str],
    flat_by_session: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    overlap_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    candidate_ids: list[str] | None = None,
    wide_window_offset: int | None = None,
    enriched_entity_names: list[str] | None = None,
) -> dict[str, Any]:
    """Score one ledger row and flatten it to a single audit-friendly record.

    ``candidate_ids``/``wide_window_offset``/``enriched_entity_names`` are set
    for the window-widen follow-up (``N``-status rows scored against a
    wider-offset session rather than a ledger candidate column, using
    text-confirmed entity names rather than the axis-based overlap lookup --
    see ``score_ledger_row``'s docstring).
    """
    ranked = score_ledger_row(
        row, enriched_text_by_date, flat_by_session, axis_by_session, overlap_lookup, idf_weights,
        candidate_ids=candidate_ids, enriched_entity_names=enriched_entity_names,
    )
    top = ranked[0] if ranked else None
    record = {
        "session_date_key": row["session_date_key"],
        "inventory_id": int(row["inventory_id"]),
        "enriched_date": str(row["enriched_date"]),
        "status_code": row["status_code"],
        "candidate_session_ids": candidate_ids if candidate_ids is not None else candidate_session_ids(row),
        "wide_window_offset": wide_window_offset,
        "nihil_actum": is_nihil_actum(enriched_text_by_date.get(str(row["enriched_date"]), "")),
        "ranked_candidates": ranked,
        "top_candidate_session_id": top["session_id"] if top else None,
        "entity_overlap_score": top["entity_overlap_score"] if top else None,
        "dense_similarity_score": top["dense_similarity"] if top else None,
        "combined_score": top["combined_score"] if top else None,
        "low_confidence": top["low_confidence"] if top else None,
    }
    return record


def wide_window_row_candidates(ledger: pd.DataFrame, flat: pd.DataFrame) -> dict[str, tuple[int, list[str]]]:
    """Return ``{session_date_key: (offset, session_ids)}`` for N-status rows
    recoverable within ``WIDE_WINDOW_OFFSETS`` (the +/-2..+/-7-day band)."""
    known = direct_session_ids(flat)
    n_rows = ledger.loc[
        ledger["status_code"].eq(WIDE_WINDOW_STATUS), ["session_date_key", "inventory_id", "enriched_date"]
    ]
    result: dict[str, tuple[int, list[str]]] = {}
    for row in n_rows.itertuples(index=False):
        period = pd.Period(row.enriched_date, freq="D")
        hit = nearest_recovery_candidates(int(row.inventory_id), period, known, offsets=WIDE_WINDOW_OFFSETS)
        if hit is not None:
            result[str(row.session_date_key)] = hit
    return result


def main() -> None:
    ledger = load(LEDGER_DATASET)
    flat = load(FLAT_DATASET)
    candidate_rows = ledger.loc[ledger["status_code"].isin(CANDIDATE_STATUSES)].sort_values(
        ["inventory_id", "enriched_date"]
    )
    wide_window = wide_window_row_candidates(ledger, flat)
    wide_rows = ledger.loc[ledger["session_date_key"].isin(wide_window)].sort_values(["inventory_id", "enriched_date"])
    (
        enriched_text_by_date, flat_by_session, axis_by_session, overlap_lookup, idf_weights,
        enriched_entity_names_by_date,
    ) = load_lookups()

    records = [
        score_row(row, enriched_text_by_date, flat_by_session, axis_by_session, overlap_lookup, idf_weights)
        for row in candidate_rows.to_dict(orient="records")
    ]
    records += [
        score_row(
            row, enriched_text_by_date, flat_by_session, axis_by_session, overlap_lookup, idf_weights,
            candidate_ids=wide_window[row["session_date_key"]][1],
            wide_window_offset=wide_window[row["session_date_key"]][0],
            enriched_entity_names=enriched_entity_names_by_date.get(str(row["enriched_date"]), []),
        )
        for row in wide_rows.to_dict(orient="records")
    ]
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)

    scored = sum(1 for record in records if record["top_candidate_session_id"] is not None)
    nihil = sum(1 for record in records if record["nihil_actum"])
    wide_scored = sum(
        1 for record in records if record.get("wide_window_offset") is not None and record["top_candidate_session_id"]
    )
    wide_confident = sum(
        1
        for record in records
        if record.get("wide_window_offset") is not None
        and record["top_candidate_session_id"]
        and not record["low_confidence"]
    )
    print(f"Wrote {len(records)} candidate-scoring rows to {output}")
    print(f"{scored} rows scored a top candidate; {nihil} abstained as nihil actum")
    print(
        f"{len(wide_rows)} N-status rows had a +/-{WIDE_WINDOW_MAX_DAYS} day recovery candidate; "
        f"{wide_scored} scored a top pick, {wide_confident} of those cleared the confidence floor"
    )


if __name__ == "__main__":
    main()

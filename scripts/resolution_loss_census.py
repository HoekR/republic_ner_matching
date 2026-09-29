#!/usr/bin/env python3
"""Census of where all 19,120 enriched resolutions end up, and why the unpaired ones are unpaired.

Buckets every enriched resolution by placement outcome, then cross-tabs each bucket against
the content-fingerprint verification status of the flat session it resolves to. The question
this exists to answer: of the 1,137 cross_day_shift resolutions -- which carry a resolved
session but no paragraph placement -- how many sit on a session whose HTR content is
independently confirmed, and whose date *label* is the only thing in dispute?

A confirmed fingerprint establishes that a flat session is a particular raw archival session.
It does not establish that the enriched sitting belongs to that session, and a raw date label
is never promoted to truth over a contested enriched date. Rows are therefore labelled
`relabel_candidate`, not `recoverable`. Diagnostic only: no status, mapping or placement is
modified.

Usage: uv run python -m scripts.resolution_loss_census
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
FINGERPRINT_DATASET = "s6b_session_fingerprint_match"
AUDIT_DATASET = "fingerprint_assignment_audit"
OUTPUT_DATASET = "resolution_loss_census"

PLACED = "placed"
UNPLACED_BUCKETS = ("cross_day_shift", "missing_htr", "nihil_actum")


def fingerprint_status_by_session(fingerprints: list[dict[str, Any]]) -> pd.DataFrame:
    """Session-level content-verification status, independent of which date claims it.

    Mirrors fingerprint_assignment_audit's verification rule: a session is verified only
    when exactly one raw session contains its fingerprint.
    """
    rows = []
    for record in fingerprints:
        matches = record.get("raw_matches") or []
        verified = record.get("raw_num") is not None and len(matches) == 1
        rows.append(
            {
                "flat_session_id": str(record["flat_session_id"]),
                "fingerprint_status": "verified"
                if verified
                else "ambiguous_fingerprint"
                if len(matches) > 1
                else "unmatched_fingerprint",
                "flat_raw_number_offset": record.get("offset") if verified else None,
            }
        )
    frame = pd.DataFrame(rows, columns=["flat_session_id", "fingerprint_status", "flat_raw_number_offset"])
    if frame["flat_session_id"].duplicated().any():
        raise ValueError("Fingerprint dataset contains duplicate flat session IDs")
    return frame


def census_rows(
    concordance: pd.DataFrame,
    fingerprints: list[dict[str, Any]],
    audit: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One row per enriched resolution, bucketed and cross-tabbed. Nothing is reassigned."""
    required = {"enriched_id", "enriched_date", "inventory_id", "resolution_index", "status", "resolved_session_id"}
    missing = required - set(concordance.columns)
    if missing:
        raise ValueError(f"Missing concordance columns: {sorted(missing)}")

    columns = set(required)
    if "paragraph_prediction_status" in concordance.columns:
        columns.add("paragraph_prediction_status")
    frame = concordance.loc[:, sorted(columns)].copy()
    frame["enriched_date"] = frame["enriched_date"].astype(str).str[:10]
    frame["inventory_id"] = frame["inventory_id"].astype(int)
    frame["flat_session_id"] = frame["resolved_session_id"].astype(str)
    frame.loc[frame["flat_session_id"].str.len() == 0, "flat_session_id"] = None

    placed = (
        frame["paragraph_prediction_status"].notna()
        if "paragraph_prediction_status" in frame.columns
        else pd.Series(False, index=frame.index)
    )
    frame["bucket"] = frame["status"].where(frame["status"].isin(UNPLACED_BUCKETS), PLACED)
    # A resolved_auto row without a paragraph prediction is not placed; surface it rather
    # than letting the status label imply a placement the pipeline never emitted.
    frame.loc[(frame["bucket"] == PLACED) & ~placed, "bucket"] = "resolved_unplaced"

    frame = frame.merge(fingerprint_status_by_session(fingerprints), how="left", on="flat_session_id", validate="many_to_one")
    frame["fingerprint_status"] = frame["fingerprint_status"].where(
        frame["flat_session_id"].notna(), "no_session"
    )
    frame["fingerprint_status"] = frame["fingerprint_status"].fillna("no_fingerprint_record")

    audit_frame = pd.DataFrame(
        audit, columns=["enriched_date", "inventory_id", "flat_session_id", "assessment", "raw_date_delta_days"]
    )
    if not audit_frame.empty:
        audit_frame["inventory_id"] = audit_frame["inventory_id"].astype(int)
        audit_frame = audit_frame.drop_duplicates(subset=["enriched_date", "inventory_id", "flat_session_id"])
        frame = frame.merge(
            audit_frame,
            how="left",
            on=["enriched_date", "inventory_id", "flat_session_id"],
            validate="many_to_one",
        )
    else:
        frame["assessment"] = None
        frame["raw_date_delta_days"] = None

    # The census's headline class: content-confirmed session, placement withheld. Whether the
    # enriched date or the raw label is right is exactly what this does not decide.
    frame["census_class"] = frame["bucket"]
    relabel = (frame["bucket"] == "cross_day_shift") & (frame["fingerprint_status"] == "verified")
    frame.loc[relabel, "census_class"] = "cross_day_shift_relabel_candidate"

    frame = frame.sort_values(["inventory_id", "enriched_date", "resolution_index"])
    return [
        {
            "enriched_id": str(row.enriched_id),
            "enriched_date": row.enriched_date,
            "inventory_id": int(row.inventory_id),
            "resolution_index": int(row.resolution_index),
            "status": str(row.status),
            "bucket": str(row.bucket),
            "census_class": str(row.census_class),
            "flat_session_id": row.flat_session_id if pd.notna(row.flat_session_id) else None,
            "fingerprint_status": str(row.fingerprint_status),
            "flat_raw_number_offset": int(row.flat_raw_number_offset)
            if pd.notna(row.flat_raw_number_offset)
            else None,
            "audit_assessment": row.assessment if pd.notna(row.assessment) else None,
            "raw_date_delta_days": int(row.raw_date_delta_days) if pd.notna(row.raw_date_delta_days) else None,
            "assignment_changed": False,
        }
        for row in frame.itertuples(index=False)
    ]


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-tabs that are the actual deliverable; the per-resolution rows are the evidence."""
    frame = pd.DataFrame(rows)
    unplaced = frame.loc[frame["bucket"] != PLACED]
    shift = frame.loc[frame["bucket"] == "cross_day_shift"]
    relabel = shift.loc[shift["fingerprint_status"] == "verified"]
    return {
        "record_type": "summary",
        "total_resolutions": int(len(frame)),
        "by_bucket": {str(k): int(v) for k, v in frame["bucket"].value_counts().items()},
        "by_census_class": {str(k): int(v) for k, v in frame["census_class"].value_counts().items()},
        "unplaced_total": int(len(unplaced)),
        "unplaced_by_inventory": {
            str(k): int(v) for k, v in unplaced["inventory_id"].value_counts().sort_index().items()
        },
        "cross_day_shift_total": int(len(shift)),
        "cross_day_shift_by_fingerprint_status": {
            str(k): int(v) for k, v in shift["fingerprint_status"].value_counts().items()
        },
        "cross_day_shift_relabel_candidates": int(len(relabel)),
        "cross_day_shift_relabel_candidate_share": round(len(relabel) / len(shift), 4) if len(shift) else None,
        "relabel_candidate_dates": int(relabel["enriched_date"].nunique()),
        "relabel_candidate_sessions": int(relabel["flat_session_id"].nunique()),
        "relabel_candidate_by_inventory": {
            str(k): int(v) for k, v in relabel["inventory_id"].value_counts().sort_index().items()
        },
        "relabel_candidate_by_offset": {
            str(k): int(v) for k, v in relabel["flat_raw_number_offset"].value_counts().sort_index().items()
        },
        "relabel_candidate_by_audit_assessment": {
            str(k): int(v) for k, v in relabel["audit_assessment"].value_counts(dropna=False).items()
        },
        "relabel_candidate_by_raw_date_delta_days": {
            str(k): int(v) for k, v in relabel["raw_date_delta_days"].value_counts(dropna=False).sort_index().items()
        },
        "placed_by_fingerprint_status": {
            str(k): int(v)
            for k, v in frame.loc[frame["bucket"] == PLACED, "fingerprint_status"].value_counts().items()
        },
        "assignment_changed": False,
    }


def main() -> None:
    concordance = load(CONCORDANCE_DATASET)
    rows = census_rows(concordance, load(FINGERPRINT_DATASET), load(AUDIT_DATASET))
    summary = summarise(rows)
    output = save_semi_structured([*rows, summary], logical_name=OUTPUT_DATASET, script=__file__)

    print(f"Wrote {len(rows)} resolution census rows + 1 summary to {output}")
    print(f"Buckets: {summary['by_bucket']}")
    print(f"Unplaced: {summary['unplaced_total']} by inventory {summary['unplaced_by_inventory']}")
    print(
        f"cross_day_shift {summary['cross_day_shift_total']} -> "
        f"{summary['cross_day_shift_relabel_candidates']} relabel candidates "
        f"({summary['cross_day_shift_relabel_candidate_share']}) "
        f"over {summary['relabel_candidate_dates']} dates / "
        f"{summary['relabel_candidate_sessions']} sessions"
    )
    print(f"  by fingerprint status: {summary['cross_day_shift_by_fingerprint_status']}")
    print(f"  by raw date delta:     {summary['relabel_candidate_by_raw_date_delta_days']}")
    print(f"  by audit assessment:   {summary['relabel_candidate_by_audit_assessment']}")
    print("Diagnostic only: no session assignment, status or paragraph placement changed")


if __name__ == "__main__":
    main()

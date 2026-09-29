#!/usr/bin/env python3
"""Audit enriched sitting -> flat session claims using flat -> raw content fingerprints.

Fingerprints verify HTR content identity, not an enriched date or resolution boundary.
The raw session's indexed date is an independent *label* to compare, not a truth to
substitute for a contested enriched sitting assignment. Output is diagnostic only:
no session mappings or paragraph placements are modified.

Usage: uv run python -m scripts.fingerprint_assignment_audit
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
FINGERPRINT_DATASET = "s6b_session_fingerprint_match"
RAW_INDEX_DATASET = "session_index_all"
OUTPUT_DATASET = "fingerprint_assignment_audit"


def audit_assignments(
    claims: pd.DataFrame, fingerprints: list[dict[str, Any]], raw_index: pd.DataFrame
) -> list[dict[str, Any]]:
    """One row per distinct sitting/session claim, with conflicts left visible.

    No raw number is interpreted as a date and no fingerprint is treated as
    evidence that the enriched sitting *belongs* to the matched raw session.
    """
    required = {"enriched_date", "inventory_id", "resolved_session_id"}
    if not required <= set(claims.columns):
        raise ValueError(f"Missing claim columns: {sorted(required - set(claims.columns))}")
    assigned = claims.loc[claims["resolved_session_id"].notna(), ["enriched_date", "inventory_id", "resolved_session_id"]].copy()
    assigned["resolved_session_id"] = assigned["resolved_session_id"].astype(str)
    assigned = assigned.loc[assigned["resolved_session_id"].str.len() > 0].drop_duplicates()
    assigned["enriched_date"] = assigned["enriched_date"].astype(str).str[:10]
    assigned["inventory_id"] = assigned["inventory_id"].astype(int)
    assigned = assigned.rename(columns={"resolved_session_id": "flat_session_id"})

    fp = pd.DataFrame(
        [
            {
                "flat_session_id": str(record["flat_session_id"]),
                "raw_session_id": str(record["raw_matches"][0])
                if record.get("raw_num") is not None and len(record.get("raw_matches") or []) == 1
                else None,
                "fingerprint_status": "verified"
                if record.get("raw_num") is not None and len(record.get("raw_matches") or []) == 1
                else "ambiguous_fingerprint" if len(record.get("raw_matches") or []) > 1 else "unmatched_fingerprint",
                "flat_raw_number_offset": record.get("offset"),
            }
            for record in fingerprints
        ],
        columns=["flat_session_id", "raw_session_id", "fingerprint_status", "flat_raw_number_offset"],
    )
    if fp["flat_session_id"].duplicated().any():
        raise ValueError("Fingerprint dataset contains duplicate flat session IDs")

    raw = raw_index[["session_id", "session_date"]].copy().rename(
        columns={"session_id": "raw_session_id", "session_date": "raw_date_label"}
    )
    if raw["raw_session_id"].duplicated().any():
        raise ValueError("Raw index contains duplicate session IDs")
    raw["raw_date_label"] = raw["raw_date_label"].astype(str).str[:10]
    frame = assigned.merge(fp, how="left", on="flat_session_id", validate="many_to_one")
    frame = frame.merge(raw, how="left", on="raw_session_id", validate="many_to_one")

    # Preserve collisions instead of arbitrary first-row selection: a date can claim
    # multiple flat sessions, or different dates can claim one verified raw session.
    frame["sitting_claim_count"] = frame.groupby(["inventory_id", "enriched_date"])["flat_session_id"].transform("size")
    raw_dates = (
        frame.loc[frame["raw_session_id"].notna()]
        .groupby("raw_session_id")["enriched_date"]
        .agg(lambda dates: sorted(set(dates)))
        .to_dict()
    )
    frame = frame.sort_values(["inventory_id", "enriched_date", "flat_session_id"])
    result = []
    for row in frame.itertuples(index=False):
        # Single pass over sitting claims (not an archival table transform); leave
        # date labels unparsed except when both are well-formed and comparable.
        raw_id = row.raw_session_id if pd.notna(row.raw_session_id) else None
        raw_date = row.raw_date_label if pd.notna(row.raw_date_label) else None
        if raw_id is None:
            assessment = row.fingerprint_status if pd.notna(row.fingerprint_status) else "no_fingerprint_record"
        elif raw_date is None:
            assessment = "raw_date_label_missing"
        elif row.sitting_claim_count > 1:
            assessment = "multiple_flat_claims"
        elif len(raw_dates[raw_id]) > 1:
            assessment = "raw_session_reused"
        else:
            assessment = "date_label_agrees" if row.enriched_date == raw_date else "date_label_conflict"
        delta = None
        if raw_date is not None:
            try:
                delta = int((pd.Period(raw_date, freq="D") - pd.Period(row.enriched_date, freq="D")).n)
            except ValueError:
                assessment = "invalid_date_label"
        result.append(
            {
                "enriched_date": row.enriched_date,
                "inventory_id": int(row.inventory_id),
                "flat_session_id": row.flat_session_id,
                "raw_session_id": raw_id,
                "raw_date_label": raw_date,
                "raw_date_delta_days": delta,
                "flat_raw_number_offset": int(row.flat_raw_number_offset) if pd.notna(row.flat_raw_number_offset) else None,
                "raw_session_claimed_by_dates": raw_dates.get(raw_id, []),
                "assessment": assessment,
                "assignment_changed": False,
            }
        )
    return result


def main() -> None:
    concordance = load(CONCORDANCE_DATASET)
    # Use the actual concordance claims; do not invent a sitting-to-session join
    # from the raw index's date labels.
    claims = concordance[["enriched_date", "inventory_id", "resolved_session_id"]]
    records = audit_assignments(claims, load(FINGERPRINT_DATASET), load(RAW_INDEX_DATASET))
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(records)} sitting/session audit rows to {output}")
    print(f"Assessments: {dict(Counter(row['assessment'] for row in records))}")
    print("Diagnostic only: no session assignment or paragraph placement changed")


if __name__ == "__main__":
    main()
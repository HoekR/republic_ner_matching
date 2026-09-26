#!/usr/bin/env python3
"""Validate browser session-date decisions and write a ledger-preserving approved artifact."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve, save_semi_structured
from scripts.build_session_date_mapping_review_ui import CANDIDATE_COLUMNS, REVIEW_STATUSES, candidate_sources


LEDGER_DATASET = "session_date_status_1626_1630"
DECISIONS_DATASET = "s4_session_date_mapping_decisions"
OUTPUT_DATASET = "s4_session_date_mapping_predictions_approved"
VALID_ACTIONS = {"approve", "no_match", "defer"}


def _json_value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if not isinstance(value, (list, dict, tuple)) and pd.isna(value):
        return None
    return value


def latest_decisions(decisions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Apply last-file-order-wins semantics to duplicate decision keys."""
    return {str(decision.get("session_date_key", "")): decision for decision in decisions}


def validate_decision(decision: dict[str, Any], row: dict[str, Any]) -> None:
    key = str(row["session_date_key"])
    if decision.get("ledger_status") != row["status_code"]:
        raise ValueError(f"{key}: ledger status does not match exported evidence")
    if row["status_code"] not in REVIEW_STATUSES:
        raise ValueError(f"{key}: decisions are only allowed for manual-review statuses")
    action = decision.get("action")
    if action not in VALID_ACTIONS:
        raise ValueError(f"{key}: unknown action {action!r}")
    selected = decision.get("selected_session_id")
    if action == "approve":
        allowed = {candidate["session_id"] for candidate in candidate_sources(row)}
        if selected not in allowed:
            raise ValueError(f"{key}: selected session is not an inventory-local candidate")
        if row["status_code"] in {"-1", "+1"} and not str(decision.get("note", "")).strip():
            raise ValueError(f"{key}: nearby approval requires a note")
    # Defer/no_match: the review UI may leave a candidate highlighted; ignore it.
    # merged_records already nulls selected_session_id for non-approvals.


def merged_records(ledger: pd.DataFrame, decisions: list[dict[str, Any]], reviewer: str, merged_at: str) -> list[dict[str, Any]]:
    """Return every ledger row, overlaying validated final review decisions."""
    rows = {str(row["session_date_key"]): row for row in ledger.to_dict(orient="records")}
    final = latest_decisions(decisions)
    unknown = sorted(set(final).difference(rows))
    if unknown:
        raise ValueError(f"Unknown session_date_key(s): {unknown[:3]}")
    for key, decision in final.items():
        validate_decision(decision, rows[key])

    records: list[dict[str, Any]] = []
    for row in ledger.sort_values(["inventory_id", "enriched_date"]).to_dict(orient="records"):
        record = {key: _json_value(value) for key, value in row.items()}
        decision = final.get(str(row["session_date_key"]))
        if decision is None:
            records.append({**record, "review_status": "unreviewed", "selected_session_id": None})
            continue
        action = decision["action"]
        records.append(
            {
                **record,
                "review_status": {"approve": "approved", "no_match": "abstained", "defer": "deferred"}[action],
                "selected_session_id": decision.get("selected_session_id") if action == "approve" else None,
                "reviewer": reviewer,
                "review_note": decision.get("note", ""),
                "decision_client_timestamp": decision.get("client_timestamp"),
                "decision_merged_at": merged_at,
                "decision_source": "s4_session_date_mapping_decisions",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewer", required=True, help="Reviewer name or initials recorded in the approved artifact")
    args = parser.parse_args()
    path = Path(resolve(DECISIONS_DATASET))
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Export decisions from the S4f review UI first.")
    exported = json.loads(path.read_text(encoding="utf-8"))
    if exported.get("format") != "s4_session_date_mapping_decisions_v1" or not isinstance(exported.get("decisions"), list):
        raise ValueError("Unsupported session-date decision export")
    records = merged_records(load(LEDGER_DATASET), exported["decisions"], args.reviewer, datetime.now(timezone.utc).isoformat())
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(records)} approved-mapping records to {output}")


if __name__ == "__main__":
    main()
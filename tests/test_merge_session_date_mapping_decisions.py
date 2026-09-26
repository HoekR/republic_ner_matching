import pandas as pd
import pytest

from scripts.merge_session_date_mapping_decisions import latest_decisions, merged_records, validate_decision


def _ledger() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date_key": ["session-3185|1626-01-01", "session-3185|1626-01-02"],
            "inventory_id": [3185, 3185],
            "enriched_date": ["1626-01-01", "1626-01-02"],
            "status_code": ["-1", "N"],
            "trusted_session_ids": [[], []],
            "exact_date_session_ids": [[], []],
            "previous_day_session_ids": [["session-3185-num-1"], []],
            "next_day_session_ids": [[], []],
            "fallback_distance": [-1, pd.NA],
            "evidence_field": ["preserve me", "preserve me too"],
        }
    )


def test_nearby_candidate_approval_requires_note():
    decision = {"ledger_status": "-1", "action": "approve", "selected_session_id": "session-3185-num-1", "note": ""}

    with pytest.raises(ValueError, match="requires a note"):
        validate_decision(decision, _ledger().iloc[0].to_dict())


def test_merge_rejects_candidate_outside_inventory_local_union():
    decisions = [{"session_date_key": "session-3185|1626-01-01", "ledger_status": "-1", "action": "approve", "selected_session_id": "session-3186-num-1", "note": "reason"}]

    with pytest.raises(ValueError, match="not an inventory-local candidate"):
        merged_records(_ledger(), decisions, "RK", "2026-09-01T00:00:00+00:00")


def test_last_file_order_wins_and_unreviewed_evidence_is_preserved():
    decisions = [
        {"session_date_key": "session-3185|1626-01-01", "ledger_status": "-1", "action": "defer", "selected_session_id": None, "note": "first"},
        {"session_date_key": "session-3185|1626-01-01", "ledger_status": "-1", "action": "approve", "selected_session_id": "session-3185-num-1", "note": "approved"},
    ]
    records = merged_records(_ledger(), decisions, "RK", "2026-09-01T00:00:00+00:00")

    assert latest_decisions(decisions)["session-3185|1626-01-01"]["action"] == "approve"
    assert records[0]["review_status"] == "approved"
    assert records[0]["selected_session_id"] == "session-3185-num-1"
    assert records[1]["review_status"] == "unreviewed"
    assert records[1]["evidence_field"] == "preserve me too"


def test_defer_may_carry_highlighted_candidate_but_merge_nulls_it():
    """Review UI can leave a candidate selected when deferring; merge must ignore it."""
    decisions = [
        {
            "session_date_key": "session-3185|1626-01-01",
            "ledger_status": "-1",
            "action": "defer",
            "selected_session_id": "session-3185-num-1",
            "note": "still looking",
        }
    ]
    records = merged_records(_ledger(), decisions, "RK", "2026-09-01T00:00:00+00:00")
    assert records[0]["review_status"] == "deferred"
    assert records[0]["selected_session_id"] is None


def test_merge_is_idempotent_for_fixed_inputs_and_timestamp():
    decisions = [{"session_date_key": "session-3185|1626-01-01", "ledger_status": "-1", "action": "no_match", "selected_session_id": None, "note": "not present"}]

    first = merged_records(_ledger(), decisions, "RK", "2026-09-01T00:00:00+00:00")
    second = merged_records(_ledger(), decisions, "RK", "2026-09-01T00:00:00+00:00")

    assert first == second
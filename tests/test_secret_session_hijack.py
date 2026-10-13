"""Secret-session hijack: flag accept + duplicate winner + apply shapes."""

from __future__ import annotations

import pandas as pd

from scripts.secret_session_hijack import (
    apply_hijack,
    build_proposals,
    duplicate_claim_map,
    hijack_dates,
)


def _toy_concordance() -> pd.DataFrame:
    # Flagged winner 1626-03-28 #14; loser 1626-03-26; undetermined 1626-05-13
    rows = []
    for i in range(3):
        rows.append({
            "enriched_date": "1626-03-26",
            "resolution_index": i,
            "status": "resolved_auto",
            "resolved_session_id": "session-4562-num-164",
            "resolved_session_date": "1626-03-26",
            "inventory_id": 4562,
            "paragraph_start_index": 0.0,
            "paragraph_end_index": 0.0,
            "paragraph_prediction_status": "predicted",
            "day_status": "resolved_auto",
        })
    for i in range(3):
        rows.append({
            "enriched_date": "1626-03-28",
            "resolution_index": i,
            "status": "resolved_auto",
            "resolved_session_id": "session-4562-num-164",
            "resolved_session_date": "1626-03-28",
            "inventory_id": 4562,
            "paragraph_start_index": 0.0 if i < 2 else 0.0,
            "paragraph_end_index": 0.0 if i < 2 else 4.0,
            "paragraph_prediction_status": "predicted",
            "day_status": "resolved_auto",
        })
    rows.append({
        "enriched_date": "1626-05-13",
        "resolution_index": 0,
        "status": "resolved_auto",
        "resolved_session_id": "session-4562-num-999",
        "resolved_session_date": "1626-05-13",
        "inventory_id": 4562,
        "paragraph_start_index": 0.0,
        "paragraph_end_index": 0.0,
        "paragraph_prediction_status": "predicted",
        "day_status": "resolved_auto",
    })
    # main-series control — must not be touched
    rows.append({
        "enriched_date": "1626-06-01",
        "resolution_index": 0,
        "status": "resolved_auto",
        "resolved_session_id": "session-3185-num-1",
        "resolved_session_date": "1626-06-01",
        "inventory_id": 3185,
        "paragraph_start_index": 0.0,
        "paragraph_end_index": 2.0,
        "paragraph_prediction_status": "predicted",
        "day_status": "resolved_auto",
    })
    return pd.DataFrame(rows)


def test_hijack_dates_only_4562():
    conc = _toy_concordance()
    dates = hijack_dates(conc)
    assert "1626-03-28" in dates
    assert "1626-06-01" not in dates


def test_apply_clears_loser_and_nonflag_keeps_flag(monkeypatch):
    conc = _toy_concordance()
    flag_keys = {("1626-03-28", 2)}
    monkeypatch.setattr(
        "scripts.secret_session_hijack.load_secret_flag_keys",
        lambda: flag_keys,
    )
    proposals = build_proposals(conc)
    actions = {
        r["enriched_date"]: r["action"]
        for r in proposals
        if r.get("record_type") == "date_proposal"
    }
    assert actions["1626-03-26"] == "duplicate_loser_clear"
    assert actions["1626-03-28"] == "withdraw_nonflag_reattach_flag"
    assert actions["1626-05-13"] == "abstain_undetermined"

    after, log = apply_hijack(conc, proposals)
    loser = after[after.enriched_date == "1626-03-26"]
    assert loser["resolved_session_id"].isna().all()
    assert (loser["status"] == "uncertain").all()

    kept = after[
        (after.enriched_date == "1626-03-28") & (after.resolution_index == 2)
    ]
    assert kept["resolved_session_id"].iloc[0] == "session-4562-num-164"
    assert kept["paragraph_end_index"].iloc[0] == 4.0

    cleared = after[
        (after.enriched_date == "1626-03-28") & (after.resolution_index < 2)
    ]
    assert cleared["resolved_session_id"].isna().all()

    control = after[after.enriched_date == "1626-06-01"]
    assert control["resolved_session_id"].iloc[0] == "session-3185-num-1"

    undet = after[after.enriched_date == "1626-05-13"]
    assert undet["resolved_session_id"].iloc[0] == "session-4562-num-999"


def test_duplicate_claim_map_flagged_wins(monkeypatch):
    conc = _toy_concordance()
    flag_keys = {("1626-03-28", 2)}
    dups = duplicate_claim_map(conc, flag_keys)
    info = dups["session-4562-num-164"]
    assert info["winner"] == "1626-03-28"
    assert "1626-03-26" in info["losers"]

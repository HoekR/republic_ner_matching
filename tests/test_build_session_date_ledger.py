import pandas as pd

from scripts.build_session_date_ledger import add_nearby_candidates, build_session_date_ledger


def test_classifies_trusted_and_exact_date_candidates_without_selection():
    enriched = [
        {"date": "1626-01-01", "resolution_index": 0},
        {"date": "1626-01-02", "resolution_index": 0},
        {"date": "1626-01-03", "resolution_index": 0},
        {"date": "1626-01-04", "resolution_index": 0},
    ]
    flat = pd.DataFrame(
        {
            "id": [
                "session-3185-num-1-resolution-1",
                "session-3185-num-2-resolution-1",
                "session-3185-num-3-resolution-1",
                "session-3185-num-4-resolution-1",
                "session-3185-num-5-resolution-1",
            ],
            "date": ["1626-01-01", "1626-01-02", "1626-01-03", "1626-01-04", "1626-01-04"],
        }
    )
    alignment = pd.DataFrame(
        {
            "enriched_id": ["1626-01-01_0", "1626-01-02_0", "1626-01-02_0"],
            "session_id": ["session-3185-num-1", "session-3185-num-2", "session-3185-num-3"],
            "date": ["1626-01-01", "1626-01-02", "1626-01-02"],
            "confidence_tier": ["tier1_anchor", "tier1_anchor", "tier1_anchor"],
        }
    )
    axis = [
        {"flat_id": flat_id, "date": "1626-01-01", "axis_id": f"{flat_id}#p0"}
        for flat_id in flat["id"]
    ]

    metadata = [{"inventory_num": 3185, "period_start": "1626-01-01", "period_end": "1626-12-31"}]
    ledger = build_session_date_ledger(enriched, flat, alignment, axis, metadata).set_index("enriched_date")

    assert ledger.loc["1626-01-01", "status_code"] == "T"
    assert ledger.loc["1626-01-02", "status_code"] == "A"
    assert ledger.loc["1626-01-03", "status_code"] == "E"
    assert ledger.loc["1626-01-04", "status_code"] == "X"
    assert ledger.loc["1626-01-04", "exact_date_session_ids"] == ["session-3185-num-4", "session-3185-num-5"]


def test_adds_review_only_nearby_candidates_for_unresolved_rows():
    ledger = pd.DataFrame(
        {
            "inventory_id": [3185, 3185, 3185, 3185, 3185],
            "enriched_date": ["1626-01-02", "1626-01-04", "1626-01-06", "1626-01-12", "1626-01-10"],
            "status_code": ["N", "N", "N", "N", "T"],
            "status_detail": ["no same-day HTR session candidate"] * 4 + ["one trusted Tier-1 session candidate"],
        }
    )
    direct = pd.DataFrame(
        {
            "inventory_id": [3185, 3185, 3185, 3185, 3186],
            "date": ["1626-01-01", "1626-01-05", "1626-01-07", "1626-01-09", "1626-01-01"],
            "session_id": ["session-3185-num-1", "session-3185-num-2", "session-3185-num-3", "session-3185-num-4", "session-3186-num-1"],
        }
    )

    result = add_nearby_candidates(ledger, direct).set_index("enriched_date")

    assert result.loc["1626-01-02", "status_code"] == "-1"
    assert result.loc["1626-01-04", "status_code"] == "+1"
    assert result.loc["1626-01-06", "status_code"] == "?"
    assert result.loc["1626-01-06", "nearby_ambiguous"]
    assert pd.isna(result.loc["1626-01-06", "fallback_distance"])
    assert result.loc["1626-01-12", "status_code"] == "N"
    assert result.loc["1626-01-12", "previous_day_session_ids"] == []
    assert result.loc["1626-01-12", "next_day_session_ids"] == []
    assert result.loc["1626-01-10", "status_code"] == "T"
    assert result.loc["1626-01-02", "previous_day_session_ids"] == ["session-3185-num-1"]
    assert result.loc["1626-01-02", "next_day_session_ids"] == []
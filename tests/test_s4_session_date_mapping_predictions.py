import pandas as pd
import numpy as np

from scripts.s4_session_date_mapping_predictions import _as_list, review_frame, selected_session


def test_selects_only_unique_same_day_trusted_or_direct_evidence():
    trusted = pd.Series({"status_code": "T", "trusted_session_ids": ["session-3185-num-1"]})
    direct = pd.Series({"status_code": "E", "exact_date_session_ids": ["session-3185-num-2"]})
    nearby = pd.Series({"status_code": "-1"})
    ambiguous = pd.Series({"status_code": "?", "nearby_ambiguous": True})

    assert selected_session(trusted) == ("session-3185-num-1", None)
    assert selected_session(direct) == ("session-3185-num-2", None)
    assert selected_session(nearby) == (None, "nearby_policy_pending")
    assert selected_session(ambiguous) == (None, "ambiguous_session_candidates")


def test_review_export_keeps_stable_key_and_note_column():
    ledger = pd.DataFrame(
        {
            "session_date_key": ["session-3185|1626-01-01"], "inventory_id": [3185],
            "enriched_date": ["1626-01-01"], "status_code": ["N"], "status_detail": ["no same-day HTR session candidate"],
            "trusted_anchor_count": [0], "trusted_session_ids": [[]], "exact_date_session_ids": [[]],
            "previous_day_session_ids": [["session-3185-num-1"]], "next_day_session_ids": [[]],
            "fallback_distance": [pd.NA], "nearby_ambiguous": [False], "exact_date_paragraph_count": [0],
        }
    )

    review = review_frame(ledger)

    assert review.loc[0, "session_date_key"] == "session-3185|1626-01-01"
    assert review.loc[0, "previous_day_session_ids"] == "session-3185-num-1"
    assert "review_note" in review.columns


def test_normalizes_parquet_candidate_arrays():
    assert _as_list(np.array([], dtype=object)) == []
    assert _as_list(np.array(["session-3185-num-1"], dtype=object)) == ["session-3185-num-1"]
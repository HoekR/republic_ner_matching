import pandas as pd

from scripts.s4_resolution_concordance import (
    attach_paragraph_attribution,
    build_row,
    build_session_date_lookup,
    resolution_paragraph_range,
    select_day_status,
)


def _day_status(inventory_id, day_status, **overrides):
    row = {
        "session_date_key": f"session-{inventory_id}|1626-01-01",
        "inventory_id": inventory_id,
        "enriched_date": "1626-01-01",
        "day_status": day_status,
        "resolved_session_id": None,
        "resolution_source": "test",
    }
    row.update(overrides)
    return row


def test_select_day_status_picks_most_confident_candidate():
    candidates = [
        _day_status(4562, "missing_htr"),
        _day_status(3185, "resolved_auto", resolved_session_id="session-3185-num-1"),
        _day_status(4861, "missing_htr"),
    ]

    chosen = select_day_status(candidates)

    assert chosen["inventory_id"] == 3185
    assert chosen["day_status"] == "resolved_auto"
    assert chosen["inventory_ambiguous"] is False
    assert chosen["inventory_candidate_count"] == 3


def test_select_day_status_flags_ambiguity_on_tied_best_rank():
    candidates = [
        _day_status(3185, "resolved_auto", resolved_session_id="session-3185-num-1"),
        _day_status(4562, "resolved_auto", resolved_session_id="session-4562-num-1"),
    ]

    chosen = select_day_status(candidates)

    # Lowest inventory_id wins the tie-break, but the row is still flagged ambiguous.
    assert chosen["inventory_id"] == 3185
    assert chosen["inventory_ambiguous"] is True


def test_select_day_status_prefers_human_approval_over_automatic():
    candidates = [
        _day_status(3185, "resolved_auto", resolved_session_id="session-auto"),
        _day_status(4562, "resolved_manual", resolved_session_id="session-human"),
    ]

    chosen = select_day_status(candidates)

    assert chosen["inventory_id"] == 4562
    assert chosen["resolved_session_id"] == "session-human"


def test_resolution_paragraph_range_first_middle_last():
    cuts = [3, 7]  # K_e = 3 resolutions over a 10-paragraph stream
    assert resolution_paragraph_range(0, cuts, paragraph_count=10) == (0, 3)
    assert resolution_paragraph_range(1, cuts, paragraph_count=10) == (3, 7)
    assert resolution_paragraph_range(2, cuts, paragraph_count=10) == (7, 10)


def test_attach_paragraph_attribution_returns_null_when_abstained():
    prediction = {"status": "abstained", "reason": "insufficient_entity_anchors", "k_e": 5, "boundaries": []}

    result = attach_paragraph_attribution(0, k_e_local=5, prediction=prediction)

    assert result["paragraph_start_index"] is None
    assert result["paragraph_prediction_status"] == "abstained"


def test_attach_paragraph_attribution_returns_null_on_k_e_mismatch():
    prediction = {
        "status": "predicted",
        "k_e": 4,
        "paragraph_count": 10,
        "boundaries": [{"paragraph_stream_index": 3}, {"paragraph_stream_index": 6}, {"paragraph_stream_index": 8}],
    }

    result = attach_paragraph_attribution(0, k_e_local=5, prediction=prediction)

    assert result["paragraph_start_index"] is None


def test_attach_paragraph_attribution_predicts_range_when_counts_match():
    prediction = {
        "status": "predicted",
        "k_e": 3,
        "paragraph_count": 10,
        "boundaries": [{"paragraph_stream_index": 3}, {"paragraph_stream_index": 7}],
    }

    result = attach_paragraph_attribution(1, k_e_local=3, prediction=prediction)

    assert result == {"paragraph_start_index": 3, "paragraph_end_index": 7, "paragraph_prediction_status": "predicted"}


def test_build_session_date_lookup_strips_resolution_suffix():
    flat = pd.DataFrame(
        {
            "id": ["session-3185-num-1-resolution-1", "session-3185-num-1-resolution-2", "session-4562-num-9"],
            "date": ["1626-01-01", "1626-01-01", "1626-01-02"],
        }
    )

    lookup = build_session_date_lookup(flat)

    assert lookup == {"session-3185-num-1": "1626-01-01", "session-4562-num-9": "1626-01-02"}


def _resolution(index=0, date="1626-01-01"):
    return {
        "enriched_date": date,
        "resolution_index": index,
        "file": "x.xml",
        "text": "t",
        "institutions": [],
        "persons": [],
        "places": [],
        "ships": [],
        "secret": False,
        "president_ids": [],
        "deputy_ids": [],
    }


def test_build_row_flags_cross_day_shift_when_resolved_session_is_on_another_day():
    day_status = _day_status(3185, "resolved_auto", resolved_session_id="session-3185-num-1")
    day_status["inventory_ambiguous"] = False
    day_status["inventory_candidate_count"] = 1
    session_dates = {"session-3185-num-1": "1626-01-02"}  # actual session date differs from enriched_date

    row = build_row(_resolution(), k_e_local=1, day_status=day_status, session_dates=session_dates, paragraph_prediction=None)

    assert row["status"] == "cross_day_shift"
    assert row["day_status"] == "resolved_auto"
    assert row["resolved_session_date"] == "1626-01-02"
    assert row["paragraph_start_index"] is None


def test_build_row_keeps_day_status_when_session_matches_same_day():
    day_status = _day_status(3185, "resolved_auto", resolved_session_id="session-3185-num-1")
    day_status["inventory_ambiguous"] = False
    day_status["inventory_candidate_count"] = 1
    session_dates = {"session-3185-num-1": "1626-01-01"}

    row = build_row(_resolution(), k_e_local=1, day_status=day_status, session_dates=session_dates, paragraph_prediction=None)

    assert row["status"] == "resolved_auto"

from scripts.s4_day_status_resolution import resolve_row


def _row(status_code: str, **overrides):
    row = {
        "session_date_key": "3186|1627-09-02",
        "inventory_id": 3186,
        "enriched_date": "1627-09-02",
        "status_code": status_code,
        "trusted_session_ids": [],
        "exact_date_session_ids": [],
    }
    row.update(overrides)
    return row


def test_trusted_status_passes_through_as_resolved_auto():
    row = _row("T", trusted_session_ids=["session-a"])

    result = resolve_row(row, approved={}, candidate_scores={}, n_recovery_offsets={})

    assert result["day_status"] == "resolved_auto"
    assert result["resolved_session_id"] == "session-a"
    assert result["resolution_source"] == "ledger_direct"


def test_exact_date_status_passes_through_as_resolved_auto():
    row = _row("E", exact_date_session_ids=["session-b"])

    result = resolve_row(row, approved={}, candidate_scores={}, n_recovery_offsets={})

    assert result["day_status"] == "resolved_auto"
    assert result["resolved_session_id"] == "session-b"


def test_human_approved_mapping_outranks_automatic_candidate():
    row = _row("?")
    approved = {row["session_date_key"]: {"selected_session_id": "session-human"}}
    candidate_scores = {
        row["session_date_key"]: {"nihil_actum": False, "top_candidate_session_id": "session-auto", "low_confidence": False}
    }

    result = resolve_row(row, approved, candidate_scores, n_recovery_offsets={})

    assert result["day_status"] == "resolved_manual"
    assert result["resolved_session_id"] == "session-human"
    assert result["resolution_source"] == "s4f_human_decision"


def test_confident_candidate_score_resolves_automatically():
    row = _row("A")
    candidate_scores = {
        row["session_date_key"]: {"nihil_actum": False, "top_candidate_session_id": "session-auto", "low_confidence": False}
    }

    result = resolve_row(row, approved={}, candidate_scores=candidate_scores, n_recovery_offsets={})

    assert result["day_status"] == "resolved_auto"
    assert result["resolved_session_id"] == "session-auto"
    assert result["resolution_source"] == "candidate_scoring"


def test_low_confidence_candidate_score_does_not_resolve():
    row = _row("A")
    candidate_scores = {
        row["session_date_key"]: {"nihil_actum": False, "top_candidate_session_id": "session-auto", "low_confidence": True}
    }

    result = resolve_row(row, approved={}, candidate_scores=candidate_scores, n_recovery_offsets={})

    assert result["day_status"] == "uncertain"
    assert result["resolved_session_id"] is None


def test_nihil_actum_flag_takes_precedence_over_missing_candidate():
    row = _row("X")
    candidate_scores = {row["session_date_key"]: {"nihil_actum": True, "top_candidate_session_id": None, "low_confidence": None}}

    result = resolve_row(row, approved={}, candidate_scores=candidate_scores, n_recovery_offsets={})

    assert result["day_status"] == "nihil_actum"
    assert result["resolved_session_id"] is None


def test_n_status_with_no_wider_window_recovery_is_missing_htr():
    row = _row("N")

    result = resolve_row(row, approved={}, candidate_scores={}, n_recovery_offsets={row["session_date_key"]: None})

    assert result["day_status"] == "missing_htr"
    assert result["resolution_source"] == "ledger_n_status_no_recovery"


def test_n_status_recoverable_at_wider_offset_is_uncertain_not_missing_htr():
    row = _row("N")

    result = resolve_row(row, approved={}, candidate_scores={}, n_recovery_offsets={row["session_date_key"]: -2})

    assert result["day_status"] == "uncertain"
    assert result["resolution_source"] == "ledger_n_status_recoverable_wider_window"


def test_n_status_scored_but_low_confidence_wide_window_is_uncertain_with_scoring_source():
    row = _row("N")
    candidate_scores = {
        row["session_date_key"]: {"nihil_actum": False, "top_candidate_session_id": "session-x", "low_confidence": True}
    }

    result = resolve_row(
        row, approved={}, candidate_scores=candidate_scores, n_recovery_offsets={row["session_date_key"]: -2}
    )

    assert result["day_status"] == "uncertain"
    assert result["resolved_session_id"] is None
    assert result["resolution_source"] == "candidate_scoring_low_confidence"


def test_n_status_missing_from_offsets_dict_is_missing_htr():
    row = _row("N")

    result = resolve_row(row, approved={}, candidate_scores={}, n_recovery_offsets={})

    assert result["day_status"] == "missing_htr"


def test_non_n_status_with_no_candidate_score_is_uncertain():
    row = _row("?")

    result = resolve_row(row, approved={}, candidate_scores={}, n_recovery_offsets={})

    assert result["day_status"] == "uncertain"
    assert result["resolution_source"] == "no_confident_source"

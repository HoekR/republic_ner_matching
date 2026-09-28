import pandas as pd

from scripts.s4_day_status_resolution import deduplicate_session_claims, fold_in_candidates, resolve_row


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


def test_uncertain_status_resolved_by_fold_in_candidate():
    row = _row("?")
    fold_in = {
        row["session_date_key"]: {
            "resolved_session_id": "session-neighbor",
            "fold_in_side": "previous",
            "fold_in_slack": 4,
        }
    }

    result = resolve_row(row, approved={}, candidate_scores={}, n_recovery_offsets={}, fold_in=fold_in)

    assert result["day_status"] == "resolved_auto"
    assert result["resolved_session_id"] == "session-neighbor"
    assert result["resolution_source"] == "fold_in_recovered"


def _ledger_row(inventory_id, enriched_date, status_code, **overrides):
    row = {
        "session_date_key": f"{inventory_id}|{enriched_date}",
        "inventory_id": inventory_id,
        "enriched_date": enriched_date,
        "status_code": status_code,
        "enriched_count": 0,
        "exact_date_paragraph_count": 0,
        "previous_day_session_ids": [],
        "next_day_session_ids": [],
    }
    row.update(overrides)
    return row


def test_fold_in_candidates_recovers_unambiguous_neighbor_with_slack():
    ledger = pd.DataFrame(
        [
            _ledger_row(
                3185, "1626-03-27", "T", enriched_count=6, exact_date_paragraph_count=10,
            ),
            _ledger_row(
                3185, "1626-03-28", "?", enriched_count=3,
                previous_day_session_ids=["session-3185-num-56"],
                next_day_session_ids=["session-3185-num-57"],
            ),
            _ledger_row(
                3185, "1626-03-29", "T", enriched_count=4, exact_date_paragraph_count=4,
            ),
        ]
    )

    result = fold_in_candidates(ledger)

    assert result["3185|1626-03-28"]["resolved_session_id"] == "session-3185-num-56"
    assert result["3185|1626-03-28"]["fold_in_side"] == "previous"
    assert result["3185|1626-03-28"]["fold_in_slack"] == 4


def test_fold_in_candidates_leaves_row_when_both_neighbors_have_slack():
    ledger = pd.DataFrame(
        [
            _ledger_row(3185, "1626-03-27", "T", enriched_count=2, exact_date_paragraph_count=10),
            _ledger_row(
                3185, "1626-03-28", "?", enriched_count=3,
                previous_day_session_ids=["session-3185-num-56"],
                next_day_session_ids=["session-3185-num-57"],
            ),
            _ledger_row(3185, "1626-03-29", "T", enriched_count=1, exact_date_paragraph_count=10),
        ]
    )

    result = fold_in_candidates(ledger)

    assert "3185|1626-03-28" not in result


def test_fold_in_candidates_skips_when_neither_neighbor_has_slack():
    ledger = pd.DataFrame(
        [
            _ledger_row(3185, "1626-03-27", "T", enriched_count=10, exact_date_paragraph_count=10),
            _ledger_row(
                3185, "1626-03-28", "?", enriched_count=3,
                previous_day_session_ids=["session-3185-num-56"],
                next_day_session_ids=["session-3185-num-57"],
            ),
            _ledger_row(3185, "1626-03-29", "T", enriched_count=4, exact_date_paragraph_count=4),
        ]
    )

    result = fold_in_candidates(ledger)

    assert "3185|1626-03-28" not in result


def test_fold_in_candidates_two_gap_rows_sharing_one_neighbor_within_budget_both_resolve():
    # 1626-02-22 (need=1) and 1626-02-24 (need=8) both fold into 1626-02-23's
    # session, whose slack is exactly 9 -- fits combined, both should resolve.
    ledger = pd.DataFrame(
        [
            _ledger_row(
                3185, "1626-02-22", "?", enriched_count=1,
                previous_day_session_ids=["session-3185-num-35"],
                next_day_session_ids=["session-3185-num-36"],
            ),
            _ledger_row(3185, "1626-02-23", "T", enriched_count=10, exact_date_paragraph_count=19),
            _ledger_row(
                3185, "1626-02-24", "?", enriched_count=8,
                previous_day_session_ids=["session-3185-num-36"],
                next_day_session_ids=["session-3185-num-37"],
            ),
        ]
    )

    result = fold_in_candidates(ledger)

    assert result["3185|1626-02-22"]["resolved_session_id"] == "session-3185-num-36"
    assert result["3185|1626-02-24"]["resolved_session_id"] == "session-3185-num-36"


def test_fold_in_candidates_two_gap_rows_sharing_one_neighbor_over_budget_neither_resolves():
    # Same setup, but 1626-02-24 now needs 9 -- combined demand (1+9=10) exceeds
    # the shared slack of 9, so neither claimant should be guessed.
    ledger = pd.DataFrame(
        [
            _ledger_row(
                3185, "1626-02-22", "?", enriched_count=1,
                previous_day_session_ids=["session-3185-num-35"],
                next_day_session_ids=["session-3185-num-36"],
            ),
            _ledger_row(3185, "1626-02-23", "T", enriched_count=10, exact_date_paragraph_count=19),
            _ledger_row(
                3185, "1626-02-24", "?", enriched_count=9,
                previous_day_session_ids=["session-3185-num-36"],
                next_day_session_ids=["session-3185-num-37"],
            ),
        ]
    )

    result = fold_in_candidates(ledger)

    assert "3185|1626-02-22" not in result
    assert "3185|1626-02-24" not in result


def test_fold_in_candidates_skips_ambiguous_multi_candidate_rows():
    ledger = pd.DataFrame(
        [
            _ledger_row(3185, "1626-03-27", "T", enriched_count=2, exact_date_paragraph_count=10),
            _ledger_row(
                3185, "1626-03-28", "?", enriched_count=3,
                previous_day_session_ids=["session-3185-num-56", "session-3185-num-56b"],
                next_day_session_ids=["session-3185-num-57"],
            ),
            _ledger_row(3185, "1626-03-29", "T", enriched_count=4, exact_date_paragraph_count=4),
        ]
    )

    result = fold_in_candidates(ledger)

    assert "3185|1626-03-28" not in result


def _candidate(session_id: str, combined_score: float, low_confidence: bool = False) -> dict:
    return {
        "session_id": session_id,
        "entity_overlap_score": combined_score,
        "dense_similarity": 0.0,
        "combined_score": combined_score,
        "low_confidence": low_confidence,
    }


def test_deduplicate_session_claims_leaves_non_colliding_picks_untouched():
    candidate_scores = {
        "key-1": {"ranked_candidates": [_candidate("session-a", 10.0)]},
        "key-2": {"ranked_candidates": [_candidate("session-b", 5.0)]},
    }

    result = deduplicate_session_claims(candidate_scores)

    assert result["key-1"]["top_candidate_session_id"] == "session-a"
    assert result["key-2"]["top_candidate_session_id"] == "session-b"
    assert result["key-1"]["low_confidence"] is False
    assert result["key-2"]["low_confidence"] is False


def test_deduplicate_session_claims_higher_score_wins_the_shared_session():
    candidate_scores = {
        "key-low": {"ranked_candidates": [_candidate("session-x", 4.0)]},
        "key-high": {"ranked_candidates": [_candidate("session-x", 9.0)]},
    }

    result = deduplicate_session_claims(candidate_scores)

    assert result["key-high"]["top_candidate_session_id"] == "session-x"
    assert result["key-high"]["combined_score"] == 9.0


def test_deduplicate_session_claims_loser_falls_back_to_next_confident_candidate():
    candidate_scores = {
        "key-low": {
            "ranked_candidates": [_candidate("session-x", 4.0), _candidate("session-y", 3.0)]
        },
        "key-high": {"ranked_candidates": [_candidate("session-x", 9.0)]},
    }

    result = deduplicate_session_claims(candidate_scores)

    assert result["key-high"]["top_candidate_session_id"] == "session-x"
    assert result["key-low"]["top_candidate_session_id"] == "session-y"
    assert result["key-low"]["low_confidence"] is False


def test_deduplicate_session_claims_loser_with_no_alternative_becomes_low_confidence():
    candidate_scores = {
        "key-low": {"ranked_candidates": [_candidate("session-x", 4.0)]},
        "key-high": {"ranked_candidates": [_candidate("session-x", 9.0)]},
    }

    result = deduplicate_session_claims(candidate_scores)

    assert result["key-low"]["top_candidate_session_id"] is None
    assert result["key-low"]["low_confidence"] is True


def test_deduplicate_session_claims_ignores_rows_with_no_confident_candidate():
    candidate_scores = {
        "key-nihil": {"ranked_candidates": [], "nihil_actum": True},
        "key-unconfident": {"ranked_candidates": [_candidate("session-z", 1.0, low_confidence=True)]},
    }

    result = deduplicate_session_claims(candidate_scores)

    assert result["key-nihil"] == candidate_scores["key-nihil"]
    assert result["key-unconfident"]["ranked_candidates"][0]["low_confidence"] is True
    assert "top_candidate_session_id" not in result["key-unconfident"]

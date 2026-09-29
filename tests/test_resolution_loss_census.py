import pandas as pd

from scripts.resolution_loss_census import census_rows, fingerprint_status_by_session, summarise


def _concordance(rows):
    return pd.DataFrame(rows)


def _row(enriched_id, date, status, session, index=0, inventory=3185, predicted=None):
    return {
        "enriched_id": enriched_id,
        "enriched_date": date,
        "inventory_id": inventory,
        "resolution_index": index,
        "status": status,
        "resolved_session_id": session,
        "paragraph_prediction_status": predicted,
    }


def test_cross_day_shift_on_verified_session_is_a_relabel_candidate_not_a_correction():
    concordance = _concordance(
        [
            _row("e-1", "1626-01-02", "cross_day_shift", "session-3185-num-3"),
            _row("e-2", "1626-01-03", "cross_day_shift", "session-3185-num-4"),
        ]
    )
    fingerprints = [
        {"flat_session_id": "session-3185-num-3", "raw_matches": ["session-3185-num-5"], "raw_num": 5, "offset": 2},
        {"flat_session_id": "session-3185-num-4", "raw_matches": [], "raw_num": None, "offset": None},
    ]
    audit = [
        {
            "enriched_date": "1626-01-02",
            "inventory_id": 3185,
            "flat_session_id": "session-3185-num-3",
            "assessment": "date_label_conflict",
            "raw_date_delta_days": 3,
        }
    ]

    rows = census_rows(concordance, fingerprints, audit)

    assert [row["census_class"] for row in rows] == [
        "cross_day_shift_relabel_candidate",
        "cross_day_shift",
    ]
    assert rows[0]["fingerprint_status"] == "verified"
    assert rows[0]["flat_raw_number_offset"] == 2
    assert rows[0]["raw_date_delta_days"] == 3
    assert rows[1]["fingerprint_status"] == "unmatched_fingerprint"
    # The census classifies; it never rewrites the assignment it is classifying.
    assert all(row["assignment_changed"] is False for row in rows)
    assert all(row["status"] == "cross_day_shift" for row in rows)


def test_missing_htr_and_nihil_actum_have_no_session_to_verify():
    concordance = _concordance(
        [
            _row("e-1", "1626-01-04", "missing_htr", "", inventory=4562),
            _row("e-2", "1626-01-05", "nihil_actum", ""),
        ]
    )

    rows = census_rows(concordance, [], [])

    assert {row["enriched_id"]: row["bucket"] for row in rows} == {"e-1": "missing_htr", "e-2": "nihil_actum"}
    assert all(row["fingerprint_status"] == "no_session" for row in rows)
    assert all(row["flat_session_id"] is None for row in rows)
    assert all(row["flat_raw_number_offset"] is None for row in rows)


def test_ambiguous_fingerprint_does_not_qualify_as_a_relabel_candidate():
    concordance = _concordance([_row("e-1", "1626-01-02", "cross_day_shift", "session-3185-num-3")])
    fingerprints = [
        {
            "flat_session_id": "session-3185-num-3",
            "raw_matches": ["session-3185-num-5", "session-3185-num-6"],
            "raw_num": None,
            "offset": None,
        }
    ]

    rows = census_rows(concordance, fingerprints, [])

    assert rows[0]["fingerprint_status"] == "ambiguous_fingerprint"
    assert rows[0]["census_class"] == "cross_day_shift"
    assert rows[0]["flat_raw_number_offset"] is None


def test_session_absent_from_the_fingerprint_dataset_is_distinct_from_an_unmatched_one():
    concordance = _concordance([_row("e-1", "1626-01-02", "cross_day_shift", "session-3185-num-9")])

    rows = census_rows(concordance, [], [])

    assert rows[0]["fingerprint_status"] == "no_fingerprint_record"
    assert rows[0]["census_class"] == "cross_day_shift"


def test_resolved_status_without_a_paragraph_prediction_is_surfaced_not_counted_as_placed():
    concordance = _concordance(
        [
            _row("e-1", "1626-01-02", "resolved_auto", "session-3185-num-3", predicted="predicted"),
            _row("e-2", "1626-01-02", "resolved_auto", "session-3185-num-3", index=1, predicted=None),
        ]
    )
    fingerprints = [
        {"flat_session_id": "session-3185-num-3", "raw_matches": ["session-3185-num-5"], "raw_num": 5, "offset": 0}
    ]

    rows = census_rows(concordance, fingerprints, [])

    assert [row["bucket"] for row in rows] == ["placed", "resolved_unplaced"]


def test_offset_is_only_reported_for_verified_sessions():
    fingerprints = [
        {"flat_session_id": "a", "raw_matches": ["r1"], "raw_num": 1, "offset": 4},
        # A stale offset on a session that did not uniquely verify must not leak through.
        {"flat_session_id": "b", "raw_matches": ["r1", "r2"], "raw_num": None, "offset": 9},
    ]

    frame = fingerprint_status_by_session(fingerprints).set_index("flat_session_id")

    assert frame.loc["a", "flat_raw_number_offset"] == 4
    assert pd.isna(frame.loc["b", "flat_raw_number_offset"])


def test_duplicate_flat_session_ids_are_rejected_rather_than_silently_deduplicated():
    fingerprints = [
        {"flat_session_id": "a", "raw_matches": ["r1"], "raw_num": 1, "offset": 0},
        {"flat_session_id": "a", "raw_matches": ["r2"], "raw_num": 2, "offset": 1},
    ]

    try:
        fingerprint_status_by_session(fingerprints)
    except ValueError as error:
        assert "duplicate" in str(error).lower()
    else:
        raise AssertionError("Expected duplicate flat session IDs to raise")


def test_summary_counts_relabel_candidates_against_the_cross_day_shift_denominator():
    concordance = _concordance(
        [
            _row("e-1", "1626-01-02", "cross_day_shift", "session-3185-num-3"),
            _row("e-2", "1626-01-02", "cross_day_shift", "session-3185-num-3", index=1),
            _row("e-3", "1626-01-03", "cross_day_shift", "session-3185-num-4"),
            _row("e-4", "1626-01-04", "missing_htr", "", inventory=4562),
        ]
    )
    fingerprints = [
        {"flat_session_id": "session-3185-num-3", "raw_matches": ["session-3185-num-5"], "raw_num": 5, "offset": 2},
        {"flat_session_id": "session-3185-num-4", "raw_matches": [], "raw_num": None, "offset": None},
    ]

    summary = summarise(census_rows(concordance, fingerprints, []))

    assert summary["total_resolutions"] == 4
    assert summary["cross_day_shift_total"] == 3
    assert summary["cross_day_shift_relabel_candidates"] == 2
    assert summary["cross_day_shift_relabel_candidate_share"] == round(2 / 3, 4)
    assert summary["relabel_candidate_dates"] == 1
    assert summary["relabel_candidate_sessions"] == 1
    assert summary["unplaced_total"] == 4
    assert summary["unplaced_by_inventory"] == {"3185": 3, "4562": 1}
    assert summary["assignment_changed"] is False

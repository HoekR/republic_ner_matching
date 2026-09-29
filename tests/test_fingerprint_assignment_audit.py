import pandas as pd

from scripts.fingerprint_assignment_audit import audit_assignments


def test_fingerprint_verifies_identity_without_promoting_raw_date_to_truth():
    claims = pd.DataFrame(
        [
            {"enriched_date": "1626-01-02", "inventory_id": 3185, "resolved_session_id": "session-3185-num-3"},
            {"enriched_date": "1626-01-03", "inventory_id": 3185, "resolved_session_id": "session-3185-num-4"},
        ]
    )
    fingerprints = [
        {"flat_session_id": "session-3185-num-3", "raw_matches": ["session-3185-num-5"], "raw_num": 5, "offset": 2},
        {"flat_session_id": "session-3185-num-4", "raw_matches": ["session-3185-num-6"], "raw_num": 6, "offset": 2},
    ]
    raw = pd.DataFrame(
        [
            {"session_id": "session-3185-num-5", "session_date": "1626-01-02"},
            {"session_id": "session-3185-num-6", "session_date": "1626-01-04"},
        ]
    )

    rows = audit_assignments(claims, fingerprints, raw)

    assert [row["assessment"] for row in rows] == ["date_label_agrees", "date_label_conflict"]
    assert rows[0]["flat_session_id"] == "session-3185-num-3"
    assert rows[0]["raw_session_id"] == "session-3185-num-5"
    assert rows[1]["raw_date_delta_days"] == 1
    assert all(row["assignment_changed"] is False for row in rows)


def test_ambiguous_and_unmatched_fingerprints_never_become_pins():
    claims = pd.DataFrame(
        [
            {"enriched_date": "1626-01-02", "inventory_id": 3185, "resolved_session_id": "session-3185-num-3"},
            {"enriched_date": "1626-01-03", "inventory_id": 3185, "resolved_session_id": "session-3185-num-4"},
        ]
    )
    fingerprints = [
        {"flat_session_id": "session-3185-num-3", "raw_matches": ["session-3185-num-5", "session-3185-num-6"], "raw_num": None},
        {"flat_session_id": "session-3185-num-4", "raw_matches": [], "raw_num": None},
    ]
    raw = pd.DataFrame([{"session_id": "session-3185-num-5", "session_date": "1626-01-02"}])

    rows = audit_assignments(claims, fingerprints, raw)

    assert [row["assessment"] for row in rows] == ["ambiguous_fingerprint", "unmatched_fingerprint"]
    assert all(row["raw_session_id"] is None for row in rows)


def test_duplicate_enriched_claims_and_raw_reuse_are_flagged_not_silently_deduplicated():
    claims = pd.DataFrame(
        [
            {"enriched_date": "1626-01-02", "inventory_id": 3185, "resolved_session_id": "session-3185-num-3"},
            {"enriched_date": "1626-01-02", "inventory_id": 3185, "resolved_session_id": "session-3185-num-4"},
            {"enriched_date": "1626-01-03", "inventory_id": 3185, "resolved_session_id": "session-3185-num-5"},
        ]
    )
    fingerprints = [
        {"flat_session_id": "session-3185-num-3", "raw_matches": ["session-3185-num-8"], "raw_num": 8},
        {"flat_session_id": "session-3185-num-4", "raw_matches": ["session-3185-num-9"], "raw_num": 9},
        {"flat_session_id": "session-3185-num-5", "raw_matches": ["session-3185-num-8"], "raw_num": 8},
    ]
    raw = pd.DataFrame(
        [
            {"session_id": "session-3185-num-8", "session_date": "1626-01-02"},
            {"session_id": "session-3185-num-9", "session_date": "1626-01-02"},
        ]
    )

    rows = audit_assignments(claims, fingerprints, raw)

    assert len(rows) == 3
    assert rows[0]["assessment"] == rows[1]["assessment"] == "multiple_flat_claims"
    assert rows[0]["raw_session_claimed_by_dates"] == ["1626-01-02", "1626-01-03"]
    assert rows[2]["raw_session_claimed_by_dates"] == ["1626-01-02", "1626-01-03"]
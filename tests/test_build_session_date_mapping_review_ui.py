import pandas as pd

from scripts.build_session_date_mapping_review_ui import (
    build_payloads,
    candidate_sources,
    drop_nihil_actum_rows,
    enriched_text_by_date,
    queue_rows,
)


def _ledger() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date_key": ["session-3185|1626-01-01", "session-3185|1626-01-02", "session-3185|1626-01-03"],
            "inventory_id": [3185, 3185, 3185],
            "enriched_date": ["1626-01-01", "1626-01-02", "1626-01-03"],
            "status_code": ["T", "-1", "A"],
            "trusted_session_ids": [["session-3185-num-1"], [], ["session-3185-num-2"]],
            "exact_date_session_ids": [[], [], ["session-3185-num-2", "session-3185-num-3"]],
            "previous_day_session_ids": [[], ["session-3185-num-4"], []],
            "next_day_session_ids": [[], [], []],
        }
    )


def test_queue_excludes_automatic_statuses_and_preserves_order():
    rows = queue_rows(_ledger())

    assert [row["session_date_key"] for row in rows] == ["session-3185|1626-01-02", "session-3185|1626-01-03"]


def test_queue_status_filter_narrows_to_requested_codes():
    rows = queue_rows(_ledger(), statuses={"-1", "+1"})

    assert [row["session_date_key"] for row in rows] == ["session-3185|1626-01-02"]


def test_drop_nihil_actum_rows_excludes_only_pure_nihil_dates():
    rows = queue_rows(_ledger())
    enriched_records = [
        {"date": "1626-01-02", "resolution_index": 0, "text": "Nihil Actum."},
        {"date": "1626-01-03", "resolution_index": 0, "text": "Is gelesen een missive."},
    ]

    kept = drop_nihil_actum_rows(rows, enriched_text_by_date(enriched_records))

    assert [row["session_date_key"] for row in kept] == ["session-3185|1626-01-03"]


def test_candidate_union_deduplicates_and_retains_sources():
    sources = candidate_sources(queue_rows(_ledger())[1])

    assert sources == [
        {"session_id": "session-3185-num-2", "sources": ["trusted_session_ids", "exact_date_session_ids"]},
        {"session_id": "session-3185-num-3", "sources": ["exact_date_session_ids"]},
    ]


def test_payload_keeps_ordered_enriched_and_complete_candidate_evidence():
    flat = pd.DataFrame(
        {
            "id": ["session-3185-num-4-resolution-2", "session-3185-num-4-resolution-1"],
            "resolutions_text": ["second resolution", "first resolution"],
        }
    )
    payload = build_payloads(
        _ledger(),
        [
            {"date": "1626-01-02", "resolution_index": 1, "text": "second enriched"},
            {"date": "1626-01-02", "resolution_index": 0, "text": "first enriched"},
        ],
        flat,
        [
            {"axis_id": "two", "flat_id": "session-3185-num-4-resolution-2", "text": "second paragraph"},
            {"axis_id": "one", "flat_id": "session-3185-num-4-resolution-1", "text": "first paragraph"},
        ],
    )[0]

    assert [item["text"] for item in payload["enriched"]] == ["first enriched", "second enriched"]
    assert [item["flat_id"] for item in payload["candidates"][0]["resolutions"]] == [
        "session-3185-num-4-resolution-1", "session-3185-num-4-resolution-2"
    ]
    assert len(payload["candidates"][0]["paragraphs"]) == 2
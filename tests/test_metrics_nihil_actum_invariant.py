"""Unit tests for Tier V nihil-actum invariant."""

from __future__ import annotations

import pandas as pd

from scripts.metrics_nihil_actum_invariant import (
    build_day_series,
    build_output_records,
    ledger_nihil_session_violations,
)


def test_build_day_series_marks_nihil_as_structural_zero():
    concordance = pd.DataFrame(
        [
            {"enriched_date": "1626-01-11", "day_status": "nihil_actum", "resolved_session_id": None},
            {"enriched_date": "1626-01-12", "day_status": "resolved_auto", "resolved_session_id": "s-1"},
            {"enriched_date": "1626-01-12", "day_status": "resolved_auto", "resolved_session_id": "s-1"},
        ]
    )
    series = build_day_series(concordance)
    nihil = series.loc[series["enriched_date"] == "1626-01-11"].iloc[0]
    work = series.loc[series["enriched_date"] == "1626-01-12"].iloc[0]
    assert bool(nihil["is_nihil_actum"]) is True
    assert int(nihil["k_e"]) == 1
    assert int(nihil["k_e_signal"]) == 0
    assert int(nihil["attributed_count"]) == 0
    assert bool(nihil["invariant_ok"]) is True
    assert int(work["k_e"]) == 2
    assert int(work["k_e_signal"]) == 2


def test_invariant_fails_when_nihil_day_has_attribution():
    concordance = pd.DataFrame(
        [
            {
                "enriched_date": "1626-01-11",
                "day_status": "nihil_actum",
                "resolved_session_id": "session-3185-num-9",
            }
        ]
    )
    series = build_day_series(concordance)
    assert bool(series.iloc[0]["invariant_ok"]) is False
    assert int(series.iloc[0]["attributed_count"]) == 1


def test_ledger_violation_when_nihil_row_carries_session():
    violations = ledger_nihil_session_violations(
        [
            {
                "day_status": "nihil_actum",
                "session_date_key": "session-3185|1626-01-11",
                "enriched_date": "1626-01-11",
                "inventory_id": 3185,
                "resolved_session_id": "session-3185-num-9",
            },
            {
                "day_status": "nihil_actum",
                "session_date_key": "session-3185|1626-01-18",
                "enriched_date": "1626-01-18",
                "inventory_id": 3185,
                "resolved_session_id": None,
            },
        ]
    )
    assert len(violations) == 1
    assert violations[0]["record_type"] == "ledger_violation"
    assert violations[0]["enriched_date"] == "1626-01-11"


def test_build_output_records_meta_and_violation_rows():
    concordance = pd.DataFrame(
        [
            {
                "enriched_date": "1626-01-11",
                "day_status": "nihil_actum",
                "resolved_session_id": "session-bad",
            },
            {
                "enriched_date": "1626-01-12",
                "day_status": "resolved_auto",
                "resolved_session_id": "session-ok",
            },
        ]
    )
    series = build_day_series(concordance)
    records = build_output_records(series, [])
    meta = records[0]
    assert meta["record_type"] == "meta"
    assert meta["invariant_passed"] is False
    assert meta["n_nihil_days"] == 1
    assert meta["n_concordance_violations"] == 1
    assert sum(1 for r in records if r["record_type"] == "day") == 2
    assert sum(1 for r in records if r["record_type"] == "violation") == 1

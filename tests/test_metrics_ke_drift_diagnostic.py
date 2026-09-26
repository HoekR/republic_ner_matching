"""Unit tests for Tier D K_e drift diagnostic."""

from __future__ import annotations

import pandas as pd

from scripts.metrics_ke_drift_diagnostic import build_output_records, score_drift


def _days(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_score_drift_flags_spike_against_neighbor_median():
    series = _days(
        [
            {
                "enriched_date": "1626-01-10",
                "k_e": 10,
                "k_e_signal": 10,
                "day_status": "resolved_auto",
                "is_nihil_actum": False,
                "invariant_ok": True,
            },
            {
                "enriched_date": "1626-01-11",
                "k_e": 30,
                "k_e_signal": 30,
                "day_status": "resolved_auto",
                "is_nihil_actum": False,
                "invariant_ok": True,
            },
            {
                "enriched_date": "1626-01-12",
                "k_e": 10,
                "k_e_signal": 10,
                "day_status": "resolved_auto",
                "is_nihil_actum": False,
                "invariant_ok": True,
            },
        ]
    )
    scored = score_drift(series, window_days=3, threshold=10)
    mid = scored.loc[scored["enriched_date"] == "1626-01-11"].iloc[0]
    assert bool(mid["drift_flag"]) is True
    assert mid["drift_direction"] == "spike"


def test_score_drift_never_flags_nihil_days():
    series = _days(
        [
            {
                "enriched_date": "1626-01-10",
                "k_e": 12,
                "k_e_signal": 12,
                "day_status": "resolved_auto",
                "is_nihil_actum": False,
                "invariant_ok": True,
            },
            {
                "enriched_date": "1626-01-11",
                "k_e": 1,
                "k_e_signal": 0,
                "day_status": "nihil_actum",
                "is_nihil_actum": True,
                "invariant_ok": True,
            },
            {
                "enriched_date": "1626-01-12",
                "k_e": 12,
                "k_e_signal": 12,
                "day_status": "resolved_auto",
                "is_nihil_actum": False,
                "invariant_ok": True,
            },
        ]
    )
    scored = score_drift(series, window_days=3, threshold=10)
    nihil = scored.loc[scored["enriched_date"] == "1626-01-11"].iloc[0]
    assert bool(nihil["drift_flag"]) is False
    assert nihil["drift_direction"] == "none"


def test_build_output_records_blocks_v_violations():
    parent_meta = {"invariant_passed": False}
    scored = score_drift(
        _days(
            [
                {
                    "enriched_date": "1626-01-10",
                    "k_e": 10,
                    "k_e_signal": 10,
                    "day_status": "resolved_auto",
                    "is_nihil_actum": False,
                    "invariant_ok": True,
                },
                {
                    "enriched_date": "1626-01-11",
                    "k_e": 5,
                    "k_e_signal": 5,
                    "day_status": "nihil_actum",
                    "is_nihil_actum": True,
                    "invariant_ok": False,
                },
                {
                    "enriched_date": "1626-01-12",
                    "k_e": 25,
                    "k_e_signal": 25,
                    "day_status": "resolved_auto",
                    "is_nihil_actum": False,
                    "invariant_ok": True,
                },
            ]
        ),
        threshold=10,
    )
    records = build_output_records(parent_meta, scored, threshold=10)
    meta = records[0]
    assert meta["n_blocked_by_v_violations"] == 1
    assert "1626-01-11" in meta["blocked_dates"]
    assert meta["parent_invariant_passed"] is False
    candidates = [r for r in records if r["record_type"] == "candidate"]
    assert all(c["enriched_date"] != "1626-01-11" for c in candidates)

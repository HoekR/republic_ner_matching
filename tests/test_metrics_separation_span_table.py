"""Unit tests for Tier O consecutive-day separation span table."""

from __future__ import annotations

import pandas as pd

from scripts.metrics_separation_span_table import (
    attach_separation,
    count_separated_per_day,
    find_solid_runs,
    summarize_runs,
)


def test_count_separated_matches_unique_start_and_extent():
    concordance = pd.DataFrame(
        [
            # day A: two resolutions, unique starts, extents 2 and 2 -> both separated
            {
                "enriched_date": "1626-01-10",
                "paragraph_start_index": 0.0,
                "paragraph_end_index": 1.0,
            },
            {
                "enriched_date": "1626-01-10",
                "paragraph_start_index": 2.0,
                "paragraph_end_index": 3.0,
            },
            # day B: shared start paragraph -> neither separated
            {
                "enriched_date": "1626-01-11",
                "paragraph_start_index": 0.0,
                "paragraph_end_index": 1.0,
            },
            {
                "enriched_date": "1626-01-11",
                "paragraph_start_index": 0.0,
                "paragraph_end_index": 2.0,
            },
            # day C: unique start but extent 4 -> not separated
            {
                "enriched_date": "1626-01-12",
                "paragraph_start_index": 0.0,
                "paragraph_end_index": 3.0,
            },
            # no attribution
            {
                "enriched_date": "1626-01-13",
                "paragraph_start_index": None,
                "paragraph_end_index": None,
            },
        ]
    )
    per_day = count_separated_per_day(concordance).set_index("enriched_date")
    assert int(per_day.loc["1626-01-10", "separated_count"]) == 2
    assert int(per_day.loc["1626-01-11", "separated_count"]) == 0
    assert int(per_day.loc["1626-01-12", "separated_count"]) == 0
    assert "1626-01-13" not in per_day.index


def test_attach_separation_uses_k_e_signal_and_skips_nihil():
    day_series = pd.DataFrame(
        [
            {
                "enriched_date": "1626-01-10",
                "k_e": 4,
                "k_e_signal": 4,
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
                "k_e": 2,
                "k_e_signal": 2,
                "day_status": "resolved_auto",
                "is_nihil_actum": False,
                "invariant_ok": True,
            },
        ]
    )
    separated = pd.DataFrame(
        [
            {"enriched_date": "1626-01-10", "separated_count": 3, "paragraph_attributed_count": 3},
            {"enriched_date": "1626-01-11", "separated_count": 1, "paragraph_attributed_count": 1},
            {"enriched_date": "1626-01-12", "separated_count": 0, "paragraph_attributed_count": 0},
        ]
    )
    attached = attach_separation(day_series, separated).set_index("enriched_date")
    assert bool(attached.loc["1626-01-10", "is_solid"]) is True  # 3/4 = 0.75
    assert bool(attached.loc["1626-01-11", "is_solid"]) is False  # nihil
    assert float(attached.loc["1626-01-11", "separated_share"]) == 0.0
    assert bool(attached.loc["1626-01-12", "is_solid"]) is False  # 0/2


def test_find_solid_runs_gap0_breaks_on_non_solid():
    frame = pd.DataFrame(
        [
            {"enriched_date": "1626-01-10", "is_solid": True, "separated_count": 1, "k_e_signal": 2},
            {"enriched_date": "1626-01-11", "is_solid": False, "separated_count": 0, "k_e_signal": 2},
            {"enriched_date": "1626-01-12", "is_solid": True, "separated_count": 1, "k_e_signal": 2},
            {"enriched_date": "1626-01-13", "is_solid": True, "separated_count": 1, "k_e_signal": 2},
        ]
    )
    runs = find_solid_runs(frame, max_gap=0)
    assert len(runs) == 2
    assert runs[0]["start_date"] == "1626-01-10"
    assert runs[0]["end_date"] == "1626-01-10"
    assert runs[0]["calendar_days"] == 1
    assert runs[1]["start_date"] == "1626-01-12"
    assert runs[1]["end_date"] == "1626-01-13"
    assert runs[1]["calendar_days"] == 2


def test_find_solid_runs_gap1_bridges_one_non_solid():
    frame = pd.DataFrame(
        [
            {"enriched_date": "1626-01-10", "is_solid": True, "separated_count": 1, "k_e_signal": 2},
            {"enriched_date": "1626-01-11", "is_solid": False, "separated_count": 0, "k_e_signal": 2},
            {"enriched_date": "1626-01-12", "is_solid": True, "separated_count": 1, "k_e_signal": 2},
        ]
    )
    runs = find_solid_runs(frame, max_gap=1)
    assert len(runs) == 1
    assert runs[0]["start_date"] == "1626-01-10"
    assert runs[0]["end_date"] == "1626-01-12"
    assert runs[0]["calendar_days"] == 3
    assert runs[0]["n_non_solid_days"] == 1


def test_summarize_runs_global_spans_criterion():
    runs = [
        {"calendar_days": 40, "n_session_days": 30},
        {"calendar_days": 35, "n_session_days": 28},
        {"calendar_days": 32, "n_session_days": 25},
        {"calendar_days": 31, "n_session_days": 20},
        {"calendar_days": 30, "n_session_days": 20},
        {"calendar_days": 30, "n_session_days": 18},
        {"calendar_days": 10, "n_session_days": 8},
    ]
    summary = summarize_runs(runs, max_gap=1)
    assert summary["global_spans_n_spans"] == 6
    assert summary["global_spans_days_covered"] == 40 + 35 + 32 + 31 + 30 + 30
    assert summary["global_spans_criterion_met"] is True
    assert summary["by_min_length"]["7"]["n_spans"] == 7
    assert summary["by_min_length"]["60"]["n_spans"] == 0

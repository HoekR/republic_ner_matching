"""Unit tests for Tier O span-gap geography diagnostic."""

from __future__ import annotations

import pandas as pd

from scripts.metrics_span_gap_map import (
    annotate_days,
    classify_nonsolid_reason,
    find_inter_solid_gaps,
    longest_under_bridge,
    severe_collapse_dates,
    summarize_geography,
)


def test_classify_nonsolid_priority():
    assert classify_nonsolid_reason({"is_solid": True}) is None
    assert (
        classify_nonsolid_reason(
            {
                "is_solid": False,
                "invariant_ok": False,
                "is_nihil_actum": True,
                "day_status": "missing_htr",
            }
        )
        == "v_violation"
    )
    assert (
        classify_nonsolid_reason(
            {
                "is_solid": False,
                "invariant_ok": True,
                "is_nihil_actum": True,
                "day_status": "nihil_actum",
            }
        )
        == "nihil_actum"
    )
    assert (
        classify_nonsolid_reason(
            {
                "is_solid": False,
                "invariant_ok": True,
                "is_nihil_actum": False,
                "day_status": "missing_htr",
                "k_e_signal": 3,
            }
        )
        == "missing_htr"
    )
    assert (
        classify_nonsolid_reason(
            {
                "is_solid": False,
                "invariant_ok": True,
                "is_nihil_actum": False,
                "day_status": "resolved_auto",
                "k_e_signal": 4,
                "separated_share": 0.1,
            }
        )
        == "weak_separation"
    )


def test_severe_collapse_dates_counts_shared_starts():
    predictions = [
        {
            "date": "1626-01-01",
            "status": "predicted",
            "k_e": 8,
            # 7 cuts at paragraph 0 -> starts [0]+cuts => 8 on para 0
            "boundaries": [{"paragraph_stream_index": 0} for _ in range(7)],
        },
        {
            "date": "1626-01-02",
            "status": "predicted",
            "k_e": 3,
            "boundaries": [
                {"paragraph_stream_index": 1},
                {"paragraph_stream_index": 2},
            ],
        },
        {"date": "1626-01-03", "status": "abstained", "k_e": 10, "boundaries": []},
    ]
    assert severe_collapse_dates(predictions) == {"1626-01-01"}


def test_find_inter_solid_gaps_classifies_breakers():
    frame = pd.DataFrame(
        [
            {
                "enriched_date": "1626-01-10",
                "is_solid": True,
                "nonsolid_class": None,
                "is_drift_candidate": False,
                "is_severe_collapse": False,
            },
            {
                "enriched_date": "1626-01-11",
                "is_solid": False,
                "nonsolid_class": "missing_htr",
                "is_drift_candidate": False,
                "is_severe_collapse": False,
            },
            {
                "enriched_date": "1626-01-12",
                "is_solid": False,
                "nonsolid_class": "weak_separation",
                "is_drift_candidate": True,
                "is_severe_collapse": True,
            },
            {
                "enriched_date": "1626-01-13",
                "is_solid": True,
                "nonsolid_class": None,
                "is_drift_candidate": False,
                "is_severe_collapse": False,
            },
            {
                "enriched_date": "1626-01-14",
                "is_solid": True,
                "nonsolid_class": None,
                "is_drift_candidate": False,
                "is_severe_collapse": False,
            },
        ]
    )
    gaps = find_inter_solid_gaps(frame)
    assert len(gaps) == 2
    break_gap = gaps[0]
    assert break_gap["n_nonsolid_session_days"] == 2
    assert break_gap["dominant_class"] in {"missing_htr", "weak_separation"}
    assert break_gap["has_drift_candidate"] is True
    assert break_gap["has_severe_collapse"] is True
    assert gaps[1]["dominant_class"] == "adjacent_solid"
    assert gaps[1]["n_nonsolid_session_days"] == 0


def test_bridge_weak_separation_joins_solids():
    frame = pd.DataFrame(
        [
            {
                "enriched_date": "1626-01-10",
                "is_solid": True,
                "nonsolid_class": None,
                "separated_count": 1,
                "k_e_signal": 2,
            },
            {
                "enriched_date": "1626-01-11",
                "is_solid": False,
                "nonsolid_class": "weak_separation",
                "separated_count": 0,
                "k_e_signal": 2,
            },
            {
                "enriched_date": "1626-01-12",
                "is_solid": True,
                "nonsolid_class": None,
                "separated_count": 1,
                "k_e_signal": 2,
            },
        ]
    )
    baseline = longest_under_bridge(frame, bridge_class="nihil_actum")
    assert baseline["longest_calendar_days"] == 1
    bridged = longest_under_bridge(frame, bridge_class="weak_separation")
    assert bridged["longest_calendar_days"] == 3
    assert bridged["n_days_bridged"] == 1


def test_summarize_geography_recommended_focus():
    day_frame = annotate_days(
        pd.DataFrame(
            [
                {
                    "enriched_date": "1626-01-10",
                    "k_e_signal": 2,
                    "day_status": "resolved_auto",
                    "is_nihil_actum": False,
                    "invariant_ok": True,
                    "separated_share": 1.0,
                    "is_solid": True,
                    "separated_count": 2,
                },
                {
                    "enriched_date": "1626-01-11",
                    "k_e_signal": 2,
                    "day_status": "resolved_auto",
                    "is_nihil_actum": False,
                    "invariant_ok": True,
                    "separated_share": 0.0,
                    "is_solid": False,
                    "separated_count": 0,
                },
                {
                    "enriched_date": "1626-01-12",
                    "k_e_signal": 2,
                    "day_status": "resolved_auto",
                    "is_nihil_actum": False,
                    "invariant_ok": True,
                    "separated_share": 1.0,
                    "is_solid": True,
                    "separated_count": 2,
                },
            ]
        ),
        drift_dates=set(),
        collapse_dates=set(),
    )
    gaps = find_inter_solid_gaps(day_frame)
    meta = summarize_geography(
        day_frame,
        gaps,
        parent_meta={"n_solid_days": 2},
        n_severe_collapse_days=0,
        n_drift_candidates=0,
    )
    assert meta["n_breaking_gaps"] == 1
    assert meta["dominant_class_in_breaking_gaps"]["weak_separation"] == 1
    assert meta["severe_collapse_implicated"] is False
    assert meta["recommended_focus"] == "bridge_or_convert_dominant_interrupter"

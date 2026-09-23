"""Unit tests for the weak_separation headroom diagnostic."""

from __future__ import annotations

from scripts.metrics_weak_separation_headroom_diagnostic import (
    build_records,
    classify_headroom,
    structural_ceiling_share,
    summarize,
    weak_separation_day_record,
)


def test_structural_ceiling_share():
    assert structural_ceiling_share(10, 3) == 0.3
    assert structural_ceiling_share(10, 20) == 1.0
    assert structural_ceiling_share(10, 0) == 0.0
    assert structural_ceiling_share(0, 10) == 0.0


def test_classify_headroom():
    assert classify_headroom(0.3) == "structurally_capped"
    assert classify_headroom(0.5) == "headroom_available"
    assert classify_headroom(0.49999) == "structurally_capped"
    assert classify_headroom(1.0) == "headroom_available"


def test_weak_separation_day_record_filters_and_measures():
    non_weak = weak_separation_day_record(
        {"nonsolid_class": "missing_htr", "enriched_date": "1626-01-01"}, {}
    )
    assert non_weak is None

    capped = weak_separation_day_record(
        {
            "nonsolid_class": "weak_separation",
            "enriched_date": "1626-01-02",
            "k_e_signal": 10,
            "separated_share": 0.2,
            "day_status": "resolved_auto",
        },
        {"1626-01-02": {"paragraph_count": 3, "k_e": 10}},
    )
    assert capped is not None
    assert capped["structural_ceiling_share"] == 0.3
    assert capped["headroom_class"] == "structurally_capped"
    assert capped["headroom"] == 0.1  # ceiling 0.3 minus actual share 0.2
    assert capped["has_prediction"] is True

    headroom = weak_separation_day_record(
        {
            "nonsolid_class": "weak_separation",
            "enriched_date": "1626-01-03",
            "k_e_signal": 10,
            "separated_share": 0.2,
            "day_status": "resolved_auto",
        },
        {"1626-01-03": {"paragraph_count": 12, "k_e": 10}},
    )
    assert headroom is not None
    assert headroom["structural_ceiling_share"] == 1.0
    assert headroom["headroom_class"] == "headroom_available"
    assert headroom["headroom"] == round(1.0 - 0.2, 4)

    no_pred = weak_separation_day_record(
        {
            "nonsolid_class": "weak_separation",
            "enriched_date": "1626-01-04",
            "k_e_signal": 10,
            "separated_share": 0.2,
        },
        {},
    )
    assert no_pred is not None
    assert no_pred["paragraph_count"] == 0
    assert no_pred["structural_ceiling_share"] == 0.0
    assert no_pred["has_prediction"] is False


def test_summarize_recommends_by_dominant_bucket():
    capped_days = [
        {"headroom_class": "structurally_capped", "headroom": 0.0}
        for _ in range(6)
    ]
    headroom_days = [
        {"headroom_class": "headroom_available", "headroom": 0.3}
        for _ in range(2)
    ]
    meta = summarize(capped_days + headroom_days)
    assert meta["n_weak_separation_days"] == 8
    assert meta["n_structurally_capped"] == 6
    assert meta["n_headroom_available"] == 2
    assert meta["recommended_focus"] == "finer_axis_needed_most_days_structurally_capped"
    assert meta["mean_headroom_on_headroom_days"] == 0.3

    meta_empty = summarize([])
    assert meta_empty["recommended_focus"] == "no_weak_separation_days"


def test_build_records_joins_predictions_by_date():
    span_gap_records = [
        {"record_type": "meta", "n_solid_days": 0},
        {
            "record_type": "day",
            "enriched_date": "1626-01-05",
            "nonsolid_class": "weak_separation",
            "k_e_signal": 5,
            "separated_share": 0.4,
            "day_status": "resolved_auto",
        },
        {
            "record_type": "day",
            "enriched_date": "1626-01-06",
            "nonsolid_class": "missing_htr",
            "k_e_signal": 0,
            "separated_share": 0.0,
        },
    ]
    predictions = [
        {"date": "1626-01-05", "status": "predicted", "k_e": 5, "paragraph_count": 5},
    ]
    records = build_records(span_gap_records, predictions)
    assert records[0]["record_type"] == "meta"
    day_records = [r for r in records if r["record_type"] == "day"]
    assert len(day_records) == 1
    assert day_records[0]["enriched_date"] == "1626-01-05"
    assert day_records[0]["structural_ceiling_share"] == 1.0

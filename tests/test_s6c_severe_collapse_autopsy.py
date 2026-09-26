"""Unit tests for S6c severe-collapse autopsy."""

from __future__ import annotations

from scripts.s6c_severe_collapse_autopsy import (
    classify_cause,
    collapse_day_record,
    pigeonhole_floor,
    summarize,
)


def test_pigeonhole_floor():
    assert pigeonhole_floor(14, 2) == 7
    assert pigeonhole_floor(13, 2) == 7
    assert pigeonhole_floor(6, 2) == 3
    assert pigeonhole_floor(8, 0) == 8


def test_classify_cause_mutually_exclusive():
    assert classify_cause(k_e=14, paragraph_count=2) == "pigeonhole_forced"
    assert classify_cause(k_e=10, paragraph_count=5) == "axis_requires_repeats"
    assert classify_cause(k_e=10, paragraph_count=12) == "room_on_axis"
    assert classify_cause(k_e=10, paragraph_count=10) == "room_on_axis"


def test_collapse_day_record_filters_and_measures():
    severe = collapse_day_record(
        {
            "date": "1626-01-01",
            "status": "predicted",
            "k_e": 8,
            "paragraph_count": 3,
            "boundaries": [{"paragraph_stream_index": 0} for _ in range(7)],
        }
    )
    assert severe is not None
    assert severe["max_on_paragraph"] == 8
    assert severe["cause_class"] == "axis_requires_repeats"
    assert severe["pigeonhole_floor"] == 3
    assert severe["excess_over_floor"] == 5

    not_severe = collapse_day_record(
        {
            "date": "1626-01-02",
            "status": "predicted",
            "k_e": 4,
            "paragraph_count": 10,
            "boundaries": [
                {"paragraph_stream_index": 1},
                {"paragraph_stream_index": 2},
                {"paragraph_stream_index": 3},
            ],
        }
    )
    assert not_severe is None


def test_summarize_recommends_structural_when_pigeonhole_dominates():
    days = [
        {
            "cause_class": "pigeonhole_forced",
            "nonsolid_class": "weak_separation",
            "is_solid": False,
            "max_on_paragraph": 12,
            "excess_over_floor": 0,
        }
        for _ in range(6)
    ] + [
        {
            "cause_class": "room_on_axis",
            "nonsolid_class": "weak_separation",
            "is_solid": False,
            "max_on_paragraph": 8,
            "excess_over_floor": 5,
        }
        for _ in range(2)
    ]
    meta = summarize(days, [], n_predicted=100, parent_span_meta=None)
    assert meta["n_severe_collapse_days"] == 8
    assert meta["recommended_focus"] == "accept_structural_or_finer_axis"
    assert meta["cause_class_totals"]["pigeonhole_forced"] == 6

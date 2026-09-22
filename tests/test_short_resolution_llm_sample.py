"""Unit tests for short-resolution LLM sample split/gating logic."""

from __future__ import annotations

import random

import pytest

from scripts.build_short_resolution_llm_sample import (
    assert_split_gate,
    day_segmentation_class,
    parse_flat_id,
    position_stratum,
    select_candidates,
    select_days,
)


def _candidate(
    day: str,
    *,
    position_stratum_value: str,
    day_position: int = 0,
    boundary_gold: bool = False,
    htr_id: str | None = None,
) -> dict:
    return {
        "session_day": day,
        "position_stratum": position_stratum_value,
        "day_position": day_position,
        "is_boundary_gold_day": boundary_gold,
        "anchor_class": "weak_or_none",
        "htr_id": htr_id or f"{day}-htr-{day_position}",
        "enriched_id": f"{day}-enr-{day_position}",
    }


def test_parse_flat_id_extracts_session_order():
    parsed = parse_flat_id("session-3185-num-7-resolution-10")
    assert parsed["session_key"] == "session-3185-num-7"
    assert parsed["session_num"] == 7
    assert parsed["order"] == 10


def test_position_and_segmentation_helpers():
    assert position_stratum("short", True) == "short_initial"
    assert position_stratum("short", False) == "short_non_initial"
    assert day_segmentation_class(5, 5) == "matched_count"
    assert day_segmentation_class(7, 4) == "under_segmented"
    assert day_segmentation_class(3, 5) == "over_segmented"


def test_select_days_forces_boundary_gold_into_test_without_leakage():
    rows = []
    for i in range(20):
        day = f"1626-01-{i + 1:02d}"
        rows.append(_candidate(day, position_stratum_value="short_initial", day_position=0))
        rows.append(
            _candidate(day, position_stratum_value="short_non_initial", day_position=1)
        )
    gold = {"1626-01-01", "1626-01-02"}
    assignment = select_days(rows, gold, random.Random(42))
    assert assignment["1626-01-01"] == "test"
    assert assignment["1626-01-02"] == "test"
    # No day appears twice by construction of the dict.
    assert len(assignment) == len(set(assignment))


def test_select_candidates_balances_short_strata_and_passes_gate():
    rows = []
    days = [f"1626-02-{i:02d}" for i in range(1, 13)]
    for day in days:
        rows.append(_candidate(day, position_stratum_value="short_initial", day_position=0))
        rows.append(
            _candidate(day, position_stratum_value="short_non_initial", day_position=1)
        )
        rows.append(_candidate(day, position_stratum_value="long_non_initial", day_position=2))

    day_split = {day: split for day, split in zip(days, ["train", "dev", "test"] * 4)}
    selected = select_candidates(rows, day_split)
    assert_split_gate(selected)
    assert {row["session_day"] for row in selected if row["split"] == "train"}.isdisjoint(
        {row["session_day"] for row in selected if row["split"] == "test"}
    )
    assert sum(1 for row in selected if row["position_stratum"] == "short_initial") > 0
    assert sum(1 for row in selected if row["position_stratum"] == "short_non_initial") > 0


def test_assert_split_gate_rejects_missing_short_non_initial():
    rows = [
        {
            "split": "train",
            "session_day": "1626-03-01",
            "position_stratum": "short_initial",
        },
        {
            "split": "test",
            "session_day": "1626-03-02",
            "position_stratum": "short_initial",
        },
    ]
    with pytest.raises(RuntimeError, match="positional from semantic"):
        assert_split_gate(rows)

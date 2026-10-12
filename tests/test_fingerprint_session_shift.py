"""Unit tests for fingerprint_session_shift helpers — no corpus DP."""

from __future__ import annotations

from sequence_graph.fingerprint_session_shift import (
    label_top1_session,
    session_num,
    shift_session,
    _session_of_flat,
)


def test_shift_session_adds_delta():
    assert shift_session("session-3185-num-142", 8) == "session-3185-num-150"
    assert shift_session("session-3185-num-142", 9) == "session-3185-num-151"
    assert shift_session("bad", 8) is None


def test_session_num():
    assert session_num("session-3185-num-142") == 142
    assert session_num("") is None


def test_label_top1_gold_vs_competitor():
    gold = "session-3185-num-142"
    comp = "session-3185-num-150"
    assert (
        label_top1_session(
            gold_session=gold,
            competitor_session=comp,
            best_flat="session-3185-num-142-resolution-3",
            best_score=3.0,
            second_score=1.0,
            margin=0.5,
        )
        == "gold"
    )
    assert (
        label_top1_session(
            gold_session=gold,
            competitor_session=comp,
            best_flat="session-3185-num-150-resolution-1",
            best_score=3.0,
            second_score=1.0,
            margin=0.5,
        )
        == "competitor"
    )


def test_label_top1_hard_vs_production():
    assert (
        label_top1_session(
            gold_session="session-3185-num-150",
            competitor_session="session-3185-num-142",
            best_flat="session-3185-num-150-resolution-2",
            best_score=4.0,
            second_score=1.0,
            margin=0.5,
            prefer_label="hard",
            other_label="production",
        )
        == "hard"
    )


def test_label_top1_abstain_on_thin_margin():
    assert (
        label_top1_session(
            gold_session="session-3185-num-142",
            competitor_session="session-3185-num-150",
            best_flat="session-3185-num-142-resolution-1",
            best_score=2.0,
            second_score=1.7,
            margin=0.5,
        )
        == "abstain"
    )


def test_label_top1_abstain_missing_flat():
    assert (
        label_top1_session(
            gold_session="session-3185-num-142",
            competitor_session="session-3185-num-150",
            best_flat=None,
            best_score=0.0,
            second_score=0.0,
        )
        == "abstain"
    )


def test_neighbourhood_stay_vs_move_labels():
    """Date-free apply uses stay/move labels on S vs S+Δ."""
    s = "session-3185-num-150"
    neighbour = "session-3185-num-159"
    assert (
        label_top1_session(
            gold_session=s,
            competitor_session=neighbour,
            best_flat=f"{s}-resolution-1",
            best_score=4.0,
            second_score=1.0,
            margin=0.5,
            prefer_label="stay",
            other_label="move",
        )
        == "stay"
    )
    assert (
        label_top1_session(
            gold_session=s,
            competitor_session=neighbour,
            best_flat=f"{neighbour}-resolution-2",
            best_score=4.0,
            second_score=1.0,
            margin=0.5,
            prefer_label="stay",
            other_label="move",
        )
        == "move"
    )


def test_neighbourhood_gold_correct_vs_baseline_labels():
    assert (
        label_top1_session(
            gold_session="session-3185-num-159",
            competitor_session="session-3185-num-150",
            best_flat="session-3185-num-159-resolution-0",
            best_score=5.0,
            second_score=1.0,
            margin=0.5,
            prefer_label="correct",
            other_label="baseline",
        )
        == "correct"
    )


def test_session_of_flat_strips_resolution():
    assert (
        _session_of_flat("session-3185-num-150-resolution-3")
        == "session-3185-num-150"
    )
    assert shift_session("session-3185-num-150", 9) == "session-3185-num-159"

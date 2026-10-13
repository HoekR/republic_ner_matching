"""Unit tests for windowed boundary selection — no model I/O."""

from __future__ import annotations

from scripts.boundary_windowed_infer import select_min_gap, select_topk


def test_select_topk_picks_highest() -> None:
    scored = {10: 0.1, 50: 0.9, 90: 0.5, 120: 0.8}
    assert select_topk(scored, 2) == [50, 120]


def test_select_min_gap_suppresses_neighbours() -> None:
    # 50 and 55 are both high; gap should keep only the best near-cluster.
    scored = {50: 1.0, 55: 0.95, 200: 0.9, 205: 0.4}
    out = select_min_gap(scored, 2, char_len=400)
    assert 50 in out
    assert 200 in out
    assert 55 not in out

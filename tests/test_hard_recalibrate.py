"""Unit tests for hard_recalibrate helpers — no full corpus DP."""

from __future__ import annotations

from sequence_graph.hard_recalibrate import (
    _normalize,
    _token_jaccard,
    detect_lag_window,
)


def test_normalize_collapses_noise():
    assert _normalize("Ontfangen, een Missive!!") == "ontfangen een missive"


def test_token_jaccard_identity():
    s = _normalize("ontfangen een missive van de heeren")
    assert _token_jaccard(s, s) == 1.0
    assert _token_jaccard(s, _normalize("geheel andere tekst hier")) < 0.3


def test_detect_lag_window_prefers_aug_sep_cluster():
    status = [
        {"date": "1626-03-01", "disagree": True, "pin_delta": 8},
        {"date": "1626-03-02", "disagree": True, "pin_delta": 8},
        {"date": "1626-08-20", "disagree": True, "pin_delta": 8},
        {"date": "1626-08-21", "disagree": True, "pin_delta": 8},
        {"date": "1626-08-25", "disagree": True, "pin_delta": 8},
        {"date": "1626-09-01", "disagree": True, "pin_delta": 9},
    ]
    w = detect_lag_window(status, merge_gap_days=7)
    # Aug/Sep clusters union: 08-20..21 and 08-25..09-01
    assert w["calendar_lo"] == "1626-08-20"
    assert w["calendar_hi"] == "1626-09-01"
    assert w["n_lag_days"] == 4
    assert w["median_delta"] in (8, 9)
    assert w["n_aug_sep_clusters"] >= 1

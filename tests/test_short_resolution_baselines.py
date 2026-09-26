"""Unit tests for short-resolution baseline scoring logic."""

from __future__ import annotations

import pytest

from scripts.build_short_resolution_baselines import (
    compute_alignment_score,
    compute_combined_formula_entity_score,
    compute_positional_score,
    formula_detection_score,
)


def _candidate(
    is_session_initial: bool = True,
    session_order: int = 1,
    alignment_confidence_tier: str | None = None,
    alignment_overlap_score: float = 0.0,
) -> dict:
    return {
        "is_session_initial": is_session_initial,
        "session_order": session_order,
        "alignment_confidence_tier": alignment_confidence_tier,
        "alignment_overlap_score": alignment_overlap_score,
    }


def test_formula_detection_requires_both_open_and_close():
    """Formula detection requires both open and close match."""
    assert formula_detection_score(None, None) is False
    assert formula_detection_score(0.9, None) is False
    assert formula_detection_score(None, 0.9) is False
    assert formula_detection_score(0.9, 0.9) is True
    assert formula_detection_score(0.8, 0.9) is True


def test_alignment_score_ranks_by_tier():
    """Alignment score prefers tier1 > tier2 > tier3."""
    tier1 = compute_alignment_score(_candidate(alignment_confidence_tier="tier1_anchor"))
    tier2 = compute_alignment_score(_candidate(alignment_confidence_tier="tier2_adjacent"))
    tier3 = compute_alignment_score(_candidate(alignment_confidence_tier="tier3_head_template"))
    none = compute_alignment_score(_candidate(alignment_confidence_tier=None))
    
    assert tier1 < tier2 < tier3 < none


def test_alignment_score_prefers_higher_overlap():
    """Within a tier, higher overlap is better (lower score)."""
    low_overlap = compute_alignment_score(
        _candidate(
            alignment_confidence_tier="tier2_adjacent",
            alignment_overlap_score=0.1,
        )
    )
    high_overlap = compute_alignment_score(
        _candidate(
            alignment_confidence_tier="tier2_adjacent",
            alignment_overlap_score=0.9,
        )
    )
    
    assert high_overlap < low_overlap


def test_positional_score_prefers_session_initial():
    """Positional score prefers is_session_initial=True."""
    initial = compute_positional_score(_candidate(is_session_initial=True))
    non_initial = compute_positional_score(_candidate(is_session_initial=False))
    
    assert initial < non_initial


def test_positional_score_prefers_lower_session_order():
    """Positional score prefers lower session_order within same initial/non-initial."""
    early = compute_positional_score(
        _candidate(is_session_initial=False, session_order=1)
    )
    late = compute_positional_score(
        _candidate(is_session_initial=False, session_order=10)
    )
    
    assert early < late


def test_combined_formula_entity_score_prefers_both_formula():
    """Combined score prefers candidates with both open and close formula signals."""
    with_both = compute_combined_formula_entity_score(0.9, 0.9, 3.0)
    with_open_only = compute_combined_formula_entity_score(0.9, None, 3.0)
    with_neither = compute_combined_formula_entity_score(None, None, 3.0)
    
    # With both formula: biggest bonus (3.0 - 1.0 = 2.0)
    # With open only: smaller bonus (3.0 - 0.3 = 2.7)
    # With neither: penalty (3.0 + 1.0 = 4.0)
    assert with_both < with_open_only < with_neither


def test_combined_formula_entity_score_respects_alignment_rank():
    """Combined score still respects underlying alignment tier."""
    good_alignment = 1.0  # tier1 + high overlap
    bad_alignment = 5.0   # no tier
    
    combined_good = compute_combined_formula_entity_score(0.9, 0.9, good_alignment)
    combined_bad = compute_combined_formula_entity_score(0.9, 0.9, bad_alignment)
    
    # With same formula signals, lower alignment base score wins
    assert combined_good < combined_bad

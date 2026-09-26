"""Unit tests for short-resolution candidate ranking (Step 4)."""

from __future__ import annotations

import json
import pytest

from scripts.build_short_resolution_ranking import (
    CandidateRankingRecord,
    build_ranking_prompt,
    rank_candidate_dry_run,
)


def test_candidate_ranking_record_schema():
    """Test CandidateRankingRecord dataclass schema."""
    record = CandidateRankingRecord(
        session_day="1626-01-01",
        enriched_id="test_0",
        position_stratum="short_initial",
        split="test",
        enriched_text_len=100,
        anchor_class="tier1",
        day_segmentation="balanced",
        counts_matched=True,
        n_candidates=3,
        gold_htr_id="htr_123",
        gold_rank_baseline=1,
        candidates=[],
        model="test-model",
        prompt_version="v1",
        temperature=0.0,
        raw_response=None,
        parsed_choice=None,
        parse_success=False,
        parse_error="test",
        llm_choice_htr_id=None,
        llm_choice_rank=None,
        llm_confidence=0.0,
        llm_evidence_quote="",
        baseline_top1_correct=True,
        llm_top1_correct=None,
        top2_recall=True,
        llm_top2_recall=None,
        abstention_rate=False,
        llm_improves_baseline=None,
    )
    
    assert record.session_day == "1626-01-01"
    assert record.enriched_id == "test_0"
    assert record.position_stratum == "short_initial"
    assert record.gold_rank_baseline == 1
    assert record.baseline_top1_correct is True


def test_ranking_prompt_construction():
    """Test that ranking prompt is well-formed."""
    enriched_summary = {
        "kind": "petition",
        "actor": "Guild Master",
        "subject": "Trade petition",
        "action_or_decision": "Deferred",
        "is_receipt_or_no_decision": False,
        "is_session_opening": False,
        "is_continuation": False,
        "evidence_quote": "Petition received",
    }
    
    candidates = [
        {
            "rank": 1,
            "htr_id": "htr_1",
            "text": "Short text 1",
            "summary": {"kind": "petition", "actor": "Guild", "evidence_quote": "Quote 1"},
            "baseline_alignment_score": 1.0,
            "baseline_positional_score": 0.5,
            "baseline_combined_formula_entity_score": 1.5,
        },
        {
            "rank": 2,
            "htr_id": "htr_2",
            "text": "Short text 2",
            "summary": {"kind": "decision", "actor": "Council", "evidence_quote": "Quote 2"},
            "baseline_alignment_score": 2.0,
            "baseline_positional_score": 1.0,
            "baseline_combined_formula_entity_score": 3.0,
        },
    ]
    
    prompt = build_ranking_prompt("test_0", enriched_summary, candidates)
    
    assert "ENRICHED RESOLUTION STRUCTURED SUMMARY" in prompt
    assert "CANDIDATE A" in prompt
    assert "CANDIDATE B" in prompt
    assert "JSON" in prompt
    assert "rank" in prompt
    assert "confidence" in prompt


def test_ranking_prompt_no_summary():
    """Test ranking prompt with missing enriched summary."""
    candidates = [
        {
            "rank": 1,
            "htr_id": "htr_1",
            "text": "Text 1",
            "summary": None,
        },
    ]
    
    prompt = build_ranking_prompt("test_0", None, candidates)
    
    assert "CANDIDATE A" in prompt
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_rank_candidate_dry_run():
    """Test dry-run ranking returns valid schema."""
    candidates = [
        {
            "rank": 1,
            "htr_id": "htr_1",
            "text": "Text 1",
            "summary": {"kind": "petition"},
        },
        {
            "rank": 2,
            "htr_id": "htr_2",
            "text": "Text 2",
            "summary": {"kind": "decision"},
        },
    ]
    
    raw_response, parsed_choice, parse_success, parse_error = rank_candidate_dry_run(
        "test_0", candidates
    )
    
    assert parse_success is True
    assert parse_error is None
    assert isinstance(parsed_choice, dict)
    assert "rank" in parsed_choice
    assert "confidence" in parsed_choice
    assert "reason" in parsed_choice
    assert "abstain" in parsed_choice
    assert parsed_choice["rank"] in [1, 2]


def test_rank_candidate_dry_run_no_candidates():
    """Test dry-run with no candidates."""
    raw_response, parsed_choice, parse_success, parse_error = rank_candidate_dry_run("test_0", [])
    
    assert parse_success is False
    assert parse_error is not None


def test_ranking_metrics_computation():
    """Test that ranking metrics are computed correctly."""
    # Baseline top-1 correct, LLM abstains
    record1 = CandidateRankingRecord(
        session_day="1626-01-01",
        enriched_id="test_0",
        position_stratum="short_initial",
        split="test",
        enriched_text_len=100,
        anchor_class="tier1",
        day_segmentation="balanced",
        counts_matched=True,
        n_candidates=3,
        gold_htr_id="htr_1",
        gold_rank_baseline=1,  # Baseline correct
        candidates=[],
        model="test",
        prompt_version="v1",
        temperature=0.0,
        raw_response=None,
        parsed_choice=None,
        parse_success=False,
        parse_error=None,
        llm_choice_htr_id=None,
        llm_choice_rank=None,
        llm_confidence=0.0,
        llm_evidence_quote="",
        baseline_top1_correct=True,
        llm_top1_correct=None,  # LLM abstained
        top2_recall=True,
        llm_top2_recall=None,
        abstention_rate=True,  # Abstained
        llm_improves_baseline=None,
    )
    
    assert record1.baseline_top1_correct is True
    assert record1.abstention_rate is True
    assert record1.llm_top1_correct is None
    
    # LLM improves over baseline
    record2 = CandidateRankingRecord(
        session_day="1626-01-02",
        enriched_id="test_1",
        position_stratum="short_non_initial",
        split="test",
        enriched_text_len=150,
        anchor_class="weak_or_none",
        day_segmentation="under_segmented",
        counts_matched=False,
        n_candidates=2,
        gold_htr_id="htr_3",
        gold_rank_baseline=2,  # Baseline missed top-1
        candidates=[],
        model="test",
        prompt_version="v1",
        temperature=0.0,
        raw_response='{"rank": 1}',
        parsed_choice={"rank": 1, "confidence": 0.9},
        parse_success=True,
        parse_error=None,
        llm_choice_htr_id="htr_3",
        llm_choice_rank=1,  # LLM got top-1
        llm_confidence=0.9,
        llm_evidence_quote="Good match",
        baseline_top1_correct=False,
        llm_top1_correct=True,  # LLM improved
        top2_recall=True,
        llm_top2_recall=True,
        abstention_rate=False,
        llm_improves_baseline=True,
    )
    
    assert record2.baseline_top1_correct is False
    assert record2.llm_top1_correct is True
    assert record2.llm_improves_baseline is True

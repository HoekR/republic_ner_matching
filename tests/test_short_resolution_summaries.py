"""Unit tests for short-resolution structured summarizer (Step 3)."""

from __future__ import annotations

import json
import pytest

from scripts.build_short_resolution_summaries import (
    AUTHORITATIVE_GATE_PASS_RATE,
    StructuredSummary,
    SummaryRecord,
    apply_recover_to_record,
    build_few_shot_prompt_context,
    build_summarization_prompt,
    is_summary_failure,
    summary_quality_report,
    validate_summary,
)


def test_structured_summary_schema():
    """Test StructuredSummary dataclass schema validation."""
    summary = StructuredSummary(
        kind="petition",
        actor="Burgomaster",
        subject="Trade petition",
        action_or_decision="Deferred to next session",
        is_receipt_or_no_decision=False,
        is_session_opening=False,
        is_continuation=False,
        evidence_quote="Petition received from merchant guild",
        uncertainty=[]
    )
    
    assert summary.kind == "petition"
    assert len(summary.uncertainty) == 0
    assert summary.is_receipt_or_no_decision is False
    
    d = summary.to_dict()
    assert d["kind"] == "petition"
    assert isinstance(d, dict)


def test_structured_summary_valid_kinds():
    """Test that kind field accepts all valid values."""
    valid_kinds = [
        "receipt", "petition", "decision", "appointment",
        "continuation", "no_decision", "other", "uncertain"
    ]
    
    for kind in valid_kinds:
        summary = StructuredSummary(
            kind=kind,
            actor="",
            subject="",
            action_or_decision="",
            is_receipt_or_no_decision=False,
            is_session_opening=False,
            is_continuation=False,
            evidence_quote="test",
            uncertainty=[]
        )
        assert summary.kind == kind


def test_summarization_prompt_truncation():
    """Test that summarization prompt truncates long texts."""
    short_text = "This is a short text"
    long_text = "x" * 2000  # Longer than default limit
    
    prompt_short = build_summarization_prompt(short_text, "context")
    prompt_long = build_summarization_prompt(long_text, "context")
    
    # Short text should not mention truncation
    assert "truncated" not in prompt_short or "... text truncated" not in prompt_short
    
    # Long text should mention truncation
    assert "truncated" in prompt_long or "... text truncated" in prompt_long


def test_build_few_shot_context():
    """Test few-shot context building."""
    context = build_few_shot_prompt_context([])
    
    assert "17th-century" in context or "Dutch" in context
    assert "JSON" in context or "json" in context
    assert len(context) > 100


def test_validate_summary_no_parsed():
    """Test validation gate when parsed is None."""
    has_evidence, has_valid, notes = validate_summary(None, None)
    
    assert has_evidence is False
    assert has_valid is False
    assert "No parsed JSON" in notes


def test_validate_summary_missing_fields():
    """Test validation gate detects missing required fields."""
    incomplete = {
        "kind": "decision",
        "actor": "Test",
        # Missing: subject, action_or_decision, is_receipt_or_no_decision, etc.
    }
    
    has_evidence, has_valid, notes = validate_summary(incomplete, "raw")
    
    assert has_valid is False
    assert any("Missing fields" in note for note in notes)


def test_validate_summary_valid_complete():
    """Test validation gate passes with complete valid summary."""
    complete = {
        "kind": "decision",
        "actor": "Council",
        "subject": "Trade regulation",
        "action_or_decision": "Approved",
        "is_receipt_or_no_decision": False,
        "is_session_opening": False,
        "is_continuation": False,
        "evidence_quote": "We hereby approve the merchant regulation",
        "uncertainty": []
    }
    
    has_evidence, has_valid, notes = validate_summary(complete, "raw")
    
    assert has_evidence is True
    assert has_valid is True
    # Should have no notes (or empty)
    assert len(notes) == 0 or not any(note for note in notes)


def test_validate_summary_no_evidence_quote():
    """Test validation gate rejects when evidence quote is missing or too short."""
    no_quote = {
        "kind": "decision",
        "actor": "Council",
        "subject": "Trade",
        "action_or_decision": "Approved",
        "is_receipt_or_no_decision": False,
        "is_session_opening": False,
        "is_continuation": False,
        "evidence_quote": "",
        "uncertainty": []
    }
    
    has_evidence, has_valid, notes = validate_summary(no_quote, "raw")
    
    assert has_evidence is False
    assert any("evidence quote" in note.lower() for note in notes)


def test_summary_record_to_dict():
    """Test SummaryRecord serialization."""
    record = SummaryRecord(
        session_day="1626-01-01",
        enriched_id="test_enrich",
        htr_id="test_htr",
        is_session_initial=True,
        position_stratum="short_initial",
        split="train",
        htr_text_len=500,
        htr_text="Sample text",
        model="test-model",
        prompt_version="v1",
        temperature=0.0,
        max_tokens=500,
        input_char_limit=1500,
        raw_response='{"kind": "decision"}',
        parsed_summary={"kind": "decision"},
        parse_success=True,
        parse_error=None,
        has_evidence_quote=True,
        has_valid_structure=True,
        gate_passed=True,
        gate_notes=[]
    )
    
    d = record.to_dict()
    
    assert d["session_day"] == "1626-01-01"
    assert d["htr_id"] == "test_htr"
    assert d["parse_success"] is True
    assert d["gate_passed"] is True
    assert isinstance(d, dict)


def test_summary_quality_report_authoritative_threshold():
    """Quality report flags authoritative only at/above the process threshold."""
    good = {
        "htr_id": "ok",
        "parse_success": True,
        "gate_passed": True,
        "parsed_summary": {"kind": "receipt"},
        "raw_response": "{}",
    }
    bad = {
        "htr_id": "bad",
        "parse_success": False,
        "gate_passed": False,
        "parsed_summary": None,
        "raw_response": "not json",
    }
    # 9/10 = 90% meets default threshold
    records = [dict(good, htr_id=f"ok{i}") for i in range(9)] + [bad]
    report = summary_quality_report(records)
    assert report["n_failed"] == 1
    assert report["gate_pass_rate"] == pytest.approx(0.9)
    assert report["authoritative"] is True
    assert is_summary_failure(bad) is True

    # 8/10 = 80% fails threshold
    records_low = [dict(good, htr_id=f"ok{i}") for i in range(8)] + [bad, dict(bad, htr_id="bad2")]
    report_low = summary_quality_report(records_low)
    assert report_low["authoritative"] is False
    assert report_low["authoritative_threshold"] == AUTHORITATIVE_GATE_PASS_RATE


def test_apply_recover_to_record_salvages_trailing_noise():
    """Recover-from-raw should salvage JSON followed by trailing model noise."""
    payload = {
        "kind": "no_decision",
        "actor": "raad",
        "subject": "missive",
        "action_or_decision": "geen resolutie",
        "is_receipt_or_no_decision": True,
        "is_session_opening": True,
        "is_continuation": False,
        "evidence_quote": "Ontfangen een Missive waerop egeen resolutie",
        "uncertainty": [],
    }
    raw = json.dumps(payload) + "\n<|endoftext|>extra chatter"
    failed = {
        "htr_id": "h1",
        "parse_success": False,
        "gate_passed": False,
        "parsed_summary": None,
        "raw_response": raw,
        "gate_notes": [],
    }
    out, status = apply_recover_to_record(failed)
    assert status == "recovered"
    assert out["gate_passed"] is True
    assert out["parse_success"] is True
    assert out["parsed_summary"]["kind"] == "no_decision"

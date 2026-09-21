#!/usr/bin/env python3
"""Local LLM verification judge and tiebreaker for resolution alignment.

Uses local mlx-lm (e.g. qwen2.5-coder, llama3) to verify ambiguous summary-to-full-text
resolution pairs or resolve borderline alignment candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mlx_llm import check_available, extract_json, generate
from mlx_llm.model import DEFAULT_MODEL


@dataclass
class LLMVerdict:
    decision: Literal["match", "no_match", "uncertain"]
    confidence: float
    reason: str


def check_llm_available(model: str | None = None) -> bool:
    """Check if the specified model is available via mlx-lm.

    If no model is provided, checks the default model.
    Always returns bool, never raises.
    """
    if model is None:
        model = DEFAULT_MODEL
    return check_available(model)


def evaluate_pair(
    summary_text: str,
    full_text: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 20,
) -> LLMVerdict:
    """Verify whether a single enriched resolution summary matches a flat resolution full text."""
    prompt = f"""Context: 17th-century Dutch Republic States-General resolutions.
Task: Determine whether the given resolution summary accurately summarizes the full resolution text below.

[SUMMARY (Enriched Resolution)]
{summary_text.strip()[:600]}

[FULL TEXT (Flat Resolution HTR)]
{full_text.strip()[:1000]}

Instructions:
1. Focus on the primary actor (who submitted petition/report), the main subject matter, and the decision taken.
2. The summary may be concise or modernized; the full text is formal and verbose.
3. If they describe the exact same event/decision, decision is "match".
4. If they describe completely different matters, decision is "no_match".
5. If ambiguous or text is too corrupted, decision is "uncertain".

Respond ONLY with a JSON object in this exact schema:
{{"decision": "match" | "no_match" | "uncertain", "confidence": 0.0 to 1.0, "reason": "brief 1-sentence reason"}}
"""
    raw_response = generate(prompt, model=model, temperature=0.0)

    if raw_response is None:
        return LLMVerdict(decision="uncertain", confidence=0.0, reason="LLM unavailable")

    # Extract JSON block
    parsed = extract_json(raw_response)
    if parsed:
        decision = str(parsed.get("decision", "uncertain")).lower()
        if decision not in ("match", "no_match", "uncertain"):
            decision = "uncertain"
        confidence = float(parsed.get("confidence", 0.5))
        reason = str(parsed.get("reason", "LLM evaluation"))
        return LLMVerdict(decision=decision, confidence=confidence, reason=reason)

    return LLMVerdict(decision="uncertain", confidence=0.0, reason="Inconclusive LLM response")


def judge_tiebreak(
    summary_text: str,
    candidate_a_text: str,
    candidate_b_text: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 25,
) -> tuple[Literal["A", "B", "NONE", "UNCERTAIN"], float, str]:
    """Choose between two competing candidate flat resolutions for a single summary."""
    prompt = f"""Context: 17th-century Dutch Republic States-General resolutions.
Task: Choose which candidate full text [A] or [B] corresponds to the given resolution summary.

[SUMMARY]
{summary_text.strip()[:600]}

[CANDIDATE A]
{candidate_a_text.strip()[:700]}

[CANDIDATE B]
{candidate_b_text.strip()[:700]}

Respond ONLY with a JSON object in this exact schema:
{{"choice": "A" | "B" | "NONE" | "UNCERTAIN", "confidence": 0.0 to 1.0, "reason": "brief 1-sentence reason"}}
"""
    raw_response = generate(prompt, model=model, temperature=0.0)

    if raw_response is None:
        return "UNCERTAIN", 0.0, "LLM unavailable"

    parsed = extract_json(raw_response)
    if parsed:
        choice = str(parsed.get("choice", "UNCERTAIN")).upper()
        if choice not in ("A", "B", "NONE", "UNCERTAIN"):
            choice = "UNCERTAIN"
        confidence = float(parsed.get("confidence", 0.5))
        reason = str(parsed.get("reason", "Tiebreaker evaluation"))
        return choice, confidence, reason

    return "UNCERTAIN", 0.0, "Inconclusive response"

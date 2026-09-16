#!/usr/bin/env python3
"""Local LLM verification judge and tiebreaker for resolution alignment.

Uses local Ollama (e.g. qwen2.5-coder, llama3) to verify ambiguous summary-to-full-text
resolution pairs or resolve borderline alignment candidates.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal


OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2:latest"


@dataclass
class LLMVerdict:
    decision: Literal["match", "no_match", "uncertain"]
    confidence: float
    reason: str


def check_ollama_available(url: str = "http://localhost:11434/api/tags") -> bool:
    """Check if local Ollama daemon is running and reachable."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def evaluate_pair(
    summary_text: str,
    full_text: str,
    model: str = DEFAULT_MODEL,
    ollama_url: str = OLLAMA_URL,
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
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0},
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        ollama_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_response = data.get("response", "").strip()

        # Extract JSON block
        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            decision = str(parsed.get("decision", "uncertain")).lower()
            if decision not in ("match", "no_match", "uncertain"):
                decision = "uncertain"
            confidence = float(parsed.get("confidence", 0.5))
            reason = str(parsed.get("reason", "LLM evaluation"))
            return LLMVerdict(decision=decision, confidence=confidence, reason=reason)
    except Exception as e:
        return LLMVerdict(decision="uncertain", confidence=0.0, reason=f"Ollama unavailable: {e}")

    return LLMVerdict(decision="uncertain", confidence=0.0, reason="Inconclusive LLM response")


def judge_tiebreak(
    summary_text: str,
    candidate_a_text: str,
    candidate_b_text: str,
    model: str = DEFAULT_MODEL,
    ollama_url: str = OLLAMA_URL,
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
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0},
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        ollama_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_response = data.get("response", "").strip()
        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            choice = str(parsed.get("choice", "UNCERTAIN")).upper()
            if choice not in ("A", "B", "NONE", "UNCERTAIN"):
                choice = "UNCERTAIN"
            confidence = float(parsed.get("confidence", 0.5))
            reason = str(parsed.get("reason", "Tiebreaker evaluation"))
            return choice, confidence, reason
    except Exception as e:
        return "UNCERTAIN", 0.0, f"Ollama unavailable: {e}"

    return "UNCERTAIN", 0.0, "Inconclusive response"

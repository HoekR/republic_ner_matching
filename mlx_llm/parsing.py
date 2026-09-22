"""Response parsing utilities for LLM output."""

from __future__ import annotations

import json
import re


def _first_json_object_span(text: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` for the first top-level ``{...}`` object.

    String-aware: braces inside JSON strings do not affect depth. Returns
    ``None`` if no complete object is found.
    """
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
            if depth < 0:
                return None
    return None


def extract_json(text: str) -> dict | None:
    """Extract the first JSON object from prose-wrapped or over-generated text.

    Prefer brace-depth scanning (string-aware) so trailing chat continuation
    after a complete object — e.g. ``}<|endoftext|>Human: ...`` — does not
    poison ``json.loads``. Falls back to a non-greedy regex only if depth
    scanning finds nothing.

    Never raises.

    Args:
        text: String possibly containing a JSON object.

    Returns:
        The parsed dict if a valid JSON object is found, None otherwise.
    """
    if not text or not isinstance(text, str):
        return None

    try:
        span = _first_json_object_span(text)
        if span is not None:
            start, end = span
            obj = json.loads(text[start:end])
            if isinstance(obj, dict):
                return obj

        # Fallback: non-greedy match (still may fail on nested objects).
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if not match:
            return None
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def parses_affirmative(text: str) -> bool | None:
    """Check if text starts with a YES or NO response.

    Strips leading/trailing whitespace and converts to uppercase.
    Returns True if the text starts with "YES", False if it starts with "NO",
    and None if it starts with neither (ambiguous or empty response).

    Never raises.

    Args:
        text: String containing a potential YES/NO response.

    Returns:
        True for YES, False for NO, None for ambiguous/empty. Never raises.
    """
    normalized = text.strip().upper()
    if normalized.startswith("YES"):
        return True
    if normalized.startswith("NO"):
        return False
    return None

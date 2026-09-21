"""Response parsing utilities for LLM output."""

from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | None:
    """Extract the first JSON object from prose-wrapped text.

    Searches for the first `{...}` block in text via regex (greedy match),
    then attempts to parse it as JSON. Returns None if no match is found
    or if json.loads fails (including json.JSONDecodeError).

    Never raises.

    Args:
        text: String possibly containing a JSON object.

    Returns:
        The parsed dict if a valid JSON object is found, None otherwise.
    """
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        return json.loads(match.group(0))
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

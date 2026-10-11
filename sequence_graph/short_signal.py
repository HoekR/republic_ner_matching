"""Short / no-decision enriched classifier + opening strength — no legacy path I/O.

Phrase lists match the retired ``align_short_resolutions`` formulas; kept here so
review and DP₂ scorers do not import ``align_resolutions`` (which resolves local
``data/`` files at import time and breaks notebook / ``data_io`` workflows).
"""

from __future__ import annotations

import re

NO_DECISION_RE = re.compile(
    r"\b(geen resolutie|geen besluit|vereist geen|geen beslissing)\b", re.IGNORECASE
)
SHORT_TEXT_CHAR_LIMIT = 100

OPEN_WINDOW = 60
CLOSE_WINDOW = 250

_OPENING_RE = re.compile(
    r"(ontfangen\s+een(ige)?\s+(missive|missiue|brief|requeste)"
    r"|is\s+gelesen\s+de\s+req(uest)?e"
    r"|houdende\s+advertentie"
    r"|opt\s+versou?ck)",
    re.IGNORECASE,
)
_CLOSING_RE = re.compile(
    r"(e?geen\s+resolutie\s+(is\s+gevallen|is\s+genomen|vereisende|vereysende)"
    r"|vereist\s+geen\s+resolutie"
    r"|sonder\s+resolutie"
    r"|waerop\s+e?geen\s+resolutie)",
    re.IGNORECASE,
)


def classify_enriched(resolution: dict) -> str | None:
    """Return a match reason if the enriched resolution looks short / no-decision."""
    text = resolution.get("text") or ""
    if NO_DECISION_RE.search(text):
        return "no_decision_marker"
    if 0 < len(text) < SHORT_TEXT_CHAR_LIMIT:
        return "short_text"
    return None


def opening_strength(text: str) -> float:
    """HTR score: 1.0 open+close receipt, 0.5 open-only, else 0.0."""
    body = text or ""
    open_m = _OPENING_RE.search(body[:OPEN_WINDOW]) or _OPENING_RE.search(body[:400])
    if open_m is None:
        return 0.0
    close_window = body[open_m.end() : open_m.end() + CLOSE_WINDOW]
    if _CLOSING_RE.search(close_window):
        return 1.0
    return 0.5

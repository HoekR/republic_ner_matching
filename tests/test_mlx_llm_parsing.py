"""Tests for mlx_llm.parsing — especially trailing-junk recovery."""

from __future__ import annotations

import json

from mlx_llm.parsing import extract_json, parses_affirmative


def test_extract_json_plain_object():
    assert extract_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_extract_json_prose_wrapped():
    text = 'Here is the result:\n{"kind": "decision", "ok": true}\nThanks.'
    assert extract_json(text) == {"kind": "decision", "ok": True}


def test_extract_json_trailing_endoftext_junk():
    """Model often completes JSON then continues past <|endoftext|>."""
    payload = {
        "kind": "receipt",
        "actor": "Pr. Martenssen",
        "subject": "missive",
        "action_or_decision": "received",
        "is_receipt_or_no_decision": True,
        "is_session_opening": False,
        "is_continuation": False,
        "evidence_quote": 'Noch ontfangen een missive van Pr. Martenssen.',
        "uncertainty": [],
    }
    raw = (
        json.dumps(payload, indent=2)
        + "<|endoftext|>Human: What is the significance of the "
        + '"duisent realen" {please ignore this brace}?'
    )
    assert extract_json(raw) == payload


def test_extract_json_braces_inside_string():
    raw = '{"evidence_quote": "see {folio} 12", "kind": "other"}'
    assert extract_json(raw) == {
        "evidence_quote": "see {folio} 12",
        "kind": "other",
    }


def test_extract_json_empty_or_invalid():
    assert extract_json("") is None
    assert extract_json("no braces here") is None
    assert extract_json("{incomplete") is None
    assert extract_json(None) is None  # type: ignore[arg-type]


def test_parses_affirmative():
    assert parses_affirmative("YES, that matches") is True
    assert parses_affirmative("no way") is False
    assert parses_affirmative("maybe") is None

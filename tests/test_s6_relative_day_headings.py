"""Relative day tokens (lesten / naestlesten) in the duplicate-session heading channel."""

from __future__ import annotations

import pandas as pd

from scripts.s6_duplicate_session_date_headings import (
    date_phrases,
    find_headings,
    matched_year,
    resolve_day_token,
)


def test_resolve_day_token_maps_lesten_to_month_end():
    sept = pd.Period("1626-09-30", freq="D")
    assert resolve_day_token(0, sept) == 30
    assert resolve_day_token(-1, sept) == 29
    assert resolve_day_token(28, sept) == 28
    assert resolve_day_token(None, sept) is None


def test_date_phrases_include_lesten_only_on_month_end():
    end = date_phrases(pd.Period("1626-09-30", freq="D"))
    mid = date_phrases(pd.Period("1626-09-28", freq="D"))
    assert any("lesten" in p for p in end)
    assert not any("lesten" in p for p in mid)


def test_matched_year_reads_trailing_year():
    assert matched_year("den lesten Septembris 1626") == 1626
    assert matched_year("den lesten May") is None


def test_lesten_heading_verifies_with_year_and_weekday():
    paragraphs = [
        {"axis_id": "p0", "text": "opening business without a date heading."},
        {
            "axis_id": "p1",
            "text": "Presentibus Dis Mercurij den lesten Septembris 1626. Resolutien.",
        },
    ]
    hits = find_headings(paragraphs, "1626-09-30")
    assert any(h["verified"] for h in hits)
    verified = next(h for h in hits if h["verified"])
    assert verified["paragraph_position"] == 1
    assert verified["parsed_day"] == 30


def test_lesten_without_year_does_not_verify():
    """Prose like 'missive den lesten May ontfangen' is not a session heading."""
    paragraphs = [
        {
            "axis_id": "p0",
            "text": "opte pointen inde missive den lesten May ontfangen vande heeren",
        },
    ]
    hits = find_headings(paragraphs, "1627-05-31")
    assert hits  # fuzzy may still locate
    assert not any(h["verified"] for h in hits)

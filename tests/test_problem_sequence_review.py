"""Unit tests for problem-sequence review helpers — no full corpus deck build."""

from __future__ import annotations

from sequence_graph.problem_sequence_review import (
    card_html,
    dated_as_review_claims_from_notes,
    record_note,
)


def test_card_html_includes_stretch_counts():
    card = {
        "card_kind": "problem_sequence",
        "inventory": "3185",
        "calendar_lo": "1626-03-22",
        "calendar_hi": "1626-03-27",
        "sess_lo": 55,
        "sess_hi": 57,
        "n_htr_sessions_inclusive": 3,
        "n_enriched": 58,
        "n_aligned": 30,
        "n_unaligned": 28,
        "n_short_unaligned": 4,
        "n_opening_hits": 15,
        "n_days_no_production_pin": 2,
        "prompt": "look at the stretch",
        "timeline_days": [
            {"date": "1626-03-22", "no_production_pin": False},
            {"date": "1626-03-23", "no_production_pin": True},
        ],
        "session_ids": ["session-3185-num-55", "session-3185-num-56"],
        "short_crumbs": [
            {"volgnr": "1626-03-23_1", "reason": "short_text", "snippet": "geen resolutie"}
        ],
        "opening_crumbs": [
            {
                "flat_id": "session-3185-num-55-resolution-2",
                "strength": 1.0,
                "snippet": "Ontfangen een Missive",
            }
        ],
        "scan_links": [],
    }
    html = card_html(card)
    assert "1626-03-22" in html
    assert "unaligned" in html.lower() or "28" in html
    assert "1626-03-23_1" in html
    assert "Ontfangen een Missive" in html
    assert "03-23*" in html  # no-pin day marked


def test_record_note_sets_flag_and_span():
    notes: dict = {}
    card = {
        "review_id": "stretch:3185:1626-03-22:1626-03-27:55:57",
        "card_kind": "problem_sequence",
        "inventory": "3185",
        "calendar_lo": "1626-03-22",
        "calendar_hi": "1626-03-27",
        "anchor_lo_session": "session-3185-num-55",
        "anchor_hi_session": "session-3185-num-57",
        "n_unaligned": 28,
        "n_opening_hits": 15,
    }
    record_note(notes, card, "walls feel wrong at num-56", flag="walls_feel_wrong")
    row = notes[card["review_id"]]
    assert row["flag"] == "walls_feel_wrong"
    assert "num-56" in row["note"]
    assert row["calendar_lo"] == "1626-03-22"


def test_dated_as_review_claims_from_contains_date_notes():
    url = (
        "https://images.diginfra.net/iiif/NL-HaNA_1.01.02/3185/"
        "NL-HaNA_1.01.02_3185_0340.jpg/full/full/0/default.jpg"
    )
    notes = {
        "stretch:3185:1626-08-22:1626-09-06:143:144": {
            "review_id": "stretch:3185:1626-08-22:1626-09-06:143:144",
            "flag": "seen",
            "note": f"{url} contains date 1626-08-22",
            "decided_at": "2026-10-11T08:00:00+00:00",
        },
        "stretch:other": {
            "review_id": "stretch:other",
            "flag": "seen",
            "note": "diagnosis: UI lid only — not a date claim",
            "decided_at": "2026-10-11T08:01:00+00:00",
        },
    }
    claims = dated_as_review_claims_from_notes(notes)
    assert len(claims) == 1
    c = claims[0]
    assert c["claim_kind"] == "dated_as_review"
    assert c["edge"] == "DATED_AS:review"
    assert c["inventory"] == "3185"
    assert c["scan_num"] == 340
    assert c["date"] == "1626-08-22"
    assert c["evidence_url"] == url
    assert c["review_id"].endswith("143:144")

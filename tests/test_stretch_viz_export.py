"""Unit tests for stretch viz export helpers — no full graph required for windowing."""

from __future__ import annotations

from sequence_graph.stretch_viz_export import window_from_notes


def test_window_from_notes_unions_annotated_spans():
    notes = {
        "a": {
            "inventory": "3185",
            "calendar_lo": "1626-08-27",
            "calendar_hi": "1626-09-21",
            "anchor_lo_session": "session-3185-num-147",
            "anchor_hi_session": "session-3185-num-148",
        },
        "b": {
            "inventory": "3185",
            "calendar_lo": "1626-08-21",
            "calendar_hi": "1626-09-03",
            "anchor_lo_session": "session-3185-num-142",
            "anchor_hi_session": "session-3185-num-143",
        },
    }
    w = window_from_notes(notes)
    assert w["inventory"] == "3185"
    assert w["calendar_lo"] == "1626-08-21"
    assert w["calendar_hi"] == "1626-09-21"
    assert w["sess_lo"] == 142
    assert w["sess_hi"] == 148

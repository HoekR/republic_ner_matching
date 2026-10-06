"""Tests for `running_axis.serialize` -- the ribbon must not hide what the state holds.

The renderer reads serialised segments, never live model objects, so a picture cannot show
something the serialised payload lacks. These tests pin the two properties that make the
ribbon honest: it is gapless (an uncovered stretch is its own segment, not a closed hole),
and addressability decides the fill, so the recoverable class stays visible even on a session
that is also shared.
"""

from __future__ import annotations

import json

from running_axis.axis import DateState, RunningAxis, SessionSpan
from running_axis.serialize import (
    ADDRESSABILITY_COLOURS,
    FILL_PRIORITY,
    SHARED_STROKE,
    render_html,
    render_svg,
    ribbon_segments,
    to_json,
)


def axis_with(sessions, dates):
    return RunningAxis({}, sessions, dates)


def view_all(axis):
    """A view over exactly the model's coverage -- a wider window is refused, correctly."""
    window = axis.coverage
    return axis.view(window.start, window.end)


def session(num, begin, end, label=(), resolved=()):
    return SessionSpan(
        session_id=f"session-3187-num-{num}",
        inventory="3187",
        session_num=num,
        char_begin=begin,
        char_end=end,
        paragraph_count=1,
        label_dates=tuple(label),
        resolved_dates=tuple(resolved),
    )


def date(d, status="resolved_auto", resolved=None, labelled=False, k_e=3):
    return DateState(d, k_e, status, "3187", resolved, labelled)


def simple():
    """Two sessions with a 50-char hole between them."""
    sessions = {
        "session-3187-num-1": session(1, 0, 100, label=("1628-10-01",), resolved=("1628-10-01",)),
        "session-3187-num-2": session(2, 150, 250, label=("1628-10-01",), resolved=("1628-10-03",)),
    }
    dates = {
        "1628-10-01": date("1628-10-01", resolved="session-3187-num-1", labelled=True),
        "1628-10-03": date("1628-10-03", status="cross_day_shift", resolved="session-3187-num-2"),
    }
    return axis_with(sessions, dates)


def test_an_uncovered_stretch_becomes_its_own_segment():
    segments = ribbon_segments(view_all(simple()))
    kinds = [s.kind for s in segments]
    assert "unclaimed" in kinds
    hole = next(s for s in segments if s.kind == "unclaimed")
    assert (hole.char_begin, hole.char_end) == (100, 150)


def test_segments_tile_the_covered_range_without_gaps():
    segments = sorted(
        ribbon_segments(view_all(simple())),
        key=lambda s: s.char_begin,
    )
    for left, right in zip(segments, segments[1:]):
        assert left.char_end == right.char_begin, f"hole between {left} and {right}"


def test_addressability_decides_the_fill_not_sharing():
    """A shared session that also carries a discarded date must still read as discarded:
    colouring sharing instead erased two of October 1628's three recoverable sessions."""
    sessions = {
        "session-3187-num-1": session(
            1, 0, 100, label=("1628-10-12",), resolved=("1628-10-12", "1628-10-14")
        )
    }
    dates = {
        "1628-10-12": date("1628-10-12", resolved="session-3187-num-1", labelled=True),
        "1628-10-14": date("1628-10-14", status="cross_day_shift", resolved="session-3187-num-1"),
    }
    segment = ribbon_segments(view_all(axis_with(sessions, dates)))[0]
    assert segment.kind == "dropped_by_label_grouping"
    assert segment.shared is True


def test_fill_priority_puts_the_recoverable_class_first():
    assert FILL_PRIORITY[0] == "dropped_by_label_grouping"
    assert FILL_PRIORITY.index("no_session") < FILL_PRIORITY.index("labelled")


def test_the_label_names_every_claimant_and_its_class():
    segment = ribbon_segments(view_all(simple()))[0]
    assert "session-3187-num-1" in segment.label
    assert "chars" in segment.label
    assert "axis label" in segment.label


def test_payload_is_plain_json():
    segments = ribbon_segments(view_all(simple()))
    payload = json.loads(to_json(segments, window="1628-10-01..1628-10-31"))
    assert payload["window"] == "1628-10-01..1628-10-31"
    assert set(payload["segments"][0]) == {
        "inventory", "char_begin", "char_end", "char_length",
        "kind", "session_id", "dates", "label", "shared",
    }


def test_svg_is_self_contained_and_one_rect_per_segment():
    segments = ribbon_segments(view_all(simple()))
    svg = render_svg(segments, title="test")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<rect") == len([s for s in segments if s.char_length > 0])
    assert "<title>" in svg, "blocks must carry a hover label"


def test_shared_sessions_get_the_marked_border():
    sessions = {
        "session-3187-num-1": session(1, 0, 100, resolved=("1628-10-01", "1628-10-02"))
    }
    dates = {
        "1628-10-01": date("1628-10-01", resolved="session-3187-num-1", labelled=True),
        "1628-10-02": date("1628-10-02", resolved="session-3187-num-1", labelled=True),
    }
    svg = render_svg(ribbon_segments(view_all(axis_with(sessions, dates))))
    assert SHARED_STROKE in svg


def test_empty_window_renders_a_message_not_a_blank_svg():
    assert "no segments" in render_svg([])


def test_render_html_includes_a_legend_for_every_colour():
    html = render_html(view_all(simple()))
    for name in ADDRESSABILITY_COLOURS:
        assert name in html
    assert "shared (border)" in html


def test_zero_length_segments_are_not_drawn():
    segments = ribbon_segments(view_all(simple()))
    svg = render_svg(segments + [type(segments[0])("3187", 500, 500, "unclaimed")])
    assert svg.count("<rect") == len([s for s in segments if s.char_length > 0])

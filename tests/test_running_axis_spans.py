"""Regression tests for `running_axis.spans`, one per defect in the borrowed original.

The numbering matches the defect list in `running_axis/spans.py`'s module docstring, which
cites REPUBLIC's `republic_attendancelist_models.MatchedText`. The gapless-partition tests
(1-3) are the ones that matter most: the module exists to make an unexplained stretch an
object rather than an absence, so a representation that drops a hole is worthless.
"""

from __future__ import annotations

import pytest

from running_axis.spans import UNMARKED, OverlapError, Span, SpanLayer


def tiles_exactly(layer: SpanLayer) -> bool:
    """The partition covers [0, length) once: contiguous, ordered, nothing missing."""
    fragments = layer.fragments()
    if not fragments:
        return layer.length == 0
    if fragments[0].begin != 0 or fragments[-1].end != layer.length:
        return False
    return all(
        left.end == right.begin for left, right in zip(fragments, fragments[1:])
    )


def test_empty_layer_is_one_unmarked_fragment():
    layer = SpanLayer("session", 100)
    assert [(f.begin, f.end, f.type) for f in layer.fragments()] == [(0, 100, UNMARKED)]
    assert layer.unmarked_length() == 100


def test_defect_1_trailing_gap_runs_to_length():
    """The original sliced txt[end:begin] with begin <= end -- a reversed, empty slice."""
    layer = SpanLayer("session", 100)
    layer.add(10, 40, "session")
    tail = layer.fragments()[-1]
    assert (tail.begin, tail.end, tail.type) == (40, 100, UNMARKED)
    assert tail.length == 60
    assert tiles_exactly(layer)


def test_defect_2_one_character_gap_is_not_dropped():
    """`if end < i.begin - 1` in the original discarded a 1-char hole outright."""
    layer = SpanLayer("session", 10)
    layer.add(0, 4, "session")
    layer.add(5, 10, "session")  # exactly one character free at offset 4
    gaps = [(f.begin, f.end) for f in layer.unmarked()]
    assert gaps == [(4, 5)]
    assert layer.unmarked_length() == 1
    assert tiles_exactly(layer)


def test_adjacent_spans_leave_no_gap():
    layer = SpanLayer("session", 10)
    layer.add(0, 5, "session")
    layer.add(5, 10, "session")
    assert layer.unmarked() == []
    assert tiles_exactly(layer)


def test_defect_3_unmarked_bounds_are_exact_not_off_by_one():
    """The original recorded 'begin': begin - 1 while its text covered [end, i.begin)."""
    layer = SpanLayer("session", 100)
    layer.add(30, 60, "session")
    head = layer.fragments()[0]
    assert (head.begin, head.end) == (0, 30)
    assert head.length == 30


def test_defect_4_overlapping_insert_happens_exactly_once():
    """The original appended the new span once per overlapping neighbour."""
    layer = SpanLayer("anchor", 100)
    for begin in (10, 20, 30):
        layer.add(begin, begin + 5, "anchor")
    assert len(layer) == 3
    layer.add(0, 100, "anchor", on_overlap="replace")
    assert len(layer) == 1
    assert tiles_exactly(layer)


def test_defect_5_containment_actually_fires():
    """`issubset(span)` against a 2-tuple meant containment never took effect."""
    layer = SpanLayer("session", 100)
    layer.add(40, 50, "session")
    layer.add(20, 80, "session", on_overlap="replace")
    assert [(s.begin, s.end) for s in layer] == [(20, 80)]


def test_overlap_raise_is_the_default_and_reports_conflicts():
    layer = SpanLayer("session", 100)
    layer.add(10, 40, "session")
    with pytest.raises(OverlapError) as excinfo:
        layer.add(30, 60, "session")
    assert [(s.begin, s.end) for s in excinfo.value.conflicts] == [(10, 40)]
    assert len(layer) == 1, "a refused insert must not mutate the layer"


def test_overlap_keep_returns_the_incumbent():
    layer = SpanLayer("session", 100)
    first = layer.add(10, 40, "session")
    assert layer.add(30, 60, "session", on_overlap="keep") == first
    assert len(layer) == 1


def test_defect_6_span_ids_round_trip():
    """TypedFragment hardcoded idnr = 0, so get_span could only ever retrieve id 0."""
    layer = SpanLayer("session", 100)
    span_id = layer.add(10, 40, "session", {"session_num": 114})
    assert layer.get(span_id).payload["session_num"] == 114
    with pytest.raises(KeyError):
        layer.get("session:999-1000")


def test_defect_7_ids_are_stable_across_loads_not_process_counters():
    """`nw_id = itertools.count()` was class-level, so ids shifted between runs."""
    first = SpanLayer("session", 100)
    first.add(10, 40, "session")
    second = SpanLayer.from_dict(first.to_dict())
    assert [s.span_id for s in first] == [s.span_id for s in second]
    third = SpanLayer("session", 100)
    third.add(10, 40, "session")
    assert [s.span_id for s in third] == [s.span_id for s in first]


def test_defect_9_ordering_is_explicit():
    layer = SpanLayer("session", 100)
    layer.add(50, 60, "session")
    layer.add(10, 20, "session")
    layer.add(30, 40, "session")
    assert [s.begin for s in layer] == [10, 30, 50]
    assert tiles_exactly(layer)


def test_zero_length_anchor_does_not_evict_its_bounding_span():
    layer = SpanLayer("anchor", 100)
    layer.add(10, 40, "resolution_start")
    layer.add(10, 10, "anchor")  # a point sitting exactly on the boundary
    assert len(layer) == 2


def test_point_spans_keep_the_partition_contiguous():
    layer = SpanLayer("anchor", 50)
    layer.add(25, 25, "anchor")
    assert tiles_exactly(layer)
    assert layer.unmarked_length() == 50


def test_span_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        Span(begin=10, end=5, type="session")


def test_add_rejects_a_span_past_the_end_of_the_layer():
    layer = SpanLayer("session", 50)
    with pytest.raises(ValueError):
        layer.add(40, 60, "session")


def test_types_are_counted_from_state():
    layer = SpanLayer("mixed", 100)
    layer.add(0, 10, "session")
    layer.add(10, 20, "session")
    layer.add(20, 30, "date_claim")
    assert layer.types() == {"session": 2, "date_claim": 1}


def test_clip_narrows_and_flags_straddling_spans():
    layer = SpanLayer("session", 100)
    layer.add(0, 30, "session", {"session_num": 1})
    layer.add(30, 70, "session", {"session_num": 2})
    layer.add(70, 100, "session", {"session_num": 3})
    view = layer.clipped_to(20, 80)
    assert view.length == 60
    assert tiles_exactly(view)
    bounds = [(s.begin, s.end, s.payload.get("clipped", False)) for s in view]
    assert bounds == [(0, 10, True), (10, 50, False), (50, 60, True)]
    straddlers = [s for s in view if s.payload.get("clipped")]
    assert straddlers[0].payload["original_begin"] == 0
    assert straddlers[1].payload["original_end"] == 100


def test_clip_drops_spans_entirely_outside_the_window():
    layer = SpanLayer("session", 100)
    layer.add(0, 10, "session")
    layer.add(50, 60, "session")
    view = layer.clipped_to(40, 70)
    assert [(s.begin, s.end) for s in view] == [(10, 20)]
    assert tiles_exactly(view)


def test_round_trip_preserves_spans_and_partition():
    layer = SpanLayer("session", 100)
    layer.add(10, 40, "session", {"session_num": 7})
    layer.add(60, 90, "date_claim", {"date": "1628-10-01"})
    restored = SpanLayer.from_dict(layer.to_dict())
    assert [s.to_dict() for s in restored] == [s.to_dict() for s in layer]
    assert [f.to_dict() for f in restored.fragments()] == [
        f.to_dict() for f in layer.fragments()
    ]

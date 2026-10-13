"""Unit tests for overflow cut marker round-trip — no Flask server."""

from __future__ import annotations

from overflow_cut_labeller.store import (
    apply_cuts_as_markers,
    count_cuts,
    offsets_from_marked_text,
    strip_markers,
)


def test_cut_marker_roundtrip() -> None:
    text = "ABCDEFGHIJKLMNOP"
    cuts = [4, 10]
    marked = apply_cuts_as_markers(text, cuts)
    assert count_cuts(marked) == 2
    assert "|||CUT|||" in marked
    assert offsets_from_marked_text(marked) == cuts
    assert strip_markers(marked) == text


def test_empty_and_dedupe() -> None:
    assert apply_cuts_as_markers("", [1]) == ""
    assert offsets_from_marked_text("no markers here") == []
    text = "abcdefghij"
    # Duplicates collapse; out-of-range dropped. Single valid cut → one marker.
    marked = apply_cuts_as_markers(text, [3, 3])
    assert offsets_from_marked_text(marked) == [3]
    assert strip_markers(marked) == text

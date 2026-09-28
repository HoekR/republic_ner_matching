"""Tests for lumped_paragraph_labeller.store."""

from lumped_paragraph_labeller.store import (
    count_cuts,
    default_annotation,
    is_labelled_row,
    merge_row,
    update_annotation,
)


def test_count_cuts():
    assert count_cuts("a|||CUT|||b|||CUT|||c") == 2


def test_update_annotation_marks_labelled():
    candidates = [
        {
            "example_id": "d#p0",
            "text": "hello world",
            "expected_cuts": 1,
            "paragraph_notes": "",
        }
    ]
    state = {"annotations": {}}
    updated = update_annotation(
        state,
        "d#p0",
        {"text": "hello|||CUT|||world", "paragraph_notes": "ok", "labelled": True},
        candidates=candidates,
    )
    row = merge_row(candidates[0], updated["annotations"]["d#p0"])
    assert is_labelled_row(row)
    assert count_cuts(row["text"]) == 1
    assert row["paragraph_notes"] == "ok"


def test_default_annotation():
    row = default_annotation({"text": "abc", "paragraph_notes": ""})
    assert row["text"] == "abc"
    assert row["labelled"] is False

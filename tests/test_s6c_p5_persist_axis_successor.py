"""Track P P5 — cut-fill / extent gates + corpus successor materialisation."""

from __future__ import annotations

from scripts.s6c_reparagraph import (
    AXIS_VERSION_P5,
    apply_cuts_to_corpus_rows,
    day_passes_gate,
    gate_host_cuts,
    identity_axis_row,
)


def test_gate_host_cuts_enough_requires_full_fill():
    assert gate_host_cuts([10, 20], 2, mode="enough_cuts") == [10, 20]
    assert gate_host_cuts([10], 2, mode="enough_cuts") == []
    assert gate_host_cuts([], 1, mode="enough_cuts") == []


def test_gate_host_cuts_any_keeps_partial():
    assert gate_host_cuts([10], 2, mode="any") == [10]
    assert gate_host_cuts([30, 10], 3, mode="any") == [10, 30]


def test_day_gate_beats_and_no_extent():
    assert day_passes_gate(
        separated_predicted=10,
        separated_plain=8,
        extent_gt_max_predicted=1,
        extent_gt_max_plain=1,
        mode="beats_plain_and_no_extent_regression",
    )
    assert not day_passes_gate(
        separated_predicted=10,
        separated_plain=8,
        extent_gt_max_predicted=3,
        extent_gt_max_plain=1,
        mode="beats_plain_and_no_extent_regression",
    )
    assert not day_passes_gate(
        separated_predicted=7,
        separated_plain=8,
        extent_gt_max_predicted=0,
        extent_gt_max_plain=0,
        mode="beats_plain_and_no_extent_regression",
    )


def test_day_gate_none_always_passes():
    assert day_passes_gate(
        separated_predicted=0,
        separated_plain=5,
        extent_gt_max_predicted=9,
        extent_gt_max_plain=0,
        mode="none",
    )


def test_apply_cuts_to_corpus_splits_only_named_hosts():
    parent = [
        {
            "text": "abcdefghij",
            "para_index": 0,
            "axis_id": "host#p0",
            "flat_id": "session-3185-num-1-resolution-1",
            "date": "1629-01-01",
        },
        {
            "text": "zzzz",
            "para_index": 1,
            "axis_id": "other#p0",
            "flat_id": "session-3185-num-1-resolution-2",
            "date": "1629-01-01",
        },
    ]
    built = apply_cuts_to_corpus_rows(
        parent,
        {"host#p0": [3, 7]},
        version=AXIS_VERSION_P5,
        parent_dataset="paragraph_axis_1626_1630",
    )
    texts = [row["text"] for row in built["axis"]]
    assert texts == ["abc", "defg", "hij", "zzzz"]
    assert built["n_hosts_split"] == 1
    assert built["n_cuts_applied"] == 2
    # para_index within flat_id; second flat resets to 0
    assert [row["para_index"] for row in built["axis"]] == [0, 1, 2, 0]
    assert built["axis"][1]["parent_para_index"] == 0
    assert built["axis"][1]["parent_char_start"] == 3
    assert built["axis"][1]["axis_version"] == AXIS_VERSION_P5
    assert built["axis"][3]["parent_para_index"] == 1
    assert built["axis"][3]["parent_char_start"] == 0
    assert built["axis"][3]["parent_char_end"] == 4
    # Parent untouched
    assert parent[0]["text"] == "abcdefghij"
    assert "parent_para_index" not in parent[0]


def test_identity_axis_row_sets_provenance():
    row = identity_axis_row(
        {"text": "ab", "para_index": 4, "axis_id": "x"},
        version="v",
        parent_dataset="parent",
        parent_para_index=9,
    )
    assert row["parent_para_index"] == 9
    assert row["parent_char_start"] == 0
    assert row["parent_char_end"] == 2
    assert row["axis_version"] == "v"
    assert row["parent_dataset"] == "parent"

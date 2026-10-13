"""P5 merge helpers — date parse + recover cuts from successor pieces."""

from __future__ import annotations

from scripts.s6c_p5_persist_axis_successor import (
    cuts_from_successor_axis,
    parse_date_list,
    _merge_cut_map,
)


def test_parse_date_list() -> None:
    assert parse_date_list("1629-02-09, 1628-01-29;1629-02-09") == [
        "1628-01-29",
        "1629-02-09",
    ]
    assert parse_date_list("") == []


def test_cuts_from_successor_axis() -> None:
    rows = [
        {"axis_id": "sess#p0"},  # identity
        {"axis_id": "sess#p1#repara:0-10"},
        {"axis_id": "sess#p1#repara:10-40"},
        {"axis_id": "sess#p1#repara:40-50"},
    ]
    assert cuts_from_successor_axis(rows) == {"sess#p1": [10, 40]}


def test_merge_cut_map_clears_and_adds() -> None:
    base = {"a": [1, 2], "b": [5]}
    merged = _merge_cut_map(base, clear_axis_ids={"a"}, add={"a": [9], "c": [3]})
    assert merged == {"b": [5], "a": [9], "c": [3]}

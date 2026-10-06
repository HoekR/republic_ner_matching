"""Tests for `running_axis.stream` -- the inventory coordinate and its lazy text.

A wrong sort key here silently corrupts every downstream offset, so ordering and the
contiguity of `char_start` are tested directly rather than inferred from totals. The corpus
integration test is marked slow: it reads the real 18 MB axis and is the regression guard on
the measured figures (21,519 paragraphs / 12,929,911 characters).
"""

from __future__ import annotations

import json

import pytest

from running_axis.stream import (
    FlatIdError,
    InventoryStream,
    build_streams,
    index_axis,
    parse_flat_id,
)


def write_axis(tmp_path, records):
    path = tmp_path / "axis.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def record(inventory, session, resolution, para, text, date="1628-10-01"):
    flat_id = f"session-{inventory}-num-{session}-resolution-{resolution}"
    return {
        "date": date,
        "flat_id": flat_id,
        "para_index": para,
        "axis_id": f"{flat_id}#p{para}",
        "text": text,
    }


# --- flat_id parsing -----------------------------------------------------------------


def test_parse_flat_id():
    assert parse_flat_id("session-3187-num-114-resolution-1") == ("3187", 114, 1)


@pytest.mark.parametrize(
    "bad",
    [
        "session-3187-num-114",
        "session-3187-num-114-resolution-1#p0",
        "session-3187-resolution-1",
        "",
    ],
)
def test_parse_flat_id_rejects_malformed(bad):
    with pytest.raises(FlatIdError):
        parse_flat_id(bad)


# --- ordering and the coordinate -----------------------------------------------------


def test_order_is_session_then_resolution_then_para_not_file_order(tmp_path):
    """Deliberately shuffled on disk; archive order must be reconstructed."""
    path = write_axis(
        tmp_path,
        [
            record("3187", 2, 1, 1, "bb"),
            record("3187", 10, 1, 0, "dddd"),
            record("3187", 2, 1, 0, "aa"),
            record("3187", 2, 2, 0, "cc"),
        ],
    )
    stream = build_streams(path)["3187"]
    assert [(r.session_num, r.resolution_num, r.para_index) for r in stream] == [
        (2, 1, 0),
        (2, 1, 1),
        (2, 2, 0),
        (10, 1, 0),
    ]
    assert [r.stream_index for r in stream] == [0, 1, 2, 3]


def test_session_numbers_sort_numerically_not_lexically(tmp_path):
    path = write_axis(
        tmp_path,
        [record("3187", num, 1, 0, "x") for num in (9, 100, 20, 3)],
    )
    stream = build_streams(path)["3187"]
    assert [r.session_num for r in stream] == [3, 9, 20, 100]


def test_char_starts_are_contiguous_and_gapless(tmp_path):
    path = write_axis(
        tmp_path,
        [
            record("3187", 1, 1, 0, "abc"),
            record("3187", 1, 1, 1, "de"),
            record("3187", 2, 1, 0, "fghi"),
        ],
    )
    stream = build_streams(path)["3187"]
    assert [(r.char_start, r.char_end) for r in stream] == [(0, 3), (3, 5), (5, 9)]
    assert stream.char_length == 9
    for left, right in zip(stream.refs, stream.refs[1:]):
        assert left.char_end == right.char_start


def test_char_length_is_the_sum_of_paragraph_lengths(tmp_path):
    texts = ["a", "bb", "ccc", "dddd"]
    path = write_axis(
        tmp_path,
        [record("3187", 1, i + 1, 0, text) for i, text in enumerate(texts)],
    )
    stream = build_streams(path)["3187"]
    assert stream.char_length == sum(len(t) for t in texts)


def test_inventories_are_kept_apart(tmp_path):
    path = write_axis(
        tmp_path,
        [record("3187", 1, 1, 0, "aaa"), record("3188", 1, 1, 0, "bbbb")],
    )
    streams = build_streams(path)
    assert set(streams) == {"3187", "3188"}
    assert streams["3187"].char_length == 3
    assert streams["3188"].char_length == 4
    # Each inventory's coordinate starts at zero; they are not one global stream.
    assert streams["3187"].refs[0].char_start == streams["3188"].refs[0].char_start == 0


# --- lookups -------------------------------------------------------------------------


def test_ref_at_finds_the_containing_paragraph(tmp_path):
    path = write_axis(
        tmp_path,
        [
            record("3187", 1, 1, 0, "abc"),
            record("3187", 1, 1, 1, "de"),
            record("3187", 2, 1, 0, "fghi"),
        ],
    )
    stream = build_streams(path)["3187"]
    assert stream.ref_at(0).para_index == 0
    assert stream.ref_at(2).char_start == 0
    assert stream.ref_at(3).char_start == 3
    assert stream.ref_at(8).session_num == 2


@pytest.mark.parametrize("position", [-1, 9, 100])
def test_ref_at_rejects_positions_outside_the_stream(tmp_path, position):
    path = write_axis(tmp_path, [record("3187", 1, 1, 0, "abcdefghi")])
    stream = build_streams(path)["3187"]
    with pytest.raises(IndexError):
        stream.ref_at(position)


def test_refs_overlapping_is_half_open(tmp_path):
    path = write_axis(
        tmp_path,
        [record("3187", 1, 1, 0, "abc"), record("3187", 1, 1, 1, "def")],
    )
    stream = build_streams(path)["3187"]
    assert len(stream.refs_overlapping(0, 3)) == 1
    assert len(stream.refs_overlapping(2, 4)) == 2
    assert stream.refs_overlapping(3, 3) == []


def test_sessions_span_their_paragraphs(tmp_path):
    path = write_axis(
        tmp_path,
        [
            record("3187", 1, 1, 0, "abc"),
            record("3187", 1, 2, 0, "de"),
            record("3187", 5, 1, 0, "fghi"),
        ],
    )
    stream = build_streams(path)["3187"]
    assert stream.sessions() == {
        "session-3187-num-1": (0, 5),
        "session-3187-num-5": (5, 9),
    }


def test_absent_session_numbers_are_reported_not_skipped(tmp_path):
    path = write_axis(
        tmp_path,
        [record("3187", num, 1, 0, "x") for num in (1, 2, 5, 6, 9)],
    )
    stream = build_streams(path)["3187"]
    assert stream.absent_session_numbers() == [3, 4, 7, 8]


def test_date_labels_are_attributes_and_may_repeat_or_be_absent(tmp_path):
    """The date is a label on a span, not the partition key -- so it can be missing."""
    path = write_axis(
        tmp_path,
        [
            record("3187", 1, 1, 0, "aa", date="1628-10-01"),
            record("3187", 2, 1, 0, "bb", date="1628-10-01"),
            {
                "date": None,
                "flat_id": "session-3187-num-3-resolution-1",
                "para_index": 0,
                "axis_id": "x#p0",
                "text": "cc",
            },
        ],
    )
    stream = build_streams(path)["3187"]
    assert stream.date_labels() == ["1628-10-01"]
    assert [r.date_label for r in stream] == ["1628-10-01", "1628-10-01", None]
    assert stream.char_length == 6, "an unlabelled paragraph still occupies the coordinate"


# --- lazy text -----------------------------------------------------------------------


def test_index_keeps_lengths_and_discards_text(tmp_path):
    path = write_axis(tmp_path, [record("3187", 1, 1, 0, "abcde")])
    rows = index_axis(path)
    assert rows[0]["char_len"] == 5
    assert "text" not in rows[0]


def test_text_is_fetched_on_demand_by_byte_offset(tmp_path):
    path = write_axis(
        tmp_path,
        [
            record("3187", 1, 1, 0, "first"),
            record("3187", 1, 1, 1, "second"),
        ],
    )
    stream = build_streams(path)["3187"]
    assert stream.text_of(stream.refs[0]) == "first"
    assert stream.text_of(stream.refs[1]) == "second"


def test_text_of_is_memoised(tmp_path):
    path = write_axis(tmp_path, [record("3187", 1, 1, 0, "abc")])
    stream = build_streams(path)["3187"]
    ref = stream.refs[0]
    assert stream.text_of(ref) == "abc"
    path.unlink()  # second read must not touch the file
    assert stream.text_of(ref) == "abc"


def test_text_spans_paragraph_boundaries(tmp_path):
    path = write_axis(
        tmp_path,
        [
            record("3187", 1, 1, 0, "abc"),
            record("3187", 1, 1, 1, "def"),
            record("3187", 2, 1, 0, "ghi"),
        ],
    )
    stream = build_streams(path)["3187"]
    assert stream.text() == "abcdefghi"
    assert stream.text(2, 7) == "cdefg"
    assert stream.text(3, 6) == "def"


def test_text_detects_an_axis_that_changed_under_the_index(tmp_path):
    """A stale index would otherwise return text at the wrong offsets, silently."""
    path = write_axis(tmp_path, [record("3187", 1, 1, 0, "abc")])
    stream = build_streams(path)["3187"]
    write_axis(tmp_path, [record("3187", 1, 1, 0, "abcdef")])
    with pytest.raises(RuntimeError, match="axis changed under the index"):
        stream.text_of(stream.refs[0])


def test_text_handles_non_ascii_offsets(tmp_path):
    """char offsets are characters, byte offsets are bytes; they must not be conflated."""
    path = write_axis(
        tmp_path,
        [record("3187", 1, 1, 0, "Vergaderinge"), record("3187", 1, 1, 1, "Oostvrieslant")],
    )
    stream = build_streams(path)["3187"]
    assert stream.refs[1].char_start == len("Vergaderinge")
    assert stream.text_of(stream.refs[1]) == "Oostvrieslant"


# --- the real corpus -----------------------------------------------------------------


def test_corpus_totals_are_unchanged():
    """Regression guard on the measured coordinate. Reads the real 18 MB axis (~1s)."""
    streams = build_streams()
    assert sum(len(s) for s in streams.values()) == 21_519
    assert sum(s.char_length for s in streams.values()) == 12_929_911
    assert {inv: len(s.absent_session_numbers()) for inv, s in streams.items()} == {
        "3185": 22,
        "3186": 27,
        "3187": 30,
        "3188": 24,
        "3189": 32,
        "4562": 1,
    }

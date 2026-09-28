"""Tests for lumped-paragraph annotation merge helpers."""

from scripts.merge_lumped_paragraph_annotations import parse_cut_offsets


def test_parse_cut_offsets_single():
    clean, offsets = parse_cut_offsets("aaaa|||CUT|||bbbb")
    assert clean == "aaaabbbb"
    assert offsets == [4]


def test_parse_cut_offsets_two():
    clean, offsets = parse_cut_offsets("aa|||CUT|||bb|||CUT|||cc")
    assert clean == "aabbcc"
    assert offsets == [2, 4]

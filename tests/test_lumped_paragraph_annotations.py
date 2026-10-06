"""Tests for lumped-paragraph annotation merge helpers."""

from scripts.merge_lumped_paragraph_annotations import parse_cut_offsets, parse_markers


def test_parse_cut_offsets_single():
    clean, offsets = parse_cut_offsets("aaaa|||CUT|||bbbb")
    assert clean == "aaaabbbb"
    assert offsets == [4]


def test_parse_cut_offsets_two():
    clean, offsets = parse_cut_offsets("aa|||CUT|||bb|||CUT|||cc")
    assert clean == "aabbcc"
    assert offsets == [2, 4]


def test_parse_markers_start_only():
    clean, cuts, starts = parse_markers("head|||START|||body")
    assert clean == "headbody"
    assert cuts == []
    assert starts == [4]


def test_parse_markers_both_share_one_clean_text():
    """A start marker must not shift the cut offsets that follow it."""
    clean, cuts, starts = parse_markers("aa|||START|||bb|||CUT|||cc")
    assert clean == "aabbcc"
    assert starts == [2]
    assert cuts == [4]


def test_parse_markers_start_after_cut():
    clean, cuts, starts = parse_markers("aa|||CUT|||bb|||START|||cc")
    assert clean == "aabbcc"
    assert cuts == [2]
    assert starts == [4]

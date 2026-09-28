from scripts.synthetic_boundary_common import (
    boundaries_from_segment_lengths,
    concat_segments,
    date_split_bucket,
    even_split_boundaries,
    length_ratio,
    passes_length_heterogeneity,
)


def test_boundaries_from_segment_lengths():
    assert boundaries_from_segment_lengths([100, 250, 50]) == [100, 350]


def test_concat_no_separator():
    assert concat_segments(["abc", "def"]) == "abcdef"


def test_length_ratio_and_heterogeneity():
    assert length_ratio([100, 200]) == 2.0
    assert passes_length_heterogeneity([100, 200], 1.5)
    assert not passes_length_heterogeneity([100, 120], 1.5)


def test_even_split_and_date_bucket():
    assert even_split_boundaries(100, 1) == [50]
    assert even_split_boundaries(300, 2) == [100, 200]
    assert date_split_bucket("1626-01-01") in {"train", "val", "test"}
    assert date_split_bucket("1626-01-01") == date_split_bucket("1626-01-01")


def test_strip_leading_opening_and_hard_merge():
    from scripts.synthetic_boundary_common import hard_merge_segment_texts, strip_leading_opening

    text = "Is goetgevonden dat men sal..."
    stripped, removed = strip_leading_opening(text, [(0, 16)], max_prefix=120)
    assert removed == 16
    assert stripped.startswith("dat men")

    texts = ["AAAA", "Is goetgevonden BBBB"]
    matches = [[], [(0, 16)]]
    new_texts, lengths, bounds, n_stripped = hard_merge_segment_texts(texts, matches)
    assert n_stripped == 1
    assert new_texts[1] == "BBBB"
    assert bounds == [4]
    assert sum(lengths) == len("".join(new_texts))

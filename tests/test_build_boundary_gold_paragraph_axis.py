import pandas as pd

from scripts.build_boundary_gold_paragraph_axis import match_annotation_to_paragraph, parse_paragraphs, selected_resolutions


def test_parse_paragraphs_keeps_all_nonempty_items():
    assert parse_paragraphs('["one", "", "two"]') == ["one", "two"]


def test_match_annotation_requires_a_unique_paragraph():
    assert match_annotation_to_paragraph("unique phrase", ["first", "a unique phrase here"]) == 1
    assert match_annotation_to_paragraph("shared", ["shared first", "shared second"]) is None


def test_selected_resolutions_full_uses_lexical_early_modern_date_range():
    frame = pd.DataFrame({"id": ["before", "inside", "after"], "date": ["1625-12-31", "1627-06-01", "1631-01-01"], "paragraph_texts": [[], [], []]})
    selected = selected_resolutions(frame, "full", {"days": []})
    assert selected["id"].tolist() == ["inside"]
from scripts.evaluate_openings_at_gold_cuts import fuzzy_matching_phrase, matching_phrase, text_after_cut


def test_text_after_cut_continues_to_next_paragraph_after_paragraph_end():
    axis = [{"text": "first"}, {"text": "Ontfangen een missive"}]
    assert text_after_cut(axis, 0, 5) == "Ontfangen een missive"


def test_matching_phrase_prefers_the_longest_prefix():
    assert matching_phrase("Ontfangen een missive van Amsterdam", ["ontfangen", "ontfangen een missive"]) == "ontfangen een missive"


def test_fuzzy_matching_phrase_handles_orthographic_variation():
    result = fuzzy_matching_phrase("Ontfangen een missiue van Amsterdam", ["ontfangen een missive"])
    assert result is not None
    assert result[0] == "ontfangen een missive"
    assert result[1] >= 0.85
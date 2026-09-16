from scripts.build_opening_phrase_candidates import leading_phrases


def test_leading_phrases_returns_two_to_five_word_prefixes():
    assert leading_phrases("Synde gehoort het rapport van de heeren") == [
        "synde gehoort",
        "synde gehoort het",
        "synde gehoort het rapport",
        "synde gehoort het rapport van",
    ]
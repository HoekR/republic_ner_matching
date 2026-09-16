from scripts.s4_corpus_paragraph_predictions import enriched_key


def test_enriched_key_normalizes_file_index_fallback():
    assert enriched_key({"volgnr": "163006ap.xml#11"}, "1630-04-06") == "1630-04-06_11"


def test_enriched_key_uses_date_index_when_volgnr_is_missing():
    assert enriched_key({"resolution_index": 3}, "1626-01-01") == "1626-01-01_3"
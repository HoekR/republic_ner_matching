from scripts.s4_corpus_paragraph_predictions import axis_for_date, enriched_key, session_of


def test_enriched_key_normalizes_file_index_fallback():
    assert enriched_key({"volgnr": "163006ap.xml#11"}, "1630-04-06") == "1630-04-06_11"


def test_enriched_key_uses_date_index_when_volgnr_is_missing():
    assert enriched_key({"resolution_index": 3}, "1626-01-01") == "1626-01-01_3"


def test_session_of_strips_the_resolution_suffix():
    assert session_of("session-3185-num-23-resolution-5") == "session-3185-num-23"


def test_axis_for_date_prefers_the_same_calendar_day():
    axis_by_date = {"1626-01-01": ["own paragraph"]}
    axis_by_session = {"session-3185-num-1": ["neighbor paragraph"]}
    session_by_date = {"1626-01-01": "session-3185-num-1"}
    assert axis_for_date("1626-01-01", axis_by_date, axis_by_session, session_by_date) == ["own paragraph"]


def test_axis_for_date_falls_back_to_the_concordance_resolved_session():
    # No same-day axis at all -- the case that used to abstain missing_htr outright.
    axis_by_date = {}
    axis_by_session = {"session-3185-num-1": ["neighbor paragraph"]}
    session_by_date = {"1626-01-02": "session-3185-num-1"}
    assert axis_for_date("1626-01-02", axis_by_date, axis_by_session, session_by_date) == ["neighbor paragraph"]


def test_axis_for_date_stays_empty_when_nothing_resolves_either_way():
    assert axis_for_date("1626-01-03", {}, {}, {}) == []
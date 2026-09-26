from scripts.s4_corpus_paragraph_predictions import axis_for_date, enriched_key, predict, session_of


def test_enriched_key_normalizes_file_index_fallback():
    assert enriched_key({"volgnr": "163006ap.xml#11"}, "1630-04-06") == "1630-04-06_11"


def test_enriched_key_uses_date_index_when_volgnr_is_missing():
    assert enriched_key({"resolution_index": 3}, "1626-01-01") == "1626-01-01_3"


def test_session_of_strips_the_resolution_suffix():
    assert session_of("session-3185-num-23-resolution-5") == "session-3185-num-23"


def test_axis_for_date_prefers_the_concordance_resolved_session_over_a_same_day_stub():
    # A non-empty same-day axis used to win unconditionally -- docs/DECISIONS.md 2026-09-22
    # found that lets a thin same-calendar stub beat a richer session concordance already
    # resolved to a neighboring date. The resolved session now wins when both exist.
    axis_by_date = {"1626-01-01": ["own paragraph"]}
    axis_by_session = {"session-3185-num-1": ["neighbor paragraph"]}
    session_by_date = {"1626-01-01": "session-3185-num-1"}
    assert axis_for_date("1626-01-01", axis_by_date, axis_by_session, session_by_date) == ["neighbor paragraph"]


def test_axis_for_date_falls_back_to_the_concordance_resolved_session():
    # No same-day axis at all -- the case that used to abstain missing_htr outright.
    axis_by_date = {}
    axis_by_session = {"session-3185-num-1": ["neighbor paragraph"]}
    session_by_date = {"1626-01-02": "session-3185-num-1"}
    assert axis_for_date("1626-01-02", axis_by_date, axis_by_session, session_by_date) == ["neighbor paragraph"]


def test_axis_for_date_falls_back_to_same_day_when_the_resolved_session_has_no_axis():
    # A resolved_auto entry exists but paragraph_axis_1626_1630 has no rows for that session
    # (a dataset gap) -- use the same-day stub rather than returning nothing.
    axis_by_date = {"1626-01-04": ["own paragraph"]}
    axis_by_session = {}
    session_by_date = {"1626-01-04": "session-3185-num-9"}
    assert axis_for_date("1626-01-04", axis_by_date, axis_by_session, session_by_date) == ["own paragraph"]


def test_axis_for_date_falls_back_to_same_day_when_no_session_is_resolved():
    axis_by_date = {"1626-01-05": ["own paragraph"]}
    assert axis_for_date("1626-01-05", axis_by_date, {}, {}) == ["own paragraph"]


def test_axis_for_date_stays_empty_when_nothing_resolves_either_way():
    assert axis_for_date("1626-01-03", {}, {}, {}) == []


def _minimal_axis(n: int) -> list[dict]:
    return [{"axis_id": f"p{i}", "flat_id": "session-1-num-1-resolution-1", "text": ""} for i in range(n)]


def test_predict_defaults_to_no_position_scores():
    axis = _minimal_axis(4)
    without_kwarg = predict("1626-01-01", ["e0", "e1", "e2"], axis, {}, {})
    with_none = predict("1626-01-01", ["e0", "e1", "e2"], axis, {}, {}, position_scores=None)
    assert without_kwarg["boundaries"] == with_none["boundaries"]


def test_predict_accepts_position_scores_without_changing_boundary_count():
    axis = _minimal_axis(4)
    baseline = predict("1626-01-01", ["e0", "e1", "e2"], axis, {}, {})
    boosted = predict("1626-01-01", ["e0", "e1", "e2"], axis, {}, {}, position_scores={2: 1.0})
    assert len(boosted["boundaries"]) == len(baseline["boundaries"]) == 2
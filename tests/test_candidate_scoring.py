from scripts.s4_candidate_scoring import (
    candidate_session_ids,
    is_nihil_actum,
    score_candidates,
    score_ledger_row,
    session_text,
    shared_entities,
    text_confirmed_names,
)


def test_ranks_candidate_sharing_most_distinctive_terms_first():
    enriched_text = "de Staten Generael resolveren over den Vrede van Munster met Spangien"
    candidate_texts = {
        "session-a": "de Staten Generael resolveren over den Vrede van Munster met Spangien",
        "session-b": "eenige leden vergaderen des morgens vroegh",
        "session-c": "de Vrede van Munster wort geresumeert",
    }

    ranked = score_candidates(enriched_text, candidate_texts)

    assert [item["session_id"] for item in ranked] == ["session-a", "session-c", "session-b"]
    assert ranked[0]["dense_similarity"] >= ranked[1]["dense_similarity"] >= ranked[2]["dense_similarity"]


def test_entity_overlap_outranks_weaker_text_similarity():
    enriched_text = "de vergadering resolveert"
    candidate_texts = {
        "session-x": "de vergadering resolveert",
        "session-y": "heel andere tekst zonder enig verband",
    }
    idf_weights = {"Munster": 5.0}
    candidate_entities = {"session-y": {"Munster"}}

    ranked = score_candidates(enriched_text, candidate_texts, idf_weights, candidate_entities)

    assert ranked[0]["session_id"] == "session-y"
    assert ranked[0]["entity_overlap_score"] == 5.0
    assert ranked[0]["combined_score"] > ranked[1]["combined_score"]


def test_session_text_concatenates_candidate_text_style_extraction():
    records = [{"resolutions_text": "eerste alinea"}, {"paragraph_text": "tweede alinea"}, {"resolutions_text": ""}]

    assert session_text(records) == "eerste alinea tweede alinea"


def test_flags_low_confidence_when_top_candidate_has_no_entity_overlap():
    enriched_text = "Ontvangen is een brief van de gedeputeerden te velde"
    candidate_texts = {
        "session-a": "Is gelesen concept vande Instructie bij den raedt van State",
        "session-b": "De heer Graeff van Cuijlenborch ende andere gedeputeerden",
    }

    ranked = score_candidates(enriched_text, candidate_texts)

    assert ranked[0]["entity_overlap_score"] == 0.0
    assert ranked[0]["low_confidence"] is True


def test_confident_when_top_candidate_clears_entity_overlap_floor():
    enriched_text = "de vergadering resolveert"
    candidate_texts = {"session-x": "de vergadering resolveert", "session-y": "onverwante tekst"}
    idf_weights = {"Munster": 8.0}
    candidate_entities = {"session-x": {"Munster"}}

    ranked = score_candidates(enriched_text, candidate_texts, idf_weights, candidate_entities)

    assert ranked[0]["session_id"] == "session-x"
    assert ranked[0]["low_confidence"] is False


def test_candidate_session_ids_reads_previous_day_column_for_minus_one_status():
    row = {"status_code": "-1", "previous_day_session_ids": ["session-a"], "next_day_session_ids": []}

    assert candidate_session_ids(row) == ["session-a"]


def test_candidate_session_ids_reads_next_day_column_for_plus_one_status():
    row = {"status_code": "+1", "previous_day_session_ids": [], "next_day_session_ids": ["session-b"]}

    assert candidate_session_ids(row) == ["session-b"]


def test_candidate_session_ids_unions_and_dedupes_both_columns_for_ambiguous_status():
    row = {
        "status_code": "?",
        "previous_day_session_ids": ["session-b", "session-a"],
        "next_day_session_ids": ["session-a", "session-c"],
    }

    assert candidate_session_ids(row) == ["session-a", "session-b", "session-c"]


def test_candidate_session_ids_empty_for_unsupported_status():
    row = {"status_code": "N", "previous_day_session_ids": [], "next_day_session_ids": []}

    assert candidate_session_ids(row) == []


def test_is_nihil_actum_matches_formulaic_entry_with_trailing_reason():
    assert is_nihil_actum("Nihil Actum")
    assert is_nihil_actum("Nihil Actum: Pasen.")
    assert is_nihil_actum("  nihil actum ")
    assert not is_nihil_actum("Ontvangen is een brief van de gedeputeerden")


def test_score_ledger_row_uses_candidate_ids_override_for_statuses_with_no_ledger_column():
    row = {"status_code": "N", "enriched_date": "1627-09-02", "enriched_ids": []}
    enriched_text_by_date = {"1627-09-02": "de vergadering resolveert"}
    flat_by_session = {"session-3186-num-1": [{"resolutions_text": "de vergadering resolveert"}]}

    ranked = score_ledger_row(
        row, enriched_text_by_date, flat_by_session, {}, {}, {}, candidate_ids=["session-3186-num-1"]
    )

    assert [item["session_id"] for item in ranked] == ["session-3186-num-1"]


def test_score_ledger_row_without_override_falls_back_to_candidate_session_ids():
    row = {"status_code": "N", "enriched_date": "1627-09-02", "enriched_ids": []}

    ranked = score_ledger_row(row, {"1627-09-02": "tekst"}, {}, {}, {}, {})

    assert ranked == []


def test_score_ledger_row_abstains_for_nihil_actum_enriched_date():
    row = {
        "status_code": "?",
        "enriched_date": "1626-01-05",
        "previous_day_session_ids": ["session-a"],
        "next_day_session_ids": [],
        "enriched_ids": [],
    }
    enriched_text_by_date = {"1626-01-05": "Nihil Actum"}

    ranked = score_ledger_row(row, enriched_text_by_date, {}, {}, {}, {})

    assert ranked == []


def test_text_confirmed_names_matches_exact_substring():
    assert text_confirmed_names(["Munster"], "de Vrede van Munster wort geresumeert") == {"Munster"}
    assert text_confirmed_names(["Spangien"], "de Vrede van Munster wort geresumeert") == set()


def test_text_confirmed_names_matches_spelling_variant_via_fuzzy_fallback():
    assert text_confirmed_names(["Charleton"], "De heer Carleton nomende sijn affscheijt") == {"Charleton"}


def test_text_confirmed_names_rejects_unrelated_name_below_threshold():
    assert text_confirmed_names(["Wassenaer"], "een heel andere tekst zonder enig verband") == set()


def test_score_ledger_row_uses_text_confirmed_names_when_enriched_entity_names_given():
    row = {"status_code": "N", "enriched_date": "1628-05-23", "enriched_ids": []}
    enriched_text_by_date = {"1628-05-23": "HHM nemen afscheid van ambassadeur Carlille"}
    flat_by_session = {
        "session-4562-num-237": [{"resolutions_text": "De heer Carleton nomende sijn affscheijt"}],
    }

    ranked = score_ledger_row(
        row, enriched_text_by_date, flat_by_session, {}, {}, {},
        candidate_ids=["session-4562-num-237"], enriched_entity_names=["Charleton"],
    )

    assert ranked[0]["shared_entities"] == ["Charleton"]
    assert ranked[0]["entity_overlap_score"] > 0


def test_shared_entities_unions_overlap_lookup_across_axis_ids():
    lookup = {
        ("volgnr-1", "axis-1"): {"Munster"},
        ("volgnr-1", "axis-2"): {"Spangien"},
        ("volgnr-2", "axis-1"): {"Munster"},
    }

    assert shared_entities(["volgnr-1"], ["axis-1", "axis-2"], lookup) == {"Munster", "Spangien"}
    assert shared_entities(["volgnr-1"], ["axis-3"], lookup) == set()

from __future__ import annotations

from match import _patterns_to_document
from preprocess import clean_span, mask_name_pattern, normalize_name_for_matching


def test_clean_span_collapses_broeckhuijsen_variants() -> None:
    a = clean_span("Heeren van Broeckhuijsen")
    b = clean_span("Heeren van Broeckhuysen")
    assert a == b


def test_normalize_name_for_matching_collapses_y_ij_ck_variants() -> None:
    a = normalize_name_for_matching("Broeckhuijsen")
    b = normalize_name_for_matching("Broeckhuysen")
    c = normalize_name_for_matching("Broekhuysen")

    assert a == b == c


def test_pattern_document_uses_same_canonical_form() -> None:
    doc_a = _patterns_to_document("Broeckhuijsen; van Lynden")
    doc_b = _patterns_to_document("Broeckhuysen; v. Lynden")

    assert doc_a == doc_b
    assert "broekhuisen" in doc_a


def test_normalize_name_for_matching_collapses_ck_family_variants() -> None:
    a = normalize_name_for_matching("Backs")
    b = normalize_name_for_matching("Baks")
    x = normalize_name_for_matching("Bax")
    ckx = normalize_name_for_matching("Backx")
    c = normalize_name_for_matching("Back")
    d = normalize_name_for_matching("Bak")
    e = normalize_name_for_matching("Bakk")

    assert a == b == x == ckx
    assert c == d == e


def test_clean_span_normalizes_raw_span_variants() -> None:
    raw_a = "Heeren van Broeckhuijsen, Bax ende Backx"
    raw_b = "Heeren van Broeckhuysen, Baks ende Backs"

    assert clean_span(raw_a) == clean_span(raw_b)


def test_normalize_name_for_matching_collapses_ae_to_aa() -> None:
    a = normalize_name_for_matching("haegh")
    b = normalize_name_for_matching("haagh")
    assert a == b


def test_clean_span_normalizes_ae_to_aa_in_raw_span() -> None:
    raw_a = "Heeren van haegh ende Broeckhuijsen"
    raw_b = "Heeren van haagh ende Broeckhuysen"

    assert clean_span(raw_a) == clean_span(raw_b)


def test_normalize_name_for_matching_collapses_g_gh_ch_variants() -> None:
    a = normalize_name_for_matching("Hage")
    b = normalize_name_for_matching("Haghe")
    c = normalize_name_for_matching("Hache")

    assert a == b == c


def test_clean_span_normalizes_g_gh_ch_in_raw_span() -> None:
    raw_a = "Heeren van Haghe ende Broeckhuijsen"
    raw_b = "Heeren van Hache ende Broeckhuysen"

    assert clean_span(raw_a) == clean_span(raw_b)


def test_normalize_name_for_matching_long_s_ocr_variants() -> None:
    assert normalize_name_for_matching("minifter") == normalize_name_for_matching("minister")
    assert normalize_name_for_matching("refident") == normalize_name_for_matching("resident")
    assert normalize_name_for_matching("fecretaris") == normalize_name_for_matching("secretaris")
    assert normalize_name_for_matching("conful") == normalize_name_for_matching("consul")
    assert normalize_name_for_matching("amfterdam") == normalize_name_for_matching("amsterdam")
    assert normalize_name_for_matching("fchout") == normalize_name_for_matching("schout")


def test_clean_span_normalizes_long_s_ocr_in_raw_span() -> None:
    raw_a = "Den minifter en den refident tot amfterdam"
    raw_b = "Den minister en den resident tot amsterdam"
    assert clean_span(raw_a) == clean_span(raw_b)


def test_mask_name_pattern_preserves_structure_not_identity() -> None:
    raw = "Wassenaer, Carel Lodewijk van"
    masked = mask_name_pattern(raw)
    assert masked == "N9 , N5 N8 van"


def test_mask_name_pattern_handles_unknown_name_flag() -> None:
    assert mask_name_pattern("", unknown=True) == "[UNK_NAME]"
    assert mask_name_pattern(None, unknown=True) == "[UNK_NAME]"

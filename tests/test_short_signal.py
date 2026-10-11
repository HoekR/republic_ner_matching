"""Unit tests for short/opening signal helpers (no legacy data paths)."""

from sequence_graph.short_signal import classify_enriched, opening_strength


def test_classify_enriched_no_decision_and_short():
    assert classify_enriched({"text": "Waarop geen resolutie is genomen."}) == (
        "no_decision_marker"
    )
    assert classify_enriched({"text": "Kort."}) == "short_text"
    assert classify_enriched({"text": "Langere tekst zonder marker " * 10}) is None


def test_opening_strength_scales():
    open_close = (
        "Ontfangen een Missive van den Ambassadeur, waerop egeen resolutie is gevallen."
    )
    open_only = "Ontfangen een requeste van Jan, ende daernaer andere saecken."
    assert opening_strength(open_close) == 1.0
    assert opening_strength(open_only) == 0.5
    assert opening_strength("Is geordonneert dat men sal....") == 0.0

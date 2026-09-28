from scripts.s6b_known_point_ledger import align_entity_mentions
from scripts.s6d_entity_mention_gap_placement import (
    build_vocab_pattern,
    mention_sequence,
    ordered_mentions,
    project_cuts,
)


def test_ordered_mentions_prefers_longer_name_at_same_start():
    pattern = build_vocab_pattern(["van holland", "holland"])
    assert ordered_mentions("de heer van holland reist", pattern) == ["van holland"]


def test_ordered_mentions_are_case_insensitive_and_in_reading_order():
    pattern = build_vocab_pattern(["heinsius", "slingelandt"])
    text = "Slingelandt schrijft aan Heinsius over de zaak."
    assert ordered_mentions(text, pattern) == ["slingelandt", "heinsius"]


def test_mention_sequence_tracks_cumulative_boundaries_per_text():
    pattern = build_vocab_pattern(["heinsius", "slingelandt"])
    texts = ["Heinsius meldt.", "niets hier.", "Slingelandt en Heinsius."]
    mentions, boundaries = mention_sequence(texts, pattern)
    assert mentions == ["heinsius", "slingelandt", "heinsius"]
    assert boundaries == [0, 1, 1, 3]


def test_project_cuts_uses_first_match_at_or_after_each_unit_boundary():
    # Three interior enriched units, each contributing one mention; flat side has the same
    # three mentions split over four local paragraphs (mirrors HTR over-segmentation).
    enriched_texts = ["Heinsius handelt.", "Slingelandt reageert.", "Fagel besluit."]
    flat_texts = ["Heinsius zegt iets.", "nog wat tekst.", "Slingelandt en Fagel."]

    pattern = build_vocab_pattern(["heinsius", "slingelandt", "fagel"])
    enriched_mentions, enriched_boundaries = mention_sequence(enriched_texts, pattern)
    flat_mentions, flat_boundaries = mention_sequence(flat_texts, pattern)

    pairs, _ = align_entity_mentions(flat_mentions, enriched_mentions)
    projected = project_cuts(pairs, enriched_boundaries, flat_boundaries)

    assert len(projected) == 3
    # Heinsius's own unit (k=0) matches the flat paragraph that holds "heinsius" (local para 0).
    assert projected[0] == 0
    # Slingelandt and Fagel both land in local paragraph 2, the only flat paragraph with either.
    assert projected[1] == 2
    assert projected[2] == 2


def test_project_cuts_falls_back_to_last_match_when_a_later_unit_is_unmatched():
    pattern = build_vocab_pattern(["heinsius"])
    enriched_texts = ["Heinsius handelt.", "geen genoemde naam."]
    flat_texts = ["niets.", "Heinsius meldt iets."]

    enriched_mentions, enriched_boundaries = mention_sequence(enriched_texts, pattern)
    flat_mentions, flat_boundaries = mention_sequence(flat_texts, pattern)
    pairs, _ = align_entity_mentions(flat_mentions, enriched_mentions)

    projected = project_cuts(pairs, enriched_boundaries, flat_boundaries)
    assert projected[0] == 1
    # Second unit has no mention of its own and nothing after it matches either -- falls back
    # to the last available match rather than returning None (caller decides abstention only
    # when `pairs` is empty for the whole gap).
    assert projected[1] == 1


def test_project_cuts_returns_all_none_when_gap_has_no_matches_at_all():
    pattern = build_vocab_pattern(["heinsius"])
    enriched_mentions, enriched_boundaries = mention_sequence(["geen naam.", "ook niet."], pattern)
    flat_mentions, flat_boundaries = mention_sequence(["stilte.", "nog stilte."], pattern)
    pairs, _ = align_entity_mentions(flat_mentions, enriched_mentions)
    assert pairs == []
    assert project_cuts(pairs, enriched_boundaries, flat_boundaries) == [None, None]

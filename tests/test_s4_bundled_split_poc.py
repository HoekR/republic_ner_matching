from scripts.s4_bundled_split_poc import (
    bundled_positions,
    locate_dictionary_matches,
    locate_instances,
    locate_span,
    merge_spans,
    propose_cuts,
    score_predicted_cuts,
    snap_cut_to_phrase,
    snap_predicted_cuts,
)


def test_locate_span_finds_exact_case_insensitive_match():
    assert locate_span("de Heere van Wassenaer reysde", "wassenaer") == (13, 22)


def test_locate_span_falls_back_to_whitespace_flexible_match():
    text = "de Heere van\n  Wassenaer reysde"
    assert locate_span(text, "van wassenaer") == (9, 24)


def test_locate_span_returns_none_when_absent():
    assert locate_span("geen naam hier", "wassenaer") is None


def test_locate_instances_advances_cursor_for_repeats():
    text = "Aerssen sprak. Daerna sprak Aerssen wederom."
    spans = locate_instances(text, ["Aerssen", "Aerssen"])
    assert spans == [(0, 7), (28, 35)]


def test_locate_dictionary_matches_respects_word_boundaries():
    text = "de Heere van Wassenaer en Wassenaerse saken"
    spans = locate_dictionary_matches(text, ["Wassenaer"])
    assert spans == [(13, 22)]


def test_locate_dictionary_matches_skips_short_names():
    spans = locate_dictionary_matches("de Ka in het schip", ["Ka"], min_length=3)
    assert spans == []


def test_merge_spans_drops_overlapping_later_additions():
    base = [(0, 5), (10, 15)]
    extra = [(2, 7), (20, 25)]
    assert merge_spans(base, extra) == [(0, 5), (10, 15), (20, 25)]


def test_propose_cuts_abstains_when_too_few_spans():
    assert propose_cuts([(0, 3), (10, 13)], k=2) is None


def test_propose_cuts_returns_zero_cuts_for_k_zero():
    assert propose_cuts([(0, 3)], k=0) == []


def test_propose_cuts_splits_evenly_spaced_spans():
    spans = [(0, 2), (10, 12), (20, 22), (30, 32)]
    assert propose_cuts(spans, k=1) == [16]


def test_propose_cuts_places_multiple_cuts_in_order():
    spans = [(0, 2), (10, 12), (20, 22), (30, 32), (40, 42), (50, 52)]
    assert propose_cuts(spans, k=2) == [16, 36]


def test_snap_cut_to_phrase_prefers_the_closest_candidate():
    offsets = [(100, "is gelesen", 1.0), (400, "ontfangen een missive", 0.9)]
    assert snap_cut_to_phrase(350, offsets) == (400, ("ontfangen een missive", 0.9))


def test_snap_cut_to_phrase_returns_raw_cut_when_nothing_is_nearby():
    offsets = [(1000, "is gelesen", 1.0)]
    assert snap_cut_to_phrase(50, offsets, max_distance=150) == (50, None)


def test_snap_predicted_cuts_keeps_a_valid_snap_and_falls_back_for_its_collision_partner():
    # Both raw cuts 300 and 400 are nearest to the same phrase hit at 420; snapping 300
    # there would collide with 400's own upper bound, so 300 falls back to its raw cut.
    offsets = [(420, "ontfangen een missive", 0.9)]
    assert snap_predicted_cuts([300, 400], offsets) == [
        (300, None),
        (420, ("ontfangen een missive", 0.9)),
    ]


def test_snap_predicted_cuts_preserves_strict_order():
    offsets = [(420, "ontfangen een missive", 0.9)]
    cuts = [cut for cut, _ in snap_predicted_cuts([300, 400], offsets)]
    assert cuts[0] < cuts[1]


def test_score_predicted_cuts_counts_within_tolerance_without_reuse():
    assert score_predicted_cuts([100, 200], gold=[105, 205], tolerance=10) == 2
    assert score_predicted_cuts([100, 100], gold=[105], tolerance=10) == 1
    assert score_predicted_cuts([100], gold=[500], tolerance=10) == 0


def test_bundled_positions_extracts_mid_paragraph_offsets_only():
    gold = {
        "days": [
            {
                "date": "1626-01-08",
                "k_e": 3,
                "boundaries": [
                    {"paragraph_stream_index": 2, "kind": "cut", "unit": "mid_paragraph", "char_offset": 409},
                    {"paragraph_stream_index": 2, "kind": "cut", "unit": "paragraph_boundary", "char_offset": 746},
                    {"paragraph_stream_index": 0, "kind": "cut", "unit": "paragraph_boundary", "char_offset": 424},
                ],
            }
        ]
    }
    axis = [
        {"date": "1626-01-08", "flat_id": "r1", "para_index": 0, "text": "eerste"},
        {"date": "1626-01-08", "flat_id": "r1", "para_index": 1, "text": "tweede"},
        {"date": "1626-01-08", "flat_id": "r2", "para_index": 0, "text": "derde"},
    ]
    positions = bundled_positions(gold, axis, codes={})
    assert len(positions) == 1
    assert positions[0]["target_splits"] == 1
    assert positions[0]["gold_offsets"] == [409]
    assert positions[0]["flat_id"] == "r2"
    assert positions[0]["para_index"] == 0


def test_bundled_positions_skips_days_marked_non_segmentable_by_review():
    gold = {
        "days": [
            {
                "date": "1626-02-28",
                "k_e": 7,
                "boundaries": [
                    {"paragraph_stream_index": 0, "kind": "cut", "unit": "mid_paragraph", "char_offset": 10},
                    {"paragraph_stream_index": 0, "kind": "cut", "unit": "mid_paragraph", "char_offset": 20},
                ],
            }
        ]
    }
    axis = [{"date": "1626-02-28", "flat_id": "r1", "para_index": 0, "text": "text"}]
    assert bundled_positions(gold, axis, codes={"1626-02-28": "M"}) == []

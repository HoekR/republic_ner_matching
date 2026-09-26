from scripts.s6b_known_point_ledger import (
    build_chain,
    collapse,
    enriched_index,
    flat_id_char_starts,
    gaps_of,
)


def test_enriched_index_reads_the_numeric_suffix():
    # Enriched ids sort as strings ("_10" before "_2"), so the index must be parsed.
    assert enriched_index("1626-06-06_12") == 12


def test_enriched_index_is_none_without_a_suffix():
    assert enriched_index("162608ja.xml") is None


def test_flat_id_char_starts_records_each_resolution_first_paragraph():
    records = [
        {"flat_id": "res-1", "text": "a" * 400},
        {"flat_id": "res-1", "text": "b" * 100},
        {"flat_id": "res-2", "text": "c" * 250},
    ]
    assert flat_id_char_starts(records) == {"res-1": 0, "res-2": 500}


def test_collapse_keeps_every_kind_that_pins_one_resolution():
    points = [
        {"kind": "tier1_anchor", "enriched_index": 3, "char_position": 900},
        {"kind": "gold_boundary", "enriched_index": 3, "char_position": 900},
    ]
    (entry,) = collapse(points)
    assert entry["enriched_index"] == 3
    assert entry["kinds"] == ["tier1_anchor", "gold_boundary"]


def test_collapse_orders_points_by_resolution_index():
    points = [
        {"kind": "tier1_anchor", "enriched_index": 5, "char_position": 1500},
        {"kind": "tier1_anchor", "enriched_index": 2, "char_position": 600},
    ]
    assert [entry["enriched_index"] for entry in collapse(points)] == [2, 5]


def test_chain_is_bounded_by_session_start_and_end_sentinels():
    chain = build_chain(k_e=4, total_chars=2000, interior=[])
    assert [entry["kinds"] for entry in chain] == [["session_start"], ["session_end"]]
    assert chain[0]["char_position"] == 0
    assert chain[-1]["enriched_index"] == 4


def test_a_day_with_no_interior_anchors_yields_one_gap_of_k_e_minus_one():
    # Exactly the cut points that still need placing.
    (gap,) = gaps_of(build_chain(k_e=7, total_chars=5000, interior=[]))
    assert gap["resolutions_in_gap"] == 6
    assert gap["char_span"] == 5000


def test_chain_drops_interior_points_outside_the_resolution_range():
    interior = [
        {"enriched_index": 0, "char_position": 0, "kinds": ["tier1_anchor"]},
        {"enriched_index": 9, "char_position": 9999, "kinds": ["tier1_anchor"]},
        {"enriched_index": 2, "char_position": 700, "kinds": ["tier1_anchor"]},
    ]
    chain = build_chain(k_e=4, total_chars=2000, interior=interior)
    assert [entry["enriched_index"] for entry in chain] == [0, 2, 4]


def test_gaps_count_only_the_resolutions_strictly_between_endpoints():
    interior = [{"enriched_index": 2, "char_position": 700, "kinds": ["tier1_anchor"]}]
    gaps = gaps_of(build_chain(k_e=5, total_chars=2000, interior=interior))
    assert [gap["resolutions_in_gap"] for gaps_ in [gaps] for gap in gaps_] == [1, 2]


def test_consecutive_pinned_resolutions_leave_a_determined_gap():
    interior = [
        {"enriched_index": 1, "char_position": 400, "kinds": ["tier1_anchor"]},
        {"enriched_index": 2, "char_position": 900, "kinds": ["tier1_anchor"]},
    ]
    gaps = gaps_of(build_chain(k_e=3, total_chars=1400, interior=interior))
    assert [gap["resolutions_in_gap"] for gap in gaps] == [0, 0, 0]
    assert [gap["char_span"] for gap in gaps] == [400, 500, 500]


def test_gap_rows_carry_the_kinds_of_both_endpoints():
    interior = [{"enriched_index": 1, "char_position": 400, "kinds": ["gold_boundary"]}]
    first, second = gaps_of(build_chain(k_e=2, total_chars=1000, interior=interior))
    assert first["left_kinds"] == ["session_start"] and first["right_kinds"] == ["gold_boundary"]
    assert second["right_kinds"] == ["session_end"]


def test_entity_mentions_align_in_order_with_flat_side_skips_but_no_enriched_side_gaps():
    from scripts.s6b_known_point_ledger import align_entity_mentions

    pairs, cost = align_entity_mentions(["Holland", "Zeeland", "Utrecht"], ["Holland", "Utrecht"])
    assert pairs == [(0, 0), (2, 1)]
    assert cost == 1.0

    pairs, cost = align_entity_mentions(["Holland", "Zeeland"], ["Holland", "Vriesland", "Zeeland"])
    assert pairs == []
    assert cost == float("inf")

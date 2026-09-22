import json

from scripts.s6b_anchor_harvest import (
    DONE_KEY,
    abstention_supply_gain,
    checkpoint_path_for,
    density_report,
    fuzzy_scan_rows,
    harvest_row,
    read_checkpoint_rows,
    read_done_dates,
    session_boundary_rows,
    session_date_verified_rows,
    session_day_find_rows,
    session_id_char_starts,
    surface_match_rows,
    tier1_rows,
)


def test_harvest_row_carries_the_channel_group_and_weight():
    row = harvest_row("1626-01-01", "3185", "tier1_entity_nw", 42, {"enriched_index": 1})
    assert row["group"] == "A"
    assert row["weight"] == 3.0
    assert row["char_position"] == 42
    assert row["payload"] == {"enriched_index": 1}


def test_session_boundary_rows_bound_the_day():
    rows = session_boundary_rows("1626-01-01", "3185", 2000)
    assert [row["char_position"] for row in rows] == [0, 2000]
    assert all(row["group"] == "D" for row in rows)


def test_tier1_rows_reuse_the_known_point_positions():
    points = [{"kind": "tier1_anchor", "enriched_index": 3, "char_position": 900}]
    (row,) = tier1_rows("1626-01-01", "3185", points)
    assert row["channel"] == "tier1_entity_nw"
    assert row["char_position"] == 900
    assert row["payload"] == {"enriched_index": 3}


def test_surface_match_rows_position_at_the_flat_ids_paragraph_start():
    flat_starts = {"res-1": 500}
    matches_by_flat_id = {"res-1": [{"entity_type": "LOC", "entity_id": "L1", "canonical_name": "Rotterdam", "match_method": "exact"}]}
    (row,) = surface_match_rows("1626-01-01", "3185", flat_starts, matches_by_flat_id)
    assert row["channel"] == "entity_surface_matches"
    assert row["char_position"] == 500
    assert row["payload"]["canonical_name"] == "Rotterdam"


def test_surface_match_rows_skips_flat_ids_with_no_matches():
    assert surface_match_rows("1626-01-01", "3185", {"res-1": 500}, {}) == []


def test_fuzzy_scan_rows_compose_paragraph_start_and_within_paragraph_offset():
    axis_starts = {"res-1#p1": 500}
    records = [{"axis_id": "res-1#p1", "flat_id": "res-1", "offset": 20, "category": "LOC", "entity_id": "L1", "canonical_name": "Rotterdam", "matched_text": "Rotterdm", "already_known": False}]
    (row,) = fuzzy_scan_rows("1626-01-01", "3185", axis_starts, records)
    assert row["char_position"] == 520
    assert row["payload"]["already_known"] is False


def test_fuzzy_scan_rows_skips_records_whose_axis_id_is_off_window():
    records = [{"axis_id": "missing#p0", "flat_id": "res-1", "offset": 0, "category": "LOC", "entity_id": "L1", "canonical_name": "X", "matched_text": "x", "already_known": True}]
    assert fuzzy_scan_rows("1626-01-01", "3185", {}, records) == []


def test_density_report_counts_anchors_days_and_distinct_positions_per_channel():
    rows = [
        harvest_row("1626-01-01", "3185", "tier1_entity_nw", 10, {}),
        harvest_row("1626-01-01", "3185", "tier1_entity_nw", 10, {}),  # same position, counted twice as anchors
        harvest_row("1626-01-02", "3185", "tier1_entity_nw", 20, {}),
    ]
    report = density_report(rows)
    assert report["tier1_entity_nw"]["anchors"] == 3
    assert report["tier1_entity_nw"]["days"] == 2
    assert report["tier1_entity_nw"]["distinct_positions"] == 2


def test_abstention_supply_gain_flags_days_with_no_group_a_anchor_at_all():
    rows = [
        harvest_row("1626-01-01", "3185", "tier1_entity_nw", 10, {}),
        harvest_row("1626-01-02", "3185", "s2_anchor_phrases", 5, {}),
        harvest_row("1626-01-03", "3185", "session_boundary", 0, {}),
    ]
    result = abstention_supply_gain(rows, ["1626-01-01", "1626-01-02", "1626-01-03"])
    assert result["abstained_days_in_window"] == 3
    # 1626-01-01 has a group-A anchor so it is excluded from "zero group-A" even
    # though it is in the (hypothetical) abstained list.
    assert result["zero_group_a_anchor_days"] == 2
    # 1626-01-02 gains an s2_anchor_phrases (group C) anchor; 1626-01-03 only has
    # the session-boundary sentinel, which does not count as a gain.
    assert result["of_those_gaining_a_non_group_a_anchor"] == 1


def test_session_day_find_rows_pairs_a_president_hit_with_a_nearby_present_hit():
    president_hits = [(200, 1.0, "preside")]
    present_hits = [(230, 0.9, "presentibus")]
    (row,) = session_day_find_rows("1626-01-01", "3185", president_hits, present_hits)
    assert row["channel"] == "session_day_find"
    assert row["group"] == "D"
    assert row["char_position"] == 200
    assert row["payload"] == {
        "president_phrase": "preside",
        "president_similarity": 1.0,
        "present_phrase": "presentibus",
        "present_similarity": 0.9,
    }


def test_session_day_find_rows_skips_hits_inside_the_leading_buffer():
    # A hit at char 10 is the day's own opening, not an internal session merge.
    president_hits = [(10, 1.0, "president")]
    present_hits = [(40, 1.0, "present")]
    assert session_day_find_rows("1626-01-01", "3185", president_hits, present_hits) == []


def test_session_day_find_rows_skips_president_hits_with_no_nearby_present():
    president_hits = [(200, 1.0, "president")]
    present_hits = [(500, 1.0, "present")]  # outside the 60-char window
    assert session_day_find_rows("1626-01-01", "3185", president_hits, present_hits) == []


def test_session_day_find_rows_picks_the_most_similar_present_hit_in_window():
    president_hits = [(200, 1.0, "president")]
    present_hits = [(210, 0.85, "presenteert"), (230, 0.95, "presentibus"), (500, 1.0, "present")]
    (row,) = session_day_find_rows("1626-01-01", "3185", president_hits, present_hits)
    assert row["payload"]["present_phrase"] == "presentibus"
    assert row["payload"]["present_similarity"] == 0.95


def test_session_id_char_starts_groups_resolutions_under_their_session_and_keeps_the_first_start():
    axis = [
        {"flat_id": "session-3185-num-1-resolution-1"},
        {"flat_id": "session-3185-num-1-resolution-1"},  # second paragraph of the same resolution
        {"flat_id": "session-3185-num-1-resolution-2"},  # second resolution, same session
        {"flat_id": "session-3185-num-2-resolution-1"},  # next session
        {"flat_id": "not-a-flat-id"},
    ]
    starts = [0, 100, 250, 900, 1200]
    assert session_id_char_starts(axis, starts) == {"session-3185-num-1": 0, "session-3185-num-2": 900}


def test_session_date_verified_rows_anchors_only_uniquely_matched_sessions():
    session_starts = {"session-3185-num-1": 0, "session-3185-num-2": 900}
    verified_by_session_id = {
        "session-3185-num-1": {"raw_session_id": "session-3185-num-2", "raw_num": 2, "offset": 1},
        # session-3185-num-2 has no entry: unmatched or ambiguous, contributes nothing.
    }
    (row,) = session_date_verified_rows("1626-01-01", "3185", session_starts, verified_by_session_id)
    assert row["channel"] == "session_date_verified"
    assert row["group"] == "D"
    assert row["char_position"] == 0
    assert row["payload"] == {
        "flat_session_id": "session-3185-num-1",
        "raw_session_id": "session-3185-num-2",
        "raw_num": 2,
        "offset": 1,
    }


def test_session_date_verified_rows_empty_when_nothing_verified():
    assert session_date_verified_rows("1626-01-01", "3185", {"session-3185-num-1": 0}, {}) == []


def test_checkpoint_path_for_uses_a_sibling_checkpoint_suffix(tmp_path):
    output_path = tmp_path / "s6b_anchor_harvest.jsonl"
    assert checkpoint_path_for(output_path) == tmp_path / "s6b_anchor_harvest.checkpoint.jsonl"


def test_read_done_dates_collects_only_marker_lines(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(harvest_row("1626-01-01", "3185", "session_boundary", 0, {})),
                json.dumps({DONE_KEY: "1626-01-01"}),
                json.dumps(harvest_row("1626-01-02", "3185", "session_boundary", 0, {})),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert read_done_dates(path) == {"1626-01-01"}


def test_read_done_dates_on_a_missing_file_is_empty(tmp_path):
    assert read_done_dates(tmp_path / "does_not_exist.jsonl") == set()


def test_read_checkpoint_rows_excludes_done_markers(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    row = harvest_row("1626-01-01", "3185", "session_boundary", 0, {})
    path.write_text(
        "\n".join([json.dumps(row), json.dumps({DONE_KEY: "1626-01-01"})]) + "\n",
        encoding="utf-8",
    )
    rows = read_checkpoint_rows(path)
    assert len(rows) == 1
    assert rows[0]["channel"] == "session_boundary"

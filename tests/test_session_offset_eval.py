import pandas as pd

from scripts.session_offset_eval import (
    build_brackets,
    day_distance,
    enriched_sittings,
    htr_sessions,
    offset_runs,
    ordinal_offset_rows,
    restrict_to_enriched_span,
)


def _concordance(rows):
    """rows: (date, inventory_id, status, k_e, resolved_session_id) -> one frame row per resolution."""
    records = []
    for date, inventory_id, status, k_e, session_id in rows:
        for index in range(k_e):
            records.append(
                {
                    "enriched_date": date,
                    "inventory_id": inventory_id,
                    "status": status,
                    "enriched_id": f"{date}_{index}",
                    "resolved_session_id": session_id,
                }
            )
    return pd.DataFrame(records)


def _axis(rows):
    """rows: (session_id, date, n_paragraphs)."""
    records = []
    for session_id, date, paragraphs in rows:
        for index in range(paragraphs):
            records.append({"date": date, "flat_id": f"{session_id}-resolution-{index + 1}"})
    return records


def test_day_distance_handles_pre_1678_dates():
    # pd.Timestamp cannot represent these at all; pd.Period must be used.
    assert day_distance("1626-01-01", "1626-01-01") == 0
    assert day_distance("1626-03-01", "1626-02-27") == 2
    assert day_distance("1626-02-27", "1626-03-01") == 2


def test_enriched_sittings_excludes_nihil_from_the_ordinal_sequence():
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "resolved_auto", 2, "session-3185-num-1"),
            ("1626-01-04", 3185, "nihil_actum", 1, ""),
            ("1626-01-05", 3185, "missing_htr", 3, ""),
            ("1626-01-06", 3185, "resolved_auto", 1, "session-3185-num-2"),
        ]
    )
    sittings = enriched_sittings(concordance)

    assert list(sittings["enriched_date"]) == ["1626-01-01", "1626-01-05", "1626-01-06"]
    # A nihil sitting consumes no HTR session, so it must not shift later ordinals.
    assert list(sittings["enriched_ordinal"]) == [0, 1, 2]
    assert list(sittings["is_resolved"]) == [True, False, True]
    assert list(sittings["k_e"]) == [2, 3, 1]


def test_htr_sessions_orders_by_flat_num_not_lexically():
    sessions = htr_sessions(
        _axis(
            [
                ("session-3185-num-10", "1626-02-01", 3),
                ("session-3185-num-2", "1626-01-05", 1),
                ("session-3186-num-1", "1627-01-01", 2),
            ]
        )
    )
    inv_3185 = sessions.loc[sessions["inventory_id"] == 3185]
    assert list(inv_3185["flat_num"]) == [2, 10]
    assert list(inv_3185["htr_ordinal"]) == [0, 1]
    # Ordinals restart per inventory.
    assert sessions.loc[sessions["inventory_id"] == 3186, "htr_ordinal"].tolist() == [0]
    assert inv_3185["paragraph_count"].tolist() == [1, 3]


def test_offset_runs_collapses_piecewise_constant_drift():
    assert offset_runs([0, 0, 0, 5, 5, 13]) == [
        {"offset": 0, "length": 3},
        {"offset": 5, "length": 2},
        {"offset": 13, "length": 1},
    ]
    assert offset_runs([]) == []


def test_ordinal_offset_reports_drift_and_label_distance():
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "resolved_auto", 1, "session-3185-num-1"),
            ("1626-01-02", 3185, "missing_htr", 1, ""),
            ("1626-01-03", 3185, "resolved_auto", 1, "session-3185-num-3"),
        ]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-3185-num-1", "1626-01-01", 1),
                ("session-3185-num-2", "1626-01-02", 1),
                ("session-3185-num-3", "1626-01-09", 1),
            ]
        )
    )
    resolved, summaries = ordinal_offset_rows(enriched_sittings(concordance), sessions)

    assert resolved["session_offset"].tolist() == [0, 0]
    summary = summaries[0]
    assert summary["resolved_sittings"] == 2
    assert summary["non_monotone_steps"] == 0
    # session-3185-num-3 is labelled 1626-01-09 but claimed by the 01-03 sitting.
    assert summary["label_distance_beyond_window"] == 1


def test_determined_bracket_forces_a_pairing_the_window_cannot_reach():
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "resolved_auto", 1, "session-3185-num-1"),
            ("1626-01-02", 3185, "missing_htr", 4, ""),
            ("1626-01-03", 3185, "resolved_auto", 1, "session-3185-num-3"),
        ]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-3185-num-1", "1626-01-01", 1),
                ("session-3185-num-2", "1626-01-20", 6),
                ("session-3185-num-3", "1626-01-03", 1),
            ]
        )
    )
    brackets, pairings = build_brackets(enriched_sittings(concordance), sessions)

    interior = [b for b in brackets if b["kind"] == "interior"]
    assert len(interior) == 1
    assert interior[0]["bracket_class"] == "determined"
    assert interior[0]["n_unresolved_sittings"] == 1
    assert interior[0]["n_unclaimed_sessions"] == 1
    assert interior[0]["unresolved_k_e"] == 4
    assert interior[0]["unclaimed_paragraphs"] == 6
    assert interior[0]["unresolved_statuses"] == {"missing_htr": 1}

    assert len(pairings) == 1
    pairing = pairings[0]
    assert pairing["enriched_date"] == "1626-01-02"
    assert pairing["session_id"] == "session-3185-num-2"
    # 18 days: order forces a pairing the +/-1-day candidate window cannot reach.
    assert pairing["day_distance"] == 18
    assert pairing["beyond_candidate_window"] is True


def test_deficit_and_surplus_brackets_force_nothing():
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "resolved_auto", 1, "session-3185-num-1"),
            ("1626-01-02", 3185, "missing_htr", 1, ""),
            ("1626-01-03", 3185, "missing_htr", 1, ""),
            ("1626-01-04", 3185, "resolved_auto", 1, "session-3185-num-3"),
        ]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-3185-num-1", "1626-01-01", 1),
                ("session-3185-num-2", "1626-01-02", 1),
                ("session-3185-num-3", "1626-01-04", 1),
            ]
        )
    )
    brackets, pairings = build_brackets(enriched_sittings(concordance), sessions)

    interior = [b for b in brackets if b["kind"] == "interior"][0]
    assert interior["bracket_class"] == "deficit"
    assert (interior["n_unresolved_sittings"], interior["n_unclaimed_sessions"]) == (2, 1)
    assert pairings == []


def test_unclaimed_session_with_no_sitting_is_the_no_insertion_case():
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "resolved_auto", 1, "session-3185-num-1"),
            ("1626-01-02", 3185, "resolved_auto", 1, "session-3185-num-3"),
        ]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-3185-num-1", "1626-01-01", 1),
                ("session-3185-num-2", "1626-01-02", 1),
                ("session-3185-num-3", "1626-01-02", 1),
            ]
        )
    )
    brackets, _ = build_brackets(enriched_sittings(concordance), sessions)

    interior = [b for b in brackets if b["kind"] == "interior"][0]
    assert interior["bracket_class"] == "surplus_no_sitting"
    assert interior["n_unresolved_sittings"] == 0
    assert interior["n_unclaimed_sessions"] == 1


def test_sessions_past_the_edition_end_are_dropped_and_ordinals_re_ranked():
    sessions = htr_sessions(
        _axis(
            [
                ("session-3189-num-1", "1630-05-01", 1),
                ("session-3189-num-2", "1630-07-02", 1),
                ("session-3189-num-3", "1630-12-31", 1),
                ("session-4562-num-9", "1630-05-11", 1),
            ]
        )
    )
    retained, excluded = restrict_to_enriched_span(sessions, "1630-05-14")

    assert sorted(excluded["session_id"]) == ["session-3189-num-2", "session-3189-num-3"]
    assert list(retained["session_id"]) == ["session-3189-num-1", "session-4562-num-9"]
    # Ordinals are recomputed on the retained stream, restarting per inventory.
    assert list(retained["htr_ordinal"]) == [0, 0]


def test_barred_sessions_cannot_be_offered_to_an_earlier_unresolved_sitting():
    # The 4562 case: a post-edition session sits inside an ordinary bracket, not a trailing
    # one, so without the filter it would be paired with a sitting dated years earlier.
    concordance = _concordance(
        [
            ("1628-03-01", 4562, "resolved_auto", 1, "session-4562-num-1"),
            ("1628-03-02", 4562, "missing_htr", 4, ""),
            ("1628-03-03", 4562, "resolved_auto", 1, "session-4562-num-3"),
        ]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-4562-num-1", "1628-03-01", 1),
                ("session-4562-num-2", "1630-10-26", 1),
                ("session-4562-num-3", "1628-03-03", 1),
            ]
        )
    )
    retained, excluded = restrict_to_enriched_span(sessions, "1630-05-14")
    assert list(excluded["session_id"]) == ["session-4562-num-2"]

    _, pairings = build_brackets(enriched_sittings(concordance), retained)
    assert pairings == []

    # Without the constraint the same data forces a 2.6-year pairing -- what it prevents.
    _, unguarded = build_brackets(enriched_sittings(concordance), sessions)
    assert [p["session_id"] for p in unguarded] == ["session-4562-num-2"]
    assert unguarded[0]["day_distance"] > 900


def test_surplus_past_the_last_sitting_is_span_not_insertion():
    # The enriched edition ends before the axis does (1630-05-14 vs 1630-12-31 in the real
    # corpus), so trailing HTR must not be counted as a session with no enriched sitting.
    concordance = _concordance(
        [("1630-05-14", 3189, "resolved_auto", 1, "session-3189-num-1")]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-3189-num-1", "1630-05-14", 1),
                ("session-3189-num-2", "1630-07-02", 1),
                ("session-3189-num-3", "1630-12-31", 1),
            ]
        )
    )
    brackets, _ = build_brackets(enriched_sittings(concordance), sessions)

    tail = [b for b in brackets if b["kind"] == "tail"][0]
    assert tail["bracket_class"] == "outside_enriched_span"
    assert tail["n_unclaimed_sessions"] == 2
    assert not any(b["bracket_class"] == "surplus_no_sitting" for b in brackets)


def test_sessions_are_counted_in_one_bracket_only_when_pins_run_backwards():
    # Non-monotone pins make the bracket ranges overlap; without a guard, session-num-3
    # would be counted both in the bracket ending at pin 4 and the one starting at pin 2.
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "resolved_auto", 1, "session-3185-num-4"),
            ("1626-01-02", 3185, "resolved_auto", 1, "session-3185-num-2"),
            ("1626-01-03", 3185, "resolved_auto", 1, "session-3185-num-5"),
        ]
    )
    sessions = htr_sessions(
        _axis([(f"session-3185-num-{n}", "1626-01-01", 1) for n in range(1, 6)])
    )
    brackets, _ = build_brackets(enriched_sittings(concordance), sessions)

    counted = sum(b["n_unclaimed_sessions"] for b in brackets)
    unclaimed = {"session-3185-num-1", "session-3185-num-3"}
    assert counted == len(unclaimed)


def test_non_monotone_pins_take_no_classification():
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "resolved_auto", 1, "session-3185-num-5"),
            ("1626-01-02", 3185, "missing_htr", 1, ""),
            ("1626-01-03", 3185, "resolved_auto", 1, "session-3185-num-1"),
        ]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-3185-num-1", "1626-01-03", 1),
                ("session-3185-num-2", "1626-01-04", 1),
                ("session-3185-num-5", "1626-01-01", 1),
            ]
        )
    )
    brackets, pairings = build_brackets(enriched_sittings(concordance), sessions)

    interior = [b for b in brackets if b["kind"] == "interior"][0]
    assert interior["bracket_class"] == "non_monotone"
    assert interior["n_unclaimed_sessions"] == 0
    assert pairings == []


def test_head_and_tail_brackets_are_open_on_one_side():
    concordance = _concordance(
        [
            ("1626-01-01", 3185, "missing_htr", 2, ""),
            ("1626-01-02", 3185, "resolved_auto", 1, "session-3185-num-2"),
            ("1626-01-03", 3185, "missing_htr", 3, ""),
        ]
    )
    sessions = htr_sessions(
        _axis(
            [
                ("session-3185-num-1", "1626-01-01", 1),
                ("session-3185-num-2", "1626-01-02", 1),
                ("session-3185-num-3", "1626-01-03", 1),
            ]
        )
    )
    brackets, pairings = build_brackets(enriched_sittings(concordance), sessions)

    kinds = {b["kind"]: b for b in brackets}
    assert kinds["head"]["bracket_class"] == "determined"
    assert kinds["tail"]["bracket_class"] == "determined"
    assert {p["enriched_date"] for p in pairings} == {"1626-01-01", "1626-01-03"}


def test_inventory_with_no_htr_sessions_is_all_deficit():
    concordance = _concordance(
        [
            ("1626-01-01", 4861, "missing_htr", 5, ""),
            ("1626-01-02", 4861, "missing_htr", 7, ""),
        ]
    )
    sessions = htr_sessions(_axis([("session-3185-num-1", "1626-01-01", 1)]))
    brackets, pairings = build_brackets(enriched_sittings(concordance), sessions)

    whole = [b for b in brackets if b["inventory_id"] == 4861]
    assert len(whole) == 1
    assert whole[0]["kind"] == "whole_inventory"
    assert whole[0]["bracket_class"] == "deficit_no_session"
    assert whole[0]["unresolved_k_e"] == 12
    assert pairings == []

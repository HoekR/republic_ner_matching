import pandas as pd

from scripts.landmark_density_eval import (
    _quantile,
    axis_stream,
    build_segments,
    date_sequence,
    detect_in_axis_markers,
    fingerprint_channel,
    flat_sessions,
    order_preservation,
    raw_session_landmarks,
    segment_stats,
)


def _regions(rows):
    return pd.DataFrame(
        [
            {
                "session_id": session_id,
                "text_region_class": region_class,
                "president_hit": president,
                "present_hit": present,
                "text": "x",
            }
            for session_id, region_class, president, present in rows
        ]
    )


def test_raw_session_landmarks_reads_region_order_not_just_presence():
    regions = _regions(
        [
            ("session-3185-num-1", "date", True, True),
            ("session-3185-num-1", "attendance", False, False),
            ("session-3185-num-1", "para", False, False),
            ("session-3185-num-2", "para", False, False),
            ("session-3185-num-2", "date", False, False),
        ]
    )
    frame = raw_session_landmarks(regions).set_index("session_id")

    assert frame.at["session-3185-num-1", "date_is_first_region"]
    assert frame.at["session-3185-num-1", "opening_before_first_para"]
    assert frame.at["session-3185-num-1", "president_hit"]
    # num-2 has a date region, but it sits *after* the first paragraph: presence alone
    # would call this a session opening, position says it is not.
    assert frame.at["session-3185-num-2", "has_date_region"]
    assert not frame.at["session-3185-num-2", "date_is_first_region"]
    assert not frame.at["session-3185-num-2", "opening_before_first_para"]


def test_raw_session_landmarks_handles_a_session_with_no_para_regions():
    frame = raw_session_landmarks(_regions([("session-3185-num-9", "date", False, False)]))
    assert frame.loc[0, "n_para_regions"] == 0
    assert not frame.loc[0, "opening_before_first_para"]


def _axis(rows):
    return [
        {"date": date, "flat_id": flat_id, "para_index": para_index, "text": text}
        for date, flat_id, para_index, text in rows
    ]


AXIS_ROWS = _axis(
    [
        ("1626-01-02", "session-3185-num-2-resolution-1", 0, "Preside den heer met Presentibus alle"),
        ("1626-01-02", "session-3185-num-2-resolution-1", 1, "tweede paragraaf"),
        ("1626-01-01", "session-3185-num-1-resolution-1", 0, "Ontfangen een missive vanden ambassadeur"),
        ("1626-01-01", "session-3185-num-1-resolution-2", 0, "gewone tekst"),
    ]
)


def test_axis_stream_orders_by_archival_sequence_not_by_date_or_input_order():
    stream = axis_stream(AXIS_ROWS)
    assert list(stream["flat_id"]) == [
        "session-3185-num-1-resolution-1",
        "session-3185-num-1-resolution-2",
        "session-3185-num-2-resolution-1",
        "session-3185-num-2-resolution-1",
    ]
    assert list(stream["stream_index"]) == [0, 1, 2, 3]
    assert list(stream["flat_session_id"].unique()) == ["session-3185-num-1", "session-3185-num-2"]


def test_flat_sessions_summarise_stream_position_and_size():
    sessions = flat_sessions(axis_stream(AXIS_ROWS)).set_index("flat_session_id")
    assert sessions.at["session-3185-num-1", "start_stream_index"] == 0
    assert sessions.at["session-3185-num-1", "n_paragraphs"] == 2
    assert sessions.at["session-3185-num-2", "start_stream_index"] == 2


def test_detect_in_axis_markers_finds_both_mapping_free_classes():
    head = pd.DataFrame(
        {
            "flat_session_id": ["a", "b", "c"],
            "head_text": [
                "Preside den heer met Presentibus alle",
                "Ontfangen een missiue vanden resident",
                "gewone tekst zonder formule",
            ],
        }
    )
    out = detect_in_axis_markers(head).set_index("flat_session_id")
    assert out.at["a", "in_axis_president_and_present"]
    assert not out.at["b", "in_axis_president_or_present"]
    # spelling variant "missiue" must still hit -- HTR noise is the point of fuzzy search
    assert out.at["b", "formulaic_opening"]
    assert not out.at["c", "formulaic_opening"]
    assert not out.at["c", "in_axis_president_or_present"]


def _fingerprints():
    return [
        {"inventory_id": "3185", "flat_num": 1, "flat_session_id": "session-3185-num-1", "raw_num": None},
        {"inventory_id": "3185", "flat_num": 2, "flat_session_id": "session-3185-num-2", "raw_num": 3},
        {"inventory_id": "3185", "flat_num": 3, "flat_session_id": "session-3185-num-3", "raw_num": 4},
    ]


def test_fingerprint_channel_builds_integer_raw_session_ids_despite_null_rows():
    """A None/int mix re-inferred to float once produced 'session-3185-num-3.0', which
    matched no raw session and silently zeroed the attendance channel."""
    raw = raw_session_landmarks(
        _regions(
            [
                ("session-3185-num-3", "date", False, False),
                ("session-3185-num-3", "attendance", False, False),
                ("session-3185-num-4", "date", False, False),
            ]
        )
    )
    frame = fingerprint_channel(_fingerprints(), raw).set_index("flat_session_id")

    assert frame.at["session-3185-num-2", "raw_session_id"] == "session-3185-num-3"
    assert frame.at["session-3185-num-1", "raw_session_id"] is None
    assert not frame.at["session-3185-num-1", "fingerprint_verified"]
    assert frame.at["session-3185-num-2", "verified_with_attendance"]
    # num-4 exists but carries no attendance region: verified, not attendance-verified
    assert frame.at["session-3185-num-3", "fingerprint_verified"]
    assert not frame.at["session-3185-num-3", "verified_with_attendance"]


def test_order_preservation_reports_drift_shape_not_just_drift_presence():
    raw = raw_session_landmarks(_regions([("session-3185-num-3", "date", False, False)]))
    frame = fingerprint_channel(_fingerprints(), raw)
    report = order_preservation(frame).set_index("inventory_id")

    assert report.at[3185, "verified"] == 2
    assert report.at[3185, "non_monotone_steps"] == 0
    # both matched sessions carry the same +1 offset: one run, i.e. a piecewise shift
    # rather than noise -- the label is wrong but the order is intact.
    assert report.at[3185, "offset_runs"] == 1
    assert report.at[3185, "drifted_share"] == 1.0


def _dates(rows):
    return pd.DataFrame(
        [
            {
                "enriched_date": date,
                "k_e": k_e,
                "inventory_id": 3185,
                "paragraph_count": paragraphs,
                "first_flat_session_id": session_id,
            }
            for date, k_e, paragraphs, session_id in rows
        ]
    )


DATES = _dates(
    [
        ("1626-01-01", 5, 2, "session-3185-num-1"),
        ("1626-01-02", 1, 9, "session-3185-num-2"),
        ("1626-01-03", 4, 4, "session-3185-num-3"),
    ]
)


def test_build_segments_cuts_only_at_landmarks():
    segments, _ = build_segments(DATES, {"session-3185-num-1", "session-3185-num-3"})
    assert [s["n_dates"] for s in segments] == [2, 1]
    assert [s["k_e"] for s in segments] == [6, 4]
    assert [s["paragraph_count"] for s in segments] == [11, 4]


def test_every_date_reproduces_the_day_partition_even_without_landmarks():
    segments, _ = build_segments(DATES, set(), every_date=True)
    assert [s["n_dates"] for s in segments] == [1, 1, 1]
    # pigeonhole per day: min(5,2) + min(1,9) + min(4,4) = 2 + 1 + 4
    assert sum(min(s["k_e"], s["paragraph_count"]) for s in segments) == 7


def test_the_first_date_always_opens_a_segment_when_it_carries_no_landmark():
    segments, _ = build_segments(DATES, {"session-3185-num-3"})
    assert [s["n_dates"] for s in segments] == [2, 1]


def test_isolate_no_htr_bars_a_dateless_day_from_borrowing_paragraphs():
    dates = _dates(
        [
            ("1626-01-01", 3, 0, None),  # no HTR at all: no flat session, no landmark
            ("1626-01-02", 2, 9, "session-3185-num-2"),
        ]
    )
    merged, _ = build_segments(dates, set())
    assert [s["k_e"] for s in merged] == [5]
    assert sum(min(s["k_e"], s["paragraph_count"]) for s in merged) == 5

    isolated, _ = build_segments(dates, set(), isolate_no_htr=True)
    assert [s["k_e"] for s in isolated] == [3, 2]
    # the no-HTR date contributes min(3, 0) = 0 instead of being absorbed
    assert sum(min(s["k_e"], s["paragraph_count"]) for s in isolated) == 2


def test_segment_stats_reports_both_headroom_variants_and_locality():
    stats = segment_stats(DATES, {"session-3185-num-1"}, "test_channel")
    assert stats["n_segments"] == 1
    assert stats["mean_dates_per_segment"] == 3.0
    assert stats["median_segment_k_e"] == 10
    # one segment: min(10 k_e, 15 paragraphs) = 10, no deficit left
    assert stats["segment_ceiling"] == 10
    assert stats["segment_deficit"] == 0
    assert stats["segment_ceiling_no_htr_isolated"] == 10


def test_date_sequence_counts_k_e_and_paragraphs_the_same_way_the_ceiling_script_does():
    concordance = pd.DataFrame(
        {
            "enriched_date": ["1626-01-01", "1626-01-01", "1626-01-02", "1626-01-09"],
            "inventory_id": [3185, 3185, 3185, 3185],
        }
    )
    stream = axis_stream(AXIS_ROWS)
    frame = date_sequence(concordance, stream, flat_sessions(stream)).set_index("enriched_date")

    assert frame.at["1626-01-01", "k_e"] == 2
    assert frame.at["1626-01-01", "paragraph_count"] == 2
    assert frame.at["1626-01-01", "first_flat_session_id"] == "session-3185-num-1"
    # a date with enriched resolutions but no HTR paragraphs stays in the frame at 0
    assert frame.at["1626-01-09", "paragraph_count"] == 0
    assert pd.isna(frame.at["1626-01-09", "first_flat_session_id"])


def test_quantile_is_index_safe_at_the_edges():
    assert _quantile([], 0.9) == 0.0
    assert _quantile([5], 0.9) == 5.0
    assert _quantile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 10.0

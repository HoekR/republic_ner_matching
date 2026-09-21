import pandas as pd

from analyze_n_status_gaps import (
    WIDE_WINDOW_OFFSETS,
    direct_session_ids,
    direct_sessions,
    nearest_recovery_candidates,
    nearest_recovery_offset,
)


def _flat(rows):
    return pd.DataFrame(
        [{"id": f"session-{inventory_id}-num-1-resolution-0", "date": date} for inventory_id, date in rows]
    )


def test_direct_session_ids_groups_sorted_session_ids_by_inventory_and_date():
    flat = pd.DataFrame(
        [
            {"id": "session-3186-num-1-resolution-0", "date": "1627-09-02"},
            {"id": "session-3186-num-2-resolution-0", "date": "1627-09-02"},
            {"id": "session-3186-num-3-resolution-0", "date": "1627-09-03"},
        ]
    )

    known = direct_session_ids(flat)

    assert known[(3186, "1627-09-02")] == ["session-3186-num-1", "session-3186-num-2"]
    assert known[(3186, "1627-09-03")] == ["session-3186-num-3"]


def test_direct_sessions_is_the_key_set_of_direct_session_ids():
    flat = _flat([(3186, "1627-09-02")])

    assert direct_sessions(flat) == set(direct_session_ids(flat))


def test_nearest_recovery_candidates_returns_nearest_offset_within_window():
    known = direct_session_ids(_flat([(3186, "1627-09-04"), (3186, "1627-09-09")]))
    period = pd.Period("1627-09-02", freq="D")

    hit = nearest_recovery_candidates(3186, period, known, offsets=WIDE_WINDOW_OFFSETS)

    assert hit == (2, ["session-3186-num-1"])


def test_nearest_recovery_candidates_none_outside_window():
    known = direct_session_ids(_flat([(3186, "1627-09-20")]))
    period = pd.Period("1627-09-02", freq="D")

    assert nearest_recovery_candidates(3186, period, known, offsets=WIDE_WINDOW_OFFSETS) is None


def test_nearest_recovery_offset_still_works_against_direct_session_ids_dict():
    """nearest_recovery_offset only needs membership-by-key, so it accepts
    either direct_sessions' set or direct_session_ids' dict."""
    known = direct_session_ids(_flat([(3186, "1627-09-04")]))
    period = pd.Period("1627-09-02", freq="D")

    assert nearest_recovery_offset(3186, period, known) == 2

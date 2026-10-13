"""remediation_window_run_log helpers (no disk write)."""

from __future__ import annotations

from sequence_graph.remediation_run_log import (
    log_bake,
    log_hard_pin_promote,
    log_hard_recalibrate,
    log_overflow_apply,
)


def test_log_helpers_shape_without_io(monkeypatch):
    captured: list[dict] = []

    def fake_append(row):
        captured.append(row)
        return row

    monkeypatch.setattr(
        "sequence_graph.remediation_run_log.append_run", fake_append
    )

    log_hard_recalibrate([
        {
            "record_type": "meta",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
            "detected_lag_lo": "1626-07-03",
            "detected_lag_hi": "1626-09-13",
            "n_lag_days": 27,
            "median_delta": 8,
            "n_hard_active": 17,
            "n_hard_vs_production_shift": 15,
            "n_literal_matched": 17,
            "n_literal_tried": 17,
        },
        {"record_type": "dp_handoff", "status": "dp1_ok"},
    ])
    assert captured[-1]["tool"] == "hard_recalibrate"
    assert captured[-1]["n_hard_active"] == 17

    log_bake([
        {
            "record_type": "meta",
            "window_id": "seed_3185_sep_oct",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
            "n_stages_present": 6,
        },
        {
            "record_type": "summary",
            "n_stages_present": 6,
            "n_gap_brackets": 57,
            "n_residual_rows": 78,
            "gate": "PASS",
            "residual_by_kind": {"unsynced_bracket": 57},
        },
    ])
    assert captured[-1]["gate"] == "PASS"
    assert captured[-1]["n_stages_present"] == 6

    log_overflow_apply([
        {
            "record_type": "meta",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
            "n_overflow_in_hard_window": 2,
            "n_clean_split": 0,
            "n_needs_human_cuts": 2,
            "claimant_match_rate": 0.5,
            "order_match_rate": 0.5,
            "n_lumped_deletion_sum": 7,
            "gate": "FAIL_OR_THIN",
        },
        {"record_type": "summary", "gate": "FAIL_OR_THIN", "next": "review"},
    ])
    assert captured[-1]["tool"] == "overflow_align_apply"

    log_hard_pin_promote([
        {
            "record_type": "meta",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
        },
        {
            "record_type": "inherit_summary",
            "n_rows": 233,
            "verdicts": {"shift": 176, "no_hard_date": 57},
        },
        {
            "record_type": "summary",
            "n_wire_edges": 17,
            "n_shift": 15,
            "n_new_pin": 2,
            "n_agree": 0,
            "monotone_ok": True,
            "before_slice_separated": 142,
            "after_slice_separated": 142,
            "delta_slice_separated": 0,
            "n_inherit_rows": 233,
            "gate": "PASS",
            "next": "wire",
        },
    ])
    assert captured[-1]["tool"] == "hard_pin_promote"
    assert captured[-1]["n_wire_edges"] == 17
    assert captured[-1]["n_inherit_rows"] == 233

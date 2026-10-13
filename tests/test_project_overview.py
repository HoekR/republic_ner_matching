"""Unit tests for project_overview helpers — no corpus I/O."""

from __future__ import annotations

from scripts.project_overview import (
    RETIRED_HARD_STRUCTURAL_NO_HTR,
    _inventory_id_str,
    _session_of_flat_id,
    _tick,
    format_overview,
)


def test_inventory_id_str_normalises_float() -> None:
    assert _inventory_id_str(3185.0) == "3185"
    assert _inventory_id_str("3186") == "3186"
    assert _inventory_id_str(None) == ""


def test_session_of_flat_id() -> None:
    assert _session_of_flat_id("session-3185-num-12-resolution-3") == "session-3185-num-12"
    assert _session_of_flat_id("session-3185-num-12#p0") == "session-3185-num-12"


def test_format_overview_marks_all_met() -> None:
    rows = [
        {
            "record_type": "meta",
            "source": "cached",
            "ceiling": 11644,
            "phase1_ceiling": 11644,
            "phase1_separated": 9550,
            "phase1_residual": 2094,
            "main_series_rows": 14240,
            "main_series_missing_htr_rows": 0,
            "hard_structural_nihil_k_e": 127,
            "main_series_ceiling_session_resolved": 12048,
            "main_series_theoretical_max_separated": 14113,
            "split_unlock_pigeonhole": 2065,
            "split_unlock_pigeonhole_days": 387,
            "split_unlock_collision": 3482,
            "displaced_recovered_into_ceiling_k_e": 856,
            "retired_hard_structural_no_htr": RETIRED_HARD_STRUCTURAL_NO_HTR,
            "separated_share_of_session_ceiling": 0.7927,
            "separated_share_of_theoretical_max": 0.6767,
            "optimum_depends_on_splitting": True,
            "n_separated": 9550,
            "separated_share_of_ceiling": 0.82,
            "n_solid_days": 799,
            "n_days": 1594,
            "invariant_passed": True,
            "n_violations": 0,
            "n_nihil_days": 127,
            "all_criteria_met": True,
            "active_focus": "All four MET.",
            "plan_next": "Phase 2 residual typology",
            "corpus_scope_last_date": "1630-05-14",
        },
        {
            "record_type": "criterion",
            "id": "global_primary",
            "label": "Global primary ≥ 50% of ceiling",
            "value": "9,550 = 82.0%",
            "met": True,
        },
        {
            "record_type": "criterion",
            "id": "global_stretch",
            "label": "Global stretch ≥ 75% of ceiling",
            "value": "9,550 = 82.0%",
            "met": True,
        },
        {
            "record_type": "criterion",
            "id": "global_spans",
            "label": "Global spans ≥ 6 / ≥ 180d (gap=2)",
            "value": "9 spans / 445 days",
            "met": True,
        },
        {
            "record_type": "criterion",
            "id": "local",
            "label": "Local ≥ 50% of inventory ceiling (3185–3189)",
            "value": "5/5 inventories",
            "met": True,
        },
        {
            "record_type": "gap_summary",
            "gap": 2,
            "spans_at_30": 9,
            "days_covered": 445,
            "criterion_met": True,
            "longest": 82,
        },
    ]
    text = format_overview(rows)
    assert "Phase-1 all four: MET" in text
    assert "Optimum depends on splitting" in text
    assert "session-resolved): 12,048" in text
    assert "theoretical max 14,113" in text
    assert "hard structural (nihil only): 127" in text
    assert "retired 'no HTR'" in text
    assert "5,590" in text
    assert "no HTR):" not in text  # old label must not appear
    assert _tick(True) == "MET"
    assert "9 spans / 445 days" in text
    assert "Phase 2 residual typology" in text

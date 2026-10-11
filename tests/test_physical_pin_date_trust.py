"""Date-trust filtering for staged physical pins — by calendar date only."""

from __future__ import annotations

from sequence_graph.physical_pin_shift import (
    apply_date_trust_to_proposals,
    new_bracket_gaps,
)


def test_trust_by_date_not_session() -> None:
    proposals = [
        {
            "record_type": "proposal",
            "date": "1626-03-27",
            "verdict": "shift",
            "proposed_session": "session-3185-num-57",
            "gate_eligible": True,
        },
        {
            "record_type": "proposal",
            "date": "1626-01-04",
            "verdict": "ambiguous_physical",
            "proposed_session": None,
            "gate_eligible": False,
        },
        {
            "record_type": "proposal",
            "date": "1626-08-20",
            "verdict": "shift",
            "proposed_session": "session-3185-num-99",
            "gate_eligible": True,
        },
    ]
    out = apply_date_trust_to_proposals(
        proposals,
        approved={"1626-03-27", "1626-01-04"},
        rejected={"1626-08-20"},
    )
    by_date = {r["date"]: r for r in out}
    assert by_date["1626-03-27"]["date_trust"] == "approved"
    assert by_date["1626-03-27"]["trust_gate_eligible"] is True
    # approved but ambiguous → still not override-eligible
    assert by_date["1626-01-04"]["date_trust"] == "approved"
    assert by_date["1626-01-04"]["trust_gate_eligible"] is False
    assert by_date["1626-08-20"]["date_trust"] == "rejected"
    assert by_date["1626-08-20"]["trust_gate_eligible"] is False
    assert by_date["1626-08-20"]["gate_eligible"] is False


def test_unreviewed_not_eligible() -> None:
    proposals = [
        {
            "record_type": "proposal",
            "date": "1627-01-01",
            "verdict": "shift",
            "proposed_session": "session-3186-num-1",
            "gate_eligible": True,
        }
    ]
    out = apply_date_trust_to_proposals(
        proposals, approved=set(), rejected=set()
    )
    assert out[0]["date_trust"] == "unreviewed"
    assert out[0]["trust_gate_eligible"] is False


def test_new_bracket_gaps_detects_geometry_change() -> None:
    before = [
        {
            "inventory": "3185",
            "anchor_lo_session": "session-3185-num-55",
            "anchor_hi_session": "session-3185-num-56",
            "calendar_lo": "1626-03-26",
            "calendar_hi": "1626-03-27",
        }
    ]
    after = [
        {
            "inventory": "3185",
            "anchor_lo_session": "session-3185-num-55",
            "anchor_hi_session": "session-3185-num-57",
            "calendar_lo": "1626-03-26",
            "calendar_hi": "1626-03-27",
        }
    ]
    new = new_bracket_gaps(before, after)
    assert len(new) == 1
    assert new[0]["anchor_hi_session"] == "session-3185-num-57"

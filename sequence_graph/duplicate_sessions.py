"""Resolve duplicate-claimed sessions into located splits -- proposals with a MACHINE GATE.

`scripts/s6_duplicate_session_date_headings.py` already has the mechanism (67 sessions claimed by
more than one enriched date; 25 get a verified shared split). This module persists that output and
marks proposals **gate-eligible or not by automatic checks**, not by human pin review.

User, 2026-10-09: persist the map half; do not rewrite PINNED_TO / production pins. Later same day:
will not review all proposed pins -- accept/reject by machine gate; report aggregates only.

Gate (all must pass for any shared row to be `gate_eligible`):
1. Held-out: `session-3185-num-56` verifies an embedded `1626-03-28` heading (Track S precondition).
2. Control: single-claimant 3187 sessions, given a distant (+40d) fake claimant date, must not
   yield `shared*` (adjacent-day fakes under-detect real shared sessions, not channel noise).
3. Structural: every `shared*` proposal partitions paragraphs (2-date) or marks earlier dates
   undivided (3+).

Does **not** touch `sequence_graph` PINNED_TO edges or any production placement.

Usage:
    uv run python -m sequence_graph.duplicate_sessions --build
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, is_main_series, scope_meta

DATASET = "duplicate_session_date_splits"
CONTROL_INVENTORY = "3187"
CONTROL_N = 20
CONTROL_SEED = 20261009
# Adjacent-day fakes are the wrong control: single-claimant sessions often still carry the
# next day's heading (under-claimed shared), which is a true positive for the channel, not a
# false split. A distant same-year date should not appear in the session text.
CONTROL_FAKE_OFFSET_DAYS = 40
HELD_OUT_SESSION = "session-3185-num-56"
HELD_OUT_DATE = "1626-03-28"


def _proposed_ranges(
    dates: list[str], total_paragraphs: int | None, split: int | None
) -> dict[str, Any] | None:
    """Per-claimant paragraph range implied by classify()'s split. None when nothing to propose.

    Exactly 2 dates: complete 2-way split. 3+: earlier dates share one range, named undivided.
    """
    if split is None or total_paragraphs is None:
        return None
    dates = sorted(dates)
    resolved_date = dates[-1]
    earlier_dates = dates[:-1]
    return {
        resolved_date: {"paragraph_range": [split, total_paragraphs - 1], "undivided_among": []},
        **{
            date: {
                "paragraph_range": [0, split - 1],
                "undivided_among": [d for d in earlier_dates if d != date],
            }
            for date in earlier_dates
        },
    }


def _adjacent_date(iso_date: str, delta_days: int = 1) -> str:
    return str(pd.Period(iso_date, freq="D") + delta_days)


def _structural_ok(record: dict[str, Any]) -> bool:
    ranges = record.get("proposed_ranges")
    if not ranges or not record["verdict"].startswith("shared"):
        return False
    split = record.get("split_at_paragraph")
    total = record.get("paragraphs")
    if split is None or total is None or not (0 <= split < total):
        return False
    if len(record["dates"]) == 2:
        ordered = sorted(v["paragraph_range"] for v in ranges.values())
        (lo1, hi1), (lo2, hi2) = ordered
        return lo1 == 0 and hi1 + 1 == lo2 and hi2 == total - 1
    # 3+: latest alone; earlier share identical range and undivided_among each other
    latest = sorted(record["dates"])[-1]
    earlier = sorted(record["dates"])[:-1]
    if ranges[latest]["undivided_among"]:
        return False
    shared_range = ranges[earlier[0]]["paragraph_range"]
    return all(
        ranges[d]["paragraph_range"] == shared_range
        and set(ranges[d]["undivided_among"]) == set(earlier) - {d}
        for d in earlier
    )


def held_out_ok(by_session: dict[str, list[dict[str, Any]]]) -> bool:
    """Held-out Track S precondition: num-56 must verify 1626-03-28 inside its text."""
    from scripts.s6_duplicate_session_date_headings import find_headings

    paragraphs = by_session.get(HELD_OUT_SESSION) or []
    if not paragraphs:
        return False
    hits = find_headings(paragraphs, HELD_OUT_DATE)
    return any(h["verified"] for h in hits)


def control_false_shared(
    by_session: dict[str, list[dict[str, Any]]],
    concordance: pd.DataFrame,
    *,
    n: int = CONTROL_N,
    seed: int = CONTROL_SEED,
    fake_offset_days: int = CONTROL_FAKE_OFFSET_DAYS,
) -> dict[str, Any]:
    """Single-claimant 3187 sessions + distant fake date must not produce shared* splits."""
    from scripts.s6_duplicate_session_date_headings import classify, duplicate_claims

    duplicates = set(duplicate_claims(concordance))
    pairs = (
        concordance[["enriched_date", "resolved_session_id"]]
        .dropna()
        .drop_duplicates()
    )
    pairs = pairs[pairs["resolved_session_id"].astype(str) != ""]
    single = (
        pairs.groupby("resolved_session_id")["enriched_date"]
        .agg(list)
        .loc[lambda s: s.map(len) == 1]
    )
    candidates: list[tuple[str, str]] = []
    for session, dates in single.items():
        session = str(session)
        if session in duplicates or not is_main_series(session):
            continue
        if CONTROL_INVENTORY not in session:
            continue
        date = str(dates[0])[:10]
        fake = _adjacent_date(date, fake_offset_days)
        if not in_scope(date) or not in_scope(fake):
            continue
        if session not in by_session:
            continue
        candidates.append((session, date))
    candidates.sort()
    rng = pd.Series(range(len(candidates)), dtype=int)
    order = rng.sample(frac=1.0, random_state=seed).tolist()
    sample = [candidates[i] for i in order[:n]]

    false_shared: list[str] = []
    for session, date in sample:
        fake_dates = sorted([date, _adjacent_date(date, fake_offset_days)])
        result = classify(session, fake_dates, by_session)
        if result["verdict"].startswith("shared"):
            false_shared.append(session)

    return {
        "control_inventory": CONTROL_INVENTORY,
        "control_fake_offset_days": fake_offset_days,
        "control_n_requested": n,
        "control_n": len(sample),
        "control_false_shared": len(false_shared),
        "control_false_shared_sessions": false_shared,
        "control_pass": len(false_shared) == 0 and len(sample) == n,
    }


def gate_duplicate_session_splits(
    records: list[dict[str, Any]],
    by_session: dict[str, list[dict[str, Any]]],
    concordance: pd.DataFrame,
) -> dict[str, Any]:
    """Aggregate machine gate. User does not review the proposal list."""
    held = held_out_ok(by_session)
    control = control_false_shared(by_session, concordance)
    shared = [r for r in records if r["verdict"].startswith("shared")]
    structural_failures = [r["session"] for r in shared if not _structural_ok(r)]
    structural_pass = len(structural_failures) == 0 and len(shared) > 0
    gate_pass = bool(held and control["control_pass"] and structural_pass)
    return {
        "record_type": "gate",
        "gate_pass": gate_pass,
        "held_out_session": HELD_OUT_SESSION,
        "held_out_date": HELD_OUT_DATE,
        "held_out_ok": held,
        "n_total": len(records),
        "n_proposed_shared": len(shared),
        "n_undecided": len(records) - len(shared),
        "n_gate_eligible": len(shared) if gate_pass else 0,
        "n_abstain": len(records) if not gate_pass else len(records) - len(shared),
        "structural_pass": structural_pass,
        "structural_failures": structural_failures,
        **control,
        "review_policy": (
            "machine_gate_only -- user will not review all proposed pins; "
            "report aggregates, not a review queue"
        ),
        **scope_meta(),
    }


def resolve_duplicate_session_claims() -> list[dict[str, Any]]:
    """One record per duplicate-claimed session; proposed_ranges only on shared* verdicts."""
    from scripts.s6_duplicate_session_date_headings import (
        classify,
        duplicate_claims,
        session_paragraphs,
    )

    axis = load("paragraph_axis_1626_1630")
    by_session = session_paragraphs(axis)
    concordance = load("resolution_concordance_1626_1630")
    claims = duplicate_claims(concordance)

    records: list[dict[str, Any]] = []
    for session, dates in sorted(claims.items()):
        # Fail closed on out-of-scope claimant dates.
        if not all(in_scope(d) for d in dates):
            continue
        if not is_main_series(session):
            continue
        result = classify(session, dates, by_session)
        proposed_ranges = (
            _proposed_ranges(dates, result.get("paragraphs"), result.get("split_at_paragraph"))
            if result["verdict"].startswith("shared")
            else None
        )
        records.append({"session": session, **result, "proposed_ranges": proposed_ranges})
    return records


def save_duplicate_session_date_splits() -> dict[str, Any]:
    """Persist proposals + gate summary. No PINNED_TO / production mutation."""
    from scripts.s6_duplicate_session_date_headings import session_paragraphs

    axis = load("paragraph_axis_1626_1630")
    by_session = session_paragraphs(axis)
    concordance = load("resolution_concordance_1626_1630")
    records = resolve_duplicate_session_claims()
    gate = gate_duplicate_session_splits(records, by_session, concordance)
    eligible = bool(gate["gate_pass"])
    for record in records:
        shared = record["verdict"].startswith("shared") and record["proposed_ranges"] is not None
        record["gate_eligible"] = bool(shared and eligible)

    payload = [gate, *records]
    save_semi_structured(
        payload,
        logical_name=DATASET,
        script="sequence_graph.duplicate_sessions",
        description=(
            "Duplicate-session split PROPOSALS with machine gate (not a human review queue). "
            "First record is record_type=gate (aggregates only). Remaining rows: one per "
            "in-scope main-series session claimed by >1 enriched date; shared* rows carry "
            "proposed_ranges and gate_eligible. Does not touch PINNED_TO or production placement. "
            "User 2026-10-09: persist map half; will not review all proposed pins."
        ),
        parent_sources=[
            "resolution_concordance_1626_1630",
            "paragraph_axis_1626_1630",
        ],
    )
    return gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    if not args.build:
        parser.print_help()
        return

    gate = save_duplicate_session_date_splits()
    print(
        f"saved {DATASET}: gate_pass={gate['gate_pass']} "
        f"proposed={gate['n_proposed_shared']} eligible={gate['n_gate_eligible']} "
        f"undecided={gate['n_undecided']} abstain={gate['n_abstain']}"
    )
    print(
        f"  held_out_ok={gate['held_out_ok']} "
        f"control_false_shared={gate['control_false_shared']}/{gate['control_n']} "
        f"structural_pass={gate['structural_pass']}"
    )
    records = [r for r in load(DATASET) if r.get("record_type") != "gate"]
    print("verdicts:")
    for verdict, count in Counter(r["verdict"] for r in records).most_common():
        print(f"  {verdict:<28}{count}")


if __name__ == "__main__":
    main()

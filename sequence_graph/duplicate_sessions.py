"""Resolve duplicate-claimed sessions into a located split -- a reviewable PROPOSAL set, persisted.

`scripts/s6_duplicate_session_date_headings.py` already has the real mechanism -- 67 sessions
claimed by more than one enriched date, each date's own embedded heading located via fuzzy
search, exact day-numeral parse, and a weekday cross-check -- but its own docstring states
"Diagnostic only: no dataset write, no manifest entry, no placement or status change." The 25/67
"shared, split located" verdicts it produces were never persisted anywhere.

**User, 2026-10-09, after finding this while auditing a different duplicate claim
(`session-3186-num-46`, PINNED_TO both `1627-03-11` and `1627-03-13` directly from
`resolved_session_id`): "i think it should resolve this."** then, scoping it down: **"Continue —
but only the map half. Persist the 25 located splits as a reviewable proposal set; pause before
rewriting graph edges or production pins."** This module runs the existing mechanism for real
(not diagnostic-only) and persists its output as a hand-drawable worklist -- a proposed cut,
located by an already-verified heading, for each of the 25 shared sessions. It does **not** touch
`sequence_graph`'s own graph, `PINNED_TO`, or any production placement -- that wiring is a
separate, deliberately deferred step, pending review of this proposal set.

**Deliberately does NOT modify `s6_duplicate_session_date_headings.py` itself** -- reuses its
`duplicate_claims`/`classify`/`session_paragraphs` functions directly rather than forking them,
the same reuse discipline every other `add_*` function in this package follows. The script keeps
its own "diagnostic only" contract for whoever runs it standalone; this module only adds
persistence on top of it.

**Honest about what a 2-way split can and cannot say for a 3+-date session, stated in the
persisted record itself, not just in prose.** `classify()` locates one split: the LATEST
claimant's confirmed start, separating it from everything earlier. For a session with exactly 2
claimant dates this is a full proposal. For 3+ (e.g. `session-3185-num-13`, claimed by three
dates), the earlier dates would be left undivided among each other -- a future reviewer or the
(not-yet-built) graph-wiring step must not silently assume an even split or pick one.

Usage:
    uv run python -m sequence_graph.duplicate_sessions --build
"""

from __future__ import annotations

import argparse

from data_io import load, save_semi_structured

DATASET = "duplicate_session_date_splits"


def _proposed_ranges(dates: list[str], total_paragraphs: int | None, split: int | None) -> dict | None:
    """The per-claimant paragraph range `classify()`'s split implies -- computed and stored as
    part of the PROPOSAL itself, so a reviewer (or a future, separate graph-wiring step) reads a
    ready-made range rather than re-deriving it. `None` when there is nothing to propose.

    For exactly 2 claimant dates this is a complete 2-way split. For 3+, the earlier dates share
    one range `undivided` among themselves -- named explicitly, never silently divided evenly or
    assigned to one of them.
    """
    if split is None or total_paragraphs is None:
        return None
    dates = sorted(dates)
    resolved_date = dates[-1]  # classify()'s own convention: the latest claimant is the one located
    earlier_dates = dates[:-1]
    return {
        resolved_date: {"paragraph_range": [split, total_paragraphs - 1], "undivided_among": []},
        **{
            date: {"paragraph_range": [0, split - 1], "undivided_among": [d for d in earlier_dates if d != date]}
            for date in earlier_dates
        },
    }


def resolve_duplicate_session_claims() -> list[dict]:
    """One record per duplicate-claimed session, from the existing heading-disambiguation
    mechanism, run for real rather than printed and discarded. `proposed_ranges` is populated
    only where `verdict` starts with `"shared"` -- the 25 of 67 a heading actually located."""
    from scripts.s6_duplicate_session_date_headings import classify, duplicate_claims, session_paragraphs

    axis = load("paragraph_axis_1626_1630")
    by_session = session_paragraphs(axis)
    concordance = load("resolution_concordance_1626_1630")
    claims = duplicate_claims(concordance)

    records = []
    for session, dates in sorted(claims.items()):
        result = classify(session, dates, by_session)
        proposed_ranges = (
            _proposed_ranges(dates, result.get("paragraphs"), result.get("split_at_paragraph"))
            if result["verdict"].startswith("shared") else None
        )
        records.append({"session": session, **result, "proposed_ranges": proposed_ranges})
    return records


def save_duplicate_session_date_splits() -> int:
    """Persists the proposal set. Does not touch `sequence_graph`'s graph, `PINNED_TO`, or any
    production placement -- review this dataset first; wiring it in is a separate, later step."""
    records = resolve_duplicate_session_claims()
    save_semi_structured(
        records, logical_name=DATASET, script="sequence_graph.duplicate_sessions",
    )
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()

    if args.build:
        n = save_duplicate_session_date_splits()
        print(f"saved {n} duplicate-session records to {DATASET} (reviewable proposal set, "
              f"not applied to the graph)")
        from collections import Counter

        records = load(DATASET)
        verdicts = Counter(r["verdict"] for r in records)
        for verdict, count in verdicts.most_common():
            print(f"  {verdict:<28}{count}")

        print("\nproposed cuts (verdict starts with 'shared'):")
        for record in records:
            if not record["verdict"].startswith("shared"):
                continue
            print(f"  {record['session']:<24}{record['dates']} -> {record['proposed_ranges']}")


if __name__ == "__main__":
    main()

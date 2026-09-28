#!/usr/bin/env python3
"""Day-level status resolution (Step 4B of docs/CANDIDATE_SCORING_AND_CONCORDANCE.md).

Joins the session-date ledger, S4f human-approved mappings (once that review
completes), and Step 4A candidate scoring into one row per ledger key with a
single ``day_status`` and optional ``resolved_session_id``, using this
precedence: human-approved mapping > confident automatic candidate
(``not low_confidence and not nihil_actum``) > ``nihil_actum`` flag > ledger
``N`` with no HTR session anywhere within +/-14 days (``missing_htr``) >
``uncertain``. ``T``/``E`` ledger rows pass through as ``resolved_auto``
directly, no scoring needed.

``N``-status rows only carry ledger-computed +/-1-day candidate columns
(from S4c); ``analyze_n_status_gaps.py`` separately found that 753 of the
3,197 ``N`` rows (23.6%) do have a same-inventory HTR session at a wider
+/-2..+/-14-day offset that nothing downstream ever looked up. Labeling all
3,197 as ``missing_htr`` would overstate the structural gap Step 1
documented (2,444 rows, 49.7% of the ledger) by conflating it with rows that
are merely unscored. This module reuses ``analyze_n_status_gaps``'s own
``direct_sessions``/``nearest_recovery_offset`` helpers to make that split
per row: only rows with no recovery at any offset become ``missing_htr``;
the remainder falls to ``uncertain`` unless ``s4_candidate_scoring_predictions``
already carries a confident score for it.

The window-widen follow-up (``scripts/s4_candidate_scoring_batch.py``,
+/-2..+/-7 days) now actually scores the front-loaded slice of these
recoverable rows, so no code change was needed here: the existing
``candidate_scores.get(key)`` check below already runs before the
``N``-specific fallback and picks up a confident wide-window match the same
way it picks up an ``A``/``X``/``-1``/``+1``/``?`` one. Rows recoverable only
past +/-7 days, or scored but not confident, still fall through to
``uncertain``/``missing_htr`` as before.

``deduplicate_session_claims`` runs over ``candidate_scores`` before any row
is resolved, enforcing a cross-date uniqueness policy on
``top_candidate_session_id`` (docs/DECISIONS.md 2026-09-23 "resolved_session_id
has no cross-date uniqueness constraint" -- two different enriched dates could
independently claim the identical HTR session, corroborated as
disproportionately ``weak_separation``-clustered by the follow-up crosstab
the same day). Best ``combined_score`` wins each session; a losing row falls
back to its own next-ranked confident candidate, or to ``low_confidence``
(-> ``uncertain``) once none remain. ``T``/``E`` ledger-direct rows are out of
scope for this pass -- they are not ranked candidate picks, and the traced
collision mechanism is specific to ``resolve_row``'s candidate-scoring branch.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from analyze_n_status_gaps import direct_sessions, nearest_recovery_offset
from data_io import load, load_jsonl, resolve, save_semi_structured

LEDGER_DATASET = "session_date_status_1626_1630"
FLAT_DATASET = "resolutions_flat"
CANDIDATE_SCORES_DATASET = "s4_candidate_scoring_predictions"
APPROVED_MAPPINGS_DATASET = "s4_session_date_mapping_predictions_approved"
OUTPUT_DATASET = "s4_day_status_resolution"
DIRECT_STATUSES = {"T": "trusted_session_ids", "E": "exact_date_session_ids"}


def _first(value: Any) -> str | None:
    """Return the first element of a ledger candidate-id list column, if any."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not value:
        return None
    return str(value[0])


def load_approved_mappings() -> dict[str, dict[str, Any]]:
    """Return approved human selections keyed by session_date_key, if S4f review has run."""
    path = Path(resolve(APPROVED_MAPPINGS_DATASET))
    if not path.exists():
        return {}
    return {
        str(record["session_date_key"]): record
        for record in load_jsonl(path)
        if record.get("review_status") == "approved"
    }


def deduplicate_session_claims(candidate_scores: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Enforce a cross-date uniqueness policy on confident candidate-scoring picks.

    ``resolve_row`` used to take each row's ``top_candidate_session_id`` at
    face value, so two different enriched dates could independently resolve
    to the identical HTR session (68/1,053 resolved_auto sessions corpus-wide,
    docs/DECISIONS.md 2026-09-23 "resolved_session_id has no cross-date
    uniqueness constraint"). Policy: best-``combined_score``-wins per session,
    globally across all rows; every other row claiming that session falls
    back to its own next-best candidate in ``ranked_candidates`` (already
    scored, no rescoring needed), or to ``low_confidence`` (-> ``uncertain``
    in ``resolve_row``) once it has no confident candidate left.

    Implemented as a single greedy pass over all (row, candidate) pairs
    sorted by descending score: the highest-scoring pair claims its row and
    its session; any later pair naming an already-claimed row or session is
    skipped, which is exactly the fallback-to-next-candidate behaviour since
    that row's next-ranked pair appears later in the same sorted list.
    """
    resolved = {key: dict(record) for key, record in candidate_scores.items()}
    pairs = [
        (entry["combined_score"], key, entry)
        for key, record in resolved.items()
        for entry in (record.get("ranked_candidates") or [])
        if not entry.get("low_confidence")
    ]
    pairs.sort(key=lambda item: item[0], reverse=True)

    claimed_rows: set[str] = set()
    claimed_sessions: set[str] = set()
    had_confident_candidate: set[str] = {key for _, key, _ in pairs}
    for _, key, entry in pairs:
        if key in claimed_rows or entry["session_id"] in claimed_sessions:
            continue
        claimed_rows.add(key)
        claimed_sessions.add(entry["session_id"])
        resolved[key].update(
            {
                "top_candidate_session_id": entry["session_id"],
                "entity_overlap_score": entry["entity_overlap_score"],
                "dense_similarity_score": entry["dense_similarity"],
                "combined_score": entry["combined_score"],
                "low_confidence": False,
            }
        )

    for key in had_confident_candidate - claimed_rows:
        resolved[key].update({"top_candidate_session_id": None, "low_confidence": True})

    return resolved


def fold_in_candidates(ledger: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Detect ``?``-status rows whose content likely got folded into one immediate
    neighbor's session rather than genuinely missing.

    Repeatedly proposed (PLAN.md/docs/DECISIONS.md, 2026-09-23 and earlier) but
    never previously wired into ``resolve_row``: compare a neighbor session's
    total paragraph capacity (``exact_date_paragraph_count``, session-wide, not
    date-scoped) against that neighbor's own expected resolution count
    (``enriched_count``). Leftover capacity (``slack``) that covers this row's
    own ``enriched_count`` is evidence the neighbor session also holds this
    date's resolutions.

    Scoped to the unambiguous case only: exactly one previous-day and one
    next-day candidate session (adjacent session numbers, i.e. no genuinely
    missing physical page). Wider gaps involve real candidate ambiguity this
    check isn't built for. If both neighbors show sufficient slack, the row is
    left for manual review rather than guessed.

    Two gap rows can independently point at the same neighbor session from
    opposite sides (e.g. both 1626-02-22 and 1626-02-24 folding into
    1626-02-23's session). A row is only resolved once every row sharing that
    neighbor still fits within its single, shared slack budget -- otherwise
    every claimant on that session is left uncertain rather than guessed.
    """
    indexed = ledger.set_index(["inventory_id", "enriched_date"])
    session_slack: dict[str, int] = {}
    claims: list[tuple[str, str, str, int]] = []

    uncertain = ledger.loc[ledger["status_code"] == "?"]
    for row in uncertain.itertuples(index=False):
        prev_ids = list(row.previous_day_session_ids)
        next_ids = list(row.next_day_session_ids)
        if len(prev_ids) != 1 or len(next_ids) != 1:
            continue

        row_period = pd.Period(row.enriched_date, freq="D")
        viable: dict[str, str] = {}
        for side, session_id, offset in (("previous", prev_ids[0], -1), ("next", next_ids[0], 1)):
            neighbor_date = str(row_period + offset)
            try:
                neighbor = indexed.loc[(row.inventory_id, neighbor_date)]
            except KeyError:
                continue
            if neighbor["status_code"] not in DIRECT_STATUSES:
                continue
            slack = session_slack.setdefault(
                session_id, int(neighbor["exact_date_paragraph_count"]) - int(neighbor["enriched_count"])
            )
            if slack >= int(row.enriched_count):
                viable[side] = session_id

        if len(viable) == 1:
            side, session_id = next(iter(viable.items()))
            claims.append((session_id, str(row.session_date_key), side, int(row.enriched_count)))

    demand: dict[str, int] = {}
    for session_id, _key, _side, need in claims:
        demand[session_id] = demand.get(session_id, 0) + need

    results: dict[str, dict[str, Any]] = {}
    for session_id, key, side, _need in claims:
        if demand[session_id] <= session_slack[session_id]:
            results[key] = {
                "resolved_session_id": session_id,
                "fold_in_side": side,
                "fold_in_slack": session_slack[session_id],
            }
    return results


def n_row_recovery_offsets(ledger: pd.DataFrame, known_sessions: set[tuple[int, str]]) -> dict[str, int | None]:
    """Return each N-status row's nearest same-inventory HTR offset within +/-14 days, if any."""
    n_rows = ledger.loc[ledger["status_code"] == "N", ["session_date_key", "inventory_id", "enriched_date"]]
    offsets: dict[str, int | None] = {}
    for row in n_rows.itertuples(index=False):
        period = pd.Period(row.enriched_date, freq="D")
        offsets[str(row.session_date_key)] = nearest_recovery_offset(int(row.inventory_id), period, known_sessions)
    return offsets


def resolve_row(
    row: dict[str, Any],
    approved: dict[str, dict[str, Any]],
    candidate_scores: dict[str, dict[str, Any]],
    n_recovery_offsets: dict[str, int | None],
    fold_in: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve one ledger row's day_status/resolved_session_id per the Step 4B precedence."""
    key = str(row["session_date_key"])
    base = {
        "session_date_key": key,
        "inventory_id": int(row["inventory_id"]),
        "enriched_date": str(row["enriched_date"]),
        "ledger_status_code": row["status_code"],
    }

    direct_column = DIRECT_STATUSES.get(str(row["status_code"]))
    if direct_column:
        return {
            **base,
            "day_status": "resolved_auto",
            "resolved_session_id": _first(row[direct_column]),
            "resolution_source": "ledger_direct",
        }

    decision = approved.get(key)
    if decision is not None:
        return {
            **base,
            "day_status": "resolved_manual",
            "resolved_session_id": decision.get("selected_session_id"),
            "resolution_source": "s4f_human_decision",
        }

    score = candidate_scores.get(key)
    if score is not None:
        if score.get("nihil_actum"):
            return {**base, "day_status": "nihil_actum", "resolved_session_id": None, "resolution_source": "candidate_scoring"}
        if score.get("top_candidate_session_id") and not score.get("low_confidence"):
            return {
                **base,
                "day_status": "resolved_auto",
                "resolved_session_id": score["top_candidate_session_id"],
                "resolution_source": "candidate_scoring",
            }

    if str(row["status_code"]) == "N":
        offset = n_recovery_offsets.get(key)
        if offset is None:
            return {**base, "day_status": "missing_htr", "resolved_session_id": None, "resolution_source": "ledger_n_status_no_recovery"}
        # A wide-window candidate score that didn't clear the confidence floor
        # (score is not None here but failed the check above) is a distinct
        # case from a row past the +/-7-day window-widen band that was never
        # scored at all -- keep the two apart in the audit trail.
        source = "candidate_scoring_low_confidence" if score is not None else "ledger_n_status_recoverable_wider_window"
        return {
            **base,
            "day_status": "uncertain",
            "resolved_session_id": None,
            "resolution_source": source,
        }

    fold = (fold_in or {}).get(key)
    if fold is not None:
        return {
            **base,
            "day_status": "resolved_auto",
            "resolved_session_id": fold["resolved_session_id"],
            "resolution_source": "fold_in_recovered",
        }

    return {**base, "day_status": "uncertain", "resolved_session_id": None, "resolution_source": "no_confident_source"}


def main() -> None:
    ledger = load(LEDGER_DATASET)
    approved = load_approved_mappings()
    candidate_scores = {str(record["session_date_key"]): record for record in load(CANDIDATE_SCORES_DATASET)}
    candidate_scores = deduplicate_session_claims(candidate_scores)
    n_recovery_offsets = n_row_recovery_offsets(ledger, direct_sessions(load(FLAT_DATASET)))
    fold_in = fold_in_candidates(ledger)

    records = [
        resolve_row(row, approved, candidate_scores, n_recovery_offsets, fold_in)
        for row in ledger.sort_values(["inventory_id", "enriched_date"]).to_dict(orient="records")
    ]

    parents = [LEDGER_DATASET, CANDIDATE_SCORES_DATASET]
    if approved:
        parents.append(APPROVED_MAPPINGS_DATASET)
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, parent_sources=parents, script=__file__)

    print(f"Wrote {len(records)} day-status rows to {output}")
    print(f"Status distribution: {dict(Counter(record['day_status'] for record in records))}")
    if not approved:
        print(f"Note: {APPROVED_MAPPINGS_DATASET} not found yet -- resolved_manual is unused until S4f review completes.")


if __name__ == "__main__":
    main()

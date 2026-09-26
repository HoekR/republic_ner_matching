#!/usr/bin/env python3
"""Step 6 gate of plans/COLLISION_AVOIDANCE_TRACK.md -- the enriched<->HTR session offset.

Step 6 proposes aligning the *enriched sitting sequence* against the *HTR session
sequence* as sequences, replacing the current correspondence, which is a
**date-label lookup plus a +/-1-day candidate window** (session_date_status_1626_1630,
Steps 4a-4e). The step's own first deliverable is this diagnostic, and it is also
the gate: if the enriched<->HTR correspondence is overwhelmingly reachable within
that +/-1 window, Step 6 closes for the price of one run and Step 3 is next.

**Why a new measurement rather than an analogy.** Finding 1 of Step 6 cites
``s6b_session_fingerprint_match``: 494 of 1,059 content-verified sessions (46.6%)
sit more than one position from their label, offsets running to 13. But that is
measured **flat<->raw, both sides HTR**. It evidences the *mechanism* (session
labels drift far), not the enriched<->HTR gap itself. This script measures the
gap across the streams.

**Metric defined before method** (track guardrail, docs/SEGMENTATION_RESULTS.md
section 5). No tolerance-family metric anywhere; everything below is a count, a
share, or a calendar-day distance.

1. *Ordinal offset* -- the literal analogue of finding 1. Per inventory, rank the
   enriched sittings by date (excluding the 127 ``nihil_actum`` dates, which
   consume zero HTR sessions -- the hard skip constraint recorded under Step 6)
   and rank the axis flat sessions by ``flat_num``; for every sitting that the
   concordance resolves to a session, ``session_offset = htr_ordinal -
   enriched_ordinal``.

   **Read this one with its conflation stated.** Unlike flat<->raw, where both
   sequences index the same archival objects so a nonzero offset means
   mislabelling, here the two sequences have genuinely different lengths (1,467
   non-nihil sittings vs 1,316 axis sessions), so the offset also absorbs
   sittings whose HTR is simply absent. A large ordinal offset is therefore *not*
   by itself evidence of drift. The decisive quantities are 2 and 3.

2. *Bracket structure* -- the payoff sizing, and the part that is not confounded.
   Consecutive resolved sittings are pins. Between two pins, count the unresolved
   sittings (``n_e``) and the unclaimed axis sessions (``n_h``). A bracket with
   ``n_e == n_h >= 1`` is **determined**: monotonicity alone forces each
   unresolved sitting onto one session, with no new evidence and nothing to tune.
   ``n_e > n_h`` is a deficit (genuinely missing HTR), ``n_e < n_h`` a surplus.

3. *Forced-pairing date distance* -- the gate proper. In a determined bracket the
   i-th unresolved sitting pairs with the i-th unclaimed session. Report
   ``|enriched_date - session_date_label|`` in calendar days for those forced
   pairs. **A pair beyond one day is a correspondence the +/-1-day candidate
   window provably could not have found**, recovered here by order alone.

4. *No-insertion check at session level.* Step 6's design notes require verifying,
   not assuming, that an HTR session belonging to no enriched sitting does not
   occur -- the resolution-level claim was checked against gold and must not be
   carried over on faith. The case is an **interior** bracket with ``n_e == 0``
   and ``n_h >= 1``: claimed sessions on both sides, so an enriched sitting was
   available and claimed neither. Head and tail surpluses are *not* that case and
   are classed ``outside_enriched_span`` instead -- the enriched edition stops at
   1630-05-14 while the axis runs to 1630-12-31, so HTR past the end of the
   edition is a corpus-window fact, not an unmatched session.

Gate (thresholds fixed here, before the run):

- **PASS / build the aligner** if at least 25% of the unresolved sittings sit in
  determined brackets *and* at least half of the forced pairings are more than
  one calendar day from their date label. That combination says the mapping is
  recoverable by order and that the current window is what blocks it.
- **CLOSE Step 6** if forced pairings are overwhelmingly (>= 90%) within +/-1 day,
  i.e. the sequence view would reproduce what the label lookup already does.
- Anything else is INCONCLUSIVE and is reported as such rather than rounded to a
  verdict.

**Scope constraint (user, 2026-09-25): the enriched edition ends 1630-05-14, so
the alignment does not extend beyond that.** The axis runs to 1630-12-31 and
carries 2,284 paragraphs (10.6%) over 184 sessions past that date -- 180 in 3189,
4 in 4562. Those sessions are dropped from the stream before bracketing, and an
assertion checks that no sitting already resolves into them (currently 0, so the
constraint costs nothing today and guards against a widened fallback later). The
cut-off is read from the data rather than hardcoded, so it tracks the edition.

Diagnostic only: reads frozen artifacts, writes one dataset, changes no
placement. Inventory 4861 has no HTR in the axis at all and 4562 is the
anchor-starved outlier excluded from pooling by finding C; both are reported per
inventory rather than silently absorbed into the corpus totals.

Usage:
    uv run python -m scripts.session_offset_eval
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
OUTPUT_DATASET = "session_offset_eval"

NIHIL_STATUS = "nihil_actum"
CANDIDATE_WINDOW_DAYS = 1  # session_date_status_1626_1630's -1/+1/? candidate window

# Gate thresholds, fixed before the run (see module docstring).
MIN_DETERMINED_SHARE = 0.25
MIN_BEYOND_WINDOW_SHARE = 0.50
CLOSE_WITHIN_WINDOW_SHARE = 0.90


def day_distance(left: str, right: str) -> int:
    """Absolute calendar-day distance. pd.Period, never Timestamp: dates predate 1678."""
    return abs((pd.Period(left, freq="D") - pd.Period(right, freq="D")).n)


def enriched_sittings(concordance: pd.DataFrame) -> pd.DataFrame:
    """One row per enriched date: k_e, status, the session it claims, and its ordinal.

    Ordinals are assigned per inventory over the date-ordered sequence with
    ``nihil_actum`` dates dropped, because a nihil sitting consumes no HTR session
    and including it would shift every later ordinal by one.
    """
    per_date = (
        concordance.groupby("enriched_date")
        .agg(
            inventory_id=("inventory_id", "first"),
            status=("status", "first"),
            k_e=("enriched_id", "size"),
            resolved_session_id=("resolved_session_id", "first"),
        )
        .reset_index()
    )
    per_date["resolved_session_id"] = per_date["resolved_session_id"].fillna("").astype(str)
    per_date["is_nihil"] = per_date["status"] == NIHIL_STATUS
    per_date = per_date.sort_values(["inventory_id", "enriched_date"]).reset_index(drop=True)

    sittings = per_date.loc[~per_date["is_nihil"]].copy()
    sittings["enriched_ordinal"] = sittings.groupby("inventory_id").cumcount()
    sittings["is_resolved"] = sittings["resolved_session_id"].str.len() > 0
    return sittings


def htr_sessions(axis_records: list[dict[str, Any]]) -> pd.DataFrame:
    """One row per axis flat session: its date label, paragraph count, and ordinal.

    Ordered by ``flat_num`` on Step 1's finding 3 -- content-verified landmarks show
    zero non-monotone steps across 3185-3189, so flat order is archive order.
    """
    frame = pd.DataFrame(
        [{"date": record["date"], "flat_id": record["flat_id"]} for record in axis_records]
    )
    frame["session_id"] = frame["flat_id"].str.replace(r"-resolution-\d+$", "", regex=True)
    frame["inventory_id"] = frame["session_id"].str.extract(r"session-(\d+)-num-")[0].astype(int)
    frame["flat_num"] = frame["session_id"].str.extract(r"-num-(\d+)$")[0].astype(int)

    sessions = (
        frame.groupby(["inventory_id", "flat_num", "session_id"])
        .agg(session_date=("date", "first"), paragraph_count=("flat_id", "size"))
        .reset_index()
        .sort_values(["inventory_id", "flat_num"])
        .reset_index(drop=True)
    )
    sessions["htr_ordinal"] = sessions.groupby("inventory_id").cumcount()
    return sessions


def restrict_to_enriched_span(
    sessions: pd.DataFrame, enriched_end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop HTR sessions dated after the enriched edition ends, and re-rank the survivors.

    **Scope constraint (user, 2026-09-25): the enriched edition ends 1630-05-14, so do not
    extend beyond that.** The axis runs to 1630-12-31 and carries 2,284 paragraphs (10.6%)
    across 184 sessions past that date -- 180 in 3189 and 4 in 4562. They are not material
    the alignment may use: an unclaimed session past the end of the edition has no sitting it
    could ever belong to, and offering one to an earlier unresolved sitting would invent a
    correspondence the edition cannot contain. 3189's are trailing and were already isolated
    as ``outside_enriched_span``; 4562's sit inside ordinary brackets and are the reason this
    is enforced rather than left to fall out of the bracket geometry.

    Returns (retained, excluded). Ordinals are recomputed on the retained stream, so the
    sequence being aligned is the one the edition actually covers.
    """
    excluded = sessions.loc[sessions["session_date"] > enriched_end].copy()
    retained = sessions.loc[sessions["session_date"] <= enriched_end].copy()
    retained = retained.sort_values(["inventory_id", "flat_num"]).reset_index(drop=True)
    retained["htr_ordinal"] = retained.groupby("inventory_id").cumcount()
    return retained, excluded


def offset_runs(offsets: list[int]) -> list[dict[str, int]]:
    """Collapse an offset series into piecewise-constant runs, as finding 1 reports."""
    runs: list[dict[str, int]] = []
    for offset in offsets:
        if runs and runs[-1]["offset"] == offset:
            runs[-1]["length"] += 1
        else:
            runs.append({"offset": offset, "length": 1})
    return runs


def build_brackets(
    sittings: pd.DataFrame, sessions: pd.DataFrame
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify the gaps between resolved pins, and force the pairings they determine.

    Returns (bracket rows, forced-pairing rows). A bracket spans two consecutive
    resolved sittings (or a sequence end); ``head``/``tail`` brackets are open on
    one side. Brackets whose pins run backwards in HTR order are marked
    ``non_monotone`` and take no classification -- forcing a pairing across an
    inverted pin would invent an ordering the data does not support.
    """
    brackets: list[dict[str, Any]] = []
    pairings: list[dict[str, Any]] = []
    counted_sessions: set[str] = set()

    for inventory_id, inv_sittings in sittings.groupby("inventory_id"):
        inv_sittings = inv_sittings.sort_values("enriched_ordinal")
        inv_sessions = sessions.loc[sessions["inventory_id"] == inventory_id].sort_values(
            "htr_ordinal"
        )
        claimed = set(inv_sittings.loc[inv_sittings["is_resolved"], "resolved_session_id"])
        session_ordinal = dict(zip(inv_sessions["session_id"], inv_sessions["htr_ordinal"]))

        rows = list(inv_sittings.itertuples(index=False))
        pin_positions = [i for i, row in enumerate(rows) if row.is_resolved]
        session_rows = list(inv_sessions.itertuples(index=False))

        # Bracket boundaries: (left pin index or None, right pin index or None).
        edges: list[tuple[int | None, int | None]] = []
        if not pin_positions:
            edges.append((None, None))
        else:
            edges.append((None, pin_positions[0]))
            edges.extend(zip(pin_positions, pin_positions[1:]))
            edges.append((pin_positions[-1], None))

        for left, right in edges:
            left_row = rows[left] if left is not None else None
            right_row = rows[right] if right is not None else None
            left_ord = session_ordinal.get(left_row.resolved_session_id) if left_row else None
            right_ord = session_ordinal.get(right_row.resolved_session_id) if right_row else None

            inner = rows[(left + 1) if left is not None else 0 : right if right is not None else len(rows)]
            unresolved = [row for row in inner if not row.is_resolved]

            low = -1 if left_ord is None else left_ord
            high = len(session_rows) if right_ord is None else right_ord
            non_monotone = left_ord is not None and right_ord is not None and right_ord < left_ord
            # Pins that run backwards make the ranges overlap, so a session could be
            # counted in two brackets; counted_sessions keeps each one to a single bracket.
            free_sessions = (
                []
                if non_monotone
                else [
                    session
                    for session in session_rows
                    if low < session.htr_ordinal < high
                    and session.session_id not in claimed
                    and session.session_id not in counted_sessions
                ]
            )
            counted_sessions.update(session.session_id for session in free_sessions)

            n_e = len(unresolved)
            n_h = len(free_sessions)
            kind = "interior" if left is not None and right is not None else (
                "head" if left is None and right is not None else
                "tail" if right is None and left is not None else "whole_inventory"
            )

            if non_monotone:
                bracket_class = "non_monotone"
            elif n_e == 0 and n_h == 0:
                bracket_class = "tight"
            elif n_e == 0:
                # Only an interior surplus is the no-insertion case: it is bracketed by two
                # claimed sessions, so an enriched sitting was available and claimed neither
                # side of it. A head/tail surplus is HTR outside the span the enriched edition
                # covers at all (it stops at 1630-05-14 while the axis runs to 1630-12-31),
                # which is a corpus-window fact, not evidence of an unmatched session.
                bracket_class = (
                    "surplus_no_sitting" if kind == "interior" else "outside_enriched_span"
                )
            elif n_h == 0:
                bracket_class = "deficit_no_session"
            elif n_e == n_h:
                bracket_class = "determined"
            elif n_e > n_h:
                bracket_class = "deficit"
            else:
                bracket_class = "surplus"

            brackets.append(
                {
                    "record_type": "bracket",
                    "inventory_id": int(inventory_id),
                    "kind": kind,
                    "bracket_class": bracket_class,
                    "left_pin_date": left_row.enriched_date if left_row else None,
                    "right_pin_date": right_row.enriched_date if right_row else None,
                    "n_unresolved_sittings": n_e,
                    "n_unclaimed_sessions": n_h,
                    "unresolved_k_e": int(sum(row.k_e for row in unresolved)),
                    "unclaimed_paragraphs": int(sum(s.paragraph_count for s in free_sessions)),
                    "unresolved_statuses": dict(Counter(row.status for row in unresolved)),
                }
            )

            if bracket_class == "determined":
                for sitting, session in zip(unresolved, free_sessions):
                    distance = day_distance(sitting.enriched_date, session.session_date)
                    pairings.append(
                        {
                            "record_type": "forced_pairing",
                            "inventory_id": int(inventory_id),
                            "enriched_date": sitting.enriched_date,
                            "enriched_status": sitting.status,
                            "k_e": int(sitting.k_e),
                            "session_id": session.session_id,
                            "session_date": session.session_date,
                            "paragraph_count": int(session.paragraph_count),
                            "day_distance": distance,
                            "beyond_candidate_window": distance > CANDIDATE_WINDOW_DAYS,
                        }
                    )

    return brackets, pairings


def ordinal_offset_rows(
    sittings: pd.DataFrame, sessions: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Per-resolved-sitting ordinal offsets, plus one run-structure row per inventory."""
    session_ordinal = dict(zip(sessions["session_id"], sessions["htr_ordinal"]))
    session_date = dict(zip(sessions["session_id"], sessions["session_date"]))

    resolved = sittings.loc[sittings["is_resolved"]].copy()
    resolved["htr_ordinal"] = resolved["resolved_session_id"].map(session_ordinal)
    resolved = resolved.loc[resolved["htr_ordinal"].notna()].copy()
    resolved["htr_ordinal"] = resolved["htr_ordinal"].astype(int)
    resolved["session_offset"] = resolved["htr_ordinal"] - resolved["enriched_ordinal"]
    resolved["session_date"] = resolved["resolved_session_id"].map(session_date)
    resolved["label_day_distance"] = [
        day_distance(enriched, session)
        for enriched, session in zip(resolved["enriched_date"], resolved["session_date"])
    ]

    summaries: list[dict[str, Any]] = []
    for inventory_id, group in resolved.groupby("inventory_id"):
        group = group.sort_values("enriched_ordinal")
        offsets = group["session_offset"].tolist()
        ordinals = group["htr_ordinal"].tolist()
        runs = offset_runs(offsets)
        non_monotone = sum(1 for a, b in zip(ordinals, ordinals[1:]) if b < a)
        summaries.append(
            {
                "record_type": "ordinal_offset_summary",
                "inventory_id": int(inventory_id),
                "resolved_sittings": len(group),
                "offset_min": int(min(offsets)),
                "offset_max": int(max(offsets)),
                "offset_median": int(pd.Series(offsets).median()),
                "beyond_one_share": round(float((group["session_offset"].abs() > 1).mean()), 4),
                "offset_runs": len(runs),
                "mean_run_length": round(len(offsets) / len(runs), 2),
                "non_monotone_steps": non_monotone,
                "label_distance_beyond_window": int(
                    (group["label_day_distance"] > CANDIDATE_WINDOW_DAYS).sum()
                ),
            }
        )
    return resolved, summaries


def main() -> None:
    concordance = load(CONCORDANCE_DATASET)
    axis = load(AXIS_DATASET)

    sittings = enriched_sittings(concordance)
    all_sessions = htr_sessions(axis)

    # Scope constraint (user, 2026-09-25): the enriched edition ends 1630-05-14; the alignment
    # does not extend beyond it. Derived from the data, not hardcoded, so it tracks the edition.
    enriched_end = str(sittings["enriched_date"].max())
    sessions, beyond_edition = restrict_to_enriched_span(all_sessions, enriched_end)

    # Invariant: nothing in production should already reach past the edition. If this ever
    # trips, a fallback has widened and the constraint is being violated upstream, not here.
    claimed_ids_all = set(
        sittings.loc[sittings["is_resolved"], "resolved_session_id"]
    )
    claimed_beyond = sorted(
        set(beyond_edition["session_id"]) & claimed_ids_all
    )
    if claimed_beyond:
        raise AssertionError(
            f"{len(claimed_beyond)} sitting(s) resolve to a session dated after the enriched "
            f"edition ends ({enriched_end}): {claimed_beyond[:5]}"
        )

    resolved, offset_summaries = ordinal_offset_rows(sittings, sessions)
    brackets, pairings = build_brackets(sittings, sessions)

    bracket_frame = pd.DataFrame(brackets)
    pairing_frame = pd.DataFrame(pairings)

    unresolved_total = int((~sittings["is_resolved"]).sum())
    unresolved_k_e = int(sittings.loc[~sittings["is_resolved"], "k_e"].sum())
    determined = bracket_frame.loc[bracket_frame["bracket_class"] == "determined"]
    determined_sittings = int(determined["n_unresolved_sittings"].sum())
    determined_k_e = int(determined["unresolved_k_e"].sum())

    beyond = (
        int(pairing_frame["beyond_candidate_window"].sum()) if len(pairing_frame) else 0
    )
    beyond_share = beyond / len(pairing_frame) if len(pairing_frame) else 0.0
    within_share = 1.0 - beyond_share
    determined_share = determined_sittings / unresolved_total if unresolved_total else 0.0

    gate_determined = determined_share >= MIN_DETERMINED_SHARE
    gate_window = beyond_share >= MIN_BEYOND_WINDOW_SHARE
    if gate_determined and gate_window:
        verdict = "PASS"
    elif within_share >= CLOSE_WITHIN_WINDOW_SHARE:
        verdict = "CLOSE"
    else:
        verdict = "INCONCLUSIVE"

    insertion_rows = bracket_frame.loc[bracket_frame["bracket_class"] == "surplus_no_sitting"]
    insertion_sessions = int(insertion_rows["n_unclaimed_sessions"].sum())
    outside_span_sessions = int(
        bracket_frame.loc[
            bracket_frame["bracket_class"] == "outside_enriched_span", "n_unclaimed_sessions"
        ].sum()
    )

    # PLAN.md's Local criterion already separates the five main annual inventories from the two
    # non-annual "secret resolution" series (4562, 4861), which are structurally HTR-poor. Where
    # the unresolved mass sits decides whether Step 6 has a target at all.
    annual = {3185, 3186, 3187, 3188, 3189}
    unresolved_rows = sittings.loc[~sittings["is_resolved"]]
    unresolved_non_annual = int((~unresolved_rows["inventory_id"].isin(annual)).sum())
    unresolved_non_annual_k_e = int(
        unresolved_rows.loc[~unresolved_rows["inventory_id"].isin(annual), "k_e"].sum()
    )

    claimed_ids = set(resolved["resolved_session_id"])
    per_inventory = []
    for inventory_id, group in bracket_frame.groupby("inventory_id"):
        pairs = pairing_frame.loc[pairing_frame["inventory_id"] == inventory_id] if len(pairing_frame) else pairing_frame
        inv_sittings = sittings.loc[sittings["inventory_id"] == inventory_id]
        inv_sessions = sessions.loc[sessions["inventory_id"] == inventory_id]
        per_inventory.append(
            {
                "record_type": "inventory_summary",
                "inventory_id": int(inventory_id),
                "sittings": int(len(inv_sittings)),
                "resolved": int(inv_sittings["is_resolved"].sum()),
                "axis_sessions": int(len(inv_sessions)),
                "enriched_span": f"{inv_sittings['enriched_date'].min()}..{inv_sittings['enriched_date'].max()}"
                if len(inv_sittings)
                else None,
                "axis_span": f"{inv_sessions['session_date'].min()}..{inv_sessions['session_date'].max()}"
                if len(inv_sessions)
                else None,
                # Counted from the session set directly, not summed over brackets, so it stays
                # correct regardless of how brackets around non-monotone pins are drawn.
                "unclaimed_sessions": int((~inv_sessions["session_id"].isin(claimed_ids)).sum()),
                "unclaimed_outside_enriched_span": int(
                    group.loc[
                        group["bracket_class"] == "outside_enriched_span", "n_unclaimed_sessions"
                    ].sum()
                ),
                "unresolved_sittings": int(group["n_unresolved_sittings"].sum()),
                "determined_sittings": int(
                    group.loc[group["bracket_class"] == "determined", "n_unresolved_sittings"].sum()
                ),
                "determined_k_e": int(
                    group.loc[group["bracket_class"] == "determined", "unresolved_k_e"].sum()
                ),
                "forced_pairs": int(len(pairs)),
                "forced_pairs_beyond_window": int(pairs["beyond_candidate_window"].sum())
                if len(pairs)
                else 0,
                "sessions_with_no_sitting": int(
                    group.loc[
                        group["bracket_class"] == "surplus_no_sitting", "n_unclaimed_sessions"
                    ].sum()
                ),
                "non_monotone_brackets": int((group["bracket_class"] == "non_monotone").sum()),
            }
        )

    distance_histogram = (
        {str(k): int(v) for k, v in sorted(Counter(pairing_frame["day_distance"]).items())}
        if len(pairing_frame)
        else {}
    )

    meta = {
        "record_type": "meta",
        "step": "Step 6 gate (plans/COLLISION_AVOIDANCE_TRACK.md)",
        "enriched_dates_total": int(concordance["enriched_date"].nunique()),
        "nihil_dates_excluded": int(
            concordance.loc[concordance["status"] == NIHIL_STATUS, "enriched_date"].nunique()
        ),
        "sittings": int(len(sittings)),
        "resolved_sittings": int(sittings["is_resolved"].sum()),
        "unresolved_sittings": unresolved_total,
        "unresolved_k_e": unresolved_k_e,
        "axis_sessions": int(len(sessions)),
        "axis_sessions_all": int(len(all_sessions)),
        "claimed_sessions": int(resolved["resolved_session_id"].nunique()),
        "unclaimed_sessions": int(len(sessions) - resolved["resolved_session_id"].nunique()),
        "sessions_claimed_by_multiple_sittings": int(
            (resolved["resolved_session_id"].value_counts() > 1).sum()
        ),
        "determined_sittings": determined_sittings,
        "determined_k_e": determined_k_e,
        "determined_share_of_unresolved": round(determined_share, 4),
        "forced_pairings": int(len(pairing_frame)),
        "forced_pairings_beyond_window": beyond,
        "forced_pairings_beyond_window_share": round(beyond_share, 4),
        "forced_pairing_day_distance_histogram": distance_histogram,
        "sessions_with_no_enriched_sitting": insertion_sessions,
        "sessions_outside_enriched_span": outside_span_sessions,
        "enriched_edition_ends": enriched_end,
        "sessions_beyond_enriched_edition": int(len(beyond_edition)),
        "sessions_beyond_enriched_edition_by_inventory": {
            str(k): int(v) for k, v in beyond_edition["inventory_id"].value_counts().items()
        },
        "claimed_sessions_beyond_enriched_edition": 0,
        "enriched_span": f"{sittings['enriched_date'].min()}..{sittings['enriched_date'].max()}",
        "axis_span_all": f"{all_sessions['session_date'].min()}..{all_sessions['session_date'].max()}",
        "axis_span_in_scope": f"{sessions['session_date'].min()}..{sessions['session_date'].max()}",
        "unresolved_in_non_annual_inventories": unresolved_non_annual,
        "unresolved_k_e_in_non_annual_inventories": unresolved_non_annual_k_e,
        "candidate_window_days": CANDIDATE_WINDOW_DAYS,
        "gate_min_determined_share": MIN_DETERMINED_SHARE,
        "gate_min_beyond_window_share": MIN_BEYOND_WINDOW_SHARE,
        "gate_close_within_window_share": CLOSE_WITHIN_WINDOW_SHARE,
        "gate_determined_ok": bool(gate_determined),
        "gate_window_ok": bool(gate_window),
        "verdict": verdict,
        "reading_note": (
            "The ordinal offset conflates label drift with genuinely absent HTR, because "
            "the two sequences have different lengths; it is context, not the gate. The "
            "gate is determined_share_of_unresolved together with "
            "forced_pairings_beyond_window_share: a forced pairing arises from "
            "monotonicity alone, and one beyond candidate_window_days is a correspondence "
            "the +/-1-day lookup could not have reached."
        ),
    }

    records: list[dict[str, Any]] = [
        meta,
        *offset_summaries,
        *per_inventory,
        *brackets,
        *pairings,
    ]
    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[CONCORDANCE_DATASET, AXIS_DATASET],
        description=(
            "Step 6 gate of plans/COLLISION_AVOIDANCE_TRACK.md: the enriched<->HTR session "
            "offset distribution, measured across the streams rather than argued by analogy "
            "from s6b_session_fingerprint_match's flat<->raw offsets. Per inventory, enriched "
            "sittings (nihil_actum excluded as the hard skip constraint) are ranked by date and "
            "axis flat sessions by flat_num; resolved sittings are pins, and the brackets "
            "between consecutive pins are classified by unresolved sittings vs unclaimed "
            "sessions. Determined brackets (n_e == n_h) force a pairing by monotonicity alone, "
            "and the calendar-day distance of those forced pairs is the gate: a pair beyond one "
            "day is a correspondence the +/-1-day candidate window could not reach. Also checks "
            "Step 6's no-insertion claim at session level (unclaimed sessions in brackets with "
            "no sitting available). Diagnostic only; no placement change, no tolerance metric."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}\n")
    print("--- 1. sequence sizes ---")
    for key in (
        "enriched_dates_total",
        "nihil_dates_excluded",
        "sittings",
        "resolved_sittings",
        "unresolved_sittings",
        "unresolved_k_e",
        "axis_sessions",
        "claimed_sessions",
        "unclaimed_sessions",
        "sessions_claimed_by_multiple_sittings",
    ):
        print(f"  {key:38s} {meta[key]:6d}")

    print("\n--- 2. ordinal offset (context, conflated -- see reading_note) ---")
    print(pd.DataFrame(offset_summaries).to_string(index=False))

    print("\n--- 3. bracket structure ---")
    summary = (
        bracket_frame.groupby("bracket_class")
        .agg(
            brackets=("bracket_class", "size"),
            unresolved_sittings=("n_unresolved_sittings", "sum"),
            unresolved_k_e=("unresolved_k_e", "sum"),
            unclaimed_sessions=("n_unclaimed_sessions", "sum"),
        )
        .sort_values("unresolved_k_e", ascending=False)
    )
    print(summary.to_string())

    print("\n--- 4. per inventory ---")
    print(pd.DataFrame(per_inventory).to_string(index=False))

    print("\n--- 5. forced pairings (the gate) ---")
    print(f"  forced pairings                 {len(pairing_frame):6d}")
    print(f"  beyond +/-{CANDIDATE_WINDOW_DAYS}-day window          {beyond:6d}  {beyond_share:6.1%}")
    print(f"  day-distance histogram          {distance_histogram}")
    print(f"  sessions with no enriched sitting {insertion_sessions:4d}  (no-insertion check, interior only)")
    print(f"  sessions outside enriched span  {outside_span_sessions:6d}  (trailing, inside scope)")
    print(
        f"  sessions barred, past edition end {len(beyond_edition):4d}  "
        f"(edition ends {enriched_end}; axis runs to {meta['axis_span_all'][-10:]}; "
        f"{meta['sessions_beyond_enriched_edition_by_inventory']}); claimed among them: 0"
    )
    print(
        f"  unresolved sittings in 4562/4861 {unresolved_non_annual:5d} of {unresolved_total}"
        f"  ({unresolved_non_annual_k_e} of {unresolved_k_e} resolutions)"
    )

    print(
        f"\nGATE: determined_share={determined_share:.1%} (>= {MIN_DETERMINED_SHARE:.0%}? "
        f"{gate_determined}) beyond_window_share={beyond_share:.1%} "
        f"(>= {MIN_BEYOND_WINDOW_SHARE:.0%}? {gate_window}) -> {verdict}"
    )


if __name__ == "__main__":
    main()

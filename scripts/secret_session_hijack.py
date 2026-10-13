"""Secret-session hijack: withdraw fabricated 4562 force-fits; re-attach flagged secrets.

On dates whose only resolved session is inventory 4562, the pipeline force-fits every
enriched resolution onto that thin secret session (paragraph 0..0 pileup). Mechanism
(user / plans/archive/ARCHIVAL_PROVENANCE_TRACK.md, DECISIONS 2026-10-05):

  1. Flag accept: ``secreet_resolutie`` OR ``secreet_deel_count > 0``.
  2. Duplicate claim: same 4562 session claimed by two dates → flagged date wins;
     unmarked claimant cleared.
  3. On days with ≥1 flag: withdraw non-flagged placements; keep/re-attach flagged
     rows on the secret session (preserve non-degenerate spans).
  4. Days with 0 flags and not duplicate-losers: abstain (undetermined).

Gate: corpus ``separated`` loss ≤ 6 (0.07%). Does not touch main-series 3185–3189
as a coverage claim; operates on the sidelined 4562 population only.

Usage:
    uv run python -m scripts.secret_session_hijack --write
    uv run python -m scripts.secret_session_hijack --write --wire
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_parquet, save_semi_structured
from scripts.apply_duplicate_session_splits_eval import separated_total, slice_separated
from scripts.corpus_scope import scope_meta

CONCORDANCE = "resolution_concordance_1626_1630"
FLAGS = "enriched_resolution_secret_flags"
PROPOSALS = "secret_session_hijack_proposals"
REPORT = "secret_session_hijack_wire_report"

STATUS_WITHDRAWN = "uncertain"
PRED_WITHDRAW = "secret_hijack_withdrawn"
PRED_DUP_LOSER = "secret_hijack_duplicate_loser"
PRED_REATTACH = "secret_hijack_reattach"
MAX_SEPARATED_LOSS = 6


def _date_str(series: pd.Series) -> pd.Series:
    return series.astype(str).str.slice(0, 10)


def load_secret_flag_keys() -> set[tuple[str, int]]:
    """Enriched (date, resolution_index) with either XML secret marker."""
    keys: set[tuple[str, int]] = set()
    for row in load(FLAGS):
        if not isinstance(row, dict):
            continue
        if not (
            row.get("secreet_resolutie")
            or int(row.get("secreet_deel_count") or 0) > 0
        ):
            continue
        date = str(row.get("date") or "")[:10]
        if not date:
            continue
        keys.add((date, int(row["resolution_index"])))
    return keys


def hijack_dates(concordance: pd.DataFrame) -> list[str]:
    """Dates whose resolved session(s) are all inventory 4562."""
    out: list[str] = []
    work = concordance.copy()
    work["enriched_date"] = _date_str(work["enriched_date"])
    for date, group in work.groupby("enriched_date"):
        sessions = [
            s
            for s in group["resolved_session_id"].dropna().astype(str).unique()
            if s and s != "nan"
        ]
        if sessions and all("4562" in s for s in sessions):
            out.append(str(date)[:10])
    return sorted(out)


def duplicate_claim_map(
    concordance: pd.DataFrame, flag_keys: set[tuple[str, int]]
) -> dict[str, dict[str, Any]]:
    """session_id → {dates, flagged_dates, winner, losers} for multi-date 4562 claims."""
    work = concordance.copy()
    work["enriched_date"] = _date_str(work["enriched_date"])
    mask = work["resolved_session_id"].fillna("").astype(str).str.contains("4562")
    sub = work.loc[mask]
    flagged_dates = {d for d, _i in flag_keys}
    result: dict[str, dict[str, Any]] = {}
    for session, group in sub.groupby("resolved_session_id"):
        dates = sorted({str(d)[:10] for d in group["enriched_date"].unique()})
        if len(dates) < 2:
            continue
        flagged = [d for d in dates if d in flagged_dates]
        winner = flagged[0] if len(flagged) == 1 else (flagged[0] if flagged else None)
        losers = [d for d in dates if d != winner] if winner else dates
        result[str(session)] = {
            "dates": dates,
            "flagged_dates": flagged,
            "winner": winner,
            "losers": losers,
            "decidable": winner is not None and len(flagged) == 1,
        }
    return result


def build_proposals(concordance: pd.DataFrame) -> list[dict[str, Any]]:
    flag_keys = load_secret_flag_keys()
    dates = hijack_dates(concordance)
    dups = duplicate_claim_map(concordance, flag_keys)
    loser_dates = {
        d
        for info in dups.values()
        if info["decidable"]
        for d in info["losers"]
    }

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "n_hijack_dates": len(dates),
            "n_flag_keys": len(flag_keys),
            "n_duplicate_sessions": len(dups),
            "n_duplicate_loser_dates": len(loser_dates),
            "policy": (
                "Withdraw non-flagged 4562 force-fits; re-attach flagged secrets; "
                "duplicate claim → flagged date wins; undetermined (0 flags) abstain."
            ),
            **scope_meta(),
        }
    ]
    for session, info in sorted(dups.items()):
        rows.append({"record_type": "duplicate_claim", "session": session, **info})

    work = concordance.copy()
    work["enriched_date"] = _date_str(work["enriched_date"])
    n_withdraw = n_reattach = n_dup_loser = n_undetermined = 0

    for date in dates:
        day = work.loc[work["enriched_date"] == date]
        day_flags = {(d, i) for d, i in flag_keys if d == date}
        n_flags = len(day_flags)
        session = str(day["resolved_session_id"].dropna().astype(str).iloc[0])
        pileup = int(
            (
                (day["paragraph_start_index"] == 0)
                & (day["paragraph_end_index"] == 0)
            ).sum()
        )

        if date in loser_dates:
            action = "duplicate_loser_clear"
            n_dup_loser += 1
        elif n_flags == 0:
            action = "abstain_undetermined"
            n_undetermined += 1
        else:
            action = "withdraw_nonflag_reattach_flag"
            n_withdraw += int(len(day) - n_flags)
            n_reattach += n_flags

        rows.append({
            "record_type": "date_proposal",
            "enriched_date": date,
            "session": session,
            "k_e": int(len(day)),
            "n_flags": n_flags,
            "flag_resolution_indexes": sorted(i for _d, i in day_flags),
            "n_pileup_0_0": pileup,
            "action": action,
            "gate_eligible": action != "abstain_undetermined",
        })

    rows.append({
        "record_type": "summary",
        "n_date_proposals": len(dates),
        "n_withdraw_rows_est": n_withdraw,
        "n_reattach_rows_est": n_reattach,
        "n_duplicate_loser_dates": n_dup_loser,
        "n_undetermined_dates": n_undetermined,
        "n_gate_eligible": sum(
            1
            for r in rows
            if r.get("record_type") == "date_proposal" and r.get("gate_eligible")
        ),
    })
    return rows


def _clear_placement(out: pd.DataFrame, mask: pd.Series, *, pred_status: str) -> int:
    n = int(mask.sum())
    if n == 0:
        return 0
    out.loc[mask, "paragraph_start_index"] = pd.NA
    out.loc[mask, "paragraph_end_index"] = pd.NA
    out.loc[mask, "resolved_session_id"] = pd.NA
    out.loc[mask, "resolved_session_date"] = pd.NA
    if "inventory_id" in out.columns:
        out.loc[mask, "inventory_id"] = pd.NA
    out.loc[mask, "status"] = STATUS_WITHDRAWN
    if "paragraph_prediction_status" in out.columns:
        out.loc[mask, "paragraph_prediction_status"] = pred_status
    if "day_status" in out.columns:
        out.loc[mask, "day_status"] = STATUS_WITHDRAWN
    return n


def apply_hijack(
    concordance: pd.DataFrame, proposals: list[dict[str, Any]]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    flag_keys = load_secret_flag_keys()
    out = concordance.copy()
    out["enriched_date"] = _date_str(out["enriched_date"])
    log: list[dict[str, Any]] = []

    for prop in proposals:
        if prop.get("record_type") != "date_proposal":
            continue
        date = prop["enriched_date"]
        action = prop["action"]
        entry: dict[str, Any] = {
            "record_type": "date_apply",
            "enriched_date": date,
            "session": prop.get("session"),
            "action": action,
            "applied": False,
            "n_withdrawn": 0,
            "n_reattached": 0,
            "reason": "",
        }
        if action == "abstain_undetermined":
            entry["reason"] = "no_xml_secret_flag"
            log.append(entry)
            continue

        day_mask = out["enriched_date"] == date
        if action == "duplicate_loser_clear":
            entry["n_withdrawn"] = _clear_placement(
                out, day_mask, pred_status=PRED_DUP_LOSER
            )
            entry["applied"] = True
            entry["reason"] = "duplicate_claim_loser"
            log.append(entry)
            continue

        # withdraw_nonflag_reattach_flag
        flag_indexes = {i for d, i in flag_keys if d == date}
        keep_mask = day_mask & out["resolution_index"].isin(flag_indexes)
        drop_mask = day_mask & ~out["resolution_index"].isin(flag_indexes)
        withdrawn = _clear_placement(out, drop_mask, pred_status=PRED_WITHDRAW)
        reattached = 0
        for idx in out.loc[keep_mask].index:
            start = out.at[idx, "paragraph_start_index"]
            end = out.at[idx, "paragraph_end_index"]
            if pd.isna(start) or pd.isna(end):
                out.at[idx, "paragraph_start_index"] = 0
                out.at[idx, "paragraph_end_index"] = 0
            if "paragraph_prediction_status" in out.columns:
                out.at[idx, "paragraph_prediction_status"] = PRED_REATTACH
            if pd.notna(out.at[idx, "resolved_session_id"]):
                out.at[idx, "status"] = "resolved_auto"
            reattached += 1
        entry["n_withdrawn"] = withdrawn
        entry["n_reattached"] = reattached
        entry["applied"] = True
        entry["reason"] = "withdraw_nonflag_reattach_flag"
        log.append(entry)

    return out, log


def run(*, write: bool, wire: bool) -> list[dict[str, Any]]:
    concordance = load(CONCORDANCE)
    proposals = build_proposals(concordance)
    before = concordance.copy()
    before["enriched_date"] = _date_str(before["enriched_date"])
    after, apply_log = apply_hijack(concordance, proposals)

    applied_dates = {e["enriched_date"] for e in apply_log if e["applied"]}
    before_slice = slice_separated(before, applied_dates)
    after_slice = slice_separated(after, applied_dates)
    before_corpus = separated_total(before)
    after_corpus = separated_total(after)
    delta_slice = after_slice["separated"] - before_slice["separated"]
    delta_corpus = after_corpus - before_corpus
    gate_ok = delta_corpus >= -MAX_SEPARATED_LOSS

    hijack_date_set = set(hijack_dates(before))
    n_pile_before = int(
        (
            (before["paragraph_start_index"] == 0)
            & (before["paragraph_end_index"] == 0)
            & before["enriched_date"].isin(hijack_date_set)
        ).sum()
    )
    n_pile_after = int(
        (
            (after["paragraph_start_index"] == 0)
            & (after["paragraph_end_index"] == 0)
            & after["enriched_date"].isin(hijack_date_set)
        ).sum()
    )

    meta = {
        "record_type": "eval_meta",
        "n_applied_dates": len(applied_dates),
        "n_abstained": sum(1 for e in apply_log if not e["applied"]),
        "n_withdrawn": sum(e.get("n_withdrawn", 0) for e in apply_log),
        "n_reattached": sum(e.get("n_reattached", 0) for e in apply_log),
        "before_slice": before_slice,
        "after_slice": after_slice,
        "delta_separated_slice": delta_slice,
        "before_corpus_separated": before_corpus,
        "after_corpus_separated": after_corpus,
        "delta_corpus_separated": delta_corpus,
        "n_pileup_0_0_before": n_pile_before,
        "n_pileup_0_0_after": n_pile_after,
        "max_separated_loss": MAX_SEPARATED_LOSS,
        "gate": "PASS" if gate_ok else "FAIL",
        "wire_requested": wire,
        **scope_meta(),
    }

    print(
        f"secret_hijack  gate={meta['gate']}  applied_dates={meta['n_applied_dates']}  "
        f"withdrawn={meta['n_withdrawn']} reattached={meta['n_reattached']}  "
        f"abstain={meta['n_abstained']}"
    )
    print(
        f"  pileup_0_0 {n_pile_before}→{n_pile_after}  "
        f"slice_separated {before_slice['separated']}→{after_slice['separated']} "
        f"(Δ{delta_slice:+d})  "
        f"corpus {before_corpus}→{after_corpus} (Δ{delta_corpus:+d})"
    )

    if write:
        save_semi_structured(
            proposals + [meta] + apply_log,
            logical_name=PROPOSALS,
            script=__file__,
            description=(
                "Secret-session hijack proposals + apply log: withdraw non-flagged "
                "4562 force-fits, re-attach XML-flagged secrets, duplicate-claim "
                "arbitration. Gate: corpus separated loss ≤ 6."
            ),
            parent_sources=[CONCORDANCE, FLAGS],
        )
        print(f"wrote {PROPOSALS}")

    if wire:
        if not gate_ok:
            raise SystemExit(
                f"refusing --wire: separated Δ={delta_corpus} exceeds "
                f"-{MAX_SEPARATED_LOSS} gate"
            )
        save_parquet(
            after,
            logical_name=CONCORDANCE,
            script=__file__,
            parent_sources=[CONCORDANCE, FLAGS, PROPOSALS],
            description=(
                "resolution_concordance after secret-session hijack wire: non-flagged "
                "4562 force-fits cleared to uncertain; XML-flagged secrets re-attached; "
                "duplicate-claim losers cleared. Main-series 3185–3189 unchanged."
            ),
        )
        save_semi_structured(
            [meta, *apply_log],
            logical_name=REPORT,
            script=__file__,
            description=(
                "Wire report for secret_session_hijack: per-date apply log + separated "
                "before/after on applied dates and corpus-wide."
            ),
            parent_sources=[CONCORDANCE, PROPOSALS],
        )
        print(f"wired {CONCORDANCE}; wrote {REPORT}")

    return proposals + [meta] + apply_log


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help=f"persist {PROPOSALS}")
    parser.add_argument(
        "--wire",
        action="store_true",
        help=f"write {CONCORDANCE} if gate PASS (implies apply)",
    )
    args = parser.parse_args()
    run(write=args.write or args.wire, wire=args.wire)


if __name__ == "__main__":
    main()

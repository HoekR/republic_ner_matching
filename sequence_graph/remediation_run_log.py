"""Append-only log of remediation-window tool runs (user, 2026-10-12).

Hard recalibrate / bake / overflow apply / wire each overwrite their own proof
dataset; without this log, pin mistakes and thin windows disappear from the
terminal scroll. One row per `--write` (and optional backfill). Canonical graph
unchanged.

    uv run python -m sequence_graph.remediation_run_log --backfill
    uv run python -m sequence_graph.remediation_run_log --tail 10
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from data_io import load, resolve, save_semi_structured

LOG_DATASET = "remediation_window_run_log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_prior() -> list[dict[str, Any]]:
    if not resolve(LOG_DATASET).exists():
        return []
    return list(load(LOG_DATASET))


def append_run(row: dict[str, Any]) -> dict[str, Any]:
    """Append one run row. Caller supplies tool-specific fields; we add stamp."""
    out = {
        "record_type": "run",
        "timestamp": row.get("timestamp") or _now(),
        **{k: v for k, v in row.items() if k not in ("record_type", "timestamp")},
    }
    save_semi_structured(
        _load_prior() + [out],
        logical_name=LOG_DATASET,
        script="sequence_graph.remediation_run_log",
    )
    return out


def log_hard_recalibrate(rows: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    meta = next(r for r in rows if r.get("record_type") == "meta")
    compare = next((r for r in rows if r.get("record_type") == "compare_notes"), None)
    n_dp = sum(1 for r in rows if r.get("record_type") == "dp_handoff")
    n_dp_ok = sum(
        1
        for r in rows
        if r.get("record_type") == "dp_handoff" and str(r.get("status", "")).startswith("dp1_ok")
    )
    return append_run({
        "tool": "hard_recalibrate",
        "inventory": meta.get("inventory"),
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "detected_lag_lo": meta.get("detected_lag_lo"),
        "detected_lag_hi": meta.get("detected_lag_hi"),
        "n_lag_days": meta.get("n_lag_days"),
        "median_delta": meta.get("median_delta"),
        "n_hard_active": meta.get("n_hard_active"),
        "n_hard_vs_production_shift": meta.get("n_hard_vs_production_shift"),
        "n_literal_matched": meta.get("n_literal_matched"),
        "n_literal_tried": meta.get("n_literal_tried"),
        "n_dp_handoff": n_dp,
        "n_dp1_ok": n_dp_ok,
        "compare_hard_path_hit": (compare or {}).get("n_hard_path_hit"),
        "compare_n_review_claims": (compare or {}).get("n_review_claims"),
        "compare_hard_path_hit_rate": (compare or {}).get("hard_path_hit_rate"),
        "gate": None,
        "note": note
        or (
            "Pinned calendar may differ from detected_lag_*; "
            "compare-notes outside pin are expected misses."
        ),
    })


def log_bake(rows: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    return append_run({
        "tool": "bake_remediation_track_gold",
        "window_id": meta.get("window_id"),
        "inventory": meta.get("inventory"),
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "detected_lag_lo": meta.get("detected_lag_lo"),
        "detected_lag_hi": meta.get("detected_lag_hi"),
        "n_stages_present": summary.get("n_stages_present") or meta.get("n_stages_present"),
        "n_gap_brackets": summary.get("n_gap_brackets"),
        "n_residual_rows": summary.get("n_residual_rows"),
        "residual_by_kind": summary.get("residual_by_kind"),
        "gate": summary.get("gate"),
        "verdict": summary.get("verdict"),
        "note": note or "Imperfect closure OK; stages 5–6 may be missing on thin windows.",
    })


def log_overflow_apply(rows: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    return append_run({
        "tool": "overflow_align_apply",
        "inventory": meta.get("inventory"),
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "n_overflow_in_hard_window": meta.get("n_overflow_in_hard_window"),
        "n_clean_split": meta.get("n_clean_split"),
        "n_needs_human_cuts": meta.get("n_needs_human_cuts"),
        "claimant_match_rate": meta.get("claimant_match_rate"),
        "order_match_rate": meta.get("order_match_rate"),
        "n_lumped_deletion_sum": meta.get("n_lumped_deletion_sum"),
        "gate": meta.get("gate") or summary.get("gate"),
        "next": summary.get("next"),
        "note": note or "Do not re-cut flats already in overflow_cut_gold.",
    })


def log_overflow_wire(rows: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    meta = next((r for r in rows if r.get("record_type") == "meta"), {})
    summary = next(r for r in rows if r.get("record_type") == "summary")
    return append_run({
        "tool": "overflow_align_wire",
        "inventory": meta.get("inventory"),
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "n_wire_edges": summary.get("n_wire_edges"),
        "n_clean_split_edges": summary.get("n_clean_split_edges"),
        "n_cut_gold_edges": summary.get("n_cut_gold_edges"),
        "n_skipped": summary.get("n_skipped"),
        "gate": summary.get("gate"),
        "next": summary.get("next"),
        "note": note or "ALIGNED_TO:overflow only; no PINNED_TO rewrite.",
    })


def log_hard_pin_repin(rows: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    meta = next((r for r in rows if r.get("record_type") == "meta"), {})
    summary = next(r for r in rows if r.get("record_type") == "summary")
    return append_run({
        "tool": "hard_pin_repin",
        "inventory": meta.get("inventory"),
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "n_wire_edges": summary.get("n_wire_edges"),
        "n_shift": summary.get("n_shift"),
        "n_new_pin": summary.get("n_new_pin"),
        "n_agree": summary.get("n_agree"),
        "monotone_ok": summary.get("monotone_ok"),
        "before_slice_separated": summary.get("before_slice_separated"),
        "uniform_slice_separated": summary.get("uniform_slice_separated"),
        "gate": summary.get("gate"),
        "next": summary.get("next"),
        "note": note or "PINNED_TO:hard only; no production key/concordance rewrite.",
    })


def log_hard_pin_promote(rows: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    meta = next((r for r in rows if r.get("record_type") == "meta"), {})
    summary = next(r for r in rows if r.get("record_type") == "summary")
    inherit = next(
        (r for r in rows if r.get("record_type") == "inherit_summary"), {}
    )
    return append_run({
        "tool": "hard_pin_promote",
        "inventory": meta.get("inventory"),
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "n_wire_edges": summary.get("n_wire_edges"),
        "n_shift": summary.get("n_shift"),
        "n_new_pin": summary.get("n_new_pin"),
        "n_agree": summary.get("n_agree"),
        "monotone_ok": summary.get("monotone_ok"),
        "before_slice_separated": summary.get("before_slice_separated"),
        "after_slice_separated": summary.get("after_slice_separated"),
        "delta_slice_separated": summary.get("delta_slice_separated"),
        "n_inherit_rows": inherit.get("n_rows") or summary.get("n_inherit_rows"),
        "inherit_verdicts": inherit.get("verdicts"),
        "gate": summary.get("gate"),
        "next": summary.get("next"),
        "note": note or (
            "Production PINNED_TO + concordance resolved_session_id from hard; "
            "inherit-date composition report only."
        ),
    })


def log_hard_pin_place(rows: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    meta = next((r for r in rows if r.get("record_type") == "meta"), {})
    summary = next(r for r in rows if r.get("record_type") == "summary")
    return append_run({
        "tool": "hard_pin_place",
        "inventory": meta.get("inventory"),
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "n_dates": summary.get("n_dates"),
        "n_placed": summary.get("n_placed"),
        "n_align_edges": summary.get("n_align_edges"),
        "before_slice_separated": summary.get("before_slice_separated"),
        "after_slice_separated": summary.get("after_slice_separated"),
        "delta_slice_separated": summary.get("delta_slice_separated"),
        "before_corpus_separated": summary.get("before_corpus_separated"),
        "after_corpus_separated": summary.get("after_corpus_separated"),
        "delta_corpus_separated": summary.get("delta_corpus_separated"),
        "before_uniform_separated": summary.get("before_uniform_separated"),
        "after_uniform_separated": summary.get("after_uniform_separated"),
        "gate": summary.get("gate"),
        "next": summary.get("next"),
        "note": note or (
            "Stage 8–9: place under lids; wire concordance + ALIGNED_TO:hard_place on PASS."
        ),
    })


def backfill_from_disk(*, force: bool = False) -> list[dict[str, Any]]:
    """Seed the log from current on-disk proofs (idempotent unless --force)."""
    prior = _load_prior()
    if prior and not force:
        print(f"{LOG_DATASET} already has {len(prior)} rows; pass --force to append again")
        return prior

    written: list[dict[str, Any]] = []
    if resolve("hard_recalibrate_proof").exists():
        written.append(
            log_hard_recalibrate(
                list(load("hard_recalibrate_proof")),
                note="backfill: current hard_recalibrate_proof on disk",
            )
        )
    if resolve("remediation_track_gold").exists():
        bake_rows = list(load("remediation_track_gold"))
        # Log each window's own summary/meta if present
        by_window: dict[str, list[dict[str, Any]]] = {}
        for r in bake_rows:
            wid = r.get("window_id")
            if wid:
                by_window.setdefault(str(wid), []).append(r)
        if by_window:
            for wid, wrows in sorted(by_window.items()):
                if any(x.get("record_type") == "summary" for x in wrows):
                    written.append(
                        log_bake(
                            wrows,
                            note=f"backfill: remediation_track_gold window={wid}",
                        )
                    )
        elif any(r.get("record_type") == "summary" for r in bake_rows):
            written.append(
                log_bake(bake_rows, note="backfill: remediation_track_gold")
            )
    if resolve("overflow_align_apply").exists():
        written.append(
            log_overflow_apply(
                list(load("overflow_align_apply")),
                note="backfill: current overflow_align_apply on disk",
            )
        )
    if resolve("overflow_align_wire").exists():
        written.append(
            log_overflow_wire(
                list(load("overflow_align_wire")),
                note="backfill: current overflow_align_wire on disk",
            )
        )
    if resolve("sequence_graph_snapshot_log").exists():
        for snap in load("sequence_graph_snapshot_log"):
            if snap.get("record_type") != "snapshot":
                continue
            written.append(
                append_run({
                    "tool": "persist_snapshot",
                    "label": snap.get("label"),
                    "n_nodes": snap.get("n_nodes"),
                    "n_edges": snap.get("n_edges"),
                    "n_aligned_to_overflow": snap.get("n_aligned_to_overflow"),
                    "coverage": snap.get("coverage"),
                    "timestamp": snap.get("timestamp") or _now(),
                    "note": "backfill from sequence_graph_snapshot_log",
                })
            )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--backfill",
        action="store_true",
        help="append rows from current on-disk proofs (no-op if log non-empty unless --force)",
    )
    group.add_argument("--tail", type=int, metavar="N", help="print last N run rows")
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --backfill, append even if log already has rows",
    )
    args = parser.parse_args()
    if args.backfill:
        rows = backfill_from_disk(force=args.force)
        print(f"{LOG_DATASET}: {len(rows)} rows after backfill")
        return
    rows = _load_prior()
    for r in rows[-args.tail :]:
        tool = r.get("tool")
        cal = f"{r.get('calendar_lo')}..{r.get('calendar_hi')}"
        gate = r.get("gate")
        print(
            f"{r.get('timestamp', '')[:19]}  {tool:<28}  {cal}  "
            f"gate={gate}  hard_active={r.get('n_hard_active')}  "
            f"stages={r.get('n_stages_present')}  "
            f"overflow={r.get('n_overflow_in_hard_window')}  "
            f"wire={r.get('n_wire_edges')}"
        )


if __name__ == "__main__":
    main()

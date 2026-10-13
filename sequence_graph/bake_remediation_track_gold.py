"""Bake full remediation track gold (stages 1–6) with residual-gap ledger.

Doctrine: gap → rearrange → diagnostic → recalibration → re-alignment → split.
Imperfect closure is OK — residuals must name where holes remain and how big.

Usage:
    uv run python -m sequence_graph.bake_remediation_track_gold --write
    uv run python -m sequence_graph.bake_remediation_track_gold \\
        --window-id next_lag --calendar-lo 1626-08-13 --calendar-hi 1626-08-19 --write
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from data_io import load, save_semi_structured
from scripts.corpus_scope import scope_meta

OUTPUT_DATASET = "remediation_track_gold"
SYNC_GAPS = "sequence_graph_sync_gaps"
HARD_RECAL = "hard_recalibrate_proof"
NEIGH_GOLD = "neighbourhood_shift_gold"
OVERFLOW_SLICE = "aligned_to_overflow_track_gold"

DEFAULT_INVENTORY = "3185"
DEFAULT_SEED_LO = "1626-09-21"
DEFAULT_SEED_HI = "1626-10-25"
DEFAULT_WINDOW_ID = "seed_3185_sep_oct"

REQUIRED = (SYNC_GAPS, HARD_RECAL, NEIGH_GOLD, OVERFLOW_SLICE)

STAGE_NAMES = {
    1: "gap",
    2: "rearrange",
    3: "diagnostic",
    4: "recalibration",
    5: "realignment",
    6: "split",
}


def _require_parents() -> None:
    missing: list[str] = []
    for name in REQUIRED:
        try:
            load(name)
        except Exception:
            missing.append(name)
    if missing:
        raise SystemExit(f"missing parent dataset(s): {', '.join(missing)}")


def _overlaps(a_lo: str, a_hi: str, b_lo: str, b_hi: str) -> bool:
    return bool(a_lo and a_hi and b_lo and b_hi and a_lo <= b_hi and b_lo <= a_hi)


def _in_window(date: str | None, lo: str, hi: str) -> bool:
    if not date:
        return False
    d = str(date)[:10]
    return lo <= d <= hi


def bake(
    *,
    inventory: str = DEFAULT_INVENTORY,
    calendar_lo: str = DEFAULT_SEED_LO,
    calendar_hi: str = DEFAULT_SEED_HI,
    window_id: str = DEFAULT_WINDOW_ID,
) -> list[dict[str, Any]]:
    """Assemble stages 1–6 + residual ledger for one seed window (no recompute)."""
    _require_parents()

    sync_rows = list(load(SYNC_GAPS))
    hard_rows = list(load(HARD_RECAL))
    neigh_rows = list(load(NEIGH_GOLD))
    overflow_rows = list(load(OVERFLOW_SLICE))

    hard_meta = next(r for r in hard_rows if r.get("record_type") == "meta")
    neigh_meta = next(
        (r for r in neigh_rows if r.get("record_type") == "meta"), {}
    )
    overflow_meta = next(
        (r for r in overflow_rows if r.get("record_type") == "meta"), {}
    )

    lag_lo = str(hard_meta.get("detected_lag_lo") or calendar_lo)
    lag_hi = str(hard_meta.get("detected_lag_hi") or calendar_hi)

    # Gap union: seed calendar ∪ lag detect (diagnostic reach)
    gap_lo = min(calendar_lo, lag_lo) if window_id == DEFAULT_WINDOW_ID else calendar_lo
    gap_hi = max(calendar_hi, lag_hi) if window_id == DEFAULT_WINDOW_ID else calendar_hi

    residuals: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    # ----- stage 1: gap -----
    gaps = [
        r
        for r in sync_rows
        if r.get("record_type") == "sync_gap"
        and str(r.get("inventory") or "") == inventory
        and _overlaps(
            str(r.get("calendar_lo") or ""),
            str(r.get("calendar_hi") or ""),
            gap_lo,
            gap_hi,
        )
    ]
    n_gap_meetings = sum(int(r.get("n_editorial_meetings_in_span") or 0) for r in gaps)
    n_gap_span = sum(int(r.get("calendar_span_days") or 0) for r in gaps)
    n_gap_paras = sum(int(r.get("htr_paragraphs_inclusive") or 0) for r in gaps)
    for g in sorted(gaps, key=lambda r: str(r.get("calendar_lo") or "")):
        rows.append({
            "record_type": "gap",
            "window_id": window_id,
            "stage_id": 1,
            "inventory": inventory,
            "calendar_lo": g.get("calendar_lo"),
            "calendar_hi": g.get("calendar_hi"),
            "calendar_span_days": g.get("calendar_span_days"),
            "n_editorial_meetings_in_span": g.get("n_editorial_meetings_in_span"),
            "htr_paragraphs_inclusive": g.get("htr_paragraphs_inclusive"),
            "anchor_lo_session": g.get("anchor_lo_session"),
            "anchor_hi_session": g.get("anchor_hi_session"),
            "n_htr_sessions_inclusive": g.get("n_htr_sessions_inclusive"),
        })
        # Every sync gap remains a residual until later stages claim it closed —
        # size stays visible even if partially addressed downstream.
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 1,
            "kind": "unsynced_bracket",
            "calendar_lo": g.get("calendar_lo"),
            "calendar_hi": g.get("calendar_hi"),
            "size_span_days": g.get("calendar_span_days"),
            "size_meetings": g.get("n_editorial_meetings_in_span"),
            "size_htr_paragraphs": g.get("htr_paragraphs_inclusive"),
            "anchor_lo_session": g.get("anchor_lo_session"),
            "anchor_hi_session": g.get("anchor_hi_session"),
            "note": "Broad sync gap at entry; later stages may shrink but not erase.",
        })

    stage1_ok = len(gaps) > 0
    rows.append({
        "record_type": "stage",
        "window_id": window_id,
        "stage_id": 1,
        "name": STAGE_NAMES[1],
        "status": "present" if stage1_ok else "empty",
        "source_dataset": SYNC_GAPS,
        "summary": (
            f"{len(gaps)} sync_gap brackets; span_days_sum={n_gap_span}; "
            f"meetings_sum={n_gap_meetings}; htr_paras_sum={n_gap_paras}"
        ),
        "n_residual_after": len(gaps),
        "n_items": len(gaps),
    })

    # ----- stage 2: rearrange -----
    hard_maps = [
        r
        for r in hard_rows
        if r.get("record_type") == "hard_map"
        and _in_window(str(r.get("date") or ""), calendar_lo, calendar_hi)
    ]
    n_shift = sum(1 for r in hard_maps if r.get("production_disagrees"))
    n_active = sum(1 for r in hard_maps if r.get("active") and r.get("session_id"))
    rows.append({
        "record_type": "rearrange",
        "window_id": window_id,
        "stage_id": 2,
        "inventory": inventory,
        "claim_set_dropped": hard_meta.get("claim_set_dropped"),
        "claim_set_active": hard_meta.get("claim_set_active"),
        "n_hard_map_in_window": len(hard_maps),
        "n_hard_active": n_active,
        "n_production_disagrees": n_shift,
        "n_hard_vs_production_shift_meta": hard_meta.get("n_hard_vs_production_shift"),
    })
    # Date-placement residuals: each hard≠production day is a typed PINNED_TO conflict
    for hm in hard_maps:
        if not hm.get("production_disagrees"):
            continue
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 2,
            "kind": "date_placement_conflict",
            "date": hm.get("date"),
            "session_id": hm.get("session_id"),
            "production_session": hm.get("production_session"),
            "size_days": 1,
            "note": (
                "Hard OBSERVED_ON∘DATED_AS session ≠ production PINNED_TO. "
                "Dating path (stages 2–4); do not joint-fix with ALIGNED_TO."
            ),
        })
    if not hard_maps:
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 2,
            "kind": "no_hard_map_in_window",
            "calendar_lo": calendar_lo,
            "calendar_hi": calendar_hi,
            "size_span_days": None,
            "size_meetings": None,
            "note": (
                "No hard_map beads in this calendar window — rearrange/recal "
                "not yet applied here (seed hard_recalibrate may be a different window)."
            ),
        })
    stage2_ok = bool(hard_meta.get("claim_set_dropped"))
    rows.append({
        "record_type": "stage",
        "window_id": window_id,
        "stage_id": 2,
        "name": STAGE_NAMES[2],
        "status": "present" if stage2_ok else "missing",
        "source_dataset": HARD_RECAL,
        "summary": (
            f"dropped={hard_meta.get('claim_set_dropped')}; "
            f"active={hard_meta.get('claim_set_active')}; "
            f"hard_map_in_window={len(hard_maps)} "
            f"(disagrees={n_shift}, active={n_active})"
        ),
        "n_residual_after": sum(1 for r in residuals if r.get("after_stage") == 2),
        "n_items": len(hard_maps),
    })

    # ----- stage 3: diagnostic -----
    rows.append({
        "record_type": "diagnostic",
        "window_id": window_id,
        "stage_id": 3,
        "inventory": inventory,
        "detected_lag_lo": lag_lo,
        "detected_lag_hi": lag_hi,
        "n_lag_days": hard_meta.get("n_lag_days"),
        "median_delta": hard_meta.get("median_delta"),
        "pin_delta_hist": hard_meta.get("pin_delta_hist"),
        "n_lag_clusters": hard_meta.get("n_lag_clusters"),
        "n_aug_sep_clusters": hard_meta.get("n_aug_sep_clusters"),
        "seed_calendar_lo": calendar_lo,
        "seed_calendar_hi": calendar_hi,
        "note": "Where to begin: largest Aug/Sep lag cluster (Δ∈{7,8,9}).",
    })
    # Lag days outside hard_map coverage in window
    hard_dates = {str(r.get("date"))[:10] for r in hard_maps if r.get("date")}
    if lag_lo and lag_hi and window_id == DEFAULT_WINDOW_ID:
        # Approximate uncovered: lag window span not equal to hard map count
        n_lag = int(hard_meta.get("n_lag_days") or 0)
        uncovered = max(0, n_lag - len(hard_dates))
        if uncovered:
            residuals.append({
                "record_type": "residual_gap",
                "window_id": window_id,
                "after_stage": 3,
                "kind": "uncovered_lag_day",
                "calendar_lo": lag_lo,
                "calendar_hi": lag_hi,
                "size_lag_days": uncovered,
                "size_lag_days_total": n_lag,
                "size_hard_map_dates": len(hard_dates),
                "note": (
                    "Lag-detect days not all covered by hard_map beads in seed "
                    "calendar (detect window may be wider than apply window)."
                ),
            })
    elif not hard_maps:
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 3,
            "kind": "diagnostic_not_applied",
            "calendar_lo": calendar_lo,
            "calendar_hi": calendar_hi,
            "size_span_days": None,
            "note": "Diagnostic/lag detect was for a different window; this gap awaits its own detect.",
        })
    stage3_ok = bool(hard_meta.get("detected_lag_lo"))
    rows.append({
        "record_type": "stage",
        "window_id": window_id,
        "stage_id": 3,
        "name": STAGE_NAMES[3],
        "status": "present" if stage3_ok else "missing",
        "source_dataset": HARD_RECAL,
        "summary": (
            f"lag={lag_lo}..{lag_hi} days={hard_meta.get('n_lag_days')} "
            f"median_Δ={hard_meta.get('median_delta')} "
            f"clusters={hard_meta.get('n_lag_clusters')}/"
            f"aug_sep={hard_meta.get('n_aug_sep_clusters')}"
        ),
        "n_residual_after": sum(
            1 for r in residuals if r.get("after_stage") == 3
        ),
        "n_items": 1,
    })

    # ----- stage 4: recalibration -----
    literals = [
        r
        for r in hard_rows
        if r.get("record_type") == "literal_opening"
        and (
            _in_window(str(r.get("enriched_date") or ""), calendar_lo, calendar_hi)
            or any(
                _in_window(d, calendar_lo, calendar_hi)
                for d in (r.get("hard_dates_for_session") or [])
            )
        )
    ]
    dps = [
        r
        for r in hard_rows
        if r.get("record_type") == "dp_handoff"
        and _overlaps(
            str(r.get("soft_calendar_lo") or r.get("seed_calendar_lo") or ""),
            str(r.get("soft_calendar_hi") or r.get("seed_calendar_hi") or ""),
            calendar_lo,
            calendar_hi,
        )
    ]
    for hm in hard_maps:
        rows.append({
            "record_type": "recalibration",
            "window_id": window_id,
            "stage_id": 4,
            "kind": "hard_map",
            "date": hm.get("date"),
            "session_id": hm.get("session_id"),
            "production_session": hm.get("production_session"),
            "production_disagrees": hm.get("production_disagrees"),
            "active": hm.get("active"),
            "unique": hm.get("unique"),
        })
    lit_matched = [r for r in literals if r.get("matched")]
    lit_tried = literals
    hard_sess = {
        str(r.get("session_id"))
        for r in hard_maps
        if r.get("session_id")
    }
    lit_sess = {str(r.get("session_id")) for r in lit_matched if r.get("session_id")}
    for sid in sorted(hard_sess - lit_sess):
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 4,
            "kind": "no_literal",
            "session_id": sid,
            "size_sessions": 1,
            "note": "Hard-map session without literal_opening match in window.",
        })
    dp_ok = [r for r in dps if r.get("dp1_ran") and not r.get("abstained")]
    dp_abs = [r for r in dps if r.get("abstained")]
    for r in dp_abs:
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 4,
            "kind": "dp_abstain",
            "calendar_lo": r.get("soft_calendar_lo"),
            "calendar_hi": r.get("soft_calendar_hi"),
            "session_lo": r.get("soft_sess_lo"),
            "session_hi": r.get("soft_sess_hi"),
            "size_k_e": r.get("k_e"),
            "size_k_f": r.get("k_f"),
            "note": "DP hand-off abstained in soft window.",
        })
    if hard_maps and not literals and not dps:
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 4,
            "kind": "recal_incomplete",
            "calendar_lo": calendar_lo,
            "calendar_hi": calendar_hi,
            "size_hard_map": len(hard_maps),
            "note": "Hard map present but no literal/DP rows in window.",
        })
    if not hard_maps:
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 4,
            "kind": "recal_not_run",
            "calendar_lo": calendar_lo,
            "calendar_hi": calendar_hi,
            "note": "Recalibration a→b→c not run for this window.",
        })
    stage4_ok = bool(hard_maps) and (bool(lit_matched) or bool(dp_ok))
    rows.append({
        "record_type": "stage",
        "window_id": window_id,
        "stage_id": 4,
        "name": STAGE_NAMES[4],
        "status": "present" if stage4_ok else ("partial" if hard_maps else "missing"),
        "source_dataset": HARD_RECAL,
        "summary": (
            f"hard_map={len(hard_maps)} literal={len(lit_matched)}/{len(lit_tried)} "
            f"dp_ok={len(dp_ok)} dp_abstain={len(dp_abs)}"
        ),
        "n_residual_after": sum(1 for r in residuals if r.get("after_stage") == 4),
        "n_items": len(hard_maps) + len(literals) + len(dps),
    })

    # ----- stage 5: realignment -----
    gold_labels = [
        r
        for r in neigh_rows
        if r.get("record_type") == "gold_label"
    ]
    as_is = [
        r
        for r in overflow_rows
        if r.get("record_type") == "as_is"
    ]
    # Restrict to window via enriched date on gold / volgnr prefix
    gold_in: list[dict[str, Any]] = []
    for r in gold_labels:
        d = str(r.get("enriched_date_file") or r.get("volgnr") or "")[:10]
        if _in_window(d, calendar_lo, calendar_hi):
            gold_in.append(r)
    as_is_by_v = {str(r.get("volgnr")): r for r in as_is if r.get("volgnr")}
    n_found = sum(
        1 for r in gold_in if r.get("label_status") in ("found", "found_needs_split")
    )
    n_split = sum(1 for r in gold_in if r.get("label_status") == "found_needs_split")
    n_not_found = sum(1 for r in gold_in if r.get("label_status") == "not_found")
    for r in gold_in:
        v = str(r.get("volgnr") or "")
        a = as_is_by_v.get(v)
        rows.append({
            "record_type": "realignment",
            "window_id": window_id,
            "stage_id": 5,
            "volgnr": v,
            "label_status": r.get("label_status"),
            "correct_session": r.get("correct_session"),
            "as_is_flat_id": (a or {}).get("as_is_flat_id"),
            "lumped": (a or {}).get("lumped"),
            "n_claimants_on_flat": (a or {}).get("n_claimants_on_flat"),
            "note": r.get("note") or "",
        })
        if r.get("label_status") == "not_found":
            residuals.append({
                "record_type": "residual_gap",
                "window_id": window_id,
                "after_stage": 5,
                "kind": "not_found",
                "volgnr": v,
                "size_enriched": 1,
                "note": "Hand gold: absent in neighbourhood HTR.",
            })
        elif a is None and r.get("label_status") in ("found", "found_needs_split"):
            residuals.append({
                "record_type": "residual_gap",
                "window_id": window_id,
                "after_stage": 5,
                "kind": "missing_assignment",
                "volgnr": v,
                "size_enriched": 1,
                "note": "Found label without as_is assignment in overflow slice.",
            })
    if not gold_in:
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 5,
            "kind": "realign_not_run",
            "calendar_lo": calendar_lo,
            "calendar_hi": calendar_hi,
            "note": "No neighbourhood hand gold in this window — re-alignment pending.",
        })
    stage5_ok = n_found > 0
    rows.append({
        "record_type": "stage",
        "window_id": window_id,
        "stage_id": 5,
        "name": STAGE_NAMES[5],
        "status": "present" if stage5_ok else "missing",
        "source_dataset": f"{NEIGH_GOLD}+{OVERFLOW_SLICE}",
        "summary": (
            f"labels_in_window={len(gold_in)} found={n_found} "
            f"needs_split={n_split} not_found={n_not_found} as_is={len(as_is)}"
        ),
        "n_residual_after": sum(1 for r in residuals if r.get("after_stage") == 5),
        "n_items": len(gold_in),
    })

    # ----- stage 6: split -----
    flats = [
        r for r in overflow_rows if r.get("record_type") == "flat_as_is"
    ]
    ends = [
        r for r in overflow_rows if r.get("record_type") == "proposed_end"
    ]
    cuts = [
        r for r in overflow_rows if r.get("record_type") == "cut_proposal"
    ]
    # Filter flats whose claimants fall in window
    def _flat_in_window(flat: dict[str, Any]) -> bool:
        vols = flat.get("claimant_volgnrs") or []
        return any(_in_window(str(v)[:10], calendar_lo, calendar_hi) for v in vols)

    flats_w = [f for f in flats if _flat_in_window(f)]
    flat_ids = {str(f.get("flat_id")) for f in flats_w}
    ends_w = [
        e for e in ends
        if str(e.get("source_flat_id")) in flat_ids
        or _in_window(str(e.get("volgnr") or "")[:10], calendar_lo, calendar_hi)
    ]
    cuts_w = [c for c in cuts if str(c.get("flat_id")) in flat_ids]

    for f in flats_w:
        rows.append({
            "record_type": "split",
            "window_id": window_id,
            "stage_id": 6,
            "kind": "flat_as_is",
            **{k: f.get(k) for k in (
                "flat_id", "session_id", "claimant_volgnrs", "n_claimants",
                "flat_char_len", "should_split", "split_signal",
            )},
        })
    for e in ends_w:
        rows.append({
            "record_type": "split",
            "window_id": window_id,
            "stage_id": 6,
            "kind": "proposed_end",
            **{k: e.get(k) for k in (
                "volgnr", "session_id", "source_flat_id", "segment_rank",
                "n_segments", "prefer_half", "expects_second_half",
                "label_status", "needs_split", "note", "is_gold", "passthrough",
            )},
        })
    for c in cuts_w:
        rows.append({
            "record_type": "split",
            "window_id": window_id,
            "stage_id": 6,
            "kind": "cut_proposal",
            "is_gold": False,
            **{k: c.get(k) for k in (
                "flat_id", "session_id", "n_cuts", "n_claimants",
                "claimant_volgnrs", "even_split_cuts", "encoder_cuts",
                "encoder_available", "model_name", "flat_char_len",
            )},
        })
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 6,
            "kind": "needs_split_pending_cuts",
            "flat_id": c.get("flat_id"),
            "size_claimants": c.get("n_claimants"),
            "size_cuts": c.get("n_cuts"),
            "size_char_len": c.get("flat_char_len"),
            "note": "Overflow flat has machine cut_proposal only — not gold until treatment.",
        })

    needs_split_vols = [
        r for r in gold_in if r.get("label_status") == "found_needs_split"
    ]
    overflow_vols = {
        v
        for f in flats_w
        for v in (f.get("claimant_volgnrs") or [])
    }
    for r in needs_split_vols:
        v = str(r.get("volgnr") or "")
        if v not in overflow_vols:
            residuals.append({
                "record_type": "residual_gap",
                "window_id": window_id,
                "after_stage": 6,
                "kind": "needs_split_not_on_overflow",
                "volgnr": v,
                "size_enriched": 1,
                "note": "found_needs_split but not on a multi-claim overflow flat.",
            })
    if not flats_w and not gold_in:
        residuals.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 6,
            "kind": "split_not_run",
            "calendar_lo": calendar_lo,
            "calendar_hi": calendar_hi,
            "note": "Overflow/split slice not available for this window.",
        })

    stage6_ok = len(flats_w) > 0
    rows.append({
        "record_type": "stage",
        "window_id": window_id,
        "stage_id": 6,
        "name": STAGE_NAMES[6],
        "status": "present" if stage6_ok else "missing",
        "source_dataset": OVERFLOW_SLICE,
        "summary": (
            f"overflow_flats={len(flats_w)} proposed_end={len(ends_w)} "
            f"cut_proposals={len(cuts_w)} (is_gold=false)"
        ),
        "n_residual_after": sum(1 for r in residuals if r.get("after_stage") == 6),
        "n_items": len(flats_w) + len(ends_w) + len(cuts_w),
    })

    # ----- residual ledger -----
    rows.extend(residuals)
    by_kind: Counter[str] = Counter()
    by_stage: Counter[int] = Counter()
    size_meetings = 0
    size_span = 0
    for r in residuals:
        by_kind[str(r.get("kind") or "unknown")] += 1
        by_stage[int(r.get("after_stage") or 0)] += 1
        size_meetings += int(r.get("size_meetings") or 0)
        size_span += int(r.get("size_span_days") or 0)

    residual_summary = {
        "record_type": "residual_summary",
        "window_id": window_id,
        "n_residual_rows": len(residuals),
        "by_after_stage": {str(k): v for k, v in sorted(by_stage.items())},
        "by_kind": dict(sorted(by_kind.items())),
        "size_meetings_sum_unsynced": size_meetings,
        "size_span_days_sum_unsynced": size_span,
        "policy": (
            "Imperfect closure expected. Residuals name remaining holes and sizes; "
            "zero residuals is not required for gate PASS."
        ),
    }
    rows.append(residual_summary)

    stages_present = sum(
        1
        for r in rows
        if r.get("record_type") == "stage"
        and r.get("status") in ("present", "partial")
    )
    gate_ok = stages_present >= 1 and (
        len(residuals) > 0
        or residual_summary["n_residual_rows"] == 0
    )
    # Explicit zero-residual reason if somehow empty
    if len(residuals) == 0:
        rows.append({
            "record_type": "residual_gap",
            "window_id": window_id,
            "after_stage": 0,
            "kind": "none_explicit",
            "note": "No residual rows computed — unexpected; check sources.",
        })
        residual_summary["n_residual_rows"] = 1
        gate_ok = stages_present >= 1

    meta = {
        "record_type": "meta",
        "mode": "bake_remediation_track_gold",
        "window_id": window_id,
        "inventory": inventory,
        "calendar_lo": calendar_lo,
        "calendar_hi": calendar_hi,
        "gap_union_lo": gap_lo,
        "gap_union_hi": gap_hi,
        "detected_lag_lo": lag_lo,
        "detected_lag_hi": lag_hi,
        "stages": "1=gap,2=rearrange,3=diagnostic,4=recalibration,5=realignment,6=split",
        "n_stages_present": stages_present,
        "n_gap_brackets": len(gaps),
        "n_residual_rows": residual_summary["n_residual_rows"],
        "residual_by_kind": residual_summary["by_kind"],
        "parents": list(REQUIRED),
        "overflow_slice_gate": overflow_meta.get("gate"),
        "neighbourhood_meta": {
            "calendar_lo": neigh_meta.get("calendar_lo"),
            "calendar_hi": neigh_meta.get("calendar_hi"),
        },
        "policy": (
            "Full remediation track gold for one window. Stages 1–6 stitched from "
            "existing artifacts (no recompute). End state need not be 100% correct; "
            "residual_gap / residual_summary must show where holes remain and how big. "
            "No production PINNED_TO / ALIGNED_TO wire. Cuts stay is_gold=false."
        ),
        "gate": "PASS" if gate_ok else "FAIL",
        **scope_meta(),
    }
    rows.insert(0, meta)
    rows.append({
        "record_type": "summary",
        "window_id": window_id,
        "n_stages_present": stages_present,
        "n_gap_brackets": len(gaps),
        "n_residual_rows": residual_summary["n_residual_rows"],
        "residual_by_kind": residual_summary["by_kind"],
        "residual_by_after_stage": residual_summary["by_after_stage"],
        "size_meetings_sum_unsynced": size_meetings,
        "size_span_days_sum_unsynced": size_span,
        "gate": meta["gate"],
        "verdict": (
            f"Track gold window={window_id}: stages_present={stages_present}/6; "
            f"residuals={residual_summary['n_residual_rows']} "
            f"(unsynced meetings≈{size_meetings}). Not dating. No wire."
        ),
    })
    return rows


def _print_report(rows: list[dict[str, Any]]) -> None:
    meta = next(r for r in rows if r["record_type"] == "meta")
    print(
        f"remediation-track-gold  window={meta['window_id']}  "
        f"inv={meta['inventory']}  cal={meta['calendar_lo']}..{meta['calendar_hi']}  "
        f"stages_present={meta['n_stages_present']}/6  "
        f"gaps={meta['n_gap_brackets']}  residuals={meta['n_residual_rows']}  "
        f"gate={meta['gate']}"
    )
    for r in rows:
        if r.get("record_type") != "stage":
            continue
        print(
            f"  stage {r['stage_id']} {r['name']}: {r['status']}  "
            f"items={r.get('n_items')}  residual_after={r.get('n_residual_after')}  "
            f"— {r.get('summary')}"
        )
    rs = next(r for r in rows if r["record_type"] == "residual_summary")
    print(
        f"  RESIDUALS n={rs['n_residual_rows']}  "
        f"by_stage={rs['by_after_stage']}  by_kind={rs['by_kind']}"
    )
    print(
        f"  sizes unsynced: meetings_sum={rs.get('size_meetings_sum_unsynced')}  "
        f"span_days_sum={rs.get('size_span_days_sum_unsynced')}"
    )
    # Top residuals by size
    res = [r for r in rows if r.get("record_type") == "residual_gap"]
    ranked = sorted(
        res,
        key=lambda r: (
            -(int(r.get("size_meetings") or r.get("size_lag_days") or r.get("size_claimants") or 0)),
            int(r.get("after_stage") or 0),
        ),
    )
    print("  top residual holes:")
    for r in ranked[:12]:
        bits = [
            f"after={r.get('after_stage')}",
            f"kind={r.get('kind')}",
        ]
        for k in (
            "calendar_lo", "calendar_hi", "flat_id", "volgnr", "session_id",
            "size_meetings", "size_span_days", "size_lag_days", "size_claimants",
            "size_char_len",
        ):
            if r.get(k) is not None:
                bits.append(f"{k}={r[k]}")
        print("   ", " ".join(bits))


def _merge_windows(existing: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep other window_ids; replace rows for the new window_id."""
    new_wid = next(
        (r.get("window_id") for r in new_rows if r.get("record_type") == "meta"),
        None,
    )
    kept = [
        r
        for r in existing
        if r.get("window_id") != new_wid and r.get("record_type") not in ("meta", "summary")
        or (
            r.get("record_type") in ("meta", "summary")
            and r.get("window_id")
            and r.get("window_id") != new_wid
        )
    ]
    # Drop bare global meta/summary without window from old single-window files
    kept = [
        r
        for r in kept
        if not (
            r.get("record_type") in ("meta", "summary")
            and not r.get("window_id")
        )
    ]
    combined = kept + new_rows
    windows = sorted({
        str(r.get("window_id"))
        for r in combined
        if r.get("record_type") == "meta" and r.get("window_id")
    })
    combined.append({
        "record_type": "index",
        "n_windows": len(windows),
        "window_ids": windows,
        "policy": "Multi-window remediation_track_gold; residuals per window_id.",
    })
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY)
    parser.add_argument("--calendar-lo", default=DEFAULT_SEED_LO)
    parser.add_argument("--calendar-hi", default=DEFAULT_SEED_HI)
    parser.add_argument("--window-id", default=DEFAULT_WINDOW_ID)
    parser.add_argument(
        "--merge",
        action="store_true",
        help="merge into existing remediation_track_gold (replace same window_id)",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    rows = bake(
        inventory=str(args.inventory),
        calendar_lo=str(args.calendar_lo),
        calendar_hi=str(args.calendar_hi),
        window_id=str(args.window_id),
    )
    _print_report(rows)
    if args.write:
        out = rows
        if args.merge:
            try:
                existing = list(load(OUTPUT_DATASET))
            except Exception:
                existing = []
            if existing:
                out = _merge_windows(existing, rows)
                print(f"merged windows → {[r.get('window_ids') for r in out if r.get('record_type')=='index']}")
        save_semi_structured(
            out,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=(
                "Full remediation track gold (gap→rearrange→diagnostic→recal→"
                "realign→split) with residual-gap ledger. Imperfect closure OK. "
                "No production wire."
            ),
            parent_sources=list(REQUIRED),
        )
        from sequence_graph.remediation_run_log import log_bake

        log_bake(rows)
        print(f"wrote {OUTPUT_DATASET}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Track P P5 — persist a versioned corpus axis successor from gated predicted cuts.

P4 showed typed Group-C cuts unlock separated on colliding days (Δ+1732 vs plain)
but under-propose (cut fill 0.435) and create extent>3 hits (231). This step:

1. Proposes the same host cuts as P4.
2. Applies a **host cut-fill gate** (default: keep a host only when enough_cuts).
3. Scores the day; applies a **day gate** (default: beats plain AND no extent
   regression vs plain).
4. Materialises accepted cuts onto a versioned successor of
   ``paragraph_axis_1626_1630`` (never in-place). Scope bar + main series at entry.

Writes:
  - ``paragraph_axis_p5_predicted_v1`` — successor paragraph stream
  - ``s6c_p5_axis_successor_ledger`` — meta + per-day gate outcomes

Usage:
    uv run python -m scripts.s6c_p5_persist_axis_successor --limit 20
    uv run python -m scripts.s6c_p5_persist_axis_successor   # full colliding set

    # Re-review one or a few days (merge-safe: other days' cuts kept):
    uv run python -m scripts.s6c_p5_persist_axis_successor \\
        --dates 1629-02-09,1628-01-29
    uv run python -m scripts.s6c_p5_persist_axis_successor \\
        --dates 1629-02-09 --dry-run          # score only
    uv run python -m scripts.s6c_p5_persist_axis_successor \\
        --dates 1629-02-09 --reject           # clear cuts for those days
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_io import load, save_semi_structured
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from scripts.s4_corpus_paragraph_predictions import axis_for_date
from scripts.s6c_group_c_typed_formula_channel import TypedFormulaChannel, build_channel
from scripts.s6c_gap_segmentation import segment_day
from scripts.s6c_p4_predicted_offset_eval import (
    CONCORDANCE,
    _dense_enriched_index,
    _main_concordance,
    colliding_hosts,
    propose_cuts_for_host,
    score_day_starts,
)
from scripts.s6c_reparagraph import (
    AXIS_VERSION_P5,
    DAY_GATE_BEATS_AND_NO_EXTENT,
    DAY_GATES,
    HOST_GATE_ENOUGH_CUTS,
    HOST_GATES,
    apply_cuts_to_corpus_rows,
    day_passes_gate,
    gate_host_cuts,
    segment_day_with_offsets,
    starts_from_segment_positions,
)
from scripts.separated_accuracy_eval import uniform_start_paragraphs

PARENT_AXIS = "paragraph_axis_1626_1630"
AXIS_OUTPUT = "paragraph_axis_p5_predicted_v1"
LEDGER_OUTPUT = "s6c_p5_axis_successor_ledger"


def parse_date_list(raw: str | None) -> list[str]:
    """Comma/semicolon-separated ISO dates → sorted unique YYYY-MM-DD."""
    if not raw:
        return []
    dates: set[str] = set()
    for part in str(raw).replace(";", ",").split(","):
        text = part.strip()[:10]
        if text and text[0].isdigit():
            dates.add(text)
    return sorted(dates)


def cuts_from_successor_axis(rows: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Recover parent ``axis_id`` → interior cut offsets from ``#repara:`` pieces."""
    pieces_by_parent: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in rows:
        axis_id = str(row.get("axis_id") or "")
        if "#repara:" not in axis_id:
            continue
        base, span = axis_id.rsplit("#repara:", 1)
        try:
            start_s, end_s = span.split("-", 1)
            start, end = int(start_s), int(end_s)
        except ValueError:
            continue
        pieces_by_parent[base].append((start, end))
    cuts: dict[str, list[int]] = {}
    for base, pieces in pieces_by_parent.items():
        ordered = sorted(pieces)
        offsets = sorted({start for start, _end in ordered if start > 0})
        if offsets:
            cuts[base] = offsets
    return cuts


def _load_existing_ledger_days() -> list[dict[str, Any]]:
    try:
        rows = list(load(LEDGER_OUTPUT))
    except Exception:
        return []
    return [dict(row) for row in rows if row.get("record_type") == "day"]


def _load_existing_cuts() -> dict[str, list[int]]:
    try:
        rows = list(load(AXIS_OUTPUT))
    except Exception:
        return {}
    return cuts_from_successor_axis(rows)


def _merge_cut_map(
    base: dict[str, list[int]],
    *,
    clear_axis_ids: set[str],
    add: dict[str, list[int]],
) -> dict[str, list[int]]:
    merged = {key: list(vals) for key, vals in base.items() if key not in clear_axis_ids}
    for axis_id, offsets in add.items():
        merged[axis_id] = sorted({int(o) for o in offsets})
    return merged


def _process_day_gated(
    date: str,
    day: pd.DataFrame,
    hosts: pd.DataFrame,
    axis: list[dict[str, Any]],
    channel: TypedFormulaChannel,
    *,
    host_gate: str,
    day_gate: str,
) -> dict[str, Any] | None:
    """Propose → host-gate → score → day-gate. Returns ledger row + accepted cuts."""
    if not axis:
        return None
    k_e = int(len(day))
    dense = _dense_enriched_index(day)
    host_rows = hosts.loc[hosts["enriched_date"] == date]
    if host_rows.empty:
        return None

    proposals: list[dict[str, Any]] = []
    gated_cuts_by_para: dict[int, list[int]] = {}
    for host in host_rows.itertuples(index=False):
        para = int(host.paragraph_start_index)
        if para < 0 or para >= len(axis):
            continue
        record = axis[para]
        text = str(record.get("text") or "")
        raw = propose_cuts_for_host(
            channel,
            axis_id=str(record.get("axis_id") or f"{date}#p{para}"),
            text=text,
            n_share=int(host.n_share),
        )
        accepted = gate_host_cuts(
            raw["cuts"], raw["n_needed"], mode=host_gate
        )
        proposal = {
            **raw,
            "paragraph_start_index": para,
            "axis_id": str(record.get("axis_id") or ""),
            "cuts_raw": list(raw["cuts"]),
            "cuts": accepted,
            "n_cuts_gated": len(accepted),
            "host_accepted": bool(accepted),
        }
        proposals.append(proposal)
        if accepted:
            gated_cuts_by_para[para] = accepted

    # Offset pins from gated cuts only.
    offset_pins: dict[int, tuple[int, int]] = {}
    for proposal in proposals:
        if not proposal["host_accepted"]:
            continue
        para = int(proposal["paragraph_start_index"])
        members = day.loc[
            day["paragraph_start_index"].astype("Int64") == para
        ].sort_values("resolution_index")
        ranks = [dense[int(r)] for r in members["resolution_index"].tolist()]
        cuts = proposal["cuts"]
        for slot, enriched_rank in enumerate(ranks):
            if slot == 0:
                offset_pins[enriched_rank] = (para, 0)
            elif slot - 1 < len(cuts):
                offset_pins[enriched_rank] = (para, int(cuts[slot - 1]))

    share_counts = (
        day.dropna(subset=["paragraph_start_index"])
        .groupby("paragraph_start_index")
        .size()
    )
    alignments: list[tuple[int | None, int | None, int | None]] = []
    plain_alignments: list[tuple[int | None, int | None]] = []
    for row in day.itertuples(index=False):
        enriched_rank = dense[int(row.resolution_index)]
        if enriched_rank == 0:
            continue
        start = row.paragraph_start_index
        if pd.isna(start):
            continue
        para = int(start)
        plain_alignments.append((enriched_rank, para))
        if enriched_rank in offset_pins:
            pin_para, offset = offset_pins[enriched_rank]
            alignments.append((enriched_rank, pin_para, int(offset)))
        elif int(share_counts.get(para, 1)) == 1:
            alignments.append((enriched_rank, para, None))

    plain_positions = segment_day(k_e, len(axis), plain_alignments)
    plain_starts = starts_from_segment_positions(plain_positions)
    plain_score = score_day_starts(plain_starts, date=date, axis_count=len(axis))

    if gated_cuts_by_para:
        carried = segment_day_with_offsets(
            k_e,
            axis,
            alignments,
            version=AXIS_VERSION_P5,
            parent_dataset=PARENT_AXIS,
        )
        successor_n = len(carried["successor"]["axis"])
        pred_starts = starts_from_segment_positions(carried["positions"])
        pred_score = score_day_starts(pred_starts, date=date, axis_count=successor_n)
        uniform = uniform_start_paragraphs(successor_n, k_e)
        uniform_score = score_day_starts(uniform, date=date, axis_count=successor_n)
    else:
        successor_n = len(axis)
        pred_score = plain_score
        uniform_score = score_day_starts(
            uniform_start_paragraphs(len(axis), k_e),
            date=date,
            axis_count=len(axis),
        )

    accepted = day_passes_gate(
        separated_predicted=pred_score["n_separated"],
        separated_plain=plain_score["n_separated"],
        extent_gt_max_predicted=pred_score["n_extent_gt_max"],
        extent_gt_max_plain=plain_score["n_extent_gt_max"],
        mode=day_gate,
    ) and bool(gated_cuts_by_para)

    applied_by_axis_id: dict[str, list[int]] = {}
    if accepted:
        for proposal in proposals:
            if not proposal["host_accepted"]:
                continue
            axis_id = proposal["axis_id"]
            if axis_id:
                applied_by_axis_id[axis_id] = list(proposal["cuts"])

    n_needed = sum(int(p["n_needed"]) for p in proposals)
    n_raw = sum(int(p["n_cuts"]) for p in proposals)
    n_gated = sum(int(p["n_cuts_gated"]) for p in proposals)
    return {
        "record_type": "day",
        "enriched_date": date,
        "k_e": k_e,
        "n_colliding_hosts": len(proposals),
        "n_hosts_accepted": sum(1 for p in proposals if p["host_accepted"]),
        "n_cuts_needed": n_needed,
        "n_cuts_raw": n_raw,
        "n_cuts_gated": n_gated,
        "n_paragraphs_before": len(axis),
        "n_paragraphs_after": successor_n if accepted else len(axis),
        "separated_plain": plain_score["n_separated"],
        "separated_predicted": pred_score["n_separated"],
        "separated_uniform_successor": uniform_score["n_separated"],
        "n_extent_gt_max_plain": plain_score["n_extent_gt_max"],
        "n_extent_gt_max_predicted": pred_score["n_extent_gt_max"],
        "delta_vs_plain": pred_score["n_separated"] - plain_score["n_separated"],
        "day_accepted": accepted,
        "applied_cuts_by_axis_id": applied_by_axis_id,
        "host_cut_fill": [
            {
                "paragraph_start_index": p["paragraph_start_index"],
                "axis_id": p["axis_id"],
                "n_share": p["n_share"],
                "n_needed": p["n_needed"],
                "n_cuts_raw": p["n_cuts"],
                "n_cuts_gated": p["n_cuts_gated"],
                "host_accepted": p["host_accepted"],
            }
            for p in proposals
        ],
    }


def _load_parent_axis() -> list[dict[str, Any]]:
    rows = list(load(PARENT_AXIS))
    kept = [
        row
        for row in rows
        if in_scope(str(row.get("date") or "")[:10])
        and is_main_series(str(row.get("flat_id") or ""))
    ]
    return kept


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap colliding dates (0 = all). Ignored when --dates is set.",
    )
    parser.add_argument(
        "--dates",
        default="",
        help=(
            "Comma-separated enriched dates to (re)score, e.g. "
            "1629-02-09,1628-01-29. Merge-safe: keeps other days' cuts/ledger."
        ),
    )
    parser.add_argument(
        "--reject",
        action="store_true",
        help="With --dates: clear cuts for those days (force gate reject), no re-propose.",
    )
    parser.add_argument("--channel", default="typed", choices=("typed",))
    parser.add_argument(
        "--host-gate",
        default=HOST_GATE_ENOUGH_CUTS,
        choices=HOST_GATES,
        help="Cut-fill gate on colliding hosts (default: enough_cuts).",
    )
    parser.add_argument(
        "--day-gate",
        default=DAY_GATE_BEATS_AND_NO_EXTENT,
        choices=DAY_GATES,
        help="Day materialisation gate (default: beats plain + no extent regression).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score only; do not write successor axis or ledger.",
    )
    args = parser.parse_args(argv)
    selected = parse_date_list(args.dates)
    if args.reject and not selected:
        raise SystemExit("--reject requires --dates")

    concordance = _main_concordance()
    placed = concordance.loc[concordance["paragraph_start_index"].notna()].copy()
    hosts = colliding_hosts(placed)
    colliding_dates = sorted(hosts["enriched_date"].unique())
    if selected:
        dates = [d for d in selected if d in set(colliding_dates) or args.reject]
        missing = [d for d in selected if d not in set(colliding_dates)]
        if missing and not args.reject:
            print(
                f"note: {len(missing)} date(s) have no colliding hosts "
                f"(skipped for re-propose): {', '.join(missing[:8])}"
                + ("…" if len(missing) > 8 else "")
            )
        # Still allow --reject on non-colliding dates to clear any stale cuts.
        if args.reject:
            dates = selected
    else:
        dates = colliding_dates
        if args.limit > 0:
            dates = dates[: int(args.limit)]

    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    channel = build_channel(args.channel)

    merge_mode = bool(selected)
    existing_cuts = _load_existing_cuts() if merge_mode else {}
    clear_axis_ids: set[str] = set()
    new_cuts: dict[str, list[int]] = {}
    rescored: list[dict[str, Any]] = []

    for date in dates:
        day = concordance.loc[concordance["enriched_date"] == date].copy()
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        for record in axis:
            aid = str(record.get("axis_id") or "")
            if aid:
                clear_axis_ids.add(aid)

        if args.reject:
            host_rows = hosts.loc[hosts["enriched_date"] == date]
            rescored.append(
                {
                    "record_type": "day",
                    "enriched_date": date,
                    "k_e": int(len(day)),
                    "n_colliding_hosts": int(len(host_rows)),
                    "n_hosts_accepted": 0,
                    "n_cuts_needed": 0,
                    "n_cuts_raw": 0,
                    "n_cuts_gated": 0,
                    "n_paragraphs_before": len(axis),
                    "n_paragraphs_after": len(axis),
                    "separated_plain": None,
                    "separated_predicted": None,
                    "separated_uniform_successor": None,
                    "n_extent_gt_max_plain": None,
                    "n_extent_gt_max_predicted": None,
                    "delta_vs_plain": 0,
                    "day_accepted": False,
                    "host_cut_fill": [],
                    "manual_reject": True,
                }
            )
            continue

        result = _process_day_gated(
            date,
            day,
            hosts,
            axis,
            channel,
            host_gate=args.host_gate,
            day_gate=args.day_gate,
        )
        if result is None:
            continue
        applied = result.pop("applied_cuts_by_axis_id")
        rescored.append(result)
        if result["day_accepted"]:
            for axis_id, offsets in applied.items():
                new_cuts[axis_id] = sorted({int(o) for o in offsets})

    if merge_mode:
        cuts_by_axis_id = _merge_cut_map(
            existing_cuts, clear_axis_ids=clear_axis_ids, add=new_cuts
        )
        kept = [
            row
            for row in _load_existing_ledger_days()
            if str(row.get("enriched_date") or "")[:10] not in set(dates)
        ]
        day_rows = kept + rescored
        day_rows.sort(key=lambda row: str(row.get("enriched_date") or ""))
    else:
        cuts_by_axis_id = new_cuts
        day_rows = rescored

    n_days = len(day_rows)
    n_accepted = sum(1 for r in day_rows if r.get("day_accepted"))
    sep_pred = sum(
        int(r["separated_predicted"])
        for r in day_rows
        if r.get("day_accepted") and r.get("separated_predicted") is not None
    )
    sep_plain = sum(
        int(r["separated_plain"])
        for r in day_rows
        if r.get("day_accepted") and r.get("separated_plain") is not None
    )
    n_cuts_needed = sum(int(r.get("n_cuts_needed") or 0) for r in day_rows)
    n_cuts_gated = sum(int(r.get("n_cuts_gated") or 0) for r in day_rows)
    summary: dict[str, Any] = {
        "record_type": "summary",
        "track": "track-p-subparagraph-division",
        "step": "P5-persist-axis-successor",
        "axis_version": AXIS_VERSION_P5,
        "host_gate": args.host_gate,
        "day_gate": args.day_gate,
        "channel": args.channel,
        "limit": None if selected else (args.limit or None),
        "dates": selected or None,
        "merge_mode": merge_mode,
        "reject": bool(args.reject),
        "dry_run": bool(args.dry_run),
        "n_colliding_dates_scored": len(rescored),
        "n_days_in_ledger": n_days,
        "n_days_accepted": n_accepted,
        "n_days_rejected": n_days - n_accepted,
        "n_hosts_split": len(cuts_by_axis_id),
        "n_cuts_applied": sum(len(v) for v in cuts_by_axis_id.values()),
        "n_cuts_needed_scored": n_cuts_needed,
        "n_cuts_gated_scored": n_cuts_gated,
        "cut_fill_gated": round(n_cuts_gated / max(1, n_cuts_needed), 4),
        "separated_predicted_accepted_days": sep_pred,
        "separated_plain_accepted_days": sep_plain,
        "delta_vs_plain_accepted_days": sep_pred - sep_plain,
        "n_extent_gt_max_predicted_accepted": sum(
            int(r["n_extent_gt_max_predicted"])
            for r in day_rows
            if r.get("day_accepted") and r.get("n_extent_gt_max_predicted") is not None
        ),
        "n_extent_gt_max_plain_accepted": sum(
            int(r["n_extent_gt_max_plain"])
            for r in day_rows
            if r.get("day_accepted") and r.get("n_extent_gt_max_plain") is not None
        ),
        "parent_dataset": PARENT_AXIS,
        "note": (
            "Gated typed Group-C cuts → versioned successor of paragraph_axis; "
            "parent never mutated; main series + scope bar at entry. "
            + (
                f"Merge re-score of {len(selected)} date(s)."
                if merge_mode
                else "Full colliding-set rebuild."
            )
        ),
        **scope_meta(),
    }

    axis_path = None
    ledger_path = None
    if not args.dry_run:
        parent_rows = _load_parent_axis()
        built = apply_cuts_to_corpus_rows(
            parent_rows,
            cuts_by_axis_id,
            version=AXIS_VERSION_P5,
            parent_dataset=PARENT_AXIS,
        )
        summary["n_paragraphs_before"] = built["n_paragraphs_before"]
        summary["n_paragraphs_after"] = built["n_paragraphs_after"]
        summary["n_hosts_split_in_stream"] = built["n_hosts_split"]
        axis_path = save_semi_structured(
            built["axis"],
            logical_name=AXIS_OUTPUT,
            parent_sources=[PARENT_AXIS, CONCORDANCE],
            description=(
                "Track P P5 versioned paragraph-axis successor: parent "
                f"{PARENT_AXIS} with gated predicted Group-C interior cuts "
                f"(host_gate={args.host_gate}, day_gate={args.day_gate}). "
                "Provenance: parent_para_index / parent_char_start/end / axis_version. "
                "Main series 3185–3189 + scope bar; parent never mutated in place."
            ),
            script=__file__,
        )
        ledger_path = save_semi_structured(
            [{"record_type": "meta", **summary}, *day_rows],
            logical_name=LEDGER_OUTPUT,
            parent_sources=[PARENT_AXIS, CONCORDANCE, "s6c_p4_predicted_offset_eval"],
            description=(
                "Track P P5 ledger: per-day host/day gate outcomes for the predicted "
                "re-paragraph successor. Companion to paragraph_axis_p5_predicted_v1."
            ),
            script=__file__,
        )
    print(
        f"P5 axis successor: rescored {len(rescored)} day(s); "
        f"ledger days={n_days}; accepted={n_accepted}; "
        f"cuts applied={summary['n_cuts_applied']}; "
        f"merge={merge_mode}; reject={bool(args.reject)}; "
        + (
            f"ledger={ledger_path}; axis={axis_path}"
            if not args.dry_run
            else "dry-run (no write)"
        )
    )


if __name__ == "__main__":
    main()

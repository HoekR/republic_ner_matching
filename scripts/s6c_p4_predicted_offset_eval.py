#!/usr/bin/env python3
"""Track P next — predicted Group-C offsets through re-paragraph on colliding days.

P3 proved gold offsets unlock ``separated`` via ``segment_day_with_offsets``.
This step feeds *predicted* interior cuts from the typed Group C channel
(resolver inside a colliding paragraph — not a standalone detector) into the
same successor path on live main-series collisions.

Population: in-scope 3185–3189 concordance rows whose ``paragraph_start_index``
is shared (n_share ≥ 2). For each colliding host, need ``n_share - 1`` cuts;
``select_interior_cuts`` takes the channel's top-ranked interior candidates.
Day-level placement then runs ``segment_day_with_offsets`` and is scored with
``label_separation`` vs the pre-split baseline and ``uniform_start_paragraphs``
on the *successor* axis (exact agreement / separated counts only).

Does **not** persist a production axis successor — diagnostic + dataset write
only. Secret series sidelined.

Usage:
    uv run python -m scripts.s6c_p4_predicted_offset_eval --limit 40
    uv run python -m scripts.s6c_p4_predicted_offset_eval   # all colliding dates
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
from scripts.corpus_scope import in_scope, is_main_series
from scripts.s4_corpus_paragraph_predictions import axis_for_date
from scripts.s6c_group_c_typed_formula_channel import TypedFormulaChannel, build_channel
from scripts.s6c_gap_segmentation import segment_day
from scripts.s6c_reparagraph import (
    AXIS_VERSION_P3,
    extents_from_starts,
    segment_day_with_offsets,
    select_interior_cuts,
    starts_from_segment_positions,
)
from scripts.separated_accuracy_eval import label_separation, uniform_start_paragraphs
from scripts.synthetic_boundary_common import MAX_EXTENT_PARAGRAPHS

CONCORDANCE = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "s6c_p4_predicted_offset_eval"


def _inv_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value).strip()


def _main_concordance() -> pd.DataFrame:
    frame = load(CONCORDANCE)
    if not isinstance(frame, pd.DataFrame):
        frame = pd.DataFrame(frame)
    work = frame.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    work = work.loc[work["enriched_date"].map(in_scope)].copy()
    work["inventory_id"] = work["inventory_id"].map(_inv_str)
    work = work.loc[work["inventory_id"].map(is_main_series)].copy()
    return work


def colliding_hosts(placed: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, paragraph_start_index) with n_share ≥ 2."""
    work = placed.dropna(subset=["paragraph_start_index"]).copy()
    work["paragraph_start_index"] = work["paragraph_start_index"].astype(int)
    shares = (
        work.groupby(["enriched_date", "paragraph_start_index"], sort=False)
        .size()
        .rename("n_share")
        .reset_index()
    )
    return shares.loc[shares["n_share"] >= 2].copy()


def _dense_enriched_index(day: pd.DataFrame) -> dict[Any, int]:
    """Map concordance resolution_index → 0..k_e-1 in reading order."""
    ordered = sorted(int(x) for x in day["resolution_index"].tolist())
    return {res: rank for rank, res in enumerate(ordered)}


def propose_cuts_for_host(
    channel: TypedFormulaChannel,
    *,
    axis_id: str,
    text: str,
    n_share: int,
) -> dict[str, Any]:
    need = max(0, int(n_share) - 1)
    candidates = channel.candidates(axis_id, text)
    cuts = select_interior_cuts(candidates, need)
    return {
        "n_share": int(n_share),
        "n_needed": need,
        "n_candidates": len(candidates),
        "n_cuts": len(cuts),
        "cuts": cuts,
        "enough_candidates": len(candidates) >= need,
        "enough_cuts": len(cuts) >= need,
    }


def score_day_starts(
    starts: list[int | None],
    *,
    date: str,
    axis_count: int,
) -> dict[str, int]:
    spans = extents_from_starts(starts, axis_count)
    rows = []
    for index, (start, end) in enumerate(spans):
        if start is None or end is None:
            continue
        rows.append(
            {
                "enriched_date": date,
                "resolution_index": index,
                "paragraph_start_index": int(start),
                "paragraph_end_index": int(end),
            }
        )
    if not rows:
        return {
            "n_resolutions": len(starts),
            "n_separated": 0,
            "n_extent_gt_max": 0,
        }
    labelled = label_separation(pd.DataFrame(rows))
    extents = (labelled["paragraph_end_index"] - labelled["paragraph_start_index"] + 1).astype(int)
    return {
        "n_resolutions": len(starts),
        "n_separated": int(labelled["separated"].sum()),
        "n_extent_gt_max": int((extents > MAX_EXTENT_PARAGRAPHS).sum()),
    }


def process_day(
    date: str,
    day: pd.DataFrame,
    hosts: pd.DataFrame,
    axis: list[dict[str, Any]],
    channel: TypedFormulaChannel,
) -> dict[str, Any] | None:
    if not axis:
        return None
    k_e = int(len(day))
    dense = _dense_enriched_index(day)
    host_rows = hosts.loc[hosts["enriched_date"] == date]
    if host_rows.empty:
        return None

    proposals: list[dict[str, Any]] = []
    # enriched_rank -> (para, char_offset) for offset-bearing pins
    offset_pins: dict[int, tuple[int, int]] = {}
    for host in host_rows.itertuples(index=False):
        para = int(host.paragraph_start_index)
        if para < 0 or para >= len(axis):
            continue
        record = axis[para]
        text = str(record.get("text") or "")
        proposal = propose_cuts_for_host(
            channel,
            axis_id=str(record.get("axis_id") or f"{date}#p{para}"),
            text=text,
            n_share=int(host.n_share),
        )
        proposal["paragraph_start_index"] = para
        proposals.append(proposal)

        members = day.loc[
            day["paragraph_start_index"].astype("Int64") == para
        ].sort_values("resolution_index")
        ranks = [dense[int(r)] for r in members["resolution_index"].tolist()]
        # First sharer stays at offset 0; subsequent get predicted cuts in order.
        cuts = proposal["cuts"]
        for slot, enriched_rank in enumerate(ranks):
            if slot == 0:
                offset_pins[enriched_rank] = (para, 0)
            elif slot - 1 < len(cuts):
                offset_pins[enriched_rank] = (para, int(cuts[slot - 1]))
            else:
                # Under-proposed: leave unpinned for segment_gap on successor
                pass

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
            continue  # session-start sentinel owns (0, 0)
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
        # else: colliding member without a predicted cut — leave for gap fill on successor

    plain_positions = segment_day(k_e, len(axis), plain_alignments)
    plain_starts = starts_from_segment_positions(plain_positions)
    plain_score = score_day_starts(plain_starts, date=date, axis_count=len(axis))

    carried = segment_day_with_offsets(
        k_e,
        axis,
        alignments,
        version=AXIS_VERSION_P3,
        parent_dataset=CONCORDANCE,
    )
    successor_n = len(carried["successor"]["axis"])
    pred_starts = starts_from_segment_positions(carried["positions"])
    pred_score = score_day_starts(pred_starts, date=date, axis_count=successor_n)

    uniform = uniform_start_paragraphs(successor_n, k_e)
    uniform_score = score_day_starts(uniform, date=date, axis_count=successor_n)

    n_needed = sum(int(p["n_needed"]) for p in proposals)
    n_cuts = sum(int(p["n_cuts"]) for p in proposals)
    return {
        "record_type": "day_score",
        "enriched_date": date,
        "k_e": k_e,
        "n_colliding_hosts": len(proposals),
        "n_cuts_needed": n_needed,
        "n_cuts_predicted": n_cuts,
        "n_candidates_total": sum(int(p["n_candidates"]) for p in proposals),
        "hosts_enough_cuts": sum(1 for p in proposals if p["enough_cuts"]),
        "n_paragraphs_before": len(axis),
        "n_paragraphs_after": successor_n,
        "separated_plain": plain_score["n_separated"],
        "separated_predicted": pred_score["n_separated"],
        "separated_uniform_successor": uniform_score["n_separated"],
        "n_extent_gt_max_predicted": pred_score["n_extent_gt_max"],
        "beats_plain": pred_score["n_separated"] > plain_score["n_separated"],
        "beats_uniform": pred_score["n_separated"] > uniform_score["n_separated"],
        "delta_vs_plain": pred_score["n_separated"] - plain_score["n_separated"],
        "proposals": proposals,
    }


def summarise(scores: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(scores)
    if n == 0:
        return {"n_days": 0}
    sep_pred = sum(int(s["separated_predicted"]) for s in scores)
    sep_plain = sum(int(s["separated_plain"]) for s in scores)
    sep_uni = sum(int(s["separated_uniform_successor"]) for s in scores)
    k_e = sum(int(s["k_e"]) for s in scores)
    return {
        "n_days": n,
        "k_e_total": k_e,
        "n_colliding_hosts": sum(int(s["n_colliding_hosts"]) for s in scores),
        "n_cuts_needed": sum(int(s["n_cuts_needed"]) for s in scores),
        "n_cuts_predicted": sum(int(s["n_cuts_predicted"]) for s in scores),
        "cut_fill_rate": round(
            sum(int(s["n_cuts_predicted"]) for s in scores)
            / max(1, sum(int(s["n_cuts_needed"]) for s in scores)),
            4,
        ),
        "hosts_enough_cuts": sum(int(s["hosts_enough_cuts"]) for s in scores),
        "separated_predicted": sep_pred,
        "separated_plain": sep_plain,
        "separated_uniform_successor": sep_uni,
        "delta_vs_plain": sep_pred - sep_plain,
        "days_beating_plain": sum(1 for s in scores if s["beats_plain"]),
        "days_beating_uniform": sum(1 for s in scores if s["beats_uniform"]),
        "n_extent_gt_max_predicted": sum(int(s["n_extent_gt_max_predicted"]) for s in scores),
        "mean_paragraphs_after": round(
            sum(int(s["n_paragraphs_after"]) for s in scores) / n, 3
        ),
        "axis_version": AXIS_VERSION_P3,
        "max_extent_paragraphs": MAX_EXTENT_PARAGRAPHS,
        "note": (
            "Predicted typed Group-C cuts on colliding hosts → segment_day_with_offsets; "
            "separated vs plain (pre-split collisions) and uniform on successor; "
            "main series only; no production axis write."
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap colliding dates (0 = all). Prefer a small limit for smoke runs.",
    )
    parser.add_argument(
        "--channel",
        default="typed",
        choices=("typed", "typed-no-ordering", "typed-no-pattern", "typed-legacy-rank"),
    )
    args = parser.parse_args(argv)

    concordance = _main_concordance()
    placed = concordance.loc[concordance["paragraph_start_index"].notna()].copy()
    hosts = colliding_hosts(placed)
    dates = sorted(hosts["enriched_date"].unique())
    if args.limit > 0:
        dates = dates[: int(args.limit)]

    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    channel = build_channel(args.channel)

    scores: list[dict[str, Any]] = []
    for date in dates:
        day = concordance.loc[concordance["enriched_date"] == date].copy()
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        result = process_day(date, day, hosts, axis, channel)
        if result is not None:
            scores.append(result)

    summary = summarise(scores)
    summary.update(
        {
            "record_type": "summary",
            "track": "track-p-subparagraph-division",
            "step": "P4-predicted-offsets",
            "channel": args.channel,
            "limit": args.limit or None,
            "n_colliding_dates_in_corpus": int(hosts["enriched_date"].nunique()),
            "n_colliding_hosts_in_corpus": int(len(hosts)),
        }
    )
    # Drop heavy per-host detail from written day rows' nested proposals for size;
    # keep cut counts only.
    slim_scores = []
    for row in scores:
        slim = {k: v for k, v in row.items() if k != "proposals"}
        slim["host_cut_fill"] = [
            {
                "paragraph_start_index": p["paragraph_start_index"],
                "n_share": p["n_share"],
                "n_needed": p["n_needed"],
                "n_cuts": p["n_cuts"],
                "n_candidates": p["n_candidates"],
                "enough_cuts": p["enough_cuts"],
            }
            for p in row.get("proposals") or []
        ]
        slim_scores.append(slim)

    path = save_semi_structured(
        [{"record_type": "meta", **summary}, *slim_scores],
        logical_name=OUTPUT_DATASET,
        script=__file__,
    )
    print(
        f"P4 predicted-offset: {summary.get('n_days')} days; "
        f"cuts {summary.get('n_cuts_predicted')}/{summary.get('n_cuts_needed')} "
        f"(fill={summary.get('cut_fill_rate')}); "
        f"separated pred/plain/uniform="
        f"{summary.get('separated_predicted')}/"
        f"{summary.get('separated_plain')}/"
        f"{summary.get('separated_uniform_successor')}; "
        f"Δ vs plain={summary.get('delta_vs_plain')}; "
        f"extent>3={summary.get('n_extent_gt_max_predicted')}; wrote {path}"
    )


if __name__ == "__main__":
    main()

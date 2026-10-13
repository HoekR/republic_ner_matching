#!/usr/bin/env python3
"""Print PLAN.md acceptance overview from Tier V / O metrics.

Default reads the last written metric datasets (fast). ``--refresh`` rebuilds
Tier V + the span table in memory from the live concordance (no write unless
``--write`` is also passed to the underlying metric scripts — this script itself
only optionally writes ``project_overview``).

Usage:
    uv run python scripts/project_overview.py
    uv run python scripts/project_overview.py --refresh
    uv run python scripts/project_overview.py --refresh --write
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, is_main_series, scope_meta

CONCORDANCE = "resolution_concordance_1626_1630"
DAY_STATUS = "s4_day_status_resolution"
V_DATASET = "metrics_nihil_actum_invariant"
SPAN_DATASET = "metrics_separation_span_table"
LOCAL_DATASET = "metrics_local_inventory_ceiling"
OUTPUT_DATASET = "project_overview"

CEILING = 11_644
PRIMARY_SHARE = 0.50
STRETCH_SHARE = 0.75
LOCAL_SHARE = 0.50
SPANS_N = 6
SPANS_DAYS = 180
# Global spans adjudicated at gap=2 (PLAN.md / DECISIONS.md baseline 4/177).
SPANS_GAP = 2
MAIN_INVENTORIES = ("3185", "3186", "3187", "3188", "3189")
# Phase-2 unlock labels (published approx.; dual ceiling with historical 11,644).
# See docs/DECISIONS.md 2026-10-13 — optimum is splitting-conditional.
SPLIT_UNLOCK_PIGEONHOLE = 1_886
SPLIT_UNLOCK_COLLISION = 4_516
# RETIRED as a live denominator (2026-10-13): same-day axis zeros miscounted
# displaced HTR as absent. Kept only so old caches / quotes can be recognized.
RETIRED_HARD_STRUCTURAL_NO_HTR = 5_590


def _records(name: str) -> list[dict[str, Any]]:
    raw = load(name)
    if isinstance(raw, pd.DataFrame):
        return raw.to_dict(orient="records")
    return list(raw)


def _meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return next(r for r in rows if r.get("record_type") == "meta")


def _gap_summaries(span_rows: list[dict[str, Any]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    if meta.get("gap_summaries"):
        return list(meta["gap_summaries"])
    return [r for r in span_rows if r.get("record_type") == "gap_summary"]


def refresh_v_and_span() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rebuild Tier V + span table in memory from live concordance."""
    from scripts.metrics_nihil_actum_invariant import (
        build_day_series,
        build_output_records as build_v_records,
        ledger_nihil_session_violations,
    )
    from scripts.metrics_separation_span_table import (
        attach_separation,
        build_output_records as build_span_records,
        count_separated_per_day,
        load_day_series,
    )

    concordance = load(CONCORDANCE)
    if not isinstance(concordance, pd.DataFrame):
        concordance = pd.DataFrame(concordance)

    day_status_rows = load(DAY_STATUS)
    if isinstance(day_status_rows, pd.DataFrame):
        day_status_rows = day_status_rows.to_dict(orient="records")

    day_series = build_day_series(concordance)
    v_rows = build_v_records(day_series, ledger_nihil_session_violations(day_status_rows))
    parent_meta, v_days = load_day_series(v_rows)
    separated = count_separated_per_day(concordance)
    day_frame = attach_separation(v_days, separated)

    n_all = int(len(concordance))
    day_status = concordance["day_status"].astype(str)
    n_htr = int((day_status != "missing_htr").sum())
    span_rows = build_span_records(
        parent_meta,
        day_frame,
        n_all_resolutions=n_all,
        n_htr_reachable=n_htr,
    )
    return v_rows, span_rows


def refresh_local() -> list[dict[str, Any]]:
    """Rebuild per-inventory Local criterion from live concordance + axis."""
    from scripts.metrics_local_inventory_ceiling import (
        EXPECTED_CORPUS_CEILING,
        EXPECTED_NO_HTR_DATE_COUNT,
        LOCAL_SHARE_THRESHOLD,
        inventory_lookup,
        per_date_ceiling,
    )
    from scripts.metrics_separation_span_table import count_separated_per_day

    concordance = load(CONCORDANCE)
    if not isinstance(concordance, pd.DataFrame):
        concordance = pd.DataFrame(concordance)
    axis = load("paragraph_axis_1626_1630")
    ceiling = per_date_ceiling(concordance, axis)
    n_no_htr = int((ceiling["paragraph_count"] == 0).sum())
    corpus_ceiling = int(ceiling["ceiling_day"].sum())
    separated_per_day = count_separated_per_day(concordance)
    inv_by_date = inventory_lookup(concordance)
    merged = ceiling.merge(
        separated_per_day[["enriched_date", "separated_count"]],
        on="enriched_date",
        how="left",
    )
    merged["separated_count"] = merged["separated_count"].fillna(0).astype(int)
    merged["inventory_id"] = (
        merged["enriched_date"].map(inv_by_date).map(_inventory_id_str)
    )
    by_inventory = (
        merged.groupby("inventory_id")
        .agg(
            n_dates=("enriched_date", "size"),
            ceiling=("ceiling_day", "sum"),
            separated=("separated_count", "sum"),
        )
        .reset_index()
    )
    by_inventory["separated_share_of_ceiling"] = (
        by_inventory["separated"] / by_inventory["ceiling"]
    ).where(by_inventory["ceiling"] > 0, 0.0).round(4)
    by_inventory["local_criterion_met"] = (
        by_inventory["separated_share_of_ceiling"] >= LOCAL_SHARE_THRESHOLD
    )
    meta = {
        "record_type": "meta",
        "corpus_ceiling_computed": corpus_ceiling,
        "corpus_ceiling_expected": EXPECTED_CORPUS_CEILING,
        "no_htr_dates_computed": n_no_htr,
        "no_htr_dates_expected": EXPECTED_NO_HTR_DATE_COUNT,
        "n_inventories": int(len(by_inventory)),
        "n_inventories_meeting_local": int(by_inventory["local_criterion_met"].sum()),
        "local_share_threshold": LOCAL_SHARE_THRESHOLD,
    }
    inv_rows = [
        {"record_type": "inventory", **row}
        for row in by_inventory.to_dict(orient="records")
    ]
    return [meta, *inv_rows]


def _active_focus() -> str:
    state_md = PROJECT_ROOT / "docs" / "STATE.md"
    if state_md.exists():
        text = state_md.read_text(encoding="utf-8")
        m = re.search(
            r"## Active Focus\s*\n+(.*?)(?:\n## |\Z)",
            text,
            flags=re.DOTALL,
        )
        if m:
            return " ".join(m.group(1).strip().split())
    state_json = PROJECT_ROOT / "docs" / "state.json"
    if state_json.exists():
        import json

        data = json.loads(state_json.read_text(encoding="utf-8"))
        focus = data.get("active_focus")
        if focus:
            return str(focus).strip()
    return "(no Active Focus recorded)"


def _plan_next() -> str:
    """Last ``**NEXT`` bullet in PLAN.md (earlier tracks leave stale NEXT lines)."""
    plan = PROJECT_ROOT / "PLAN.md"
    if not plan.exists():
        return ""
    hits = [
        line.strip().lstrip("- ").strip()
        for line in plan.read_text(encoding="utf-8").splitlines()
        if "**NEXT" in line
    ]
    return hits[-1] if hits else ""


def _inventory_id_str(value: Any) -> str:
    """Normalise float inventory ids (3185.0) to digit strings."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def _tick(ok: bool) -> str:
    return "MET" if ok else "not met"


def _session_of_flat_id(flat_id: Any) -> str:
    text = str(flat_id or "")
    if "-resolution-" in text:
        return text.split("-resolution-", 1)[0]
    return text.rsplit("#", 1)[0]


def main_series_htr_account(concordance: pd.DataFrame) -> dict[str, Any]:
    """Live main-series HTR + session-resolved ceiling (replaces retired no-HTR mass).

    User 2026-10-09: concordance ``missing_htr`` is displaced HTR (except small
    mistakes). Capacity is ``min(k_e, paragraphs_on_resolved_session)`` per date,
    not same-calendar-day axis zeros. Secret 4562/4861 stay out.

    Theoretical max under re-paragraph = main ``k_e`` minus nihil-only dates
    (every non-nihil day has a session whose paragraphs can be split until each
    resolution can own a start). Pigeonhole unlock = that max minus today's
    session-resolved ceiling.
    """
    work = concordance.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    work = work.loc[work["enriched_date"].map(in_scope)].copy()
    work["inventory_id"] = work["inventory_id"].map(_inventory_id_str)
    main = work.loc[work["inventory_id"].map(is_main_series)].copy()

    day_status = (
        main["day_status"].astype(str) if "day_status" in main.columns else pd.Series(dtype=str)
    )
    n_missing_htr = int((day_status == "missing_htr").sum()) if len(day_status) else 0

    by_date = main.groupby("enriched_date", sort=False).agg(
        k_e=("enriched_date", "size"),
        n_resolved_session=("resolved_session_id", lambda s: int(s.notna().sum())),
        statuses=("day_status", lambda s: tuple(sorted(set(s.astype(str))))),
    )
    # Modal resolved session per date (production pin).
    sess = (
        main.dropna(subset=["resolved_session_id"])
        .groupby("enriched_date")["resolved_session_id"]
        .agg(lambda s: str(s.astype(str).value_counts().index[0]))
    )
    by_date = by_date.join(sess.rename("resolved_session_id"), how="left")

    no_session = by_date.loc[by_date["n_resolved_session"] == 0]
    status_mix = {
        "|".join(statuses): int((no_session["statuses"] == statuses).sum())
        for statuses in sorted(set(no_session["statuses"]))
    }

    axis = load("paragraph_axis_1626_1630")
    same_day = (
        pd.Series([str(r.get("date") or "")[:10] for r in axis])
        .value_counts()
        .rename("same_day_paras")
    )
    session_paras = (
        pd.Series([_session_of_flat_id(r.get("flat_id") or r.get("axis_id")) for r in axis])
        .value_counts()
        .rename("session_paras")
    )
    frame = by_date.join(same_day, how="left")
    frame["same_day_paras"] = frame["same_day_paras"].fillna(0).astype(int)
    frame["session_paras"] = (
        frame["resolved_session_id"].map(session_paras).fillna(0).astype(int)
    )
    frame["old_ceiling_day"] = frame[["k_e", "same_day_paras"]].min(axis=1).astype(int)
    frame["session_ceiling_day"] = frame[["k_e", "session_paras"]].min(axis=1).astype(int)
    # Crowded: session has text but fewer paragraphs than resolutions.
    crowded = frame.loc[(frame["session_paras"] > 0) & (frame["k_e"] > frame["session_paras"])]
    pigeonhole_blocked = int((crowded["k_e"] - crowded["session_paras"]).sum())

    same_day_zero = frame.loc[frame["same_day_paras"] == 0]
    displaced_as_zero = same_day_zero.loc[same_day_zero["n_resolved_session"] > 0]
    # Capacity the old same-day formula dropped but session capacity recovers.
    displaced_into_ceiling = int(
        displaced_as_zero["session_ceiling_day"].sum()
    ) if len(displaced_as_zero) else 0

    main_k_e = int(len(main))
    nihil_k_e = int(no_session["k_e"].sum()) if len(no_session) else 0
    session_ceiling = int(frame["session_ceiling_day"].sum())
    old_same_day_ceiling = int(frame["old_ceiling_day"].sum())
    # Every non-nihil main-series resolution is reachable once re-paragraph can
    # create as many starts as needed inside its session's text.
    theoretical_max = main_k_e - nihil_k_e
    split_unlock_pigeonhole = max(0, theoretical_max - session_ceiling)

    placed = main.loc[main["paragraph_start_index"].notna()].copy()
    share_counts = (
        placed.groupby(["enriched_date", "paragraph_start_index"], sort=False)[
            "paragraph_start_index"
        ].transform("size")
        if len(placed)
        else pd.Series(dtype=int)
    )
    collision_rows = int((share_counts > 1).sum()) if len(share_counts) else 0

    return {
        "main_series_rows": main_k_e,
        "main_series_dates": int(main["enriched_date"].nunique()) if len(main) else 0,
        "main_series_missing_htr_rows": n_missing_htr,
        "main_series_no_resolved_session_dates": int(len(no_session)),
        "main_series_no_resolved_session_k_e": nihil_k_e,
        "main_series_no_resolved_session_status_mix": status_mix,
        "hard_structural_nihil_k_e": nihil_k_e,
        "same_day_axis_zero_dates": int(len(same_day_zero)),
        "same_day_axis_zero_k_e": int(same_day_zero["k_e"].sum()) if len(same_day_zero) else 0,
        "same_day_axis_zero_but_resolved_session_dates": int(len(displaced_as_zero)),
        "same_day_axis_zero_but_resolved_session_k_e": (
            int(displaced_as_zero["k_e"].sum()) if len(displaced_as_zero) else 0
        ),
        "displaced_recovered_into_ceiling_k_e": displaced_into_ceiling,
        "phase1_ceiling_historical_same_day": CEILING,
        "main_series_ceiling_same_day": old_same_day_ceiling,
        "main_series_ceiling_session_resolved": session_ceiling,
        "main_series_theoretical_max_separated": theoretical_max,
        "split_unlock_pigeonhole_session": split_unlock_pigeonhole,
        "split_unlock_pigeonhole_days": int(len(crowded)),
        "split_unlock_collision_placed_rows": collision_rows,
        "retired_hard_structural_no_htr": RETIRED_HARD_STRUCTURAL_NO_HTR,
        "htr_account_note": (
            "Main-series missing_htr=0; retired 5,590 'no HTR' was displaced HTR "
            "(user 2026-10-09). Live ceiling = sum min(k_e, session_paragraphs); "
            "hard floor = nihil_actum only; theoretical max = main k_e − nihil. "
            "Secret 4562/4861 out."
        ),
    }


def build_overview(
    *,
    refresh: bool,
) -> list[dict[str, Any]]:
    source = "refresh" if refresh else "cached"
    if refresh:
        v_rows, span_rows = refresh_v_and_span()
        local_rows = refresh_local()
    else:
        v_rows = _records(V_DATASET)
        span_rows = _records(SPAN_DATASET)
        local_rows = _records(LOCAL_DATASET)

    v_meta = _meta(v_rows)
    span_meta = _meta(span_rows)
    local_meta = _meta(local_rows)
    gaps = _gap_summaries(span_rows, span_meta)
    gap2 = next((g for g in gaps if int(g["gap"]) == SPANS_GAP), {})

    separated = int(span_meta["n_separated"])
    ceiling = int(span_meta.get("ceiling_separable") or CEILING)
    share = separated / ceiling if ceiling else 0.0
    solid = int(span_meta["n_solid_days"])
    n_days = int(span_meta["n_days"])

    primary_ok = share >= PRIMARY_SHARE
    stretch_ok = share >= STRETCH_SHARE
    spans_n = int(gap2.get("global_spans_n_spans") or 0)
    spans_days = int(gap2.get("global_spans_days_covered") or 0)
    spans_ok = bool(gap2.get("global_spans_criterion_met")) or (
        spans_n >= SPANS_N and spans_days >= SPANS_DAYS
    )

    inv_rows = []
    for r in local_rows:
        if r.get("record_type") != "inventory":
            continue
        inv = _inventory_id_str(r.get("inventory_id"))
        if inv not in MAIN_INVENTORIES:
            continue
        inv_rows.append({**r, "inventory_id": inv})
    main_met = [r for r in inv_rows if bool(r.get("local_criterion_met"))]
    local_ok = len(main_met) == len(MAIN_INVENTORIES)

    criteria = [
        {
            "record_type": "criterion",
            "id": "global_primary",
            "label": f"Global primary ≥ {PRIMARY_SHARE:.0%} of ceiling",
            "value": f"{separated:,} = {share:.1%}",
            "threshold": f"≥ {int(PRIMARY_SHARE * ceiling):,}",
            "met": primary_ok,
        },
        {
            "record_type": "criterion",
            "id": "global_stretch",
            "label": f"Global stretch ≥ {STRETCH_SHARE:.0%} of ceiling",
            "value": f"{separated:,} = {share:.1%}",
            "threshold": f"≥ {int(STRETCH_SHARE * ceiling):,}",
            "met": stretch_ok,
        },
        {
            "record_type": "criterion",
            "id": "global_spans",
            "label": f"Global spans ≥ {SPANS_N} / ≥ {SPANS_DAYS}d (gap={SPANS_GAP})",
            "value": f"{spans_n} spans / {spans_days} days",
            "threshold": f"≥ {SPANS_N} / ≥ {SPANS_DAYS}",
            "met": spans_ok,
            "longest": gap2.get("longest_calendar_days"),
        },
        {
            "record_type": "criterion",
            "id": "local",
            "label": f"Local ≥ {LOCAL_SHARE:.0%} of inventory ceiling (3185–3189)",
            "value": f"{len(main_met)}/{len(MAIN_INVENTORIES)} inventories",
            "threshold": "all five main-series",
            "met": local_ok,
        },
    ]

    focus = _active_focus()
    nxt = _plan_next()
    phase1_residual = max(0, ceiling - separated)

    concordance = load(CONCORDANCE)
    if not isinstance(concordance, pd.DataFrame):
        concordance = pd.DataFrame(concordance)
    htr_account = main_series_htr_account(concordance)

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "source": source,
            "ceiling": ceiling,
            "phase1_ceiling": ceiling,
            "phase1_ceiling_note": (
                "Historical same-day pigeonhole (MET targets). Superseded as live "
                "denominator by main_series_ceiling_session_resolved."
            ),
            "phase1_separated": separated,
            "phase1_residual": phase1_residual,
            # Live main-series account (2026-10-13 recalculation).
            **htr_account,
            # Keep approx collision label for dual reporting; pigeonhole from live account.
            "split_unlock_pigeonhole": htr_account["split_unlock_pigeonhole_session"],
            "split_unlock_collision": htr_account["split_unlock_collision_placed_rows"],
            "split_unlock_collision_historical": SPLIT_UNLOCK_COLLISION,
            "optimum_depends_on_splitting": True,
            "phase1_closed_met": all(c["met"] for c in criteria),
            "n_separated": separated,
            "separated_share_of_ceiling": round(share, 4),
            "separated_share_of_session_ceiling": round(
                separated / htr_account["main_series_ceiling_session_resolved"], 4
            )
            if htr_account["main_series_ceiling_session_resolved"]
            else None,
            "separated_share_of_theoretical_max": round(
                separated / htr_account["main_series_theoretical_max_separated"], 4
            )
            if htr_account["main_series_theoretical_max_separated"]
            else None,
            "n_solid_days": solid,
            "n_days": n_days,
            "invariant_passed": bool(v_meta.get("invariant_passed")),
            "n_violations": int(v_meta.get("n_violations") or 0),
            "n_nihil_days": int(v_meta.get("n_nihil_days") or 0),
            "all_criteria_met": all(c["met"] for c in criteria),
            "active_focus": focus,
            "plan_next": nxt,
            **scope_meta(),
        },
        *criteria,
        *[
            {
                "record_type": "inventory",
                "inventory_id": str(r.get("inventory_id")),
                "separated": int(r.get("separated") or 0),
                "ceiling": int(r.get("ceiling") or 0),
                "separated_share_of_ceiling": float(r.get("separated_share_of_ceiling") or 0),
                "local_criterion_met": bool(r.get("local_criterion_met")),
            }
            for r in sorted(inv_rows, key=lambda x: str(x.get("inventory_id")))
        ],
        *[
            {
                "record_type": "gap_summary",
                "gap": int(g["gap"]),
                "spans_at_30": int(g.get("global_spans_n_spans") or 0),
                "days_covered": int(g.get("global_spans_days_covered") or 0),
                "criterion_met": bool(g.get("global_spans_criterion_met")),
                "longest": int(g.get("longest_calendar_days") or 0),
            }
            for g in gaps
        ],
    ]
    return rows


def format_overview(rows: list[dict[str, Any]]) -> str:
    meta = _meta(rows)
    criteria = [r for r in rows if r["record_type"] == "criterion"]
    inventories = [r for r in rows if r["record_type"] == "inventory"]
    gaps = [r for r in rows if r["record_type"] == "gap_summary"]

    phase1_ceil = int(meta.get("phase1_ceiling") or meta["ceiling"])
    phase1_sep = int(meta.get("phase1_separated") or meta["n_separated"])
    phase1_res = int(meta.get("phase1_residual") or max(0, phase1_ceil - phase1_sep))
    sess_ceil = int(meta.get("main_series_ceiling_session_resolved") or 0)
    theor_max = int(meta.get("main_series_theoretical_max_separated") or 0)
    nihil_k = int(meta.get("hard_structural_nihil_k_e") or meta.get("n_nihil_days") or 0)
    lines: list[str] = [
        "republic_ner_matching — acceptance overview",
        (
            f"source={meta['source']}  "
            f"corpus_scope_last_date={meta.get('corpus_scope_last_date') or '?'}"
        ),
        "",
        "Goal: separate resolutions into HTR (session-relative archival address).",
        (
            f"Phase-1 ceiling (historical same-day): {phase1_ceil:,} — MET targets only; "
            "not the live denominator."
        ),
        (
            f"Live main-series ceiling (session-resolved): {sess_ceil:,} "
            f"of {int(meta.get('main_series_rows') or 0):,} k_e "
            f"(theoretical max {theor_max:,} = k_e − {nihil_k:,} nihil)."
        ),
        "Optimum depends on splitting (Phase-2 re-paragraph) — dual ceilings, not one %.",
        "",
        "Phase 1 acceptance (CLOSED when all MET; % vs historical 11,644)",
        f"{'criterion':<48} {'value':<28} {'status':>8}",
        "-" * 88,
    ]
    for c in criteria:
        lines.append(
            f"{c['label']:<48} {c['value']:<28} {_tick(c['met']):>8}"
        )
    sess_share = meta.get("separated_share_of_session_ceiling")
    theor_share = meta.get("separated_share_of_theoretical_max")
    lines.extend([
        "",
        f"Phase-1 all four: {_tick(bool(meta['all_criteria_met']))}",
        (
            f"Separated: {meta['n_separated']:,} "
            f"({meta['separated_share_of_ceiling']:.1%} of historical 11,644"
            + (
                f"; {sess_share:.1%} of session ceiling {sess_ceil:,}"
                if sess_share is not None and sess_ceil
                else ""
            )
            + (
                f"; {theor_share:.1%} of theoretical max {theor_max:,}"
                if theor_share is not None and theor_max
                else ""
            )
            + ")"
        ),
        f"Phase-1 residual vs historical 11,644: {phase1_res:,}",
        (
            f"Main-series missing_htr rows: "
            f"{int(meta.get('main_series_missing_htr_rows') or 0)} "
            f"(retired 'no HTR' {int(meta.get('retired_hard_structural_no_htr') or RETIRED_HARD_STRUCTURAL_NO_HTR):,} "
            f"was displaced HTR)"
        ),
        f"Solid days: {meta['n_solid_days']}/{meta['n_days']}",
        f"Tier V: invariant_passed={meta['invariant_passed']}  "
        f"nihil_days={meta['n_nihil_days']}  violations={meta['n_violations']}",
        "",
        "Horizons (main series 3185–3189; live recalculation)",
        f"  hard structural (nihil only): {nihil_k:,} k_e",
        f"  session-resolved ceiling: {sess_ceil:,}",
        (
            f"  split unlock pigeonhole (→ theoretical max): "
            f"{int(meta.get('split_unlock_pigeonhole') or 0):,} "
            f"on {int(meta.get('split_unlock_pigeonhole_days') or 0)} crowded days"
        ),
        f"  theoretical max separated: {theor_max:,}",
        (
            f"  collision among placed (diagnostic): "
            f"{int(meta.get('split_unlock_collision') or 0):,} rows sharing a start"
        ),
        (
            f"  displaced recovered into ceiling vs same-day-zero: "
            f"{int(meta.get('displaced_recovered_into_ceiling_k_e') or 0):,}"
        ),
        "",
        "Spans@30 by gap",
    ])
    for g in gaps:
        lines.append(
            f"  gap={g['gap']}: spans={g['spans_at_30']} days={g['days_covered']} "
            f"met={g['criterion_met']} longest={g['longest']}"
        )
    if inventories:
        lines.extend(["", "Local (main series 3185–3189)"])
        for r in inventories:
            lines.append(
                f"  {r['inventory_id']}: {r['separated']:,}/{r['ceiling']:,} "
                f"= {r['separated_share_of_ceiling']:.1%}  "
                f"{_tick(r['local_criterion_met'])}"
            )
    lines.extend(["", "Active focus", f"  {meta.get('active_focus') or '(none)'}"])
    if meta.get("plan_next"):
        lines.extend(["", "PLAN NEXT", f"  {meta['plan_next']}"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="rebuild Tier V + spans + local from live concordance (in memory)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"persist overview records as {OUTPUT_DATASET}",
    )
    args = parser.parse_args(argv)

    rows = build_overview(refresh=args.refresh)
    print(format_overview(rows))

    if args.write:
        path = save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[V_DATASET, SPAN_DATASET, LOCAL_DATASET, CONCORDANCE],
            description=(
                "PLAN.md acceptance overview: Phase-1 criteria (CLOSED when MET) plus "
                "Phase-2 splitting-conditional dual ceilings (phase1_residual, "
                "split_unlock_pigeonhole/collision), Tier V, solid days, Active Focus."
            ),
        )
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()

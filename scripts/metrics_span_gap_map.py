#!/usr/bin/env python3
"""Tier O — span-gap geography: why solid days fail to form ≥30d runs.

Parents on ``metrics_separation_span_table`` day rows (solid flags already
computed). Classifies every non-solid session-day, enumerates the gaps between
consecutive solid days, and reports which interrupter classes dominate those
breaks. Optionally flags Tier D drift candidates and S6c severe-collapse days
so the map can answer whether the deferred 79-day autopsy is implicated.

Also reports counterfactual longest runs if each interrupter class were
bridgeable (tolerated forever inside a run without counting toward ``max_gap``).

Usage:
    uv run python scripts/metrics_span_gap_map.py
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
from scripts.metrics_separation_span_table import (
    PRIMARY_LENGTH_THRESHOLD,
    find_solid_runs,
    summarize_runs,
)

PARENT_O_DATASET = "metrics_separation_span_table"
DRIFT_DATASET = "metrics_ke_drift_diagnostic"
CORPUS_PRED_DATASET = "s4_corpus_paragraph_predictions"
OUTPUT_DATASET = "metrics_span_gap_map"

SEVERE_COLLAPSE_MIN = 7
# Primary interrupter classes (mutually exclusive, priority order).
NONSOLID_CLASSES = (
    "v_violation",
    "nihil_actum",
    "missing_htr",
    "weak_separation",
    "other",
)


def load_day_frame(records: list[dict[str, Any]]) -> tuple[dict[str, Any], pd.DataFrame]:
    """Split Tier O output into meta + day frame."""
    meta = next((r for r in records if r.get("record_type") == "meta"), None)
    if meta is None:
        raise ValueError(f"{PARENT_O_DATASET} has no meta record")
    days = [r for r in records if r.get("record_type") == "day"]
    if not days:
        raise ValueError(f"{PARENT_O_DATASET} has no day records")
    frame = pd.DataFrame(days)
    required = {
        "enriched_date",
        "k_e_signal",
        "day_status",
        "is_nihil_actum",
        "invariant_ok",
        "separated_share",
        "is_solid",
        "separated_count",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"day series missing columns: {sorted(missing)}")
    return meta, frame


def classify_nonsolid_reason(row: pd.Series | dict[str, Any]) -> str | None:
    """Mutually exclusive reason a session-day is not solid; None if solid."""
    get = row.get if isinstance(row, dict) else lambda k, default=None: row[k] if k in row.index else default
    if bool(get("is_solid")):
        return None
    if not bool(get("invariant_ok", True)):
        return "v_violation"
    if bool(get("is_nihil_actum")):
        return "nihil_actum"
    status = str(get("day_status") or "")
    if status == "missing_htr":
        return "missing_htr"
    if status == "resolved_auto" or int(get("k_e_signal") or 0) > 0:
        return "weak_separation"
    return "other"


def classify_nonsolid_series(frame: pd.DataFrame) -> pd.Series:
    """Vectorized interrupter-class labels; None/NA for solid days."""
    solid = frame["is_solid"].astype(bool)
    invariant_ok = frame["invariant_ok"].astype(bool)
    nihil = frame["is_nihil_actum"].astype(bool)
    status = frame["day_status"].astype(str)
    k_e_signal = frame["k_e_signal"].fillna(0).astype(int)

    labels = pd.Series(pd.NA, index=frame.index, dtype=object)
    nonsolid = ~solid
    labels.loc[nonsolid & ~invariant_ok] = "v_violation"
    remaining = nonsolid & labels.isna()
    labels.loc[remaining & nihil] = "nihil_actum"
    remaining = nonsolid & labels.isna()
    labels.loc[remaining & (status == "missing_htr")] = "missing_htr"
    remaining = nonsolid & labels.isna()
    labels.loc[remaining & ((status == "resolved_auto") | (k_e_signal > 0))] = "weak_separation"
    remaining = nonsolid & labels.isna()
    labels.loc[remaining] = "other"
    return labels


def severe_collapse_dates(
    predictions: list[dict[str, Any]],
    *,
    min_on_paragraph: int = SEVERE_COLLAPSE_MIN,
) -> set[str]:
    """Dates where ≥ ``min_on_paragraph`` predicted resolutions share one paragraph start.

    Reconstructs starts as ``[0] + cut_indices`` truncated to ``k_e`` (S6c emits
    ``k_e - 1`` cuts). Historical count was 79/1059; recomputed count may differ
    slightly after concordance wiring added predicted days.
    """
    out: set[str] = set()
    for row in predictions:
        if row.get("status") != "predicted":
            continue
        k_e = int(row.get("k_e") or 0)
        if k_e < min_on_paragraph:
            continue
        cuts = [
            int(b["paragraph_stream_index"])
            for b in (row.get("boundaries") or [])
            if b.get("paragraph_stream_index") is not None
        ]
        starts = ([0] + cuts)[:k_e]
        if not starts:
            continue
        if max(Counter(starts).values()) >= min_on_paragraph:
            out.add(str(row.get("date") or "")[:10])
    return out


def drift_candidate_dates(records: list[dict[str, Any]]) -> set[str]:
    """Dates flagged by Tier D drift diagnostic."""
    out: set[str] = set()
    for row in records:
        rtype = row.get("record_type")
        if rtype == "candidate":
            out.add(str(row.get("enriched_date") or "")[:10])
        elif rtype == "day" and bool(row.get("drift_flag")):
            out.add(str(row.get("enriched_date") or "")[:10])
    return {d for d in out if d}


def annotate_days(
    day_frame: pd.DataFrame,
    *,
    drift_dates: set[str],
    collapse_dates: set[str],
) -> pd.DataFrame:
    """Attach interrupter class + orthogonal flags."""
    work = day_frame.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    work["nonsolid_class"] = classify_nonsolid_series(work)
    work["is_drift_candidate"] = work["enriched_date"].isin(drift_dates)
    work["is_severe_collapse"] = work["enriched_date"].isin(collapse_dates)
    return work.sort_values("enriched_date").reset_index(drop=True)


def find_inter_solid_gaps(day_frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Gaps between consecutive solid session-days (the breaks that split gap=0 runs).

    Each gap is the open interval of non-solid session-days between one solid day
    and the next solid day later in the ordered Tier O series. Leading/trailing
    non-solid stretches (before the first / after the last solid) are omitted —
    they cannot stitch two solids together.
    """
    work = day_frame.copy()
    work["period"] = pd.PeriodIndex(work["enriched_date"].astype(str).str.slice(0, 10), freq="D")
    work = work.sort_values("period").reset_index(drop=True)

    solid_indices = [i for i, solid in enumerate(work["is_solid"].astype(bool)) if solid]
    gaps: list[dict[str, Any]] = []
    for left_i, right_i in zip(solid_indices, solid_indices[1:], strict=False):
        if right_i == left_i + 1:
            # Adjacent solids — no interrupter session-day (calendar hole still possible).
            left_period = work.iloc[left_i]["period"]
            right_period = work.iloc[right_i]["period"]
            calendar_gap = int(right_period.ordinal - left_period.ordinal) - 1
            gaps.append(
                {
                    "left_solid_date": str(work.iloc[left_i]["enriched_date"])[:10],
                    "right_solid_date": str(work.iloc[right_i]["enriched_date"])[:10],
                    "n_nonsolid_session_days": 0,
                    "calendar_gap_days": calendar_gap,
                    "class_counts": {},
                    "dominant_class": "adjacent_solid",
                    "has_drift_candidate": False,
                    "has_severe_collapse": False,
                    "nonsolid_dates": [],
                }
            )
            continue

        between = work.iloc[left_i + 1 : right_i]
        class_counts = (
            between["nonsolid_class"].fillna("other").astype(str).value_counts().to_dict()
        )
        class_counts = {str(k): int(v) for k, v in class_counts.items()}
        if class_counts:
            # Tie-break by NONSOLID_CLASSES declaration order.
            dominant = max(
                class_counts,
                key=lambda c: (
                    class_counts[c],
                    -NONSOLID_CLASSES.index(c) if c in NONSOLID_CLASSES else -99,
                ),
            )
        else:
            dominant = "other"
        left_period = work.iloc[left_i]["period"]
        right_period = work.iloc[right_i]["period"]
        calendar_gap = int(right_period.ordinal - left_period.ordinal) - 1
        gaps.append(
            {
                "left_solid_date": str(work.iloc[left_i]["enriched_date"])[:10],
                "right_solid_date": str(work.iloc[right_i]["enriched_date"])[:10],
                "n_nonsolid_session_days": int(len(between)),
                "calendar_gap_days": calendar_gap,
                "class_counts": class_counts,
                "dominant_class": dominant,
                "has_drift_candidate": bool(between["is_drift_candidate"].any()),
                "has_severe_collapse": bool(between["is_severe_collapse"].any()),
                "nonsolid_dates": between["enriched_date"].astype(str).str.slice(0, 10).tolist(),
            }
        )
    return gaps


def longest_under_bridge(
    day_frame: pd.DataFrame,
    *,
    bridge_class: str,
) -> dict[str, Any]:
    """Recompute gap=0 solid runs treating ``bridge_class`` non-solids as transparent.

    Transparent days do not break a run and do not count as solid; the run still
    must start and end on a true solid day (``find_solid_runs`` semantics via a
    temporary ``is_solid`` mask that keeps bridged days non-solid but removes them
    from the series for gap purposes).
    """
    work = day_frame.copy()
    # Drop bridged non-solids from the session-day sequence so adjacent solids
    # across that class become contiguous for gap=0 run finding.
    keep = work["is_solid"].astype(bool) | (work["nonsolid_class"] != bridge_class)
    trimmed = work.loc[keep].reset_index(drop=True)
    runs = find_solid_runs(trimmed, max_gap=0)
    summary = summarize_runs(runs, max_gap=0)
    return {
        "bridge_class": bridge_class,
        "n_days_bridged": int((work["nonsolid_class"] == bridge_class).sum()),
        "longest_calendar_days": summary["longest_calendar_days"],
        "global_spans_n_spans": summary["global_spans_n_spans"],
        "global_spans_days_covered": summary["global_spans_days_covered"],
        "global_spans_criterion_met": summary["global_spans_criterion_met"],
        "n_runs_any_length": summary["n_runs_any_length"],
    }


def summarize_geography(
    day_frame: pd.DataFrame,
    gaps: list[dict[str, Any]],
    *,
    parent_meta: dict[str, Any],
    n_severe_collapse_days: int,
    n_drift_candidates: int,
) -> dict[str, Any]:
    """Meta summary answering whether collapse/drift bind span formation."""
    n_solid = int(day_frame["is_solid"].astype(bool).sum())
    class_totals = (
        day_frame.loc[~day_frame["is_solid"].astype(bool), "nonsolid_class"]
        .fillna("other")
        .astype(str)
        .value_counts()
        .to_dict()
    )
    class_totals = {str(k): int(v) for k, v in class_totals.items()}

    breaking = [g for g in gaps if int(g["n_nonsolid_session_days"]) > 0]
    adjacent = [g for g in gaps if int(g["n_nonsolid_session_days"]) == 0]
    dominant_counts = Counter(g["dominant_class"] for g in breaking)
    n_break_with_collapse = sum(1 for g in breaking if g["has_severe_collapse"])
    n_break_with_drift = sum(1 for g in breaking if g["has_drift_candidate"])

    calendar_gaps = [int(g["calendar_gap_days"]) for g in gaps]
    session_gaps = [int(g["n_nonsolid_session_days"]) for g in gaps]

    bridges = [longest_under_bridge(day_frame, bridge_class=c) for c in NONSOLID_CLASSES]

    # Collapse is "implicated" only if bridging weak_separation still fails AND
    # a material share of breaking gaps contain a severe-collapse day.
    weak_bridge = next(b for b in bridges if b["bridge_class"] == "weak_separation")
    collapse_share = (n_break_with_collapse / len(breaking)) if breaking else 0.0
    severe_collapse_implicated = bool(
        weak_bridge["longest_calendar_days"] < PRIMARY_LENGTH_THRESHOLD
        and collapse_share >= 0.25
        and n_break_with_collapse >= 5
    )

    return {
        "record_type": "meta",
        "tier": "O",
        "parent": PARENT_O_DATASET,
        "parent_n_solid_days": int(parent_meta.get("n_solid_days", n_solid)),
        "n_solid_days": n_solid,
        "n_nonsolid_days": int((~day_frame["is_solid"].astype(bool)).sum()),
        "nonsolid_class_totals": class_totals,
        "n_inter_solid_gaps": int(len(gaps)),
        "n_breaking_gaps": int(len(breaking)),
        "n_adjacent_solid_pairs": int(len(adjacent)),
        "dominant_class_in_breaking_gaps": {k: int(v) for k, v in dominant_counts.items()},
        "calendar_gap_days_median": float(pd.Series(calendar_gaps).median()) if calendar_gaps else 0.0,
        "calendar_gap_days_max": int(max(calendar_gaps)) if calendar_gaps else 0,
        "session_nonsolid_gap_median": float(pd.Series(session_gaps).median()) if session_gaps else 0.0,
        "session_nonsolid_gap_max": int(max(session_gaps)) if session_gaps else 0,
        "n_breaking_gaps_with_severe_collapse": int(n_break_with_collapse),
        "n_breaking_gaps_with_drift_candidate": int(n_break_with_drift),
        "breaking_gap_severe_collapse_share": round(collapse_share, 4),
        "n_severe_collapse_days_corpus": int(n_severe_collapse_days),
        "n_drift_candidate_days": int(n_drift_candidates),
        "n_solid_that_are_severe_collapse": int(
            (day_frame["is_solid"].astype(bool) & day_frame["is_severe_collapse"].astype(bool)).sum()
        ),
        "bridge_counterfactuals": bridges,
        "severe_collapse_implicated": severe_collapse_implicated,
        "recommended_focus": (
            "revisit_severe_collapse_autopsy"
            if severe_collapse_implicated
            else "bridge_or_convert_dominant_interrupter"
        ),
        "note": (
            "Inter-solid gaps are non-solid session-days between consecutive solid days "
            "in the Tier O series. Bridge counterfactuals drop one nonsolid_class from the "
            "series and recompute gap=0 solid runs. severe_collapse_implicated is true only "
            "when bridging weak_separation still leaves longest < 30d AND ≥25% of breaking "
            "gaps contain a severe-collapse day."
        ),
    }


def build_output_records(
    parent_meta: dict[str, Any],
    day_frame: pd.DataFrame,
    gaps: list[dict[str, Any]],
    *,
    n_severe_collapse_days: int,
    n_drift_candidates: int,
) -> list[dict[str, Any]]:
    """Meta + gap rows + annotated day rows."""
    meta = summarize_geography(
        day_frame,
        gaps,
        parent_meta=parent_meta,
        n_severe_collapse_days=n_severe_collapse_days,
        n_drift_candidates=n_drift_candidates,
    )
    records: list[dict[str, Any]] = [meta]
    for rank, gap in enumerate(
        sorted(
            gaps,
            key=lambda g: (-int(g["n_nonsolid_session_days"]), -int(g["calendar_gap_days"]), g["left_solid_date"]),
        ),
        start=1,
    ):
        records.append(
            {
                "record_type": "gap",
                "rank_by_session_gap": rank,
                **gap,
            }
        )
    for row in day_frame.itertuples(index=False):
        nonsolid = row.nonsolid_class
        if nonsolid is pd.NA or (isinstance(nonsolid, float) and pd.isna(nonsolid)):
            nonsolid = None
        else:
            nonsolid = str(nonsolid) if nonsolid is not None else None
        records.append(
            {
                "record_type": "day",
                "enriched_date": row.enriched_date,
                "k_e_signal": int(row.k_e_signal),
                "day_status": str(row.day_status) if row.day_status is not None else None,
                "separated_share": round(float(row.separated_share), 4),
                "is_solid": bool(row.is_solid),
                "nonsolid_class": nonsolid,
                "is_drift_candidate": bool(row.is_drift_candidate),
                "is_severe_collapse": bool(row.is_severe_collapse),
            }
        )
    return records


def main() -> None:
    parent_records = load(PARENT_O_DATASET)
    if isinstance(parent_records, pd.DataFrame):
        parent_records = parent_records.to_dict(orient="records")
    parent_meta, day_series = load_day_frame(parent_records)

    drift_records = load(DRIFT_DATASET)
    if isinstance(drift_records, pd.DataFrame):
        drift_records = drift_records.to_dict(orient="records")
    drift_dates = drift_candidate_dates(drift_records)

    predictions = load(CORPUS_PRED_DATASET)
    if isinstance(predictions, pd.DataFrame):
        predictions = predictions.to_dict(orient="records")
    collapse_dates = severe_collapse_dates(predictions)

    day_frame = annotate_days(day_series, drift_dates=drift_dates, collapse_dates=collapse_dates)
    gaps = find_inter_solid_gaps(day_frame)
    records = build_output_records(
        parent_meta,
        day_frame,
        gaps,
        n_severe_collapse_days=len(collapse_dates),
        n_drift_candidates=len(drift_dates),
    )
    meta = records[0]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[PARENT_O_DATASET, DRIFT_DATASET, CORPUS_PRED_DATASET],
        description=(
            "Tier O span-gap geography: classifies non-solid days between consecutive "
            "solid days, reports dominant interrupters and bridge counterfactuals, and "
            "flags whether S6c severe-collapse days are implicated in Global spans failure."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(
        f"solid={meta['n_solid_days']} breaking_gaps={meta['n_breaking_gaps']} "
        f"adjacent_solid_pairs={meta['n_adjacent_solid_pairs']}"
    )
    print(f"nonsolid_class_totals={meta['nonsolid_class_totals']}")
    print(f"dominant_class_in_breaking_gaps={meta['dominant_class_in_breaking_gaps']}")
    print(
        f"breaking_gaps_with_severe_collapse="
        f"{meta['n_breaking_gaps_with_severe_collapse']}/{meta['n_breaking_gaps']} "
        f"(share={meta['breaking_gap_severe_collapse_share']})"
    )
    print(f"severe_collapse_implicated={meta['severe_collapse_implicated']}")
    print(f"recommended_focus={meta['recommended_focus']}")
    for bridge in meta["bridge_counterfactuals"]:
        print(
            f"  bridge {bridge['bridge_class']}: "
            f"longest={bridge['longest_calendar_days']} "
            f"spans@30={bridge['global_spans_n_spans']} "
            f"bridged_days={bridge['n_days_bridged']}"
        )


if __name__ == "__main__":
    main()

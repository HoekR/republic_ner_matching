#!/usr/bin/env python3
"""Step 5c.1 of plans/COLLISION_AVOIDANCE_TRACK.md — is the `separated` set *accurate*?

PLAN.md's Global-primary criterion is MET at 8,015 separated resolutions (68.8% of the 11,644
ceiling), and Step 5 proposes freezing that as a **scaffold** to fill gaps around. Step 5c
condition 1 blocks that freeze until the separated set is verified, because `separated` is a
**coverage** criterion — unique start paragraph on the date, extent <= 3 paragraphs — and never
tests whether the placement is *right*. A wrong anchor corrupts the gap on each side of it, so
gap-filling around an unverified scaffold propagates error both ways.

This script measures accuracy on the only ground truth that exists: the 50 hand-annotated
`boundary_gold_sample` days.

Three questions, in order of what they decide:

1. **Is a separated placement more likely to be right than a non-separated one?** If not,
   `separated` carries no accuracy signal and cannot act as a scaffold selector -- the 8,015 would
   be "mapped somewhere unique" (MAPQ > 0) and nothing more.
2. **Does the production placement beat an even spread?** Step 2 found a trivial uniform spread
   beats gold's own annotations on the `separated` criterion, so uniform is the null that any
   claim of alignment quality has to clear. Scored here by correctness, which `separated` cannot do.
3. **How wrong are the wrong ones?** A scaffold whose errors are one paragraph off is usable;
   one whose errors are arbitrary is not.

Metric choice: exact start-paragraph agreement and absolute displacement in **paragraphs**.
Deliberately NOT tolerance-threshold F1 at character offsets -- that family is ruled out as a
target for this track (`docs/METRICS.md`, and the track's own guardrail).

Gold convention (canonical, taken from scripts/s6a_char_axis_evaluation.py, NOT re-derived):
``boundaries`` is a list of slots in reading order; ``kind`` is ``cut`` (a boundary between two
resolutions), ``start`` (where the day's *first* resolution opens, when it is not paragraph 0) or
``end_of_last_resolution`` (excluded -- it closes the day, it opens nothing). A slot whose ``unit``
is ``paragraph_boundary`` sits at the *end* of its paragraph (``char_offset == len(paragraph)``),
so the resolution it opens starts at ``paragraph_stream_index + 1``; any other unit opens inside
the paragraph itself. Cut *c* therefore opens resolution *c+1*, and 41 of 373 slots are unlocated
placeholders (``flat_id``/``char_offset`` null, ``unit == "out_of_range"``, parked at the day's
last paragraph index) which are held out as unknown rather than treated as real starts.

Usage:
    uv run python -m scripts.separated_accuracy_eval
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured
from scripts.evaluate_s4_paragraph_axis import review_codes
from scripts.s4_corpus_paragraph_predictions import AXIS_DATASET, axis_for_date, resolved_sessions, session_of
from scripts.s6a_char_axis_evaluation import opening_paragraph

GOLD_DATASET = "boundary_gold_sample"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "separated_accuracy_eval"

MAX_EXTENT_PARAGRAPHS = 3
# `end_of_last_resolution` closes the day rather than opening a resolution; see module docstring.
OPENING_KINDS = frozenset({"cut", "start"})


def is_located(slot: dict[str, Any]) -> bool:
    """A slot the annotator could actually place, as opposed to an `out_of_range` placeholder."""
    return (
        slot.get("flat_id") is not None
        and slot.get("char_offset") is not None
        and slot.get("paragraph_stream_index") is not None
    )


def gold_start_paragraphs(day: dict[str, Any], k_e: int) -> list[int | None]:
    """Start paragraph per resolution index, `None` where gold does not locate it.

    Resolution 0 starts at paragraph 0 unless gold records an explicit ``start`` slot (8 days do,
    always as the list's first entry). Every later resolution *j* opens at cut *j-1*.
    """
    slots = [slot for slot in day.get("boundaries") or [] if slot.get("kind") in OPENING_KINDS]

    if slots and slots[0].get("kind") == "start":
        first = opening_paragraph(slots[0]) if is_located(slots[0]) else None
        cuts = slots[1:]
    else:
        first = 0
        cuts = slots

    starts: list[int | None] = [first]
    for index in range(1, k_e):
        cut = cuts[index - 1] if index - 1 < len(cuts) else None
        starts.append(opening_paragraph(cut) if cut is not None and is_located(cut) else None)
    return starts


def uniform_start_paragraphs(paragraph_count: int, k_e: int) -> list[int]:
    """The null placement: `segment_gap`'s uniform `ideal` spread over the whole day."""
    cuts = [(rank * paragraph_count) // k_e for rank in range(1, k_e)]
    return [0] + cuts


def label_separation(frame: pd.DataFrame) -> pd.DataFrame:
    """Row-level `separated` flag and loss reason, per PLAN.md's acceptance criteria.

    Mirrors ``scripts/metrics_separation_span_table.count_separated_per_day`` exactly; the caller
    asserts the per-day sums agree rather than trusting that they do.
    """
    work = frame.copy()
    work["extent"] = (work["paragraph_end_index"] - work["paragraph_start_index"] + 1).astype(int)
    shares = (
        work.groupby(["enriched_date", "paragraph_start_index"], sort=False)
        .size()
        .rename("n_share")
        .reset_index()
    )
    work = work.merge(shares, on=["enriched_date", "paragraph_start_index"], how="left")
    work["unique_start"] = work["n_share"] == 1
    work["bounded_extent"] = work["extent"] <= MAX_EXTENT_PARAGRAPHS
    work["separated"] = work["unique_start"] & work["bounded_extent"]
    work["loss_reason"] = [
        "separated"
        if separated
        else ("collision_and_extent" if not unique and not bounded else ("collision" if not unique else "extent"))
        for separated, unique, bounded in zip(work["separated"], work["unique_start"], work["bounded_extent"])
    ]
    return work


def accuracy(frame: pd.DataFrame, predicted: str, reference: str = "gold_start") -> dict[str, Any]:
    """Correctness of a placement column against gold, in paragraphs."""
    scored = frame.dropna(subset=[predicted, reference])
    if scored.empty:
        return {"n": 0, "exact_agreement": None, "within_1": None, "mean_abs_displacement": None,
                "median_abs_displacement": None}
    displacement = (scored[predicted].astype(int) - scored[reference].astype(int)).abs()
    return {
        "n": int(len(scored)),
        "exact_agreement": round(float((displacement == 0).mean()), 4),
        "within_1": round(float((displacement <= 1).mean()), 4),
        "mean_abs_displacement": round(float(displacement.mean()), 3),
        "median_abs_displacement": round(float(displacement.median()), 3),
    }


def main() -> None:
    gold = load(GOLD_DATASET)
    codes = review_codes()
    concordance = load(CONCORDANCE_DATASET)
    concordance["enriched_date"] = concordance["enriched_date"].astype(str).str.slice(0, 10)

    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)
        axis_by_session[session_of(record["flat_id"])].append(record)
    session_by_date = resolved_sessions()

    gold_days = {str(day["date"]): day for day in gold["days"]}

    # Separation is a property of the whole corpus day (uniqueness is computed over every
    # attributed row on that date), so label the full corpus first and subset to gold after.
    attributed = concordance.loc[
        concordance["paragraph_start_index"].notna() & concordance["paragraph_end_index"].notna()
    ].copy()
    labelled = label_separation(attributed)

    from scripts.metrics_separation_span_table import count_separated_per_day

    reference_counts = count_separated_per_day(concordance).set_index("enriched_date")["separated_count"]
    own_counts = labelled.groupby("enriched_date")["separated"].sum().astype(int)
    if not own_counts.reindex(reference_counts.index).fillna(0).astype(int).equals(reference_counts):
        raise AssertionError("row-level separation disagrees with metrics_separation_span_table")

    rows: list[dict[str, Any]] = []
    per_day: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)

    for date, day in sorted(gold_days.items()):
        k_e = int(day["k_e"])
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis:
            skipped["no_axis"] += 1
            continue
        day_rows = labelled.loc[labelled["enriched_date"] == date]
        if day_rows.empty:
            skipped["no_paragraph_attribution"] += 1
            continue

        paragraph_count = len(axis)
        gold_starts = gold_start_paragraphs(day, k_e)
        uniform = uniform_start_paragraphs(paragraph_count, k_e)
        review_code = codes.get(date, "S")

        for row in day_rows.itertuples(index=False):
            index = int(row.resolution_index)
            if index >= k_e:
                skipped["resolution_index_beyond_gold_k_e"] += 1
                continue
            rows.append(
                {
                    "date": date,
                    "review_code": review_code,
                    "resolution_index": index,
                    "k_e": k_e,
                    "paragraph_count": paragraph_count,
                    "gold_start": gold_starts[index],
                    "predicted_start": int(row.paragraph_start_index),
                    "uniform_start": uniform[index] if index < len(uniform) else None,
                    "extent": int(row.extent),
                    "separated": bool(row.separated),
                    "loss_reason": str(row.loss_reason),
                }
            )

        located = sum(1 for start in gold_starts if start is not None)
        per_day.append(
            {
                "date": date,
                "review_code": review_code,
                "k_e": k_e,
                "paragraph_count": paragraph_count,
                "gold_located_starts": located,
                "gold_complete": located == k_e,
                "attributed_rows": int(len(day_rows)),
                "separated_rows": int(day_rows["separated"].sum()),
            }
        )

    frame = pd.DataFrame(rows)
    day_frame = pd.DataFrame(per_day)

    # Resolution 0 starts at paragraph 0 by construction on BOTH sides (the concordance's
    # resolution_paragraph_range hardcodes start=0, and gold defaults to 0 absent a `start` slot),
    # so scoring it would hand every cohort a free agreement. Held out and reported separately.
    scoreable = frame.loc[frame["resolution_index"] >= 1] if not frame.empty else frame
    trivial = frame.loc[frame["resolution_index"] == 0] if not frame.empty else frame

    cohorts: list[dict[str, Any]] = []
    for label, subset in [
        ("all_attributed", scoreable),
        ("separated", scoreable.loc[scoreable["separated"]] if not scoreable.empty else scoreable),
        ("not_separated", scoreable.loc[~scoreable["separated"]] if not scoreable.empty else scoreable),
    ]:
        cohorts.append(
            {
                "cohort": label,
                "rows": int(len(subset)),
                "production": accuracy(subset, "predicted_start"),
                "uniform_null": accuracy(subset, "uniform_start"),
            }
        )

    by_loss_reason = [
        {"loss_reason": reason, "rows": int(len(subset)), "production": accuracy(subset, "predicted_start")}
        for reason, subset in (scoreable.groupby("loss_reason") if not scoreable.empty else [])
    ]
    by_review_code = [
        {"review_code": code, "rows": int(len(subset)), "production": accuracy(subset, "predicted_start"),
         "uniform_null": accuracy(subset, "uniform_start")}
        for code, subset in (scoreable.groupby("review_code") if not scoreable.empty else [])
    ]

    # Step 2's side finding, recomputed under the canonical gold convention above: does a uniform
    # spread really out-score gold's own annotations on `separated`? Restricted to days where gold
    # locates every resolution, since a partially-annotated day cannot be scored on uniqueness.
    complete = day_frame.loc[day_frame["gold_complete"]] if not day_frame.empty else day_frame
    complete_dates = set(complete["date"]) if not complete.empty else set()
    separated_comparison: dict[str, Any] = {"complete_gold_days": int(len(complete_dates))}
    if complete_dates:
        subset = frame.loc[frame["date"].isin(complete_dates)]
        separated_comparison.update(
            {
                "resolutions": int(len(subset)),
                "production_separated": int(subset["separated"].sum()),
                "gold_separated": int(
                    sum(
                        _separated_under(day_frame, date, frame, "gold_start")
                        for date in sorted(complete_dates)
                    )
                ),
                "uniform_separated": int(
                    sum(
                        _separated_under(day_frame, date, frame, "uniform_start")
                        for date in sorted(complete_dates)
                    )
                ),
                "note": (
                    "Counts on the same days under the same criterion (unique start paragraph, "
                    "extent <= 3). Extent under gold/uniform is the distance to the next start, "
                    "with the day's paragraph_count closing the last resolution."
                ),
            }
        )

    summary = {
        "record_type": "summary",
        "gold_days_total": len(gold_days),
        "gold_days_scored": int(len(day_frame)),
        "skipped_days": dict(skipped),
        "scoreable_rows": int(len(scoreable)),
        "trivial_index0_rows": int(len(trivial)),
        "gold_located_scoreable_rows": int(scoreable["gold_start"].notna().sum()) if not scoreable.empty else 0,
        "cohorts": cohorts,
        "by_loss_reason": by_loss_reason,
        "by_review_code": by_review_code,
        "separated_criterion_comparison": separated_comparison,
        "max_extent_paragraphs": MAX_EXTENT_PARAGRAPHS,
        "metric_note": (
            "Exact start-paragraph agreement and absolute paragraph displacement only. No "
            "tolerance-family character metric is computed or targeted."
        ),
    }

    records = (
        [summary]
        + [{"record_type": "day", **record} for record in per_day]
        + [{"record_type": "resolution", **record} for record in frame.to_dict("records")]
    )
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)

    print(f"Wrote separated-accuracy evaluation to {output}")
    print(f"gold days scored: {summary['gold_days_scored']} / {summary['gold_days_total']} {dict(skipped)}")
    for cohort in cohorts:
        production = cohort["production"]
        null = cohort["uniform_null"]
        print(
            f"{cohort['cohort']:>15}: n={production['n']:>4} "
            f"exact={production['exact_agreement']} within1={production['within_1']} "
            f"meanDisp={production['mean_abs_displacement']} | "
            f"uniform exact={null['exact_agreement']} meanDisp={null['mean_abs_displacement']}"
        )
    print(f"separated-criterion comparison: {separated_comparison}")


def _separated_under(day_frame: pd.DataFrame, date: str, frame: pd.DataFrame, column: str) -> int:
    """`separated` count for one day under an alternative start-paragraph column."""
    day = day_frame.loc[day_frame["date"] == date].iloc[0]
    subset = frame.loc[frame["date"] == date].sort_values("resolution_index")
    starts = [value for value in subset[column].tolist() if value is not None and not pd.isna(value)]
    if len(starts) != len(subset):
        return 0
    starts = [int(value) for value in starts]
    paragraph_count = int(day["paragraph_count"])
    ends = starts[1:] + [paragraph_count]
    counts = pd.Series(starts).value_counts()
    return sum(
        1
        for start, end in zip(starts, ends)
        if counts[start] == 1 and (end - start + 1) <= MAX_EXTENT_PARAGRAPHS
    )


if __name__ == "__main__":
    main()

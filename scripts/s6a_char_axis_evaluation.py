#!/usr/bin/env python3
"""S6a -- re-score S4 boundary predictions on a composed character axis.

docs/steps/STEP_S6_anchor_chain_alignment.md section 3 gates every other S6 step on this
one: until scoring runs at character coordinates, a win is invisible to every tracked
metric. SEGMENTATION_TRANSFER.md section 6.3 always specified that cut points land at
*character* positions, but s4_paragraph_axis_baseline.py emits `paragraph_stream_index`
as the real output coordinate, with `char_offset` only a byproduct of a phrase-snap hit.

HTR under-segments on 81.1% of days, so distinct gold cuts routinely land inside one
paragraph and collapse to the same integer. `compute_boundary_prf` consumes each
reference boundary at most once and predicted positions are strictly increasing, so at
tolerance 0 those collapsed slots are unreachable no matter how good the predictor is.
This module composes `(paragraph_stream_index, char_offset)` into one integer axis so
they separate, and reports exactly which slots fold and whether composition unfolds them.

Composition convention
----------------------
A day's paragraphs concatenate with **no separator**, so the axis is literally the
character offsets of the day's concatenated text. This is not an arbitrary choice:
gold `paragraph_boundary` cuts carry `char_offset == len(paragraph_text)` (verified on
1626-01-08: paragraph 0 has length 424 and its boundary cut sits at 424), so a
paragraph-final cut composes to exactly the start of the next paragraph. Any invented
separator would put those two descriptions of the same point at different coordinates.

Scoring denominators
--------------------
Only 35 of the 50 gold days have any `boundary_gold_paragraph_axis` records; the other
15 all have `k_f == 0` and `flat_ids == []`, i.e. the accepted `missing_htr` structural
ceiling (13 carry review code M; 1626-05-17 and 1627-04-11 are the two uncoded k_e==1
days already noted in docs/state.json). A day with no text has no character axis, so it
cannot be scored here. Eligibility otherwise follows S5: review code S or uncoded.

Two slot sets are reported, deliberately, because they answer different questions:

* `CEILING_KINDS` (`cut` only) reproduces the guide's measured ceiling -- 352 cut slots,
  280 distinct paragraph positions, 320 distinct character positions.
* `REF_KINDS` (`cut` and `start`) matches what evaluate_s4_paragraph_axis.py actually
  scores, so the re-scored baseline is like-for-like against the 2026-09-18 run.

Usage:
    uv run python -m scripts.s6a_char_axis_evaluation
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from data_io import load, save_semi_structured
from evaluation_harness import evaluate_segmentation_session, summarize_segmentation_evaluations


GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
REVIEW_DATASET = "boundary_gold_exception_review"
PREDICTIONS_DATASET = "s4_paragraph_axis_predictions"
OUTPUT_DATASET = "s6a_char_axis_evaluation"

CHAR_TOLERANCES = (0, 50, 150)
REF_KINDS = frozenset({"cut", "start"})
CEILING_KINDS = frozenset({"cut"})


def char_starts(records: Sequence[dict[str, Any]]) -> list[int]:
    """Cumulative character start offset of each paragraph in a day's ordered axis."""
    starts: list[int] = []
    total = 0
    for record in records:
        starts.append(total)
        total += len(record["text"])
    return starts


def axis_char_length(records: Sequence[dict[str, Any]]) -> int:
    return sum(len(record["text"]) for record in records)


def compose(starts: Sequence[int], paragraph_stream_index: Any, char_offset: Any) -> int | None:
    """Compose a (paragraph index, within-paragraph offset) pair to one axis coordinate.

    Returns None when the slot carries no offset (gold's `out_of_range` markers) or the
    paragraph index falls outside the day's axis -- both are annotation gaps, and a
    caller must drop them rather than guess a position.
    """
    if char_offset is None or paragraph_stream_index is None:
        return None
    index = int(paragraph_stream_index)
    if not 0 <= index < len(starts):
        return None
    return starts[index] + int(char_offset)


def slots_of(day: dict[str, Any], kinds: frozenset[str]) -> list[dict[str, Any]]:
    return [boundary for boundary in day.get("boundaries") or [] if boundary.get("kind") in kinds]


def composed_positions(day: dict[str, Any], starts: Sequence[int], kinds: frozenset[str]) -> list[int]:
    """Composed coordinates for a day's scoreable slots, dropping offset-less ones."""
    positions = [
        compose(starts, boundary.get("paragraph_stream_index"), boundary.get("char_offset"))
        for boundary in slots_of(day, kinds)
    ]
    return sorted(position for position in positions if position is not None)


def opening_paragraph(boundary: dict[str, Any]) -> int | None:
    """The paragraph in which the next resolution opens.

    A `paragraph_boundary` cut recorded at index `p` sits at the *end* of `p`
    (`char_offset == len(p)`), so the next resolution opens at `p + 1`. Any other unit
    opens inside `p` itself.
    """
    index = boundary.get("paragraph_stream_index")
    if index is None:
        return None
    return int(index) + 1 if boundary.get("unit") == "paragraph_boundary" else int(index)


def lumped_positions(day: dict[str, Any], starts: Sequence[int], kinds: frozenset[str] = REF_KINDS) -> list[int]:
    """Gold cuts collapsed onto the start of the paragraph they open, then de-duplicated.

    This deliberately discards sub-paragraph precision: an interior cut is credited at its
    paragraph's start, so it becomes reachable by a paragraph-granular predictor instead of
    counting as a structural miss. Several cuts opening in one paragraph lump to one position,
    which is why the lumped reference count is lower than the strict one.
    """
    positions = set()
    for boundary in slots_of(day, kinds):
        index = opening_paragraph(boundary)
        if index is not None and 0 <= index < len(starts):
            positions.add(starts[index])
    return sorted(positions)


def lump_prediction(starts: Sequence[int], paragraph_indices: Sequence[int]) -> list[int]:
    """Model output collapsed the same way, so both sides are scored at one granularity."""
    return sorted({starts[index] for index in paragraph_indices if 0 <= index < len(starts)})


def fold_groups(day: dict[str, Any], starts: Sequence[int], kinds: frozenset[str] = REF_KINDS) -> list[dict[str, Any]]:
    """Describe every set of slots that folds onto one paragraph index.

    A group is `fully_separated` when composition gives each of its slots a distinct
    character coordinate. Groups that stay folded are an annotation gap -- their slots
    carry `char_offset: null` -- not a limit of the coordinate.
    """
    by_index: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for boundary in slots_of(day, kinds):
        by_index[boundary.get("paragraph_stream_index")].append(boundary)

    groups = []
    for index, slots in sorted(by_index.items(), key=lambda item: (item[0] is None, item[0])):
        if len(slots) < 2:
            continue
        composed = [compose(starts, index, slot.get("char_offset")) for slot in slots]
        distinct = {position for position in composed if position is not None}
        null_offsets = sum(1 for position in composed if position is None)
        groups.append(
            {
                "paragraph_stream_index": index,
                "slot_count": len(slots),
                "distinct_composed": len(distinct),
                "null_offsets": null_offsets,
                "fully_separated": null_offsets == 0 and len(distinct) == len(slots),
                "slots": [
                    {
                        "kind": slot.get("kind"),
                        "unit": slot.get("unit"),
                        "char_offset": slot.get("char_offset"),
                        "composed": position,
                    }
                    for slot, position in zip(slots, composed)
                ],
            }
        )
    return groups


def ceiling_report(days: Sequence[dict[str, Any]], starts_by_date: dict[str, list[int]]) -> dict[str, Any]:
    """Reproduce the guide's paragraph-vs-character reachable-position ceiling.

    The bound is rigorous at tolerance 0 only: a hypothesis must equal a reference
    exactly, and strictly increasing predictions can claim at most one slot per distinct
    value. At tolerance > 0 a clustering predictor can exceed it (STEP_S6 section 1).
    """
    paragraph_positions: set[tuple[str, Any]] = set()
    char_positions: set[tuple[str, int]] = set()
    total_slots = 0
    null_offset_slots = 0

    for day in days:
        date = str(day["date"])
        starts = starts_by_date.get(date, [])
        for boundary in slots_of(day, CEILING_KINDS):
            total_slots += 1
            index = boundary.get("paragraph_stream_index")
            paragraph_positions.add((date, index))
            position = compose(starts, index, boundary.get("char_offset"))
            if position is None:
                null_offset_slots += 1
            else:
                char_positions.add((date, position))

    return {
        "cut_slots": total_slots,
        "distinct_paragraph_positions": len(paragraph_positions),
        "distinct_char_positions": len(char_positions),
        "null_offset_slots": null_offset_slots,
        "paragraph_recall_bound_tol0": len(paragraph_positions) / total_slots if total_slots else 0.0,
        "char_recall_bound_tol0": len(char_positions) / total_slots if total_slots else 0.0,
    }


def review_codes() -> dict[str, str]:
    review = load(REVIEW_DATASET)
    return {
        str(row.date): str(row.review_code).strip()
        for row in review[["date", "review_code"]].dropna().itertuples(index=False)
        if str(row.review_code).strip()
    }


def main() -> None:
    gold = load(GOLD_DATASET)
    predictions = {item["date"]: item for item in load(PREDICTIONS_DATASET)}
    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)
    starts_by_date = {date: char_starts(records) for date, records in axis_by_date.items()}

    days = gold["days"]
    codes = review_codes()
    eligible = [day for day in days if codes.get(str(day["date"]), "S") == "S"]

    evaluated = []
    evaluated_lumped = []
    per_day = []
    no_axis = []
    abstentions: dict[str, int] = defaultdict(int)

    for day in eligible:
        date = str(day["date"])
        starts = starts_by_date.get(date)
        if not starts:
            no_axis.append(date)
            continue

        ref = composed_positions(day, starts, REF_KINDS)
        folds = fold_groups(day, starts, REF_KINDS)
        record = {
            "date": date,
            "k_e": int(day["k_e"]),
            "axis_paragraph_count": len(starts),
            "axis_char_length": axis_char_length(axis_by_date[date]),
            "ref_slots": len(slots_of(day, REF_KINDS)),
            "ref_composed": len(ref),
            "folded_groups": folds,
            "folded_slot_count": sum(group["slot_count"] for group in folds),
            "folded_groups_fully_separated": sum(1 for group in folds if group["fully_separated"]),
        }

        prediction = predictions.get(date)
        if prediction is None or prediction["status"] != "predicted":
            reason = str(prediction["reason"]) if prediction else "no_prediction"
            abstentions[reason] += 1
            record["status"] = "abstained"
            record["reason"] = reason
            per_day.append(record)
            continue

        hyp = sorted(
            position
            for position in (
                compose(starts, boundary.get("paragraph_stream_index"), boundary.get("char_offset"))
                for boundary in prediction["boundaries"]
            )
            if position is not None
        )
        ref_lumped = lumped_positions(day, starts, REF_KINDS)
        hyp_lumped = lump_prediction(
            starts, [boundary["paragraph_stream_index"] for boundary in prediction["boundaries"]]
        )
        record["status"] = "predicted"
        record["reason"] = None
        record["hyp_composed"] = len(hyp)
        record["ref_lumped"] = len(ref_lumped)
        record["hyp_lumped"] = len(hyp_lumped)
        per_day.append(record)

        evaluated.append(
            evaluate_segmentation_session(
                session_id=date,
                date=date,
                k_e=int(day["k_e"]),
                ref_boundaries=ref,
                hyp_boundaries=hyp,
                total_length=record["axis_char_length"],
                tolerances=CHAR_TOLERANCES,
            )
        )
        evaluated_lumped.append(
            evaluate_segmentation_session(
                session_id=date,
                date=date,
                k_e=int(day["k_e"]),
                ref_boundaries=ref_lumped,
                hyp_boundaries=hyp_lumped,
                total_length=record["axis_char_length"],
                tolerances=CHAR_TOLERANCES,
            )
        )

    report = {
        "unit": "character",
        "tolerances": list(CHAR_TOLERANCES),
        "gold_days": len(days),
        "days_with_axis": len(axis_by_date),
        "eligible_sessions": len(eligible),
        "eligible_without_axis": no_axis,
        "scoreable_sessions": len(eligible) - len(no_axis),
        "predicted_sessions": len(evaluated),
        "coverage": len(evaluated) / (len(eligible) - len(no_axis)) if len(eligible) > len(no_axis) else 0.0,
        "abstentions_by_reason": dict(abstentions),
        "ceiling": ceiling_report(days, starts_by_date),
        "metrics": summarize_segmentation_evaluations(evaluated, tolerances=CHAR_TOLERANCES) if evaluated else {},
        "metrics_lumped": summarize_segmentation_evaluations(evaluated_lumped, tolerances=CHAR_TOLERANCES)
        if evaluated_lumped
        else {},
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    ceiling = report["ceiling"]
    print(f"Wrote S6a character-axis evaluation to {output}")
    print(
        f"  ceiling: {ceiling['distinct_char_positions']}/{ceiling['cut_slots']} char positions "
        f"({ceiling['char_recall_bound_tol0']:.3f}) vs "
        f"{ceiling['distinct_paragraph_positions']}/{ceiling['cut_slots']} paragraph "
        f"({ceiling['paragraph_recall_bound_tol0']:.3f}) at tolerance 0"
    )
    print(f"  scoreable: {report['scoreable_sessions']} of {report['eligible_sessions']} eligible; predicted {len(evaluated)}")
    for label, key in (("strict", "metrics"), ("lumped", "metrics_lumped")):
        # summarize_segmentation_evaluations keys this dict by str(tol), not int.
        by_tolerance = report[key].get("boundary_metrics_by_tolerance", {}) if report[key] else {}
        scores = " ".join(
            f"tol{tolerance}={by_tolerance.get(str(tolerance), {}).get('micro_f1', 0.0):.3f}"
            for tolerance in CHAR_TOLERANCES
        )
        print(f"  {label:>6}: {scores}")


if __name__ == "__main__":
    main()

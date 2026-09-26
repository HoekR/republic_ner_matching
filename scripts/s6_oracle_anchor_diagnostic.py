#!/usr/bin/env python3
"""S6 Step 1 -- does anchor supply or the placement model bind?

STEP_S6_anchor_chain_alignment.md section 2.3 proposes replacing S4's entity-only NW with
colinear anchor chaining. That is worth building only if the *search over anchors* is what
limits the result. Two facts suggest it may not be: 12 of 16 gold abstentions were structural
(paragraph axis coarser than `K_e`), and chaining's power in its home domain comes from dense
unambiguous seeds, whereas here tagger recall is 50-55% and mean entity containment is 0.295.

This script settles it before any DP is written, by handing the *existing, unmodified* placement
model a perfect anchor set derived from gold and scoring it on S6a's character axis. Nothing here
is a new model: `interpolate_positions` and `snap_boundaries` are imported from
s4_paragraph_axis_baseline as-is, and only the anchor source changes.

Reading the result (decision rule fixed before the run, per docs/ITERATION_POLICY.md):

* oracle micro F1 at tol 50 is HIGH   -> anchor supply binds; S6b harvest is the answer and the
                                        chaining DP adds little over the same thin anchors.
* oracle micro F1 at tol 50 is LOW    -> the placement model binds; chaining will not fix it
                                        either, and a count-constrained segmentation DP that
                                        puts `K_e` inside the objective is the way forward.

Two structural facts the sweep is designed to expose, both invisible to paragraph-coordinate
scoring and neither fixable by a better search:

1. `interpolate_positions` requires anchors strictly increasing in *both* coordinates. When two
   gold cuts fold onto one paragraph index -- 24 groups across 16 days per S6a -- even a perfect
   anchor set is non-monotone and the model abstains.
2. The model emits `(paragraph index, phrase-snap offset or 0)`. A cut annotated `mid_paragraph`
   is therefore unreachable at tight tolerance however good the anchors are.

Usage:
    uv run python -m scripts.s6_oracle_anchor_diagnostic
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from data_io import load, save_semi_structured
from evaluation_harness import evaluate_segmentation_session, summarize_segmentation_evaluations
from scripts.s4_paragraph_axis_baseline import interpolate_positions, phrase_hits, snap_boundaries
from scripts.s6a_char_axis_evaluation import (
    REF_KINDS,
    axis_char_length,
    char_starts,
    compose,
    composed_positions,
    review_codes,
)


GOLD_DATASET = "boundary_gold_sample"
AXIS_DATASET = "boundary_gold_paragraph_axis"
PHRASE_DATASET = "s4_opening_phrase_candidates"
OUTPUT_DATASET = "s6_oracle_anchor_diagnostic"

CHAR_TOLERANCES = (0, 50, 150)
DENSITIES = ("all", "half", "endpoints")


def oracle_anchors(day: dict[str, Any]) -> list[tuple[int, int]] | None:
    """Perfect `(enriched_index, axis_index)` anchors read straight off the gold cuts.

    The unit matters, and getting it wrong silently fabricates collisions. A
    `paragraph_boundary` cut recorded at index `p` sits at the *end* of paragraph `p`
    (`char_offset == len(p)`), so the next resolution opens in paragraph `p + 1`. A
    `mid_paragraph` cut opens inside paragraph `p` itself. Reading both as `p` makes
    consecutive resolutions share an index and look non-monotone when they are not.

    Enriched resolution 0 starts at the first paragraph. Returns None when a cut carries no
    paragraph index at all -- an annotation gap, not a model failure.
    """
    cuts = [boundary for boundary in day.get("boundaries") or [] if boundary.get("kind") == "cut"]
    k_e = int(day["k_e"])
    if k_e <= 1:
        return []

    anchors: list[tuple[int, int]] = [(0, 0)]
    for enriched_index, cut in enumerate(cuts[: k_e - 1], start=1):
        index = cut.get("paragraph_stream_index")
        if index is None:
            return None
        opens_at = int(index) + 1 if cut.get("unit") == "paragraph_boundary" else int(index)
        anchors.append((enriched_index, opens_at))
    return anchors


def thin_anchors(anchors: Sequence[tuple[int, int]], density: str) -> list[tuple[int, int]]:
    """Sub-sample a perfect anchor set so the result is a curve rather than one point."""
    if density == "all":
        return list(anchors)
    if density == "half":
        return list(anchors[::2])
    if density == "endpoints":
        return [anchors[0], anchors[-1]] if len(anchors) >= 2 else list(anchors)
    raise ValueError(f"unknown density: {density}")


def anchor_obstruction(anchors: Sequence[tuple[int, int]], k_e: int, axis_count: int) -> str | None:
    """Name the structural reason the current model cannot use a perfect anchor set."""
    if axis_count < k_e:
        return "axis_shorter_than_k_e"
    if any(axis_index >= axis_count for _, axis_index in anchors):
        return "anchor_beyond_axis"
    if not all(left[0] < right[0] and left[1] < right[1] for left, right in zip(anchors, anchors[1:])):
        return "folded_anchors_non_monotone"
    return None


def reachability(day: dict[str, Any]) -> dict[str, int]:
    """Split gold cuts by whether a paragraph-granular predictor could ever land on them."""
    units = Counter(
        str(boundary.get("unit"))
        for boundary in day.get("boundaries") or []
        if boundary.get("kind") == "cut"
    )
    return {
        "paragraph_boundary_cuts": units.get("paragraph_boundary", 0),
        "mid_paragraph_cuts": units.get("mid_paragraph", 0),
        "out_of_range_cuts": units.get("out_of_range", 0),
    }


def compose_prediction(starts: Sequence[int], snapped: Sequence[tuple[int, Any]]) -> list[int]:
    """Compose the model's `(paragraph index, snap offset)` output onto the character axis."""
    positions = []
    for position, hit in snapped:
        composed = compose(starts, position, hit[1] if hit else 0)
        if composed is not None:
            positions.append(composed)
    return sorted(positions)


def main() -> None:
    gold = load(GOLD_DATASET)
    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)

    phrase_candidates = load(PHRASE_DATASET)[0]["candidates"]
    phrases = [item["phrase"] for item in phrase_candidates if item["word_count"] >= 3]

    codes = review_codes()
    eligible = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S"]

    per_day: list[dict[str, Any]] = []
    evaluated: dict[str, list[Any]] = {density: [] for density in DENSITIES}
    obstructions: dict[str, Counter[str]] = {density: Counter() for density in DENSITIES}
    totals = Counter()

    for day in eligible:
        date = str(day["date"])
        axis = axis_by_date.get(date)
        if not axis:
            totals["no_axis"] += 1
            continue

        starts = char_starts(axis)
        ref = composed_positions(day, starts, REF_KINDS)
        anchors = oracle_anchors(day)
        counts = reachability(day)
        for key, value in counts.items():
            totals[key] += value

        record: dict[str, Any] = {
            "date": date,
            "k_e": int(day["k_e"]),
            "axis_paragraph_count": len(axis),
            "axis_char_length": axis_char_length(axis),
            "ref_composed": len(ref),
            **counts,
            "runs": {},
        }

        if anchors is None:
            record["oracle_status"] = "gold_cut_without_paragraph_index"
            per_day.append(record)
            totals["gold_gap"] += 1
            continue

        hits = phrase_hits(axis, phrases)
        for density in DENSITIES:
            subset = thin_anchors(anchors, density)
            obstruction = anchor_obstruction(subset, int(day["k_e"]), len(axis))
            if obstruction is not None:
                obstructions[density][obstruction] += 1
                record["runs"][density] = {"status": "abstained", "reason": obstruction}
                continue

            positions = interpolate_positions(int(day["k_e"]), len(axis), subset)
            if positions is None:
                obstructions[density]["interpolation_failed"] += 1
                record["runs"][density] = {"status": "abstained", "reason": "interpolation_failed"}
                continue

            hyp = compose_prediction(starts, snap_boundaries(positions, hits))
            record["runs"][density] = {"status": "predicted", "hyp_composed": len(hyp)}
            evaluated[density].append(
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

        per_day.append(record)

    scoreable = len(per_day)
    report = {
        "unit": "character",
        "tolerances": list(CHAR_TOLERANCES),
        "eligible_sessions": len(eligible),
        "scoreable_sessions": scoreable,
        "gold_cut_reachability": {
            "paragraph_boundary_cuts": totals["paragraph_boundary_cuts"],
            "mid_paragraph_cuts": totals["mid_paragraph_cuts"],
            "out_of_range_cuts": totals["out_of_range_cuts"],
        },
        "densities": {
            density: {
                "predicted_sessions": len(evaluated[density]),
                "coverage": len(evaluated[density]) / scoreable if scoreable else 0.0,
                "abstentions_by_reason": dict(obstructions[density]),
                "metrics": summarize_segmentation_evaluations(evaluated[density], tolerances=CHAR_TOLERANCES)
                if evaluated[density]
                else {},
            }
            for density in DENSITIES
        },
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote S6 oracle-anchor diagnostic to {output}")
    reach = report["gold_cut_reachability"]
    total_cuts = sum(reach.values())
    print(
        f"  gold cuts on eligible days: {total_cuts} "
        f"({reach['paragraph_boundary_cuts']} paragraph_boundary, "
        f"{reach['mid_paragraph_cuts']} mid_paragraph, {reach['out_of_range_cuts']} out_of_range)"
    )
    for density in DENSITIES:
        entry = report["densities"][density]
        metrics = entry["metrics"].get("boundary_metrics_by_tolerance", {}) if entry["metrics"] else {}
        # summarize_segmentation_evaluations keys this dict by str(tol), not int.
        scores = " ".join(
            f"tol{tol}={metrics.get(str(tol), {}).get('micro_f1', 0.0):.3f}" for tol in CHAR_TOLERANCES
        )
        print(
            f"  {density:>9}: predicted {entry['predicted_sessions']}/{scoreable} "
            f"({entry['coverage']:.3f})  {scores}  abstentions={entry['abstentions_by_reason']}"
        )


if __name__ == "__main__":
    main()

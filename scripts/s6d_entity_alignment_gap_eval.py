#!/usr/bin/env python3
"""Step 3 of plans/COLLISION_AVOIDANCE_TRACK.md, "first experiment": run
`align_entity_mentions` (`scripts/s6b_known_point_ledger.py`) over the entity-mention streams of
`s6b_known_point_ledger.py`'s **open** gaps, project the traceback onto paragraph cut points via
`scripts/s6d_entity_mention_gap_placement.py`, and score the result against gold exactly the way
`scripts/separated_accuracy_eval.py`'s Step 5c.1 baseline does -- reusing its `accuracy()` and
`gold_start_paragraphs()` rather than inventing a new metric.

Scope, deliberately narrow (see PLAN.md / docs/state.json `inventory-stream-collision-avoidance`):

* Only the 50 gold days -- gold is the only ground truth this can be scored against, and it is
  what the 5c.1 baseline (0.639 exact / 0.911 within-1) itself is scored on, restricted the same
  way to `review_code == "S"` (segmentable) days.
* Only `bucket_of(...) == "open"` gaps get a new placement; `determined`/`nearly_determined` gaps
  and any open gap the alignment cannot project (too few/no matched mentions) fall back to the
  existing production placement (`resolution_concordance_1626_1630.paragraph_start_index`) --
  never a worse answer than today's baseline for those resolutions.
* Interior known points come from tier-1 anchors only (`s6b_known_point_ledger.tier1_points`) --
  gold boundaries are NOT used to build the chain (that would leak gold into the placement being
  scored); gold is read only afterwards, to score.

Usage:
    uv run python -m scripts.s6d_entity_alignment_gap_eval
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured
from scripts.s6c_gap_segmentation import segment_gap
from scripts.d1c_idf_band_order_eval import name_frequencies, overlap_frame
from scripts.evaluate_s4_paragraph_axis import review_codes
from scripts.s4_corpus_paragraph_predictions import axis_for_date, resolved_sessions, session_of
from scripts.s6a_char_axis_evaluation import char_starts
from scripts.s6b_known_point_ledger import (
    align_entity_mentions,
    build_chain,
    bucket_of,
    collapse,
    flat_id_char_starts,
    tier1_points,
)
from scripts.s6d_entity_mention_gap_placement import build_vocab_pattern, mention_sequence, project_cuts
from scripts.separated_accuracy_eval import accuracy, gold_start_paragraphs

GOLD_DATASET = "boundary_gold_sample"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
ALIGNMENT_DATASET = "alignment_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
ENRICHED_DATASET = "enriched_resolutions_1626_1630"
OUTPUT_DATASET = "s6d_entity_alignment_gap_eval"
TIER1 = "tier1_anchor"

# Verdict thresholds, fixed before the run. See docstring rationale.
MIN_PROJECTED_FOR_VERDICT = 20
MIN_EXACT_MARGIN_OVER_CONTROL = 0.0


def enriched_by_date() -> dict[str, dict[int, str]]:
    by_date: dict[str, dict[int, str]] = defaultdict(dict)
    for item in load(ENRICHED_DATASET):
        date = str(item.get("date") or "")[:10]
        index = item.get("resolution_index")
        if date and index is not None:
            by_date[date][int(index)] = str(item.get("text") or "")
    return by_date


def bisect_paragraph(starts: list[int], char_position: int) -> int:
    """Index of the axis paragraph starting at or containing `char_position`."""
    import bisect

    return max(0, min(len(starts) - 1, bisect.bisect_right(starts, char_position) - 1))


def gap_paragraph_range(starts: list[int], left_char: int, right_char: int) -> list[int]:
    """Axis paragraph indices spanning `[left_char, right_char)`, at least the left paragraph."""
    import bisect

    left_para = bisect_paragraph(starts, left_char)
    right_para = bisect.bisect_left(starts, right_char)
    if right_para <= left_para:
        return [left_para]
    return list(range(left_para, right_para))


def place_open_gaps(
    chain: list[dict[str, Any]],
    axis: list[dict[str, Any]],
    starts: list[int],
    enriched_texts_by_index: dict[int, str],
    pattern,
) -> tuple[dict[int, int], dict[int, int], int, int, Counter[str]]:
    """Predicted paragraph index per interior enriched index the alignment could project,
    plus (open_gap_resolutions, projected_resolutions) coverage counts and a per-resolution
    tally of *why* the rest abstained.

    The abstention reasons are kept apart on purpose: "the enriched text was never retrieved"
    (a `(date, resolution_index)` lookup miss, i.e. a mapping artefact) is a completely different
    finding from "the text is there and names no known entity" (a genuine evidence absence), and
    the first version of this script lumped both into one coverage number. `identical_share` does
    the same job on the other side: the DP substitutes non-identical names at the same unit cost
    as a skip, so a projection can happen with zero *shared* names -- in which case the alignment
    is positional bookkeeping, not entity evidence, and the reader must be able to see that.
    """
    predicted: dict[int, int] = {}
    control: dict[int, int] = {}
    open_resolutions = 0
    projected_resolutions = 0
    reasons: Counter[str] = Counter()

    for left, right in zip(chain, chain[1:]):
        left_e, right_e = left["enriched_index"], right["enriched_index"]
        resolutions_in_gap = right_e - left_e - 1
        if bucket_of(resolutions_in_gap) != "open":
            continue
        open_resolutions += resolutions_in_gap

        interior_indices = list(range(left_e + 1, right_e))
        enriched_texts = [enriched_texts_by_index.get(index, "") for index in interior_indices]
        if not any(enriched_texts):
            reasons["enriched_text_not_retrieved"] += resolutions_in_gap
            continue

        gap_paragraphs = gap_paragraph_range(starts, left["char_position"], right["char_position"])
        flat_texts = [axis[i]["text"] for i in gap_paragraphs]

        enriched_mentions, enriched_boundaries = mention_sequence(enriched_texts, pattern)
        flat_mentions, flat_boundaries = mention_sequence(flat_texts, pattern)
        pairs, _ = align_entity_mentions(flat_mentions, enriched_mentions)
        if not pairs:
            # Three distinct causes, kept apart because they license opposite conclusions.
            # The third dominates and is easy to misread as the first two: `align_entity_mentions`
            # offers only "advance both" and "advance flat", never "advance enriched", so reaching
            # (n, m) needs exactly m matches plus n-m flat skips -- infeasible whenever n < m, and
            # it returns [] via `dp[n][m] == inf` with BOTH sides non-empty. n < m is routine here
            # because the vocabulary comes from the overlap tables' enriched-side `name` column and
            # is scanned as a literal lowercase substring, which recovers far better on clean
            # editorial prose than on period-spelled HTR.
            if not flat_mentions and not enriched_mentions:
                reasons["no_vocab_hits_either_side"] += resolutions_in_gap
            elif not flat_mentions:
                reasons["no_vocab_hits_htr_side"] += resolutions_in_gap
            elif not enriched_mentions:
                reasons["no_vocab_hits_enriched_side"] += resolutions_in_gap
            else:
                reasons["unreachable_fewer_htr_than_enriched_mentions"] += resolutions_in_gap
            continue

        identical = sum(1 for flat_i, enriched_j in pairs if flat_mentions[flat_i] == enriched_mentions[enriched_j])
        reasons["projected_gaps"] += 1
        reasons["projected_pairs"] += len(pairs)
        reasons["projected_pairs_identical"] += identical
        if identical == 0:
            reasons["projected_gaps_with_zero_shared_names"] += 1

        projected = project_cuts(pairs, enriched_boundaries, flat_boundaries)
        for offset, local_paragraph in enumerate(projected):
            if local_paragraph is None:
                continue
            local_paragraph = min(local_paragraph, len(gap_paragraphs) - 1)
            predicted[interior_indices[offset]] = gap_paragraphs[local_paragraph]
            projected_resolutions += 1

        # Control: same chain and gap, but pure even split via segment_gap (no entity evidence)
        n_to_place = right_e - left_e - 1
        if n_to_place > 0:
            control_positions = segment_gap(left["enriched_index"], right["enriched_index"], n_to_place, position_scores=None)
            for offset, para_idx in enumerate(control_positions):
                if para_idx is not None:
                    control[interior_indices[offset]] = para_idx

    return predicted, control, open_resolutions, projected_resolutions, reasons


def main() -> None:
    gold = load(GOLD_DATASET)
    codes = review_codes()
    s_days = [day for day in gold["days"] if codes.get(str(day["date"]), "S") == "S"]

    concordance = load(CONCORDANCE_DATASET)
    concordance["enriched_date"] = concordance["enriched_date"].astype(str).str.slice(0, 10)
    baseline_by_key = {
        (str(row.enriched_date), int(row.resolution_index)): (
            int(row.paragraph_start_index) if pd.notna(row.paragraph_start_index) else None
        )
        for row in concordance[["enriched_date", "resolution_index", "paragraph_start_index"]].itertuples(
            index=False
        )
    }

    alignment = load(ALIGNMENT_DATASET)
    alignment = alignment[alignment["confidence_tier"] == TIER1]
    tier1_by_date: dict[str, list[Any]] = defaultdict(list)
    for row in alignment[["enriched_id", "flat_id", "date"]].itertuples(index=False):
        tier1_by_date[str(row.date)].append(row)

    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)
        axis_by_session[session_of(record["flat_id"])].append(record)
    session_by_date = resolved_sessions()

    enriched_texts_by_date = enriched_by_date()

    frequencies = name_frequencies(overlap_frame())
    pattern = build_vocab_pattern(sorted(frequencies))

    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)
    total_open = 0
    total_projected = 0
    abstention_reasons: Counter[str] = Counter()
    enriched_lookup: Counter[str] = Counter()

    for day in s_days:
        date = str(day["date"])
        k_e = int(day["k_e"])
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis:
            skipped["no_axis"] += 1
            continue

        starts = char_starts(axis)
        total_chars = starts[-1] + len(axis[-1]["text"])
        by_flat_id = flat_id_char_starts(axis)
        interior = tier1_points(tier1_by_date.get(date, []), by_flat_id)
        chain = build_chain(k_e, total_chars, collapse(interior))

        # Does the enriched side even resolve for this date? A missing date, or a date whose
        # index set does not cover 1..k_e-1, makes every downstream "no entity evidence" verdict
        # on that day a lookup artefact rather than a finding about the text.
        day_enriched = enriched_texts_by_date.get(date, {})
        enriched_lookup["days"] += 1
        if not day_enriched:
            enriched_lookup["days_with_no_enriched_date"] += 1
        else:
            missing = [index for index in range(1, k_e) if not day_enriched.get(index)]
            enriched_lookup["interior_indices"] += max(0, k_e - 1)
            enriched_lookup["interior_indices_missing"] += len(missing)
            if missing:
                enriched_lookup["days_with_any_missing_index"] += 1

        predicted, control, open_resolutions, projected_resolutions, reasons = place_open_gaps(
            chain, axis, starts, day_enriched, pattern
        )
        total_open += open_resolutions
        total_projected += projected_resolutions
        abstention_reasons.update(reasons)

        gold_starts = gold_start_paragraphs(day, k_e)
        for index in range(1, k_e):
            baseline = baseline_by_key.get((date, index))
            new_value = predicted.get(index, baseline)
            control_value = control.get(index, baseline)
            rows.append(
                {
                    "date": date,
                    "resolution_index": index,
                    "gold_start": gold_starts[index],
                    "baseline_start": baseline,
                    "control_start": control_value,
                    "new_start": new_value,
                    "in_open_gap": index in {i for i in predicted} or None,
                    "projected": index in predicted,
                }
            )

    frame = pd.DataFrame(rows)
    baseline_accuracy = accuracy(frame, "baseline_start")
    control_accuracy = accuracy(frame, "control_start")
    new_accuracy = accuracy(frame, "new_start")

    projected_only = frame.loc[frame["projected"]] if not frame.empty else frame
    projected_accuracy = accuracy(projected_only, "new_start")
    projected_control_accuracy = accuracy(projected_only, "control_start")

    # Verdict: entity-DP must beat segment_gap on identical anchor input, at the pre-declared threshold
    projected_exact_new = projected_accuracy.get("exact_agreement", 0)
    projected_exact_control = projected_control_accuracy.get("exact_agreement", 0)
    exact_margin = projected_exact_new - projected_exact_control
    n_projected = projected_accuracy.get("n", 0)

    verdict = "no_data"
    if n_projected >= MIN_PROJECTED_FOR_VERDICT:
        if exact_margin > MIN_EXACT_MARGIN_OVER_CONTROL:
            verdict = "step3_continues"
        else:
            verdict = "step3_closes_negative"

    summary = {
        "record_type": "summary",
        "gold_days_total": len(gold["days"]),
        "gold_days_s_code": len(s_days),
        "skipped_days": dict(skipped),
        "rows": int(len(frame)),
        "open_gap_resolutions": total_open,
        "projected_resolutions": total_projected,
        "coverage_of_open_gaps": round(total_projected / total_open, 4) if total_open else None,
        "baseline_accuracy": baseline_accuracy,
        "control_accuracy": control_accuracy,
        "new_accuracy": new_accuracy,
        "projected_subset_accuracy": projected_accuracy,
        "projected_subset_control_accuracy": projected_control_accuracy,
        "projected_exact_margin_over_control": round(exact_margin, 4),
        "step3_verdict": verdict,
        "verdict_threshold_min_projected": MIN_PROJECTED_FOR_VERDICT,
        "verdict_threshold_min_margin": MIN_EXACT_MARGIN_OVER_CONTROL,
        "abstention_reasons": dict(abstention_reasons),
        "enriched_lookup": dict(enriched_lookup),
        "metric_note": "Exact start-paragraph agreement / within-1, no tolerance-family character metric. Verdict: entity-DP vs segment_gap (pure even split) on identical chains, projected subset only.",
    }

    records = [summary] + [{"record_type": "resolution", **record} for record in frame.to_dict("records")]
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)

    print(f"Wrote entity-alignment gap eval to {output}")
    print(f"gold S-code days scored: {len(s_days)}, skipped {dict(skipped)}")
    print(f"enriched lookup: {dict(enriched_lookup)}")
    print(f"abstention reasons (resolutions, unless named gaps/pairs): {dict(abstention_reasons)}")
    print(f"\nVERDICT: {verdict}")
    print(f"projected subset (n={n_projected}): entity-DP exact {projected_exact_new:.4f} vs control {projected_exact_control:.4f}, margin {exact_margin:.4f}")
    print(f"threshold: min_projected={MIN_PROJECTED_FOR_VERDICT}, min_margin={MIN_EXACT_MARGIN_OVER_CONTROL}")
    print(f"open-gap resolutions {total_open}, projected {total_projected} (coverage {summary['coverage_of_open_gaps']})")
    print(f"baseline: {baseline_accuracy}")
    print(f"new (fallback-filled): {new_accuracy}")
    print(f"new (projected subset only): {projected_accuracy}")


if __name__ == "__main__":
    main()

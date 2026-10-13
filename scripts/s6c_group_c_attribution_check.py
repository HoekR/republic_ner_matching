#!/usr/bin/env python3
"""Step 4 pre-check (plans/archive/STAGED_ANCHOR_CONSOLIDATION.md): would promoting Group C
(`s2_anchor_phrases`, `s4_opening_phrase_candidates`) to a *hard* backbone anchor be worth
the attribution risk, or does it repeat Group B's trap?

Group C hits are axis-paragraph-keyed with no enriched-resolution index -- exactly the
same shape as Group B's `entity_surface_matches`/`fuzzy_surface_scan`, which measured as
confusion (not signal) once forced through a name-matching attribution rule
(`s6b_group_b_signal_check.py`, docs/DECISIONS.md 2026-10-02). Step 4a's staging spec only
gains anything from C if a hit can become a committed `(enriched_index, axis_index)` pair
-- today C is used only as a *soft* bonus inside gaps Group A already anchored
(`segment_day`'s `position_scores`, plus `s4_paragraph_axis_baseline.snap_boundaries`'s
post-hoc nudge). This script measures the hard-anchor alternative before building it.

Attribution rule -- reuses existing machinery, no new matching logic: within one
Group-A-bounded gap (`build_anchor_backbone`), `segment_gap` already computes an "ideal"
even-split paragraph per rank (`ideal = low + rank * span // (count + 1)`, the same
dispersion baseline it scores every candidate against). A phrase hit inside the gap is
attributed to whichever rank's ideal position it sits closest to; a tie between two ranks
is ambiguous, not attributed. This is a *positional* claim ("a resolution opens near
here"), unlike Group B's *nominal* claim ("this named entity belongs to this
resolution") -- rank order is exactly the evidence `segment_gap` already uses, so this
reuses it rather than inventing a name/entity matcher.

Scoped to `pigeonhole_floor == 1` gaps only (where `segment_gap` runs at all today;
`floor > 1` gaps abstain regardless of what evidence is offered, per Step 3, and are out
of scope for this check).

Three comparisons per attributed, gold-scoreable rank, each a `segment_gap` call bounded
to that rank's own gap:
1. **baseline** -- `segment_gap` with no position evidence at all (pure even split).
2. **today** -- `segment_gap` with C's existing soft `position_scores`, then
   `snap_boundaries`'s post-hoc nudge -- i.e. current production shape.
3. **hard** -- the attributed hit's paragraph taken directly, bypassing `segment_gap`.

If `hard` does not beat `today` by much, or wins mostly where `today` already wins, a
hard-anchor role for C is not worth the staging machinery it would require. If `hard`
corrects cases `today` gets wrong, that is the signal 4a/4b would be built to exploit.

Scope: all `boundary_gold_sample` days (no harvest-file dependency -- phrase search is
live, same FuzzyPhraseSearcher pass `s4_paragraph_axis_baseline.py` already runs at this
scale). No dataset write, no manifest entry -- diagnostic only.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6c_group_c_attribution_check
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.pathology_corpus_stage_a import load_combined_overlap
from scripts.s4_corpus_paragraph_predictions import axis_for_date, grouped_enriched
from scripts.s4_paragraph_axis_baseline import (
    PHRASE_SEARCH_CONFIG,
    build_axis_overlap,
    phrase_hits,
    snap_to_phrase,
)
from scripts.s6a_char_axis_evaluation import char_starts
from scripts.s6c_gap_segmentation import build_anchor_backbone, segment_gap
from scripts.separated_accuracy_eval import gold_start_paragraphs

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

GOLD_DATASET = "boundary_gold_sample"
S2_PHRASE_DATASET = "s2_anchor_phrase_inventory"
S4_PHRASE_DATASET = "s4_opening_phrase_candidates"


def build_combined_c_searcher() -> FuzzyPhraseSearcher:
    s2_phrases = [entry["phrase"] for entry in load(S2_PHRASE_DATASET)["opening_phrases_top_20"]]
    s4_candidates = [entry["phrase"] for entry in load(S4_PHRASE_DATASET)[0]["candidates"] if entry["word_count"] >= 3]
    phrases = sorted(set(s2_phrases) | set(s4_candidates))
    return FuzzyPhraseSearcher(phrases, config=PHRASE_SEARCH_CONFIG)


def ideal_positions(low_anchor: int, high_anchor: int, count: int) -> list[int]:
    """Mirrors `segment_gap`'s own even-split baseline exactly -- the dispersion target
    every candidate position is scored against there."""
    span = high_anchor - low_anchor
    return [low_anchor + (rank * span) // (count + 1) for rank in range(1, count + 1)]


def attribute_hits_in_gap(
    low_axis: int, high_axis: int, gap: int, hits: dict[int, tuple[str, int, float]]
) -> tuple[dict[int, tuple[int, float]], int]:
    """rank (1-indexed within gap) -> (axis_index, similarity) for unambiguous attributions;
    second return value is the count of hits dropped to a tie."""
    low = low_axis
    high = max(low_axis, high_axis - 1)
    ideal = ideal_positions(low_axis, high_axis, gap)
    by_rank: dict[int, list[tuple[int, float]]] = {}
    ambiguous = 0
    for position, hit in hits.items():
        if not (low <= position <= high):
            continue
        distances = [abs(ideal[rank - 1] - position) for rank in range(1, gap + 1)]
        best_distance = min(distances)
        winners = [rank for rank, distance in enumerate(distances, start=1) if distance == best_distance]
        if len(winners) > 1:
            ambiguous += 1
            continue
        by_rank.setdefault(winners[0], []).append((position, hit[2]))
    attributed = {
        rank: max(candidates, key=lambda item: item[1]) for rank, candidates in by_rank.items()
    }
    return attributed, ambiguous


def check_day(
    date: str,
    day: dict[str, Any],
    axis_by_date: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
    combined_overlap,
    idf_weights: dict[str, float],
    enriched_by_date: dict[str, list[str]],
    searcher: FuzzyPhraseSearcher,
) -> dict[str, Any]:
    axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
    enriched_ids = enriched_by_date.get(date)
    result = {
        "date": date, "candidate_hits": 0, "ambiguous": 0, "attributed": 0, "scored": 0,
        "baseline_exact": 0, "today_exact": 0, "hard_exact": 0, "hard_novel_vs_today": 0,
        "hard_fixes_today": 0, "hard_breaks_today": 0,
    }
    if not axis or not enriched_ids:
        result["skipped"] = "missing_htr_or_enriched"
        return result

    k_e = len(enriched_ids)
    gold_starts = gold_start_paragraphs(day, k_e)
    axis_ids = [record["axis_id"] for record in axis]
    starts = char_starts(axis)

    overlap_lookup = build_axis_overlap(axis, combined_overlap)
    alignments = align_session(enriched_ids, axis_ids, overlap_lookup, idf_weights)
    backbone = build_anchor_backbone(k_e, len(axis_ids), alignments)
    hits = phrase_hits(axis, searcher)
    position_scores = {index: hit[2] for index, hit in hits.items()}

    for (left_enriched, left_axis), (right_enriched, right_axis) in zip(backbone, backbone[1:]):
        gap = right_enriched - left_enriched - 1
        if gap <= 0:
            continue
        room = max(1, right_axis - left_axis)
        if math.ceil(gap / room) > 1:
            continue  # out of scope -- segment_gap doesn't run here today either

        attributed, ambiguous = attribute_hits_in_gap(left_axis, right_axis, gap, hits)
        result["candidate_hits"] += sum(
            1 for position in hits if left_axis <= position <= max(left_axis, right_axis - 1)
        )
        result["ambiguous"] += ambiguous
        result["attributed"] += len(attributed)
        if not attributed:
            continue

        baseline_chosen = segment_gap(left_axis, right_axis, gap)
        today_chosen = segment_gap(left_axis, right_axis, gap, position_scores)
        today_snapped = [snap_to_phrase(position, hits)[0] for position in today_chosen]

        for rank, (hard_position, _similarity) in attributed.items():
            absolute_index = left_enriched + rank
            gold_position = gold_starts[absolute_index] if absolute_index < len(gold_starts) else None
            if gold_position is None:
                continue
            result["scored"] += 1
            baseline_position = baseline_chosen[rank - 1]
            today_position = today_snapped[rank - 1]
            baseline_ok = baseline_position == gold_position
            today_ok = today_position == gold_position
            hard_ok = hard_position == gold_position
            result["baseline_exact"] += baseline_ok
            result["today_exact"] += today_ok
            result["hard_exact"] += hard_ok
            if hard_position != today_position:
                result["hard_novel_vs_today"] += 1
                if hard_ok and not today_ok:
                    result["hard_fixes_today"] += 1
                if today_ok and not hard_ok:
                    result["hard_breaks_today"] += 1
    return result


def main() -> None:
    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    combined_overlap = load_combined_overlap()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_by_date = grouped_enriched()
    searcher = build_combined_c_searcher()

    gold = load(GOLD_DATASET)
    days_by_date = {str(day["date"]): day for day in gold["days"]}
    dates = sorted(days_by_date)
    print(f"gold days: {len(dates)}")

    totals: Counter[str] = Counter()
    for date in dates:
        r = check_day(
            date, days_by_date[date], axis_by_date, axis_by_session, session_by_date,
            combined_overlap, idf_weights, enriched_by_date, searcher,
        )
        for key in (
            "candidate_hits", "ambiguous", "attributed", "scored", "baseline_exact",
            "today_exact", "hard_exact", "hard_novel_vs_today", "hard_fixes_today", "hard_breaks_today",
        ):
            totals[key] += r.get(key, 0)
        print(
            f"{date}: candidates={r['candidate_hits']} ambiguous={r.get('ambiguous', 0)} "
            f"attributed={r.get('attributed', 0)} scored={r.get('scored', 0)} "
            f"baseline_exact={r.get('baseline_exact', 0)} today_exact={r.get('today_exact', 0)} "
            f"hard_exact={r.get('hard_exact', 0)} hard_vs_today_diff={r.get('hard_novel_vs_today', 0)} "
            f"(fixes={r.get('hard_fixes_today', 0)} breaks={r.get('hard_breaks_today', 0)})"
            + (f"  <-- {r['skipped']}" if r.get("skipped") else "")
        )

    candidates = totals["candidate_hits"] or 1
    scored = totals["scored"] or 1
    print(
        f"\n{len(dates)} days summary: candidate_hits={totals['candidate_hits']} "
        f"ambiguous={totals['ambiguous']} ({totals['ambiguous'] / candidates:.1%}) "
        f"attributed={totals['attributed']} ({totals['attributed'] / candidates:.1%})"
    )
    print(
        f"of attributed, gold-scoreable: {scored} -- exact agreement: "
        f"baseline(no evidence)={totals['baseline_exact'] / scored:.1%} "
        f"today(soft C + snap)={totals['today_exact'] / scored:.1%} "
        f"hard(C as backbone anchor)={totals['hard_exact'] / scored:.1%}"
    )
    print(
        f"hard disagrees with today on {totals['hard_novel_vs_today']} of {scored} scored ranks -- "
        f"of those, hard fixes a today-wrong case {totals['hard_fixes_today']} times and "
        f"breaks a today-right case {totals['hard_breaks_today']} times"
    )


if __name__ == "__main__":
    main()

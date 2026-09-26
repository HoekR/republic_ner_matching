#!/usr/bin/env python3
"""S6c -- count-constrained segmentation DP inside interpolate_positions's gaps.

Rescoped 2026-09-21 (docs/DECISIONS.md, docs/steps/STEP_S6_anchor_chain_alignment.md
section 3): two independent measurements (the S6 Step 1 oracle-anchor diagnostic and the
S6b full-corpus anchor harvest) agree that entity-anchor *placement*, not anchor *supply*,
binds the S4 baseline. `interpolate_positions` (scripts/s4_paragraph_axis_baseline.py)
aborts an entire day -- producing zero prediction, not a degraded one -- whenever any one
gap between two anchors cannot be interpolated cleanly:

* `folded_anchors_non_monotone` -- two different enriched resolutions share one paragraph
  (common: HTR under-segments 81.1% of days), so two anchors tie or invert in paragraph
  order and the strict `<` check fails.
* `axis_shorter_than_k_e` -- the paragraph axis has fewer paragraphs than the day has
  resolutions, so no strictly-increasing assignment exists at all.

Both are exactly the kind of thing paragraph-level *lumped* scoring (S6a) already
tolerates: several resolution starts collapsing onto one paragraph costs nothing there,
since lumped scoring de-duplicates by paragraph. So the fix is not a smarter search for
anchors (S6b already showed the anchor supply is not the bottleneck) -- it is letting the
placement step degrade to repeated paragraph assignments instead of abstaining.

This module replaces the *interpolation* step only, gap by gap, with a small DP that:

1. Builds a non-decreasing anchor backbone (out-of-order anchors are clipped forward
   rather than aborting the day), always anchored at the structural session start/end
   sentinels `(0, 0)` and `(k_e, axis_count)` per STEP_S6 section 2.2 group D, matching
   `s6b_known_point_ledger.py`'s chain convention.
2. Inside each gap, chooses `count` non-decreasing paragraph positions (repeats allowed,
   which is what absorbs both failure modes above) that both stay close to an even split
   of the gap and prefer any group-C phrase-hit evidence available at that gap, via
   `position_scores: dict[int, float]` (paragraph index -> bonus in roughly [0, 1]).

Group B (`entity_surface_matches_1626_1630`, `s4_fuzzy_surface_form_scan`) is not wired
into `position_scores` yet -- deliberately deferred, not overlooked. `s4_paragraph_axis_baseline.py`
already builds group-C phrase hits per gold day; scoring corpus-wide with group B/C would
need the same per-day FuzzyPhraseSearcher pass `s6b_anchor_harvest.py` needed ~32 minutes
(parallelized) for, which is heavy compute this module does not run by default -- see
PLAN.md for the handoff.

The old `interpolate_positions` is left untouched in s4_paragraph_axis_baseline.py:
`s6_oracle_anchor_diagnostic.py` deliberately pins to it (the unmodified placement model)
to measure anchor supply in isolation, and that comparison stays meaningful only if it
keeps testing the *old* model.
"""

from __future__ import annotations

from collections.abc import Sequence


def segment_gap(
    low_anchor: int,
    high_anchor: int,
    count: int,
    position_scores: dict[int, float] | None = None,
    phrase_weight: float = 3.0,
    dispersion_weight: float = 1.0,
) -> list[int]:
    """Place `count` non-decreasing paragraph positions between two anchors.

    Positions may repeat -- that is what lets a gap narrower than `count` (axis shorter
    than needed) still produce a usable, if imprecise, answer instead of nothing. Each
    slot's score trades off distance from an even split of the gap against any bonus in
    `position_scores` (phrase-hit similarity, roughly 0..1); `phrase_weight` /
    `dispersion_weight` set how many paragraphs of drift a perfect phrase hit is worth
    (default: about 3).
    """
    if count <= 0:
        return []
    position_scores = position_scores or {}
    low = low_anchor
    high = max(low_anchor, high_anchor - 1)
    positions = list(range(low, high + 1))
    span = high_anchor - low_anchor
    ideal = [low_anchor + (rank * span) // (count + 1) for rank in range(1, count + 1)]

    def score(position: int, rank: int) -> float:
        bonus = position_scores.get(position, 0.0) * phrase_weight
        penalty = dispersion_weight * abs(position - ideal[rank - 1])
        return bonus - penalty

    n = len(positions)
    neg = float("-inf")
    # dp[k][i]: best score choosing k non-decreasing slots from positions[0..i-1],
    # where a slot may reuse the same physical position as its neighbour (repeats
    # allowed by construction -- see docstring).
    dp = [[0.0] * (n + 1)] + [[neg] * (n + 1) for _ in range(count)]
    took = [[False] * (n + 1) for _ in range(count + 1)]
    for k in range(1, count + 1):
        for i in range(1, n + 1):
            skip = dp[k][i - 1]
            take = dp[k - 1][i] + score(positions[i - 1], k)
            if take > skip:
                dp[k][i] = take
                took[k][i] = True
            else:
                dp[k][i] = skip

    result: list[int] = []
    k, i = count, n
    while k > 0:
        if took[k][i]:
            result.append(positions[i - 1])
            k -= 1
        else:
            i -= 1
    result.reverse()
    return result


def segment_day(
    enriched_count: int,
    axis_count: int,
    alignments: Sequence[tuple[int | None, int | None]],
    position_scores: dict[int, float] | None = None,
) -> list[int]:
    """Count-constrained replacement for `interpolate_positions` that never abstains.

    Returns the `enriched_count - 1` paragraph positions at which resolutions 1..k_e-1
    open (resolution 0 is implicitly the session start). Unlike `interpolate_positions`,
    this always returns a list -- callers that want to keep an abstention path for other
    reasons (missing HTR, cross-day shift, ...) apply it before calling this.
    """
    if enriched_count <= 1:
        return []

    raw_anchors = sorted(
        {
            (int(enriched_index), int(axis_index))
            for enriched_index, axis_index in alignments
            if enriched_index is not None
            and axis_index is not None
            and 0 < enriched_index < enriched_count
            and 0 <= axis_index < axis_count
        }
    )

    # Non-decreasing backbone, always bounded by the structural session start/end
    # sentinels (STEP_S6 section 2.2 group D) -- an anchor that would go backwards
    # relative to the previous one is clipped forward rather than aborting the day.
    backbone: list[tuple[int, int]] = [(0, 0)]
    last_axis = 0
    for enriched_index, axis_index in raw_anchors:
        if enriched_index <= backbone[-1][0]:
            continue
        clipped = min(max(axis_index, last_axis), axis_count - 1)
        backbone.append((enriched_index, clipped))
        last_axis = clipped
    backbone.append((enriched_count, axis_count))

    positions = [0] * enriched_count
    for enriched_index, axis_index in backbone:
        if enriched_index < enriched_count:
            positions[enriched_index] = axis_index

    for (left_enriched, left_axis), (right_enriched, right_axis) in zip(backbone, backbone[1:]):
        gap = right_enriched - left_enriched - 1
        if gap <= 0:
            continue
        chosen = segment_gap(left_axis, right_axis, gap, position_scores)
        for offset, position in enumerate(chosen, start=1):
            positions[left_enriched + offset] = position

    return positions[1:]

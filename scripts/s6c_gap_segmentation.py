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
   `position_scores: dict[int, float]` (paragraph index -> bonus in roughly [0, 1]), or, for
   evidence that is specific to one resolution rather than to a paragraph, `rank_scores` /
   `segment_day`'s `resolution_scores` -- see `similarity_rank_scores` and
   plans/TFIDF_EMBEDDINGS_TRACK.md for what each form can and cannot express.

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

from collections.abc import Mapping, Sequence

import numpy as np


def segment_gap(
    low_anchor: int,
    high_anchor: int,
    count: int,
    position_scores: dict[int, float] | None = None,
    phrase_weight: float = 3.0,
    dispersion_weight: float = 1.0,
    rank_scores: Sequence[Mapping[int, float]] | None = None,
) -> list[int]:
    """Place `count` non-decreasing paragraph positions between two anchors.

    Positions may repeat -- that is what lets a gap narrower than `count` (axis shorter
    than needed) still produce a usable, if imprecise, answer instead of nothing. Each
    slot's score trades off distance from an even split of the gap against any bonus in
    `position_scores` (phrase-hit similarity, roughly 0..1); `phrase_weight` /
    `dispersion_weight` set how many paragraphs of drift a perfect phrase hit is worth
    (default: about 3).

    `rank_scores`, when given, supersedes `position_scores`: entry `rank_scores[rank - 1]`
    is the paragraph -> bonus map for the *specific* resolution that occupies slot `rank`
    of this gap. `position_scores` cannot express that -- it is one map shared by every
    slot, so a per-resolution signal has to be collapsed across resolutions before it can
    be passed (`similarity_position_scores` takes the per-paragraph max), which throws away
    exactly the which-resolution-goes-where information such a signal carries. The DP
    already fills slots in increasing rank and increasing position, so scoring slot `rank`
    with its own resolution's evidence needs no change to the recurrence.
    """
    if count <= 0:
        return []
    position_scores = position_scores or {}
    low = low_anchor
    high = max(low_anchor, high_anchor - 1)
    positions = list(range(low, high + 1))
    span = high_anchor - low_anchor
    ideal = [low_anchor + (rank * span) // (count + 1) for rank in range(1, count + 1)]

    def bonus(position: int, rank: int) -> float:
        if rank_scores is not None and rank - 1 < len(rank_scores):
            return rank_scores[rank - 1].get(position, 0.0)
        return position_scores.get(position, 0.0)

    def score(position: int, rank: int) -> float:
        penalty = dispersion_weight * abs(position - ideal[rank - 1])
        return bonus(position, rank) * phrase_weight - penalty

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


def similarity_position_scores(
    similarity_matrix: np.ndarray,
    scale: float = 1.0,
) -> dict[int, float]:
    """Convert similarity matrix into position_scores bonus per paragraph.

    For each paragraph (column), compute the max similarity across all resolutions (rows).
    This creates a bonus that biases gap-filling towards paragraphs where at least one
    resolution has high semantic similarity.

    Args:
        similarity_matrix: shape (k_e, k_p) — k_e resolutions, k_p paragraphs.
        scale: multiply all scores by this factor to control bonus magnitude vs. dispersion.

    Returns:
        dict mapping paragraph index -> bonus in roughly [0, scale].
    """
    if similarity_matrix is None or similarity_matrix.size == 0:
        return {}
    scores: dict[int, float] = {}
    max_sims = np.max(similarity_matrix, axis=0)  # max per paragraph across all resolutions
    for para_idx, max_sim in enumerate(max_sims):
        bonus = float(max_sim) * scale
        if bonus > 0:
            scores[int(para_idx)] = bonus
    return scores


RANK_NORMALIZATIONS = ("raw", "rownorm", "zscore")


def similarity_rank_scores(
    similarity_matrix: np.ndarray,
    scale: float = 1.0,
    normalize: str = "rownorm",
) -> dict[int, dict[int, float]]:
    """Per-resolution paragraph bonuses for `segment_gap`'s `rank_scores`.

    Keeps the similarity matrix's rows apart instead of collapsing them, so resolution `i`
    is scored by its *own* similarity profile (row `i`), not by whichever resolution happens
    to match a paragraph best.

    `normalize` fixes what the bonus means, which matters more than `scale`: the measured
    absolute similarity level (mean 0.1314 corpus-wide) is far larger than the
    correct-vs-best-wrong margin (0.0201), so a bonus proportional to the raw level is
    dominated by noise, whichever scale it is given (docs/DECISIONS.md, commit 8f90e4b).

    * ``raw`` -- bonus = similarity. The form already measured NEGATIVE; kept as the null.
    * ``rownorm`` -- bonus = similarity / row max, so each resolution's best paragraph scores
      `scale` and the level cancels out. Comparable across resolutions by construction.
    * ``zscore`` -- bonus = (similarity - row mean) / row std, clipped at 0, so only
      paragraphs this resolution likes *more than its own average* score at all, in units of
      that row's own dispersion.

    Args:
        similarity_matrix: shape (k_e, k_p) -- k_e resolutions, k_p paragraphs.
        scale: multiplies every bonus; trades off against `segment_gap`'s dispersion penalty
            of 1.0 per paragraph of drift (and is multiplied by `phrase_weight` on top).
        normalize: one of `RANK_NORMALIZATIONS`.

    Returns:
        dict mapping resolution index -> {paragraph index -> bonus}, sparse (zero and
        negative bonuses are omitted, which is what makes `zscore` a filter as well as a
        rescaling).
    """
    if normalize not in RANK_NORMALIZATIONS:
        raise ValueError(f"normalize must be one of {RANK_NORMALIZATIONS}, got {normalize!r}")
    if similarity_matrix is None or similarity_matrix.size == 0:
        return {}
    matrix = np.asarray(similarity_matrix, dtype=float)
    if matrix.ndim != 2:
        return {}

    if normalize == "raw":
        weights = matrix
    elif normalize == "rownorm":
        row_max = matrix.max(axis=1, keepdims=True)
        weights = np.divide(matrix, row_max, out=np.zeros_like(matrix), where=row_max > 0)
    else:
        row_mean = matrix.mean(axis=1, keepdims=True)
        row_std = matrix.std(axis=1, keepdims=True)
        weights = np.divide(
            matrix - row_mean, row_std, out=np.zeros_like(matrix), where=row_std > 0
        )
    weights = np.clip(weights, 0.0, None) * scale

    return {
        int(row): {int(column): float(weights[row, column]) for column in np.flatnonzero(weights[row])}
        for row in range(weights.shape[0])
        if weights[row].any()
    }


def segment_day(
    enriched_count: int,
    axis_count: int,
    alignments: Sequence[tuple[int | None, int | None]],
    position_scores: dict[int, float] | None = None,
    resolution_scores: Mapping[int, Mapping[int, float]] | None = None,
) -> list[int]:
    """Count-constrained replacement for `interpolate_positions` that never abstains.

    Returns the `enriched_count - 1` paragraph positions at which resolutions 1..k_e-1
    open (resolution 0 is implicitly the session start). Unlike `interpolate_positions`,
    this always returns a list -- callers that want to keep an abstention path for other
    reasons (missing HTR, cross-day shift, ...) apply it before calling this.

    `resolution_scores` maps *enriched resolution index* -> {paragraph -> bonus} and is
    sliced per gap into `segment_gap`'s rank-ordered `rank_scores`: slot `rank` of the gap
    after anchor `left_enriched` is resolution `left_enriched + rank`. Use it for evidence
    that is specific to one resolution (e.g. `similarity_rank_scores`); `position_scores`
    stays for evidence that only says "this paragraph looks like a boundary".
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
        rank_scores = (
            [resolution_scores.get(left_enriched + rank, {}) for rank in range(1, gap + 1)]
            if resolution_scores
            else None
        )
        chosen = segment_gap(left_axis, right_axis, gap, position_scores, rank_scores=rank_scores)
        for offset, position in enumerate(chosen, start=1):
            positions[left_enriched + offset] = position

    return positions[1:]

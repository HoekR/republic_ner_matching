#!/usr/bin/env python3
"""Step 3's "first experiment": project `align_entity_mentions`'s traceback onto paragraph
cut points inside `s6b_known_point_ledger.py`'s open gaps.

Pure placement primitives only (no I/O, no corpus-wide loop) -- `scripts/s6d_entity_alignment_gap_eval.py`
wires these to the gold days. Kept here, separate from the eval script, so the DP-adjacent geometry
(mention extraction, boundary bookkeeping, nearest-match projection) is unit-testable on small
synthetic fixtures per this repo's house style (see tests/test_s6b_known_point_ledger.py).

Vocabulary and the DP itself are NOT redefined here:
* the entity vocabulary is the same `name_frequencies` source `scripts/d1c_idf_band_order_eval.py`
  built from the three overlap tables (>= 4 chars, whatever `calculate_idf_weights` covers) --
  this module only compiles it into a scan pattern, it does not choose it;
* the alignment itself is `scripts.s6b_known_point_ledger.align_entity_mentions`, unchanged.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Sequence


def build_vocab_pattern(vocabulary: Sequence[str]) -> re.Pattern[str]:
    """One compiled alternation with word boundaries, longest names first so a longer name wins
    over a substring of itself at the same start position (Python's `|` tries alternatives in
    listed order). Word boundary \\b on both sides prevents `over` matching inside `overgelevert`.

    Note: \\b is sensitive to non-word characters -- entries like `d'ess` or `colvé` may have
    unexpected boundary behavior since apostrophes and accented vowels do not match \\w.
    """
    names = sorted({str(name).lower() for name in vocabulary if name}, key=len, reverse=True)
    if not names:
        return re.compile(r"(?!x)x")  # matches nothing
    return re.compile(r"\b(" + "|".join(re.escape(name) for name in names) + r")\b")


def ordered_mentions(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Vocabulary hits in `text`, left to right, non-overlapping (one symbol per mention)."""
    return [match.group(0) for match in pattern.finditer(str(text).lower())]


def mention_sequence(texts: Sequence[str], pattern: re.Pattern[str]) -> tuple[list[str], list[int]]:
    """Concatenated mention stream over `texts` in order, plus cumulative-count boundaries.

    `boundaries[k]` is the number of mentions strictly before `texts[k]`; `boundaries` has
    `len(texts) + 1` entries, so `boundaries[k]` is also the alignment-index threshold at which
    `texts[k]`'s own content begins.
    """
    mentions: list[str] = []
    boundaries = [0]
    for text in texts:
        mentions.extend(ordered_mentions(text, pattern))
        boundaries.append(len(mentions))
    return mentions, boundaries


def project_cuts(
    pairs: Sequence[tuple[int, int]],
    enriched_boundaries: Sequence[int],
    flat_boundaries: Sequence[int],
) -> list[int | None]:
    """One projected local flat-paragraph index per interior enriched unit, or `None`.

    `pairs` are the `(flat_index, enriched_index)` matches from `align_entity_mentions`'s
    traceback, in increasing order on both coordinates (the DP only ever advances). For each
    interior unit `k` (0-indexed, `len(enriched_boundaries) - 1` of them), the cut is placed at
    the paragraph of the first matched mention at or after that unit's own first mention
    (`enriched_boundaries[k]`); falling back to the last match before it when the unit itself and
    everything after it went unmatched. `None` when no pair exists on the relevant side at all --
    the caller must fall back to the existing baseline placement for that unit, never guess.
    """
    if not pairs:
        return [None] * (len(enriched_boundaries) - 1)

    results: list[int | None] = []
    for k in range(len(enriched_boundaries) - 1):
        target = enriched_boundaries[k]
        chosen_flat_index = None
        for flat_index, enriched_index in pairs:
            if enriched_index >= target:
                chosen_flat_index = flat_index
                break
        if chosen_flat_index is None:
            chosen_flat_index = pairs[-1][0]
        local_paragraph = bisect.bisect_right(flat_boundaries, chosen_flat_index) - 1
        results.append(max(0, local_paragraph))
    return results

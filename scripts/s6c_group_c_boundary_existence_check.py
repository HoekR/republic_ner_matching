#!/usr/bin/env python3
"""Step 5 (plans/archive/STAGED_ANCHOR_CONSOLIDATION.md, user follow-up 2026-10-02): does a Group C
phrase hit's mere *presence* inside an already-forced-abstention gap (`pigeonhole_floor > 1`)
predict that gold actually places a real boundary at that paragraph -- independent of which
specific resolution it belongs to?

This is a narrower claim than the one `s6c_group_c_attribution_check.py` already falsified
(docs/DECISIONS.md 2026-10-02): that script attributed a hit to a specific resolution *rank*
via positional nearest-ideal-split, scored on `pigeonhole_floor == 1` gaps, and found hard
attribution worse than today's soft wiring (30.9% vs 47.9%). It explicitly excluded
`floor > 1` gaps, because `segment_gap` abstains there today (Step 3) regardless of evidence.

This check targets exactly that excluded population, and a different, weaker question:
existence, not identity. "Resolution 2 of 3 opens here" was wrong; "a boundary of *some*
resolution sits here, as opposed to pure continuation text" is a binary per-paragraph label,
scoreable against gold without any attribution step at all.

Method, reusing existing machinery -- no new matching logic:
- `build_anchor_backbone` gives the same Group-A-anchored gaps the production DP sees.
- A gap is in scope iff `ceil(gap_count / room) > 1` (same pigeonhole test as
  `s6c_gap_segmentation.py`'s own `pigeonhole_floor`).
- Within scope, a gap is scored only if gold locates every resolution in it (no partial
  labels) -- `gold_start_paragraphs` gives each resolution's start paragraph; the set of
  *distinct* values among them is "real sub-boundary" paragraphs (gold may itself collapse
  several resolutions onto one paragraph -- that is a true negative for the other paragraphs
  in the gap, not a scoring error).
- `phrase_hits` (same combined Group C searcher as the attribution check) gives presence/
  absence per paragraph, with no rank or identity attached.
- Score a plain per-paragraph 2x2 (hit x boundary) over every paragraph in every scored gap,
  aggregated across the gold days. Precision/recall/lift over the base rate is the whole
  result -- no accuracy-on-placement number, because no placement is made.

Widening (user, 2026-10-05): the first run (docs/DECISIONS.md 2026-10-02) was inconclusive for
lack of data, not for lack of signal -- 20 `floor > 1` gaps in scope across the 50 original gold
days, of which only 2 scoreable (8 paragraphs). Open question (a) there was to widen the gold
population; this run does exactly that by reading `boundary_gold_hard_period_sample` alongside
the original, and reports each sample separately as well as combined. That sample is drawn from
severe-collapse / high-`|K_e - K_f|` days -- by construction the population that produces
crowded, forced-abstention gaps -- but it is only partly annotated, so most of its days still
contribute nothing and are counted as such rather than silently skipped.

Three conventions the hard-period sample introduces that the original gold never used, all
handled here and nowhere else yet:
- `kind == "date_start"` / `"date_end"`: the HTR session spans two calendar dates, and these
  bracket the part of the stream that belongs to *this* date. Paragraphs outside that bracket
  are clipped out of the scored window: a hit there may well open a real boundary of the
  neighbouring date, so counting it as a false positive against this day's gold would be wrong.
  Clipping only ever *narrows* the window -- it is not the window-widening that 2026-10-02
  deferred pending the user's sign-off.
- `unit == "no_htr_text"` cuts (null position): already unlocated by `is_located`, so they make
  their gap "incomplete" rather than inventing a start. No change needed, noted for the reader.
- Days annotated as having no locatable boundary at all are indistinguishable from unannotated
  ones in the merged sample (`annotated_at` is set for every day the merge touched), so a day
  with zero located opening slots is counted as `unlabelled`. Its `floor > 1` gaps are still
  counted -- they are the population the remaining annotation would unlock -- but kept out of
  the 2x2 under their own skip reason rather than lumped in with partially-labelled gaps.
`1626-03-28` is excluded by name, per the 2026-10-02 decision that it is a session/date mixup
rather than an annotatable boundary case.

Scope: all `boundary_gold_sample` + `boundary_gold_hard_period_sample` days, live phrase search
(same cost as the attribution check). No dataset write, no manifest entry -- diagnostic only.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6c_group_c_boundary_existence_check
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
from scripts.s4_paragraph_axis_baseline import build_axis_overlap, phrase_hits
from scripts.s6c_gap_segmentation import build_anchor_backbone
from scripts.s6a_char_axis_evaluation import opening_paragraph
from scripts.s6c_group_c_attribution_check import build_combined_c_searcher
from scripts.separated_accuracy_eval import OPENING_KINDS, gold_start_paragraphs, is_located

from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

GOLD_DATASET = "boundary_gold_sample"
HARD_GOLD_DATASET = "boundary_gold_hard_period_sample"

# docs/DECISIONS.md 2026-10-02: `1626-03-28`'s single visible resolution is the complete,
# archive-verified secret resolution for that date; its other 15 enriched entries live in another
# session entirely. There is no internal boundary to find, so it is not scoreable here.
EXCLUDED_DATES = {"1626-03-28"}


def gold_date_window(day: dict[str, Any]) -> tuple[int | None, int | None]:
    """`(first, last)` paragraph of *this* date's own content, from `date_start`/`date_end` slots.

    Only the hard-period sample carries these; `(None, None)` means "no constraint recorded", which
    is every original gold day. A `date_start` opens content, so it follows `opening_paragraph`'s
    paragraph_boundary convention; a `date_end` closes it, so the date's last paragraph is the
    slot's own index under either unit.
    """
    first = last = None
    for slot in day.get("boundaries") or []:
        if not is_located(slot):
            continue
        if slot.get("kind") == "date_start":
            first = opening_paragraph(slot)
        elif slot.get("kind") == "date_end":
            last = int(slot["paragraph_stream_index"])
    return first, last


def has_located_gold(day: dict[str, Any]) -> bool:
    """Whether gold locates any resolution opening at all on this day -- see module docstring."""
    return any(
        is_located(slot)
        for slot in day.get("boundaries") or []
        if slot.get("kind") in OPENING_KINDS
    )


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
        "date": date, "gaps_in_scope": 0, "gaps_scored": 0, "gaps_skipped_incomplete": 0,
        "gaps_skipped_gold_outside": 0, "gaps_skipped_date_clipped_empty": 0,
        "gaps_skipped_unlabelled_day": 0, "paragraphs_scored": 0, "paragraphs_clipped": 0,
        "boundary_paragraphs": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0,
        "days_unlabelled": 0, "days_missing_data": 0, "days_k_e_mismatch": 0,
    }
    if not axis or not enriched_ids:
        result["days_missing_data"] = 1
        result["skipped"] = "missing_htr_or_enriched"
        return result

    # An unlabelled day still goes through the backbone, so its `floor > 1` gaps are counted: that
    # is the population the rest of the hard-period annotation would unlock, which is the whole
    # reason for widening. Its gaps just cannot be scored.
    labelled = has_located_gold(day)
    result["days_unlabelled"] = 0 if labelled else 1

    k_e = len(enriched_ids)
    # `gold_start_paragraphs` indexes its cuts by enriched rank, so a `k_e` disagreement between the
    # live enriched stream and the sample's own recorded count would shift every start it returns.
    if day.get("k_e") is not None and int(day["k_e"]) != k_e:
        result["days_k_e_mismatch"] = 1
        result["skipped"] = f"k_e_mismatch(sample={day['k_e']} live={k_e})"
        return result
    gold_starts = gold_start_paragraphs(day, k_e)
    date_first, date_last = gold_date_window(day)
    axis_ids = [record["axis_id"] for record in axis]

    overlap_lookup = build_axis_overlap(axis, combined_overlap)
    alignments = align_session(enriched_ids, axis_ids, overlap_lookup, idf_weights)
    backbone = build_anchor_backbone(k_e, len(axis_ids), alignments)
    hits = phrase_hits(axis, searcher)

    for (left_enriched, left_axis), (right_enriched, right_axis) in zip(backbone, backbone[1:]):
        gap = right_enriched - left_enriched - 1
        if gap <= 0:
            continue
        room = max(1, right_axis - left_axis)
        if math.ceil(gap / room) <= 1:
            continue  # in scope for the attribution check, not this one
        result["gaps_in_scope"] += 1

        ranks = range(1, gap + 1)
        absolute_indices = [left_enriched + rank for rank in ranks]
        located = [
            gold_starts[index] if index < len(gold_starts) else None
            for index in absolute_indices
        ]
        if any(position is None for position in located):
            result["gaps_skipped_unlabelled_day" if not labelled else "gaps_skipped_incomplete"] += 1
            continue

        low = left_axis
        high = max(left_axis, right_axis - 1)
        if date_first is not None or date_last is not None:
            clipped_low = max(low, date_first) if date_first is not None else low
            clipped_high = min(high, date_last) if date_last is not None else high
            result["paragraphs_clipped"] += (high - low + 1) - max(0, clipped_high - clipped_low + 1)
            if clipped_high < clipped_low:
                result["gaps_skipped_date_clipped_empty"] += 1
                continue
            low, high = clipped_low, clipped_high
        if any(position < low or position > high for position in located):
            result["gaps_skipped_gold_outside"] += 1
            continue

        boundary_paragraphs = set(located)
        result["gaps_scored"] += 1
        result["boundary_paragraphs"] += len(boundary_paragraphs)
        for position in range(low, high + 1):
            result["paragraphs_scored"] += 1
            is_boundary = position in boundary_paragraphs
            has_hit = position in hits
            if has_hit and is_boundary:
                result["tp"] += 1
            elif has_hit and not is_boundary:
                result["fp"] += 1
            elif not has_hit and is_boundary:
                result["fn"] += 1
            else:
                result["tn"] += 1
    return result


TALLY_KEYS = (
    "gaps_in_scope", "gaps_scored", "gaps_skipped_incomplete", "gaps_skipped_gold_outside",
    "gaps_skipped_date_clipped_empty", "gaps_skipped_unlabelled_day", "paragraphs_scored",
    "paragraphs_clipped", "boundary_paragraphs", "tp", "fp", "fn", "tn",
    "days_unlabelled", "days_missing_data", "days_k_e_mismatch",
)


def load_gold_days() -> list[tuple[str, str, dict[str, Any]]]:
    """`(source, date, day)` across both gold samples, newest sample second, excluded dates dropped.

    The hard-period sample was built to exclude the original sample's dates, so an overlap would
    mean the samples have diverged from that contract and the same day would be scored twice.
    """
    by_source = {name: load(name)["days"] for name in (GOLD_DATASET, HARD_GOLD_DATASET)}
    seen: dict[str, str] = {}
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for source, days in by_source.items():
        for day in days:
            date = str(day["date"])
            if date in seen:
                raise ValueError(f"{date} appears in both {seen[date]} and {source}")
            seen[date] = source
            if date in EXCLUDED_DATES:
                continue
            rows.append((source, date, day))
    return rows


def report(label: str, n_days: int, totals: Counter[str]) -> None:
    tp, fp, fn, tn = totals["tp"], totals["fp"], totals["fn"], totals["tn"]
    scored_paragraphs = tp + fp + fn + tn
    print(
        f"\n{label} -- {n_days} days "
        f"({n_days - totals['days_unlabelled'] - totals['days_missing_data']} with located gold, "
        f"{totals['days_unlabelled']} annotated with nothing locatable, "
        f"{totals['days_missing_data']} with no HTR/enriched data at all"
        + (f", {totals['days_k_e_mismatch']} k_e mismatch" if totals["days_k_e_mismatch"] else "")
        + f"): gaps_in_scope={totals['gaps_in_scope']} gaps_scored={totals['gaps_scored']} "
        f"(skipped incomplete={totals['gaps_skipped_incomplete']} "
        f"outside={totals['gaps_skipped_gold_outside']} "
        f"date-clipped empty={totals['gaps_skipped_date_clipped_empty']} "
        f"on unlabelled days={totals['gaps_skipped_unlabelled_day']})"
    )
    if totals["paragraphs_clipped"]:
        print(f"paragraphs dropped as belonging to a neighbouring date: {totals['paragraphs_clipped']}")
    if not scored_paragraphs:
        print("paragraphs scored: 0 -- nothing to measure")
        return
    base_rate = (tp + fn) / scored_paragraphs
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    print(
        f"paragraphs scored: {scored_paragraphs} -- base rate of a paragraph being a real "
        f"boundary: {base_rate:.1%}"
    )
    print(
        f"hit presence: precision={precision:.1%} recall={recall:.1%} "
        f"(tp={tp} fp={fp} fn={fn} tn={tn}) -- lift over base rate: "
        f"{(precision / base_rate if base_rate else float('nan')):.2f}x"
    )


def main() -> None:
    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    combined_overlap = load_combined_overlap()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_by_date = grouped_enriched()
    searcher = build_combined_c_searcher()

    rows = sorted(load_gold_days(), key=lambda row: (row[0] != GOLD_DATASET, row[1]))
    per_source: dict[str, Counter[str]] = {}
    days_per_source: Counter[str] = Counter()
    print(f"gold days: {len(rows)} (excluded: {', '.join(sorted(EXCLUDED_DATES))})")

    for source, date, day in rows:
        r = check_day(
            date, day, axis_by_date, axis_by_session, session_by_date,
            combined_overlap, idf_weights, enriched_by_date, searcher,
        )
        totals = per_source.setdefault(source, Counter())
        days_per_source[source] += 1
        for key in TALLY_KEYS:
            totals[key] += r.get(key, 0)
        if r.get("gaps_in_scope"):
            print(
                f"{date} [{source}]: gaps_in_scope={r['gaps_in_scope']} scored={r['gaps_scored']} "
                f"(skipped incomplete={r['gaps_skipped_incomplete']} outside={r['gaps_skipped_gold_outside']} "
                f"date-clipped={r['gaps_skipped_date_clipped_empty']} "
                f"unlabelled={r['gaps_skipped_unlabelled_day']}) "
                f"paragraphs={r['paragraphs_scored']} boundaries={r['boundary_paragraphs']} "
                f"tp={r['tp']} fp={r['fp']} fn={r['fn']} tn={r['tn']}"
                + (f"  <-- {r['skipped']}" if r.get("skipped") else "")
            )

    combined: Counter[str] = Counter()
    for source, totals in per_source.items():
        report(source, days_per_source[source], totals)
        combined.update(totals)
    report("combined", sum(days_per_source.values()), combined)


if __name__ == "__main__":
    main()

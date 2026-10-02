#!/usr/bin/env python3
"""Step 4 pre-check (plans/STAGED_ANCHOR_CONSOLIDATION.md): does Group B carry a usable,
new signal, or mostly confusion?

Group B (`entity_surface_matches`, `fuzzy_surface_scan`) anchors are dictionary/fuzzy entity
hits positioned on the **axis** (char_position in one day's HTR paragraph concatenation), with
no link to a specific **enriched** resolution -- unlike Group A (`tier1_entity_nw`), which comes
from an existing `(enriched_id, axis_id) -> shared entity names` overlap table
(`place/org/per_overlap_1626_1630`, joined via `build_axis_overlap`). Both 4a's `rank_scores`
and 4b's relaxed `align_session` gate need that per-resolution attribution before Group B can be
wired in at all.

Rather than inventing new name-matching machinery (risk: a canonical-name substring/variant
mismatch would silently manufacture noise this check is supposed to rule out), this reuses the
project's own existing overlap artifact as the sole arbiter of attribution: a Group B anchor's
`canonical_name` is matched, case/whitespace-normalized, against the entity names
`build_axis_overlap` already resolved for that anchor's axis paragraph. If exactly one enriched
resolution's overlap set contains that name, the anchor is attributed to it; if none do, it is
unattributable by this mechanism; if more than one do, attribution is ambiguous. No new matching
logic, no new data.

Three questions, each gating the next:
1. **Attribution** -- how much of Group B even attaches to a specific enriched resolution this
   way, vs. unattributable/ambiguous?
2. **Correctness** -- among attributed anchors, scored against the 50-day `boundary_gold_sample`
   (`separated_accuracy_eval.gold_start_paragraphs`, same exact-start-paragraph convention as the
   rest of this track, guardrail 5 -- never gap-mass alone): does the attributed axis paragraph
   match gold's start paragraph for that resolution?
3. **Novelty** -- among the *correct* attributed anchors, how many are NOT already covered by a
   live Group A anchor (`align_session`, default `anchor_only_diagonal=True`,
   `semantic_weight=0.0`, recomputed fresh per Step 2's finding that the harvest's own
   `tier1_entity_nw` rows are stale) at the same (resolution, paragraph) cell? A correct-but-
   redundant anchor adds nothing Step 4 doesn't already have; a correct-and-novel one is the
   thing this step would actually be buying.

Scope: the 35 of 50 `boundary_gold_sample` days that also appear in the existing
`s6b_anchor_harvest.jsonl` (not yet re-run with the Step 2 harvest-date-enumeration fix, so this
reads current production harvest rows as-is -- out-of-bounds char_positions are counted and
reported, not silently dropped, consistent with how this fix's blast radius was already measured
for the 3 pathology seed days in `s6b_char_paragraph_join_check.py`). Scoped to gold days rather
than the 3 pathology seed days precisely because none of the 3 seed days carry gold -- Step 2's
join check already tested join mechanics there; this needs a correctness signal, so it needs gold
coverage instead.

No dataset write, no manifest entry -- diagnostic only, same posture as
`pathology_corpus_stage_a.py` and `s6b_char_paragraph_join_check.py`.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6b_group_b_signal_check
"""

from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from typing import Any

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.pathology_corpus_stage_a import load_combined_overlap
from scripts.s4_corpus_paragraph_predictions import axis_for_date, grouped_enriched
from scripts.s4_paragraph_axis_baseline import build_axis_overlap
from scripts.s6a_char_axis_evaluation import char_starts
from scripts.separated_accuracy_eval import gold_start_paragraphs

HARVEST_DATASET = "s6b_anchor_harvest"
GOLD_DATASET = "boundary_gold_sample"
B_CHANNELS = ("entity_surface_matches", "fuzzy_surface_scan")


def normalize(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


def names_by_axis(overlap_lookup: dict[tuple[str, str], set[str]]) -> dict[str, dict[str, set[str]]]:
    """Invert `build_axis_overlap`'s `(enriched_id, axis_id) -> names` lookup to
    `axis_id -> {enriched_id -> normalized names}`, one axis_id lookup per Group B anchor."""
    by_axis: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for (enriched_id, axis_id), names in overlap_lookup.items():
        by_axis[axis_id][enriched_id] = {normalize(name) for name in names}
    return by_axis


def resolve_axis_index(char_position: int, starts: list[int], n_paragraphs: int, total_chars: int) -> int | None:
    if char_position < 0 or char_position > total_chars:
        return None
    index = bisect.bisect_right(starts, char_position) - 1
    if not 0 <= index < n_paragraphs:
        return None
    return index


def check_day(
    date: str,
    day: dict[str, Any],
    harvest_rows: list[dict[str, Any]],
    axis_by_date: dict[str, list[dict[str, Any]]],
    axis_by_session: dict[str, list[dict[str, Any]]],
    session_by_date: dict[str, str],
    combined_overlap,
    idf_weights: dict[str, float],
    enriched_by_date: dict[str, list[str]],
) -> dict[str, Any]:
    axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
    enriched_ids = enriched_by_date.get(date)
    result = {
        "date": date, "n_b_rows": 0, "out_of_bounds": 0, "unattributed": 0, "ambiguous": 0,
        "attributed": 0, "scored": 0, "exact": 0, "within_1": 0,
        "novel_scored": 0, "novel_exact": 0,
    }
    if not axis or not enriched_ids:
        result["skipped"] = "missing_htr_or_enriched"
        return result

    k_e = len(enriched_ids)
    gold_starts = gold_start_paragraphs(day, k_e)
    rank_by_enriched_id = {eid: i for i, eid in enumerate(enriched_ids)}

    axis_ids = [record["axis_id"] for record in axis]
    starts = char_starts(axis)
    total_chars = starts[-1] + len(axis[-1]["text"]) if axis else 0
    n_paragraphs = len(axis_ids)

    overlap_lookup = build_axis_overlap(axis, combined_overlap)
    candidates_by_axis = names_by_axis(overlap_lookup)

    alignments = align_session(enriched_ids, axis_ids, overlap_lookup, idf_weights)
    live_group_a_pairs = {(i, j) for i, j in alignments if i is not None and j is not None}

    rows = [r for r in harvest_rows if r["date"] == date and r["channel"] in B_CHANNELS]
    result["n_b_rows"] = len(rows)
    for row in rows:
        axis_index = resolve_axis_index(row["char_position"], starts, n_paragraphs, total_chars)
        if axis_index is None:
            result["out_of_bounds"] += 1
            continue
        axis_id = axis_ids[axis_index]
        canonical = normalize(row["payload"].get("canonical_name", ""))
        if not canonical:
            result["unattributed"] += 1
            continue
        matched = [
            eid for eid, names in candidates_by_axis.get(axis_id, {}).items() if canonical in names
        ]
        if len(matched) == 0:
            result["unattributed"] += 1
            continue
        if len(matched) > 1:
            result["ambiguous"] += 1
            continue
        result["attributed"] += 1
        rank = rank_by_enriched_id.get(matched[0])
        if rank is None or rank >= len(gold_starts) or gold_starts[rank] is None:
            continue
        result["scored"] += 1
        is_novel_cell = (rank, axis_index) not in live_group_a_pairs
        if is_novel_cell:
            result["novel_scored"] += 1
        displacement = abs(axis_index - gold_starts[rank])
        if displacement == 0:
            result["exact"] += 1
            if is_novel_cell:
                result["novel_exact"] += 1
        if displacement <= 1:
            result["within_1"] += 1
    return result


def main() -> None:
    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    combined_overlap = load_combined_overlap()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_by_date = grouped_enriched()

    gold = load(GOLD_DATASET)
    days_by_date = {str(day["date"]): day for day in gold["days"]}

    harvest_rows = [r for r in load(HARVEST_DATASET) if "channel" in r]
    harvest_dates = {r["date"] for r in harvest_rows}
    dates = sorted(d for d in days_by_date if d in harvest_dates)
    print(f"gold days: {len(days_by_date)}, also in harvest: {len(dates)}")

    totals: Counter[str] = Counter()
    per_day = []
    for date in dates:
        r = check_day(
            date, days_by_date[date], harvest_rows, axis_by_date, axis_by_session, session_by_date,
            combined_overlap, idf_weights, enriched_by_date,
        )
        per_day.append(r)
        for key in ("n_b_rows", "out_of_bounds", "unattributed", "ambiguous", "attributed", "scored",
                     "exact", "within_1", "novel_scored", "novel_exact"):
            totals[key] += r.get(key, 0)
        print(
            f"{date}: b_rows={r['n_b_rows']} oob={r.get('out_of_bounds', 0)} "
            f"unattributed={r.get('unattributed', 0)} ambiguous={r.get('ambiguous', 0)} "
            f"attributed={r.get('attributed', 0)} scored={r.get('scored', 0)} "
            f"exact={r.get('exact', 0)} within_1={r.get('within_1', 0)} "
            f"novel_scored={r.get('novel_scored', 0)} novel_exact={r.get('novel_exact', 0)}"
            + (f"  <-- {r['skipped']}" if r.get("skipped") else "")
        )

    n_b = totals["n_b_rows"] or 1
    attributed = totals["attributed"] or 1
    scored = totals["scored"] or 1
    print(
        f"\n{len(dates)} days summary: b_rows={totals['n_b_rows']} "
        f"out_of_bounds={totals['out_of_bounds']} ({totals['out_of_bounds'] / n_b:.1%}) "
        f"unattributed={totals['unattributed']} ({totals['unattributed'] / n_b:.1%}) "
        f"ambiguous={totals['ambiguous']} ({totals['ambiguous'] / n_b:.1%}) "
        f"attributed={totals['attributed']} ({totals['attributed'] / n_b:.1%})"
    )
    novel_scored = totals["novel_scored"] or 1
    print(
        f"of attributed, gold-scoreable: {totals['scored']} ({totals['scored'] / attributed:.1%}); "
        f"exact_agreement={totals['exact'] / scored:.1%} within_1={totals['within_1'] / scored:.1%}"
    )
    print(
        f"of those scored rows, cell NOT already covered by live Group A: "
        f"{totals['novel_scored']} ({totals['novel_scored'] / scored:.1%} of scored) -- "
        f"exact_agreement on that novel subset: {totals['novel_exact'] / novel_scored:.1%} "
        f"({totals['novel_exact']}/{totals['novel_scored']})"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Step 2 of plans/COLLISION_AVOIDANCE_TRACK.md — does enriched text length predict HTR extent?

`segment_gap` (scripts/s6c_gap_segmentation.py:76) places its slots at *uniform* spacing::

    ideal = [low_anchor + (rank * span) // (count + 1) for rank in range(1, count + 1)]

i.e. it assumes every resolution inside a gap occupies the same amount of text. That default fires
whenever no anchor evidence is available, which is the code path responsible for the bulk of the
corpus-wide collision losses (finding A in the track file). Hypothesis 6 of the track says long and
short resolutions are reflected as such in *both* streams, so a length-proportional prior should
beat uniform spacing for free — no new evidence channel, using enriched text already on disk.

This script measures that on the boundary gold sample, two ways:

1. **Correlation.** Per gold day, each resolution's share of the day's enriched summary text vs its
   share of the day's HTR text (characters, composed from the paragraph axis by pure concatenation
   plus the gold boundary's own ``char_offset`` -- the S6a convention). Spearman and Pearson,
   pooled over all resolutions and averaged per day.

2. **Anchor-free A/B.** Predict cuts for each day from the day's structural bounds alone, under
   (a) the uniform rule above and (b) cumulative enriched-length shares, and score both against
   gold. This isolates the placement *prior* from every anchor channel, which is what Step 2 is
   actually deciding.

Metric choice: mean absolute displacement in **paragraphs** and the project's own **separated**
criterion (unique start paragraph on the day, extent <= 3). Deliberately NOT tolerance-threshold
F1 at char offsets -- that family is ruled out as a target. Character offsets are used here only
to measure text *lengths*, never to score boundary precision.

Usage:
    uv run python -m scripts.length_prior_eval
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured
from scripts.evaluate_s4_paragraph_axis import review_codes
from scripts.s4_corpus_paragraph_predictions import AXIS_DATASET, axis_for_date, resolved_sessions, session_of

GOLD_DATASET = "boundary_gold_sample"
ENRICHED_DATASET = "enriched_resolutions_1626_1630"
OUTPUT_DATASET = "length_prior_eval"

MAX_EXTENT_PARAGRAPHS = 3


def enriched_text_by_gold_id() -> dict[str, str]:
    """Map the gold sample's '<file>#<resolution_index>' ids to enriched summary text."""
    return {
        f"{record['file']}#{record['resolution_index']}": str(record.get("text") or "")
        for record in load(ENRICHED_DATASET)
        if record.get("file") is not None and record.get("resolution_index") is not None
    }


def gold_starts(day: dict[str, Any], k_e: int) -> list[dict[str, Any] | None]:
    """Per-resolution start markers, indexed by resolution order; None where unlocated.

    ``boundaries`` is in resolution order but is neither complete nor uniformly annotated: markers
    the annotator could not place carry no ``flat_id`` and a null ``char_offset``, and are parked
    at the day's last paragraph index (verified: 1626-02-03 parks at 28 of 29 paragraphs). Treating
    those as real starts fabricates extents, so they are held out as None rather than dropped --
    the resolution still exists, only its location is unknown.
    """
    boundaries = day.get("boundaries") or []
    starts: list[dict[str, Any] | None] = []
    for index in range(k_e):
        if index >= len(boundaries):
            starts.append(None)
            continue
        boundary = boundaries[index]
        located = (
            boundary.get("flat_id") is not None
            and boundary.get("char_offset") is not None
            and boundary.get("paragraph_stream_index") is not None
        )
        starts.append(
            {
                "paragraph_stream_index": int(boundary["paragraph_stream_index"]),
                "char_offset": int(boundary["char_offset"]),
            }
            if located
            else None
        )
    return starts


def char_axis(axis: list[dict[str, Any]]) -> tuple[list[int], int]:
    """Cumulative character offset at the start of each paragraph, by pure concatenation."""
    offsets: list[int] = []
    running = 0
    for record in axis:
        offsets.append(running)
        running += len(str(record.get("text") or ""))
    return offsets, running


def absolute_char(start: dict[str, Any], offsets: list[int], total_chars: int) -> int:
    index = start["paragraph_stream_index"]
    if index >= len(offsets):
        return total_chars
    return min(offsets[index] + start["char_offset"], total_chars)


def uniform_cuts(paragraph_count: int, k_e: int) -> list[int]:
    """Exactly segment_gap's ideal spacing over the whole day (low=0, high=paragraph_count)."""
    return [(rank * paragraph_count) // k_e for rank in range(1, k_e)]


def proportional_cuts(paragraph_count: int, enriched_lengths: list[int]) -> list[int]:
    total = sum(enriched_lengths)
    if total <= 0:
        return uniform_cuts(paragraph_count, len(enriched_lengths))
    cuts: list[int] = []
    running = 0
    for length in enriched_lengths[:-1]:
        running += length
        cuts.append(min(int(round(paragraph_count * running / total)), paragraph_count))
    return cuts


def mean_abs_displacement(predicted: list[int], reference: list[int]) -> float | None:
    if not reference or len(predicted) != len(reference):
        return None
    return sum(abs(p - r) for p, r in zip(predicted, reference)) / len(reference)


def separated_count(cuts: list[int], paragraph_count: int) -> int:
    starts = [0] + list(cuts)
    ends = list(cuts) + [paragraph_count]
    share = Counter(starts)
    return sum(
        1
        for start, end in zip(starts, ends)
        if share[start] == 1 and (end - start + 1) <= MAX_EXTENT_PARAGRAPHS
    )


def correlate(frame: pd.DataFrame, left: str, right: str) -> dict[str, float | None]:
    if len(frame) < 3 or frame[left].nunique() < 2 or frame[right].nunique() < 2:
        return {"spearman": None, "pearson": None, "n": len(frame)}
    return {
        "spearman": float(frame[left].corr(frame[right], method="spearman")),
        "pearson": float(frame[left].corr(frame[right], method="pearson")),
        "n": len(frame),
    }


def main() -> None:
    gold = load(GOLD_DATASET)
    codes = review_codes()
    enriched_text = enriched_text_by_gold_id()

    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        axis_by_date[str(record["date"])].append(record)
        axis_by_session[session_of(record["flat_id"])].append(record)
    session_by_date = resolved_sessions()

    rows: list[dict[str, Any]] = []
    per_day: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()

    for day in gold["days"]:
        date = str(day["date"])
        k_e = int(day["k_e"])
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        if not axis:
            skipped["no_axis"] += 1
            continue

        starts = gold_starts(day, k_e)
        lengths = [len(enriched_text.get(str(eid), "")) for eid in day["enriched_ids"]]
        if len(lengths) != k_e or sum(lengths) == 0:
            skipped["enriched_text_unavailable"] += 1
            continue

        offsets, total_chars = char_axis(axis)
        paragraph_count = len(axis)
        review_code = codes.get(date, "S")

        # Extents are only defined where two *consecutive* resolutions are both located.
        pairs = 0
        for i in range(k_e - 1):
            here, following = starts[i], starts[i + 1]
            if here is None or following is None:
                continue
            extent = absolute_char(following, offsets, total_chars) - absolute_char(here, offsets, total_chars)
            if extent < 0:
                continue
            pairs += 1
            rows.append(
                {
                    "date": date,
                    "review_code": review_code,
                    "enriched_id": str(day["enriched_ids"][i]),
                    "resolution_index": i,
                    "k_e": k_e,
                    "enriched_chars": lengths[i],
                    "htr_chars": extent,
                    "enriched_share": lengths[i] / sum(lengths),
                    "htr_share": (extent / total_chars) if total_chars else 0.0,
                }
            )

        cuts_uniform = uniform_cuts(paragraph_count, k_e)
        cuts_proportional = proportional_cuts(paragraph_count, lengths)
        # Score displacement only at ranks where gold actually located the resolution.
        located_ranks = [j for j in range(1, k_e) if starts[j] is not None]
        reference = [starts[j]["paragraph_stream_index"] for j in located_ranks]
        uniform_at = [cuts_uniform[j - 1] for j in located_ranks]
        proportional_at = [cuts_proportional[j - 1] for j in located_ranks]

        per_day.append(
            {
                "date": date,
                "review_code": review_code,
                "k_e": k_e,
                "paragraph_count": paragraph_count,
                "total_chars": total_chars,
                "located_starts": sum(1 for s in starts if s is not None),
                "extent_pairs": pairs,
                "uniform_mean_abs_displacement": mean_abs_displacement(uniform_at, reference),
                "proportional_mean_abs_displacement": mean_abs_displacement(proportional_at, reference),
                "uniform_separated": separated_count(cuts_uniform, paragraph_count),
                "proportional_separated": separated_count(cuts_proportional, paragraph_count),
                "gold_separated_ceiling": separated_count(sorted(reference), paragraph_count),
            }
        )

    frame = pd.DataFrame(rows)
    day_frame = pd.DataFrame(per_day)

    def cohort(label: str, sub_rows: pd.DataFrame, sub_days: pd.DataFrame) -> dict[str, Any]:
        per_day_spearman = [
            value
            for _, group in sub_rows.groupby("date")
            if (value := correlate(group, "enriched_chars", "htr_chars")["spearman"]) is not None
        ]
        displacement = sub_days.dropna(subset=["uniform_mean_abs_displacement"])
        return {
            "cohort": label,
            "days": int(len(sub_days)),
            "extent_pairs": int(len(sub_rows)),
            "correlation_pooled_absolute_chars": correlate(sub_rows, "enriched_chars", "htr_chars"),
            "correlation_pooled_within_day_share": correlate(sub_rows, "enriched_share", "htr_share"),
            "per_day_spearman_mean": float(pd.Series(per_day_spearman).mean()) if per_day_spearman else None,
            "per_day_spearman_median": float(pd.Series(per_day_spearman).median()) if per_day_spearman else None,
            "per_day_spearman_positive_days": int(sum(1 for v in per_day_spearman if v > 0)),
            "per_day_spearman_days": len(per_day_spearman),
            "uniform_mean_abs_displacement": float(displacement["uniform_mean_abs_displacement"].mean())
            if len(displacement)
            else None,
            "proportional_mean_abs_displacement": float(displacement["proportional_mean_abs_displacement"].mean())
            if len(displacement)
            else None,
            "uniform_separated_total": int(sub_days["uniform_separated"].sum()),
            "proportional_separated_total": int(sub_days["proportional_separated"].sum()),
            "gold_separated_ceiling_total": int(sub_days["gold_separated_ceiling"].sum()),
            "k_e_total": int(sub_days["k_e"].sum()),
        }

    cohorts = [cohort("all_scored_days", frame, day_frame)]
    clean_days = day_frame[day_frame["review_code"] == "S"]
    cohorts.append(cohort("review_code_S_only", frame[frame["review_code"] == "S"], clean_days))

    summary = {
        "record_type": "summary",
        "gold_days_total": len(gold["days"]),
        "gold_days_scored": len(day_frame),
        "skipped": dict(skipped),
        "review_code_counts": day_frame["review_code"].value_counts().to_dict(),
        "cohorts": cohorts,
    }

    output = save_semi_structured(
        [summary, *per_day, *rows],
        logical_name=OUTPUT_DATASET,
        script=__file__,
    )

    print(f"Wrote length-prior evaluation to {output}")
    print(f"  gold days scored: {summary['gold_days_scored']}/{summary['gold_days_total']} "
          f"(skipped: {summary['skipped']})")
    print(f"  review codes: {summary['review_code_counts']}")

    def fmt(value: float | None, digits: int = 3) -> str:
        return "n/a" if value is None else f"{value:.{digits}f}"

    for entry in cohorts:
        abs_corr = entry["correlation_pooled_absolute_chars"]
        share_corr = entry["correlation_pooled_within_day_share"]
        print()
        print(f"  [{entry['cohort']}] {entry['days']} days, {entry['extent_pairs']} extent pairs")
        print("    correlation, enriched chars vs HTR chars:")
        print(f"      pooled absolute        : spearman={fmt(abs_corr['spearman'])} "
              f"pearson={fmt(abs_corr['pearson'])} (n={abs_corr['n']})")
        print(f"      pooled within-day share: spearman={fmt(share_corr['spearman'])} "
              f"pearson={fmt(share_corr['pearson'])}")
        print(f"      per-day spearman       : mean={fmt(entry['per_day_spearman_mean'])} "
              f"median={fmt(entry['per_day_spearman_median'])} "
              f"positive on {entry['per_day_spearman_positive_days']}/{entry['per_day_spearman_days']} days")
        print("    anchor-free A/B (no entity evidence at all):")
        print(f"      mean |displacement| paragraphs: uniform={fmt(entry['uniform_mean_abs_displacement'])} "
              f"proportional={fmt(entry['proportional_mean_abs_displacement'])}")
        print(f"      separated: uniform={entry['uniform_separated_total']} "
              f"proportional={entry['proportional_separated_total']} "
              f"(gold itself scores {entry['gold_separated_ceiling_total']} of {entry['k_e_total']})")


if __name__ == "__main__":
    main()

"""Measure whether a position is predictable from a local uniform expectation -- the first
question to answer before adding a positional-prior cost term to `align_bracket` (the user's
worked example, 2026-10-09: known anchors + a session's own k_e make a decaying plausibility
prior for where an unplaced resolution sits).

**Step 1 only: measure, don't build yet.** This does not touch `CostModel` or `align_bracket`.
It answers one question: across `gold_aligned_pairs`' 345 real correspondences, how far does the
true position actually fall from what a uniform spread over the bracket would predict? If that
displacement is small and tight, a positional prior is worth building. If it is wide or
unpredictable, building the cost term first would be adding machinery before checking it helps --
exactly what this measurement exists to prevent.

**Not yet the multi-session, anchor-bounded "local" expectation from the worked example** -- that
needs `align_bracket` to run per-gap between `running_axis.chain`'s hard anchors first (the
scoping step this measurement feeds into). For now, "local" means "within one
`boundary_gold_sample` bracket" (today's only population), i.e. the single-day uniform spread
already used elsewhere in this project as the null baseline (`uniform_start_paragraphs`) --
repurposed here as the *expectation* a prior would center on, not as a baseline to beat.

Usage:
    uv run python -m sequence_graph.position_prior
"""

from __future__ import annotations

import argparse

import pandas as pd

from data_io import load
from scripts.corpus_scope import in_scope
from scripts.separated_accuracy_eval import gold_start_paragraphs, uniform_start_paragraphs

from sequence_graph.align import day_paragraph_stream

GOLD_DATASET = "boundary_gold_sample"


def measure_displacement() -> pd.DataFrame:
    """One row per gold-located resolution: its true position, the local uniform-spread
    expectation for that same bracket, and their displacement. Non-circular by construction --
    reads only `boundary_gold_sample`, never a solver-derived edge."""
    rows: list[dict] = []
    for day in load(GOLD_DATASET)["days"]:
        date = day["date"]
        if not in_scope(date):
            continue
        k_e = day["k_e"]
        if k_e < 2:
            continue  # a spread needs >= 2 resolutions to say anything about position
        stream = day_paragraph_stream(date)
        if not stream:
            continue
        starts = gold_start_paragraphs(day, k_e)
        expected = uniform_start_paragraphs(len(stream), k_e)
        for ref_index, (true_position, expected_position) in enumerate(zip(starts, expected)):
            if true_position is None:
                continue
            rows.append({
                "date": date, "ref_index": ref_index, "k_e": k_e, "room": len(stream),
                "true_position": true_position, "expected_position": expected_position,
                "displacement": true_position - expected_position,
            })
    return pd.DataFrame(rows)


def summarize(displacements: pd.DataFrame) -> dict:
    d = displacements["displacement"]
    return {
        "n": len(d),
        "mean": d.mean(),
        "std": d.std(),
        "median": d.median(),
        "mad": (d - d.median()).abs().median(),
        "share_within_1": (d.abs() <= 1).mean(),
        "share_within_2": (d.abs() <= 2).mean(),
        "min": d.min(),
        "max": d.max(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    displacements = measure_displacement()
    stats = summarize(displacements)
    print(f"n = {stats['n']} gold-located resolutions, {displacements['date'].nunique()} days")
    print(f"mean displacement:   {stats['mean']:+.3f} paragraphs")
    print(f"median displacement: {stats['median']:+.3f} paragraphs (MAD {stats['mad']:.3f})")
    print(f"std displacement:    {stats['std']:.3f} paragraphs")
    print(f"within 1 paragraph:  {stats['share_within_1']:.1%}")
    print(f"within 2 paragraphs: {stats['share_within_2']:.1%}")
    print(f"range: [{stats['min']:+d}, {stats['max']:+d}]")

    print("\nby k_e bucket (does the prior get worse on long days, as it should if it's real):")
    displacements["k_e_bucket"] = pd.cut(
        displacements["k_e"], bins=[0, 3, 7, 15, 1000], labels=["1-3", "4-7", "8-15", "16+"],
    )
    for bucket, group in displacements.groupby("k_e_bucket", observed=True):
        print(f"  k_e {bucket}: n={len(group)}, std={group['displacement'].std():.3f}, "
              f"within_1={((group['displacement']).abs() <= 1).mean():.1%}")


if __name__ == "__main__":
    main()

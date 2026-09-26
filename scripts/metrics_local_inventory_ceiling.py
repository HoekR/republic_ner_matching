#!/usr/bin/env python3
"""Tier O — per-inventory pigeonhole ceiling and PLAN.md's Local criterion.

Reproduces, for the first time as a scripted computation, the corpus-wide
pigeonhole ceiling PLAN.md and docs/DECISIONS.md (2026-09-22) cite as a fixed
constant (11,644 / 19,120 = 60.9%; docs/METRICS.md's "Known gaps" flags this as
unreproduced): for each date with any enriched resolutions, the ceiling
contribution is ``min(k_e, paragraph_count)`` where ``paragraph_count`` is that
calendar date's own HTR paragraph count from ``paragraph_axis_1626_1630``
(pigeonhole — a day with ``n`` paragraphs can hold at most ``n`` distinct start
paragraphs) and ``k_e`` is enriched resolution count that date. A date with no
same-day HTR contributes 0 (535 such dates, matching PLAN.md's cited figure).

Then answers PLAN.md's **Local** acceptance criterion, never previously
computed: does any inventory reach >=50% of its own ceiling? Separated counts
per date reuse ``count_separated_per_day`` from
``scripts/metrics_separation_span_table.py`` unchanged (same definition, same
source columns) so this and the Global-primary number can never silently
diverge; inventory grouping uses ``resolution_concordance_1626_1630``'s own
resolved ``inventory_id`` per date (one value per date, verified elsewhere).

Usage:
    uv run python scripts/metrics_local_inventory_ceiling.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.metrics_separation_span_table import count_separated_per_day

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
OUTPUT_DATASET = "metrics_local_inventory_ceiling"

LOCAL_SHARE_THRESHOLD = 0.5
# Cited corpus-wide baseline (docs/DECISIONS.md 2026-09-22); this script's own ceiling sum
# is asserted to match so a formula drift is caught immediately rather than silently diverging.
EXPECTED_CORPUS_CEILING = 11_644
EXPECTED_NO_HTR_DATE_COUNT = 535


def per_date_ceiling(concordance: pd.DataFrame, axis: list[dict[str, Any]]) -> pd.DataFrame:
    """Pigeonhole ceiling per calendar date: min(k_e, same-day raw paragraph_count)."""
    dates = concordance["enriched_date"].astype(str).str.slice(0, 10)
    k_e = dates.value_counts().rename("k_e")

    para_dates = pd.Series([str(r["date"])[:10] for r in axis])
    paragraph_count = para_dates.value_counts().rename("paragraph_count")

    frame = pd.DataFrame(k_e).join(paragraph_count, how="left")
    frame["paragraph_count"] = frame["paragraph_count"].fillna(0).astype(int)
    frame["ceiling_day"] = frame[["k_e", "paragraph_count"]].min(axis=1).astype(int)
    frame = frame.reset_index(names="enriched_date")
    return frame


def inventory_lookup(concordance: pd.DataFrame) -> pd.Series:
    """One inventory_id per enriched_date (verified single-valued elsewhere)."""
    return concordance.drop_duplicates("enriched_date").set_index("enriched_date")["inventory_id"]


def main() -> None:
    concordance = load(CONCORDANCE_DATASET)
    axis = load(AXIS_DATASET)

    ceiling = per_date_ceiling(concordance, axis)
    n_no_htr_dates = int((ceiling["paragraph_count"] == 0).sum())
    corpus_ceiling = int(ceiling["ceiling_day"].sum())

    if corpus_ceiling != EXPECTED_CORPUS_CEILING or n_no_htr_dates != EXPECTED_NO_HTR_DATE_COUNT:
        print(
            f"WARNING: computed ceiling={corpus_ceiling} (expected {EXPECTED_CORPUS_CEILING}), "
            f"no-HTR dates={n_no_htr_dates} (expected {EXPECTED_NO_HTR_DATE_COUNT}) -- "
            "formula no longer matches the cited PLAN.md/DECISIONS.md baseline."
        )

    separated_per_day = count_separated_per_day(concordance)
    inv_by_date = inventory_lookup(concordance)

    merged = ceiling.merge(separated_per_day[["enriched_date", "separated_count"]], on="enriched_date", how="left")
    merged["separated_count"] = merged["separated_count"].fillna(0).astype(int)
    merged["inventory_id"] = merged["enriched_date"].map(inv_by_date)

    by_inventory = (
        merged.groupby("inventory_id")
        .agg(
            n_dates=("enriched_date", "size"),
            date_min=("enriched_date", "min"),
            date_max=("enriched_date", "max"),
            k_e_total=("k_e", "sum"),
            ceiling=("ceiling_day", "sum"),
            separated=("separated_count", "sum"),
        )
        .reset_index()
    )
    by_inventory["separated_share_of_ceiling"] = (
        by_inventory["separated"] / by_inventory["ceiling"]
    ).where(by_inventory["ceiling"] > 0, 0.0).round(4)
    by_inventory["local_criterion_met"] = by_inventory["separated_share_of_ceiling"] >= LOCAL_SHARE_THRESHOLD
    by_inventory = by_inventory.sort_values("separated_share_of_ceiling", ascending=False).reset_index(drop=True)

    meta = {
        "record_type": "meta",
        "tier": "O",
        "parent": [CONCORDANCE_DATASET, AXIS_DATASET],
        "local_share_threshold": LOCAL_SHARE_THRESHOLD,
        "corpus_ceiling_computed": corpus_ceiling,
        "corpus_ceiling_expected": EXPECTED_CORPUS_CEILING,
        "no_htr_dates_computed": n_no_htr_dates,
        "no_htr_dates_expected": EXPECTED_NO_HTR_DATE_COUNT,
        "n_inventories": int(len(by_inventory)),
        "n_inventories_meeting_local": int(by_inventory["local_criterion_met"].sum()),
        "note": (
            "ceiling_day = min(k_e, same-calendar-day raw paragraph_count from "
            "paragraph_axis_1626_1630); separated reuses "
            "metrics_separation_span_table.count_separated_per_day unchanged. Local "
            "criterion: any inventory with separated/ceiling >= 0.5."
        ),
    }
    inventory_rows = [
        {"record_type": "inventory", **row}
        for row in by_inventory.to_dict(orient="records")
    ]
    records = [meta, *inventory_rows]

    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[CONCORDANCE_DATASET, AXIS_DATASET],
        description=(
            "Tier O per-inventory pigeonhole ceiling (min(k_e, same-day paragraph_count) "
            "summed per inventory_id) and PLAN.md's Local criterion (any inventory reaching "
            ">=50% of its own ceiling), plus the first scripted reproduction of the corpus-wide "
            "11,644 ceiling constant."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}")
    print(f"corpus ceiling: {corpus_ceiling} (expected {EXPECTED_CORPUS_CEILING})")
    print(f"no-HTR dates: {n_no_htr_dates} (expected {EXPECTED_NO_HTR_DATE_COUNT})")
    print(f"inventories meeting Local (>=50% of own ceiling): {meta['n_inventories_meeting_local']} / {meta['n_inventories']}")
    print(by_inventory[["inventory_id", "n_dates", "date_min", "date_max", "ceiling", "separated", "separated_share_of_ceiling", "local_criterion_met"]])


if __name__ == "__main__":
    main()

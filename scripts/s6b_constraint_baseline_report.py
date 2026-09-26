#!/usr/bin/env python3
"""Render the S6b constraint baseline to docs/S6B_CONSTRAINT_BASELINE.md.

Reads the registered `s6b_known_point_ledger` dataset and writes a readable report:
overall figures, the per-month table, and the year / inventory rollups that say whether
any month-to-month movement is real.

Separated from the ledger script so the measurement and its presentation can change
independently -- re-render without recomputing, recompute without touching prose.

Usage:
    uv run python -m scripts.s6b_constraint_baseline_report
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_io import load


LEDGER_DATASET = "s6b_known_point_ledger"
REPORT_PATH = Path("docs/S6B_CONSTRAINT_BASELINE.md")


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def rollup_table(rollup: dict[str, dict[str, Any]], label: str) -> list[str]:
    """One row per period: counts first, then the two shares that disagree."""
    lines = [
        f"| {label} | days | no axis | resolutions | pinned | pinned % | det. | nearly | open | unplaced | in open | open % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, entry in rollup.items():
        buckets = entry["buckets"]
        unplaced = entry["unplaced_resolutions"]
        lines.append(
            f"| {name} | {entry['days']} | {entry['days_without_axis']} | {entry['resolutions']} | "
            f"{entry['interior_known_points']} | {pct(entry['pinned_share_of_resolutions'])} | "
            f"{buckets['determined']['gaps']} | {buckets['nearly_determined']['gaps']} | {buckets['open']['gaps']} | "
            f"{unplaced} | {buckets['open']['resolutions']} | {pct(entry['open_share_by_resolution'])} |"
        )
    return lines


def main() -> None:
    rows = load(LEDGER_DATASET)
    report = rows[0]
    overall = report["overall"]
    buckets = overall["buckets"]
    window = report["window"]
    nearly_max = report["nearly_determined_max"]

    sizes = overall["gap_size_distribution"]
    largest = max((int(size) for size in sizes), default=0)

    lines: list[str] = [
        "# S6b — constraint baseline: known points and counted gaps",
        "",
        f"Window **{window['start']} → {window['end']}**, generated from the registered "
        f"`{LEDGER_DATASET}` dataset by [scripts/s6b_constraint_baseline_report.py]"
        "(../scripts/s6b_constraint_baseline_report.py).",
        "",
        "## What this measures",
        "",
        "This is a baseline of the **problem**, not of a model — nothing here predicts anything.",
        "Along each day's character stream the ledger chains every *known* point:",
        "",
        "```",
        "[session start] … [known resolution i] —gap: N resolutions must fall here— [known resolution j] … [session end]",
        "```",
        "",
        "Because `K_e` (the enriched resolution count per day) is normative and hand-checked, every",
        "interval between two consecutive known points carries a count that **must** be satisfied.",
        f"A gap holding 0 unplaced resolutions is already determined; one holding 1–{nearly_max} is nearly",
        "determined by its endpoints plus counting; larger gaps are where the real work is.",
        "",
        "Known points are kept **typed** rather than merged, so the ledger shows which kind of",
        "knowledge does the pinning: session start/end sentinels, tier-1 entity anchors, and",
        "hand-annotated gold boundaries.",
        "",
        "## Headline",
        "",
        f"- **{overall['days']}** days carry an HTR paragraph axis; **{overall['days_without_axis']}** have enriched",
        "  resolutions but no axis at all — the accepted `missing_htr` ceiling.",
        f"- **{overall['resolutions']}** resolutions, of which **{overall['interior_known_points']}** are pinned by a known point",
        f"  (**{pct(overall['pinned_share_of_resolutions'])}**): "
        + ", ".join(f"{count} {kind}" for kind, count in sorted(overall["pinned_by_kind"].items()))
        + ".",
        f"- **{overall['unplaced_resolutions']}** resolutions remain unplaced across **{overall['gaps']}** gaps.",
        "",
        "| bucket | gaps | unplaced resolutions | share of unplaced | characters |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| determined (0) | {buckets['determined']['gaps']} | {buckets['determined']['resolutions']} | 0.0% | {buckets['determined']['chars']:,} |",
        f"| nearly determined (1–{nearly_max}) | {buckets['nearly_determined']['gaps']} | {buckets['nearly_determined']['resolutions']} | "
        f"{pct(buckets['nearly_determined']['resolutions'] / overall['unplaced_resolutions']) if overall['unplaced_resolutions'] else '—'} | {buckets['nearly_determined']['chars']:,} |",
        f"| **open (>{nearly_max})** | **{buckets['open']['gaps']}** | **{buckets['open']['resolutions']}** | "
        f"**{pct(overall['open_share_by_resolution'])}** | {buckets['open']['chars']:,} |",
        "",
        "### Read both shares, never one",
        "",
        f"Counting **gaps**, {pct(overall['settled_share_by_gap'])} are determined or nearly so — which sounds excellent.",
        f"Counting **resolutions**, {pct(overall['open_share_by_resolution'])} of the unplaced work sits in the "
        f"{buckets['open']['gaps']} open gaps.",
        "Both are true. A gap of size 0 contributes a row to the distribution but zero work, so",
        "gap-count shares are dominated by already-solved intervals.",
        "[`SEGMENTATION_TRANSFER.md` §7](SEGMENTATION_TRANSFER.md) argues from roughly the gap-count view that",
        "\"the residual problem is small and locally constrained\"; that holds by gap count and fails by",
        f"resolution count (see [DECISIONS.md](DECISIONS.md), 2026-09-20). The longest gap runs **{largest}** resolutions.",
        "",
        "## By month",
        "",
        "Monthly **counts** are solid and show exactly where the corpus goes dark. Monthly **ratios**",
        "rest on thin cells, so check the year and inventory rollups below before reading a trend into",
        "month-to-month movement.",
        "",
    ]
    lines += rollup_table(report["by_month"], "month")
    lines += [
        "",
        "## By year",
        "",
    ]
    lines += rollup_table(report["by_year"], "year")
    lines += [
        "",
        "## By inventory",
        "",
        "Inventory is read from the flat id (`session-3185-num-7-resolution-1`), not from",
        "`session_date_status.inventory_id`, which enumerates several *candidate* inventories per date.",
        "`no_axis` collects the days with no HTR text at all.",
        "",
    ]
    lines += rollup_table(report["by_inventory"], "inventory")

    # Detected rather than written down, so the note cannot go stale on a re-render.
    outliers = [
        (name, entry)
        for name, entry in report["by_inventory"].items()
        if entry["resolutions"] and entry["pinned_share_of_resolutions"] < overall["pinned_share_of_resolutions"] / 2
    ]
    if outliers:
        lines += ["", "### Anchor-starved inventories", ""]
        lines += [
            f"Flagged automatically: pinned share below half the corpus average "
            f"({pct(overall['pinned_share_of_resolutions'] / 2)}).",
            "",
        ]
        for name, entry in outliers:
            lines.append(
                f"- **{name}** — {entry['resolutions']} resolutions over {entry['days']} days, but only "
                f"{entry['interior_known_points']} pinned (**{pct(entry['pinned_share_of_resolutions'])}**), leaving "
                f"**{pct(entry['open_share_by_resolution'])}** of its unplaced work in open gaps. Tier-1 anchoring "
                "essentially does not reach this material, so it is a different problem from the rest of the corpus "
                "and should not be pooled with it when fitting anything."
            )

    lines += [
        "",
        "## Gap-size distribution",
        "",
        "| resolutions in gap | gaps |",
        "| ---: | ---: |",
    ]
    lines += [f"| {size} | {count} |" for size, count in sorted(sizes.items(), key=lambda item: int(item[0]))]
    lines += [
        "",
        "## What this implies",
        "",
        f"The work is **concentrated, not diffuse**: {buckets['open']['gaps']} open gaps spanning",
        f"{buckets['open']['chars']:,} characters hold {pct(overall['open_share_by_resolution'])} of the unplaced resolutions,",
        "while the remaining intervals are already determined or pinned to within a resolution or two by",
        "counting alone. A placement model only has to be good inside those stretches — a far better",
        "specified target than \"improve boundary F1\" over the whole corpus.",
        "",
    ]

    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print(f"Wrote {REPORT_PATH}")
    print(f"  {overall['days']} days, {overall['resolutions']} resolutions, {overall['gaps']} gaps")
    print(f"  settled by gap {pct(overall['settled_share_by_gap'])} vs open by resolution {pct(overall['open_share_by_resolution'])}")
    print(f"  months {len(report['by_month'])}, years {len(report['by_year'])}, inventories {len(report['by_inventory'])}")


if __name__ == "__main__":
    main()

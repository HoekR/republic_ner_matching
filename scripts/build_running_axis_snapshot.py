#!/usr/bin/env python3
"""Write a `running_axis` snapshot, so a run's figures are answerable from the artifact.

The problem this closes: three different gap counts were in circulation for
`s6b_known_point_ledger` -- 120 from a one-month run that is what sits on disk, 947 cited in
`PLAN.md` from an earlier full-window run, and a third set that was fabricated -- because
nothing in the output said which window it described. Every record here carries the model's
coverage, and every reported figure is a `running_axis.tally.Tally` naming its population and
window, so the same confusion cannot recur.

Diagnostic only: no placement change, no tolerance-family metric.

Usage:
    uv run python scripts/build_running_axis_snapshot.py
    uv run python scripts/build_running_axis_snapshot.py --start 1628-10-01 --end 1628-10-31
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import save_semi_structured
from running_axis.axis import ADDRESSABILITY, RunningAxis

OUTPUT_DATASET = "running_axis_snapshot"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None, help="window start; defaults to full coverage")
    parser.add_argument("--end", default=None, help="window end; defaults to full coverage")
    args = parser.parse_args()

    axis = RunningAxis.load()
    coverage = axis.coverage
    start = args.start or coverage.start
    end = args.end or coverage.end
    view = axis.view(start, end)
    report = view.report()

    records = axis.snapshot()
    records[0]["reported_window"] = {"start": start, "end": end}
    records[0]["report"] = {
        name: {
            "value": tally.value,
            "population": tally.population.name,
            "unit": tally.population.unit,
            "attribution": tally.population.attribution,
            "window": {"start": tally.window.start, "end": tally.window.end},
        }
        for name, tally in report.items()
    }

    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote running-axis snapshot to {path}")
    print(f"  model coverage {coverage}:")
    print(
        f"    {len(axis.sessions):,} sessions | {len(axis.dates):,} enriched dates "
        f"| {sum(len(s) for s in axis.streams.values()):,} paragraphs  (coverage-wide)"
    )
    print(f"  reported window {start}..{end}:")
    for name in (
        "axis_sessions",
        "enriched_dates",
        *(f"dates_{k}" for k in ADDRESSABILITY),
        "enriched_resolutions",
        *(f"resolutions_{k}" for k in ADDRESSABILITY),
    ):
        print(f"    {report[name]}")


if __name__ == "__main__":
    main()

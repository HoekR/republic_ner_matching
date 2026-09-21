#!/usr/bin/env python3
"""S6b -- the constraint baseline: known points and the counted gaps between them.

This is a baseline of the *problem*, not of a model. Nothing here predicts anything.

The structure it records, along one continuous stream:

    [session start] ... [known resolution i] --gap: N resolutions must fall here-- [known resolution j] ... [session end]

Every interval between two consecutive known points carries a count that must be
satisfied, because `K_e` (the enriched resolution count per day) is normative. A gap
holding 0 unknown resolutions is already determined; a gap holding 1 is nearly
determined by its two fixed endpoints; large gaps are where the real work is. So the
baseline number is not an F1 -- it is how much of the stream is already pinned by known
points plus counting, and the shape of the gap-size distribution.

Two deliberate choices, both requested:

* **Known points stay typed.** A session start, a tier-1 entity anchor and a gold
  boundary are all "known", but they are kept as distinct kinds rather than collapsed,
  so the ledger shows which kind of knowledge does the pinning and what each contributes
  on its own.
* **A contiguous window, not the gold sample.** The 50 gold days are a stratified
  scatter, so intervals between them would measure the sampling rather than the corpus.
  The chain only means something over consecutive sessions, so the window runs
  continuously -- by default the whole 1626-1630 period.

Rolled up three ways. Month is the easiest to scan and is the primary table, but monthly
*ratios* rest on thin cells (roughly 20 days and 18 open gaps per month), so read the
year and inventory rollups before calling any month-to-month movement a trend. Monthly
*counts* -- days with an axis, resolutions, anchors -- are solid and show exactly where
the corpus goes dark.

Positions are character coordinates on the same per-day axis S6a established, so this
ledger and the S6a/S6 evaluation numbers are expressed in one unit.

Usage:
    uv run python -m scripts.s6b_known_point_ledger
    uv run python -m scripts.s6b_known_point_ledger --start 1626-01-01 --end 1626-12-31
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from data_io import load, save_semi_structured
from scripts.s6a_char_axis_evaluation import char_starts, opening_paragraph


ALIGNMENT_DATASET = "alignment_1626_1630"
AXIS_DATASET = "paragraph_axis_1626_1630"
LEDGER_DATASET = "session_date_status_1626_1630"
GOLD_DATASET = "boundary_gold_sample"
OUTPUT_DATASET = "s6b_known_point_ledger"

DEFAULT_START = "1626-01-01"
DEFAULT_END = "1630-12-31"
TIER1 = "tier1_anchor"

# Gap sizes at or below this are treated as effectively settled by their endpoints plus
# the count constraint, per SEGMENTATION_TRANSFER.md section 7.
NEARLY_DETERMINED = 2


def enriched_index(enriched_id: str) -> int | None:
    """`1626-06-06_12` -> 12. Enriched ids sort as strings, so never rely on sort order."""
    match = re.search(r"_(\d+)$", str(enriched_id))
    return int(match.group(1)) if match else None


def inventory_of(records: Sequence[dict[str, Any]]) -> str:
    """Inventory the day's HTR text actually comes from, read off the flat ids.

    Not taken from `session_date_status.inventory_id`: that column enumerates 3-4
    *candidate* inventories per date, so picking one of those rows is arbitrary. The
    flat id (`session-3185-num-7-resolution-1`) names the inventory the text is in.
    """
    found = Counter()
    for record in records:
        match = re.match(r"session-(\d+)-", str(record.get("flat_id", "")))
        if match:
            found[match.group(1)] += 1
    return found.most_common(1)[0][0] if found else "unknown"


def flat_id_char_starts(records: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Character offset at which each flat resolution's first paragraph opens."""
    starts = char_starts(records)
    first: dict[str, int] = {}
    for position, record in zip(starts, records):
        first.setdefault(str(record["flat_id"]), position)
    return first


def tier1_points(rows: Sequence[Any], by_flat_id: dict[str, int]) -> list[dict[str, Any]]:
    """One known point per tier-1 anchor whose flat resolution is on this day's axis."""
    points = []
    for row in rows:
        index = enriched_index(row.enriched_id)
        position = by_flat_id.get(str(row.flat_id))
        if index is not None and position is not None:
            points.append({"kind": TIER1, "enriched_index": index, "char_position": position})
    return points


def gold_points(day: dict[str, Any], starts: Sequence[int]) -> list[dict[str, Any]]:
    """Known points from hand-annotated boundaries, pinning resolution i at cut i-1."""
    cuts = [boundary for boundary in day.get("boundaries") or [] if boundary.get("kind") == "cut"]
    points = []
    for enriched_offset, cut in enumerate(cuts, start=1):
        index = opening_paragraph(cut)
        if index is None or not 0 <= index < len(starts):
            continue
        offset = cut.get("char_offset")
        position = starts[index] if cut.get("unit") == "paragraph_boundary" or offset is None else starts[index] + int(offset)
        points.append({"kind": "gold_boundary", "enriched_index": enriched_offset, "char_position": position})
    return points


def collapse(points: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One point per enriched index, keeping every kind that pins it.

    Several sources can pin the same resolution -- that is agreement, not a conflict, and
    the ledger records which kinds agreed rather than silently preferring one.
    """
    by_index: dict[int, dict[str, Any]] = {}
    for point in sorted(points, key=lambda item: (item["enriched_index"], item["char_position"])):
        index = point["enriched_index"]
        if index in by_index:
            entry = by_index[index]
            if point["kind"] not in entry["kinds"]:
                entry["kinds"].append(point["kind"])
            continue
        by_index[index] = {
            "enriched_index": index,
            "char_position": point["char_position"],
            "kinds": [point["kind"]],
        }
    return [by_index[index] for index in sorted(by_index)]


def build_chain(k_e: int, total_chars: int, interior: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the known points and bound them with the session start and end sentinels.

    The session start pins resolution 0 at character 0; the session end pins `k_e` (one
    past the last resolution) at the end of the stream. A day with no interior anchors
    therefore yields one gap of `k_e - 1` -- exactly the cut points that need placing.
    """
    points = [{"enriched_index": 0, "char_position": 0, "kinds": ["session_start"]}]
    points.extend(
        point for point in interior if 0 < point["enriched_index"] < k_e
    )
    points.append({"enriched_index": k_e, "char_position": total_chars, "kinds": ["session_end"]})
    return points


def bucket_of(resolutions_in_gap: int) -> str:
    """Name the gap's difficulty class: already settled, nearly settled, or genuinely open."""
    if resolutions_in_gap == 0:
        return "determined"
    return "nearly_determined" if resolutions_in_gap <= NEARLY_DETERMINED else "open"


def aggregate(day_stats: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Summarise any set of days -- the whole window, or one month of it.

    Reports gap counts *and* resolution-weighted counts side by side on purpose: a gap of
    size 0 contributes a row but no work, so gap-count shares are dominated by
    already-solved intervals and read far more favourably than the real picture
    (docs/DECISIONS.md 2026-09-20).
    """
    buckets = {name: {"gaps": 0, "resolutions": 0, "chars": 0} for name in ("determined", "nearly_determined", "open")}
    pinned_by_kind: Counter[str] = Counter()
    resolutions = 0
    unplaced = 0
    days_without_axis = 0
    gap_sizes: Counter[int] = Counter()

    for stat in day_stats:
        if stat.get("no_axis"):
            days_without_axis += 1
            continue
        resolutions += stat["k_e"]
        unplaced += stat["unplaced"]
        for kind, count in stat["pinned_by_kind"].items():
            pinned_by_kind[kind] += count
        for size, count in stat["gap_sizes"].items():
            gap_sizes[size] += count
        for name, entry in stat["buckets"].items():
            buckets[name]["gaps"] += entry["gaps"]
            buckets[name]["resolutions"] += entry["resolutions"]
            buckets[name]["chars"] += entry["chars"]

    total_gaps = sum(entry["gaps"] for entry in buckets.values())
    pinned = sum(pinned_by_kind.values())
    settled_gaps = buckets["determined"]["gaps"] + buckets["nearly_determined"]["gaps"]

    return {
        "days": sum(1 for stat in day_stats if not stat.get("no_axis")),
        "days_without_axis": days_without_axis,
        "resolutions": resolutions,
        "interior_known_points": pinned,
        "pinned_by_kind": dict(pinned_by_kind),
        "pinned_share_of_resolutions": pinned / resolutions if resolutions else 0.0,
        "unplaced_resolutions": unplaced,
        "gaps": total_gaps,
        "buckets": buckets,
        "gap_size_distribution": {str(size): gap_sizes[size] for size in sorted(gap_sizes)},
        # The two shares that disagree, both reported so neither can be quoted alone.
        "settled_share_by_gap": settled_gaps / total_gaps if total_gaps else 0.0,
        "open_share_by_resolution": buckets["open"]["resolutions"] / unplaced if unplaced else 0.0,
    }


def gaps_of(chain: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per interval: how many resolutions must fall inside, and over what span."""
    rows = []
    for left, right in zip(chain, chain[1:]):
        rows.append(
            {
                "left_kinds": left["kinds"],
                "right_kinds": right["kinds"],
                "left_enriched_index": left["enriched_index"],
                "right_enriched_index": right["enriched_index"],
                "resolutions_in_gap": right["enriched_index"] - left["enriched_index"] - 1,
                "char_span": right["char_position"] - left["char_position"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Known-point / counted-gap constraint baseline.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    args = parser.parse_args()

    alignment = load(ALIGNMENT_DATASET)
    alignment = alignment[
        (alignment["date"] >= args.start)
        & (alignment["date"] <= args.end)
        & (alignment["confidence_tier"] == TIER1)
    ]
    tier1_by_date: dict[str, list[Any]] = defaultdict(list)
    for row in alignment[["enriched_id", "flat_id", "date"]].itertuples(index=False):
        tier1_by_date[str(row.date)].append(row)

    axis_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(AXIS_DATASET):
        date = str(record["date"])
        if args.start <= date <= args.end:
            axis_by_date[date].append(record)

    ledger = load(LEDGER_DATASET)
    ledger = ledger[(ledger["enriched_date"] >= args.start) & (ledger["enriched_date"] <= args.end)]
    k_e_by_date = {
        str(row.enriched_date): int(row.enriched_count)
        for row in ledger[["enriched_date", "enriched_count"]].itertuples(index=False)
    }

    gold_by_date = {str(day["date"]): day for day in load(GOLD_DATASET)["days"]}

    day_stats: list[dict[str, Any]] = []
    per_day: list[dict[str, Any]] = []

    for date in sorted(k_e_by_date):
        k_e = k_e_by_date[date]
        axis = axis_by_date.get(date)
        if not axis:
            day_stats.append({"date": date, "month": date[:7], "year": date[:4], "inventory": "no_axis", "no_axis": True})
            continue
        inventory = inventory_of(axis)

        starts = char_starts(axis)
        total_chars = starts[-1] + len(axis[-1]["text"])
        by_flat_id = flat_id_char_starts(axis)

        interior = tier1_points(tier1_by_date.get(date, []), by_flat_id)
        gold_day = gold_by_date.get(date)
        if gold_day is not None:
            interior.extend(gold_points(gold_day, starts))
        chain = build_chain(k_e, total_chars, collapse(interior))
        rows = gaps_of(chain)

        pinned_by_kind: Counter[str] = Counter()
        for point in chain[1:-1]:
            for kind in point["kinds"]:
                pinned_by_kind[kind] += 1

        buckets = {name: {"gaps": 0, "resolutions": 0, "chars": 0} for name in ("determined", "nearly_determined", "open")}
        gap_sizes: Counter[int] = Counter()
        for row in rows:
            name = bucket_of(row["resolutions_in_gap"])
            buckets[name]["gaps"] += 1
            buckets[name]["resolutions"] += row["resolutions_in_gap"]
            buckets[name]["chars"] += row["char_span"]
            gap_sizes[row["resolutions_in_gap"]] += 1

        day_stats.append(
            {
                "date": date,
                "month": date[:7],
                "year": date[:4],
                "inventory": inventory,
                "no_axis": False,
                "k_e": k_e,
                "unplaced": sum(row["resolutions_in_gap"] for row in rows),
                "pinned_by_kind": dict(pinned_by_kind),
                "buckets": buckets,
                "gap_sizes": dict(gap_sizes),
            }
        )
        per_day.append(
            {
                "date": date,
                "month": date[:7],
                "inventory": inventory,
                "k_e": k_e,
                "axis_paragraph_count": len(axis),
                "axis_char_length": total_chars,
                "interior_known_points": len(chain) - 2,
                "chain": chain,
                "gaps": rows,
            }
        )

    def rollup(key: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for stat in day_stats:
            groups[stat[key]].append(stat)
        return {name: aggregate(groups[name]) for name in sorted(groups)}

    report = {
        "window": {"start": args.start, "end": args.end},
        "nearly_determined_max": NEARLY_DETERMINED,
        "overall": aggregate(day_stats),
        "by_month": rollup("month"),
        "by_year": rollup("year"),
        "by_inventory": rollup("inventory"),
    }

    output = save_semi_structured([report, *per_day], logical_name=OUTPUT_DATASET, script=__file__)
    overall = report["overall"]
    print(f"Wrote known-point ledger to {output}")
    print(f"  window {args.start}..{args.end}: {overall['days']} days with an axis, {overall['days_without_axis']} without")
    print(f"  resolutions {overall['resolutions']} | pinned {overall['interior_known_points']} ({overall['pinned_share_of_resolutions']:.3f}) by kind {overall['pinned_by_kind']}")
    for name, entry in overall["buckets"].items():
        print(f"    {name:18} gaps {entry['gaps']:>5}  resolutions {entry['resolutions']:>5}  chars {entry['chars']:>9}")
    print(f"  settled share BY GAP {overall['settled_share_by_gap']:.3f} vs open share BY RESOLUTION {overall['open_share_by_resolution']:.3f}")
    print(f"  months {len(report['by_month'])} | years {len(report['by_year'])} | inventories {sorted(report['by_inventory'])}")


if __name__ == "__main__":
    main()

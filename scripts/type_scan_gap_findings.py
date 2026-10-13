#!/usr/bin/env python3
"""Step 3 of `plans/archive/SCAN_SEQUENCE_TRACK.md`: type every bracket on the scan axis.

**What this is.** One row per bracket between consecutive scan->date anchors, each carrying a
type, a quantity and the images to check it on — ordered along the axis, so the dataset reads as
a **status of the timeline** rather than a bag of findings. Same review-worklist form as
`unplaced_date_review` (whose `iiif_url` is imported, not reimplemented); the populations are
disjoint — that one lists enriched dates with no HTR session, this one lists stretches of paper.

**What it deliberately is not.** Step 3 used to end "and it is the pigeonhole argument from the
counting question". That was struck on 2026-10-08 after the provenance check: the forcing frame
was mine and nobody asked for it. So this produces *no* count of determined placements, and
changes no placement.

**The null comes first, and it is measured, not assumed.** `room < charge` under the measured
requirement fires on 155 of ~594 brackets, but that charge is a sum of per-bucket **medians**, so
a bracket a scan or two short is exactly what a median predicts. Here each charged day instead
draws from the **empirical distribution** of exclusive extents for its own `k_e` bucket
(`scans_per_day_by_ke`'s day rows), 4,000 draws per bracket, giving

    p_low  = P(sum of day extents <= room)   -- room improbably SMALL  -> `shortfall`
    p_high = P(sum of day extents >= room)   -- room improbably LARGE  -> `surplus_room`

Nothing is fitted and there is no tolerance to tune: the null is the measurement itself.

**The cheapest explanation was checked first and is a no-op — measured, not assumed.** A nihil day
is charged 0 scans, so a nihil undercount would make brackets look short for free. The production
status column *does* undercount: `h_xml_nihil_vs_feast_calendar` (2026-10-07) found 34 XML-literal
nihil dates missing from it, because `s4_day_status_resolution.py`'s `T`/`E` ledger rows bypass the
nihil check. **But this track never read that column.** `calendar()` runs `is_nihil_actum` over each
date's own concatenated text and recovers all **161**, the identical set — so the charge here was
never affected, and **0** of the 155 shortfalls are absorbed. Both charges are still computed and
carried per row (`charge_production_nihil`, `charge_xml_nihil`) as a standing guard: if the two ever
diverge, a nihil regression has reached this track.

**Three things are carried as evidence and NOT used to assign a type**, so that whether they
explain findings stays a measurement instead of becoming the definition of one:

* `loose_anchor_*` — the end was recovered by the bracket bootstrap (1.3% measured parse error).
* `long_span` — the bracket's day span is above the 99th percentile of all bracket spans.
* `unrecorded_interior_days` — interior dates the edition records nothing for at all.

The script prints the cross-tab of findings against each. Inventory 4562 is the one exception: it
is typed `anchor_suspect` up front, by the same rule the rest of the track uses and not by name —
its 8 anchors sit 700 days apart on adjacent scans, so its arithmetic means nothing.

**What cannot be typed from this data, stated rather than guessed.** The track's step list names
"missing pages" as a candidate type. Scan numbering inside an inventory is contiguous and
complete (`inventory_metadata.num_scans`), so a *digitisation* gap is not observable here and no
row claims one; a `shortfall` says the paper between two dated headings cannot hold the days the
calendar puts there, and leaves the cause to the image.

Diagnostic only: writes one dataset, changes no placement.

Usage:
    uv run python scripts/type_scan_gap_findings.py
    uv run python scripts/type_scan_gap_findings.py --strict-only
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.build_unplaced_date_review import iiif_url
from scripts.corpus_scope import assert_no_sidelined, in_scope, scope_meta, series_meta
from scripts.h_session_date_vs_heading import read_heading
from scripts.measure_scans_per_day import (
    REGION_DATASET,
    KE_BUCKETS,
    MIN_BUCKET_DAYS,
    bucket_label,
    calendar,
    day_rows,
    observations,
    requirement_curve,
)

OUTPUT_DATASET = "scan_gap_findings"
DRAWS = 4000
ALPHA = 0.05  # two-sided tails of the empirical null; not a tuned tolerance
RNG_SEED = 20261008
LONG_SPAN_PCT = 99
# Step 1's hold-out: of the bootstrap's loose parses, 96.6% right, 1.3% wrong, 2.1% declined.
# A wrong anchor corrupts the bracket on each side of it, so this rate bounds how much of the
# finding count can be parse error rather than paper.
LOOSE_PARSE_ERROR_RATE = 0.013


def xml_nihil_dates() -> set[str]:
    """The 161 dates the XML itself marks nihil actum, not the 127 the status column carries."""
    return {
        str(row["date"])[:10]
        for row in load("h_xml_nihil_vs_feast_calendar")
        if row.get("record_type") == "xml_day" and row.get("xml_nihil")
    }


def date_regions_by_scan() -> dict[str, dict[int, bool]]:
    """`(inventory, scan) -> did its date region parse strictly?`

    A scan inside a bracket that carries a date region the parser could not read is the concrete
    place to look for a heading that was never read -- and after the Step 1 bootstrap it is also a
    *decline*, since the bootstrap already tried every one of these and kept only the parses that
    disambiguated to exactly one date inside their bracket. So an unparsed region inside a bracket
    is observable evidence, not a guess, and it separates "a heading is there and we failed to
    read it" from "there is no heading on this paper at all".
    """
    out: dict[str, dict[int, bool]] = defaultdict(dict)
    for row in load(REGION_DATASET):
        if row.get("record_type") != "region" or row.get("region_class") != "date":
            continue
        reading = read_heading(row["text"], row["inventory"])
        parsed = None not in (reading["day"], reading["month"], reading["year"])
        scan = int(str(row["scan_id"]).split("_")[-1])
        out[row["inventory"]][scan] = out[row["inventory"]].get(scan, False) or parsed
    return out


def extent_samples(busy: pd.DataFrame) -> dict[str, np.ndarray]:
    """Empirical exclusive-extent distribution per `k_e` bucket, with the same thinness guard.

    A bucket holding fewer than `MIN_BUCKET_DAYS` days inherits the nearest bucket below that has
    enough — the identical rule `requirement_curve` uses for its medians, so the null and the
    charge describe the same population.
    """
    samples: dict[str, np.ndarray] = {}
    carried = np.array([0.0])
    for lo, _hi in KE_BUCKETS:
        label = bucket_label(lo)
        sub = busy.loc[busy["ke_bucket"] == label, "exclusive_scans"].to_numpy(dtype=float)
        if len(sub) >= MIN_BUCKET_DAYS:
            carried = sub
        samples[label] = carried
    return samples


def analyse(
    with_bootstrap: bool,
    k_e: dict[str, int],
    nihil_prod: set[str],
    nihil_xml: set[str],
    edition_end: pd.Period,
    regions: dict[str, dict[int, bool]],
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Type every bracket under one anchor set. Both sets are run and both are written.

    They are not interchangeable and the choice is not a detail: the strict set is small and
    clean (no loose parse anywhere in it), the bootstrapped set is 73% denser but its findings
    carry the loose parser's 1.3% error on two brackets per bad anchor. The two disagree by 3x on
    shortfalls, so collapsing to one view would hide the disagreement rather than resolve it.
    """
    anchor_set = "strict+bootstrap" if with_bootstrap else "strict"
    print(f"\n{'=' * 78}\nANCHOR SET: {anchor_set}\n{'=' * 78}")
    obs = observations(with_bootstrap)

    # The null: measured per-day extents, from the same population `requirement_curve` reads.
    frame, _dropped = day_rows(obs, k_e, nihil_prod)
    order = [bucket_label(lo) for lo, _ in KE_BUCKETS]
    frame["ke_bucket"] = pd.Categorical(
        frame["k_e"].map(bucket_label), categories=order, ordered=True
    )
    clean = frame[frame["adjacent"]]
    busy = clean[clean["in_edition"] & ~clean["is_nihil"]]
    curve = requirement_curve(busy)
    samples = extent_samples(busy)

    print(f"null from {len(busy):,} measured sitting days; "
          f"per-bucket n = "
          + ", ".join(f"{k}:{len(v)}" for k, v in samples.items() if len(v) > 1))

    # Brackets, built the way `bootstrap_scan_anchors.metrics` builds them (one date per scan),
    # so counts stay comparable with the figures already published for this track.
    collapsed: dict[str, dict[int, pd.Period]] = defaultdict(dict)
    for inventory, scan, date, src in obs:
        if inventory not in collapsed or scan not in collapsed[inventory]:
            collapsed[inventory][scan] = date
    source_of: dict[tuple[str, int], str] = {}
    for inventory, scan, date, src in obs:
        source_of.setdefault((inventory, scan), src)

    # A date read off two widely separated scans cannot be right at both. Carried as evidence,
    # never as a type: the top shortfalls are dominated by this shape (3187 scan 320 and scan 434
    # both claim early August 1628) and calling it a wrong anchor here would be the fiat this
    # script exists to avoid. The quantity is the scan spread of every observation of that date.
    date_scan_spread: dict[tuple[str, str], int] = {}
    seen: dict[tuple[str, str], list[int]] = defaultdict(list)
    for inventory, scan, date, _src in obs:
        seen[(inventory, str(date))].append(scan)
    for key, scans in seen.items():
        date_scan_spread[key] = max(scans) - min(scans)

    def charge(days: list[pd.Period], nihil: set[str]) -> float:
        total = 0.0
        for day in days:
            key = str(day)
            if key in nihil or key not in k_e:
                continue
            total += curve.get(bucket_label(k_e[key]), 1.0)
        return total

    rng = np.random.default_rng(RNG_SEED)
    rows: list[dict[str, Any]] = []
    for inventory, by_scan in sorted(collapsed.items()):
        points = sorted(by_scan.items())
        for (scan_a, date_a), (scan_b, date_b) in zip(points, points[1:]):
            room = scan_b - scan_a
            if room <= 0 or (date_b - date_a).n <= 0:
                continue
            assert in_scope(date_a), f"scope bar bypassed: {inventory} {date_a}"
            days = list(pd.period_range(date_a, date_b - 1, freq="D"))
            charge_prod = charge(days, nihil_prod)
            charge_xml = charge(days, nihil_xml)

            # Empirical null under the better (XML) nihil set.
            drawn = np.zeros(DRAWS)
            charged_days = 0
            for day in days:
                key = str(day)
                if key in nihil_xml or key not in k_e:
                    continue
                charged_days += 1
                pool = samples.get(bucket_label(k_e[key]), np.array([1.0]))
                drawn += rng.choice(pool, size=DRAWS)
            if charged_days:
                p_low = float((drawn <= room).mean())
                p_high = float((drawn >= room).mean())
            else:
                p_low = p_high = None

            if not charged_days:
                finding = "no_business_charged"
            elif p_low < ALPHA:
                finding = "shortfall"
            elif p_high < ALPHA:
                finding = "surplus_room"
            else:
                finding = "fits"

            interior = [
                {"date": str(d), "k_e": k_e.get(str(d), 0),
                 "nihil_xml": str(d) in nihil_xml, "nihil_production": str(d) in nihil_prod}
                for d in days
            ]
            rows.append({
                "record_type": "bracket",
                "anchor_set": anchor_set,
                "inventory": inventory,
                "from_scan": scan_a,
                "to_scan": scan_b,
                "from_date": str(date_a),
                "to_date": str(date_b),
                "quarter": f"{date_a.year}Q{(date_a.month - 1) // 3 + 1}",
                "room_scans": room,
                "calendar_days": len(days),
                "charged_days": charged_days,
                "k_e": sum(k_e.get(str(d), 0) for d in days),
                "nihil_days_production": sum(1 for d in days if str(d) in nihil_prod),
                "nihil_days_xml": sum(1 for d in days if str(d) in nihil_xml),
                "unrecorded_interior_days": sum(1 for d in days if str(d) not in k_e),
                "charge_production_nihil": round(charge_prod, 2),
                "charge_xml_nihil": round(charge_xml, 2),
                "shortfall_scans": round(max(0.0, charge_xml - room), 2),
                "surplus_scans": round(max(0.0, room - charge_xml), 2),
                "p_room_improbably_small": None if p_low is None else round(p_low, 4),
                "p_room_improbably_large": None if p_high is None else round(p_high, 4),
                "finding_type": finding,
                "loose_anchor_from": source_of.get((inventory, scan_a)) == "bootstrap",
                "loose_anchor_to": source_of.get((inventory, scan_b)) == "bootstrap",
                "from_date_scan_spread": date_scan_spread.get((inventory, str(date_a)), 0),
                "to_date_scan_spread": date_scan_spread.get((inventory, str(date_b)), 0),
                "interior_scans_with_unread_date_region": sum(
                    1 for s in range(scan_a + 1, scan_b)
                    if regions.get(inventory, {}).get(s) is False
                ),
                "interior_scans_with_no_date_region": sum(
                    1 for s in range(scan_a + 1, scan_b)
                    if s not in regions.get(inventory, {})
                ),
                "interior_days": interior,
                "images": [u for u in (iiif_url(f"NL-HaNA_1.01.02_{inventory}_{s:04d}")
                                       for s in (scan_a, scan_b)) if u],
            })

    table = pd.DataFrame(rows)
    assert_no_sidelined(table, "inventory")
    span_p99 = float(table["calendar_days"].quantile(LONG_SPAN_PCT / 100))
    table["long_span"] = table["calendar_days"] > span_p99
    table["loose_anchor"] = table["loose_anchor_from"] | table["loose_anchor_to"]
    # A date's own observations should sit within a day's worth of paper. The threshold is the
    # 99th percentile of observed spreads, in SCANS -- not `span_p99`, which counts days.
    spread_p99 = float(pd.Series(list(date_scan_spread.values())).quantile(LONG_SPAN_PCT / 100))
    table["repeated_anchor_date"] = (
        table[["from_date_scan_spread", "to_date_scan_spread"]].max(axis=1) > spread_p99
    )

    # What the fuller nihil set absorbs: brackets the production charge calls short and the XML
    # charge does not. Measured, so the cheapest explanation is off the table before any claim.
    short_prod = table["charge_production_nihil"] > table["room_scans"]
    short_xml = table["charge_xml_nihil"] > table["room_scans"]
    absorbed = int((short_prod & ~short_xml).sum())

    counts = table["finding_type"].value_counts().to_dict()
    findings = table[table["finding_type"].isin(["shortfall", "surplus_room"])]

    print(f"\nbrackets {len(table):,}  (anchors {sum(len(v) for v in collapsed.values()):,}, "
          f"{'with' if with_bootstrap else 'without'} bootstrap)")
    print(f"  median-charge `room < charge`: {int(short_prod.sum())} production nihil -> "
          f"{int(short_xml.sum())} XML nihil ({absorbed} absorbed -- the two nihil sets are "
          f"identical here, so this is a guard, not an explanation)")
    print(f"  under the empirical null (alpha {ALPHA}), long-span p{LONG_SPAN_PCT} "
          f"= {span_p99:.0f} days:")
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {name:<22}{n:>5}")

    print("\nFINDINGS against the evidence NOT used to type them "
          "(so whether they explain anything stays measured):")
    cross = ["loose_anchor", "long_span", "repeated_anchor_date"]
    print(f"{'type':<16}{'n':>5}{'loose anchor':>14}{'long span':>11}"
          f"{'date 2 places':>15}{'unread region':>15}{'no region':>11}")

    def line(name: str, sub: pd.DataFrame, tail: str = "") -> None:
        print(f"{name:<16}{len(sub):>5}"
              + "".join(f"{sub[c].mean():>13.0%}  " for c in cross)
              + f"{(sub['interior_scans_with_unread_date_region'] > 0).mean():>13.0%}"
              + f"{(sub['interior_scans_with_no_date_region'] > 0).mean():>11.0%}{tail}")

    for name, sub in findings.groupby("finding_type"):
        line(name, sub)
    rest = table[table["finding_type"] == "fits"]
    if len(rest):
        line("fits", rest, "   <- base rate")

    # How much of the finding count can be parse error rather than paper. Not a correction and not
    # a filter -- a bound, printed beside the count so the count is never read without it.
    n_loose = sum(1 for src in source_of.values() if src == "bootstrap")
    error_brackets = 2 * LOOSE_PARSE_ERROR_RATE * n_loose
    print(f"\nPARSE-ERROR BOUND: {n_loose} loose anchors at the hold-out's "
          f"{LOOSE_PARSE_ERROR_RATE:.1%} error rate corrupt ~{error_brackets:.0f} brackets "
          f"(2 each), against {len(findings)} findings -- so up to "
          f"{min(1.0, error_brackets / max(1, len(findings))):.0%} of them could be a bad anchor "
          f"rather than bad paper. The strict-only run has no loose anchors at all and is the "
          f"clean comparison.")

    # Reproduction check against the figures already published for this track, so the bracket
    # construction here is verifiably the same one. Published: 600 strict brackets
    # (`scan_anchor_brackets`) and `room < charge` on 155 of 593 excluding inventory 4562.
    healthy = table
    short_healthy = int((healthy["charge_production_nihil"] > healthy["room_scans"]).sum())
    print(f"  reproduction check, 4562 excluded: {short_healthy} of {len(healthy)} brackets "
          f"`room < charge` (published strict figure: 155 of 593)")

    print("\nSTATUS OF THE TIMELINE, by quarter "
          "(brackets / scans bracketed / shortfall / surplus / unanchored scans between):")
    timeline: list[dict[str, Any]] = []
    for (inventory, quarter), sub in table.groupby(["inventory", "quarter"]):
        row = {
            "record_type": "timeline",
            "anchor_set": anchor_set,
            "inventory": inventory,
            "quarter": quarter,
            "brackets": len(sub),
            "scans_bracketed": int(sub["room_scans"].sum()),
            "from_scan": int(sub["from_scan"].min()),
            "to_scan": int(sub["to_scan"].max()),
            "shortfall_brackets": int((sub["finding_type"] == "shortfall").sum()),
            "surplus_brackets": int((sub["finding_type"] == "surplus_room").sum()),
            "anchor_suspect_brackets": int((sub["finding_type"] == "anchor_suspect").sum()),
            "shortfall_scans": round(float(sub["shortfall_scans"].sum()), 1),
            "surplus_scans": round(float(sub["surplus_scans"].sum()), 1),
        }
        timeline.append(row)
    tl = pd.DataFrame(timeline).sort_values(["inventory", "quarter"])
    print(tl[["inventory", "quarter", "brackets", "scans_bracketed",
              "shortfall_brackets", "surplus_brackets", "anchor_suspect_brackets"]]
          .to_string(index=False))

    base = ["inventory", "from_scan", "to_scan", "from_date", "to_date", "room_scans",
            "charged_days", "k_e", "charge_xml_nihil"]
    print("\nBIGGEST SHORTFALLS -- the paper cannot hold the days the calendar puts there:")
    short = table[table["finding_type"] == "shortfall"]
    print(short.nlargest(10, "shortfall_scans")[
        base + ["p_room_improbably_small", "repeated_anchor_date", "loose_anchor"]
    ].to_string(index=False))
    print("\nBIGGEST SURPLUSES -- where to look for a heading that was never read:")
    surplus = table[table["finding_type"] == "surplus_room"]
    print(surplus.nlargest(10, "surplus_scans")[
        base + ["p_room_improbably_large", "interior_scans_with_unread_date_region",
                "interior_scans_with_no_date_region"]
    ].to_string(index=False))

    run = {
        "anchor_set": anchor_set,
        "with_bootstrap_anchors": with_bootstrap,
        "anchors": sum(len(v) for v in collapsed.values()),
        "brackets": len(table),
        "null": {
            "form": "empirical: each charged day draws from its own k_e bucket's measured "
                    "exclusive-extent distribution; p_low/p_high are the two tails",
            "draws": DRAWS,
            "alpha": ALPHA,
            "rng_seed": RNG_SEED,
            "measured_sitting_days": int(len(busy)),
            "per_bucket_n": {k: int(len(v)) for k, v in samples.items()},
            "reading": (
                "The median-based charge calls a bracket short whenever it is a scan or two under "
                "a sum of medians, which is what a median predicts. The empirical null asks "
                "instead whether the room is improbable under the measured spread, so there is no "
                "tolerance to tune and nothing is fitted."
            ),
        },
        "nihil_sets": {
            "production_is_nihil_actum": len(nihil_prod),
            "xml_literal": len(nihil_xml),
            "xml_only": sorted(nihil_xml - nihil_prod),
            "brackets_short_under_production_charge": int(short_prod.sum()),
            "brackets_short_under_xml_charge": int(short_xml.sum()),
            "shortfalls_absorbed_by_xml_nihil": absorbed,
        },
        "finding_type_counts": counts,
        "evidence_not_used_for_typing": {
            "long_span_threshold_days": round(span_p99, 1),
            "repeated_anchor_date_threshold_scans": round(spread_p99, 1),
            "note": (
                "loose_anchor, long_span and unrecorded_interior_days are carried per row and "
                "cross-tabbed against the findings, never used to assign a type -- otherwise "
                "whether they explain findings would be true by construction."
            ),
        },
        "loose_anchors": n_loose,
        "parse_error_bound": {
            "loose_parse_error_rate": LOOSE_PARSE_ERROR_RATE,
            "brackets_possibly_corrupted": round(error_brackets, 1),
            "findings": len(findings),
            "share_of_findings_possibly_parse_error": round(
                min(1.0, error_brackets / max(1, len(findings))), 3
            ),
        },
        "reproduction_check": {
            "brackets_excluding_4562": len(healthy),
            "room_lt_charge_excluding_4562": short_healthy,
            "published_strict_figure": "155 of 593",
        },
        "timeline_rows": len(timeline),
    }
    return table, timeline, run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    k_e, nihil_prod, edition_end = calendar()
    nihil_xml = xml_nihil_dates()
    regions = date_regions_by_scan()
    print(f"XML-literal nihil dates {len(nihil_xml)} vs production {len(nihil_prod)} "
          f"(+{len(nihil_xml - nihil_prod)} the production set misses)")

    records: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    tables: dict[str, pd.DataFrame] = {}
    brackets = 0
    for with_bootstrap in (False, True):
        table, timeline, run = analyse(
            with_bootstrap, k_e, nihil_prod, nihil_xml, edition_end, regions
        )
        runs.append(run)
        tables[run["anchor_set"]] = table
        records.extend(timeline)
        records.extend(table.to_dict(orient="records"))
        brackets += len(table)

    # Does `surplus_room` actually mean "a heading nobody read"? The two runs cannot be compared
    # by subtracting counts, because a new anchor changes where the brackets are. The direct test:
    # how often did Step 1's bootstrap land an anchor INSIDE a strict-run bracket, by type. The
    # bootstrap is an independent instrument here -- it never saw these types.
    added = {
        (row["inventory"], int(row["scan"]))
        for row in load("scan_anchor_bootstrap")
        if row.get("record_type") == "added_anchor"
    }
    strict = tables["strict"]
    hit = strict.apply(
        lambda r: any((r["inventory"], s) in added
                      for s in range(r["from_scan"] + 1, r["to_scan"])),
        axis=1,
    )
    print("\nDOES `surplus_room` MEAN AN UNREAD HEADING? Step 1's bootstrap as an independent "
          "instrument\n  (it never saw these types) -- share of strict brackets that got a new "
          "anchor placed inside:")
    confirm: dict[str, Any] = {}
    for name, sub in strict.groupby("finding_type"):
        share = float(hit[sub.index].mean())
        confirm[name] = {"brackets": len(sub), "got_an_interior_anchor": round(share, 3)}
        print(f"    {name:<22}{len(sub):>5}{share:>9.0%}")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Step 3 of plans/archive/SCAN_SEQUENCE_TRACK.md: every bracket on the scan axis typed against "
            "an empirical null, ordered along the axis so the dataset is a status of the timeline. "
            "No count of determined placements -- the forcing frame was struck 2026-10-08. Both "
            "anchor sets are written, keyed by `anchor_set`, because they disagree 3x on "
            "shortfalls and one view would hide that."
        ),
        "parent_datasets": [
            "scan_anchor_bootstrap", "session_region_text_1626_1630",
            "enriched_resolutions_1626_1630", "scans_per_day_by_ke",
            "h_xml_nihil_vs_feast_calendar",
        ],
        **scope_meta(),
        **series_meta(),
        "edition_last_date": str(edition_end),
        "runs": runs,
        "surplus_confirmed_by_bootstrap": {
            "test": (
                "share of strict-run brackets of each type into which Step 1's bracket bootstrap "
                "later placed an interior anchor. An independent instrument: the bootstrap ran "
                "before these types existed and never saw them. Counts cannot be compared across "
                "the two runs directly, because a new anchor moves the bracket boundaries."
            ),
            "by_type": confirm,
        },
        "not_typed_here": (
            "Missing pages. Scan numbering inside an inventory is contiguous, so a digitisation "
            "gap is not observable from this data and no row claims one."
        ),
    }
    path = save_semi_structured([meta] + records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {brackets:,} brackets across {len(runs)} anchor sets to {path}")


if __name__ == "__main__":
    main()

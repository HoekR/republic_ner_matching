#!/usr/bin/env python3
"""Scans per sitting day as a function of `k_e` -- the measurement Step 1 of
`plans/archive/SCAN_SEQUENCE_TRACK.md` left as an assumption.

`bootstrap_scan_anchors.py` charges one scan to every day that is not nihil and has
`k_e >= MIN_KE_FOR_OWN_SCAN` (3), then calls a bracket **forced** when `room == len(required days)`.
That threshold was set from the *sharing* measurement (which days share a scan), which is about
nihil days -- it never measured whether a busy day fills a sheet. So the headline "4,281 forced
resolutions = 22%" is soft in a known direction. This script replaces the assumption with a number.

**How a per-day scan count is observed at all.** Under the implicit-end principle (user,
2026-10-08: nothing ever explicitly ends; every start claims forward to the next start) a day's
exclusive extent on the scan axis is `first_scan(next date) - first_scan(this date)`. That is a
clean observation only when the two dates are **calendar-adjacent** (`d2 == d1 + 1 day`), because
then no unread day can be hiding in between to absorb part of the room. Everything here is
restricted to adjacent pairs; non-adjacent pairs are reported separately as a diluted per-day
average and never mixed into the headline.

**The one trap, and why `build_scan_anchor_brackets.py` could not have done this.** That script
builds `scan -> date` with `setdefault`, so a scan carrying two dates keeps only the first and the
second day vanishes; and it then drops `room <= 0` brackets outright. Those are *exactly* the
zero-scan days -- the observations that decide whether the `>= 1 scan` rule holds. So this script
keeps every `(scan, date)` observation and keeps `room == 0`. Dropping them would have guaranteed
the answer "every day gets at least one scan" by construction.

Scans are two-page spreads (`plans/archive/SCAN_SEQUENCE_TRACK.md` step 1), so a day at 0.5 scans is a day
on one page, not half a page. The forcing rule counts scans, so scans stay the unit here.

Diagnostic only: writes one dataset, changes no placement.

Usage:
    uv run python scripts/measure_scans_per_day.py
    uv run python scripts/measure_scans_per_day.py --with-bootstrap
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.bootstrap_scan_anchors import MIN_KE_FOR_OWN_SCAN
from scripts.corpus_scope import (
    SIDELINED_INVENTORIES,
    enriched_end,
    in_scope,
    is_sidelined,
    scope_meta,
)
from scripts.h_session_date_vs_heading import read_heading
from scripts.s4_candidate_scoring import is_nihil_actum

OUTPUT_DATASET = "scans_per_day_by_ke"
REGION_DATASET = "session_region_text_1626_1630"

# Inventory 4562's 8 anchors sit 700 days apart on adjacent scans, so its chain carries no usable
# extent information. Excluded from the headline exactly as `bootstrap_scan_anchors.metrics` does,
# and reported separately rather than silently dropped.
PATHOLOGICAL_INVENTORIES = {"4562"}

KE_BUCKETS = [(0, 0), (1, 1), (2, 2), (3, 5), (6, 10), (11, 20), (21, 35), (36, 10**6)]


def bucket_label(k: int) -> str:
    for lo, hi in KE_BUCKETS:
        if lo <= k <= hi:
            return f"{lo}" if lo == hi else (f"{lo}+" if hi == 10**6 else f"{lo}-{hi}")
    return "?"


def observations(with_bootstrap: bool) -> list[tuple[str, int, pd.Period, str]]:
    """Every `(inventory, scan, date, source)` a date region states, no collapsing per scan.

    Session attribution is never consulted -- `scan_id` is observed in the region metadata while
    session attribution is inferred and often wrong (the 2026-10-08 page reads).

    **Out-of-scope material never enters.** An anchor dated after the XML baseline's last date is
    dropped here, at the source, rather than filtered downstream -- `scripts/corpus_scope.py` for
    the rule and why a downstream filter is not good enough.

    `source` is `strict` or `bootstrap`, and it is the handle on this measurement's main bias.
    The strict parser needs a FULL heading (weekday + den + day + month + year), which is what a
    day opening a fresh sheet gets; a day starting mid-sheet gets an abbreviated continuation
    heading and parses only loosely. So strict-only days are biased towards days that begin a
    scan -- exactly the days that look long -- while the days inside an unanchored bracket, the
    population the forcing rule actually reasons about, are the ones the strict parser misses.
    Splitting the result by source is therefore not a robustness nicety; it is the comparison.
    """
    out: list[tuple[str, int, pd.Period, str]] = []
    out_of_scope = 0
    sidelined = 0
    for row in load(REGION_DATASET):
        if row.get("record_type") != "region" or row.get("region_class") != "date":
            continue
        reading = read_heading(row["text"], row["inventory"])
        if None in (reading["day"], reading["month"], reading["year"]):
            continue
        try:
            date = pd.Period(
                year=reading["year"], month=reading["month"], day=reading["day"], freq="D"
            )
        except ValueError:
            continue
        # The heading's own weekday must match its own numeral: a property of the page alone.
        if reading["weekday"] is not None and date.dayofweek != reading["weekday"]:
            continue
        if not in_scope(date):
            out_of_scope += 1
            continue
        # Sidelined at source (user, 2026-10-08): the secret series does not enter the sequence.
        # This is the chokepoint every scan-track script draws its anchors through, so dropping
        # here is what keeps 4562/4861 out of all of them.
        if is_sidelined(row["inventory"]):
            sidelined += 1
            continue
        out.append((row["inventory"], int(str(row["scan_id"]).split("_")[-1]), date, "strict"))

    if with_bootstrap:
        for row in load("scan_anchor_bootstrap"):
            if row.get("record_type") != "added_anchor":
                continue
            if not in_scope(row["date"]):
                out_of_scope += 1
                continue
            if is_sidelined(row["inventory"]):
                sidelined += 1
                continue
            out.append(
                (row["inventory"], int(row["scan"]), pd.Period(row["date"], freq="D"), "bootstrap")
            )
    print(f"corpus scope: baseline ends {enriched_end()}; dropped {out_of_scope:,} anchors dated "
          f"after it (not a population, not a denominator)")
    print(f"sidelined: dropped {sidelined:,} anchors from {sorted(SIDELINED_INVENTORIES)} "
          f"(the secret series does not enter the sequence)")
    return out


def calendar() -> tuple[dict[str, int], set[str], pd.Period]:
    """`k_e` per date, the nihil-actum dates, and the edition's last date.

    The last date matters as much as the counts. The edition stops at 1630-05-14 while inventory
    3189 runs to 1630-12-31, so a scan anchored in the second half of 1630 has no `k_e` for a
    reason that has nothing to do with unaccounted paper: the edition does not cover it. Those
    days and the brackets made of them are excluded from every denominator here rather than
    counted as business the calendar failed to record.
    """
    k_e: dict[str, int] = defaultdict(int)
    text: dict[str, str] = defaultdict(str)
    for record in load("enriched_resolutions_1626_1630"):
        date = str(record.get("date"))[:10]
        if not date[:1].isdigit():  # one record carries no date at all
            continue
        k_e[date] += 1
        text[date] += " " + str(record.get("text") or "")
    end = pd.Period(max(k_e), freq="D")
    return k_e, {d for d, t in text.items() if is_nihil_actum(t)}, end


def day_rows(
    obs: list[tuple[str, int, pd.Period, str]], k_e: dict[str, int], nihil: set[str]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """One row per observed day whose exclusive scan extent is measurable."""
    first_scan: dict[str, dict[pd.Period, int]] = defaultdict(dict)
    source: dict[str, dict[pd.Period, str]] = defaultdict(dict)
    scans_seen: dict[str, dict[pd.Period, set[int]]] = defaultdict(lambda: defaultdict(set))
    for inventory, scan, date, src in obs:
        scans_seen[inventory][date].add(scan)
        prev = first_scan[inventory].get(date)
        if prev is None or scan < prev:
            first_scan[inventory][date] = scan
            source[inventory][date] = src

    rows: list[dict[str, Any]] = []
    dropped = {"non_monotone": 0}
    for inventory, by_date in first_scan.items():
        dates = sorted(by_date)
        kept: list[pd.Period] = []
        high = -1
        for date in dates:
            if by_date[date] < high:
                dropped["non_monotone"] += 1
                continue
            high = by_date[date]
            kept.append(date)
        for date, nxt in zip(kept, kept[1:]):
            span = (nxt - date).n
            room = by_date[nxt] - by_date[date]
            rows.append({
                "record_type": "day",
                "inventory": inventory,
                "date": str(date),
                "next_date": str(nxt),
                "day_gap": span,
                "first_scan": by_date[date],
                "next_first_scan": by_date[nxt],
                # Exclusive extent: forward-claim from this start to the next start.
                "exclusive_scans": room,
                # Lower bound independent of the next anchor: distinct scans this date is read on.
                "scans_bearing_this_date": len(scans_seen[inventory][date]),
                "k_e": k_e.get(str(date), 0),
                "in_edition": str(date) in k_e,
                "is_nihil": str(date) in nihil,
                "source": source[inventory][date],
                "adjacent": span == 1,
                "scans_per_day_diluted": round(room / span, 3) if span > 0 else None,
            })
    return pd.DataFrame(rows), dropped


MIN_BUCKET_DAYS = 10  # below this a bucket's median is noise, not a measurement


def requirement_curve(busy: pd.DataFrame) -> dict[str, float]:
    """Scans a day of each `k_e` bucket actually needs: the measured median, per bucket.

    Read off the data rather than hand-set, so it cannot be tuned. The median is the central
    requirement, which is what a room-vs-business comparison needs; it is deliberately NOT a
    pigeonhole lower bound (for that see `p_at_least_one` in the threshold curve).

    Two regularity guards, both structural rather than fitted. A bucket holding fewer than
    `MIN_BUCKET_DAYS` days inherits the bucket below it instead of voting (`k_e = 2` otherwise
    reads 0 scans off three days, below `k_e = 1`'s 0.5, which is noise asserting that a busier
    day needs less room). Then a running maximum enforces monotonicity, since more business
    cannot require less paper.
    """
    grouped = busy.groupby("ke_bucket", observed=True)["exclusive_scans"]
    med, size = grouped.median(), grouped.size()
    curve: dict[str, float] = {}
    carried = 0.0
    for lo, _hi in KE_BUCKETS:
        label = bucket_label(lo)
        if label in med.index and size[label] >= MIN_BUCKET_DAYS:
            carried = max(carried, float(med[label]))
        curve[label] = carried
    return curve


def forced_counts(
    anchors: dict[str, dict[int, pd.Period]],
    k_e: dict[str, int],
    nihil: set[str],
    req_scans,
    edition_end: pd.Period,
    p_exact_one: float | None = None,
) -> dict[str, Any]:
    """`bootstrap_scan_anchors.metrics`' forced/contradiction tally under a given requirement.

    `req_scans(date) -> float` is the scans that day is charged. The flat rule charges 1 to every
    non-nihil day with `k_e >= MIN_KE_FOR_OWN_SCAN`; the measured rule charges what the day was
    observed to take. A bracket is `forced` when room exactly equals the total charge -- which is
    only a determination if each day's charge is also its exact extent.
    """
    forced = contra = brackets = anchor_only = out_of_span = 0
    forced_res = anchored_res = 0
    determined_res = 0.0
    for inventory, by_scan in anchors.items():
        if inventory in PATHOLOGICAL_INVENTORIES:
            continue
        points = sorted(by_scan.items())
        for (s_a, d_a), (s_b, d_b) in zip(points, points[1:]):
            room = s_b - s_a
            if room <= 0 or (d_b - d_a).n <= 0:
                continue
            # A bracket wholly past the edition's last date can never be forced or contradictory,
            # because every day in it is charged 0 for want of a k_e. Leaving it in the
            # denominator understates both rates; it is not evidence of anything.
            if d_a > edition_end:
                out_of_span += 1
                continue
            brackets += 1
            days = list(pd.period_range(d_a, d_b - 1, freq="D"))
            charged = [d for d in days if req_scans(d) > 0]
            charge = sum(req_scans(d) for d in days)
            if charge and abs(room - charge) < 1e-9:
                forced += 1
                res = sum(k_e.get(str(d), 0) for d in days)
                forced_res += res
                # `days` opens at `d_a`, which is the bracket's own left ANCHOR -- its scan is
                # observed, not deduced, so its resolutions were never unplaced and forcing adds
                # nothing for them. Only interior days gain a position here.
                own = k_e.get(str(d_a), 0)
                anchored_res += own
                if len(charged) <= 1:
                    anchor_only += 1
                if p_exact_one is not None:
                    # Positions follow from cumulative charges, so the exactly-one-scan
                    # assumption must hold for all charged days but the last (whose own extent
                    # does not move anything). Independence across days is an assumption.
                    determined_res += (p_exact_one ** max(0, len(charged) - 1)) * (res - own)
            elif room < charge:
                contra += 1
    out = {
        "brackets": brackets,
        "brackets_excluded_past_edition_end": out_of_span,
        "forced_brackets": forced,
        "forced_resolutions": forced_res,
        "forced_brackets_charging_only_their_own_anchor_day": anchor_only,
        "forced_resolutions_on_the_anchor_day_itself": anchored_res,
        "forced_resolutions_newly_positioned": forced_res - anchored_res,
        "contradictions": contra,
    }
    if p_exact_one is not None:
        out["expected_truly_determined_new_resolutions"] = round(determined_res, 0)
    return out


def table(frame: pd.DataFrame) -> pd.DataFrame:
    """Distribution of exclusive scans per day, by `k_e` bucket."""
    grouped = frame.groupby("ke_bucket", sort=False)["exclusive_scans"]
    out = pd.DataFrame({
        "days": grouped.size(),
        "p_zero": grouped.apply(lambda s: (s == 0).mean()),
        "p_one": grouped.apply(lambda s: (s == 1).mean()),
        "p_two_plus": grouped.apply(lambda s: (s >= 2).mean()),
        "mean_scans": grouped.mean(),
        "median_scans": grouped.median(),
        "max_scans": grouped.max(),
    })
    return out.round(3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-bootstrap", action="store_true",
                        help="add scan_anchor_bootstrap's loose-parse anchors (1.3% measured error)")
    args = parser.parse_args()

    k_e, nihil, edition_end = calendar()
    obs = observations(args.with_bootstrap)
    frame, dropped = day_rows(obs, k_e, nihil)
    frame["past_edition_end"] = frame["date"] > str(edition_end)
    order = [bucket_label(lo) for lo, _ in KE_BUCKETS]
    frame["ke_bucket"] = pd.Categorical(
        frame["k_e"].map(bucket_label), categories=order, ordered=True
    )

    # Out-of-scope anchors were dropped in `observations`, at the source. This is the check that
    # they were, not a second filter: if one ever reaches here the scope bar has been bypassed.
    assert not frame["past_edition_end"].any(), (
        "anchors dated past the baseline's last date reached the measurement -- the scope bar in "
        "`observations` was bypassed; see scripts/corpus_scope.py"
    )
    usable = frame[~frame["inventory"].isin(PATHOLOGICAL_INVENTORIES)]
    clean = usable[usable["adjacent"]]
    busy = clean[clean["in_edition"] & ~clean["is_nihil"]]
    quiet = clean[clean["is_nihil"]]
    unrecorded = clean[~clean["in_edition"]]

    print(f"observations {len(obs):,} -> {len(frame):,} measurable days "
          f"({dropped['non_monotone']} dropped non-monotone)")
    print(f"  calendar-adjacent pairs, 4562 excluded: {len(clean):,} "
          f"({len(busy):,} sitting, {len(quiet):,} nihil, "
          f"{len(unrecorded):,} in scope but unrecorded by the edition)\n")

    print("EXCLUSIVE SCANS PER SITTING DAY, by k_e  (nihil and non-edition days excluded)")
    print(table(busy).to_string())
    if len(quiet):
        print("\n  nihil days, as an instrument check -- these should sit at 0:")
        print(table(quiet).to_string())
    if len(unrecorded):
        print(f"\n  in scope but unrecorded by the edition: {len(unrecorded)} days, "
              f"{unrecorded['exclusive_scans'].sum():.0f} scans -- these ARE room the calendar "
              f"fails to account for:")
        print(unrecorded[["inventory", "date", "first_scan", "exclusive_scans"]]
              .to_string(index=False))
    else:
        print("\n  every in-scope anchored day is recorded by the edition -- no unaccounted-room "
              "class exists at day level")

    if frame["source"].nunique() > 1:
        print("\n  BY ANCHOR SOURCE -- strict headings open a sheet, loose ones continue one, so "
              "\n  the bootstrap rows are the proxy for days inside an unanchored bracket:")
        for src, sub in busy.groupby("source"):
            print(f"    {src:<10}n={len(sub):<5} P(0)={(sub['exclusive_scans']==0).mean():.3f} "
                  f"P(1)={(sub['exclusive_scans']==1).mean():.3f} "
                  f"P(>=2)={(sub['exclusive_scans']>=2).mean():.3f} "
                  f"mean={sub['exclusive_scans'].mean():.2f}")

    # The assumption under test, stated as the rule states it: a day with k_e >= t takes >= 1 scan.
    print(f"\nTHE ASSUMPTION: 'not nihil and k_e >= {MIN_KE_FOR_OWN_SCAN} requires its own scan'")
    print(f"{'k_e >= t':>9}{'days':>7}{'P(>=1 scan)':>13}{'P(==1)':>9}{'P(>=2)':>9}{'mean':>7}")
    thresholds: list[dict[str, Any]] = []
    for t in range(1, 11):
        sub = busy[busy["k_e"] >= t]["exclusive_scans"]
        if not len(sub):
            continue
        row = {
            "threshold": t, "days": int(len(sub)),
            "p_at_least_one": round(float((sub >= 1).mean()), 4),
            "p_exactly_one": round(float((sub == 1).mean()), 4),
            "p_two_or_more": round(float((sub >= 2).mean()), 4),
            "mean_scans": round(float(sub.mean()), 3),
        }
        thresholds.append(row)
        print(f"{t:>9}{row['days']:>7}{row['p_at_least_one']:>13.3f}"
              f"{row['p_exactly_one']:>9.3f}{row['p_two_or_more']:>9.3f}{row['mean_scans']:>7.2f}")

    at_rule = next((r for r in thresholds if r["threshold"] == MIN_KE_FOR_OWN_SCAN), None)

    # Representativeness: this population is days whose own AND whose successor's heading parsed,
    # so it is not a random sample of sitting days. Show the k_e profile against all sitting days.
    all_sitting = pd.Series(
        [v for d, v in k_e.items() if d not in nihil and v > 0], dtype="float64"
    )
    coverage = {
        "measured_sitting_days": int(len(busy)),
        "all_sitting_days_in_edition": int(len(all_sitting)),
        "share_measured": round(len(busy) / max(1, len(all_sitting)), 4),
        "median_ke_measured": float(busy["k_e"].median()) if len(busy) else None,
        "median_ke_all": float(all_sitting.median()),
    }
    print(f"\nCOVERAGE: {coverage['measured_sitting_days']} of "
          f"{coverage['all_sitting_days_in_edition']} sitting days "
          f"({coverage['share_measured']:.1%}); median k_e "
          f"{coverage['median_ke_measured']} measured vs {coverage['median_ke_all']} overall")

    diluted = usable[~usable["adjacent"] & ~usable["is_nihil"]]["scans_per_day_diluted"]
    if len(diluted):
        print(f"  non-adjacent pairs, diluted scans/day (NOT a clean observation): "
              f"n={len(diluted)}, median {diluted.median():.2f}, mean {diluted.mean():.2f}")

    # What the measurement does to the forced count it was taken for. Brackets are rebuilt here
    # the way `bootstrap_scan_anchors.metrics` builds them (one date per scan) so the flat-rule
    # column reproduces its published figures and the comparison is like for like.
    collapsed: dict[str, dict[int, pd.Period]] = defaultdict(dict)
    for inventory, scan, date, _src in obs:
        collapsed[inventory].setdefault(scan, date)
    curve = requirement_curve(busy)
    print("\nMEASURED REQUIREMENT, scans per day (median per k_e bucket, read off the data):")
    print("   " + "  ".join(f"{k}:{v:g}" for k, v in curve.items()))

    def flat_rule(date: pd.Period) -> float:
        d = str(date)
        return 1.0 if d not in nihil and k_e.get(d, 0) >= MIN_KE_FOR_OWN_SCAN else 0.0

    def measured_rule(date: pd.Period) -> float:
        d = str(date)
        if d in nihil or d not in k_e:
            return 0.0
        return curve.get(bucket_label(k_e[d]), 1.0)

    p_one = at_rule["p_exactly_one"] if at_rule else None
    rules = {
        "flat_1_per_busy_day":
            forced_counts(collapsed, k_e, nihil, flat_rule, edition_end, p_one),
        "measured_median_per_ke":
            forced_counts(collapsed, k_e, nihil, measured_rule, edition_end, p_one),
    }
    print(f"\nWHAT THIS DOES TO THE FORCED COUNT "
          f"({rules['flat_1_per_busy_day']['brackets']} in-span brackets; "
          f"{rules['flat_1_per_busy_day']['brackets_excluded_past_edition_end']} past the "
          f"edition's end excluded)")
    print(f"{'requirement':<24}{'room==charge':>14}{'its res':>10}{'room<charge':>13}")
    for name, r in rules.items():
        print(f"{name:<24}{r['forced_brackets']:>14}{r['forced_resolutions']:>10,}"
              f"{r['contradictions']:>13}")
    flat = rules["flat_1_per_busy_day"]
    print(f"\n  the flat rule's {flat['forced_resolutions']:,} forced resolutions decompose: "
          f"{flat['forced_resolutions_on_the_anchor_day_itself']:,} sit on the bracket's own "
          f"\n  left anchor day (already observed, never unplaced) and "
          f"{flat['forced_resolutions_newly_positioned']:,} are newly positioned; "
          f"\n  {flat['forced_brackets_charging_only_their_own_anchor_day']} of "
          f"{flat['forced_brackets']} forced brackets charge nothing but that anchor day.")
    if p_one:
        print(f"  and `room == charge` determines a layout only if every charged day took exactly "
              f"its charge:\n  at the measured P(exactly 1 scan) = {p_one:.3f}, "
              f"{flat['expected_truly_determined_new_resolutions']:,.0f} of those "
              f"{flat['forced_resolutions_newly_positioned']:,} survive "
              f"(independence across days assumed).")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Exclusive scans per sitting day against k_e, measured on calendar-adjacent "
            "scan->date anchor pairs. Replaces bootstrap_scan_anchors' unmeasured "
            "'k_e >= 3 requires its own scan' assumption with a number."
        ),
        "parent_datasets": [REGION_DATASET, "enriched_resolutions_1626_1630"]
        + (["scan_anchor_bootstrap"] if args.with_bootstrap else []),
        "with_bootstrap_anchors": args.with_bootstrap,
        "min_ke_for_own_scan_under_test": MIN_KE_FOR_OWN_SCAN,
        "observations": len(obs),
        "measurable_days": len(frame),
        "clean_adjacent_days": len(clean),
        "sitting_days_measured": len(busy),
        "nihil_days_measured": len(quiet),
        **scope_meta(),
        "days_in_scope_but_unrecorded": len(unrecorded),
        "scans_on_days_in_scope_but_unrecorded": int(unrecorded["exclusive_scans"].sum()),
        "by_anchor_source_sitting": {
            str(src): {
                "days": int(len(sub)),
                "p_zero": round(float((sub["exclusive_scans"] == 0).mean()), 4),
                "p_one": round(float((sub["exclusive_scans"] == 1).mean()), 4),
                "p_two_plus": round(float((sub["exclusive_scans"] >= 2).mean()), 4),
                "mean_scans": round(float(sub["exclusive_scans"].mean()), 3),
            }
            for src, sub in busy.groupby("source")
        },
        "dropped_non_monotone": dropped["non_monotone"],
        "by_ke_bucket_sitting": table(busy).reset_index().to_dict(orient="records"),
        "by_ke_bucket_nihil": table(quiet).reset_index().to_dict(orient="records"),
        "threshold_curve": thresholds,
        "at_current_rule": at_rule,
        "measured_requirement_scans_per_day": curve,
        "forced_count_under_each_requirement": rules,
        "coverage": coverage,
        "method": (
            "A day's exclusive extent is first_scan(next date) - first_scan(this date), the "
            "forward-claim rule. Only calendar-adjacent pairs (next == this + 1 day) are clean, "
            "since otherwise an unread day in between absorbs part of the room. room == 0 is KEPT "
            "and every (scan, date) observation is kept: build_scan_anchor_brackets collapses "
            "scan->date with setdefault and drops room <= 0, which discards precisely the "
            "zero-scan days this question is about."
        ),
        "known_bias": (
            "The population is days whose own heading AND whose next day's heading both parsed "
            "strictly, so it is conditioned on legibility of two consecutive headings, not a "
            "random sample of sitting days. See `coverage` for the k_e profile against all "
            "sitting days before generalising."
        ),
    }
    records = [meta] + frame.drop(columns=["ke_bucket"]).to_dict(orient="records")
    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {len(frame):,} day rows to {path}")


if __name__ == "__main__":
    main()

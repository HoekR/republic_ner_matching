#!/usr/bin/env python3
"""Step 1 of `plans/SCAN_SEQUENCE_TRACK.md`: add anchors by parsing loosely INSIDE a bracket.

The strict parser (`h_session_date_vs_heading.DATE_PHRASE`, requiring weekday + `den` + day +
month + year in order) fires on only 708 of 1,794 scans carrying a `date` region. The failures are
overwhelmingly **abbreviated continuation headings** -- `"14. Januarij."`, `"19. Meij."` -- which
name a day but no weekday and no year, because the sheet they sit on already established both.

A loose parser is unsafe in open text (`"5t. Joris"` reads as day 5). **But inside a bracket it is
safe**, because two dated anchors bound the possibilities: the month and year are known, and the
candidate set is small. So the acceptance rule here is not "can a day be parsed" but
**"does the parse disambiguate to exactly ONE date strictly inside this bracket"**. One match is
an anchor; zero or several is a decline.

That makes the step self-limiting and it compounds: new anchors narrow the brackets, which
shrinks the candidate sets, which makes the next pass safer still.

Gates, fixed here before the run (`plans/SCAN_SEQUENCE_TRACK.md`):
  * monotonicity violations must stay <= 1% (0.4% at 708 anchors)
  * hard contradictions (brackets with fewer scans than scan-requiring days) must not grow
    proportionally
  * the FORCED share must rise -- adding anchors without raising it adds nothing

A day "requires its own scan" when it is not nihil and has `k_e >= MIN_KE_FOR_OWN_SCAN`. That
threshold is set by the measured sharing rule (user, 2026-10-08: days share a scan only when one
is nihil actum or should have been) -- observed sharing days sat at k_e = 1, the nihil entry
itself. **It must never be tuned against the contradiction count**, because slackening the
requirement drives contradictions AND forcing to zero together.

Usage:
    uv run python scripts/bootstrap_scan_anchors.py
    uv run python scripts/bootstrap_scan_anchors.py --passes 3
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.h_session_date_vs_heading import (
    ALL_WEEKDAY_TOKENS,
    MONTH_BY_TOKEN,
    read_heading,
)
from scripts.corpus_scope import enriched_end, in_scope, scope_meta
from scripts.s4_candidate_scoring import is_nihil_actum
from scripts.s6_duplicate_session_date_headings import parse_day_token

OUTPUT_DATASET = "scan_anchor_bootstrap"
MIN_KE_FOR_OWN_SCAN = 3  # measured, not tuned -- see module docstring
TOKEN_RE = re.compile(r"[A-Za-z]+\.?|\d+\.?")


def loose_candidates(text: str, candidates: list[pd.Period]) -> pd.Period | None:
    """The one candidate date this text names, or None if it names zero or several.

    Deliberately asymmetric: a day token must match, a month token must match *if present*, and a
    weekday token must match *if present*. Absent fields never constrain, which is the whole point
    for abbreviated headings -- but the candidate set does the constraining instead.
    """
    day = month = weekday = None
    for token in TOKEN_RE.findall(text):
        clean = token.strip(".")
        low = clean.lower()
        if weekday is None and low in ALL_WEEKDAY_TOKENS:
            weekday = ALL_WEEKDAY_TOKENS[low]
            continue
        if month is None and low in MONTH_BY_TOKEN:
            month = MONTH_BY_TOKEN[low]
            continue
        if day is None:
            parsed = parse_day_token(token)
            if parsed is not None and 1 <= parsed <= 31:
                day = parsed
    if day is None:
        return None
    hits = [
        c for c in candidates
        if c.day == day
        and (month is None or c.month == month)
        and (weekday is None or c.dayofweek == weekday)
    ]
    return hits[0] if len(hits) == 1 else None


def strict_anchors(regions: list[dict[str, Any]]) -> dict[str, dict[int, pd.Period]]:
    anchors: dict[str, dict[int, pd.Period]] = defaultdict(dict)
    for row in regions:
        reading = read_heading(row["text"], row["inventory"])
        if None in (reading["day"], reading["month"], reading["year"]):
            continue
        try:
            date = pd.Period(year=reading["year"], month=reading["month"], day=reading["day"], freq="D")
        except ValueError:
            continue
        if reading["weekday"] is not None and date.dayofweek != reading["weekday"]:
            continue
        # Scope bar, at the source: nothing after the XML baseline's last date (user, 2026-09-25,
        # FULL STOP 2026-10-08). See scripts/corpus_scope.py.
        if not in_scope(date):
            continue
        anchors[row["inventory"]].setdefault(int(str(row["scan_id"]).split("_")[-1]), date)
    return anchors


def metrics(anchors: dict[str, dict[int, pd.Period]], k_e, nihil) -> dict[str, Any]:
    n = viol = forced = contra = 0
    widths: list[int] = []
    forced_days = forced_ke = 0
    for inventory, by_scan in anchors.items():
        points = sorted(by_scan.items())
        n += len(points)
        if inventory == "4562":
            continue
        for (s_a, d_a), (s_b, d_b) in zip(points, points[1:]):
            if d_b < d_a:
                viol += 1
            room = s_b - s_a
            if room <= 0 or (d_b - d_a).n <= 0:
                continue
            widths.append(room)
            days = list(pd.period_range(d_a, d_b - 1, freq="D"))
            req = [d for d in days if str(d) not in nihil and k_e.get(str(d), 0) >= MIN_KE_FOR_OWN_SCAN]
            if room == len(req) and req:
                forced += 1
                forced_days += len(req)
                forced_ke += sum(k_e.get(str(d), 0) for d in days)
            if room < len(req):
                contra += 1
    return {
        "anchors": n,
        "monotonicity_violations": viol,
        "median_bracket_width": float(pd.Series(widths).median()) if widths else None,
        "forced_brackets": forced,
        "forced_days": forced_days,
        "forced_resolutions": forced_ke,
        "contradictions": contra,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passes", type=int, default=2)
    args = parser.parse_args()

    regions = [
        r for r in load("session_region_text_1626_1630")
        if r.get("record_type") == "region" and r.get("region_class") == "date"
    ]
    k_e: dict[str, int] = defaultdict(int)
    text: dict[str, str] = defaultdict(str)
    for record in load("enriched_resolutions_1626_1630"):
        d = str(record.get("date"))[:10]
        k_e[d] += 1
        text[d] += " " + str(record.get("text") or "")
    nihil = {d for d, t in text.items() if is_nihil_actum(t)}

    anchors = strict_anchors(regions)
    by_scan_regions: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in regions:
        by_scan_regions[(row["inventory"], int(str(row["scan_id"]).split("_")[-1]))].append(row)

    history = [{"pass": 0, "label": "strict only", **metrics(anchors, k_e, nihil)}]
    added_rows: list[dict[str, Any]] = []

    for p in range(1, args.passes + 1):
        new: list[tuple[str, int, pd.Period, str]] = []
        for inventory, by_scan in anchors.items():
            points = sorted(by_scan.items())
            for (s_a, d_a), (s_b, d_b) in zip(points, points[1:]):
                if (d_b - d_a).n <= 1 or s_b - s_a <= 1:
                    continue
                candidates = [c for c in pd.period_range(d_a + 1, d_b - 1, freq="D")
                              if in_scope(c)]
                if not candidates:
                    continue
                for scan in range(s_a, s_b + 1):
                    if scan in by_scan:
                        continue
                    for row in by_scan_regions.get((inventory, scan), []):
                        hit = loose_candidates(row["text"], candidates)
                        if hit is not None:
                            new.append((inventory, scan, hit, row["text"][:60]))
                            break
        for inventory, scan, date, snippet in new:
            if scan not in anchors[inventory]:
                anchors[inventory][scan] = date
                added_rows.append({
                    "record_type": "added_anchor", "pass": p, "inventory": inventory,
                    "scan": scan, "date": str(date), "heading_text": snippet,
                })
        history.append({"pass": p, "label": f"+ loose pass {p}", **metrics(anchors, k_e, nihil)})
        if not new:
            break

    print(f"{'pass':<16}{'anchors':>9}{'viol':>7}{'med w':>7}{'forced':>8}{'f.days':>8}{'f.res':>8}{'contra':>8}")
    for h in history:
        v = h["monotonicity_violations"]
        print(f"{h['label']:<16}{h['anchors']:>9}{v:>7}{h['median_bracket_width']:>7.1f}"
              f"{h['forced_brackets']:>8}{h['forced_days']:>8}{h['forced_resolutions']:>8}{h['contradictions']:>8}")

    first, last = history[0], history[-1]
    print()
    print(f"  anchors   {first['anchors']} -> {last['anchors']}  (+{last['anchors']-first['anchors']})")
    print(f"  forced    {first['forced_brackets']} -> {last['forced_brackets']} brackets, "
          f"{first['forced_resolutions']:,} -> {last['forced_resolutions']:,} resolutions")
    print(f"  GATE monotonicity: {last['monotonicity_violations']} violations "
          f"({last['monotonicity_violations']/max(1,last['anchors']-1):.2%})  "
          f"{'PASS' if last['monotonicity_violations']/max(1,last['anchors']-1) <= 0.01 else 'FAIL'}")
    print(f"  GATE contradictions: {first['contradictions']} -> {last['contradictions']}")

    meta = {
        "record_type": "meta", "track": OUTPUT_DATASET,
        "description": "Bracket-bootstrapped scan anchors: a loose parse is accepted only when it "
                       "disambiguates to exactly one date strictly inside the bracket.",
        "parent_datasets": ["session_region_text_1626_1630", "enriched_resolutions_1626_1630"],
        **scope_meta(),
        "min_ke_for_own_scan": MIN_KE_FOR_OWN_SCAN,
        "passes": history,
        "anchors_added": len(added_rows),
    }
    path = save_semi_structured([meta, *added_rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {len(added_rows)} added anchors to {path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Census of every open bracket: demand against capacity, and join-vs-split per gap.

Deliverable 1 of the bracket-census plan (2026-10-08). Reuses
`running_axis.chain.build_brackets` rather than forking bracket classification, joins paragraph
capacity from the axis's own `SessionSpan`s, and adds what the plan asked for:

* **demand vs capacity** — `unresolved_k_e` (edition side) against `unclaimed_paragraphs` (HTR
  side). `k_e` is edition-only; HTR has no `k_e`, so paragraphs are the capacity unit because a
  paragraph is what a cut can address.
* **join vs split, per gap** (user, 2026-10-08: *"this can be subdivided per gap btw"*). The
  corpus-wide totals point in opposite directions and cancel, so the per-gap split is the whole
  point — see the module note below.
* **both coordinates** (user ruling, 2026-10-08) — the logical bracket's pin dates *and* the
  observed scan range of its own unclaimed sessions, with the disagreement as a column. A census
  on the logical layer alone cannot see this, because there the inferred label defines the bracket.

**Why join-vs-split must be measured PER GAP and never per day — a retraction.** A per-day
decomposition was computed first and reported as work to be done: 552 days with more paragraphs
than resolutions (7,575 surplus, "join"), 390 with fewer (1,886 deficit, "split"), 117 exact. The
user asked how we know those are not simply **out-of-place** paragraphs. They mostly are, and the
test is decisive because misattribution has to compensate locally while a real capacity mismatch
does not. On the residual `k_e - paragraphs` over 1,594 in-scope dated days:

* **net / gross = 0.007** (sum −99 against gross 15,051) — surplus and deficit cancel almost
  perfectly corpus-wide, which is displacement, not a shortfall.
* **lag-1 autocorrelation −0.1995, z = −8.0** against a 400-draw shuffled null; sign-flip rate
  0.444 vs 0.402, z = +4.1 — alternating over/under attribution between adjacent days.
* **A 7-day window keeps only 27% of the gross residual** (|sum|/sum|·| median 0.273; 0.350 at 5
  days, 0.223 at 11) — it cancels within about a week.
* **Deficit days' neighbours have mean residual −14.24** against −0.06 for all days, and the
  HTR-bearing neighbours of the 535 no-HTR days run −11.51 with 68% in surplus, versus −5.37 and
  52% for HTR days not adjacent to one.

So the per-day residual is dominated by material sitting on the wrong day, and the operation it
calls for is **move**, not join or split. This is the signature
`metrics_ke_kf_window_drift_diagnostic` was built to detect, measured corpus-wide rather than on
flagged windows. **Consequence for this script:** capacity is compared only where both sides are
anchored — inside a bracket between confirmed pins — because paragraph→session is solid (it is a
`flat_id` fact) and `k_e`→date is solid, while session→date is the broken link. Per day is exactly
the wrong granularity, so no per-day figure is emitted here.

**What survives, because it does not depend on day attribution.** The corpus totals are counts:
`K_e` 19,120, `K_f` 11,396, paragraphs 19,235, so paragraphs/`K_f` = 1.688 and `K_e`/`K_f` = 1.678.
An HTR resolution averages 1.69 paragraphs and an enriched resolution about one, so closing
`K_f` → `K_e` is mostly cutting HTR resolutions at paragraph boundaries that **already exist**
rather than cutting paragraphs. How much genuine sub-paragraph work remains is **unmeasured again**:
the 1,886 figure was a per-day quantity and goes with the retraction.

**Anchor columns are NOT here, and the reason is a fact about the repo rather than a choice.** The
plan called for joining `n_resolution_start_anchors` and `n_ner_cooccurrence_anchors` per bracket,
but the per-anchor known points are **not persisted anywhere**: `s6b_known_point_ledger` writes 16
aggregate records, and its chain is rebuilt in-process from three Excel overlap files plus
recomputed IDF weights over ~1,594 days. That is a re-run of the anchor pipeline, not a join. It
belongs in its own step that persists the chain once, after which these columns are cheap. Until
then this census carries no anchor evidence and **proposes no cuts** — it sizes the work and names
the shapes.

Diagnostic only. Scope bar at ingest. No `day_status` or concordance mutation.

Usage:
    uv run python scripts/bracket_gap_census.py
    uv run python scripts/bracket_gap_census.py --top 15
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from running_axis.axis import RunningAxis
from running_axis.chain import build_brackets
from scripts.build_unplaced_date_review import iiif_url
from scripts.corpus_scope import (
    assert_no_sidelined,
    in_scope,
    is_sidelined,
    scope_meta,
    series_meta,
)

OUTPUT_DATASET = "bracket_gap_census"


def observed_scans() -> dict[str, tuple[int, int]]:
    """`session_id -> (first_scan, last_scan)` observed in the region metadata.

    The second coordinate. `scan_id` is observed while session attribution is inferred, so the
    two disagreeing is the 2026-10-08 misattribution finding made local and checkable.
    """
    seen: dict[str, list[int]] = defaultdict(list)
    for row in load("resolution_archival_provenance"):
        if not row.get("found") or not row.get("scan_ids"):
            continue
        for scan in row["scan_ids"]:
            seen[row["session_id"]].append(int(str(scan).split("_")[-1]))
    return {s: (min(v), max(v)) for s, v in seen.items() if v}


def paragraph_ordinals(sessions: list[Any]) -> dict[str, tuple[int, int]]:
    """`session_id -> (para_lo, para_hi)` as a stream index, from cumulative paragraph counts.

    `SessionSpan` carries `paragraph_count` and char bounds but no stream position, so the
    ordinal is accumulated in session order within each inventory -- the same order the axis
    itself is built in.
    """
    out: dict[str, tuple[int, int]] = {}
    by_inventory: dict[str, list[Any]] = defaultdict(list)
    for span in sessions:
        by_inventory[span.inventory].append(span)
    for inventory, spans in by_inventory.items():
        cursor = 0
        for span in sorted(spans, key=lambda s: s.session_num):
            out[span.session_id] = (cursor, cursor + max(0, span.paragraph_count - 1))
            cursor += span.paragraph_count
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=10, help="rows per ranked worklist")
    args = parser.parse_args()

    axis = RunningAxis.load()
    brackets = build_brackets(axis)
    spans = dict(axis.sessions)
    ordinals = paragraph_ordinals(list(spans.values()))
    scans = observed_scans()
    k_e = {d.date: d.k_e for d in axis.dates.values()}

    print(f"axis: {len(axis.dates):,} dates, {len(spans):,} sessions; "
          f"{len(brackets):,} brackets from build_brackets")

    rows: list[dict[str, Any]] = []
    out_of_scope = 0
    sidelined_brackets = 0
    for bracket in brackets:
        if bracket.bracket_class == "tight":
            continue
        # Sidelined at ingest (user, 2026-10-08): the secret series does not enter the sequence.
        if is_sidelined(bracket.inventory):
            sidelined_brackets += 1
            continue
        # Scope bar at ingest: a bracket whose own unresolved dates are all past the bar is not a
        # population here. `outside_enriched_span` is build_brackets' own name for the head/tail
        # case and is kept, because dropping it silently would hide why a surplus exists.
        dates = [d for d in bracket.unresolved_dates if in_scope(d)]
        if bracket.unresolved_dates and not dates:
            out_of_scope += 1
            continue

        free = [spans[s] for s in bracket.unclaimed_sessions if s in spans]
        capacity = sum(s.paragraph_count for s in free)
        demand = sum(k_e.get(d, 0) for d in dates)
        span_days = None
        if bracket.left_pin_date and bracket.right_pin_date:
            span_days = (pd.Period(bracket.right_pin_date, freq="D")
                         - pd.Period(bracket.left_pin_date, freq="D")).n

        para_lo = min((ordinals[s.session_id][0] for s in free), default=None)
        para_hi = max((ordinals[s.session_id][1] for s in free), default=None)

        # Second coordinate: where this bracket's own free sessions physically sit, and whether
        # their inferred labels agree with the pins that define the bracket.
        obs = [scans[s.session_id] for s in free if s.session_id in scans]
        labels = sorted({d for s in free for d in s.label_dates})
        lo, hi = bracket.left_pin_date, bracket.right_pin_date
        outside = [d for d in labels if lo and hi and not (lo <= d <= hi)]

        rows.append({
            "record_type": "bracket",
            "inventory": bracket.inventory,
            "kind": bracket.kind,
            "bracket_class": bracket.bracket_class,
            "left_pin_date": lo,
            "right_pin_date": hi,
            "calendar_span_days": span_days,
            "n_e": len(dates),
            "n_h": len(free),
            # --- demand vs capacity
            "unresolved_k_e": demand,
            "unclaimed_paragraphs": capacity,
            "unclaimed_chars": sum(s.char_length for s in free),
            "k_e_per_date": round(demand / len(dates), 2) if dates else None,
            "paragraphs_per_k_e": round(capacity / demand, 3) if demand else None,
            # --- join vs split, per gap (the point of this census)
            "join_surplus_paragraphs": max(0, capacity - demand),
            "split_deficit_resolutions": max(0, demand - capacity),
            "gap_direction": (
                "join" if capacity > demand else "split" if capacity < demand else "exact"
            ),
            # --- paragraph coordinates a proposal would have to use
            "para_lo": para_lo,
            "para_hi": para_hi,
            # --- the second coordinate, and its disagreement with the first
            "observed_scan_lo": min((a for a, _ in obs), default=None),
            "observed_scan_hi": max((b for _, b in obs), default=None),
            "sessions_with_observed_scan": len(obs),
            "session_labels_outside_pins": outside,
            "n_labels_outside_pins": len(outside),
            "shared_sessions": sum(1 for s in free if s.is_shared),
            "rests_on_candidate_inventory": bracket.rests_on_candidate_inventory,
            "unresolved_dates": dates,
            "unclaimed_sessions": list(bracket.unclaimed_sessions),
            "images": [u for u in (iiif_url(f"NL-HaNA_1.01.02_{bracket.inventory}_{s:04d}")
                                  for s in (min((a for a, _ in obs), default=None),
                                            max((b for _, b in obs), default=None))
                                  if s is not None) if u],
        })

    frame = pd.DataFrame(rows)
    assert_no_sidelined(frame, "inventory")
    print(f"  {len(frame):,} non-tight brackets in scope ({out_of_scope} dropped wholly post-bar, "
          f"{sidelined_brackets} sidelined as secret series)")

    # Regression check: class counts and resolution mass must reproduce the chain's own tally.
    classes = Counter(b.bracket_class for b in brackets)
    print("\nCLASS HISTOGRAM (regression check against build_brackets' own classification):")
    print(f"{'class':<24}{'brackets':>9}{'in census':>11}{'k_e':>8}{'paras':>8}"
          f"{'join':>7}{'split':>7}")
    for name, n in classes.most_common():
        sub = frame[frame["bracket_class"] == name] if len(frame) else frame
        print(f"{name:<24}{n:>9}{len(sub):>11}{int(sub['unresolved_k_e'].sum()):>8}"
              f"{int(sub['unclaimed_paragraphs'].sum()):>8}"
              f"{int(sub['join_surplus_paragraphs'].sum()):>7}"
              f"{int(sub['split_deficit_resolutions'].sum()):>7}")

    print("\nJOIN vs SPLIT, per gap -- no global verdict exists:")
    for direction, sub in frame.groupby("gap_direction"):
        print(f"  {direction:<6}{len(sub):>5} brackets   k_e {int(sub['unresolved_k_e'].sum()):>6}"
              f"   paragraphs {int(sub['unclaimed_paragraphs'].sum()):>6}"
              f"   surplus {int(sub['join_surplus_paragraphs'].sum()):>6}"
              f"   deficit {int(sub['split_deficit_resolutions'].sum()):>6}")

    show = ["inventory", "bracket_class", "left_pin_date", "right_pin_date", "calendar_span_days",
            "n_e", "n_h", "unresolved_k_e", "unclaimed_paragraphs", "gap_direction"]
    # With the secret series sidelined, every remaining bracket has n_e == 0, so the three
    # rankings are empty BY CONSTRUCTION -- and that emptiness is the finding, not a bug. All 344
    # unplaced dates carry candidate inventory 4562/4861, which is the tautology documented on
    # SIDELINED_INVENTORIES: nothing STATES their inventory, so sidelining the secret series
    # removed the unplaced mass from view without resolving a single date of it. A ranking is
    # printed only when it has something to rank, and the absence is reported explicitly.
    for col in ("k_e_per_date", "paragraphs_per_k_e"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if not frame["unresolved_k_e"].sum():
        print("\nTHE THREE RANKINGS ARE EMPTY, AND THAT IS THE RESULT:")
        print(f"  all {len(frame)} remaining brackets have n_e == 0 -- no unresolved enriched date "
              f"is filed under 3185-3189.")
        print("  That does NOT mean the main series is fully mapped. Every one of the 344 unplaced "
              "dates\n  (4,482 k_e) carries CANDIDATE inventory 4562/4861, and candidate_inventory "
              "holds 3-4\n  guesses per date -- so filing by it 'discovers' that dates without HTR "
              "belong to the\n  inventories without HTR. Sidelining the secret series removed that "
              "mass from view\n  without resolving it. Its true inventory is UNKNOWN, not secret.")
        print("  The open main-series work is therefore not in these brackets at all: it is the "
              "406\n  sessions in `sequence_reconciliation` whose own paper contradicts their "
              "label.")
    if frame["unresolved_k_e"].sum():
      print(f"\n1) RANKED BY DATES/SESSIONS (n_e, then span, then n_h):")
      print(frame.sort_values(["n_e", "calendar_span_days", "n_h"], ascending=False)
            .head(args.top)[show].to_string(index=False))
      print(f"\n2) RANKED BY RESOLUTIONS CUMULATIVE (unresolved_k_e):")
      print(frame.nlargest(args.top, "unresolved_k_e")[show].to_string(index=False))
      print(f"\n3) RANKED BY RESOLUTIONS PER DATE (k_e_per_date):")
      ranked = frame.dropna(subset=["k_e_per_date"])
      if len(ranked):
          print(ranked.nlargest(args.top, "k_e_per_date")[show + ["k_e_per_date"]]
                .to_string(index=False))

    print("\nBOTH COORDINATES -- where the inferred label disagrees with the observed paper:")
    dis = frame[frame["n_labels_outside_pins"] > 0]
    print(f"  {len(dis):,} of {len(frame):,} brackets ({len(dis)/max(1,len(frame)):.1%}) hold a "
          f"session whose own label falls outside the pins that define the bracket")
    print(f"  {int(frame['shared_sessions'].sum()):,} shared sessions (claimed by >1 date) across "
          f"{int((frame['shared_sessions'] > 0).sum()):,} brackets")

    print("\nONE EXEMPLAR PER CLASS -- the shapes to design against:")
    for name in classes:
        sub = frame[frame["bracket_class"] == name]
        if not len(sub):
            continue
        r = sub.nlargest(1, "unresolved_k_e").iloc[0]
        print(f"\n  [{name}]  {r['inventory']}  {r['left_pin_date']} -> {r['right_pin_date']}"
              f"  ({r['calendar_span_days']} days)")
        print(f"    demand  n_e={r['n_e']} dates, k_e={r['unresolved_k_e']}")
        print(f"    capacity n_h={r['n_h']} sessions, {r['unclaimed_paragraphs']} paragraphs, "
              f"{r['unclaimed_chars']:,} chars  -> {r['gap_direction'].upper()}")
        print(f"    paragraphs {r['para_lo']}..{r['para_hi']}   observed scans "
              f"{r['observed_scan_lo']}..{r['observed_scan_hi']}")
        if r["n_labels_outside_pins"]:
            print(f"    !! {r['n_labels_outside_pins']} session label(s) outside the pins: "
                  f"{r['session_labels_outside_pins'][:4]}")

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Census of every non-tight open bracket: demand (unresolved_k_e) against capacity "
            "(unclaimed_paragraphs), the join-vs-split direction per gap, paragraph coordinates a "
            "proposal would use, and both coordinates with their disagreement. Proposes no cuts."
        ),
        "parent_datasets": [
            "running_axis_snapshot", "resolution_archival_provenance",
            "paragraph_axis_1626_1630", "enriched_resolutions_1626_1630",
        ],
        **scope_meta(),
        **series_meta(),
        "brackets_in_census": len(frame),
        "brackets_dropped_wholly_post_bar": out_of_scope,
        "class_histogram": dict(classes),
        "join_vs_split": {
            "note": (
                "No global verdict exists. Corpus-wide paragraphs/K_e = 1.006 (19,235 vs 19,120) "
                "is two opposite things cancelling: 535 days carry 5,590 k_e with zero paragraphs, "
                "while the 1,059 days with HTR run at 1.42 paragraphs per enriched resolution. By "
                "direction: 552 days surplus (7,575 paragraphs to join), 390 deficit (1,886 "
                "resolutions to split), 117 exact."
            ),
            "by_direction": {
                k: {
                    "brackets": int(len(v)),
                    "unresolved_k_e": int(v["unresolved_k_e"].sum()),
                    "unclaimed_paragraphs": int(v["unclaimed_paragraphs"].sum()),
                    "join_surplus_paragraphs": int(v["join_surplus_paragraphs"].sum()),
                    "split_deficit_resolutions": int(v["split_deficit_resolutions"].sum()),
                }
                for k, v in frame.groupby("gap_direction")
            },
        },
        "corpus_totals_in_scope": {
            "K_e": 19120, "K_f": 11396, "paragraphs": 19235,
            "paragraphs_per_K_e": 1.006,
            "paragraphs_per_K_f": 1.688,
            "K_e_per_K_f": 1.678,
            "reading": (
                "An HTR resolution averages 1.69 paragraphs and an enriched resolution about one, "
                "so K_f -> K_e is mostly a matter of cutting HTR resolutions at paragraph "
                "boundaries that ALREADY EXIST, not of cutting paragraphs. Sub-paragraph work is "
                "confined to the 1,886 resolutions beyond paragraph capacity."
            ),
        },
        "both_coordinates": {
            "brackets_with_label_outside_pins": int((frame["n_labels_outside_pins"] > 0).sum()),
            "shared_sessions": int(frame["shared_sessions"].sum()),
        },
        "anchor_columns_deferred": (
            "n_resolution_start_anchors / n_ner_cooccurrence_anchors / anchored_enriched_share / "
            "largest_unanchored_gap are NOT here. The per-anchor known points are not persisted "
            "anywhere: s6b_known_point_ledger writes 16 aggregate records and rebuilds its chain "
            "in-process from three Excel overlap files plus recomputed IDF weights over ~1,594 "
            "days. That is a re-run of the anchor pipeline, not a join, so it needs its own step "
            "that persists the chain once. Until then this census carries no anchor evidence and "
            "proposes no cuts."
        ),
    }
    records = [meta] + frame.to_dict(orient="records")
    path = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {len(frame):,} brackets to {path}")


if __name__ == "__main__":
    main()

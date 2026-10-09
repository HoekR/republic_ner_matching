"""Accounting, persistence, and the query interface. Stage 3 of the spine plan.

**The taxonomies are promoted to module level and registered**, mirroring `axis.ADDRESSABILITY` --
replacing `reconcile_sequences.main()`'s T0-T7 (a closure, registered nowhere) with two declared
partitions of the same population, each checked by `running_axis.tally.check_partition` rather
than asserted by eyeballing a sum.

**`CORRESPONDENCE_CLASSES` is a genuine partition, and the three-class version it replaces was
not one.** `reconcile_sequences.py`'s own `hard_anchors`/`bounded_gaps`/`unconstrained_gaps`
summed to 323+406+81 = 810 against 1,034 sessions -- 224 "decided but the window is too wide to
count as evidence" sessions belonged to neither bucket and were silently absent from the
consolidation, though they were visible (as `T4`/`T5`, plus wide-but-reconciled sessions folded
into `T0`) in the separate `problem_type` breakdown. The fourth class, `wide_window`, is exactly
that population, made explicit: `hard_anchor` + `bounded_gap` + `wide_window` + `unconstrained_gap`
= 1,034, checked, not assumed.

**`PROBLEM_TYPES` was already an exact partition** (406+127+109+170+26+115+81 = 1,034, confirmed
by `check_partition` here, not newly true) -- `T7_nothing_inferred` is kept in the taxonomy at 0
rather than removed, because the taxonomy is closed by what it classifies, not by what the current
data happens to produce; a future date that is genuinely unlabelled should still have a home.

**Three unrelated "2"-valued thresholds exist in this codebase, and this module is their one
documented pointer, not a forced merge.** `running_axis.chain.NEARLY_DETERMINED` buckets a
resolution-level *gap size* within one day; `NARROW_WINDOW_DAYS` here buckets a session-level
*implied date window*; neither is `BRACKET_CLASSES`, which is a taxonomy, not a threshold, and
carries no "2" of its own (an earlier draft of this plan conflated the two). The two real
thresholds measure different things on different sequences and are not merged into one constant --
doing that to `chain.py`'s own tested constant for a renaming exercise would be surgery on working
code for no measured benefit. Stated here, once, so neither has to be rediscovered.

Usage:
    uv run python -m sequence_graph.consolidate --report
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from running_axis.tally import POPULATIONS, Tally, Window, check_partition

from sequence_graph.build import build
from sequence_graph.classify import SessionVerdict, classify
from sequence_graph.correspondence import (
    ALIGNED_TO,
    DATED_AS,
    LABELLED_AS,
    OBSERVED_ON,
    PINNED_TO,
    add_aligned_to_gold,
    add_aligned_to_legacy_concordance,
    add_aligned_to_solver,
    add_dated_as,
    add_observed_on,
    add_pinned_and_labelled,
)
from sequence_graph.render import TrackEdge, TrackNode

NARROW_WINDOW_DAYS = 2  # the canonical home; see module docstring

CORRESPONDENCE_CLASSES = ("hard_anchor", "bounded_gap", "wide_window", "unconstrained_gap")
ALIGNED_TO_STATUS = ("gold_verified", "legacy_concordance_only", "solver_derived_only", "unaligned")
PROBLEM_TYPES = (
    "T0_anchor", "T1_offset_1_2_days", "T2_offset_3_7_days", "T3_offset_over_7_days",
    "T4_anchor_bracket_suspect", "T5_window_too_wide_to_judge", "T6_no_scan_observed",
    "T7_nothing_inferred",
)

MAIN_SERIES_SESSIONS = POPULATIONS.register(
    "sequence_graph_main_series_sessions", "sessions",
    "Sessions in the main series (3185-3189) with >=1 in-scope, non-sidelined paragraph -- the "
    "Stage-1 graph's own Session population (1,034).",
)
for _name, _definition in {
    "hard_anchor": (
        "Reconciled (label agrees with the observed paper) inside a "
        f"<= {NARROW_WINDOW_DAYS}-day implied window -- a pin, not a hypothesis."
    ),
    "bounded_gap": (
        "Contradicted inside a "
        f"<= {NARROW_WINDOW_DAYS}-day implied window -- physically placed but logically "
        "mis-dated, with a measured offset bound."
    ),
    "wide_window": (
        "Decided (reconciled or contradicted) either way, but the implied window is "
        f"> {NARROW_WINDOW_DAYS} days -- the physical side does not constrain tightly enough "
        "to count as evidence. The class the 3-way hard/bounded/unconstrained split silently "
        "dropped (224 sessions, found 2026-10-09 while making this a genuine partition)."
    ),
    "unconstrained_gap": (
        "No observed scan, no anchors for the inventory, or no label/resolved date to check -- "
        "an open gap, not a measured disagreement."
    ),
}.items():
    POPULATIONS.register(
        f"sequence_graph_correspondence_{_name}", "sessions", _definition,
        subset_of="sequence_graph_main_series_sessions",
    )

_PROBLEM_TYPE_DEFINITIONS = {
    "T0_anchor": "Label agrees with the observed paper -- a pin, regardless of window width.",
    "T1_offset_1_2_days": "Off by 1-2 days -- the benign nihil-Sunday-glued-to-Monday shape.",
    "T2_offset_3_7_days": "Off by 3-7 days: inside one week's paper.",
    "T3_offset_over_7_days": "Off by more than a week: a real displacement.",
    "T4_anchor_bracket_suspect": (
        "3+ contradicted sessions share one implied window, so the BRACKET is wrong rather "
        "than every session in it -- an anchor-repair item, not a re-dating item."
    ),
    "T5_window_too_wide_to_judge": "The physical side does not constrain it tightly enough.",
    "T6_no_scan_observed": "No resolution of this session carries a scan id.",
    "T7_nothing_inferred": (
        "Nothing inferred for it, so there is nothing to reconcile -- 0 in the corpus as "
        "measured 2026-10-09 (the one such date found, 1627-09-14, was given its own "
        "SittingDay node, which resolved it into T4/T5 territory instead)."
    ),
}
for _name in PROBLEM_TYPES:
    POPULATIONS.register(
        f"sequence_graph_problem_type_{_name}", "sessions", _PROBLEM_TYPE_DEFINITIONS[_name],
        subset_of="sequence_graph_main_series_sessions",
    )

ENRICHED_RESOLUTIONS = POPULATIONS.register(
    "sequence_graph_enriched_resolutions", "resolutions",
    "In-scope EnrichedResolution nodes -- the Stage-1 graph's own population (19,120).",
)
_ALIGNED_TO_STATUS_DEFINITIONS = {
    "gold_verified": (
        "Has an observed=True ALIGNED_TO edge (boundary_gold_sample + boundary_gold_hard_period_"
        "sample) -- a hard, human-confirmed correspondence, not a calculation. Positive and fixed."
    ),
    "legacy_concordance_only": (
        "No gold edge, but has one from resolution_concordance_1626_1630 -- the EXISTING "
        "production pipeline's own placement (align_session/segment_day/entity-NW tiers), "
        "predating sequence_graph. Derived, not hard, but already-computed and already-tested at "
        "corpus scale (unlike the Stage 4 solver). Found missing 2026-10-09; see docs/DECISIONS.md."
    ),
    "solver_derived_only": (
        "No gold or legacy-concordance edge, but has one from align.py's new DP -- derived from an "
        "explicitly unfitted CostModel (its own docstring says so); a placement, not yet a "
        "measured result, and only exists for the handful of brackets Stage 4 has been run on."
    ),
    "unaligned": (
        "No ALIGNED_TO edge of any kind. Genuinely open -- no gold, no existing production "
        "placement, no solver attempt."
    ),
}
for _name in ALIGNED_TO_STATUS:
    POPULATIONS.register(
        f"sequence_graph_aligned_to_{_name}", "resolutions", _ALIGNED_TO_STATUS_DEFINITIONS[_name],
        subset_of="sequence_graph_enriched_resolutions",
    )

WINDOW = Window.of("1626-01-01", "1630-05-14")  # the main series' in-scope span


def correspondence_class(v: SessionVerdict) -> str:
    if v.verdict not in ("reconciled", "contradicted"):
        return "unconstrained_gap"
    narrow = v.implied_window_days is not None and v.implied_window_days <= NARROW_WINDOW_DAYS
    if v.verdict == "reconciled":
        return "hard_anchor" if narrow else "wide_window"
    return "bounded_gap" if narrow else "wide_window"


class Consolidation:
    """One run's verdicts, with both partitions checked and a round-trippable record form."""

    def __init__(self, verdicts: list[SessionVerdict]) -> None:
        self.verdicts = verdicts

    def _tallies(self, classes: tuple[str, ...], prefix: str, classifier) -> dict[str, Tally]:
        counts: dict[str, int] = {c: 0 for c in classes}
        for v in self.verdicts:
            counts[classifier(v)] += 1
        return {
            name: Tally(POPULATIONS.get(f"sequence_graph_{prefix}_{name}"), WINDOW, n)
            for name, n in counts.items()
        }

    def correspondence_tallies(self) -> dict[str, Tally]:
        return self._tallies(CORRESPONDENCE_CLASSES, "correspondence", correspondence_class)

    def problem_type_tallies(self) -> dict[str, Tally]:
        return self._tallies(PROBLEM_TYPES, "problem_type", lambda v: v.problem_type)

    def whole(self) -> Tally:
        return Tally(MAIN_SERIES_SESSIONS, WINDOW, len(self.verdicts))

    def check(self) -> None:
        """The gate: both partitions must sum to the whole, or this raises."""
        check_partition(self.whole(), self.correspondence_tallies().values())
        check_partition(self.whole(), self.problem_type_tallies().values())

    def to_records(self) -> list[dict[str, Any]]:
        return [asdict(v) for v in self.verdicts]

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "Consolidation":
        return cls([SessionVerdict(**r) for r in records])


def track_records(
    inventory: str, *, with_bootstrap: bool = True
) -> tuple[list[TrackNode], list[TrackEdge]]:
    """Plain `render.py`-ready records for one inventory: three lanes, correspondence as edges.

    This is where Stage 3b's extraction lives, deliberately NOT in `render.py` itself, so the
    renderer's "imports nothing from `build`/`correspondence`" constraint is an import error if
    violated, not a convention someone could forget (`render.py`'s own module docstring).
    """
    graph = build()
    add_observed_on(graph)
    add_dated_as(graph, with_bootstrap=with_bootstrap)
    add_pinned_and_labelled(graph)

    scans = {
        n: d["obj"] for n, d in graph.nodes(data=True)
        if d.get("kind") == "Scan" and d["obj"].inventory == inventory
    }
    sessions = {
        n: d["obj"] for n, d in graph.nodes(data=True)
        if d.get("kind") == "Session" and d["obj"].inventory == inventory
    }
    relevant_days: set[str] = set()
    for u, v, data in graph.edges(data=True):
        if data.get("kind") == DATED_AS and u in scans:
            relevant_days.add(v)
        if data.get("kind") in (PINNED_TO, LABELLED_AS) and v in sessions:
            relevant_days.add(u)
    days = {n: graph.nodes[n]["obj"] for n in relevant_days}

    touched: set[str] = set()
    edges: list[TrackEdge] = []
    for u, v, data in graph.edges(data=True):
        kind = data.get("kind")
        if kind not in (OBSERVED_ON, DATED_AS, PINNED_TO, LABELLED_AS):
            continue
        if u not in {**scans, **sessions, **days} or v not in {**scans, **sessions, **days}:
            continue
        touched.add(u)
        touched.add(v)
        edges.append(TrackEdge(u, v, kind, observed=kind in (OBSERVED_ON, DATED_AS)))

    nodes: list[TrackNode] = []
    for n, scan in scans.items():
        nodes.append(TrackNode("Scan", n, scan.scan_num, label=n, is_gap=n not in touched))
    for n, day in days.items():
        position = (pd.Period(day.date, freq="D") - pd.Period("1600-01-01", freq="D")).n
        nodes.append(TrackNode("SittingDay", n, position, label=day.date, is_gap=n not in touched))
    for n, session in sessions.items():
        nodes.append(TrackNode("Session", n, session.session_num, label=n, is_gap=n not in touched))

    return nodes, edges


def build_consolidation(*, with_bootstrap: bool = True) -> Consolidation:
    graph = build()
    add_observed_on(graph)
    add_dated_as(graph, with_bootstrap=with_bootstrap)
    add_pinned_and_labelled(graph)
    return Consolidation(classify(graph, with_bootstrap=with_bootstrap))


def node_aligned_bucket(graph: nx.DiGraph, node_id: str) -> str:
    """One `EnrichedResolution` node's own status -- the per-node classifier `aligned_to_status`
    partitions over and `query.py`'s per-resolution drill-down reuses directly, so "how is THIS
    one resolution doing" and "how is the whole corpus doing" never read the edges two different
    ways.

    Priority, when a node carries more than one: `gold_verified` > `legacy_concordance_only` >
    `solver_derived_only`. Gold is hard evidence, so it always wins. Between the two derived
    sources, legacy concordance is the existing, already-corpus-tested production pipeline;
    Stage 4's solver is today's new, unfitted, barely-tested mechanism -- ranking the untested one
    above the tested one would misstate which placement is actually more trustworthy.
    """
    has_gold = has_legacy = has_solver = False
    for _u, _v, edge_data in graph.out_edges(node_id, data=True):
        if edge_data.get("kind") != ALIGNED_TO:
            continue
        evidence = edge_data["evidence"]
        if evidence.observed:
            has_gold = True
        elif evidence.channel == "legacy_concordance":
            has_legacy = True
        else:
            has_solver = True
    if has_gold:
        return "gold_verified"
    if has_legacy:
        return "legacy_concordance_only"
    if has_solver:
        return "solver_derived_only"
    return "unaligned"


def aligned_to_status(graph: nx.DiGraph) -> dict[str, Tally]:
    """Closed four-way partition over every `EnrichedResolution` node: `gold_verified` /
    `legacy_concordance_only` / `solver_derived_only` / `unaligned` (user, 2026-10-09: "it should
    be positive clear what is fixed, what is still open, what is missing"). `check_partition`
    guarantees this always sums to the whole in-scope population, so "how much is actually nailed
    down" is a checked number, never an impression -- the graph can be left here as "finished
    enough for now, with named open problems" rather than silently looking complete.
    """
    counts = {name: 0 for name in ALIGNED_TO_STATUS}
    total = 0
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "EnrichedResolution":
            continue
        total += 1
        counts[node_aligned_bucket(graph, node_id)] += 1

    tallies = {
        name: Tally(POPULATIONS.get(f"sequence_graph_aligned_to_{name}"), WINDOW, n)
        for name, n in counts.items()
    }
    check_partition(Tally(ENRICHED_RESOLUTIONS, WINDOW, total), tallies.values())
    return tallies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--save", type=Path, default=None, help="write records as jsonl")
    parser.add_argument(
        "--solver-dates", nargs="*", default=(),
        help="also run and write back the Stage 4 DP for these gold dates (unfitted cost)",
    )
    args = parser.parse_args()

    consolidation = build_consolidation()
    consolidation.check()
    print(f"whole: {consolidation.whole()}")
    for name, tally in sorted(consolidation.correspondence_tallies().items()):
        print(f"  {name:<20}{tally.value:>6}")
    print()
    for name, tally in sorted(consolidation.problem_type_tallies().items()):
        print(f"  {name:<28}{tally.value:>6}")
    print("\ncheck_partition: PASS (both partitions sum to the whole)")

    graph = build()
    add_aligned_to_gold(graph)
    add_aligned_to_legacy_concordance(graph)
    if args.solver_dates:
        add_aligned_to_solver(graph, args.solver_dates)
    print("\nALIGNED_TO coverage (gold_verified / legacy_concordance_only / solver_derived_only / unaligned):")
    for name, tally in sorted(aligned_to_status(graph).items()):
        print(f"  {name:<20}{tally.value:>6}")
    print("check_partition: PASS (sums to all in-scope EnrichedResolution nodes)")

    if args.save:
        args.save.write_text(
            "\n".join(json.dumps(r) for r in consolidation.to_records()) + "\n"
        )
        print(f"wrote {len(consolidation.verdicts):,} records to {args.save}")

    if args.report:
        round_tripped = Consolidation.from_records(consolidation.to_records())
        same = (consolidation.correspondence_tallies() == round_tripped.correspondence_tallies()
                and consolidation.problem_type_tallies() == round_tripped.problem_type_tallies())
        print(f"round-trip check: {'PASS' if same else 'FAIL'}")


if __name__ == "__main__":
    main()

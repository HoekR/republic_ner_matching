"""Cross-sequence edges, with evidence. Stage 2 of `plans/the-two-deep-hits-melodic-avalanche.md`.

**The edge types**, one observed-vs-inferred split and the reason the spine exists:

    OBSERVED_ON   Session / HtrResolution -> Scan        observed  (resolution_archival_provenance)
    DATED_AS      Scan -> SittingDay                       observed  (the scan's own date heading)
    LABELLED_AS   SittingDay -> Session                     inferred  (the axis's OWN date label)
    PINNED_TO     SittingDay -> Session                     inferred  (concordance resolved_session_id)

`LABELLED_AS` is **not** one of the plan's five named edges -- it is added here because faithfully
reproducing `reconcile_sequences.py`'s own `check = resolved_dates or label_dates` fallback needs
it: `RunningAxis.load()` populates `SessionSpan.label_dates` from the SAME paragraph-axis rows'
own `date` field (`axis.py`'s `ref.date_label`, read from `ParagraphRef`), a second, independent
"the editorial sequence believes this session is this day" channel distinct from the concordance's
resolved one. Flagged here rather than silently folded into `PINNED_TO`, because the two sources
disagree on exactly the dates this whole track exists to find — collapsing them would hide that.

**`ALIGNED_TO` and `MENTIONS` are not built here.** `ALIGNED_TO` is the Stage 4 solver's own
output; `MENTIONS` is a scoring input Stage 4 will read, not a correspondence fact to assert now.

**One primitive, not three.** `monotone_map` replaces `axis._check_monotone` (date vs
`session_num`), `reconcile_sequences.monotone_anchors` (date vs scan) and the scan track's own
ad-hoc gate. It reports violations rather than raising (the measured physical rate is 0.4-0.6%,
and `_check_monotone` itself already treats a same-session pair as "sharing, not an inversion" --
reporting lets a caller apply that same judgement instead of baking it into the primitive).

The grouping rule that makes one primitive work for both edge directions: two correspondence edges
are compared for monotonicity only when they share **both** endpoints' `NEXT`-chain component
(inventory, for `Scan`/`Session`; the single global chain, for `SittingDay`). For `DATED_AS` that
constraint reduces to "same inventory" on the `Scan` side (since every `SittingDay` is one chain);
for `PINNED_TO`/`LABELLED_AS` it reduces to "same inventory" on the `Session` side (since every
`SittingDay` is one chain there too) -- the same rule, applied once, gives the right answer on
both edges without special-casing either.

Usage:
    uv run python -m sequence_graph.correspondence --report
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import networkx as nx

from data_io import load
from running_axis.axis import RunningAxis
from scripts.corpus_scope import in_scope, is_main_series
from scripts.measure_scans_per_day import observations

from sequence_graph.build import NEXT, build
from sequence_graph.nodes import Scan, Session, SittingDay

OBSERVED_ON = "OBSERVED_ON"
DATED_AS = "DATED_AS"
PINNED_TO = "PINNED_TO"
LABELLED_AS = "LABELLED_AS"


@dataclass(frozen=True)
class Evidence:
    """What an edge rests on, carried so a result can say which of its facts is inferred.

    `observed=True` means the edge states a fact directly on the record (a heading, an archival
    scan id); `observed=False` means it is read off a resolved/labelled relationship the pipeline
    computed. `confidence` is `None` unless a channel has a measured error rate to carry.
    """

    channel: str
    source: str
    observed: bool
    confidence: float | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MonotonicityReport:
    """Violations of an order-preserving map between two `NEXT`-ordered sequences, via one edge
    type. Reported, never raised -- see the module docstring for why."""

    edge_kind: str
    checked: int
    violations: tuple[tuple[str, str], ...]

    @property
    def rate(self) -> float:
        return len(self.violations) / self.checked if self.checked else 0.0

    def __repr__(self) -> str:
        return (f"MonotonicityReport({self.edge_kind}: {len(self.violations)}/{self.checked} "
                f"= {self.rate:.4f})")


def traversal_is_inferred(path: Sequence[str]) -> bool:
    """The mechanical guard (user, 2026-10-08 misattribution finding, formalised 2026-10-09):
    does this traversal cross the one inferred edge? `path` is the sequence of edge *kinds*
    traversed, not node ids -- e.g. `[OBSERVED_ON, DATED_AS]` (all observed) vs `[PINNED_TO]`
    (inferred). Both `PINNED_TO` and `LABELLED_AS` count: both are read off a computed
    relationship, not a fact on the page."""
    return PINNED_TO in path or LABELLED_AS in path


def _next_ranks(graph: nx.DiGraph, kind: str) -> dict[str, tuple[int, int]]:
    """`node_id -> (component, rank)` from a kind's own `NEXT` subgraph.

    `NEXT` edges never cross an inventory (or, for `SittingDay`, never cross anything -- it is
    one global chain), so weakly-connected components recover exactly the groups that
    `axis._check_monotone` calls "the same inventory", without reading `inventory` at all.
    """
    nodes = [n for n, d in graph.nodes(data=True) if d.get("kind") == kind]
    sub = nx.DiGraph()
    sub.add_nodes_from(nodes)
    sub.add_edges_from(
        (u, v) for u, v, d in graph.edges(data=True)
        if d.get("kind") == NEXT and graph.nodes[u].get("kind") == kind
    )
    ranks: dict[str, tuple[int, int]] = {}
    for component_id, component in enumerate(nx.weakly_connected_components(sub)):
        for rank, node in enumerate(nx.topological_sort(sub.subgraph(component))):
            ranks[node] = (component_id, rank)
    return ranks


def monotone_map(graph: nx.DiGraph, from_kind: str, to_kind: str, edge_kind: str) -> MonotonicityReport:
    """Is `edge_kind` an order-preserving map from `from_kind`'s `NEXT` order to `to_kind`'s?

    Compared only within a shared `(from_component, to_component)` pair -- see the module
    docstring for why this one rule is enough for both `DATED_AS` and `PINNED_TO`/`LABELLED_AS`.
    """
    from_ranks = _next_ranks(graph, from_kind)
    to_ranks = _next_ranks(graph, to_kind)

    groups: dict[tuple[int, int], list[tuple[int, int, str, str]]] = defaultdict(list)
    for u, v, data in graph.edges(data=True):
        if data.get("kind") != edge_kind:
            continue
        if u not in from_ranks or v not in to_ranks:
            continue
        from_component, from_rank = from_ranks[u]
        to_component, to_rank = to_ranks[v]
        groups[(from_component, to_component)].append((from_rank, to_rank, u, v))

    checked = 0
    violations: list[tuple[str, str]] = []
    for items in groups.values():
        items.sort(key=lambda t: t[0])
        high = -1
        for _from_rank, to_rank, u, v in items:
            checked += 1
            if to_rank < high:
                violations.append((u, v))
            else:
                high = max(high, to_rank)
    return MonotonicityReport(edge_kind=edge_kind, checked=checked, violations=tuple(violations))


def add_observed_on(graph: nx.DiGraph) -> int:
    """`Session -> Scan`, observed in `resolution_archival_provenance`.

    One edge per session, to its OWN first observed scan -- the fact `reconcile_sequences.
    session_scans` keys on (`min(scan_ids)` per session, not per resolution). Per-resolution
    `HtrResolution -> Scan` is not built: no Stage-2 consumer reads it, and adding it unused
    would be exactly the kind of untested claim this spine exists to avoid making.
    """
    seen: dict[str, list[int]] = defaultdict(list)
    for row in load("resolution_archival_provenance"):
        if not row.get("found") or not row.get("scan_ids"):
            continue
        for scan in row["scan_ids"]:
            seen[row["session_id"]].append(int(str(scan).split("_")[-1]))

    added = 0
    for session_id, scans in seen.items():
        session_node = f"session:{session_id}"
        if session_node not in graph:
            continue  # sidelined or post-bar: not a Stage-1 node, so no edge from it
        first_scan, last_scan = min(scans), max(scans)
        inventory = graph.nodes[session_node]["obj"].inventory
        scan_node = Scan(inventory=inventory, scan_num=first_scan).node_id
        if scan_node not in graph:
            continue
        graph.add_edge(
            session_node, scan_node, key=OBSERVED_ON, kind=OBSERVED_ON,
            evidence=Evidence(
                channel="scan_ids", source="resolution_archival_provenance", observed=True,
                detail={"first_scan": first_scan, "last_scan": last_scan},
            ),
        )
        added += 1
    return added


def add_dated_as(graph: nx.DiGraph, *, with_bootstrap: bool = True) -> tuple[int, MonotonicityReport]:
    """`Scan -> SittingDay`, from each scan's own date-region heading.

    Monotonicity is checked, not assumed: `monotone_map` replaces `monotone_anchors`'s ad-hoc
    per-inventory sort-and-drop, reporting violations so a caller decides, rather than a
    first-match-wins rule silently dropping the rest.
    """
    first_scan_for: dict[tuple[str, str], int] = {}  # (inventory, date) -> min scan
    source_of: dict[tuple[str, int], str] = {}
    for inventory, scan, date, src in observations(with_bootstrap):
        key = (inventory, str(date))
        if key not in first_scan_for or scan < first_scan_for[key]:
            first_scan_for[key] = scan
        source_of[(inventory, scan)] = src

    added = 0
    for (inventory, date), scan in first_scan_for.items():
        scan_node = Scan(inventory=inventory, scan_num=scan).node_id
        day_node = SittingDay(date=date).node_id
        if scan_node not in graph or day_node not in graph:
            continue
        channel = source_of.get((inventory, scan), "strict")
        graph.add_edge(
            scan_node, day_node, key=DATED_AS, kind=DATED_AS,
            evidence=Evidence(
                channel=channel, source="session_region_text_1626_1630", observed=True,
                confidence=0.986 if channel == "bootstrap" else None,
            ),
        )
        added += 1

    report = monotone_map(graph, from_kind="Scan", to_kind="SittingDay", edge_kind=DATED_AS)
    return added, report


def add_pinned_and_labelled(graph: nx.DiGraph) -> tuple[int, int, MonotonicityReport, MonotonicityReport]:
    """`PINNED_TO` (concordance `resolved_session_id`) and `LABELLED_AS` (the axis's own date
    label), both `SittingDay -> Session`, both inferred. See the module docstring."""
    axis = RunningAxis.load()
    pinned = labelled = 0
    for session_id, span in axis.sessions.items():
        session_node = f"session:{session_id}"
        if session_node not in graph:
            continue
        for date in span.resolved_dates:
            if not in_scope(date):
                continue
            day_node = SittingDay(date=date).node_id
            if day_node not in graph:
                continue
            graph.add_edge(
                day_node, session_node, key=PINNED_TO, kind=PINNED_TO,
                evidence=Evidence(
                    channel="resolved_session_id", source="resolution_concordance_1626_1630",
                    observed=False,
                ),
            )
            pinned += 1
        for date in span.label_dates:
            if not in_scope(date):
                continue
            day_node = SittingDay(date=date).node_id
            if day_node not in graph:
                continue
            graph.add_edge(
                day_node, session_node, key=LABELLED_AS, kind=LABELLED_AS,
                evidence=Evidence(
                    channel="date_label", source="paragraph_axis_1626_1630", observed=False,
                ),
            )
            labelled += 1

    pinned_report = monotone_map(graph, from_kind="SittingDay", to_kind="Session", edge_kind=PINNED_TO)
    labelled_report = monotone_map(graph, from_kind="SittingDay", to_kind="Session", edge_kind=LABELLED_AS)
    return pinned, labelled, pinned_report, labelled_report


def build_correspondence(graph: nx.DiGraph | None = None, *, with_bootstrap: bool = True) -> nx.DiGraph:
    """The Stage-1 graph plus all cross-sequence edges. Mutates and returns `graph`."""
    if graph is None:
        graph = build()
    add_observed_on(graph)
    add_dated_as(graph, with_bootstrap=with_bootstrap)
    add_pinned_and_labelled(graph)
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--strict-only", action="store_true")
    args = parser.parse_args()

    graph = build()
    observed_on_n = add_observed_on(graph)
    dated_as_n, dated_report = add_dated_as(graph, with_bootstrap=not args.strict_only)
    pinned_n, labelled_n, pinned_report, labelled_report = add_pinned_and_labelled(graph)

    print(f"OBSERVED_ON: {observed_on_n:,} edges")
    print(f"DATED_AS:    {dated_as_n:,} edges  -- {dated_report}")
    print(f"PINNED_TO:   {pinned_n:,} edges  -- {pinned_report}")
    print(f"LABELLED_AS: {labelled_n:,} edges  -- {labelled_report}")
    if args.report:
        main_series_sessions = sum(
            1 for _n, d in graph.nodes(data=True)
            if d.get("kind") == "Session" and is_main_series(d["obj"].inventory)
        )
        print(f"\nmain-series sessions on the graph: {main_series_sessions:,}")


if __name__ == "__main__":
    main()

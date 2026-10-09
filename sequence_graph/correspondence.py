"""Cross-sequence edges, with evidence. Stage 2 of `plans/SEQUENCE_GRAPH_SPINE.md`.

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

**`ALIGNED_TO` IS built here, in two observed-vs-derived halves (user, 2026-10-09: "ONLY if
results are discarded explicitly they should not be written back" -- Stage 4's output does not
stay in-memory and get thrown away just because it hasn't been fitted yet):

    ALIGNED_TO (gold)    EnrichedResolution -> HtrResolution   observed=True   boundary_gold_sample
    ALIGNED_TO (solver)  EnrichedResolution -> HtrResolution   observed=False  sequence_graph.align

`add_aligned_to_gold` is a positive, hard fact per edge: a human read the page and confirmed the
correspondence (`scripts.separated_accuracy_eval.gold_start_paragraphs`, reused rather than
re-derived -- it already handles the general non-1:1 case `align.py`'s own bespoke gold parsing in
`run_bracket` explicitly declined to generalize). No confidence value, by the same convention as
every other `observed=True` edge in this module: hand annotation has no separately *measured*
error rate to carry, so none is invented.

`add_aligned_to_solver` is the DP's own derived output, `observed=False`, and **carries no
confidence either, but for the opposite reason** -- `align.CostModel` is explicitly unfitted
(its own docstring), so a numeric confidence would be a fabricated precision, not a missing one.
`detail` carries the move kind and the path's `total_cost` instead, so a reader can see exactly
what calculation the edge rests on rather than a bare, un-gradeable "derived."

**Found while testing this the same day: a `MultiDiGraph` silently overwrites a parallel edge
that reuses the same `(u, v, key)` triple** -- the exact `DiGraph`-edge-collision class Stage 2
already hit once (see `PINNED_TO`/`LABELLED_AS`). A first cut gave both halves the literal key
`ALIGNED_TO`, so writing a solver edge for a day that already had a gold edge on the same pair
silently replaced the hard fact with the derived one -- the single worst version of "discarding a
result" this module exists to prevent. Fixed: gold and solver halves key on
`f"{ALIGNED_TO}:gold"` / `f"{ALIGNED_TO}:solver"` respectively, so both can coexist as parallel
edges on the same `(u, v)` pair and `aligned_to_status`'s gold-takes-priority read is actually
reading two real edges, not one edge that happened to survive.

**The non-circularity rule (user, 2026-10-09): evidence must be cumulative, never a loop.**
`add_aligned_to_solver`'s edges must never be read back in as if they were ground truth for fitting
`CostModel` itself -- that is the same trap `tier1_anchor`-as-positives already sits in elsewhere
(diagnostic only, explicitly not used to fit anything). `gold_aligned_pairs` below is the one
sanctioned read path for calibration: it filters to `observed=True` and nothing else, so "which
edges are safe to fit on" is a property of the code, not a convention someone has to remember.

**Coverage, not just edges: `sequence_graph.consolidate.aligned_to_status` answers "what's still
missing"** (user, 2026-10-09) -- a closed three-way partition over every in-scope
`EnrichedResolution` (gold-verified / solver-derived-only / unaligned), `check_partition`-verified
like every other taxonomy in this package, so "how much of this is actually nailed down" is a
reportable number, never an impression.

**`MENTIONS` is not built here** -- it is a scoring input Stage 4 reads (the overlap tables), not
a correspondence fact this module asserts.

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
ALIGNED_TO = "ALIGNED_TO"


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


def add_aligned_to_gold(graph: nx.DiGraph) -> int:
    """`EnrichedResolution -> HtrResolution`, `observed=True`, from `boundary_gold_sample` --
    the only ground truth that exists. See the module docstring for why this reuses
    `gold_start_paragraphs` instead of a bespoke mapping, and carries no confidence value.

    Only resolutions gold actually locates get an edge. An unresolved slot stays unresolved --
    never coded as "absent" (a much stronger, separately-verified claim a few individual days
    carry in `docs/DECISIONS.md` prose but that has no structured dataset yet; not built here,
    flagged as a known gap) and never guessed at a default position.
    """
    from scripts.separated_accuracy_eval import gold_start_paragraphs

    from sequence_graph.align import day_paragraph_stream
    from sequence_graph.nodes import EnrichedResolution, HtrResolution

    added = 0
    for day in load("boundary_gold_sample")["days"]:
        date = day["date"]
        if not in_scope(date):
            continue
        stream = day_paragraph_stream(date)
        if not stream:
            continue
        starts = gold_start_paragraphs(day, day["k_e"])
        for index, position in enumerate(starts):
            if position is None or position >= len(stream):
                continue
            enriched_node = EnrichedResolution(date=date, index=index).node_id
            if enriched_node not in graph:
                continue
            flat_id = stream[position]
            htr_node = HtrResolution.from_flat_id(flat_id).node_id
            if htr_node not in graph:
                continue
            graph.add_edge(
                enriched_node, htr_node, key=f"{ALIGNED_TO}:gold", kind=ALIGNED_TO,
                evidence=Evidence(
                    channel="gold_annotation", source="boundary_gold_sample", observed=True,
                    detail={"paragraph_stream_index": position},
                ),
            )
            added += 1
    return added


def add_aligned_to_solver(
    graph: nx.DiGraph, dates: Sequence[str], *, cost: Any = None,
) -> int:
    """`EnrichedResolution -> HtrResolution`, `observed=False`, the DP's own derived output for
    each date in `dates` -- written back rather than discarded, per the module docstring's
    non-circularity rule: these edges exist to be read, never to be read back in as if they were
    ground truth for fitting the same `CostModel` that produced them (`gold_aligned_pairs` is the
    one sanctioned input for that).

    Only `MATCH` and `INSERTION_SPLIT` moves produce an edge -- both assert "this read item
    belongs to this ref item", just at different confidence a future fitted cost would price
    differently. `DELETION_GAP` (no HTR counterpart) and `SOFT_CLIP` (dropped margin content)
    correctly produce no edge: there is nothing to assert a correspondence to.

    **Scope limit, stated rather than implied away: `dates` is currently restricted to
    `boundary_gold_sample` days.** `n_ref`/`flat_ids` come from the gold day record, same as
    `align.run_bracket`, so this cannot yet run on the 19,000+ enriched resolutions with no gold
    entry at all -- which is most of the corpus and the actual point of Stage 4 eventually
    running past a handful of brackets. Pulling `flat_ids`/`n_ref` from production data
    (paragraph_axis / resolution_concordance) directly, independent of gold, is the real
    corpus-wide extension and is not done here.
    """
    from sequence_graph.align import (
        INSERTION_SPLIT,
        MATCH,
        CostModel,
        align_bracket,
        build_entity_overlap_scorer,
    )
    from sequence_graph.nodes import EnrichedResolution, HtrResolution

    cost = cost or CostModel()
    gold = load("boundary_gold_sample")
    gold_by_date = {day["date"]: day for day in gold["days"]}
    scorer = build_entity_overlap_scorer()

    added = 0
    for date in dates:
        day = gold_by_date.get(date)
        if day is None or not in_scope(date):
            continue
        flat_ids = sorted(day["flat_ids"], key=lambda fid: HtrResolution.from_flat_id(fid).resolution_num)
        n_ref, n_read = len(day["enriched_ids"]), len(flat_ids)
        if n_ref == 0 or n_read == 0:
            continue
        volgnrs = [f"{date}_{index}" for index in range(n_ref)]
        overlap_cache: dict[tuple[int, int], float] = {}

        def overlap(i: int, j: int, volgnrs=volgnrs, flat_ids=flat_ids) -> float:
            key = (i, j)
            if key not in overlap_cache:
                overlap_cache[key] = scorer(volgnrs[i], flat_ids[j])
            return overlap_cache[key]

        result = align_bracket(n_ref, n_read, overlap, cost)
        if result.abstained:
            continue
        for pair in result.pairs:
            if pair.kind not in (MATCH, INSERTION_SPLIT) or pair.ref_index is None or pair.read_index is None:
                continue
            enriched_node = EnrichedResolution(date=date, index=pair.ref_index).node_id
            htr_node = HtrResolution.from_flat_id(flat_ids[pair.read_index]).node_id
            if enriched_node not in graph or htr_node not in graph:
                continue
            graph.add_edge(
                enriched_node, htr_node, key=f"{ALIGNED_TO}:solver", kind=ALIGNED_TO,
                evidence=Evidence(
                    channel="dp_solver", source="sequence_graph.align", observed=False,
                    confidence=None,
                    detail={"move_kind": pair.kind, "step_cost": pair.cost,
                            "cost_model_fitted": False, "total_path_cost": result.total_cost},
                ),
            )
            added += 1
    return added


def gold_aligned_pairs(graph: nx.DiGraph) -> list[tuple[str, str]]:
    """The one sanctioned read path for anything that fits/calibrates against `ALIGNED_TO`:
    `(enriched_node_id, htr_node_id)` pairs with `observed=True` evidence only. Never includes a
    solver-derived edge, by construction -- see the module docstring's non-circularity rule."""
    return [
        (u, v) for u, v, data in graph.edges(data=True)
        if data.get("kind") == ALIGNED_TO and data["evidence"].observed
    ]


def build_correspondence(
    graph: nx.DiGraph | None = None, *, with_bootstrap: bool = True, solver_dates: Sequence[str] = (),
) -> nx.DiGraph:
    """The Stage-1 graph plus all cross-sequence edges. Mutates and returns `graph`.

    `solver_dates` is empty by default: running the unfitted DP corpus-wide is not something this
    builder does silently. Pass specific dates to also write back `ALIGNED_TO` (solver) edges for
    them (e.g. the days already tested in `notebooks/sequence_graph_exploration.ipynb`).
    """
    if graph is None:
        graph = build()
    add_observed_on(graph)
    add_dated_as(graph, with_bootstrap=with_bootstrap)
    add_pinned_and_labelled(graph)
    add_aligned_to_gold(graph)
    if solver_dates:
        add_aligned_to_solver(graph, solver_dates)
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

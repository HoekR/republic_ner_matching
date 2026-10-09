"""Build the three sequences as `NEXT`/`CONTAINS` graphs. Stage 1 -- no correspondence yet.

**Guards at construction, not downstream.** The scope bar (`scripts/corpus_scope.in_scope`) and
the secret-series sideline (`scripts/corpus_scope.is_sidelined`) are applied exactly where each
node is created, so a sidelined or post-bar identifier can never reach a node id. This mirrors the
project's own standing rule for the scope bar (`scripts/corpus_scope.py`'s own docstring: "a rule
that only lives in `plans/*.md` is a rule that gets broken") -- the guard lives in the one place
data enters the graph, not in a downstream filter that a later script could bypass.

**Sidelining is asymmetric between the physical/HTR side and the editorial side, deliberately.**
A `Session`/`HtrResolution`/`Paragraph` carries its own inventory in its identifier -- it *states*
provenance, so `is_sidelined` can test it directly and the sidelined ones are dropped before a
node object is ever built. A `SittingDay`/`EnrichedResolution` carries no inventory at all: the
enriched XML has no physical grounding (`Stgen.dtd` has no folio/page/scan/inventory element), so
an editorial node's relationship to the secret series can only be *inferred*, through a `PINNED_TO`
edge -- a Stage 2 fact, not a Stage 1 one. Filtering editorial nodes here by what they resolve to
would make the editorial sequence's own node count depend on the correspondence it is supposed to
be compared against, which is exactly the conflation the spine exists to stop. So **every in-scope
editorial node is built, regardless of what it does or does not resolve to** -- 1,594 `SittingDay`
nodes, 19,120 `EnrichedResolution` nodes, unconditionally.

**Sessions are built bottom-up, from surviving paragraphs, not top-down from `RunningAxis`.**
`RunningAxis.sessions`' own `paragraph_count` is not scope-bar-filtered (`running_axis` predates
`corpus_scope` and has no dependency on it), so a session straddling the bar would report its
full, uncut paragraph count. Building `Session`/`HtrResolution`/`Paragraph` nodes directly from
`paragraph_axis_1626_1630`, keeping only rows that pass both guards, sidesteps the straddling
question entirely: a session's node set is exactly its surviving children, and a session with zero
surviving children simply has no node at all.

Usage:
    uv run python -m sequence_graph.build --report
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Iterator

import networkx as nx

from data_io import load
from running_axis.stream import FlatIdError, parse_flat_id
from scripts.corpus_scope import in_scope, is_main_series, is_sidelined

from sequence_graph.nodes import (
    EnrichedResolution,
    HtrResolution,
    Paragraph,
    Scan,
    Session,
    SittingDay,
)

AXIS_DATASET = "paragraph_axis_1626_1630"
ENRICHED_DATASET = "enriched_resolutions_1626_1630"
INVENTORY_DATASET = "inventory_metadata"

NEXT = "NEXT"
CONTAINS = "CONTAINS"


def _axis_rows() -> Iterator[dict]:
    """In-scope, non-sidelined rows of the paragraph axis. The one gate for the HTR side."""
    for row in load(AXIS_DATASET):
        if row.get("record_type") == "meta" or not row.get("flat_id"):
            continue
        if not in_scope(row.get("date")):
            continue
        if is_sidelined(row["flat_id"]):
            continue
        yield row


def build_physical_sequence(graph: nx.DiGraph) -> None:
    """One `Scan` chain per main-series inventory, `scan_num` 1..`num_scans`.

    Scan numbering is contiguous and complete by construction (`inventory_metadata.num_scans`;
    the scan track's own standing note: a digitisation gap is not observable from this data), so
    there is no filtering question here beyond which inventories are main-series at all.
    """
    for row in load(INVENTORY_DATASET):
        inventory = str(row.get("inventory_num"))
        # `inventory_metadata` holds 674 distinct inventories project-wide, almost all unrelated
        # to this corpus. `not is_sidelined(inventory)` is true of every one of them -- it tests
        # "not 4562/4861", not "is one of 3185-3189" -- so the positive test (`is_main_series`) is
        # required here, not its absence from the sidelined set.
        if not is_main_series(inventory) or row.get("num_scans") is None:
            continue
        # Post-bar inventories (none in the main series) would be dropped the same way; the
        # scan sequence has no date of its own to test against `in_scope`, only an inventory.
        num_scans = int(row["num_scans"])
        prev: Scan | None = None
        for scan_num in range(1, num_scans + 1):
            scan = Scan(inventory=inventory, scan_num=scan_num)
            graph.add_node(scan.node_id, kind="Scan", obj=scan)
            if prev is not None:
                graph.add_edge(prev.node_id, scan.node_id, key=NEXT, kind=NEXT)
            prev = scan


def build_htr_sequence(graph: nx.DiGraph) -> None:
    """`Session -> HtrResolution -> Paragraph`, each level `NEXT`-ordered, built bottom-up."""
    # session_id -> {resolution_num -> flat_id}; flat_id -> [row, ...] in para_index order.
    sessions: dict[str, dict[int, str]] = defaultdict(dict)
    paragraphs_by_flat: dict[str, list[dict]] = defaultdict(list)

    for row in _axis_rows():
        flat_id = row["flat_id"]
        try:
            inventory, session_num, resolution_num = parse_flat_id(flat_id)
        except FlatIdError:
            continue
        session_id = f"session-{inventory}-num-{session_num}"
        sessions[session_id][resolution_num] = flat_id
        paragraphs_by_flat[flat_id].append(row)

    for session_id, by_resolution_num in sessions.items():
        inventory, session_num, _ = parse_flat_id(f"{session_id}-resolution-0")
        session = Session(session_id=session_id, inventory=inventory, session_num=session_num)
        graph.add_node(session.node_id, kind="Session", obj=session)

        ordered_flat_ids = [by_resolution_num[n] for n in sorted(by_resolution_num)]
        prev_res: HtrResolution | None = None
        for flat_id in ordered_flat_ids:
            res = HtrResolution.from_flat_id(flat_id)
            graph.add_node(res.node_id, kind="HtrResolution", obj=res)
            graph.add_edge(session.node_id, res.node_id, key=CONTAINS, kind=CONTAINS)
            if prev_res is not None:
                graph.add_edge(prev_res.node_id, res.node_id, key=NEXT, kind=NEXT)
            prev_res = res

            paras = sorted(paragraphs_by_flat[flat_id], key=lambda r: r["para_index"])
            prev_para: Paragraph | None = None
            for para_row in paras:
                para = Paragraph(
                    axis_id=para_row["axis_id"],
                    flat_id=flat_id,
                    para_index=para_row["para_index"],
                )
                graph.add_node(para.node_id, kind="Paragraph", obj=para)
                graph.add_edge(res.node_id, para.node_id, key=CONTAINS, kind=CONTAINS)
                if prev_para is not None:
                    graph.add_edge(prev_para.node_id, para.node_id, key=NEXT, kind=NEXT)
                prev_para = para

    # Sessions NEXT-ordered within their own inventory, by session_num -- a different order from
    # the paragraph-insertion order above, so built as a second pass over the finished node set.
    by_inventory: dict[str, list[Session]] = defaultdict(list)
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") == "Session":
            by_inventory[data["obj"].inventory].append(data["obj"])
    for inventory, spans in by_inventory.items():
        ordered = sorted(spans, key=lambda s: s.session_num)
        for a, b in zip(ordered, ordered[1:]):
            graph.add_edge(a.node_id, b.node_id, key=NEXT, kind=NEXT)


def build_editorial_sequence(graph: nx.DiGraph) -> None:
    """`SittingDay -> EnrichedResolution`, both `NEXT`-ordered. Unfiltered by sidelining.

    See the module docstring: an enriched resolution states no inventory of its own, so nothing
    here can be sidelined by the ledger rule -- only the scope bar applies.
    """
    by_date: dict[str, list[int]] = defaultdict(list)
    for row in load(ENRICHED_DATASET):
        date = str(row.get("date"))[:10]
        if not date[:1].isdigit() or not in_scope(date):
            continue
        index = row.get("resolution_index")
        if index is None:
            continue
        by_date[date].append(int(index))

    # A date can be claimed by a session's own label (the axis's `date_label`) or by the
    # concordance's resolved_session_id while carrying ZERO rows in the enriched table at all --
    # measured: exactly one such date corpus-wide (1627-09-14). Dropping it would silently
    # discard a claim a real session makes (CLAUDE.md's standing rule against exactly that), so
    # it gets a SittingDay node with no EnrichedResolution children, rather than no node at all.
    from running_axis.axis import RunningAxis  # local: avoids a package import cycle

    axis = RunningAxis.load()
    for session_id, span in axis.sessions.items():
        if is_sidelined(session_id):
            continue
        for date in (*span.label_dates, *span.resolved_dates):
            if in_scope(date) and date not in by_date:
                by_date[date] = []

    prev_day: SittingDay | None = None
    for date in sorted(by_date):
        day = SittingDay(date=date)
        graph.add_node(day.node_id, kind="SittingDay", obj=day)
        if prev_day is not None:
            graph.add_edge(prev_day.node_id, day.node_id, key=NEXT, kind=NEXT)
        prev_day = day

        prev_res: EnrichedResolution | None = None
        for index in sorted(by_date[date]):
            res = EnrichedResolution(date=date, index=index)
            graph.add_node(res.node_id, kind="EnrichedResolution", obj=res)
            graph.add_edge(day.node_id, res.node_id, key=CONTAINS, kind=CONTAINS)
            if prev_res is not None:
                graph.add_edge(prev_res.node_id, res.node_id, key=NEXT, kind=NEXT)
            prev_res = res


def build() -> nx.DiGraph:
    """The three sequences, nodes and `NEXT`/`CONTAINS` only. No correspondence (Stage 2)."""
    graph = nx.MultiDiGraph()  # PINNED_TO/LABELLED_AS (Stage 2) can share an (day, session) pair
    build_physical_sequence(graph)
    build_htr_sequence(graph)
    build_editorial_sequence(graph)
    return graph


def counts_by_kind(graph: nx.DiGraph) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for _node_id, data in graph.nodes(data=True):
        out[data["kind"]] += 1
    return dict(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print node/edge counts by kind")
    args = parser.parse_args()

    graph = build()
    counts = counts_by_kind(graph)
    print(f"nodes: {graph.number_of_nodes():,}  edges: {graph.number_of_edges():,}")
    if args.report:
        for kind, n in sorted(counts.items()):
            print(f"  {kind:<18}{n:>8,}")
        next_edges = sum(1 for *_e, d in graph.edges(data=True) if d.get("kind") == NEXT)
        contains_edges = sum(1 for *_e, d in graph.edges(data=True) if d.get("kind") == CONTAINS)
        print(f"  {'NEXT edges':<18}{next_edges:>8,}")
        print(f"  {'CONTAINS edges':<18}{contains_edges:>8,}")


if __name__ == "__main__":
    main()

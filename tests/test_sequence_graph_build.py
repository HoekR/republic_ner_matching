"""Stage 1 gate: three sequences, `NEXT`/`CONTAINS` only, no correspondence.

`plans/SEQUENCE_GRAPH_SPINE.md` Stage 1: "each sequence is one totally-ordered
chain per inventory/day with no forks; counts match the datasets exactly... zero sidelined or
post-bar nodes." These are functional tests against a live build (nothing is persisted until
Stage 3), not synthetic unit tests, because the gate is a property of the real corpus counts, and
a synthetic graph could satisfy "no forks" trivially without proving anything about the data.

The target counts were corrected 2026-10-09 (the plan's first draft cited the raw, pre-sideline
axis totals): `is_sidelined`/`is_main_series` apply to the physical and HTR sequences, which state
their own inventory; the editorial sequence states none, so it is built unfiltered by sidelining
(scope bar only) -- see `sequence_graph/build.py`'s module docstring.
"""

from __future__ import annotations

import networkx as nx
import pytest

from scripts.corpus_scope import in_scope, is_sidelined
from sequence_graph.build import CONTAINS, NEXT, build, counts_by_kind

EXPECTED_COUNTS = {
    "Scan": 3195,  # sum of num_scans over 3185-3189 (inventory_metadata)
    "Session": 1034,  # sessions with >=1 surviving in-scope, non-sidelined paragraph
    "HtrResolution": 11273,  # flat_ids, in-scope + main-series
    "Paragraph": 18946,  # paragraph_axis rows, in-scope + main-series
    "SittingDay": 1595,  # 1,594 in-scope enriched dates + 1 phantom label date with 0 k_e
    "EnrichedResolution": 19120,  # all in-scope k_e (editorial: unfiltered by sidelining)
}


@pytest.fixture(scope="module")
def graph() -> nx.DiGraph:
    return build()


def test_node_counts_match_the_datasets_exactly(graph):
    counts = counts_by_kind(graph)
    assert counts == EXPECTED_COUNTS


def test_no_forks_every_node_has_at_most_one_next_neighbour_each_way(graph):
    out_degree: dict[str, int] = {}
    in_degree: dict[str, int] = {}
    for u, v, data in graph.edges(data=True):
        if data.get("kind") != NEXT:
            continue
        out_degree[u] = out_degree.get(u, 0) + 1
        in_degree[v] = in_degree.get(v, 0) + 1
    assert all(c <= 1 for c in out_degree.values())
    assert all(c <= 1 for c in in_degree.values())


def test_next_chains_are_acyclic(graph):
    next_only = nx.DiGraph(
        (u, v) for u, v, data in graph.edges(data=True) if data.get("kind") == NEXT
    )
    assert nx.is_directed_acyclic_graph(next_only)


def test_every_contains_child_has_exactly_one_parent(graph):
    parent_count: dict[str, int] = {}
    for _u, v, data in graph.edges(data=True):
        if data.get("kind") != CONTAINS:
            continue
        parent_count[v] = parent_count.get(v, 0) + 1
    assert all(c == 1 for c in parent_count.values())


def test_zero_sidelined_identifiers_reached_a_node(graph):
    hits = []
    for node_id, data in graph.nodes(data=True):
        obj = data["obj"]
        for field in ("session_id", "flat_id", "inventory"):
            value = getattr(obj, field, None)
            if value is not None and is_sidelined(value):
                hits.append((node_id, field, value))
    assert not hits, hits[:5]


def test_zero_out_of_scope_dates_reached_a_node(graph):
    hits = []
    for node_id, data in graph.nodes(data=True):
        date = getattr(data["obj"], "date", None)
        if date is not None and not in_scope(date):
            hits.append((node_id, date))
    assert not hits, hits[:5]


def test_a_label_date_with_zero_enriched_rows_still_gets_a_sitting_day(graph):
    """Found while building Stage 2's gate, not anticipated here: `1627-09-14` is claimed by a
    session's own axis label (and only that -- never the enriched table) with ZERO rows in
    `enriched_resolutions_1626_1630`. Dropping it would silently discard a claim a real session
    makes; it gets a `SittingDay` node with no `EnrichedResolution` children instead."""
    assert "day:1627-09-14" in graph
    children = [v for u, v, d in graph.out_edges("day:1627-09-14", data=True)
                if u == "day:1627-09-14" and d.get("kind") == CONTAINS]
    assert children == []


def test_editorial_sequence_is_unfiltered_by_sidelining():
    """Decision 1 (user, 2026-10-08): sideline by LEDGER. An enriched resolution states no
    inventory, so the 398 k_e on sidelined-resolved dates must still appear as nodes here --
    only the (Stage 2) PINNED_TO edge to them is absent, not the editorial node itself."""
    counts = counts_by_kind(build())
    assert counts["EnrichedResolution"] == 19120  # not 19120 - 398 = 18722


def test_session_chain_is_ordered_by_session_num_not_insertion_order(graph):
    """Sessions are built bottom-up from paragraphs (insertion order is whatever dict iteration
    gives), then NEXT-ordered by session_num in a second pass -- confirm the second pass worked."""
    sessions = [
        data["obj"]
        for _n, data in graph.nodes(data=True)
        if data.get("kind") == "Session" and data["obj"].inventory == "3185"
    ]
    sessions.sort(key=lambda s: s.session_num)
    for a, b in zip(sessions, sessions[1:]):
        # MultiDiGraph: edges between one pair are keyed by kind, so [u][v] is a dict of keys.
        assert graph.has_edge(a.node_id, b.node_id, key=NEXT)
        assert graph[a.node_id][b.node_id][NEXT]["kind"] == NEXT

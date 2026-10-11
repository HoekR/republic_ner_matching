"""Persist the full `sequence_graph` to disk -- a saved artifact, not something rebuilt from
source datasets on every single run.

**User, 2026-10-09: "is the graph saved to disk?"** No, until now -- every script called
`build()` + the `add_*` functions fresh, every time, discarding the result when the process
exited. **"AND WORK FROM AND ON THE SAVED GRAPH FROM NOW ON."** `load_graph()` is now the one
entry point `query.py`/`fit_cost.py`/`position_prior.py` use; `save_graph()` is the one place that
calls `build_full_graph()` and writes it out. Round-trip discipline matches Stage 3's
`Consolidation.to_records()`/`from_records()` exactly, generalized to the whole graph: a graph
rebuilt from records must equal the live one, tested, not assumed.

**Two registered datasets**, `sequence_graph_nodes` / `sequence_graph_edges` (`data_manifest.toml`).
A node record is `{node_id, kind, **the node's own dataclass fields}`; an edge record is
`{source, target, key, kind, evidence}`, `evidence` `None` for `NEXT`/`CONTAINS` (they carry none)
and the full `Evidence` dict otherwise. `key` is saved and restored exactly, not re-derived from
`kind` -- `ALIGNED_TO` is the one edge kind where several keys (`:gold`/`:legacy`/`:solver`) can
coexist on the same `(u, v)` pair, and collapsing them back to one key on reload would silently
merge three different evidence sources into one, the same class of bug the gold/solver key
collision already was.

**"For a risky operation you can make a new copy... measure improvement... save the results to a
log" (user, 2026-10-09).** `save_graph()` computes `aligned_to_status` before writing (on whatever
was previously saved, if anything) and after (on the new build), and appends both to
`sequence_graph_aligned_to_coverage_log` -- so a rebuild's actual effect is a logged number, not
an unverified claim, before the new graph becomes canonical (overwriting the saved one, not
living alongside it as a permanent fork).

Usage:
    uv run python -m sequence_graph.persist --build          # rebuild, log the comparison, save
    uv run python -m sequence_graph.persist --build --solver-dates 1629-03-02 1626-11-16
    uv run python -m sequence_graph.persist --summary         # load the saved graph, print counts
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone

import networkx as nx

from data_io import load, save_semi_structured

from sequence_graph.build import build
from sequence_graph.correspondence import (
    ALIGNED_TO,
    Evidence,
    add_aligned_to_gold,
    add_aligned_to_legacy_concordance,
    add_aligned_to_solver,
    add_dated_as,
    add_observed_on,
    add_pinned_and_labelled,
)
from sequence_graph.nodes import (
    EnrichedResolution,
    Entity,
    HtrResolution,
    Paragraph,
    Scan,
    Session,
    SittingDay,
)

NODE_CLASSES = {
    "Scan": Scan,
    "Session": Session,
    "HtrResolution": HtrResolution,
    "Paragraph": Paragraph,
    "SittingDay": SittingDay,
    "EnrichedResolution": EnrichedResolution,
    "Entity": Entity,
}


def build_full_graph(*, with_bootstrap: bool = True, solver_dates: Sequence[str] = ()) -> nx.MultiDiGraph:
    """Everything this project currently knows how to put on the graph: the three sequences,
    all four cross-sequence edges, and `ALIGNED_TO`'s three evidence sources (gold -- both
    samples, legacy concordance, and the solver for whichever dates are passed). Still not
    corpus-wide for the solver (see `add_aligned_to_solver`'s own scope-limit note)."""
    graph = build()
    add_observed_on(graph)
    add_dated_as(graph, with_bootstrap=with_bootstrap)
    add_pinned_and_labelled(graph)
    add_aligned_to_gold(graph)
    add_aligned_to_legacy_concordance(graph)
    if solver_dates:
        add_aligned_to_solver(graph, solver_dates)
    return graph


def node_records(graph: nx.MultiDiGraph) -> list[dict]:
    records = []
    for node_id, data in graph.nodes(data=True):
        obj = data["obj"]
        records.append({"node_id": node_id, "kind": data["kind"], **asdict(obj)})
    return records


def edge_records(graph: nx.MultiDiGraph) -> list[dict]:
    records = []
    for u, v, key, data in graph.edges(keys=True, data=True):
        evidence = data.get("evidence")
        records.append({
            "source": u, "target": v, "key": key, "kind": data["kind"],
            "evidence": asdict(evidence) if evidence is not None else None,
        })
    return records


def graph_from_records(nodes: list[dict], edges: list[dict]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for row in nodes:
        kind = row["kind"]
        cls = NODE_CLASSES[kind]
        fields = {k: v for k, v in row.items() if k not in ("node_id", "kind")}
        graph.add_node(row["node_id"], kind=kind, obj=cls(**fields))
    for row in edges:
        kwargs = {"key": row["key"], "kind": row["kind"]}
        if row.get("evidence") is not None:
            kwargs["evidence"] = Evidence(**row["evidence"])
        graph.add_edge(row["source"], row["target"], **kwargs)
    return graph


def load_graph() -> nx.MultiDiGraph:
    """The one entry point every `sequence_graph` consumer should use from now on -- reads the
    saved graph, never rebuilds it. Raises `FileNotFoundError` if `save_graph()` has not run yet."""
    nodes = load("sequence_graph_nodes")
    edges = load("sequence_graph_edges")
    return graph_from_records(nodes, edges)


def _coverage_counts(graph: nx.MultiDiGraph) -> dict[str, int]:
    from sequence_graph.consolidate import aligned_to_status
    return {name: tally.value for name, tally in aligned_to_status(graph).items()}


def _log_coverage_and_write(graph: nx.MultiDiGraph, *, before: dict[str, int] | None) -> dict:
    """Shared write path: coverage log + nodes/edges. Used by full rebuild and in-place push."""
    after = _coverage_counts(graph)
    timestamp = datetime.now(timezone.utc).isoformat()
    log_rows = [
        {
            "timestamp": timestamp, "bucket": name,
            "before": (before or {}).get(name), "after": after[name],
        }
        for name in after
    ]
    save_semi_structured(
        load("sequence_graph_aligned_to_coverage_log") + log_rows
        if _dataset_exists("sequence_graph_aligned_to_coverage_log") else log_rows,
        logical_name="sequence_graph_aligned_to_coverage_log",
        script="sequence_graph.persist",
    )
    save_semi_structured(
        node_records(graph), logical_name="sequence_graph_nodes", script="sequence_graph.persist",
    )
    save_semi_structured(
        edge_records(graph), logical_name="sequence_graph_edges", script="sequence_graph.persist",
    )
    return {"before": before, "after": after}


def save_loaded_graph(graph: nx.MultiDiGraph) -> dict:
    """Persist an already-mutated in-memory graph (e.g. after pushing solver MATCH edges).

    Does **not** rebuild from sources. Logs ALIGNED_TO coverage before→after against the
    previously saved graph, then overwrites `sequence_graph_nodes` / `sequence_graph_edges`.
    """
    try:
        before = _coverage_counts(load_graph())
    except FileNotFoundError:
        before = None
    return _log_coverage_and_write(graph, before=before)


def save_graph(*, with_bootstrap: bool = True, solver_dates: Sequence[str] = ()) -> dict:
    """Build, compare against whatever was previously saved (if anything), log the comparison,
    then save -- "for a risky operation you can make a new copy... eventually it should be
    plowed back into the graph" (user): the new build becomes the one canonical saved graph, not
    a permanent fork, but only after its effect is measured and logged.
    """
    try:
        before_graph = load_graph()
        before = _coverage_counts(before_graph)
    except FileNotFoundError:
        before = None

    graph = build_full_graph(with_bootstrap=with_bootstrap, solver_dates=solver_dates)
    return _log_coverage_and_write(graph, before=before)


def _dataset_exists(logical_name: str) -> bool:
    from data_io import resolve
    return resolve(logical_name).exists()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true")
    group.add_argument("--summary", action="store_true")
    parser.add_argument("--strict-only", action="store_true")
    parser.add_argument("--solver-dates", nargs="*", default=())
    args = parser.parse_args()

    if args.build:
        result = save_graph(with_bootstrap=not args.strict_only, solver_dates=args.solver_dates)
        print("ALIGNED_TO coverage, before -> after:")
        for name, after_value in result["after"].items():
            before_value = (result["before"] or {}).get(name)
            print(f"  {name:<25}{str(before_value):>8} -> {after_value}")
        print("\nsaved sequence_graph_nodes, sequence_graph_edges, "
              "sequence_graph_aligned_to_coverage_log")
    else:
        graph = load_graph()
        kinds: dict[str, int] = {}
        for _n, data in graph.nodes(data=True):
            kinds[data["kind"]] = kinds.get(data["kind"], 0) + 1
        print("nodes:", kinds)
        print("edges:", graph.number_of_edges())
        for name, value in _coverage_counts(graph).items():
            print(f"  {name:<25}{value}")


if __name__ == "__main__":
    main()

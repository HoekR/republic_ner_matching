"""`uv run python -m sequence_graph.query` -- "what do we actually know here", one command.

The interface the plan names explicitly: "refer to at all times" needs a command, not a document.
Answers for a session, a date or a scan -- the three things someone actually has in hand when
asking a question about this corpus. For a date, prints **both paths**: the inferred one
(`SittingDay -[PINNED_TO/LABELLED_AS]-> Session`) and, for whatever session that names, the
observed one (`Session -[OBSERVED_ON]-> Scan -[DATED_AS]-> SittingDay`, walked back through the
anchor bracket) -- so agreement or disagreement between them is read off the output directly,
never asserted in prose.

Usage:
    uv run python -m sequence_graph.query --session session-3187-num-155
    uv run python -m sequence_graph.query --date 1629-05-18
    uv run python -m sequence_graph.query --scan 3187 320
"""

from __future__ import annotations

import argparse

from scripts.build_unplaced_date_review import iiif_url

from sequence_graph.build import build
from sequence_graph.classify import SessionVerdict, classify
from sequence_graph.consolidate import correspondence_class
from sequence_graph.correspondence import (
    DATED_AS,
    LABELLED_AS,
    OBSERVED_ON,
    PINNED_TO,
    add_dated_as,
    add_observed_on,
    add_pinned_and_labelled,
    traversal_is_inferred,
)
from sequence_graph.nodes import Scan, SittingDay


def _load():
    graph = build()
    add_observed_on(graph)
    add_dated_as(graph)
    add_pinned_and_labelled(graph)
    verdicts = {v.session_id: v for v in classify(graph)}
    return graph, verdicts


def _print_verdict(v: SessionVerdict | None) -> None:
    if v is None:
        print("  no verdict: not a main-series session with a surviving paragraph")
        return
    print(f"  verdict:              {v.verdict}")
    print(f"  problem_type:         {v.problem_type}")
    print(f"  correspondence_class: {correspondence_class(v)}")
    print(f"  implied window:       {v.implied_lo} .. {v.implied_hi} "
          f"({v.implied_window_days} days)" if v.implied_lo else "  implied window:       none")
    if v.offset_days is not None:
        print(f"  offset:               {v.offset_days:+d} days")
    print(f"  paragraphs:           {v.paragraph_count}")


def query_session(session_id: str) -> None:
    graph, verdicts = _load()
    node = f"session:{session_id}"
    print(f"SESSION {session_id}")
    if node not in graph:
        print("  not on the graph: sidelined, post-bar, or has no surviving paragraph")
        return
    inventory = graph.nodes[node]["obj"].inventory

    obs = [v for _u, v, d in graph.out_edges(node, data=True) if d.get("kind") == OBSERVED_ON]
    print(f"  OBSERVED path: {'Session -> Scan' if obs else '(no observed scan)'}")
    for scan_node in obs:
        scan = graph.nodes[scan_node]["obj"]
        print(f"    observed on {scan_node}")
        print(f"    image: {iiif_url(f'NL-HaNA_1.01.02_{inventory}_{scan.scan_num:04d}') or '(n/a)'}")

    resolved = [u for u, _v, d in graph.in_edges(node, data=True) if d.get("kind") == PINNED_TO]
    labelled = [u for u, _v, d in graph.in_edges(node, data=True) if d.get("kind") == LABELLED_AS]
    print(f"  INFERRED path: SittingDay -> Session")
    print(f"    PINNED_TO (concordance):  {sorted(graph.nodes[u]['obj'].date for u in resolved) or '(none)'}")
    print(f"    LABELLED_AS (axis label): {sorted(graph.nodes[u]['obj'].date for u in labelled) or '(none)'}")
    print(f"    is this traversal inferred? {traversal_is_inferred([PINNED_TO])}")

    _print_verdict(verdicts.get(session_id))


def query_date(date: str) -> None:
    graph, verdicts = _load()
    node = f"day:{date}"
    print(f"DATE {date}")
    if node not in graph:
        print("  not on the graph: out of scope")
        return

    inferred = [
        (v, graph.nodes[v]["obj"].session_id, d.get("kind"))
        for _u, v, d in graph.out_edges(node, data=True)
        if d.get("kind") in (PINNED_TO, LABELLED_AS)
    ]
    print(f"  INFERRED path (SittingDay -> Session), "
          f"inferred={traversal_is_inferred([PINNED_TO]) if inferred else None}:")
    if not inferred:
        print("    (nothing: no session resolves to or labels this date)")
    for _session_node, session_id, kind in inferred:
        print(f"    {kind}: {session_id}")
        _print_verdict(verdicts.get(session_id))
        print()

    print("  OBSERVED path (for each session the inferred path named, Session -> Scan -> "
          "SittingDay via that session's own anchor bracket):")
    seen = {session_id for _s, session_id, _k in inferred}
    for session_id in seen:
        session_node = f"session:{session_id}"
        obs = [v for _u, v, d in graph.out_edges(session_node, data=True)
               if d.get("kind") == OBSERVED_ON]
        if not obs:
            print(f"    {session_id}: no observed scan")
            continue
        scan_node = obs[0]
        dated = [v for _u, v, d in graph.out_edges(scan_node, data=True) if d.get("kind") == DATED_AS]
        print(f"    {session_id} observed on {scan_node} "
              f"-> dated as {[graph.nodes[v]['obj'].date for v in dated] or '(no direct heading)'}")


def query_scan(inventory: str, scan_num: int) -> None:
    node = Scan(inventory=inventory, scan_num=scan_num).node_id
    graph, _verdicts = _load()
    print(f"SCAN {inventory}:{scan_num}")
    if node not in graph:
        print("  not on the graph: not a main-series inventory or scan_num out of range")
        return
    dated = [v for _u, v, d in graph.out_edges(node, data=True) if d.get("kind") == DATED_AS]
    print(f"  DATED_AS: {[graph.nodes[v]['obj'].date for v in dated] or '(no heading parsed)'}")
    sessions = [u for u, _v, d in graph.in_edges(node, data=True) if d.get("kind") == OBSERVED_ON]
    print(f"  OBSERVED_ON (sessions starting here): "
          f"{[graph.nodes[u]['obj'].session_id for u in sessions] or '(none)'}")
    print(f"  image: {iiif_url(f'NL-HaNA_1.01.02_{inventory}_{scan_num:04d}') or '(n/a)'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session")
    group.add_argument("--date")
    group.add_argument("--scan", nargs=2, metavar=("INVENTORY", "SCAN_NUM"))
    args = parser.parse_args()

    if args.session:
        query_session(args.session)
    elif args.date:
        query_date(args.date)
    else:
        query_scan(args.scan[0], int(args.scan[1]))


if __name__ == "__main__":
    main()

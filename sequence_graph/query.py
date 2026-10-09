"""`uv run python -m sequence_graph.query` -- "what do we actually know here", one command.

The interface the plan names explicitly: "refer to at all times" needs a command, not a document.
Answers for a session, a date, a scan, or a date range -- the things someone actually has in hand
when asking a question about this corpus. For a date, prints **both paths**: the inferred one
(`SittingDay -[PINNED_TO/LABELLED_AS]-> Session`) and, for whatever session that names, the
observed one (`Session -[OBSERVED_ON]-> Scan -[DATED_AS]-> SittingDay`, walked back through the
anchor bracket) -- so agreement or disagreement between them is read off the output directly,
never asserted in prose.

`query_range` (Step 4.6 of `plans/SEQUENCE_GRAPH_SPINE.md`, user request) is the week/month
overview: every date grouped by week, each with its `PINNED_TO`/`LABELLED_AS` status and
`ALIGNED_TO` coverage, and a per-session drill-down to the individual HTR resolution -- "what do
we actually know, over a stretch of time" rather than one thing at a time. Every function here is
plain and importable, so a notebook calls the same code the CLI does (user: "eventually should
work in a notebook as well").

Usage:
    uv run python -m sequence_graph.query --session session-3187-num-155
    uv run python -m sequence_graph.query --date 1629-05-18
    uv run python -m sequence_graph.query --scan 3187 320
    uv run python -m sequence_graph.query --range 1629-03-01 1629-03-31 --solver-dates 1629-03-02
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Sequence

import pandas as pd

from data_io import load
from scripts.build_unplaced_date_review import iiif_url

from sequence_graph.align import DELETION_GAP, INSERTION_SPLIT, MATCH, SOFT_CLIP, run_bracket
from sequence_graph.build import CONTAINS, build
from sequence_graph.classify import SessionVerdict, classify
from sequence_graph.consolidate import correspondence_class, node_aligned_bucket
from sequence_graph.correspondence import (
    ALIGNED_TO,
    DATED_AS,
    LABELLED_AS,
    OBSERVED_ON,
    PINNED_TO,
    add_aligned_to_gold,
    add_aligned_to_solver,
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


def _load_for_range(solver_dates: Sequence[str]):
    """Like `_load`, plus `ALIGNED_TO` -- gold always (cheap, from `boundary_gold_sample`), the
    solver only for `solver_dates` (expensive, and restricted to gold days -- see
    `add_aligned_to_solver`'s own docstring for the scope limit)."""
    graph, verdicts = _load()
    add_aligned_to_gold(graph)
    if solver_dates:
        add_aligned_to_solver(graph, solver_dates)
    return graph, verdicts


def _week_start(date: str) -> str:
    period = pd.Period(date, freq="D")
    return str(period - period.dayofweek)  # Monday of that date's ISO week


def _dates_in_range(graph, start: str, end: str) -> list[str]:
    lo, hi = pd.Period(start, freq="D"), pd.Period(end, freq="D")
    return sorted(
        data["obj"].date for _node, data in graph.nodes(data=True)
        if data.get("kind") == "SittingDay" and lo <= pd.Period(data["obj"].date, freq="D") <= hi
    )


def _date_sessions(graph, date: str) -> list[tuple[str, str, str]]:
    """`(session_node, session_id, edge_kind)` for every PINNED_TO/LABELLED_AS this date carries."""
    node = SittingDay(date=date).node_id
    return [
        (v, graph.nodes[v]["obj"].session_id, d.get("kind"))
        for _u, v, d in graph.out_edges(node, data=True)
        if d.get("kind") in (PINNED_TO, LABELLED_AS)
    ]


def _date_aligned_summary(graph, date: str) -> tuple[Counter, int]:
    """`ALIGNED_TO` coverage for this date's own `EnrichedResolution` children -- the per-date
    slice of `consolidate.aligned_to_status`, same classifier (`node_aligned_bucket`), so a date's
    own number and the corpus-wide number are never read two different ways."""
    day_node = SittingDay(date=date).node_id
    children = [v for _u, v, d in graph.out_edges(day_node, data=True) if d.get("kind") == CONTAINS]
    return Counter(node_aligned_bucket(graph, c) for c in children), len(children)


def _session_resolution_lines(graph, session_id: str, date: str, attempted: bool) -> list[str]:
    """One line per HTR resolution in this session: a clean correspondence (gold or solver,
    tagged), a proposed cut from the solver's own move trace on an unresolved stretch (only where
    `attempted`), or "not yet attempted" -- never a guess, never silence.

    `attempted` is the caller's own bookkeeping (did `_load_for_range`'s `solver_dates` include
    this date), not something read off the graph -- `DELETION_GAP`/`SOFT_CLIP` moves are
    deliberately not persisted as graph facts yet (Step 4.5's stated, deferred design question),
    so reading the graph alone cannot distinguish "not tried" from "tried, found nothing": this
    function reruns `align_bracket` live for an attempted date instead, to show that detail.
    """
    session_node = f"session:{session_id}"
    htr_nodes = sorted(
        (v for _u, v, d in graph.out_edges(session_node, data=True) if d.get("kind") == CONTAINS),
        key=lambda n: graph.nodes[n]["obj"].resolution_num,
    )
    if not htr_nodes:
        return ["(no HTR resolutions under this session)"]

    move_by_flat_id: dict[str, tuple[str, int | None]] = {}
    bracket_abstained = False
    if attempted:
        try:
            report = run_bracket(date)
            bracket_abstained = report["abstained"]
            for kind, ref_index, read_index in report["moves"]:
                if read_index is not None:
                    move_by_flat_id[report["flat_ids"][read_index]] = (kind, ref_index)
        except (ValueError, KeyError):
            pass  # date not in boundary_gold_sample, or gold couldn't place anything -- stays empty

    lines: list[str] = []
    for htr_node in htr_nodes:
        flat_id = graph.nodes[htr_node]["obj"].flat_id
        gold_targets = [
            u for u, _v, d in graph.in_edges(htr_node, data=True)
            if d.get("kind") == ALIGNED_TO and d["evidence"].observed
        ]
        solver_targets = [
            (u, d) for u, _v, d in graph.in_edges(htr_node, data=True)
            if d.get("kind") == ALIGNED_TO and not d["evidence"].observed
        ]
        if gold_targets:
            lines.append(f"{flat_id} -> {', '.join(sorted(gold_targets))} [gold]")
        elif solver_targets:
            tags = [f"{u} [solver, {d['evidence'].detail.get('move_kind')}, unfitted]" for u, d in solver_targets]
            lines.append(f"{flat_id} -> {', '.join(tags)}")
        elif flat_id in move_by_flat_id:
            kind, ref_index = move_by_flat_id[flat_id]
            if kind == SOFT_CLIP:
                lines.append(f"{flat_id}: dropped as margin content (solver, unfitted) -- proposed: no correspondence")
            else:
                lines.append(f"{flat_id}: proposed cut [solver, {kind}, unfitted, abstained={bracket_abstained}]")
        elif attempted:
            lines.append(f"{flat_id}: unaligned (solver ran for {date}, this resolution outside the scored bracket)")
        else:
            lines.append(f"{flat_id}: unaligned (solver not yet attempted for {date})")
    return lines


def query_range(start: str, end: str, *, solver_dates: Sequence[str] = ()) -> None:
    """The week/month overview (Step 4.6): every in-scope date grouped by ISO week, its
    `PINNED_TO`/`LABELLED_AS` status and `ALIGNED_TO` coverage, then each session's own
    resolution-level drill-down. Plain and importable -- a notebook calls this directly, same as
    the CLI (`--range`)."""
    solver_dates = tuple(solver_dates)
    graph, verdicts = _load_for_range(solver_dates)
    dates = _dates_in_range(graph, start, end)
    if not dates:
        print(f"no in-scope dates between {start} and {end}")
        return

    weeks: dict[str, list[str]] = defaultdict(list)
    for date in dates:
        weeks[_week_start(date)].append(date)

    print(f"RANGE {start}..{end} ({len(dates)} in-scope dates, {len(weeks)} weeks)")
    for week_start in sorted(weeks):
        week_dates = weeks[week_start]
        print(f"\n  WEEK {week_start}..{week_dates[-1]}")
        for date in week_dates:
            sessions = _date_sessions(graph, date)
            counts, total = _date_aligned_summary(graph, date)
            status_bits = [
                f"{kind}:{session_id} [{verdicts[session_id].verdict}/{correspondence_class(verdicts[session_id])}]"
                if session_id in verdicts else f"{kind}:{session_id} [no verdict]"
                for _node, session_id, kind in sessions
            ] or ["no session (PINNED_TO/LABELLED_AS: none)"]
            aligned_bit = (
                f"ALIGNED_TO {counts.get('gold_verified', 0)}/{total} gold, "
                f"{counts.get('solver_derived_only', 0)}/{total} solver, "
                f"{counts.get('unaligned', 0)}/{total} open"
                if total else "no enriched resolutions"
            )
            attempted = date in solver_dates
            print(f"    {date}: {'; '.join(status_bits)} | {aligned_bit} "
                  f"({'solver run' if attempted else 'solver not yet attempted'})")
            seen_sessions = dict.fromkeys(session_id for _node, session_id, _kind in sessions)
            for session_id in seen_sessions:
                for line in _session_resolution_lines(graph, session_id, date, attempted):
                    print(f"        {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session")
    group.add_argument("--date")
    group.add_argument("--scan", nargs=2, metavar=("INVENTORY", "SCAN_NUM"))
    group.add_argument("--range", nargs=2, metavar=("START", "END"))
    parser.add_argument(
        "--solver-dates", nargs="*", default=(),
        help="with --range: also run align.py's DP for these gold dates and show it in the report",
    )
    args = parser.parse_args()

    if args.range:
        query_range(args.range[0], args.range[1], solver_dates=args.solver_dates)
        return

    if args.session:
        query_session(args.session)
    elif args.date:
        query_date(args.date)
    else:
        query_scan(args.scan[0], int(args.scan[1]))


if __name__ == "__main__":
    main()

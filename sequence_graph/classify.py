"""Stage 2's gate: reproduce `reconcile_sequences.py`'s verdicts from the graph, exactly.

**Why this module exists separately from `correspondence.py`.** `monotone_map` there is a real,
general order-preserving-map check (every pair compared, like `axis._check_monotone`) and it
disagrees with `reconcile_sequences.monotone_anchors`'s legacy rule (sort by date, greedily drop
any scan that is not a new maximum) on pathological stretches: one badly-parsed anchor makes every
*later*, individually correct entry look like a violation too, under a pairwise check, in a way
the old greedy drop does not. Measured: `monotone_map` reports 4.19% on `DATED_AS` where the old
rule reports 0.4-0.6%. That is a genuine, useful finding (the old rule is locally forgiving in a
way a true order-preserving-map check is not) -- but it is not this module's problem to resolve.
This module's job is narrower: **reproduce the legacy classification exactly**, using the legacy
filtering rule, so Stage 2's gate is a fair test of whether the GRAPH REPRESENTATION can carry the
same computation -- not a test of whether a different, stricter monotonicity notion agrees with
the old one, which it was never going to, and finding out is `monotone_map`'s contribution, kept
in `correspondence.py`, not papered over here.

Usage:
    uv run python -m sequence_graph.classify --report
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass

import networkx as nx

from scripts.corpus_scope import is_main_series
from scripts.measure_scans_per_day import observations

from sequence_graph.build import build
from sequence_graph.correspondence import (
    DATED_AS,
    LABELLED_AS,
    OBSERVED_ON,
    PINNED_TO,
    add_dated_as,
    add_observed_on,
    add_pinned_and_labelled,
)

NARROW_WINDOW_DAYS = 2  # same threshold as reconcile_sequences.py; unified in Stage 3


def _legacy_monotone_anchors(with_bootstrap: bool) -> dict[str, list[tuple[int, str]]]:
    """`reconcile_sequences.monotone_anchors`'s exact rule, reproduced for gate fidelity.

    Sort by DATE per inventory; keep a `(scan, date)` point only if its scan is a new maximum.
    This is the rule the reference bracket construction actually used, so it is what must be
    reproduced here -- `monotone_map`'s own, stricter notion is a separate, later finding.
    """
    first: dict[str, dict[str, int]] = defaultdict(dict)
    for inventory, scan, date, _src in observations(with_bootstrap):
        key = str(date)
        prev = first[inventory].get(key)
        if prev is None or scan < prev:
            first[inventory][key] = scan
    out: dict[str, list[tuple[int, str]]] = {}
    for inventory, by_date in first.items():
        kept: list[tuple[int, str]] = []
        high = -1
        for date in sorted(by_date):
            scan = by_date[date]
            if scan < high:
                continue
            high = scan
            kept.append((scan, date))
        out[inventory] = kept
    return out


def _implied_range(points: list[tuple[int, str]], scan: int) -> tuple[str | None, str | None]:
    """Same forward-claim rule as `reconcile_sequences.implied_range`."""
    left = right = None
    for a_scan, a_date in points:
        if a_scan <= scan:
            left = a_date
        else:
            right = a_date
            break
    return left, right


@dataclass
class SessionVerdict:
    session_id: str
    verdict: str
    problem_type: str
    implied_lo: str | None
    implied_hi: str | None
    implied_window_days: int | None
    offset_days: int | None
    paragraph_count: int


def classify(graph: nx.DiGraph, *, with_bootstrap: bool = True) -> list[SessionVerdict]:
    """One verdict + problem_type per main-series session, via the graph's own edges.

    Reads `OBSERVED_ON` for the session's first scan, the legacy-filtered anchor list per
    inventory for the implied bracket, and `PINNED_TO`/`LABELLED_AS` incoming edges for what the
    editorial sequence believes about this session -- the graph-native equivalent of
    `SessionSpan.resolved_dates`/`label_dates`.
    """
    anchors_by_inventory = _legacy_monotone_anchors(with_bootstrap)

    sessions = [
        (node_id, data["obj"])
        for node_id, data in graph.nodes(data=True)
        if data.get("kind") == "Session" and is_main_series(data["obj"].inventory)
    ]

    verdicts: list[SessionVerdict] = []
    for session_node, session in sessions:
        obs_scan = None
        for _u, v, data in graph.out_edges(session_node, data=True):
            if data.get("kind") == OBSERVED_ON:
                obs_scan = graph.nodes[v]["obj"].scan_num
                break

        resolved = sorted(
            graph.nodes[u]["obj"].date
            for u, _v, data in graph.in_edges(session_node, data=True)
            if data.get("kind") == PINNED_TO
        )
        labelled = sorted(
            graph.nodes[u]["obj"].date
            for u, _v, data in graph.in_edges(session_node, data=True)
            if data.get("kind") == LABELLED_AS
        )
        points = anchors_by_inventory.get(session.inventory, [])
        paragraph_count = sum(
            1 for _u, v, data in graph.out_edges(session_node, data=True)
            if data.get("kind") == "CONTAINS"
            for _u2, v2, d2 in graph.out_edges(v, data=True)
            if d2.get("kind") == "CONTAINS"
        )

        if obs_scan is None or not points:
            verdict = "no_observed_scan" if obs_scan is None else "no_anchors"
            verdicts.append(SessionVerdict(
                session.session_id, verdict, "", None, None, None, None, paragraph_count,
            ))
            continue

        lo, hi = _implied_range(points, obs_scan)
        window = None
        if lo is not None and hi is not None:
            window = (pd_days(hi) - pd_days(lo))

        check = resolved or labelled
        offset_days = None
        if lo is None and hi is None:
            verdict = "unconstrained"
        elif not check:
            verdict = "no_label_to_check"
        else:
            inside = [d for d in check if (lo is None or lo <= d) and (hi is None or d <= hi)]
            verdict = "reconciled" if inside else "contradicted"
            if not inside:
                offs = []
                for d in check:
                    dp = pd_days(d)
                    if lo is not None and dp < pd_days(lo):
                        offs.append(dp - pd_days(lo))
                    elif hi is not None and dp > pd_days(hi):
                        offs.append(dp - pd_days(hi))
                offset_days = min(offs, key=abs) if offs else None

        verdicts.append(SessionVerdict(
            session.session_id, verdict, "", lo, hi, window, offset_days, paragraph_count,
        ))

    # Crowded-window detection (T4), checked before window width -- same precedence as the
    # reference. Keyed on (lo, hi) among contradicted sessions only.
    window_crowd = Counter(
        (v.implied_lo, v.implied_hi) for v in verdicts if v.verdict == "contradicted"
    )
    for v in verdicts:
        v.problem_type = _problem_type(v, window_crowd)
    return verdicts


def _problem_type(v: SessionVerdict, window_crowd: Counter) -> str:
    if v.verdict == "no_observed_scan":
        return "T6_no_scan_observed"
    if v.verdict == "no_label_to_check":
        return "T7_nothing_inferred"
    if v.verdict == "reconciled":
        return "T0_anchor"
    if window_crowd.get((v.implied_lo, v.implied_hi), 0) >= 3:
        return "T4_anchor_bracket_suspect"
    if v.implied_window_days is None or v.implied_window_days > NARROW_WINDOW_DAYS or v.offset_days is None:
        return "T5_window_too_wide_to_judge"
    off = abs(v.offset_days)
    if off <= 2:
        return "T1_offset_1_2_days"
    return "T2_offset_3_7_days" if off <= 7 else "T3_offset_over_7_days"


_EPOCH_CACHE: dict[str, int] = {}


def pd_days(date: str) -> int:
    """Days since an arbitrary epoch, cached -- avoids importing pandas into this module twice
    per comparison; only relative differences are ever used."""
    if date not in _EPOCH_CACHE:
        import pandas as pd
        _EPOCH_CACHE[date] = (pd.Period(date, freq="D") - pd.Period("1600-01-01", freq="D")).n
    return _EPOCH_CACHE[date]


def consolidate(verdicts: list[SessionVerdict]) -> dict[str, int]:
    narrow = [
        v for v in verdicts
        if v.implied_window_days is not None and v.implied_window_days <= NARROW_WINDOW_DAYS
        and v.verdict in ("reconciled", "contradicted")
    ]
    hard = [v for v in narrow if v.verdict == "reconciled"]
    bounded = [v for v in narrow if v.verdict == "contradicted"]
    unconstrained = [
        v for v in verdicts
        if v.verdict in ("no_observed_scan", "no_anchors", "unconstrained", "no_label_to_check")
    ]
    return {
        "hard_anchors": len(hard),
        "bounded_gaps": len(bounded),
        "unconstrained_gaps": len(unconstrained),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--strict-only", action="store_true")
    args = parser.parse_args()

    graph = build()
    add_observed_on(graph)
    add_dated_as(graph, with_bootstrap=not args.strict_only)
    add_pinned_and_labelled(graph)

    verdicts = classify(graph, with_bootstrap=not args.strict_only)
    print(f"sessions classified: {len(verdicts):,}")

    verdict_counts = Counter(v.verdict for v in verdicts)
    print("\nVERDICTS:")
    for name, n in verdict_counts.most_common():
        print(f"  {name:<20}{n:>6}")

    type_counts = Counter(v.problem_type for v in verdicts)
    print("\nPROBLEM TYPES:")
    for name, n in sorted(type_counts.items()):
        print(f"  {name:<28}{n:>6}")

    gate = consolidate(verdicts)
    print("\nCONSOLIDATED:")
    for name, n in gate.items():
        print(f"  {name:<20}{n:>6}")

    if args.report:
        # Corrected 2026-10-09: the plan's 261 (and the original 276 before that) both carried
        # 180 post-bar-only sessions that reconcile_sequences.py never actually excluded -- an
        # oversight inherited from running_axis's deliberate post-bar visibility. Restricting the
        # ORIGINAL reference logic to the same scope-compliant population Stage 1 builds gives
        # 81, not 261 -- verified directly against reconcile_sequences.py's own functions, not
        # re-derived. hard_anchors/bounded_gaps are unaffected (323/406 both times).
        target = {"hard_anchors": 323, "bounded_gaps": 406, "unconstrained_gaps": 81}
        print(f"\nGATE: {'PASS' if gate == target else 'FAIL'} (target {target})")


if __name__ == "__main__":
    main()

"""Broad synchronisation gaps on the saved graph — nothing left 'outside'.

User, 2026-10-09: do not answer with 'material outside whose status we do not know'.
**Broaden the gap:** between consecutive main-series **production** `PINNED_TO` anchors on
the HTR `NEXT` chain, charge **everything** in the bracket — all editorial meetings in the
calendar span, all HTR units in the session span (pinned or not), all `k_e` and paragraph
mass. The gap is the work region for sync/anchors, not an exclusion zone.

4562/4861 out (`is_main_series` only). Scope bar via SittingDay nodes on the graph.

Usage:
    uv run python -m sequence_graph.sync_gaps --report
    uv run python -m sequence_graph.sync_gaps --top 20
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import networkx as nx

from data_io import load, save_semi_structured
from scripts.corpus_scope import is_main_series, scope_meta
from sequence_graph.build import NEXT
from sequence_graph.correspondence import PINNED_TO
from sequence_graph.persist import load_graph

OUTPUT_DATASET = "sequence_graph_sync_gaps"


@dataclass(frozen=True)
class SessionPin:
    session_id: str
    inventory: str
    session_num: int
    pinned_dates: tuple[str, ...]


def _day_has_main_production_pin(graph: nx.MultiDiGraph, day_node: str) -> bool:
    for _u, v, key, ed in graph.out_edges(day_node, keys=True, data=True):
        if ed.get("kind") != PINNED_TO or key != PINNED_TO:
            continue
        if graph.nodes[v].get("kind") == "Session" and is_main_series(
            graph.nodes[v]["obj"].session_id
        ):
            return True
    return False


def _production_pinned_dates(graph: nx.MultiDiGraph, session_node: str) -> tuple[str, ...]:
    dates: list[str] = []
    for u, _v, key, ed in graph.in_edges(session_node, keys=True, data=True):
        if ed.get("kind") != PINNED_TO or key != PINNED_TO:
            continue
        if graph.nodes[u].get("kind") == "SittingDay":
            dates.append(graph.nodes[u]["obj"].date)
    return tuple(sorted(set(dates)))


def pinned_sessions(graph: nx.MultiDiGraph) -> list[SessionPin]:
    out: list[SessionPin] = []
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "Session":
            continue
        sess = data["obj"]
        if not is_main_series(sess.session_id):
            continue
        dates = _production_pinned_dates(graph, node_id)
        if not dates:
            continue
        out.append(
            SessionPin(
                session_id=sess.session_id,
                inventory=sess.inventory,
                session_num=sess.session_num,
                pinned_dates=dates,
            )
        )
    return sorted(out, key=lambda p: (p.inventory, p.session_num))


def _sessions_in_inventory(graph: nx.MultiDiGraph, inventory: str) -> list[tuple[int, str, str]]:
    """(session_num, session_id, node_id) sorted."""
    rows = []
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "Session":
            continue
        s = data["obj"]
        if s.inventory != inventory or not is_main_series(s.session_id):
            continue
        rows.append((s.session_num, s.session_id, node_id))
    return sorted(rows)


def _paragraph_count(graph: nx.MultiDiGraph, session_node: str) -> int:
    n = 0
    for htr in graph.successors(session_node):
        if graph.nodes[htr].get("kind") != "HtrResolution":
            continue
        for _p, _q, ed in graph.out_edges(htr, data=True):
            if ed.get("kind") == "CONTAINS":
                n += 1
    return n


def _k_e_in_date_span(graph: nx.MultiDiGraph, lo: str, hi: str) -> tuple[int, int]:
    """(n_meetings, n_resolutions) for SittingDays with lo <= date <= hi."""
    meetings = resolutions = 0
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "SittingDay":
            continue
        date = data["obj"].date
        if not (lo <= date <= hi):
            continue
        meetings += 1
        for _u, _v, ed in graph.out_edges(node_id, data=True):
            if ed.get("kind") == "CONTAINS":
                resolutions += 1
    return meetings, resolutions


def build_broad_gaps(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    """Interior brackets between consecutive pinned sessions per inventory."""
    pins_by_inv: dict[str, list[SessionPin]] = {}
    for p in pinned_sessions(graph):
        pins_by_inv.setdefault(p.inventory, []).append(p)

    gaps: list[dict[str, Any]] = []
    for inventory, pins in sorted(pins_by_inv.items()):
        all_sess = _sessions_in_inventory(graph, inventory)
        num_to_node = {num: node for num, _sid, node in all_sess}

        for left, right in zip(pins, pins[1:]):
            if right.session_num <= left.session_num:
                continue
            lo_date = min(left.pinned_dates)
            hi_date = max(right.pinned_dates)
            # HTR in bracket: inclusive session range (anchors + interior — full sync region)
            interior = [
                (num, sid, num_to_node[num])
                for num, sid, _ in all_sess
                if left.session_num <= num <= right.session_num
            ]
            htr_paras = sum(_paragraph_count(graph, node) for _n, _s, node in interior)
            n_meetings, k_e = _k_e_in_date_span(graph, lo_date, hi_date)
            # editorial meetings without production pin inside span (sync debt)
            unsynced_meetings = 0
            for node_id, data in graph.nodes(data=True):
                if data.get("kind") != "SittingDay":
                    continue
                date = data["obj"].date
                if not (lo_date <= date <= hi_date):
                    continue
                if _day_has_main_production_pin(graph, node_id):
                    continue
                unsynced_meetings += 1

            gaps.append({
                "record_type": "sync_gap",
                "inventory": inventory,
                "anchor_lo_session": left.session_id,
                "anchor_hi_session": right.session_id,
                "anchor_lo_dates": list(left.pinned_dates),
                "anchor_hi_dates": list(right.pinned_dates),
                "calendar_lo": lo_date,
                "calendar_hi": hi_date,
                "calendar_span_days": (
                    __import__("pandas").Period(hi_date, freq="D")
                    - __import__("pandas").Period(lo_date, freq="D")
                ).n + 1,
                "n_htr_sessions_inclusive": len(interior),
                "htr_paragraphs_inclusive": htr_paras,
                "n_editorial_meetings_in_span": n_meetings,
                "k_e_in_span": k_e,
                "n_meetings_no_production_pin_in_span": unsynced_meetings,
                "charge_k_e": k_e,
                "charge_htr_paras": htr_paras,
                "charge_combined": k_e + htr_paras,
            })
    gaps.sort(
        key=lambda g: (
            -g["charge_combined"],
            -g["charge_k_e"],
            g["inventory"],
            g["calendar_lo"],
        )
    )
    return gaps


def gate_summary(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_type": "meta",
        "definition": (
            "Broad sync gap = calendar span between consecutive production PINNED_TO "
            "sessions on HTR NEXT; charges all editorial k_e in the calendar span and all "
            "HTR paragraphs in the inclusive session-num range (anchors included)."
        ),
        "n_interior_brackets": len(gaps),
        "total_k_e_in_gaps": sum(g["charge_k_e"] for g in gaps),
        "total_htr_paras_in_gaps": sum(g["charge_htr_paras"] for g in gaps),
        **scope_meta(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="write dataset + print summary")
    parser.add_argument("--top", type=int, default=15, help="rows to print")
    args = parser.parse_args()

    graph = load_graph()
    gaps = build_broad_gaps(graph)
    meta = gate_summary(gaps)

    if args.report:
        save_semi_structured(
            [meta, *gaps],
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=meta["definition"],
            parent_sources=["sequence_graph_nodes", "sequence_graph_edges"],
        )

    print(meta["definition"])
    print(
        f"brackets={meta['n_interior_brackets']}  "
        f"total k_e in gaps={meta['total_k_e_in_gaps']}  "
        f"total HTR paras in gaps={meta['total_htr_paras_in_gaps']}"
    )
    print(f"\nTop {args.top} broad sync gaps (by k_e in span):")
    for g in gaps[: args.top]:
        print(
            f"  {g['inventory']} {g['calendar_lo']}..{g['calendar_hi']} "
            f"({g['calendar_span_days']}d)  "
            f"anchors {g['anchor_lo_session']} | {g['anchor_hi_session']}  "
            f"k_e={g['charge_k_e']} ({g['n_meetings_no_production_pin_in_span']} meetings no pin)  "
            f"htr={g['n_htr_sessions_inclusive']} sess / {g['charge_htr_paras']} paras  "
            f"combined={g['charge_combined']}"
        )


if __name__ == "__main__":
    main()

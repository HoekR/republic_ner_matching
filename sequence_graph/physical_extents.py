"""Physical session extents from OBSERVED_ON — bounds first, text later.

User, 2026-10-09: session↔scan is a physical track and has nothing to do with text. Use it to
determine session boundaries objectively; only then find text inside those spans. Undated
sessions (OBSERVED_ON present, no DATED_AS on those scans) benefit because they land in
different sync gaps once extents are physical.

Does **not** propose PINNED_TO from text bags or concordance extents. Sample proof only.

Usage:
    uv run python -m sequence_graph.physical_extents --prove
    uv run python -m sequence_graph.physical_extents --prove --inventory 3185 --scan-lo 95 --scan-hi 110
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

import networkx as nx

from data_io import save_semi_structured
from scripts.corpus_scope import is_main_series, scope_meta
from sequence_graph.correspondence import DATED_AS, OBSERVED_ON, PINNED_TO
from sequence_graph.persist import load_graph

OUTPUT_DATASET = "sequence_graph_physical_extents_proof"
# Default continuous sample: physical scan NEXT stretch covering the known
# 03-27 / num-56 disagreement (heading on scan 103 → num-57; num-56 on undated scan 98).
DEFAULT_INVENTORY = "3185"
DEFAULT_SCAN_LO = 95
DEFAULT_SCAN_HI = 110
PROOF_DATED_DAY = "1626-03-27"
PROOF_DATED_SESSION = "session-3185-num-57"
PROOF_UNDATED_SESSION = "session-3185-num-56"
PROOF_UNDATED_SCAN = 98


@dataclass(frozen=True)
class PhysicalExtent:
    session_id: str
    inventory: str
    session_num: int
    scan_nums: tuple[int, ...]
    dated_days: tuple[str, ...]  # SittingDay dates via DATED_AS on those scans
    undated: bool  # True iff OBSERVED_ON scans carry zero DATED_AS

    @property
    def scan_lo(self) -> int | None:
        return min(self.scan_nums) if self.scan_nums else None

    @property
    def scan_hi(self) -> int | None:
        return max(self.scan_nums) if self.scan_nums else None


def build_extents(graph: nx.MultiDiGraph) -> list[PhysicalExtent]:
    """One extent per main-series Session with ≥1 OBSERVED_ON scan."""
    out: list[PhysicalExtent] = []
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "Session":
            continue
        sess = data["obj"]
        if not is_main_series(sess.session_id):
            continue
        scans: list[int] = []
        days: set[str] = set()
        for _u, v, ed in graph.out_edges(node_id, data=True):
            if ed.get("kind") != OBSERVED_ON:
                continue
            if graph.nodes[v].get("kind") != "Scan":
                continue
            scan = graph.nodes[v]["obj"]
            if scan.inventory != sess.inventory:
                continue
            scans.append(int(scan.scan_num))
            for _a, day_node, ded in graph.out_edges(v, data=True):
                if ded.get("kind") != DATED_AS:
                    continue
                if graph.nodes[day_node].get("kind") == "SittingDay":
                    days.add(graph.nodes[day_node]["obj"].date)
        if not scans:
            continue
        scans_t = tuple(sorted(set(scans)))
        days_t = tuple(sorted(days))
        out.append(
            PhysicalExtent(
                session_id=sess.session_id,
                inventory=sess.inventory,
                session_num=sess.session_num,
                scan_nums=scans_t,
                dated_days=days_t,
                undated=len(days_t) == 0,
            )
        )
    return sorted(out, key=lambda e: (e.inventory, e.session_num))


def dated_day_to_sessions(graph: nx.MultiDiGraph) -> dict[str, list[str]]:
    """SittingDay date → sessions reached by DATED_AS ← Scan ← OBSERVED_ON (physical only)."""
    by_date: dict[str, set[str]] = defaultdict(set)
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "SittingDay":
            continue
        date = data["obj"].date
        for scan_node, _v, ed in graph.in_edges(node_id, data=True):
            if ed.get("kind") != DATED_AS:
                continue
            for sess_node, _s, oed in graph.in_edges(scan_node, data=True):
                if oed.get("kind") != OBSERVED_ON:
                    continue
                if graph.nodes[sess_node].get("kind") != "Session":
                    continue
                sid = graph.nodes[sess_node]["obj"].session_id
                if is_main_series(sid):
                    by_date[date].add(sid)
    return {d: sorted(s) for d, s in by_date.items()}


def nearest_dated_scans(
    graph: nx.MultiDiGraph, inventory: str, scan_num: int
) -> dict[str, Any]:
    """On the scan NEXT chain, nearest scans with DATED_AS before/after `scan_num`."""
    lo_scan = lo_date = hi_scan = hi_date = None
    # walk down
    for sn in range(scan_num - 1, 0, -1):
        node = f"scan:{inventory}:{sn}"
        if node not in graph:
            continue
        dates = [
            graph.nodes[v]["obj"].date
            for _u, v, ed in graph.out_edges(node, data=True)
            if ed.get("kind") == DATED_AS and graph.nodes[v].get("kind") == "SittingDay"
        ]
        if dates:
            lo_scan, lo_date = sn, min(dates)
            break
    # walk up (cap generously)
    for sn in range(scan_num + 1, scan_num + 500):
        node = f"scan:{inventory}:{sn}"
        if node not in graph:
            if sn > scan_num + 50 and lo_scan is not None:
                break
            continue
        dates = [
            graph.nodes[v]["obj"].date
            for _u, v, ed in graph.out_edges(node, data=True)
            if ed.get("kind") == DATED_AS and graph.nodes[v].get("kind") == "SittingDay"
        ]
        if dates:
            hi_scan, hi_date = sn, min(dates)
            break
    return {
        "lo_dated_scan": lo_scan,
        "lo_dated_day": lo_date,
        "hi_dated_scan": hi_scan,
        "hi_dated_day": hi_date,
    }


def neighbourhood_rows(
    graph: nx.MultiDiGraph, inventory: str, lo: int, hi: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sn in range(lo, hi + 1):
        node = f"scan:{inventory}:{sn}"
        if node not in graph:
            continue
        dated = [
            graph.nodes[v]["obj"].date
            for _u, v, ed in graph.out_edges(node, data=True)
            if ed.get("kind") == DATED_AS and graph.nodes[v].get("kind") == "SittingDay"
        ]
        sessions = [
            graph.nodes[u]["obj"].session_id
            for u, _v, ed in graph.in_edges(node, data=True)
            if ed.get("kind") == OBSERVED_ON and graph.nodes[u].get("kind") == "Session"
        ]
        rows.append({
            "record_type": "scan_row",
            "inventory": inventory,
            "scan_num": sn,
            "dated_days": sorted(dated),
            "sessions": sessions,
        })
    return rows


def prove_march_1626(graph: nx.MultiDiGraph, extents: list[PhysicalExtent]) -> dict[str, Any]:
    """Fixed physical proof on the 1626-03-27 / num-56 neighbourhood."""
    by_sid = {e.session_id: e for e in extents}
    day_sessions = dated_day_to_sessions(graph)
    physical_for_dated = day_sessions.get(PROOF_DATED_DAY, [])
    undated_ext = by_sid.get(PROOF_UNDATED_SESSION)
    dated_ok = physical_for_dated == [PROOF_DATED_SESSION]
    undated_ok = bool(
        undated_ext
        and undated_ext.undated
        and PROOF_UNDATED_SCAN in undated_ext.scan_nums
    )
    # production pin on 03-27 (inferred) vs physical
    pin_sessions: list[str] = []
    day_node = f"day:{PROOF_DATED_DAY}"
    if day_node in graph:
        for _u, v, ed in graph.out_edges(day_node, data=True):
            if ed.get("kind") == PINNED_TO and graph.nodes[v].get("kind") == "Session":
                pin_sessions.append(graph.nodes[v]["obj"].session_id)

    return {
        "record_type": "proof_case",
        "label": "march_1626_physical_neighbourhood",
        "dated_day": PROOF_DATED_DAY,
        "physical_sessions_for_dated_day": physical_for_dated,
        "expected_physical_session": PROOF_DATED_SESSION,
        "physical_dated_ok": dated_ok,
        "production_PINNED_TO": pin_sessions,
        "pin_disagrees_with_physical": sorted(set(pin_sessions)) != [PROOF_DATED_SESSION],
        "undated_session": PROOF_UNDATED_SESSION,
        "undated_extent": asdict(undated_ext) if undated_ext else None,
        "undated_ok": undated_ok,
        "gate_pass": dated_ok and undated_ok,
        "neighbourhood": neighbourhood_rows(
            graph, DEFAULT_INVENTORY, DEFAULT_SCAN_LO, DEFAULT_SCAN_HI
        ),
    }


def continuous_stretch(
    graph: nx.MultiDiGraph,
    extents: list[PhysicalExtent],
    *,
    inventory: str,
    scan_lo: int,
    scan_hi: int,
) -> dict[str, Any]:
    """One contiguous scan NEXT window: every scan + sessions that touch it + calendar brackets."""
    by_sid = {e.session_id: e for e in extents}
    scan_rows = neighbourhood_rows(graph, inventory, scan_lo, scan_hi)
    # sessions whose physical span intersects [scan_lo, scan_hi]
    sessions_in: list[dict[str, Any]] = []
    seen: set[str] = set()
    for e in extents:
        if e.inventory != inventory:
            continue
        if e.scan_hi is None or e.scan_lo is None:
            continue
        if e.scan_hi < scan_lo or e.scan_lo > scan_hi:
            continue
        if e.session_id in seen:
            continue
        seen.add(e.session_id)
        mid = e.scan_nums[len(e.scan_nums) // 2]
        sessions_in.append({
            "record_type": "stretch_session",
            **asdict(e),
            "physical_calendar_bracket": nearest_dated_scans(graph, e.inventory, mid),
        })
    sessions_in.sort(key=lambda r: r["session_num"])
    n_undated = sum(1 for r in sessions_in if r["undated"])
    return {
        "record_type": "continuous_stretch",
        "inventory": inventory,
        "scan_lo": scan_lo,
        "scan_hi": scan_hi,
        "n_scans_present": len(scan_rows),
        "n_sessions_intersecting": len(sessions_in),
        "n_undated_sessions": n_undated,
        "scans": scan_rows,
        "sessions": sessions_in,
    }


def corpus_summary(extents: list[PhysicalExtent]) -> dict[str, Any]:
    undated = [e for e in extents if e.undated]
    dated = [e for e in extents if not e.undated]
    return {
        "record_type": "meta",
        "n_sessions_with_observed_on": len(extents),
        "n_dated": len(dated),
        "n_undated": len(undated),
        "undated_share": round(len(undated) / max(len(extents), 1), 3),
        "note": (
            "Physical extents from OBSERVED_ON only; dated_days from DATED_AS on those scans. "
            "Text is not used. Proof is a continuous scan stretch (book order), not a random draw."
        ),
        **scope_meta(),
    }


def prove(
    *,
    inventory: str,
    scan_lo: int,
    scan_hi: int,
    write: bool,
) -> list[dict[str, Any]]:
    graph = load_graph()
    extents = build_extents(graph)
    meta = corpus_summary(extents)
    case = prove_march_1626(graph, extents)
    # If caller asked for the default window, the gate case is inside the stretch; always
    # emit the continuous stretch as the sample (may equal or differ from the gate window).
    stretch = continuous_stretch(
        graph, extents, inventory=inventory, scan_lo=scan_lo, scan_hi=scan_hi
    )

    print(meta["note"])
    print(
        f"main-series sessions with OBSERVED_ON: {meta['n_sessions_with_observed_on']}  "
        f"dated={meta['n_dated']}  undated={meta['n_undated']} "
        f"({100 * meta['undated_share']:.1f}%)"
    )
    print(f"\n=== GATE {case['label']} ===")
    print(
        f"  {case['dated_day']} via DATED_AS→scan→OBSERVED_ON → "
        f"{case['physical_sessions_for_dated_day']}  "
        f"(expect [{PROOF_DATED_SESSION}])  "
        f"{'PASS' if case['physical_dated_ok'] else 'FAIL'}"
    )
    print(
        f"  production PINNED_TO={case['production_PINNED_TO']}  "
        f"disagrees_with_physical={case['pin_disagrees_with_physical']}"
    )
    print(
        f"  {PROOF_UNDATED_SESSION} undated on scans "
        f"{case['undated_extent']['scan_nums'] if case['undated_extent'] else None}  "
        f"{'PASS' if case['undated_ok'] else 'FAIL'}"
    )
    print(f"  gate_pass={case['gate_pass']}")

    print(
        f"\n=== CONTINUOUS STRETCH {inventory} scans {scan_lo}..{scan_hi} "
        f"({stretch['n_sessions_intersecting']} sessions, "
        f"{stretch['n_undated_sessions']} undated) ==="
    )
    print("  scan  dated_day(s)              session(s)")
    for row in stretch["scans"]:
        dated = ",".join(row["dated_days"]) if row["dated_days"] else "—"
        sess = ",".join(row["sessions"]) if row["sessions"] else "—"
        # always print continuous line (including empty) so the book order is visible
        mark = ""
        if PROOF_UNDATED_SCAN == row["scan_num"]:
            mark = "  ← undated num-56"
        if PROOF_DATED_DAY in row["dated_days"]:
            mark = "  ← 03-27 physical"
        print(f"  {row['scan_num']:>4}  {dated:<26} {sess}{mark}")

    print("\n  sessions intersecting stretch (physical calendar bracket from dated neighbours):")
    for row in stretch["sessions"]:
        b = row["physical_calendar_bracket"]
        flag = " UNDATED" if row["undated"] else ""
        print(
            f"    {row['session_id']}  scans={list(row['scan_nums'])}{flag}  "
            f"dated_on_own_scans={list(row['dated_days']) or '—'}  "
            f"neighbours {b['lo_dated_day']}@{b['lo_dated_scan']} .. "
            f"{b['hi_dated_day']}@{b['hi_dated_scan']}"
        )

    rows: list[dict[str, Any]] = [meta, case, stretch, *stretch["sessions"]]
    if write:
        save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=meta["note"],
            parent_sources=["sequence_graph_nodes", "sequence_graph_edges"],
        )
        print(f"\nWrote {OUTPUT_DATASET}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prove", action="store_true")
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY)
    parser.add_argument("--scan-lo", type=int, default=DEFAULT_SCAN_LO)
    parser.add_argument("--scan-hi", type=int, default=DEFAULT_SCAN_HI)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not args.prove:
        parser.error("pass --prove")
    prove(
        inventory=args.inventory,
        scan_lo=args.scan_lo,
        scan_hi=args.scan_hi,
        write=args.write,
    )


if __name__ == "__main__":
    main()

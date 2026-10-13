"""Gated PINNED_TO repin from the hard map (OBSERVED_ON ∘ DATED_AS).

Lands parallel ``PINNED_TO:hard`` claim edges on the saved graph. Does **not**
overwrite the production ``PINNED_TO`` key, and does **not** rewrite concordance
or ``ALIGNED_TO`` — content re-align under the new lids is a later step.

Population: active unique hard-map beads from ``hard_recalibrate_proof`` (or a
live ``hard_map_in_window`` recompute) inside a pinned calendar window.

Gate (structural + standing guard):
  - eligible hard pins > 0, main-series, in-scope
  - hard ``session_num`` monotone in date order within the inventory
  - report slice ``separated`` vs ``uniform_start_paragraphs`` on eligible dates
    (never absolute; pin land does not change placements, so Δ separated = 0)

Usage:
    uv run python -m sequence_graph.hard_pin_repin --write
    uv run python -m sequence_graph.hard_pin_repin --write --push-graph
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from typing import Any

import networkx as nx
import pandas as pd

from data_io import load, save_semi_structured
from scripts.apply_duplicate_session_splits_eval import slice_separated
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from scripts.separated_accuracy_eval import label_separation, uniform_start_paragraphs
from sequence_graph.correspondence import Evidence, PINNED_TO
from sequence_graph.hard_recalibrate import hard_map_in_window
from sequence_graph.persist import load_graph, save_loaded_graph

PROOF_DATASET = "hard_recalibrate_proof"
CONCORDANCE = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "hard_pin_repin"
EDGE_KEY = f"{PINNED_TO}:hard"
CHANNEL = "hard_observed_on_compose_dated_as"

DEFAULT_INVENTORY = "3185"
DEFAULT_LO = "1626-09-21"
DEFAULT_HI = "1626-10-25"


def _session_num(session_id: str) -> int | None:
    m = re.search(r"num-(\d+)", session_id)
    return int(m.group(1)) if m else None


def _window_from_proof(proof_rows: list[dict[str, Any]]) -> tuple[str, str, str]:
    meta = next((r for r in proof_rows if r.get("record_type") == "meta"), {})
    return (
        str(meta.get("inventory") or DEFAULT_INVENTORY),
        str(meta.get("calendar_lo") or DEFAULT_LO),
        str(meta.get("calendar_hi") or DEFAULT_HI),
    )


def hard_map_rows_for_window(
    *,
    proof_rows: list[dict[str, Any]] | None = None,
    graph: nx.MultiDiGraph | None = None,
    inventory: str | None = None,
    calendar_lo: str | None = None,
    calendar_hi: str | None = None,
) -> tuple[list[dict[str, Any]], str, str, str]:
    """Prefer on-disk proof hard_map; else recompute from graph."""
    if proof_rows is None:
        try:
            proof_rows = list(load(PROOF_DATASET))
        except Exception:
            proof_rows = []

    inv, lo, hi = _window_from_proof(proof_rows)
    if inventory:
        inv = inventory
    if calendar_lo:
        lo = calendar_lo
    if calendar_hi:
        hi = calendar_hi

    from_proof = [
        r
        for r in proof_rows
        if r.get("record_type") == "hard_map"
        and r.get("active")
        and r.get("unique")
        and r.get("session_id")
        and lo <= str(r.get("date") or "") <= hi
    ]
    if from_proof:
        return from_proof, inv, lo, hi

    if graph is None:
        graph = load_graph()
    live = [
        r
        for r in hard_map_in_window(graph, inv, lo, hi)
        if r.get("active") and r.get("unique") and r.get("session_id")
    ]
    return live, inv, lo, hi


def propose_repin_rows(hard_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One wire candidate per active unique hard bead."""
    out: list[dict[str, Any]] = []
    for r in sorted(hard_rows, key=lambda x: str(x.get("date") or "")):
        date = str(r.get("date") or "")[:10]
        sid = str(r.get("session_id") or "")
        if not date or not in_scope(date) or not is_main_series(sid):
            out.append({
                "record_type": "skipped",
                "date": date or None,
                "session_id": sid or None,
                "reason": "out_of_scope_or_sidelined",
            })
            continue
        prod = r.get("production_session")
        if prod is None:
            verdict = "new_pin"
        elif prod == sid:
            verdict = "agree"
        else:
            verdict = "shift"
        out.append({
            "record_type": "wire_edge",
            "date": date,
            "session_id": sid,
            "session_num": r.get("session_num") or _session_num(sid),
            "production_session": prod,
            "production_disagrees": bool(r.get("production_disagrees")),
            "verdict": verdict,
            "dated_scans_on_session": list(r.get("dated_scans_on_session") or []),
            "edge": PINNED_TO,
            "edge_key": EDGE_KEY,
            "channel": CHANNEL,
            "observed": False,
            "gate_eligible": True,
        })
    return out


def hard_pins_monotone(wire_edges: list[dict[str, Any]]) -> dict[str, Any]:
    """session_num must be non-decreasing along sorted dates."""
    beads = sorted(
        (r for r in wire_edges if r.get("record_type") == "wire_edge"),
        key=lambda r: (str(r["date"]), int(r.get("session_num") or 0)),
    )
    violations: list[dict[str, Any]] = []
    prev_num: int | None = None
    prev_date: str | None = None
    for r in beads:
        num = r.get("session_num")
        if num is None:
            continue
        num = int(num)
        if prev_num is not None and num < prev_num:
            violations.append({
                "date": r["date"],
                "session_num": num,
                "prev_date": prev_date,
                "prev_session_num": prev_num,
            })
        prev_num = num
        prev_date = r["date"]
    return {
        "n_beads": len(beads),
        "n_violations": len(violations),
        "violations": violations,
        "ok": len(violations) == 0 and len(beads) > 0,
    }


def uniform_separated_on_dates(
    concordance: pd.DataFrame, dates: set[str]
) -> dict[str, int]:
    """Uniform-null separated count on the same paragraph span production uses."""
    work = concordance.copy()
    work["enriched_date"] = work["enriched_date"].astype(str).str.slice(0, 10)
    sub = work.loc[work["enriched_date"].isin(dates)].copy()
    rows: list[dict[str, Any]] = []
    for date, group in sub.groupby("enriched_date"):
        attributed = group.loc[
            group["paragraph_start_index"].notna() & group["paragraph_end_index"].notna()
        ]
        if attributed.empty:
            continue
        starts = attributed["paragraph_start_index"].astype(int)
        ends = attributed["paragraph_end_index"].astype(int)
        lo, hi = int(starts.min()), int(ends.max())
        n_para = max(1, hi - lo + 1)
        ordered = attributed.sort_values("resolution_index")
        k = len(ordered)
        u_starts = uniform_start_paragraphs(n_para, k)
        for i, _idx in enumerate(ordered.index):
            s = lo + u_starts[i] if i < len(u_starts) else lo
            rows.append({
                "enriched_date": date,
                "paragraph_start_index": s,
                "paragraph_end_index": s,
            })
    if not rows:
        return {"separated": 0, "attributed": 0, "n_dates": 0}
    lab = label_separation(pd.DataFrame(rows))
    return {
        "separated": int(lab["separated"].sum()),
        "attributed": len(lab),
        "n_dates": int(lab["enriched_date"].nunique()),
    }


def run_hard_pin_repin(
    *,
    proof_rows: list[dict[str, Any]] | None = None,
    concordance: pd.DataFrame | None = None,
    inventory: str | None = None,
    calendar_lo: str | None = None,
    calendar_hi: str | None = None,
    graph: nx.MultiDiGraph | None = None,
) -> list[dict[str, Any]]:
    hard_rows, inv, lo, hi = hard_map_rows_for_window(
        proof_rows=proof_rows,
        graph=graph,
        inventory=inventory,
        calendar_lo=calendar_lo,
        calendar_hi=calendar_hi,
    )
    parts = propose_repin_rows(hard_rows)
    edges = [r for r in parts if r.get("record_type") == "wire_edge"]
    skipped = [r for r in parts if r.get("record_type") == "skipped"]
    mono = hard_pins_monotone(edges)

    if concordance is None:
        concordance = load(CONCORDANCE)
    eligible_dates = {str(r["date"]) for r in edges}
    before_slice = slice_separated(concordance, eligible_dates)
    uniform_slice = uniform_separated_on_dates(concordance, eligible_dates)

    by_verdict = Counter(r.get("verdict") for r in edges)
    gate_ok = mono["ok"] and len(edges) > 0
    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "hard_pin_repin",
            "edge": PINNED_TO,
            "edge_key": EDGE_KEY,
            "channel": CHANNEL,
            "inventory": inv,
            "calendar_lo": lo,
            "calendar_hi": hi,
            "n_hard_active": len(hard_rows),
            "n_wire_edges": len(edges),
            "n_skipped": len(skipped),
            "n_shift": by_verdict.get("shift", 0),
            "n_new_pin": by_verdict.get("new_pin", 0),
            "n_agree": by_verdict.get("agree", 0),
            "monotone_ok": mono["ok"],
            "n_monotone_violations": mono["n_violations"],
            "before_slice_separated": before_slice["separated"],
            "before_slice_attributed": before_slice["attributed"],
            "uniform_slice_separated": uniform_slice["separated"],
            "delta_separated_vs_uniform": (
                before_slice["separated"] - uniform_slice["separated"]
            ),
            "policy": (
                "PINNED_TO:hard claim channel only. No production PINNED_TO key "
                "overwrite, no concordance / ALIGNED_TO rewrite. Re-align under "
                "new lids is a later step. Separated reported vs uniform null "
                "(standing guard); pin land leaves placements unchanged."
            ),
            **scope_meta(),
        },
        *edges,
        *skipped,
        {
            "record_type": "monotone",
            **mono,
        },
        {
            "record_type": "separated_guard",
            "slice_dates": sorted(eligible_dates),
            "before": before_slice,
            "uniform_null": uniform_slice,
            "delta_separated": 0,
            "note": (
                "Pin land does not move paragraph placements; Δ separated = 0. "
                "before vs uniform is the standing-guard snapshot on this slice."
            ),
        },
        {
            "record_type": "summary",
            "n_wire_edges": len(edges),
            "n_shift": by_verdict.get("shift", 0),
            "n_new_pin": by_verdict.get("new_pin", 0),
            "n_agree": by_verdict.get("agree", 0),
            "n_skipped": len(skipped),
            "monotone_ok": mono["ok"],
            "before_slice_separated": before_slice["separated"],
            "uniform_slice_separated": uniform_slice["separated"],
            "gate": "PASS" if gate_ok else "FAIL",
            "next": (
                "Re-run with --push-graph to plow PINNED_TO:hard into the saved "
                "graph. Then content re-align (stages 5–6) under the new lids; "
                "still no production PINNED_TO key overwrite."
            ),
        },
    ]
    rows[0]["gate"] = rows[-1]["gate"]
    return rows


def push_hard_pins_to_graph(
    graph: nx.MultiDiGraph,
    wire_rows: list[dict[str, Any]],
) -> int:
    """Replace ``PINNED_TO:hard`` for dates in ``wire_rows`` only (other windows kept)."""
    wire_dates = {
        str(row["date"])[:10]
        for row in wire_rows
        if row.get("record_type") == "wire_edge" and row.get("date")
    }
    drop = [
        (u, v, k)
        for u, v, k, d in graph.edges(keys=True, data=True)
        if d.get("kind") == PINNED_TO
        and k == EDGE_KEY
        and u.startswith("day:")
        and u[4:] in wire_dates
    ]
    graph.remove_edges_from(drop)
    added = 0
    for row in wire_rows:
        if row.get("record_type") != "wire_edge":
            continue
        date = str(row["date"])[:10]
        sid = str(row["session_id"])
        if not in_scope(date) or not is_main_series(sid):
            continue
        u = f"day:{date}"
        v = f"session:{sid}"
        if u not in graph or v not in graph:
            continue
        graph.add_edge(
            u,
            v,
            key=EDGE_KEY,
            kind=PINNED_TO,
            evidence=Evidence(
                channel=CHANNEL,
                source="sequence_graph.hard_pin_repin",
                observed=False,
                confidence=None,
                detail={
                    "verdict": row.get("verdict"),
                    "production_session": row.get("production_session"),
                    "production_disagrees": bool(row.get("production_disagrees")),
                    "dated_scans_on_session": list(
                        row.get("dated_scans_on_session") or []
                    ),
                },
            ),
        )
        added += 1
    return added


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--write", action="store_true", help=f"persist {OUTPUT_DATASET}")
    parser.add_argument(
        "--push-graph",
        action="store_true",
        help=f"add {EDGE_KEY} edges to the saved sequence graph",
    )
    parser.add_argument("--inventory", default=None)
    parser.add_argument("--calendar-lo", default=None)
    parser.add_argument("--calendar-hi", default=None)
    args = parser.parse_args(argv)

    rows = run_hard_pin_repin(
        inventory=args.inventory,
        calendar_lo=args.calendar_lo,
        calendar_hi=args.calendar_hi,
    )
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    print(
        f"hard_pin_repin  gate={summary['gate']}  "
        f"edges={summary['n_wire_edges']}  "
        f"shift={summary['n_shift']} new={summary['n_new_pin']} "
        f"agree={summary['n_agree']}  "
        f"monotone={summary['monotone_ok']}"
    )
    print(
        f"  separated guard: before={summary['before_slice_separated']}  "
        f"uniform={summary['uniform_slice_separated']}  "
        f"Δvs_uniform={meta['delta_separated_vs_uniform']:+d}  "
        f"(placements unchanged)"
    )
    print(f"  next: {summary.get('next')}")
    print(f"  records: {dict(Counter(r.get('record_type') for r in rows))}")

    if args.write:
        path = save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[PROOF_DATASET],
        )
        from sequence_graph.remediation_run_log import log_hard_pin_repin

        log_hard_pin_repin(rows)
        print(f"wrote {path}")

    if args.push_graph:
        if summary["gate"] != "PASS":
            raise SystemExit(
                f"refusing --push-graph: gate={summary['gate']} "
                f"(monotone_ok={summary['monotone_ok']}, "
                f"n_wire={summary['n_wire_edges']})"
            )
        graph = load_graph()
        n = push_hard_pins_to_graph(graph, rows)
        save_loaded_graph(graph)
        print(f"pushed {n} {EDGE_KEY} edges")


if __name__ == "__main__":
    main()

"""Promote ``PINNED_TO:hard`` to production ``PINNED_TO`` on a scoped seed window.

Doctrine (docs/DECISIONS.md 2026-10-12): overwrite production pins from hard evidence
+ monotone — **not** gated on content re-align. Concordance ``resolved_session_id``
moves with the pin; paragraph placements stay put.

Also reports **inherit-date** composition for the content path: once ``ALIGNED_TO``
names an HTR session, the sitting date is inherited from that session's hard path
(``OBSERVED_ON∘DATED_AS`` / active ``PINNED_TO:hard`` bead). Content never writes
``PINNED_TO``.

Usage:
    uv run python -m sequence_graph.hard_pin_promote --write
    uv run python -m sequence_graph.hard_pin_promote --write --wire --push-graph
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

import networkx as nx
import pandas as pd

from data_io import load, save_parquet, save_semi_structured
from scripts.apply_duplicate_session_splits_eval import separated_total, slice_separated
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from sequence_graph.build import CONTAINS
from sequence_graph.correspondence import (
    ALIGNED_TO,
    DATED_AS,
    Evidence,
    OBSERVED_ON,
    PINNED_TO,
)
from sequence_graph.hard_pin_repin import (
    CHANNEL as HARD_CHANNEL,
    DEFAULT_HI,
    DEFAULT_INVENTORY,
    DEFAULT_LO,
    EDGE_KEY as HARD_EDGE_KEY,
    OUTPUT_DATASET as REPIN_DATASET,
    hard_pins_monotone,
    run_hard_pin_repin,
    uniform_separated_on_dates,
)
from sequence_graph.persist import load_graph, save_loaded_graph

CONCORDANCE = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "hard_pin_promote"
CHANNEL = "hard_pin_promote"
PRED_STATUS = "hard_pin_promote"


def _wire_edges_from_repin(
    repin_rows: list[dict[str, Any]] | None = None,
    *,
    inventory: str | None = None,
    calendar_lo: str | None = None,
    calendar_hi: str | None = None,
    concordance: pd.DataFrame | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Prefer on-disk ``hard_pin_repin`` wire_edge rows; else recompute."""
    if repin_rows is None:
        try:
            repin_rows = list(load(REPIN_DATASET))
        except Exception:
            repin_rows = []

    meta = next((r for r in repin_rows if r.get("record_type") == "meta"), {})
    edges = [r for r in repin_rows if r.get("record_type") == "wire_edge"]
    if edges:
        inv = inventory or str(meta.get("inventory") or DEFAULT_INVENTORY)
        lo = calendar_lo or str(meta.get("calendar_lo") or DEFAULT_LO)
        hi = calendar_hi or str(meta.get("calendar_hi") or DEFAULT_HI)
        scoped = [
            r
            for r in edges
            if lo <= str(r.get("date") or "") <= hi
            and is_main_series(str(r.get("session_id") or ""))
            and in_scope(str(r.get("date") or ""))
        ]
        return scoped, {
            "inventory": inv,
            "calendar_lo": lo,
            "calendar_hi": hi,
            "source": REPIN_DATASET,
            "gate": next(
                (r.get("gate") for r in repin_rows if r.get("record_type") == "summary"),
                meta.get("gate"),
            ),
        }

    recomputed = run_hard_pin_repin(
        inventory=inventory,
        calendar_lo=calendar_lo,
        calendar_hi=calendar_hi,
        concordance=concordance,
    )
    meta = next(r for r in recomputed if r.get("record_type") == "meta")
    edges = [r for r in recomputed if r.get("record_type") == "wire_edge"]
    return edges, {
        "inventory": meta["inventory"],
        "calendar_lo": meta["calendar_lo"],
        "calendar_hi": meta["calendar_hi"],
        "source": "recompute",
        "gate": meta.get("gate"),
    }


def hard_dates_for_session(graph: nx.MultiDiGraph, session_id: str) -> list[str]:
    """Sitting dates claimed for a session via ``PINNED_TO:hard``, else OBSERVED_ON∘DATED_AS."""
    sess = f"session:{session_id}"
    if sess not in graph:
        return []
    hard: list[str] = []
    for u, _v, key, ed in graph.in_edges(sess, keys=True, data=True):
        if ed.get("kind") != PINNED_TO or key != HARD_EDGE_KEY:
            continue
        if graph.nodes[u].get("kind") != "SittingDay":
            continue
        hard.append(str(graph.nodes[u]["obj"].date)[:10])
    if hard:
        return sorted(set(hard))

    composed: list[str] = []
    for _u, scan, ed in graph.out_edges(sess, data=True):
        if ed.get("kind") != OBSERVED_ON:
            continue
        if graph.nodes[scan].get("kind") != "Scan":
            continue
        for _s, day, ed2 in graph.out_edges(scan, data=True):
            if ed2.get("kind") != DATED_AS:
                continue
            if graph.nodes[day].get("kind") != "SittingDay":
                continue
            date = str(graph.nodes[day]["obj"].date)[:10]
            if in_scope(date):
                composed.append(date)
    return sorted(set(composed))


def session_of_htr(graph: nx.MultiDiGraph, htr_node: str) -> str | None:
    """Parent Session of an HtrResolution via CONTAINS."""
    if htr_node not in graph:
        return None
    for u, _v, ed in graph.in_edges(htr_node, data=True):
        if ed.get("kind") == CONTAINS and graph.nodes[u].get("kind") == "Session":
            return str(graph.nodes[u]["obj"].session_id)
    return None


def inherit_date_rows(
    graph: nx.MultiDiGraph,
    *,
    calendar_lo: str,
    calendar_hi: str,
    inventory: str,
) -> list[dict[str, Any]]:
    """ALIGNED_TO → session → hard sitting date (composition report; no PINNED_TO write)."""
    rows: list[dict[str, Any]] = []
    for u, v, key, ed in graph.edges(keys=True, data=True):
        if ed.get("kind") != ALIGNED_TO:
            continue
        if graph.nodes[u].get("kind") != "EnrichedResolution":
            continue
        if graph.nodes[v].get("kind") != "HtrResolution":
            continue
        enriched = graph.nodes[u]["obj"]
        date = str(enriched.date)[:10]
        if not (calendar_lo <= date <= calendar_hi) or not in_scope(date):
            continue
        flat_id = str(graph.nodes[v]["obj"].flat_id)
        if not is_main_series(flat_id):
            continue
        if inventory and f"session-{inventory}-" not in flat_id:
            continue
        sid = session_of_htr(graph, v)
        if sid is None:
            rows.append({
                "record_type": "inherit",
                "editorial_date": date,
                "resolution_index": int(enriched.index),
                "flat_id": flat_id,
                "session_id": None,
                "inherited_dates": [],
                "verdict": "no_session_parent",
                "aligned_key": key,
                "channel": getattr(ed.get("evidence"), "channel", None),
            })
            continue
        inherited = hard_dates_for_session(graph, sid)
        if not inherited:
            verdict = "no_hard_date"
        elif date in inherited:
            verdict = "agree"
        elif len(inherited) == 1:
            verdict = "shift"
        else:
            verdict = "ambiguous_hard"
        rows.append({
            "record_type": "inherit",
            "editorial_date": date,
            "resolution_index": int(enriched.index),
            "flat_id": flat_id,
            "session_id": sid,
            "inherited_dates": inherited,
            "inherited_date": inherited[0] if len(inherited) == 1 else None,
            "verdict": verdict,
            "aligned_key": key,
            "channel": getattr(ed.get("evidence"), "channel", None),
            "observed": bool(getattr(ed.get("evidence"), "observed", False)),
        })
    return rows


def apply_concordance_promote(
    concordance: pd.DataFrame,
    wire_edges: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Set ``resolved_session_id`` on eligible dates; leave paragraph spans unchanged."""
    out = concordance.copy()
    out["enriched_date"] = out["enriched_date"].astype(str).str.slice(0, 10)
    log: list[dict[str, Any]] = []
    for edge in sorted(wire_edges, key=lambda r: str(r.get("date") or "")):
        date = str(edge["date"])[:10]
        sid = str(edge["session_id"])
        if not in_scope(date) or not is_main_series(sid):
            log.append({
                "record_type": "date_wire",
                "date": date,
                "session_id": sid,
                "wired": False,
                "reason": "out_of_scope_or_sidelined",
            })
            continue
        mask = out["enriched_date"] == date
        n = int(mask.sum())
        if n == 0:
            log.append({
                "record_type": "date_wire",
                "date": date,
                "session_id": sid,
                "wired": False,
                "reason": "no_concordance_rows",
                "verdict": edge.get("verdict"),
            })
            continue
        before = (
            out.loc[mask, "resolved_session_id"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        changed = int((out.loc[mask, "resolved_session_id"].astype(str) != sid).sum())
        out.loc[mask, "resolved_session_id"] = sid
        out.loc[mask, "paragraph_prediction_status"] = PRED_STATUS
        log.append({
            "record_type": "date_wire",
            "date": date,
            "session_id": sid,
            "wired": True,
            "reason": "wired",
            "verdict": edge.get("verdict"),
            "n_rows": n,
            "n_changed": changed,
            "prior_sessions": before,
            "production_session": edge.get("production_session"),
        })
    return out, log


def push_production_pins_to_graph(
    graph: nx.MultiDiGraph,
    wire_edges: list[dict[str, Any]],
) -> dict[str, int]:
    """Replace production ``PINNED_TO`` key for promoted dates; leave ``:hard`` intact."""
    dropped = 0
    added = 0
    skipped = 0
    for edge in wire_edges:
        if edge.get("record_type") not in (None, "wire_edge"):
            continue
        date = str(edge.get("date") or "")[:10]
        sid = str(edge.get("session_id") or "")
        if not date or not sid or not in_scope(date) or not is_main_series(sid):
            skipped += 1
            continue
        day = f"day:{date}"
        sess = f"session:{sid}"
        if day not in graph or sess not in graph:
            skipped += 1
            continue
        drop = [
            (u, v, k)
            for u, v, k, d in graph.out_edges(day, keys=True, data=True)
            if d.get("kind") == PINNED_TO and k == PINNED_TO
        ]
        graph.remove_edges_from(drop)
        dropped += len(drop)
        graph.add_edge(
            day,
            sess,
            key=PINNED_TO,
            kind=PINNED_TO,
            evidence=Evidence(
                channel=CHANNEL,
                source="sequence_graph.hard_pin_promote",
                observed=False,
                confidence=None,
                detail={
                    "verdict": edge.get("verdict"),
                    "prior_production_session": edge.get("production_session"),
                    "hard_channel": HARD_CHANNEL,
                    "dated_scans_on_session": list(
                        edge.get("dated_scans_on_session") or []
                    ),
                },
            ),
        )
        added += 1
    return {"dropped": dropped, "added": added, "skipped": skipped}


def run_hard_pin_promote(
    *,
    repin_rows: list[dict[str, Any]] | None = None,
    concordance: pd.DataFrame | None = None,
    graph: nx.MultiDiGraph | None = None,
    inventory: str | None = None,
    calendar_lo: str | None = None,
    calendar_hi: str | None = None,
) -> list[dict[str, Any]]:
    if concordance is None:
        concordance = load(CONCORDANCE)
    edges, ctx = _wire_edges_from_repin(
        repin_rows,
        inventory=inventory,
        calendar_lo=calendar_lo,
        calendar_hi=calendar_hi,
        concordance=concordance,
    )
    mono = hard_pins_monotone(edges)
    by_verdict = Counter(r.get("verdict") for r in edges)
    eligible_dates = {str(r["date"]) for r in edges}
    before_slice = slice_separated(concordance, eligible_dates)
    uniform_slice = uniform_separated_on_dates(concordance, eligible_dates)
    before_corpus = separated_total(concordance)

    # Preview concordance Δ (session id only; placements unchanged ⇒ Δ sep = 0)
    preview, wire_log = apply_concordance_promote(concordance, edges)
    after_slice = slice_separated(preview, eligible_dates)
    after_corpus = separated_total(preview)

    if graph is None:
        try:
            graph = load_graph()
        except Exception:
            graph = None
    inherit: list[dict[str, Any]] = []
    if graph is not None:
        inherit = inherit_date_rows(
            graph,
            calendar_lo=ctx["calendar_lo"],
            calendar_hi=ctx["calendar_hi"],
            inventory=ctx["inventory"],
        )
    inherit_by = Counter(r.get("verdict") for r in inherit)

    gate_ok = mono["ok"] and len(edges) > 0
    # Separated must not fall (placements unchanged ⇒ expect Δ=0)
    sep_ok = (
        after_slice["separated"] >= before_slice["separated"]
        and after_corpus >= before_corpus
    )
    gate = "PASS" if gate_ok and sep_ok else "FAIL"

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "hard_pin_promote",
            "edge": PINNED_TO,
            "edge_key": PINNED_TO,
            "hard_edge_key": HARD_EDGE_KEY,
            "channel": CHANNEL,
            "inventory": ctx["inventory"],
            "calendar_lo": ctx["calendar_lo"],
            "calendar_hi": ctx["calendar_hi"],
            "repin_source": ctx["source"],
            "n_wire_edges": len(edges),
            "n_shift": by_verdict.get("shift", 0),
            "n_new_pin": by_verdict.get("new_pin", 0),
            "n_agree": by_verdict.get("agree", 0),
            "monotone_ok": mono["ok"],
            "n_monotone_violations": mono["n_violations"],
            "before_slice_separated": before_slice["separated"],
            "after_slice_separated": after_slice["separated"],
            "delta_slice_separated": after_slice["separated"] - before_slice["separated"],
            "before_corpus_separated": before_corpus,
            "after_corpus_separated": after_corpus,
            "delta_corpus_separated": after_corpus - before_corpus,
            "uniform_slice_separated": uniform_slice["separated"],
            "delta_separated_vs_uniform": (
                before_slice["separated"] - uniform_slice["separated"]
            ),
            "n_inherit_rows": len(inherit),
            "inherit_verdicts": dict(inherit_by),
            "policy": (
                "Scoped production PINNED_TO promote from PINNED_TO:hard on seed. "
                "Concordance resolved_session_id moves; paragraph placements unchanged. "
                "Gate = hard + monotone (+ separated non-decrease). Content re-align is "
                "not a gate. Inherit-date = ALIGNED_TO∘session∘hard composition report "
                "only — never writes PINNED_TO."
            ),
            "gate": gate,
            **scope_meta(),
        },
        *edges,
        *wire_log,
        {"record_type": "monotone", **mono},
        {
            "record_type": "separated_guard",
            "slice_dates": sorted(eligible_dates),
            "before": before_slice,
            "after": after_slice,
            "uniform_null": uniform_slice,
            "delta_separated": after_slice["separated"] - before_slice["separated"],
            "note": (
                "Session-id rewrite only; Δ separated expected 0. "
                "before vs uniform is the standing-guard snapshot."
            ),
        },
        *inherit,
        {
            "record_type": "inherit_summary",
            "n_rows": len(inherit),
            "verdicts": dict(inherit_by),
            "note": (
                "Sitting date inherited from session hard path; content selects "
                "session via ALIGNED_TO, dating rides archival claim set."
            ),
        },
        {
            "record_type": "summary",
            "n_wire_edges": len(edges),
            "n_shift": by_verdict.get("shift", 0),
            "n_new_pin": by_verdict.get("new_pin", 0),
            "n_agree": by_verdict.get("agree", 0),
            "n_dates_wired_preview": sum(1 for r in wire_log if r.get("wired")),
            "monotone_ok": mono["ok"],
            "before_slice_separated": before_slice["separated"],
            "after_slice_separated": after_slice["separated"],
            "delta_slice_separated": after_slice["separated"] - before_slice["separated"],
            "before_corpus_separated": before_corpus,
            "after_corpus_separated": after_corpus,
            "n_inherit_rows": len(inherit),
            "gate": gate,
            "next": (
                "Re-run with --wire --push-graph to overwrite concordance "
                "resolved_session_id and production PINNED_TO key on the saved graph. "
                "Snapshot first if desired: "
                "`uv run python -m sequence_graph.persist --snapshot before_hard_pin_promote`."
            ),
        },
    ]
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--write", action="store_true", help=f"persist {OUTPUT_DATASET}")
    parser.add_argument(
        "--wire",
        action="store_true",
        help=f"rewrite {CONCORDANCE} resolved_session_id for promoted dates",
    )
    parser.add_argument(
        "--push-graph",
        action="store_true",
        help="overwrite production PINNED_TO key on the saved graph",
    )
    parser.add_argument("--inventory", default=None)
    parser.add_argument("--calendar-lo", default=None)
    parser.add_argument("--calendar-hi", default=None)
    args = parser.parse_args(argv)

    rows = run_hard_pin_promote(
        inventory=args.inventory,
        calendar_lo=args.calendar_lo,
        calendar_hi=args.calendar_hi,
    )
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    inherit_sum = next(r for r in rows if r.get("record_type") == "inherit_summary")
    print(
        f"hard_pin_promote  gate={summary['gate']}  "
        f"edges={summary['n_wire_edges']}  "
        f"shift={summary['n_shift']} new={summary['n_new_pin']} "
        f"agree={summary['n_agree']}  "
        f"monotone={summary['monotone_ok']}"
    )
    print(
        f"  separated: slice {summary['before_slice_separated']}→"
        f"{summary['after_slice_separated']} "
        f"(Δ{summary['delta_slice_separated']:+d}); "
        f"corpus {summary['before_corpus_separated']}→"
        f"{summary['after_corpus_separated']}"
    )
    print(
        f"  inherit-date: n={inherit_sum['n_rows']}  "
        f"verdicts={inherit_sum['verdicts']}"
    )
    print(f"  next: {summary.get('next')}")
    print(f"  records: {dict(Counter(r.get('record_type') for r in rows))}")

    if args.write:
        path = save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[REPIN_DATASET, CONCORDANCE],
        )
        from sequence_graph.remediation_run_log import log_hard_pin_promote

        log_hard_pin_promote(rows)
        print(f"wrote {path}")

    if args.wire or args.push_graph:
        if summary["gate"] != "PASS":
            raise SystemExit(
                f"refusing mutation: gate={summary['gate']} "
                f"(monotone_ok={summary['monotone_ok']}, "
                f"n_wire={summary['n_wire_edges']})"
            )

    if args.wire:
        edges = [r for r in rows if r.get("record_type") == "wire_edge"]
        before = load(CONCORDANCE)
        after, _log = apply_concordance_promote(before, edges)
        save_parquet(
            after,
            logical_name=CONCORDANCE,
            script=__file__,
            parent_sources=[CONCORDANCE, REPIN_DATASET, OUTPUT_DATASET],
            description=(
                "resolution_concordance after scoped hard_pin_promote: "
                f"resolved_session_id rewritten for {meta['inventory']} "
                f"{meta['calendar_lo']}..{meta['calendar_hi']} from "
                "PINNED_TO:hard beads; paragraph spans unchanged."
            ),
        )
        print(
            f"wired concordance: {summary['n_dates_wired_preview']} dates → "
            f"resolved_session_id from hard beads"
        )

    if args.push_graph:
        edges = [r for r in rows if r.get("record_type") == "wire_edge"]
        graph = load_graph()
        stats = push_production_pins_to_graph(graph, edges)
        save_loaded_graph(graph)
        print(
            f"pushed production PINNED_TO: added={stats['added']} "
            f"dropped={stats['dropped']} skipped={stats['skipped']}"
        )


if __name__ == "__main__":
    main()

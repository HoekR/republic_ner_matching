"""Minimal remediation proof — ablation on annotated stretch claim corrections.

Working hypothesis (3185 late Aug): production pins lag physical by a near-constant
session Δ (~+8); review date↔scan claims agree with physical. The minimal correction
is one stretch-local pin policy, not N day patches.

How we know:
  * **Sufficient** — every review-held day is entailed by the active pin channel
    (review scan ∈ OBSERVED_ON of the active session).
  * **Minimal** — among sufficient candidates, smallest description size; necessity
    controls (subset / wrong-sign / prefer production) fail sufficiency.

No production PINNED_TO wire. Claim-policy overlay only.

Usage:
    uv run python -m sequence_graph.minimal_remediation
    uv run python -m sequence_graph.minimal_remediation --write
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter
from typing import Any, Callable

import networkx as nx

from data_io import save_semi_structured
from scripts.corpus_scope import scope_meta
from sequence_graph.correspondence import OBSERVED_ON
from sequence_graph.persist import load_graph
from sequence_graph.problem_sequence_review import load_notes
from sequence_graph.stretch_viz_export import (
    _observed_scans,
    _session_num,
    build_stretch_payload,
    window_from_notes,
)

OUTPUT_DATASET = "minimal_remediation_proof"

# Candidate description sizes (smaller = more minimal among sufficient).
SIZE = {
    "A_prefer_physical": 1,
    "B_constant_delta": 1,
    "C_review_patches": 3,
    "D_physical_plus_parse": 2,
    "ctrl_prefer_production": 1,
    "ctrl_wrong_sign_delta": 1,
    "ctrl_review_subset_1": 1,
}


def _session_id(inventory: str, num: int) -> str:
    return f"session-{inventory}-num-{num}"


def _observed_for_session(
    graph: nx.MultiDiGraph, session_id: str | None, inventory: str
) -> set[int]:
    return set(_observed_scans(graph, session_id, inventory))


def _active_session_clears_review(
    graph: nx.MultiDiGraph,
    day: dict[str, Any],
    active_session: str | None,
    inventory: str,
) -> bool:
    """Review scan must sit on the active session's OBSERVED_ON folios."""
    claims = day.get("review_claims") or []
    if not claims:
        return True
    if not active_session:
        return False
    scans = _observed_for_session(graph, active_session, inventory)
    return all(int(c["scan_num"]) in scans for c in claims)


def _pin_disagree(day: dict[str, Any]) -> bool:
    prod, phys = day.get("production_session"), day.get("physical_session")
    return bool(prod and phys and prod != phys)


def _median_delta(days: list[dict[str, Any]]) -> int:
    deltas = [
        int(d["pin_delta"])
        for d in days
        if d.get("pin_delta") is not None and _pin_disagree(d)
    ]
    if not deltas:
        return 0
    return int(statistics.median(deltas))


def _offset_session(
    inventory: str,
    production: str | None,
    delta: int,
    graph: nx.MultiDiGraph,
) -> str | None:
    if not production:
        return None
    n = _session_num(production)
    if n is None:
        return None
    sid = _session_id(inventory, n + delta)
    node = f"session:{sid}"
    if node not in graph:
        return None
    if graph.nodes[node]["obj"].inventory != inventory:
        return None
    return sid


ActiveFn = Callable[[dict[str, Any]], str | None]


def _eval_candidate(
    *,
    candidate_id: str,
    label: str,
    days: list[dict[str, Any]],
    review_days: list[dict[str, Any]],
    graph: nx.MultiDiGraph,
    inventory: str,
    active_fn: ActiveFn,
    size: int,
) -> dict[str, Any]:
    cleared: list[str] = []
    failed: list[str] = []
    for day in review_days:
        active = active_fn(day)
        ok = _active_session_clears_review(graph, day, active, inventory)
        if ok:
            cleared.append(day["date"])
        else:
            failed.append(day["date"])

    # Residual conflicts under active policy: active ≠ physical when both exist,
    # or review not cleared. Report pin-disagree residual vs physical.
    residual_pin = 0
    residual_dates: list[str] = []
    for day in days:
        if not _pin_disagree(day):
            continue
        active = active_fn(day)
        phys = day.get("physical_session")
        if active != phys:
            residual_pin += 1
            residual_dates.append(day["date"])

    n_review = len(review_days)
    n_cleared = len(cleared)
    sufficient = n_review > 0 and n_cleared == n_review
    return {
        "record_type": "candidate",
        "candidate_id": candidate_id,
        "label": label,
        "size": size,
        "n_review": n_review,
        "n_review_cleared": n_cleared,
        "review_cleared_dates": cleared,
        "review_failed_dates": failed,
        "sufficient": sufficient,
        "residual_pin_disagree_vs_physical": residual_pin,
        "residual_dates_sample": residual_dates[:12],
        "claim_set": candidate_id,
    }


def run_ablation(graph: nx.MultiDiGraph | None = None) -> list[dict[str, Any]]:
    notes = load_notes()
    window = window_from_notes(notes)
    inventory = window["inventory"]
    graph = graph or load_graph()
    payload = build_stretch_payload(
        graph,
        inventory=inventory,
        calendar_lo=window["calendar_lo"],
        calendar_hi=window["calendar_hi"],
        sess_lo=window.get("sess_lo"),
        sess_hi=window.get("sess_hi"),
    )
    days = payload["days"]
    review_days = [d for d in days if d.get("review_claims")]
    pin_dis_days = [d for d in days if _pin_disagree(d)]
    delta = _median_delta(days)
    delta_hist = Counter(
        int(d["pin_delta"]) for d in pin_dis_days if d.get("pin_delta") is not None
    )

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "inventory": inventory,
            "calendar_lo": window["calendar_lo"],
            "calendar_hi": window["calendar_hi"],
            "display_lo": payload["meta"]["display_lo"],
            "display_hi": payload["meta"]["display_hi"],
            "n_days": len(days),
            "n_conflicts": payload["meta"]["n_conflicts"],
            "n_pin_disagree": len(pin_dis_days),
            "n_review": len(review_days),
            "median_pin_delta": delta,
            "pin_delta_hist": {str(k): v for k, v in sorted(delta_hist.items())},
            "review_dates": [d["date"] for d in review_days],
            "policy": (
                "Ablation of stretch-local pin corrections vs review-held days. "
                "Sufficient = all review scans on active session OBSERVED_ON. "
                "Minimal = smallest sufficient candidate; controls must fail. "
                "No production PINNED_TO wire."
            ),
            **scope_meta(),
        }
    ]

    # --- candidates ---
    def active_A(day: dict[str, Any]) -> str | None:
        return day.get("physical_session") or day.get("production_session")

    def active_B(day: dict[str, Any]) -> str | None:
        return _offset_session(
            inventory, day.get("production_session"), delta, graph
        ) or day.get("production_session")

    review_scan_to_session: dict[tuple[str, int], str | None] = {}
    for day in review_days:
        for c in day["review_claims"]:
            scan = int(c["scan_num"])
            # session that observes this scan
            sid = None
            sn = f"scan:{inventory}:{scan}"
            if sn in graph:
                for u, _v, ed in graph.in_edges(sn, data=True):
                    if ed.get("kind") != OBSERVED_ON:
                        continue
                    if graph.nodes[u].get("kind") != "Session":
                        continue
                    sid = graph.nodes[u]["obj"].session_id
                    break
            review_scan_to_session[(day["date"], scan)] = sid

    def active_C(day: dict[str, Any]) -> str | None:
        claims = day.get("review_claims") or []
        if not claims:
            return day.get("production_session")
        # Prefer physical if it clears; else session from review scan OBSERVED_ON
        phys = day.get("physical_session")
        if phys and _active_session_clears_review(graph, day, phys, inventory):
            return phys
        for c in claims:
            sid = review_scan_to_session.get((day["date"], int(c["scan_num"])))
            if sid:
                return sid
        return day.get("production_session")

    # D: prefer physical; parse override stub for 08-31 diagnosis (date identity only —
    # does not change active session unless physical missing). Same as A for pins.
    def active_D(day: dict[str, Any]) -> str | None:
        return active_A(day)

    # Controls
    def active_prod(day: dict[str, Any]) -> str | None:
        return day.get("production_session")

    def active_wrong_sign(day: dict[str, Any]) -> str | None:
        return _offset_session(
            inventory, day.get("production_session"), -delta, graph
        ) or day.get("production_session")

    # Necessity: only first review day patched; others stay production
    subset_date = review_days[0]["date"] if review_days else None

    def active_subset(day: dict[str, Any]) -> str | None:
        if day["date"] == subset_date:
            return active_C(day)
        return day.get("production_session")

    specs: list[tuple[str, str, ActiveFn, int]] = [
        ("A_prefer_physical", "prefer PINNED_TO:physical in window", active_A, SIZE["A_prefer_physical"]),
        (
            "B_constant_delta",
            f"production session_num + median Δ ({delta})",
            active_B,
            SIZE["B_constant_delta"],
        ),
        ("C_review_patches", "review claims only (per-day patches)", active_C, SIZE["C_review_patches"]),
        (
            "D_physical_plus_parse",
            "prefer physical + parse overrides (08-31 class; pin path = A)",
            active_D,
            SIZE["D_physical_plus_parse"],
        ),
        (
            "ctrl_prefer_production",
            "control: keep production pins",
            active_prod,
            SIZE["ctrl_prefer_production"],
        ),
        (
            "ctrl_wrong_sign_delta",
            f"control: production − median Δ ({-delta})",
            active_wrong_sign,
            SIZE["ctrl_wrong_sign_delta"],
        ),
        (
            "ctrl_review_subset_1",
            f"control: patch only {subset_date}",
            active_subset,
            SIZE["ctrl_review_subset_1"],
        ),
    ]

    candidate_rows: list[dict[str, Any]] = []
    for cid, label, fn, size in specs:
        candidate_rows.append(
            _eval_candidate(
                candidate_id=cid,
                label=label,
                days=days,
                review_days=review_days,
                graph=graph,
                inventory=inventory,
                active_fn=fn,
                size=size,
            )
        )

    sufficient = [r for r in candidate_rows if r["sufficient"] and not r["candidate_id"].startswith("ctrl_")]
    # Minimal among sufficient: smallest size; tie-break prefer A over B over C over D
    preference = {
        "A_prefer_physical": 0,
        "B_constant_delta": 1,
        "D_physical_plus_parse": 2,
        "C_review_patches": 3,
    }
    minimal_id: str | None = None
    if sufficient:
        sufficient_sorted = sorted(
            sufficient,
            key=lambda r: (r["size"], preference.get(r["candidate_id"], 99)),
        )
        minimal_id = sufficient_sorted[0]["candidate_id"]

    controls_ok = all(
        (not r["sufficient"])
        for r in candidate_rows
        if r["candidate_id"].startswith("ctrl_")
    )

    for r in candidate_rows:
        r["minimal"] = r["candidate_id"] == minimal_id
        r["controls_fail_as_required"] = controls_ok

    verdict = {
        "record_type": "verdict",
        "sufficient_candidates": [r["candidate_id"] for r in sufficient],
        "minimal_candidate": minimal_id,
        "controls_fail_as_required": controls_ok,
        "knowability": (
            "Remediation = all review-held days cleared under active claim set. "
            "Minimality = smallest sufficient non-control candidate; "
            "controls (production / wrong-sign / review subset) must fail."
        ),
        "hypothesis": (
            "Constant pin lag: prefer physical (A) or +median Δ (B) remediates; "
            "per-day review patches (C) are sufficient but not minimal if A/B pass."
        ),
    }
    rows.extend(candidate_rows)
    rows.append(verdict)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"persist JSONL to {OUTPUT_DATASET}",
    )
    args = parser.parse_args()
    rows = run_ablation()
    meta = next(r for r in rows if r["record_type"] == "meta")
    verdict = next(r for r in rows if r["record_type"] == "verdict")
    print(
        f"window {meta['inventory']} {meta['calendar_lo']}..{meta['calendar_hi']}  "
        f"pin_disagree={meta['n_pin_disagree']} review={meta['n_review']}  "
        f"median_Δ={meta['median_pin_delta']} hist={meta['pin_delta_hist']}"
    )
    print(f"{'candidate':<28} {'cleared':>8} {'suff':>5} {'resid':>6} {'min':>4}  label")
    for r in rows:
        if r["record_type"] != "candidate":
            continue
        print(
            f"{r['candidate_id']:<28} "
            f"{r['n_review_cleared']}/{r['n_review']:<6} "
            f"{'yes' if r['sufficient'] else 'no':>5} "
            f"{r['residual_pin_disagree_vs_physical']:>6} "
            f"{'YES' if r['minimal'] else '':>4}  "
            f"{r['label']}"
        )
    print(
        f"\nverdict: minimal={verdict['minimal_candidate']}  "
        f"sufficient={verdict['sufficient_candidates']}  "
        f"controls_fail={verdict['controls_fail_as_required']}"
    )
    if args.write:
        save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=(
                "Minimal remediation ablation on annotated stretch: candidates "
                "prefer-physical / constant-Δ / review-patches vs review-held days; "
                "controls must fail. No production PINNED_TO wire."
            ),
            parent_sources=["problem_sequence_review_notes", "sequence_graph_edges"],
        )
        print(f"wrote {OUTPUT_DATASET}")


if __name__ == "__main__":
    main()

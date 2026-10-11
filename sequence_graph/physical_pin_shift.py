"""Propose PINNED_TO from the physical track, then remeasure sync gaps.

Order (user, 2026-10-09): session boundaries from OBSERVED_ON / scan NEXT; DATED_AS on
those scans gives sitting→session without text. Apply unique physical maps as pin
overrides; rebuild broad sync gaps; show undated sessions moving between brackets.

Production ``PINNED_TO`` (key ``PINNED_TO``) is never overwritten here. Staging writes
parallel ``PINNED_TO:physical`` edges (observed=False). Gap remeasure uses an in-memory
override set (production dates relocated onto unique physical sessions).

Date trust (user, 2026-10-09): human review judges **calendar date on scan** only.
``session_num`` is a parsing artefact and must not score trust. Approved dates form the
trust set for staged physical pins; rejected dates are excluded from overrides. Still no
production wire. After trusted overrides, inventory **text inside** the new brackets
(unaligned editorial mass vs HTR paragraphs) — alignment itself is a later step.

Usage:
    uv run python -m sequence_graph.physical_pin_shift --propose --remeasure
    uv run python -m sequence_graph.physical_pin_shift --propose --remeasure --stage
    uv run python -m sequence_graph.physical_pin_shift --trust-approvals --write
    uv run python -m sequence_graph.physical_pin_shift --trust-approvals --annotate-graph --write
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from typing import Any

import networkx as nx

from data_io import load, save_semi_structured
from scripts.corpus_scope import is_main_series, scope_meta
from sequence_graph.correspondence import ALIGNED_TO, Evidence, PINNED_TO
from sequence_graph.persist import load_graph, save_loaded_graph
from sequence_graph.physical_extents import (
    PROOF_DATED_DAY,
    PROOF_DATED_SESSION,
    PROOF_UNDATED_SESSION,
    build_extents,
    dated_day_to_sessions,
)
from sequence_graph.sync_gaps import SessionPin, pinned_sessions

OUTPUT_DATASET = "session_anchor_shift_proposals"
TRUST_DATASET = "session_anchor_shift_date_trust"
APPROVALS_DATASET = "session_anchor_shift_approvals"
PHYSICAL_PIN_KEY = f"{PINNED_TO}:physical"


def _session_num(session_id: str) -> int:
    m = re.search(r"num-(\d+)", session_id)
    if not m:
        raise ValueError(session_id)
    return int(m.group(1))


def _inventory(session_id: str) -> str:
    m = re.search(r"session-(\d+)-num-", session_id)
    if not m:
        raise ValueError(session_id)
    return m.group(1)


def production_date_to_session(graph: nx.MultiDiGraph) -> dict[str, str]:
    """SittingDay date → production PINNED_TO session (main series only; last wins if multi)."""
    out: dict[str, str] = {}
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "SittingDay":
            continue
        date = data["obj"].date
        for _u, v, key, ed in graph.out_edges(node_id, keys=True, data=True):
            if ed.get("kind") != PINNED_TO or key != PINNED_TO:
                continue
            if graph.nodes[v].get("kind") != "Session":
                continue
            sid = graph.nodes[v]["obj"].session_id
            if is_main_series(sid):
                out[date] = sid
    return out


def propose_physical_pins(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    """One row per SittingDay with a unique physical session (DATED_AS→scan→OBSERVED_ON)."""
    physical = dated_day_to_sessions(graph)
    production = production_date_to_session(graph)
    rows: list[dict[str, Any]] = []
    for date, sessions in sorted(physical.items()):
        if len(sessions) != 1:
            rows.append({
                "record_type": "proposal",
                "date": date,
                "verdict": "ambiguous_physical" if len(sessions) > 1 else "no_physical",
                "physical_sessions": sessions,
                "proposed_session": None,
                "production_session": production.get(date),
                "gate_eligible": False,
            })
            continue
        proposed = sessions[0]
        prod = production.get(date)
        if prod is None:
            verdict = "new_pin"
        elif prod == proposed:
            verdict = "agree"
        else:
            verdict = "shift"
        rows.append({
            "record_type": "proposal",
            "date": date,
            "verdict": verdict,
            "physical_sessions": sessions,
            "proposed_session": proposed,
            "production_session": prod,
            "gate_eligible": verdict in ("new_pin", "shift", "agree"),
            "inventory": _inventory(proposed),
        })
    return rows


def gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_v: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["record_type"] != "proposal":
            continue
        by_v[r["verdict"]] += 1
    hit = next((r for r in rows if r.get("date") == PROOF_DATED_DAY), None)
    hit_ok = bool(
        hit
        and hit.get("proposed_session") == PROOF_DATED_SESSION
        and hit.get("verdict") in ("shift", "agree", "new_pin")
    )
    return {
        "record_type": "gate",
        "channel": "physical_DATED_AS_OBSERVED_ON",
        "verdicts": dict(by_v),
        "n_eligible": sum(1 for r in rows if r.get("gate_eligible")),
        "n_shift": by_v.get("shift", 0),
        "n_new_pin": by_v.get("new_pin", 0),
        "n_agree": by_v.get("agree", 0),
        "validation_date": PROOF_DATED_DAY,
        "validation_expected_session": PROOF_DATED_SESSION,
        "validation_row": hit,
        "validation_ok": hit_ok,
        "review_policy": (
            "Unique physical sitting→session only; never overwrites production PINNED_TO key; "
            "staging uses PINNED_TO:physical; text unused."
        ),
        **scope_meta(),
    }


def override_pins(
    production: list[SessionPin],
    proposals: list[dict[str, Any]],
) -> list[SessionPin]:
    """Relocate proposal dates onto proposed sessions; drop empty pin sets."""
    by_sess: dict[str, set[str]] = {
        p.session_id: set(p.pinned_dates) for p in production
    }
    meta = {
        p.session_id: (p.inventory, p.session_num) for p in production
    }
    for row in proposals:
        if not row.get("gate_eligible") or not row.get("proposed_session"):
            continue
        if row["verdict"] == "agree":
            continue  # already correct
        date = row["date"]
        proposed = row["proposed_session"]
        for sid in list(by_sess):
            by_sess[sid].discard(date)
        by_sess.setdefault(proposed, set()).add(date)
        if proposed not in meta:
            meta[proposed] = (_inventory(proposed), _session_num(proposed))
    out: list[SessionPin] = []
    for sid, dates in by_sess.items():
        if not dates:
            continue
        inv, num = meta[sid]
        out.append(
            SessionPin(
                session_id=sid,
                inventory=inv,
                session_num=num,
                pinned_dates=tuple(sorted(dates)),
            )
        )
    return sorted(out, key=lambda p: (p.inventory, p.session_num))


def gaps_from_pins(graph: nx.MultiDiGraph, pins: list[SessionPin]) -> list[dict[str, Any]]:
    """Same geometry as sync_gaps.build_broad_gaps, but with an explicit pin list."""
    from sequence_graph.sync_gaps import (
        _day_has_main_production_pin,
        _k_e_in_date_span,
        _paragraph_count,
        _sessions_in_inventory,
    )

    pins_by_inv: dict[str, list[SessionPin]] = defaultdict(list)
    for p in pins:
        pins_by_inv[p.inventory].append(p)

    gaps: list[dict[str, Any]] = []
    for inventory, inv_pins in sorted(pins_by_inv.items()):
        inv_pins = sorted(inv_pins, key=lambda p: p.session_num)
        all_sess = _sessions_in_inventory(graph, inventory)
        num_to_node = {num: node for num, _sid, node in all_sess}
        for left, right in zip(inv_pins, inv_pins[1:]):
            if right.session_num <= left.session_num:
                continue
            lo_date = min(left.pinned_dates)
            hi_date = max(right.pinned_dates)
            interior = [
                (num, sid, num_to_node[num])
                for num, sid, _ in all_sess
                if left.session_num <= num <= right.session_num
            ]
            htr_paras = sum(_paragraph_count(graph, node) for _n, _s, node in interior)
            n_meetings, k_e = _k_e_in_date_span(graph, lo_date, hi_date)
            unsynced = 0
            for node_id, data in graph.nodes(data=True):
                if data.get("kind") != "SittingDay":
                    continue
                date = data["obj"].date
                if not (lo_date <= date <= hi_date):
                    continue
                if _day_has_main_production_pin(graph, node_id):
                    continue
                unsynced += 1
            gaps.append({
                "inventory": inventory,
                "anchor_lo_session": left.session_id,
                "anchor_hi_session": right.session_id,
                "calendar_lo": lo_date,
                "calendar_hi": hi_date,
                "n_htr_sessions_inclusive": len(interior),
                "interior_session_ids": [sid for _n, sid, _ in interior],
                "charge_k_e": k_e,
                "charge_htr_paras": htr_paras,
                "n_meetings_no_production_pin_in_span": unsynced,
            })
    return gaps


def load_date_trust() -> dict[str, Any]:
    """Approved / rejected calendar dates from the review notebook (date-only judgment)."""
    approved: set[str] = set()
    rejected: set[str] = set()
    deferred: set[str] = set()
    notes: dict[str, str] = {}
    try:
        rows = list(load(APPROVALS_DATASET))
    except FileNotFoundError:
        rows = []
    for r in rows:
        if r.get("record_type") != "approval":
            continue
        day = r.get("dated_day")
        if not day:
            continue
        action = r.get("action")
        if action == "approve":
            approved.add(str(day))
        elif action == "reject":
            rejected.add(str(day))
        elif action == "defer":
            deferred.add(str(day))
        note = (r.get("note") or "").strip()
        if note:
            notes[str(day)] = note
    # reject wins if both somehow present
    approved -= rejected
    return {
        "approved_dates": sorted(approved),
        "rejected_dates": sorted(rejected),
        "deferred_dates": sorted(deferred),
        "notes_by_date": notes,
        "n_approved": len(approved),
        "n_rejected": len(rejected),
        "n_deferred": len(deferred),
    }


def apply_date_trust_to_proposals(
    proposals: list[dict[str, Any]],
    *,
    approved: set[str],
    rejected: set[str],
) -> list[dict[str, Any]]:
    """Annotate proposals; only approved dates stay gate_eligible for trusted overrides.

    Trust is by **date**, never by session_num. Ambiguous / no_physical rows stay ineligible.
    """
    out: list[dict[str, Any]] = []
    for row in proposals:
        if row.get("record_type") != "proposal":
            out.append(row)
            continue
        date = str(row["date"])
        if date in rejected:
            trust = "rejected"
        elif date in approved:
            trust = "approved"
        else:
            trust = "unreviewed"
        eligible = bool(row.get("gate_eligible")) and trust == "approved"
        rec = dict(row)
        rec["date_trust"] = trust
        rec["gate_eligible"] = eligible
        rec["trust_gate_eligible"] = eligible
        out.append(rec)
    return out


def _gap_key(g: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(g["inventory"]),
        str(g["anchor_lo_session"]),
        str(g["anchor_hi_session"]),
        str(g["calendar_lo"]),
        str(g["calendar_hi"]),
    )


def new_bracket_gaps(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Gaps present after trusted overrides that were not in the production geometry."""
    before_keys = {_gap_key(g) for g in before}
    return [g for g in after if _gap_key(g) not in before_keys]


def text_inside_brackets(
    graph: nx.MultiDiGraph,
    gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Editorial vs HTR text mass inside brackets — inventory only, no DP / no session scoring."""
    rows: list[dict[str, Any]] = []
    for g in gaps:
        lo, hi = g["calendar_lo"], g["calendar_hi"]
        n_enriched = 0
        n_aligned = 0
        for node_id, data in graph.nodes(data=True):
            if data.get("kind") != "SittingDay":
                continue
            date = data["obj"].date
            if not (lo <= date <= hi):
                continue
            for _u, v, ed in graph.out_edges(node_id, data=True):
                if ed.get("kind") != "CONTAINS":
                    continue
                if graph.nodes[v].get("kind") != "EnrichedResolution":
                    continue
                n_enriched += 1
                if any(
                    aed.get("kind") == ALIGNED_TO
                    for _x, _y, _k, aed in graph.out_edges(v, keys=True, data=True)
                ):
                    n_aligned += 1
        rows.append({
            "record_type": "text_inside",
            "inventory": g["inventory"],
            "calendar_lo": lo,
            "calendar_hi": hi,
            "anchor_lo_session": g["anchor_lo_session"],
            "anchor_hi_session": g["anchor_hi_session"],
            "charge_k_e": g["charge_k_e"],
            "charge_htr_paras": g.get("charge_htr_paras"),
            "n_htr_sessions_inclusive": g["n_htr_sessions_inclusive"],
            "n_enriched": n_enriched,
            "n_aligned": n_aligned,
            "n_unaligned": n_enriched - n_aligned,
            "n_meetings_no_production_pin_in_span": g.get(
                "n_meetings_no_production_pin_in_span"
            ),
        })
    rows.sort(
        key=lambda r: (
            -(r["n_unaligned"] or 0),
            -(r["charge_k_e"] or 0),
            r["inventory"],
            r["calendar_lo"],
        )
    )
    return rows


def annotate_physical_date_trust(
    graph: nx.MultiDiGraph,
    *,
    approved: set[str],
    rejected: set[str],
) -> dict[str, int]:
    """Stamp ``date_trust`` on staged PINNED_TO:physical edges. No production wire."""
    counts = {"approved": 0, "rejected": 0, "unreviewed": 0}
    for u, v, k, d in list(graph.edges(keys=True, data=True)):
        if d.get("kind") != PINNED_TO or k != PHYSICAL_PIN_KEY:
            continue
        if graph.nodes[u].get("kind") != "SittingDay":
            continue
        date = str(graph.nodes[u]["obj"].date)
        if date in rejected:
            trust = "rejected"
        elif date in approved:
            trust = "approved"
        else:
            trust = "unreviewed"
        counts[trust] += 1
        old = d.get("evidence")
        detail = dict(getattr(old, "detail", None) or {})
        detail["date_trust"] = trust
        detail["trust_by"] = "approved_calendar_date"
        graph.edges[u, v, k]["evidence"] = Evidence(
            channel=getattr(old, "channel", None) or "physical_dated_as_observed_on",
            source=getattr(old, "source", None) or "sequence_graph.physical_pin_shift",
            observed=False,
            confidence=getattr(old, "confidence", None),
            detail=detail,
        )
    return counts


def gap_containing_session(gaps: list[dict[str, Any]], session_id: str) -> dict[str, Any] | None:
    for g in gaps:
        if session_id in (g.get("interior_session_ids") or []):
            return g
        # also match anchors
        if session_id in (g.get("anchor_lo_session"), g.get("anchor_hi_session")):
            return g
    return None


def stage_physical_edges(graph: nx.MultiDiGraph, proposals: list[dict[str, Any]]) -> int:
    """Write PINNED_TO:physical for shift/new_pin (and agree, for completeness)."""
    # drop prior physical proposal edges
    drop = [
        (u, v, k)
        for u, v, k, d in graph.edges(keys=True, data=True)
        if d.get("kind") == PINNED_TO and k == PHYSICAL_PIN_KEY
    ]
    graph.remove_edges_from(drop)
    n = 0
    for row in proposals:
        if row.get("verdict") not in ("shift", "new_pin", "agree"):
            continue
        proposed = row.get("proposed_session")
        if not proposed:
            continue
        u = f"day:{row['date']}"
        v = f"session:{proposed}"
        if u not in graph or v not in graph:
            continue
        graph.add_edge(
            u,
            v,
            key=PHYSICAL_PIN_KEY,
            kind=PINNED_TO,
            evidence=Evidence(
                channel="physical_dated_as_observed_on",
                source="sequence_graph.physical_pin_shift",
                observed=False,
                confidence=None,
                detail={
                    "verdict": row["verdict"],
                    "production_session": row.get("production_session"),
                },
            ),
        )
        n += 1
    return n


def remeasure(
    graph: nx.MultiDiGraph,
    proposals: list[dict[str, Any]],
    *,
    stretch_sessions: list[str] | None = None,
) -> dict[str, Any]:
    production = pinned_sessions(graph)
    # annotate production gaps with interior ids
    before = gaps_from_pins(graph, production)
    after_pins = override_pins(production, proposals)
    after = gaps_from_pins(graph, after_pins)

    focus = stretch_sessions or [PROOF_UNDATED_SESSION]
    membership: list[dict[str, Any]] = []
    for sid in focus:
        b = gap_containing_session(before, sid)
        a = gap_containing_session(after, sid)
        membership.append({
            "session_id": sid,
            "before": None
            if b is None
            else {
                "anchors": f"{b['anchor_lo_session']}|{b['anchor_hi_session']}",
                "calendar": f"{b['calendar_lo']}..{b['calendar_hi']}",
                "k_e": b["charge_k_e"],
            },
            "after": None
            if a is None
            else {
                "anchors": f"{a['anchor_lo_session']}|{a['anchor_hi_session']}",
                "calendar": f"{a['calendar_lo']}..{a['calendar_hi']}",
                "k_e": a["charge_k_e"],
            },
            "changed": (b or {}).get("anchor_lo_session") != (a or {}).get("anchor_lo_session")
            or (b or {}).get("anchor_hi_session") != (a or {}).get("anchor_hi_session")
            or (b or {}).get("calendar_lo") != (a or {}).get("calendar_lo")
            or (b or {}).get("calendar_hi") != (a or {}).get("calendar_hi"),
        })

    shifts = [r for r in proposals if r.get("verdict") == "shift"]
    return {
        "record_type": "remeasure",
        "n_production_pin_sessions": len(production),
        "n_after_pin_sessions": len(after_pins),
        "n_gaps_before": len(before),
        "n_gaps_after": len(after),
        "n_shifts_applied": len(shifts),
        "membership": membership,
        "n_membership_changed": sum(1 for m in membership if m["changed"]),
    }


def parse_stretch(spec: str) -> tuple[str, int, int]:
    # inventory:lo:hi
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError(f"stretch must be inventory:scan_lo:scan_hi, got {spec!r}")
    return parts[0], int(parts[1]), int(parts[2])


def run_trust_approvals(
    graph: nx.MultiDiGraph,
    *,
    stretch: str,
    annotate_graph: bool,
    write: bool,
) -> dict[str, Any]:
    """Approved dates → trusted physical overrides → text mass in new brackets."""
    trust = load_date_trust()
    approved = set(trust["approved_dates"])
    rejected = set(trust["rejected_dates"])
    proposals = propose_physical_pins(graph)
    trusted_props = apply_date_trust_to_proposals(
        proposals, approved=approved, rejected=rejected
    )
    n_trust_eligible = sum(1 for r in trusted_props if r.get("trust_gate_eligible"))
    n_trust_shift = sum(
        1
        for r in trusted_props
        if r.get("trust_gate_eligible") and r.get("verdict") == "shift"
    )

    inv, lo, hi = parse_stretch(stretch)
    extents = build_extents(graph)
    stretch_undated = [
        e.session_id
        for e in extents
        if e.inventory == inv
        and e.undated
        and e.scan_lo is not None
        and e.scan_hi is not None
        and not (e.scan_hi < lo or e.scan_lo > hi)
    ]
    focus = sorted(set(stretch_undated) | {PROOF_UNDATED_SESSION, PROOF_DATED_SESSION})
    rem = remeasure(graph, trusted_props, stretch_sessions=focus)

    production = pinned_sessions(graph)
    before = gaps_from_pins(graph, production)
    after_pins = override_pins(production, trusted_props)
    after = gaps_from_pins(graph, after_pins)
    new_gaps = new_bracket_gaps(before, after)
    text_rows = text_inside_brackets(graph, new_gaps)

    print(
        f"date trust: approved={trust['n_approved']}  rejected={trust['n_rejected']}  "
        f"deferred={trust['n_deferred']}"
    )
    print(
        f"trusted physical overrides: eligible={n_trust_eligible}  "
        f"shifts={n_trust_shift}  (session_num unused)"
    )
    print(
        f"gaps production→trusted-physical: {rem['n_gaps_before']} → {rem['n_gaps_after']}  "
        f"new bracket geometries={len(new_gaps)}"
    )
    print(f"stretch membership changed: {rem['n_membership_changed']}/{len(rem['membership'])}")
    for m in rem["membership"]:
        if not m["changed"]:
            continue
        print(f"  CHANGED {m['session_id']}")
        print(f"    before: {m['before']}")
        print(f"    after:  {m['after']}")

    unaligned = sum(r["n_unaligned"] for r in text_rows)
    print(
        f"\n=== TEXT INSIDE new brackets (inventory; no DP) ===\n"
        f"  brackets={len(text_rows)}  unaligned_enriched={unaligned}  "
        f"aligned={sum(r['n_aligned'] for r in text_rows)}  "
        f"k_e={sum(r['charge_k_e'] for r in text_rows)}  "
        f"htr_paras={sum(r.get('charge_htr_paras') or 0 for r in text_rows)}"
    )
    for r in text_rows[:12]:
        print(
            f"  {r['inventory']} {r['calendar_lo']}..{r['calendar_hi']}  "
            f"unaligned={r['n_unaligned']}/{r['n_enriched']}  "
            f"k_e={r['charge_k_e']}  htr_paras={r['charge_htr_paras']}  "
            f"htr_sess={r['n_htr_sessions_inclusive']}"
        )
    if len(text_rows) > 12:
        print(f"  … {len(text_rows) - 12} more")

    edge_counts: dict[str, int] | None = None
    if annotate_graph:
        edge_counts = annotate_physical_date_trust(
            graph, approved=approved, rejected=rejected
        )
        save_loaded_graph(graph)
        print(
            f"\nannotated {PHYSICAL_PIN_KEY} date_trust: {edge_counts}  "
            f"(production PINNED_TO untouched)"
        )

    summary = {
        "record_type": "date_trust_summary",
        "channel": "DATED_AS_review",
        "policy": (
            "Trust set = approved calendar dates from session_anchor_shift_approvals. "
            "session_num never scores. No production PINNED_TO wire. "
            "Text-inside = unaligned enriched vs HTR mass in new bracket geometries."
        ),
        **{k: trust[k] for k in (
            "n_approved", "n_rejected", "n_deferred",
            "approved_dates", "rejected_dates", "deferred_dates",
        )},
        "n_trust_gate_eligible": n_trust_eligible,
        "n_trust_shifts": n_trust_shift,
        "remeasure": rem,
        "n_new_brackets": len(new_gaps),
        "n_unaligned_in_new_brackets": unaligned,
        "n_aligned_in_new_brackets": sum(r["n_aligned"] for r in text_rows),
        "edge_date_trust_counts": edge_counts,
        **scope_meta(),
    }

    if write:
        payload: list[dict[str, Any]] = [
            summary,
            {"record_type": "notes_by_date", "notes": trust["notes_by_date"]},
            *[r for r in trusted_props if r.get("date_trust") in ("approved", "rejected")],
            *text_rows,
        ]
        save_semi_structured(
            payload,
            logical_name=TRUST_DATASET,
            script=__file__,
            description=summary["policy"],
            parent_sources=[
                APPROVALS_DATASET,
                OUTPUT_DATASET,
                "sequence_graph_nodes",
                "sequence_graph_edges",
            ],
        )
        print(f"Wrote {TRUST_DATASET}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--propose", action="store_true")
    parser.add_argument("--remeasure", action="store_true")
    parser.add_argument(
        "--trust-approvals",
        action="store_true",
        help="approved dates as trust set; remeasure; text inside new brackets",
    )
    parser.add_argument(
        "--annotate-graph",
        action="store_true",
        help="with --trust-approvals: stamp date_trust on PINNED_TO:physical and save",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help=f"write {PHYSICAL_PIN_KEY} edges and save graph (does not replace production pins)",
    )
    parser.add_argument(
        "--stretch",
        default="3185:95:110",
        help="inventory:scan_lo:scan_hi — undated sessions in this stretch are tracked in remeasure",
    )
    parser.add_argument("--write", action="store_true", help="persist output dataset")
    args = parser.parse_args()
    if not args.propose and not args.trust_approvals:
        parser.error("pass --propose and/or --trust-approvals")

    graph = load_graph()

    if args.trust_approvals:
        run_trust_approvals(
            graph,
            stretch=args.stretch,
            annotate_graph=args.annotate_graph,
            write=args.write,
        )
        if not args.propose:
            return

    proposals = propose_physical_pins(graph)
    gate = gate_summary(proposals)

    print(
        f"physical unique pins: eligible={gate['n_eligible']}  "
        f"shift={gate['n_shift']} new={gate['n_new_pin']} agree={gate['n_agree']}  "
        f"verdicts={gate['verdicts']}"
    )
    print(
        f"gate {gate['validation_date']} → {gate['validation_expected_session']}: "
        f"{'PASS' if gate['validation_ok'] else 'FAIL'}  "
        f"row={gate['validation_row']}"
    )

    inv, lo, hi = parse_stretch(args.stretch)
    extents = build_extents(graph)
    stretch_undated = [
        e.session_id
        for e in extents
        if e.inventory == inv
        and e.undated
        and e.scan_lo is not None
        and e.scan_hi is not None
        and not (e.scan_hi < lo or e.scan_lo > hi)
    ]
    # always include proof undated session
    focus = sorted(set(stretch_undated) | {PROOF_UNDATED_SESSION, PROOF_DATED_SESSION})

    rem: dict[str, Any] | None = None
    if args.remeasure:
        rem = remeasure(graph, proposals, stretch_sessions=focus)
        print(
            f"\n=== REMEASURE gaps (production → physical overrides) ===\n"
            f"  pin sessions {rem['n_production_pin_sessions']} → {rem['n_after_pin_sessions']}  "
            f"gaps {rem['n_gaps_before']} → {rem['n_gaps_after']}  "
            f"shifts applied={rem['n_shifts_applied']}"
        )
        print(f"  stretch {inv} {lo}..{hi} undated focus + proof sessions:")
        for m in rem["membership"]:
            b, a = m["before"], m["after"]
            flag = " CHANGED" if m["changed"] else ""
            print(f"    {m['session_id']}{flag}")
            print(f"      before: {b}")
            print(f"      after:  {a}")

    staged = 0
    if args.stage:
        if not gate["validation_ok"]:
            raise SystemExit("refusing --stage: validation gate failed")
        staged = stage_physical_edges(graph, proposals)
        save_loaded_graph(graph)
        print(f"\nstaged {staged} {PHYSICAL_PIN_KEY} edges; graph saved")

    if args.write and not args.trust_approvals:
        payload = [gate, *proposals]
        if rem is not None:
            payload.append(rem)
        save_semi_structured(
            payload,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=gate["review_policy"],
            parent_sources=[
                "sequence_graph_nodes",
                "sequence_graph_edges",
                "sequence_graph_physical_extents_proof",
            ],
        )
        print(f"Wrote {OUTPUT_DATASET}")


if __name__ == "__main__":
    main()

"""Review cards for physical pin shifts — dated scans + ambiguities, with IIIF links.

Judgment grain is the **dated scan** (is DATED_AS right on that image?). Session numeric
labels are parsing artefacts: the same sitting can get different ``session_num`` values
across ledgers while sharing one calendar date — judge the date, not the number.
Secret inventories stay out of this pipeline; that fact only explains why numbers mislead.

Approvals persist to ``session_anchor_shift_approvals``.

Usage (library + notebook):
    from sequence_graph.physical_pin_review import build_review_deck, load_approvals, save_approvals
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from data_io import load, save_semi_structured
from sequence_graph.correspondence import DATED_AS
from sequence_graph.persist import load_graph
from sequence_graph.physical_extents import neighbourhood_rows

APPROVALS_DATASET = "session_anchor_shift_approvals"
PROPOSALS_DATASET = "session_anchor_shift_proposals"
IIIF = (
    "https://images.diginfra.net/iiif/NL-HaNA_1.01.02/{inv}/"
    "NL-HaNA_1.01.02_{inv}_{scan:04d}.jpg/full/full/0/default.jpg"
)


def iiif_for_scan(inventory: str, scan_num: int) -> str:
    return IIIF.format(inv=inventory, scan=int(scan_num))


def _session_num(session_id: str) -> int | None:
    m = re.search(r"num-(\d+)", session_id or "")
    return int(m.group(1)) if m else None


def _load_proposals() -> list[dict[str, Any]]:
    return [
        r
        for r in load(PROPOSALS_DATASET)
        if r.get("record_type") == "proposal"
    ]


def dated_scan_cards(
    *,
    inventory: str,
    scan_lo: int,
    scan_hi: int,
) -> list[dict[str, Any]]:
    """One card per scan in a continuous stretch that carries DATED_AS (judgment unit)."""
    graph = load_graph()
    proposals = {r["date"]: r for r in _load_proposals()}
    cards: list[dict[str, Any]] = []
    for row in neighbourhood_rows(graph, inventory, scan_lo, scan_hi):
        if not row["dated_days"]:
            continue
        for day in row["dated_days"]:
            prop = proposals.get(day, {})
            cards.append({
                "record_type": "review_card",
                "card_kind": "dated_scan",
                "review_id": f"scan:{inventory}:{row['scan_num']}:{day}",
                "inventory": inventory,
                "scan_num": row["scan_num"],
                "dated_day": day,
                "sessions_on_scan": row["sessions"],
                "proposed_session": prop.get("proposed_session"),
                "production_session": prop.get("production_session"),
                "verdict": prop.get("verdict"),
                "iiif_url": iiif_for_scan(inventory, row["scan_num"]),
                "prompt": (
                    f"Does scan {inventory}/{row['scan_num']:04d} carry a date heading "
                    f"for {day}?"
                ),
            })
    return cards


def ambiguous_cards() -> list[dict[str, Any]]:
    """Dates whose dated scan(s) are shared / crowded — judge the heading, not session ids."""
    graph = load_graph()
    cards: list[dict[str, Any]] = []
    for r in _load_proposals():
        if r.get("verdict") != "ambiguous_physical":
            continue
        date = r["date"]
        # find scans for this day
        day_node = f"day:{date}"
        scan_links: list[dict[str, Any]] = []
        if day_node in graph:
            for u, _v, ed in graph.in_edges(day_node, data=True):
                if ed.get("kind") != DATED_AS:
                    continue
                scan = graph.nodes[u]["obj"]
                other_days = sorted(
                    {
                        graph.nodes[dv]["obj"].date
                        for _su, dv, ded in graph.out_edges(u, data=True)
                        if ded.get("kind") == DATED_AS
                        and graph.nodes[dv].get("kind") == "SittingDay"
                    }
                )
                scan_links.append({
                    "inventory": scan.inventory,
                    "scan_num": scan.scan_num,
                    "dated_days_on_scan": other_days,
                    "iiif_url": iiif_for_scan(scan.inventory, scan.scan_num),
                })
        n_scans = len(scan_links)
        multi = [
            f"{lk['inventory']}/{lk['scan_num']:04d} → {', '.join(lk['dated_days_on_scan'])}"
            for lk in scan_links
            if len(lk.get("dated_days_on_scan") or []) > 1
        ]
        hint = (
            f" Scan(s) with more than one date heading: {'; '.join(multi)}."
            if multi
            else ""
        )
        cards.append({
            "record_type": "review_card",
            "card_kind": "ambiguous",
            "review_id": f"ambiguous:{date}",
            "dated_day": date,
            "physical_sessions": r.get("physical_sessions"),
            "production_session": r.get("production_session"),
            "scan_links": scan_links,
            "iiif_url": scan_links[0]["iiif_url"] if scan_links else None,
            "prompt": (
                f"Is the date heading for {date} correct on its scan"
                f"{'s' if n_scans != 1 else ''}?"
                f"{hint} Approve / reject / defer — ignore session numbers."
            ),
        })
    return cards


def far_shift_cards(*, min_abs_delta: int = 4, limit: int = 40) -> list[dict[str, Any]]:
    """Large session-num jumps — sample for page check (not the full 430)."""
    graph = load_graph()
    cards: list[dict[str, Any]] = []
    for r in _load_proposals():
        if r.get("verdict") != "shift":
            continue
        a, b = _session_num(r.get("production_session")), _session_num(r.get("proposed_session"))
        if a is None or b is None or abs(b - a) < min_abs_delta:
            continue
        date = r["date"]
        day_node = f"day:{date}"
        scan_num = inventory = None
        if day_node in graph:
            for u, _v, ed in graph.in_edges(day_node, data=True):
                if ed.get("kind") == DATED_AS:
                    scan = graph.nodes[u]["obj"]
                    inventory, scan_num = scan.inventory, scan.scan_num
                    break
        if inventory is None or scan_num is None:
            continue
        cards.append({
            "record_type": "review_card",
            "card_kind": "far_shift",
            "review_id": f"far:{date}",
            "dated_day": date,
            "delta": b - a,
            "production_session": r["production_session"],
            "proposed_session": r["proposed_session"],
            "inventory": inventory,
            "scan_num": scan_num,
            "iiif_url": iiif_for_scan(inventory, scan_num),
            "prompt": (
                f"Confirm the date heading for {date} on scan "
                f"{inventory}/{scan_num:04d}."
            ),
        })
        if len(cards) >= limit:
            break
    return cards


def build_review_deck(
    *,
    inventory: str = "3185",
    scan_lo: int = 95,
    scan_hi: int = 110,
    include_ambiguous: bool = True,
    include_far: bool = True,
    far_limit: int = 40,
) -> list[dict[str, Any]]:
    cards = dated_scan_cards(inventory=inventory, scan_lo=scan_lo, scan_hi=scan_hi)
    if include_ambiguous:
        cards.extend(ambiguous_cards())
    if include_far:
        cards.extend(far_shift_cards(limit=far_limit))
    return cards


def load_approvals() -> dict[str, dict[str, Any]]:
    try:
        rows = list(load(APPROVALS_DATASET))
    except FileNotFoundError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("record_type") != "approval":
            continue
        rid = r.get("review_id")
        if rid:
            out[str(rid)] = r
    return out


def save_approvals(approvals: dict[str, dict[str, Any]]) -> None:
    rows = [
        {
            "record_type": "meta",
            "n_approvals": len(approvals),
            "actions": _action_counts(approvals),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    ]
    for rid, row in sorted(approvals.items()):
        rec = dict(row)
        rec["record_type"] = "approval"
        rec["review_id"] = rid
        rows.append(rec)
    save_semi_structured(
        rows,
        logical_name=APPROVALS_DATASET,
        script=__file__,
        description=(
            "Human approvals for physical pin-shift review cards "
            "(dated_scan / ambiguous / far_shift). Actions: approve|reject|defer."
        ),
        parent_sources=[PROPOSALS_DATASET],
    )


def _action_counts(approvals: dict[str, dict[str, Any]]) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for row in approvals.values():
        c[str(row.get("action") or "unset")] += 1
    return dict(c)


def record_approval(
    approvals: dict[str, dict[str, Any]],
    card: dict[str, Any],
    action: str,
    *,
    note: str = "",
    selected_session: str | None = None,
) -> dict[str, dict[str, Any]]:
    if action not in ("approve", "reject", "defer", "note"):
        raise ValueError(action)
    prev = approvals.get(card["review_id"]) or {}
    # action="note" updates free text only; keep prior approve/reject/defer if any.
    resolved = prev.get("action") if action == "note" else action
    if resolved == "note":
        resolved = "defer"
    approvals[card["review_id"]] = {
        "review_id": card["review_id"],
        "card_kind": card.get("card_kind"),
        "action": resolved,
        "note": note,
        "selected_session": selected_session
        if selected_session is not None
        else prev.get("selected_session"),
        "dated_day": card.get("dated_day"),
        "scan_num": card.get("scan_num"),
        "inventory": card.get("inventory"),
        "iiif_url": card.get("iiif_url"),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    return approvals


def card_html(card: dict[str, Any], prior: dict[str, Any] | None = None) -> str:
    """Compact HTML for a review card: date, scan, IIIF — no session numbers."""
    prior = prior or {}
    day = card.get("dated_day") or "—"
    kind = card.get("card_kind")
    lines = [
        f"<h3>{kind} — {day}</h3>",
        f"<p>{card.get('prompt', '')}</p>",
    ]
    if card.get("iiif_url") and not card.get("scan_links"):
        url = card["iiif_url"]
        inv, num = card.get("inventory"), card.get("scan_num")
        label = f"{inv}/{num:04d}" if inv is not None and num is not None else "scan"
        lines.append(
            f'<p><a href="{url}" target="_blank" rel="noopener">Open IIIF ({label})</a></p>'
            f'<p><img src="{url}" alt="scan" style="max-width:100%;max-height:480px;"/></p>'
        )
    for link in card.get("scan_links") or []:
        url = link.get("iiif_url")
        if not url:
            continue
        inv, num = link.get("inventory"), link.get("scan_num")
        days = ", ".join(link.get("dated_days_on_scan") or []) or "—"
        lines.append(
            f"<p>Scan {inv}/{num:04d} — date heading(s) on page: {days}<br/>"
            f'<a href="{url}" target="_blank" rel="noopener">IIIF</a></p>'
            f'<p><img src="{url}" alt="scan" style="max-width:100%;max-height:360px;"/></p>'
        )
    if prior:
        note = (prior.get("note") or "").replace("<", "&lt;")
        lines.append(
            f"<p><b>Prior:</b> {prior.get('action')} "
            f"@ {prior.get('decided_at', '')}<br/>"
            f"<b>Note:</b> {note or '—'}</p>"
        )
    return "\n".join(lines)

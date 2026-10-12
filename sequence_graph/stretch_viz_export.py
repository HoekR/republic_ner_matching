"""Export annotated stretch as a conflict timeline for the SVG viewer.

Primary payload: per-day claim summary (production / physical / review / literal
scans) and conflict rows. Full lane edges kept only for the selected-day detail
panel. Review claims from notes — not written to the graph.

Usage:
    uv run python -m sequence_graph.stretch_viz_export
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from sequence_graph.correspondence import DATED_AS, OBSERVED_ON, PINNED_TO
from sequence_graph.persist import load_graph
from sequence_graph.physical_pin_review import iiif_for_scan
from sequence_graph.problem_sequence_review import (
    dated_as_review_claims_from_notes,
    load_notes,
)

PHYSICAL_PIN_KEY = f"{PINNED_TO}:physical"
VIZ_PUBLIC = Path(__file__).resolve().parents[1] / "viz" / "sequence_stretch" / "public"
DEFAULT_OUT = VIZ_PUBLIC / "stretch.json"
SESSION_NUM_RE = re.compile(r"num-(\d+)$")
MARGIN_DAYS = 3


def _session_num(session_id: str) -> int | None:
    m = SESSION_NUM_RE.search(session_id or "")
    return int(m.group(1)) if m else None


def _sid_label(session_id: str | None) -> str | None:
    if not session_id:
        return None
    n = _session_num(session_id)
    return f"num-{n}" if n is not None else session_id


def _period(date: str) -> pd.Period:
    return pd.Period(str(date), freq="D")


def _shift_date(date: str, days: int) -> str:
    return str(_period(date) + days)


def _day_in_window(date: str, lo: str, hi: str) -> bool:
    if not in_scope(date):
        return False
    p = _period(date)
    return _period(lo) <= p <= _period(hi)


def window_from_notes(notes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    calendars: list[str] = []
    sess_nums: list[int] = []
    inventory = "3185"
    for row in notes.values():
        inv = str(row.get("inventory") or "")
        if inv and not is_main_series(inv):
            continue
        if inv:
            inventory = inv
        lo, hi = row.get("calendar_lo"), row.get("calendar_hi")
        if lo and hi and in_scope(str(lo)) and in_scope(str(hi)):
            calendars.extend([str(lo), str(hi)])
        for key in ("anchor_lo_session", "anchor_hi_session"):
            n = _session_num(str(row.get(key) or ""))
            if n is not None:
                sess_nums.append(n)
    if not calendars:
        raise SystemExit("no in-scope calendar spans in problem_sequence_review_notes")
    return {
        "inventory": inventory,
        "calendar_lo": min(calendars),
        "calendar_hi": max(calendars),
        "sess_lo": min(sess_nums) if sess_nums else None,
        "sess_hi": max(sess_nums) if sess_nums else None,
    }


def _pins_for_day(graph: nx.MultiDiGraph, day_id: str) -> dict[str, str | None]:
    production: str | None = None
    physical: str | None = None
    for _u, v, key, ed in graph.out_edges(day_id, keys=True, data=True):
        if ed.get("kind") != PINNED_TO:
            continue
        if graph.nodes[v].get("kind") != "Session":
            continue
        sid = graph.nodes[v]["obj"].session_id
        if not is_main_series(graph.nodes[v]["obj"].inventory):
            continue
        if key == PHYSICAL_PIN_KEY or str(key).endswith(":physical"):
            physical = sid
        else:
            production = sid
    return {"production": production, "physical": physical}


def _literal_scans(graph: nx.MultiDiGraph, day_id: str, inventory: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for u, _v, ed in graph.in_edges(day_id, data=True):
        if ed.get("kind") != DATED_AS:
            continue
        if graph.nodes[u].get("kind") != "Scan":
            continue
        obj = graph.nodes[u]["obj"]
        if obj.inventory != inventory:
            continue
        out.append({
            "scan_num": int(obj.scan_num),
            "iiif_url": iiif_for_scan(inventory, int(obj.scan_num)),
        })
    return sorted(out, key=lambda r: r["scan_num"])


def _observed_scans(graph: nx.MultiDiGraph, session_id: str | None, inventory: str) -> list[int]:
    if not session_id:
        return []
    node = f"session:{session_id}"
    if node not in graph:
        return []
    nums: list[int] = []
    for _u, v, ed in graph.out_edges(node, data=True):
        if ed.get("kind") != OBSERVED_ON:
            continue
        if graph.nodes[v].get("kind") != "Scan":
            continue
        obj = graph.nodes[v]["obj"]
        if obj.inventory == inventory:
            nums.append(int(obj.scan_num))
    return sorted(set(nums))


def _notes_for_date(notes: dict[str, dict[str, Any]], date: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for rid, row in notes.items():
        lo, hi = row.get("calendar_lo"), row.get("calendar_hi")
        if not lo or not hi:
            continue
        if _day_in_window(date, str(lo), str(hi)):
            hits.append({
                "review_id": rid,
                "flag": row.get("flag"),
                "note": row.get("note"),
            })
    return hits


def build_stretch_payload(
    graph: nx.MultiDiGraph,
    *,
    inventory: str,
    calendar_lo: str,
    calendar_hi: str,
    sess_lo: int | None = None,
    sess_hi: int | None = None,
) -> dict[str, Any]:
    display_lo = _shift_date(calendar_lo, -MARGIN_DAYS)
    display_hi = _shift_date(calendar_hi, MARGIN_DAYS)

    notes = {
        rid: row
        for rid, row in load_notes().items()
        if str(row.get("inventory") or "") == inventory
    }
    review_claims = [
        c
        for c in dated_as_review_claims_from_notes()
        if c["inventory"] == inventory
        and _day_in_window(c["date"], display_lo, display_hi)
    ]
    review_by_date: dict[str, list[dict[str, Any]]] = {}
    for c in review_claims:
        review_by_date.setdefault(c["date"], []).append({
            "scan_num": c["scan_num"],
            "iiif_url": c["evidence_url"],
            "review_id": c["review_id"],
        })

    # Calendar continuum for the timeline (inclusive display window).
    dates: list[str] = []
    cur = _period(display_lo)
    end = _period(display_hi)
    while cur <= end:
        d = str(cur)
        if in_scope(d):
            dates.append(d)
        cur += 1

    days_out: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for date in dates:
        day_id = f"day:{date}"
        pins = _pins_for_day(graph, day_id) if day_id in graph else {
            "production": None,
            "physical": None,
        }
        prod = pins["production"]
        phys = pins["physical"]
        literals = _literal_scans(graph, day_id, inventory) if day_id in graph else []
        reviews = review_by_date.get(date, [])
        note_hits = _notes_for_date(notes, date)

        prod_n = _session_num(prod or "")
        phys_n = _session_num(phys or "")
        pin_disagree = bool(prod and phys and prod != phys)
        missing_prod = phys is not None and prod is None
        has_review = bool(reviews)
        is_conflict = pin_disagree or missing_prod or has_review

        # Prefer IIIF: review scan, else literal DATED_AS, else physical session scans.
        iiif: str | None = None
        focus_scan: int | None = None
        if reviews:
            focus_scan = int(reviews[0]["scan_num"])
            iiif = reviews[0]["iiif_url"]
        elif literals:
            focus_scan = int(literals[0]["scan_num"])
            iiif = literals[0]["iiif_url"]
        else:
            for sid in (phys, prod):
                nums = _observed_scans(graph, sid, inventory)
                if nums:
                    focus_scan = nums[0]
                    iiif = iiif_for_scan(inventory, nums[0])
                    break

        reasons: list[str] = []
        if pin_disagree:
            reasons.append("production_ne_physical")
        if missing_prod:
            reasons.append("physical_without_production")
        if has_review:
            reasons.append("review_claim")
        if note_hits and not reasons:
            reasons.append("in_annotated_stretch")

        day_row = {
            "date": date,
            "production_session": prod,
            "production_label": _sid_label(prod),
            "physical_session": phys,
            "physical_label": _sid_label(phys),
            "literal_scans": literals,
            "review_claims": reviews,
            "notes": note_hits,
            "focus_scan": focus_scan,
            "iiif_url": iiif,
            "is_conflict": is_conflict,
            "reasons": reasons,
            "pin_delta": (
                (phys_n - prod_n)
                if prod_n is not None and phys_n is not None
                else None
            ),
        }
        days_out.append(day_row)
        if is_conflict:
            conflicts.append(day_row)

    return {
        "meta": {
            "inventory": inventory,
            "calendar_lo": calendar_lo,
            "calendar_hi": calendar_hi,
            "display_lo": display_lo,
            "display_hi": display_hi,
            "sess_lo": sess_lo,
            "sess_hi": sess_hi,
            "margin_days": MARGIN_DAYS,
            "n_days": len(days_out),
            "n_conflicts": len(conflicts),
            "n_review_claims": len(review_claims),
            "view": "conflict_timeline",
            "policy": (
                "Conflict timeline for annotated stretch. Review claims from notes "
                "only — not written to the graph. No production PINNED_TO wire."
            ),
            **scope_meta(),
        },
        "days": days_out,
        "conflicts": conflicts,
        "review_claims": review_claims,
        "notes": [
            {
                "review_id": rid,
                "flag": row.get("flag"),
                "note": row.get("note"),
                "calendar_lo": row.get("calendar_lo"),
                "calendar_hi": row.get("calendar_hi"),
                "anchor_lo_session": row.get("anchor_lo_session"),
                "anchor_hi_session": row.get("anchor_hi_session"),
            }
            for rid, row in sorted(notes.items())
        ],
    }


def export_stretch(
    *,
    inventory: str | None = None,
    calendar_lo: str | None = None,
    calendar_hi: str | None = None,
    out_path: Path = DEFAULT_OUT,
) -> Path:
    notes = load_notes()
    window = window_from_notes(notes)
    inv = inventory or window["inventory"]
    lo = calendar_lo or window["calendar_lo"]
    hi = calendar_hi or window["calendar_hi"]
    graph = load_graph()
    payload = build_stretch_payload(
        graph,
        inventory=inv,
        calendar_lo=lo,
        calendar_hi=hi,
        sess_lo=window.get("sess_lo"),
        sess_hi=window.get("sess_hi"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default=None)
    parser.add_argument("--calendar-lo", default=None)
    parser.add_argument("--calendar-hi", default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    path = export_stretch(
        inventory=args.inventory,
        calendar_lo=args.calendar_lo,
        calendar_hi=args.calendar_hi,
        out_path=args.out,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data["meta"]
    print(
        f"wrote {path}  days={meta['n_days']} conflicts={meta['n_conflicts']} "
        f"review={meta['n_review_claims']} window={meta['display_lo']}..{meta['display_hi']}"
    )


if __name__ == "__main__":
    main()

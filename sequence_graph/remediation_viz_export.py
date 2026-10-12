"""Export hard-recalibration as a before→after bipartite morph payload.

Before = production PINNED_TO (contested lids). After = unique hard path
Session-OBSERVED_ON-Scan-DATED_AS-SittingDay, plus literal-opening seeds and
held-out review claims. Reads ``hard_recalibrate_proof`` (no re-run of DP).

Writes ``viz/sequence_stretch/public/remediation.json`` (gitignored —
regenerate after clone or ``--focus-*`` / ``--full-lag`` window change).

Usage:
    uv run python -m sequence_graph.remediation_viz_export
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_io import load
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from sequence_graph.correspondence import DATED_AS, OBSERVED_ON
from sequence_graph.persist import load_graph
from sequence_graph.physical_pin_review import iiif_for_scan
from sequence_graph.problem_sequence_review import load_notes
from sequence_graph.stretch_viz_export import _session_num, _sid_label

VIZ_PUBLIC = Path(__file__).resolve().parents[1] / "viz" / "sequence_stretch" / "public"
DEFAULT_OUT = VIZ_PUBLIC / "remediation.json"


def _load_proof() -> list[dict[str, Any]]:
    rows = load("hard_recalibrate_proof")
    if not rows:
        raise SystemExit("hard_recalibrate_proof empty — run hard_recalibrate --write first")
    return rows


def _observed_scans_for_session(
    graph: Any, session_id: str, inventory: str
) -> list[int]:
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


def _dated_as_scans(graph: Any, date: str, inventory: str) -> list[int]:
    day = f"day:{date}"
    if day not in graph:
        return []
    nums: list[int] = []
    for u, _v, ed in graph.in_edges(day, data=True):
        if ed.get("kind") != DATED_AS:
            continue
        if graph.nodes[u].get("kind") != "Scan":
            continue
        obj = graph.nodes[u]["obj"]
        if obj.inventory == inventory:
            nums.append(int(obj.scan_num))
    return sorted(set(nums))


def build_remediation_payload(
    *,
    focus_lo: str | None = None,
    focus_hi: str | None = None,
) -> dict[str, Any]:
    rows = _load_proof()
    meta_row = next(r for r in rows if r.get("record_type") == "meta")
    inventory = str(meta_row["inventory"])
    calendar_lo = str(meta_row["calendar_lo"])
    calendar_hi = str(meta_row["calendar_hi"])
    # Default visual focus = Aug–Sep intersection of the lag window.
    flo = focus_lo or max(calendar_lo, "1626-08-01")
    fhi = focus_hi or min(calendar_hi, "1626-09-30")
    if flo > fhi:
        flo, fhi = calendar_lo, calendar_hi

    hard_all = [r for r in rows if r.get("record_type") == "hard_map" and r.get("active")]
    hard = [r for r in hard_all if flo <= r["date"] <= fhi and in_scope(r["date"])]
    if not hard:
        hard = [r for r in hard_all if in_scope(r["date"])]

    lit_by_sess = {
        r["session_id"]: r
        for r in rows
        if r.get("record_type") == "literal_opening" and r.get("matched")
    }
    compare = next((r for r in rows if r.get("record_type") == "compare_notes"), None)
    review_by_date = {
        d["date"]: d for d in (compare or {}).get("detail") or []
    }
    dp_ok = [
        r
        for r in rows
        if r.get("record_type") == "dp_handoff" and r.get("status") == "dp1_ok"
    ]
    dp_by_sess: dict[int, dict[str, Any]] = {}
    for r in dp_ok:
        for sn in range(int(r["chunk_sess_lo"]), int(r["chunk_sess_hi"]) + 1):
            dp_by_sess[sn] = r

    graph = load_graph()
    notes = {
        rid: row
        for rid, row in load_notes().items()
        if str(row.get("inventory") or "") == inventory
        and is_main_series(str(row.get("inventory") or ""))
    }

    sessions_seen: dict[str, dict[str, Any]] = {}
    dates_out: list[dict[str, Any]] = []
    before_edges: list[dict[str, Any]] = []
    after_edges: list[dict[str, Any]] = []
    hard_paths: list[dict[str, Any]] = []
    scans_seen: dict[int, dict[str, Any]] = {}

    for hr in hard:
        date = hr["date"]
        hard_sid = hr["session_id"]
        prod_sid = hr.get("production_session")
        hard_n = hr.get("session_num") or _session_num(hard_sid)
        prod_n = _session_num(prod_sid or "")
        dated_on_sess = list(hr.get("dated_scans_on_session") or [])
        observed = _observed_scans_for_session(graph, hard_sid, inventory)
        dated_all = _dated_as_scans(graph, date, inventory)
        bridge = dated_on_sess or sorted(set(observed) & set(dated_all))
        focus_scan = bridge[0] if bridge else (observed[0] if observed else None)

        for sid, n in ((hard_sid, hard_n), (prod_sid, prod_n)):
            if not sid or n is None:
                continue
            if sid not in sessions_seen:
                lit = lit_by_sess.get(sid)
                dp = dp_by_sess.get(int(n))
                sessions_seen[sid] = {
                    "id": sid,
                    "label": _sid_label(sid),
                    "session_num": int(n),
                    "literal_opening": bool(lit),
                    "literal_flat": (lit or {}).get("opening_flat"),
                    "literal_snippet": ((lit or {}).get("snippet") or "")[:160],
                    "dp1_n_match": (dp or {}).get("n_match"),
                    "dp1_n_match_entity": (dp or {}).get("n_match_with_entity"),
                    "dp1_status": (dp or {}).get("status"),
                }

        for sn in sorted(set(observed) | set(dated_all) | set(bridge)):
            if sn not in scans_seen:
                scans_seen[sn] = {
                    "scan_num": sn,
                    "iiif_url": iiif_for_scan(inventory, sn),
                }

        review = review_by_date.get(date)
        note_hits = [
            {
                "review_id": rid,
                "flag": row.get("flag"),
                "note": row.get("note"),
            }
            for rid, row in notes.items()
            if row.get("calendar_lo")
            and row.get("calendar_hi")
            and str(row["calendar_lo"]) <= date <= str(row["calendar_hi"])
        ]

        dates_out.append({
            "date": date,
            "production_session": prod_sid,
            "production_label": _sid_label(prod_sid),
            "hard_session": hard_sid,
            "hard_label": _sid_label(hard_sid),
            "pin_delta": (
                (hard_n - prod_n)
                if hard_n is not None and prod_n is not None
                else None
            ),
            "production_disagrees": bool(hr.get("production_disagrees")),
            "dated_scans_on_session": dated_on_sess,
            "observed_scans": observed,
            "dated_as_scans": dated_all,
            "bridge_scans": bridge,
            "focus_scan": focus_scan,
            "iiif_url": (
                iiif_for_scan(inventory, int(focus_scan)) if focus_scan is not None else None
            ),
            "literal_opening": bool(lit_by_sess.get(hard_sid)),
            "review_held_out": review,
            "notes": note_hits,
            "in_aug_sep": date[5:7] in ("08", "09"),
        })

        if prod_sid and prod_n is not None:
            before_edges.append({
                "id": f"before:{date}",
                "kind": "PINNED_TO:production",
                "date": date,
                "session_id": prod_sid,
                "session_num": int(prod_n),
                "disagrees": bool(hr.get("production_disagrees")),
            })

        after_edges.append({
            "id": f"after:{date}",
            "kind": "PINNED_TO:hard_composite",
            "date": date,
            "session_id": hard_sid,
            "session_num": int(hard_n),
            "via_scans": bridge,
            "literal_opening": bool(lit_by_sess.get(hard_sid)),
            "review_hit": bool((review or {}).get("review_scan_on_hard_dated_path")),
        })

        for sn in bridge:
            hard_paths.append({
                "id": f"path:{date}:{sn}",
                "date": date,
                "session_id": hard_sid,
                "session_num": int(hard_n),
                "scan_num": sn,
                "edges": ["OBSERVED_ON", "DATED_AS"],
            })

    sessions_out = sorted(sessions_seen.values(), key=lambda s: s["session_num"])
    scans_out = sorted(scans_seen.values(), key=lambda s: s["scan_num"])

    n_disagree = sum(1 for d in dates_out if d["production_disagrees"])
    n_lit = sum(1 for d in dates_out if d["literal_opening"])
    n_review = sum(1 for d in dates_out if d.get("review_held_out"))

    return {
        "meta": {
            "inventory": inventory,
            "lag_calendar_lo": calendar_lo,
            "lag_calendar_hi": calendar_hi,
            "focus_lo": flo,
            "focus_hi": fhi,
            "median_delta": meta_row.get("median_delta"),
            "n_dates": len(dates_out),
            "n_sessions": len(sessions_out),
            "n_scans": len(scans_out),
            "n_production_disagree": n_disagree,
            "n_literal_opening": n_lit,
            "n_review_held_out": n_review,
            "n_hard_paths": len(hard_paths),
            "dp1_channel": meta_row.get("dp1_channel"),
            "claim_set_dropped": meta_row.get("claim_set_dropped"),
            "claim_set_active": meta_row.get("claim_set_active"),
            "view": "remediation_morph",
            "tool": "d3_bipartite_morph",
            "policy": (
                "Before = production PINNED_TO. After = unique OBSERVED_ON∘DATED_AS "
                "hard map (+ literal openings). Review notes held out (compare only). "
                "No production wire. Morph tool = D3 (2D date↔session remapping); "
                "three.js rejected for this view — depth does not clarify the pin shift."
            ),
            "source_dataset": "hard_recalibrate_proof",
            **scope_meta(),
        },
        "dates": dates_out,
        "sessions": sessions_out,
        "scans": scans_out,
        "before_edges": before_edges,
        "after_edges": after_edges,
        "hard_paths": hard_paths,
        "compare_notes": compare,
        "fingerprint_fit": next(
            (r for r in rows if r.get("record_type") == "fingerprint_fit"), None
        ),
    }


def export_remediation(
    *,
    focus_lo: str | None = None,
    focus_hi: str | None = None,
    out_path: Path = DEFAULT_OUT,
) -> Path:
    payload = build_remediation_payload(focus_lo=focus_lo, focus_hi=focus_hi)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--focus-lo", default=None, help="default max(lag_lo, 1626-08-01)")
    parser.add_argument("--focus-hi", default=None, help="default min(lag_hi, 1626-09-30)")
    parser.add_argument("--full-lag", action="store_true", help="use full lag window")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    lo = hi = None
    if args.full_lag:
        rows = _load_proof()
        meta = next(r for r in rows if r.get("record_type") == "meta")
        lo, hi = meta["calendar_lo"], meta["calendar_hi"]
    else:
        lo, hi = args.focus_lo, args.focus_hi
    path = export_remediation(focus_lo=lo, focus_hi=hi, out_path=args.out)
    data = json.loads(path.read_text(encoding="utf-8"))
    m = data["meta"]
    print(
        f"wrote {path}  focus={m['focus_lo']}..{m['focus_hi']}  "
        f"dates={m['n_dates']} sessions={m['n_sessions']} scans={m['n_scans']}  "
        f"disagree={m['n_production_disagree']} literal={m['n_literal_opening']}  "
        f"review={m['n_review_held_out']}"
    )


if __name__ == "__main__":
    main()

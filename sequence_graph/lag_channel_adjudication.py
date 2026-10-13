"""Human adjudication deck for the hard-map vs content-fingerprint conflict.

On pin-disagree days, two channels disagree:
  * dating (hard): OBSERVED_ON ∘ DATED_AS + literal openings
  * content (fingerprint): enriched text prefers the production session

This module does **not** pick a winner. It builds one review card per disagree
day with IIIF for hard bridge scans and production-session scans, plus short
text snippets, so a human can say which paper carries the sitting.

Approvals → ``lag_channel_adjudication_notes`` (optional write).
Cards → ``lag_channel_adjudication`` (``--write``).

Usage:
    uv run python -m sequence_graph.lag_channel_adjudication --write
    uv run python -m sequence_graph.lag_channel_adjudication --limit 5
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from build_alignment_new import enriched_volgnr
from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, scope_meta
from sequence_graph.correspondence import OBSERVED_ON
from sequence_graph.fingerprint_session_shift import _flat_text_by_id
from sequence_graph.persist import load_graph
from sequence_graph.physical_pin_review import iiif_for_scan
from sequence_graph.sync_gap_align import _axis_by_inv_sess, _enriched_by_date

CARDS_DATASET = "lag_channel_adjudication"
NOTES_DATASET = "lag_channel_adjudication_notes"
SNIPPET = 280


def _session_opening_text(session_id: str, flat_text: dict[str, str], axis: dict) -> str:
    import re

    m = re.search(r"session-(\d+)-num-(\d+)", session_id or "")
    if not m:
        return ""
    flats = axis.get((m.group(1), int(m.group(2))), [])
    if not flats:
        return ""
    return (flat_text.get(flats[0]) or "")[:SNIPPET]


def _observed_scans(graph: Any, session_id: str, inventory: str) -> list[int]:
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


def _enriched_snippets(date: str, enr_by_date: dict[str, list[str]], enr_text: dict[str, str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for vid in (enr_by_date.get(date) or [])[:3]:
        out.append({"volgnr": vid, "snippet": (enr_text.get(vid) or "")[:SNIPPET]})
    return out


def build_cards(*, limit: int | None = None) -> list[dict[str, Any]]:
    proof = load("hard_recalibrate_proof")
    meta = next(r for r in proof if r.get("record_type") == "meta")
    inventory = str(meta["inventory"])
    lo, hi = str(meta["calendar_lo"]), str(meta["calendar_hi"])
    hard = [
        r
        for r in proof
        if r.get("record_type") == "hard_map"
        and r.get("active")
        and r.get("production_disagrees")
        and lo <= r["date"] <= hi
        and in_scope(r["date"])
    ]
    lit_by_sess = {
        r["session_id"]: r
        for r in proof
        if r.get("record_type") == "literal_opening" and r.get("matched")
    }
    # fingerprint lag verdicts if present
    fp_day: dict[str, dict[str, Any]] = {}
    try:
        for r in load("fingerprint_session_shift_lag"):
            if r.get("record_type") == "lag_day":
                fp_day[r["date"]] = r
    except Exception:
        pass

    graph = load_graph()
    axis = _axis_by_inv_sess()
    flat_text = _flat_text_by_id()
    enr_by_date = _enriched_by_date()
    enr_text: dict[str, str] = {}
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if vid:
            enr_text[vid] = str(er.get("text") or "")

    if limit is not None:
        hard = hard[: max(0, limit)]

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "inventory": inventory,
            "calendar_lo": lo,
            "calendar_hi": hi,
            "n_cards": len(hard),
            "question": (
                "On this calendar day, does the HARD session's dated folio carry the "
                "sitting (trust archival dating), or does the PRODUCTION session's "
                "HTR text match the enriched edition (trust content association)?"
            ),
            "policy": (
                "Human adjudication only. Does not write PINNED_TO or ALIGNED_TO. "
                "Channels shown side by side: hard dated scans, production observed "
                "scans, literal opening on hard, enriched snippets, fingerprint day "
                "verdict if available."
            ),
            **scope_meta(),
        }
    ]

    for hr in hard:
        date = hr["date"]
        hard_sid = hr["session_id"]
        prod_sid = hr["production_session"]
        bridge = list(hr.get("dated_scans_on_session") or [])
        hard_obs = _observed_scans(graph, hard_sid, inventory)
        prod_obs = _observed_scans(graph, prod_sid, inventory)
        focus_hard = bridge[0] if bridge else (hard_obs[0] if hard_obs else None)
        focus_prod = prod_obs[0] if prod_obs else None
        lit = lit_by_sess.get(hard_sid) or {}
        fp = fp_day.get(date) or {}

        rows.append({
            "record_type": "adjudication_card",
            "review_id": f"lag:{inventory}:{date}",
            "date": date,
            "inventory": inventory,
            "hard_session": hard_sid,
            "production_session": prod_sid,
            "hard_session_num": hr.get("session_num"),
            "hard_bridge_scans": bridge,
            "hard_observed_scans": hard_obs,
            "production_observed_scans": prod_obs,
            "hard_iiif": iiif_for_scan(inventory, int(focus_hard)) if focus_hard else None,
            "production_iiif": (
                iiif_for_scan(inventory, int(focus_prod)) if focus_prod else None
            ),
            "literal_opening_flat": lit.get("opening_flat"),
            "literal_snippet": (lit.get("snippet") or "")[:SNIPPET],
            "hard_opening_snippet": _session_opening_text(hard_sid, flat_text, axis),
            "production_opening_snippet": _session_opening_text(prod_sid, flat_text, axis),
            "enriched_snippets": _enriched_snippets(date, enr_by_date, enr_text),
            "n_enriched": len(enr_by_date.get(date) or []),
            "fingerprint_day_verdicts": fp.get("verdicts"),
            "prompt": (
                f"{date}: open HARD IIIF (dated path) and PRODUCTION IIIF. "
                f"Does the enriched sitting belong with the hard folio's date heading, "
                f"or with the production session's HTR body?"
            ),
            "verdict_options": [
                "trust_hard_dating",
                "trust_production_content",
                "both_partially",
                "unclear",
            ],
        })
    return rows


def load_notes() -> dict[str, dict[str, Any]]:
    try:
        rows = load(NOTES_DATASET)
    except Exception:
        return {}
    return {
        r["review_id"]: r
        for r in rows
        if r.get("record_type") == "note" and r.get("review_id")
    }


def save_note(
    review_id: str,
    *,
    verdict: str,
    note: str = "",
) -> None:
    notes = load_notes()
    notes[review_id] = {
        "record_type": "note",
        "review_id": review_id,
        "verdict": verdict,
        "note": note,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    save_semi_structured(
        list(notes.values()),
        logical_name=NOTES_DATASET,
        script=__file__,
        description=(
            "Human verdicts on lag-window hard-dating vs production-content "
            "adjudication cards. No production wire."
        ),
        parent_sources=[CARDS_DATASET],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="first N disagree days")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rows = build_cards(limit=args.limit)
    meta = next(r for r in rows if r["record_type"] == "meta")
    print(
        f"adjudication deck  {meta['inventory']} {meta['calendar_lo']}..{meta['calendar_hi']}  "
        f"cards={meta['n_cards']}"
    )
    print(f"  Q: {meta['question']}")
    for r in rows:
        if r.get("record_type") != "adjudication_card":
            continue
        print(
            f"  {r['date']}  hard={r['hard_session'].replace('session-3185-','')}  "
            f"prod={r['production_session'].replace('session-3185-','')}  "
            f"hard_iiif_scan={r['hard_bridge_scans'][:1] or r['hard_observed_scans'][:1]}  "
            f"prod_scans={r['production_observed_scans'][:3]}"
        )
        if r.get("hard_iiif"):
            print(f"    HARD  {r['hard_iiif']}")
        if r.get("production_iiif"):
            print(f"    PROD  {r['production_iiif']}")
    if args.write:
        save_semi_structured(
            rows,
            logical_name=CARDS_DATASET,
            script=__file__,
            description=(
                "Human adjudication cards for hard-map vs fingerprint-content conflict "
                "on pin-disagree days: IIIF both sides, opening + enriched snippets. "
                "No production wire."
            ),
            parent_sources=[
                "hard_recalibrate_proof",
                "fingerprint_session_shift_lag",
                "paragraph_axis_1626_1630",
            ],
        )
        print(f"wrote {CARDS_DATASET}")


if __name__ == "__main__":
    main()

"""Multi-day / multi-session problem-sequence review — stream stretches, not one session.

Judgment unit is a continuous inventory stretch (calendar span × session span) seeded from
``session_anchor_shift_date_trust`` ``text_inside`` rows. Session numbers are labels inside
the stretch, not the card identity. Notes only — no production ``PINNED_TO`` wire.

Date↔scan notes shape as ``dated_as_review`` claims via
``dated_as_review_claims_from_notes`` (parse-only; not written to the graph). See
``docs/SEQUENCE_MODEL.md`` § Anchors are claims.

Usage (library + notebook):
    from sequence_graph.problem_sequence_review import build_review_deck, load_notes, save_notes
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from typing import Any

from build_alignment_new import enriched_volgnr
from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from sequence_graph.consolidate import node_aligned_bucket
from sequence_graph.correspondence import OBSERVED_ON, PINNED_TO
from sequence_graph.nodes import EnrichedResolution
from sequence_graph.persist import load_graph
from sequence_graph.physical_pin_review import iiif_for_scan
from sequence_graph.short_signal import classify_enriched, opening_strength
from running_axis.stream import parse_flat_id

import networkx as nx
import pandas as pd

DATE_TRUST_DATASET = "session_anchor_shift_date_trust"
NOTES_DATASET = "problem_sequence_review_notes"
MAX_SHORT_CRUMBS = 5
MAX_OPENING_CRUMBS = 5

# Free-text date↔scan note, e.g. "..._0340.jpg/... contains date 1626-08-22"
_CONTAINS_DATE_RE = re.compile(
    r"(?P<url>https?://\S*?/(?P<inventory>\d{4})/\S*?_(?P=inventory)_"
    r"(?P<scan>\d+)\.(?:jpg|jpeg|png)\S*)\s+contains\s+date\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


def _session_num(session_id: str) -> int | None:
    m = re.search(r"num-(\d+)", session_id or "")
    return int(m.group(1)) if m else None


def _text_inside_seeds() -> list[dict[str, Any]]:
    return [
        r
        for r in load(DATE_TRUST_DATASET)
        if r.get("record_type") == "text_inside"
        and is_main_series(str(r.get("inventory") or ""))
    ]


def _scans_for_session(graph: nx.MultiDiGraph, session_id: str) -> list[int]:
    node = f"session:{session_id}"
    if node not in graph:
        return []
    nums: list[int] = []
    for _u, v, ed in graph.out_edges(node, data=True):
        if ed.get("kind") != OBSERVED_ON:
            continue
        if graph.nodes[v].get("kind") != "Scan":
            continue
        nums.append(int(graph.nodes[v]["obj"].scan_num))
    return sorted(set(nums))


def _production_pin_for_date(graph: nx.MultiDiGraph, date: str) -> str | None:
    """Prefer production ``PINNED_TO`` over staged ``PINNED_TO:physical``."""
    day = f"day:{date}"
    if day not in graph:
        return None
    physical: str | None = None
    for _u, v, key, ed in graph.out_edges(day, keys=True, data=True):
        if ed.get("kind") != PINNED_TO:
            continue
        if graph.nodes[v].get("kind") != "Session":
            continue
        sid = graph.nodes[v]["obj"].session_id
        if key == f"{PINNED_TO}:physical" or str(key).endswith(":physical"):
            physical = sid
            continue
        return sid
    return physical


def _flat_text_by_id() -> dict[str, str]:
    parts: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in load("paragraph_axis_1626_1630"):
        flat = str(row.get("flat_id") or "")
        if not flat or not is_main_series(flat):
            continue
        try:
            pi = int(row.get("para_index") or 0)
        except (TypeError, ValueError):
            pi = 0
        parts[flat].append((pi, str(row.get("text") or "")))
    return {
        fid: " ".join(t for _pi, t in sorted(chunks))
        for fid, chunks in parts.items()
    }


def _flats_in_session_range(
    inventory: str, lo: int, hi: int, flat_text: dict[str, str]
) -> list[str]:
    out: list[str] = []
    for flat in flat_text:
        if not flat.startswith(f"session-{inventory}-num-"):
            continue
        try:
            _inv, sess, _res = parse_flat_id(flat)
        except Exception:
            continue
        if lo <= sess <= hi:
            out.append(flat)
    out.sort(key=lambda f: parse_flat_id(f)[1:3])
    return out


def _enriched_in_span(lo: str, hi: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date) or not (lo <= date <= hi):
            continue
        vid = enriched_volgnr(er)
        if not vid:
            continue
        rows.append(er)
    rows.sort(
        key=lambda er: (
            str(er.get("date") or "")[:10],
            int(er.get("resolution_index") or 0),
        )
    )
    return rows


def _timeline(
    graph: nx.MultiDiGraph,
    *,
    inventory: str,
    calendar_lo: str,
    calendar_hi: str,
    sess_lo: int,
    sess_hi: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Per-day pin presence + session-id list for the stretch."""
    days: list[str] = []
    cur = pd.Period(calendar_lo, freq="D")
    end = pd.Period(calendar_hi, freq="D")
    while cur <= end:
        days.append(str(cur))
        cur += 1
    rows: list[dict[str, Any]] = []
    for date in days:
        pin = _production_pin_for_date(graph, date)
        pin_num = _session_num(pin) if pin else None
        in_sess_band = (
            pin_num is not None and sess_lo <= pin_num <= sess_hi
        )
        rows.append({
            "date": date,
            "production_pin": pin,
            "pin_in_stretch_sessions": in_sess_band,
            "no_production_pin": pin is None,
        })
    sessions = [
        f"session-{inventory}-num-{n}" for n in range(sess_lo, sess_hi + 1)
    ]
    return rows, sessions


def build_stretch_card(
    seed: dict[str, Any],
    *,
    graph: nx.MultiDiGraph,
    flat_text: dict[str, str],
) -> dict[str, Any]:
    inventory = str(seed["inventory"])
    lo = str(seed["calendar_lo"])[:10]
    hi = str(seed["calendar_hi"])[:10]
    lo_s = seed.get("anchor_lo_session") or ""
    hi_s = seed.get("anchor_hi_session") or ""
    sess_lo = _session_num(str(lo_s))
    sess_hi = _session_num(str(hi_s))
    if sess_lo is None or sess_hi is None:
        raise ValueError(f"bad session anchors on seed {lo}..{hi}")

    enriched = _enriched_in_span(lo, hi)
    n_aligned = 0
    short_unaligned: list[dict[str, Any]] = []
    for er in enriched:
        date = str(er.get("date") or "")[:10]
        idx = int(er.get("resolution_index") or 0)
        node = EnrichedResolution(date=date, index=idx).node_id
        bucket = (
            node_aligned_bucket(graph, node) if node in graph else "unaligned"
        )
        if bucket != "unaligned":
            n_aligned += 1
            continue
        reason = classify_enriched(er)
        if not reason:
            continue
        text = str(er.get("text") or "")
        short_unaligned.append({
            "volgnr": enriched_volgnr(er),
            "reason": reason,
            "snippet": text[:160].replace("\n", " "),
        })

    flats = _flats_in_session_range(inventory, sess_lo, sess_hi, flat_text)
    openings: list[dict[str, Any]] = []
    for fid in flats:
        strength = opening_strength(flat_text.get(fid) or "")
        if strength <= 0:
            continue
        openings.append({
            "flat_id": fid,
            "strength": strength,
            "snippet": (flat_text.get(fid) or "")[:160].replace("\n", " "),
        })

    lo_scans = _scans_for_session(graph, str(lo_s))
    hi_scans = _scans_for_session(graph, str(hi_s))
    mid_num = (sess_lo + sess_hi) // 2
    # Mid only when it is a distinct session (2-session bands otherwise repeat lo).
    mid_scans: list[int] = []
    if mid_num not in (sess_lo, sess_hi):
        mid_scans = _scans_for_session(
            graph, f"session-{inventory}-num-{mid_num}"
        )
    scan_links: list[dict[str, Any]] = []
    seen_scans: set[int] = set()
    for label, nums in (
        ("anchor_lo", lo_scans[:1]),
        ("mid", mid_scans[:1]),
        ("anchor_hi", hi_scans[-1:] if hi_scans else []),
    ):
        for num in nums:
            if num in seen_scans:
                continue
            seen_scans.add(num)
            scan_links.append({
                "role": label,
                "inventory": inventory,
                "scan_num": num,
                "iiif_url": iiif_for_scan(inventory, num),
            })

    timeline_days, session_ids = _timeline(
        graph,
        inventory=inventory,
        calendar_lo=lo,
        calendar_hi=hi,
        sess_lo=sess_lo,
        sess_hi=sess_hi,
    )
    n_no_pin = sum(1 for d in timeline_days if d["no_production_pin"])
    review_id = f"stretch:{inventory}:{lo}:{hi}:{sess_lo}:{sess_hi}"

    return {
        "record_type": "review_card",
        "card_kind": "problem_sequence",
        "review_id": review_id,
        "inventory": inventory,
        "calendar_lo": lo,
        "calendar_hi": hi,
        "anchor_lo_session": lo_s,
        "anchor_hi_session": hi_s,
        "sess_lo": sess_lo,
        "sess_hi": sess_hi,
        "n_htr_sessions_inclusive": sess_hi - sess_lo + 1,
        "n_enriched": len(enriched),
        "n_aligned": n_aligned,
        "n_unaligned": len(enriched) - n_aligned,
        "n_short_unaligned": len(short_unaligned),
        "n_opening_hits": len(openings),
        "n_days_no_production_pin": n_no_pin,
        "charge_k_e": seed.get("charge_k_e"),
        "timeline_days": timeline_days,
        "session_ids": session_ids,
        "short_crumbs": short_unaligned[:MAX_SHORT_CRUMBS],
        "opening_crumbs": openings[:MAX_OPENING_CRUMBS],
        "scan_links": scan_links,
        "iiif_url": scan_links[0]["iiif_url"] if scan_links else None,
        "prompt": (
            f"Problem sequence {inventory} {lo}..{hi} / "
            f"sessions {sess_lo}..{sess_hi}. "
            f"Unaligned {len(enriched) - n_aligned}/{len(enriched)}; "
            f"short-unaligned {len(short_unaligned)}; "
            f"openings {len(openings)}. "
            "Note what looks local vs wall-artefact — session_num is not the judgment key."
        ),
    }


def build_review_deck(*, limit: int | None = None) -> list[dict[str, Any]]:
    """Deck of problem-sequence cards, largest unaligned mass first."""
    print("Loading graph + flat text (once)…")
    graph = load_graph()
    flat_text = _flat_text_by_id()
    seeds = _text_inside_seeds()
    seeds = sorted(
        seeds,
        key=lambda r: (-(r.get("n_unaligned") or 0), r.get("calendar_lo") or ""),
    )
    if limit is not None:
        seeds = seeds[:limit]
    return [
        build_stretch_card(seed, graph=graph, flat_text=flat_text) for seed in seeds
    ]


def load_notes() -> dict[str, dict[str, Any]]:
    try:
        rows = list(load(NOTES_DATASET))
    except FileNotFoundError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("record_type") != "note":
            continue
        rid = r.get("review_id")
        if rid:
            out[str(rid)] = r
    return out


def save_notes(notes: dict[str, dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "n_notes": len(notes),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "policy": (
                "Qualitative notes on multi-day/session problem sequences. "
                "No production PINNED_TO wire. Judgment unit = stretch."
            ),
            **scope_meta(),
        }
    ]
    for rid, row in sorted(notes.items()):
        rec = dict(row)
        rec["record_type"] = "note"
        rec["review_id"] = rid
        rows.append(rec)
    save_semi_structured(
        rows,
        logical_name=NOTES_DATASET,
        script=__file__,
        description=(
            "Human notes on multi-day/multi-session problem-sequence review cards "
            "(seeded from session_anchor_shift_date_trust text_inside). "
            "Judgment unit is the stretch, not session_num. No production wire."
        ),
        parent_sources=[DATE_TRUST_DATASET],
    )


def record_note(
    notes: dict[str, dict[str, Any]],
    card: dict[str, Any],
    note: str,
    *,
    flag: str = "seen",
) -> dict[str, dict[str, Any]]:
    """Persist free-text note. flag ∈ {seen, walls_feel_wrong, opening_cluster, other}."""
    notes[card["review_id"]] = {
        "review_id": card["review_id"],
        "card_kind": card.get("card_kind"),
        "flag": flag,
        "note": note,
        "inventory": card.get("inventory"),
        "calendar_lo": card.get("calendar_lo"),
        "calendar_hi": card.get("calendar_hi"),
        "anchor_lo_session": card.get("anchor_lo_session"),
        "anchor_hi_session": card.get("anchor_hi_session"),
        "n_unaligned": card.get("n_unaligned"),
        "n_opening_hits": card.get("n_opening_hits"),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    return notes


def dated_as_review_claims_from_notes(
    notes: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Shape date↔scan review notes as ``dated_as_review`` claim records.

    Parse-only: does **not** write ``DATED_AS:review`` into the graph. Pattern::

        <iiif_url> contains date YYYY-MM-DD

    Skips notes that do not match (diagnoses, UI blockers, resolution crumbs).
    Main-series and in-scope dates only.
    """
    if notes is None:
        notes = load_notes()
    claims: list[dict[str, Any]] = []
    for rid, row in sorted(notes.items()):
        text = str(row.get("note") or "")
        for m in _CONTAINS_DATE_RE.finditer(text):
            inv = m.group("inventory")
            date = m.group("date")
            if not is_main_series(inv) or not in_scope(date):
                continue
            claims.append({
                "claim_kind": "dated_as_review",
                "edge": "DATED_AS:review",
                "inventory": inv,
                "scan_num": int(m.group("scan")),
                "date": date,
                "evidence_url": m.group("url"),
                "review_id": rid,
                "flag": row.get("flag"),
                "decided_at": row.get("decided_at"),
                "source_note": text,
            })
    return claims


def card_html(card: dict[str, Any], prior: dict[str, Any] | None = None) -> str:
    prior = prior or {}
    lo, hi = card.get("calendar_lo"), card.get("calendar_hi")
    inv = card.get("inventory")
    lines = [
        f"<h3>problem sequence — {escape(str(inv))} {escape(str(lo))}..{escape(str(hi))}</h3>",
        f"<p>{escape(card.get('prompt') or '')}</p>",
        (
            f"<p><b>Sessions</b> {card.get('sess_lo')}..{card.get('sess_hi')} "
            f"({card.get('n_htr_sessions_inclusive')} inclusive) · "
            f"<b>enriched</b> {card.get('n_enriched')} · "
            f"<b>unaligned</b> {card.get('n_unaligned')} · "
            f"<b>short∩unaligned</b> {card.get('n_short_unaligned')} · "
            f"<b>openings</b> {card.get('n_opening_hits')} · "
            f"<b>days w/o production pin</b> {card.get('n_days_no_production_pin')}</p>"
        ),
    ]
    day_bits: list[str] = []
    for d in card.get("timeline_days") or []:
        mark = "*" if d.get("no_production_pin") else ""
        day_bits.append(f"{d['date'][5:]}{mark}")
    if day_bits:
        lines.append(
            "<p><b>Days</b> (* = no production PINNED_TO): "
            f"<code style='font-size:0.85rem'>{escape(' · '.join(day_bits))}</code></p>"
        )
    sess_bits = [
        s.replace(f"session-{inv}-num-", "n")
        for s in (card.get("session_ids") or [])
    ]
    if sess_bits:
        shown = sess_bits if len(sess_bits) <= 24 else (
            sess_bits[:12] + ["…"] + sess_bits[-11:]
        )
        lines.append(
            f"<p><b>Session band</b>: "
            f"<code style='font-size:0.85rem'>{escape(' '.join(shown))}</code></p>"
        )

    if card.get("short_crumbs"):
        lines.append("<p><b>Unaligned short crumbs</b></p><ul>")
        for c in card["short_crumbs"]:
            lines.append(
                f"<li><code>{escape(str(c.get('volgnr')))}</code> "
                f"[{escape(str(c.get('reason')))}] "
                f"{escape(str(c.get('snippet') or ''))}</li>"
            )
        lines.append("</ul>")
    if card.get("opening_crumbs"):
        lines.append("<p><b>HTR opening crumbs</b></p><ul>")
        for c in card["opening_crumbs"]:
            lines.append(
                f"<li><code>{escape(str(c.get('flat_id')))}</code> "
                f"str={c.get('strength')} "
                f"{escape(str(c.get('snippet') or ''))}</li>"
            )
        lines.append("</ul>")

    for link in card.get("scan_links") or []:
        url = link.get("iiif_url")
        if not url:
            continue
        role = link.get("role")
        inv_s, num = link.get("inventory"), link.get("scan_num")
        lines.append(
            f"<p><b>Scan ({escape(str(role))})</b> {escape(str(inv_s))}/"
            f"{int(num):04d} — "
            f'<a href="{escape(url)}" target="_blank" rel="noopener">IIIF</a></p>'
            f'<p><img src="{escape(url)}" alt="scan" '
            f'style="max-width:100%;max-height:360px;"/></p>'
        )

    if prior:
        note = escape(str(prior.get("note") or ""))
        lines.append(
            f"<p><b>Prior flag:</b> {escape(str(prior.get('flag')))} "
            f"@ {escape(str(prior.get('decided_at') or ''))}<br/>"
            f"<b>Note:</b> {note or '—'}</p>"
        )
    return "\n".join(lines)

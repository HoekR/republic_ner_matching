"""Stage 8–9 of remediation: place under promoted PINNED_TO lids; wire on gate PASS.

Procedure ([`docs/steps/STEP_REMEDIATION_TRACK_GOLD.md`](../docs/steps/STEP_REMEDIATION_TRACK_GOLD.md)):
  7 pin promote → **8 place under lids** → **9 wire backbone**.

For each promoted date, pack editorial resolutions onto the sitting's **scan-span**
paragraph stream: from this date's ``DATED_AS`` heading scan through the scan before
the next ``DATED_AS`` (continuation paper has no date heading — do not invent
``DATED_AS``). Stream = concat of sessions ``OBSERVED_ON`` any scan in that span
(fallback: pinned session alone). Abstain when ``room < k_e`` (incomplete HTR under
a correct lid must not tank the window gate). Abstain when concordance
``day_status == nihil_actum`` (Tier V: nihil days must have zero
``resolved_session_id`` attributions).

Gate: seed-slice ``separated`` rises, corpus does not fall; always report vs uniform.

On ``--wire --push-graph`` (gate PASS only): write concordance spans and
``ALIGNED_TO:hard_place`` (enriched → HTR flat at placed start).

Remediation: ``--strip-nihil`` clears ``hard_pin_place`` attributions on
nihil days (session + paragraph) and drops matching graph edges.

Usage:
    uv run python -m sequence_graph.hard_pin_place --write
    uv run python -m sequence_graph.hard_pin_place --write --wire --push-graph
    uv run python -m sequence_graph.hard_pin_place --strip-nihil --push-graph
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from typing import Any

import networkx as nx
import pandas as pd

from data_io import load, save_parquet, save_semi_structured
from running_axis.stream import parse_flat_id
from scripts.apply_duplicate_session_splits_eval import (
    _place_in_range,
    separated_total,
    slice_separated,
)
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from scripts.separated_accuracy_eval import label_separation, uniform_start_paragraphs
from scripts.wire_duplicate_session_splits import _place_prefer_existing
from sequence_graph.correspondence import ALIGNED_TO, DATED_AS, Evidence, OBSERVED_ON
from sequence_graph.hard_pin_promote import OUTPUT_DATASET as PROMOTE_DATASET
from sequence_graph.nodes import EnrichedResolution, HtrResolution
from sequence_graph.persist import load_graph, save_loaded_graph

CONCORDANCE = "resolution_concordance_1626_1630"
AXIS = "paragraph_axis_1626_1630"
OUTPUT_DATASET = "hard_pin_placement_lift"
EDGE_KEY = f"{ALIGNED_TO}:hard_place"
CHANNEL = "hard_pin_place"
PRED_STATUS = "hard_pin_place"
NIHIL_STATUS = "nihil_actum"
STRIP_NIHIL_DATASET = "hard_pin_place_nihil_strip"

_SESSION_NUM = re.compile(r"num-(\d+)")


def session_paragraph_stream(session_id: str) -> list[str]:
    """Flat_ids of a session in resolution/para order — one stream index per axis row."""
    rows = [
        r
        for r in load(AXIS)
        if str(r.get("flat_id") or "").startswith(f"{session_id}-resolution-")
    ]

    def key(row: dict) -> tuple[int, int]:
        _inv, _sess, res_num = parse_flat_id(row["flat_id"])
        return (res_num, int(row.get("para_index") or 0))

    rows.sort(key=key)
    return [str(r["flat_id"]) for r in rows]


def inventory_from_session(session_id: str) -> str:
    """Inventory digit string from ``session-{inv}-num-N``."""
    parts = session_id.split("-")
    if len(parts) >= 2 and parts[0] == "session":
        return parts[1]
    return ""


def dated_scans_for_day(
    graph: nx.MultiDiGraph, inventory: str, date: str
) -> list[int]:
    """Scan numbers with ``DATED_AS`` → this sitting day (heading pages only)."""
    day = f"day:{date}"
    if day not in graph:
        return []
    out: list[int] = []
    for u, _v, ed in graph.in_edges(day, data=True):
        if ed.get("kind") != DATED_AS:
            continue
        if graph.nodes[u].get("kind") != "Scan":
            continue
        scan = graph.nodes[u]["obj"]
        if str(scan.inventory) != str(inventory):
            continue
        out.append(int(scan.scan_num))
    return sorted(set(out))


def next_dated_scan_after(
    graph: nx.MultiDiGraph, inventory: str, scan_num: int
) -> int | None:
    """Next scan in this inventory that carries any ``DATED_AS`` heading."""
    for sn in range(scan_num + 1, scan_num + 500):
        node = f"scan:{inventory}:{sn}"
        if node not in graph:
            continue
        for _u, v, ed in graph.out_edges(node, data=True):
            if ed.get("kind") == DATED_AS and graph.nodes[v].get("kind") == "SittingDay":
                return sn
    return None


def sitting_scan_span(
    graph: nx.MultiDiGraph, inventory: str, date: str
) -> dict[str, Any]:
    """Physical sitting span: heading scan .. scan before next heading (exclusive hi).

    ``DATED_AS`` only exists on pages with date headings; continuation scans in the
    span correctly have none. Room comes from sessions ``OBSERVED_ON`` those scans.
    """
    headings = dated_scans_for_day(graph, inventory, date)
    if not headings:
        return {
            "span_lo": None,
            "span_hi_exclusive": None,
            "heading_scans": [],
            "next_dated_scan": None,
            "span_scans": [],
            "scans_without_session": [],
            "span_sessions": [],
        }
    lo = min(headings)
    nxt = next_dated_scan_after(graph, inventory, lo)
    hi = nxt if nxt is not None else lo + 1
    span_scans = list(range(lo, hi))
    sessions: list[tuple[int, int, str]] = []  # (first_scan, sess_num, sid)
    seen: set[str] = set()
    without: list[int] = []
    for sn in span_scans:
        node = f"scan:{inventory}:{sn}"
        if node not in graph:
            without.append(sn)
            continue
        found = False
        for u, _v, ed in graph.in_edges(node, data=True):
            if ed.get("kind") != OBSERVED_ON:
                continue
            if graph.nodes[u].get("kind") != "Session":
                continue
            sid = graph.nodes[u]["obj"].session_id
            if not is_main_series(sid) or sid in seen:
                continue
            found = True
            seen.add(sid)
            m = _SESSION_NUM.search(sid)
            snum = int(m.group(1)) if m else 0
            sessions.append((sn, snum, sid))
        if not found:
            without.append(sn)
    sessions.sort()
    return {
        "span_lo": lo,
        "span_hi_exclusive": hi,
        "heading_scans": headings,
        "next_dated_scan": nxt,
        "span_scans": span_scans,
        "scans_without_session": without,
        "span_sessions": [s for _a, _b, s in sessions],
    }


def span_paragraph_stream(
    span_sessions: list[str],
    *,
    fallback_session_id: str,
    streams: dict[str, list[str]] | None = None,
) -> list[str]:
    """Concat session streams in span order; fall back to the pinned session alone."""
    if streams is None:
        streams = {}
    sids = list(span_sessions) if span_sessions else [fallback_session_id]
    if fallback_session_id not in sids:
        # Pin session always included (hard lid) even if OBSERVED_ON misspelled
        sids = [fallback_session_id, *[s for s in sids if s != fallback_session_id]]
    out: list[str] = []
    for sid in sids:
        if sid not in streams:
            streams[sid] = session_paragraph_stream(sid)
        out.extend(streams[sid])
    return out


def promoted_date_sessions(
    promote_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Wire-edge population from hard_pin_promote (stage 7)."""
    if promote_rows is None:
        promote_rows = list(load(PROMOTE_DATASET))
    meta = next((r for r in promote_rows if r.get("record_type") == "meta"), {})
    edges = [
        r
        for r in promote_rows
        if r.get("record_type") == "wire_edge"
        and in_scope(str(r.get("date") or ""))
        and is_main_series(str(r.get("session_id") or ""))
    ]
    return sorted(edges, key=lambda r: str(r["date"])), meta


def place_date_on_session(
    group: pd.DataFrame,
    *,
    session_id: str,
    stream: list[str],
    span_meta: dict[str, Any] | None = None,
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """Return (start,end) pairs + log for one date's concordance rows.

    Abstains when ``room < k_e``: packing onto an incomplete HTR span (continuation
    scans often lack ``OBSERVED_ON``) would force shared starts and tank ``separated``.
    Abstains when ``day_status == nihil_actum`` (Tier V invariant).
    """
    k = len(group)
    room = len(stream)
    entry: dict[str, Any] = {
        "record_type": "date_place",
        "date": str(group["enriched_date"].iloc[0])[:10],
        "session_id": session_id,
        "k_e": k,
        "room": room,
        "placed": False,
        "reason": "",
        "n_unique_starts": 0,
        "n_had_attr": int(group["paragraph_start_index"].notna().sum()),
    }
    if span_meta:
        entry.update({
            "span_lo": span_meta.get("span_lo"),
            "span_hi_exclusive": span_meta.get("span_hi_exclusive"),
            "heading_scans": span_meta.get("heading_scans"),
            "next_dated_scan": span_meta.get("next_dated_scan"),
            "span_sessions": span_meta.get("span_sessions"),
            "scans_without_session": span_meta.get("scans_without_session"),
        })
    if k == 0:
        entry["reason"] = "no_concordance_rows"
        return [], entry
    if _group_is_nihil(group):
        entry["reason"] = "nihil_actum_abstain"
        return [], entry
    if room <= 0:
        entry["reason"] = "empty_session_stream"
        return [], entry
    if room < k:
        entry["reason"] = "room_lt_ke_abstain"
        entry["n_unique_starts"] = 0
        return [], entry

    lo, hi = 0, room - 1
    attributed = group.loc[group["paragraph_start_index"].notna()]
    if attributed.empty:
        uniq = 0
        in_range = False
    else:
        starts = attributed["paragraph_start_index"].astype(int)
        uniq = int(starts.nunique())
        in_range = bool(((starts >= lo) & (starts <= hi)).all())
    # Prefer existing only when already fully separated inside the stream;
    # otherwise pack exclusive starts (stage-8 goal = separated lift).
    if uniq >= k and in_range and room >= k:
        placements = _place_prefer_existing(group, lo, hi)
    else:
        placements = _place_in_range(k, lo, hi)
    entry.update({
        "placed": True,
        "reason": "placed",
        "n_unique_starts": len({p[0] for p in placements}),
        "paragraph_range": [lo, hi],
    })
    return placements, entry


def _group_is_nihil(group: pd.DataFrame) -> bool:
    """True when concordance day_status marks the date as nihil_actum."""
    if "day_status" not in group.columns or group.empty:
        return False
    statuses = group["day_status"].astype(str)
    return bool((statuses == NIHIL_STATUS).any())


def strip_nihil_hard_place(
    concordance: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Clear hard_pin_place session + paragraph attrs on nihil_actum days.

    Tier V counts ``resolved_session_id`` as attribution — clearing paragraphs
    alone is not enough. Returns the cleaned frame and one log row per date.
    """
    out = concordance.copy()
    out["enriched_date"] = out["enriched_date"].astype(str).str.slice(0, 10)
    if "day_status" not in out.columns:
        return out, []
    nihil = out["day_status"].astype(str) == NIHIL_STATUS
    if "paragraph_prediction_status" in out.columns:
        from_place = out["paragraph_prediction_status"].astype(str) == PRED_STATUS
    else:
        from_place = pd.Series(False, index=out.index)
    has_session = out["resolved_session_id"].notna()
    if "paragraph_start_index" in out.columns:
        has_para = out["paragraph_start_index"].notna()
    else:
        has_para = pd.Series(False, index=out.index)
    # Prefer prediction-status cue; also catch the measured V shape (session +
    # paragraph under nihil) if status was cleared but attrs remain.
    mask = nihil & (from_place | (has_session & has_para))
    log: list[dict[str, Any]] = []
    if not bool(mask.any()):
        return out, log
    for date, group in out.loc[mask].groupby("enriched_date", sort=True):
        log.append({
            "record_type": "nihil_strip",
            "date": str(date)[:10],
            "n_rows": int(len(group)),
            "session_ids": sorted({
                str(s) for s in group["resolved_session_id"].dropna().unique()
            }),
            "had_pred_status": (
                PRED_STATUS
                if "paragraph_prediction_status" in group.columns
                and (group["paragraph_prediction_status"].astype(str) == PRED_STATUS).any()
                else ""
            ),
        })
    out.loc[mask, "resolved_session_id"] = pd.NA
    if "paragraph_start_index" in out.columns:
        out.loc[mask, "paragraph_start_index"] = pd.NA
    if "paragraph_end_index" in out.columns:
        out.loc[mask, "paragraph_end_index"] = pd.NA
    if "paragraph_prediction_status" in out.columns:
        out.loc[mask, "paragraph_prediction_status"] = pd.NA
    return out, log


def drop_hard_place_edges_for_dates(
    graph: nx.MultiDiGraph, dates: set[str]
) -> int:
    """Remove ``ALIGNED_TO:hard_place`` edges whose enriched date is in ``dates``."""
    if not dates:
        return 0
    drop = [
        (u, v, k)
        for u, v, k, d in graph.edges(keys=True, data=True)
        if d.get("kind") == ALIGNED_TO
        and k == EDGE_KEY
        and u.startswith("enriched:")
        and u.split(":", 2)[1] in dates
    ]
    graph.remove_edges_from(drop)
    return len(drop)

    lo, hi = 0, room - 1
    attributed = group.loc[group["paragraph_start_index"].notna()]
    if attributed.empty:
        uniq = 0
        in_range = False
    else:
        starts = attributed["paragraph_start_index"].astype(int)
        uniq = int(starts.nunique())
        in_range = bool(((starts >= lo) & (starts <= hi)).all())
    # Prefer existing only when already fully separated inside the stream;
    # otherwise pack exclusive starts (stage-8 goal = separated lift).
    if uniq >= k and in_range and room >= k:
        placements = _place_prefer_existing(group, lo, hi)
    else:
        placements = _place_in_range(k, lo, hi)
    entry.update({
        "placed": True,
        "reason": "placed",
        "n_unique_starts": len({p[0] for p in placements}),
        "paragraph_range": [lo, hi],
    })
    return placements, entry


def apply_placements(
    concordance: pd.DataFrame,
    edges: list[dict[str, Any]],
    *,
    streams: dict[str, list[str]] | None = None,
    graph: nx.MultiDiGraph | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    """Rewrite paragraph spans for promoted dates; build ALIGNED_TO wire candidates."""
    out = concordance.copy()
    out["enriched_date"] = out["enriched_date"].astype(str).str.slice(0, 10)
    # Injected ``streams`` (unit tests) ⇒ skip live graph span; production leaves
    # streams=None so we load the graph and use DATED_AS..next heading room.
    live_span = streams is None and graph is None
    if streams is None:
        streams = {}
    if live_span:
        try:
            graph = load_graph()
        except Exception:
            graph = None
    place_log: list[dict[str, Any]] = []
    align_edges: list[dict[str, Any]] = []

    for edge in edges:
        date = str(edge["date"])[:10]
        sid = str(edge["session_id"])
        inv = inventory_from_session(sid)
        span_meta: dict[str, Any] | None = None
        if graph is not None and inv:
            span_meta = sitting_scan_span(graph, inv, date)
            stream = span_paragraph_stream(
                list(span_meta.get("span_sessions") or []),
                fallback_session_id=sid,
                streams=streams,
            )
        else:
            if sid not in streams:
                streams[sid] = session_paragraph_stream(sid)
            stream = streams[sid]
        mask = out["enriched_date"] == date
        group = out.loc[mask]
        placements, entry = place_date_on_session(
            group, session_id=sid, stream=stream, span_meta=span_meta
        )
        entry["verdict"] = edge.get("verdict")
        place_log.append(entry)
        if not entry["placed"] or not placements:
            continue
        order = group.sort_values("resolution_index").index
        out.loc[order, "paragraph_start_index"] = [p[0] for p in placements]
        out.loc[order, "paragraph_end_index"] = [p[1] for p in placements]
        out.loc[order, "paragraph_prediction_status"] = PRED_STATUS
        out.loc[order, "resolved_session_id"] = sid

        ordered = group.sort_values("resolution_index")
        for (_idx, row), (start, end) in zip(ordered.iterrows(), placements):
            if start < 0 or start >= len(stream):
                continue
            flat_id = stream[start]
            align_edges.append({
                "record_type": "wire_edge",
                "date": date,
                "resolution_index": int(row["resolution_index"]),
                "session_id": sid,
                "flat_id": flat_id,
                "paragraph_start_index": int(start),
                "paragraph_end_index": int(end),
                "edge_key": EDGE_KEY,
                "channel": CHANNEL,
                "observed": False,
            })
    return out, place_log, align_edges


def uniform_on_dates(concordance: pd.DataFrame, dates: set[str]) -> dict[str, int]:
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
        for i, _ in enumerate(ordered.index):
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


def run_hard_pin_place(
    *,
    promote_rows: list[dict[str, Any]] | None = None,
    concordance: pd.DataFrame | None = None,
    streams: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    edges, promo_meta = promoted_date_sessions(promote_rows)
    if concordance is None:
        concordance = load(CONCORDANCE)
    before = concordance.copy()
    before["enriched_date"] = before["enriched_date"].astype(str).str.slice(0, 10)
    dates = {str(e["date"])[:10] for e in edges}

    after, place_log, align_edges = apply_placements(
        concordance, edges, streams=streams
    )
    before_slice = slice_separated(before, dates)
    after_slice = slice_separated(after, dates)
    before_corpus = separated_total(before)
    after_corpus = separated_total(after)
    before_uniform = uniform_on_dates(before, dates)
    after_uniform = uniform_on_dates(after, dates)

    delta_slice = after_slice["separated"] - before_slice["separated"]
    delta_corpus = after_corpus - before_corpus
    gate_ok = (
        len(edges) > 0
        and delta_slice > 0
        and delta_corpus >= 0
    )
    gate = "PASS" if gate_ok else "FAIL"

    placed = [r for r in place_log if r.get("placed")]
    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "hard_pin_place",
            "stage": 8,
            "channel": CHANNEL,
            "edge_key": EDGE_KEY,
            "inventory": promo_meta.get("inventory"),
            "calendar_lo": promo_meta.get("calendar_lo"),
            "calendar_hi": promo_meta.get("calendar_hi"),
            "n_dates": len(edges),
            "n_placed": len(placed),
            "n_align_edges": len(align_edges),
            "before_slice_separated": before_slice["separated"],
            "after_slice_separated": after_slice["separated"],
            "delta_slice_separated": delta_slice,
            "before_corpus_separated": before_corpus,
            "after_corpus_separated": after_corpus,
            "delta_corpus_separated": delta_corpus,
            "before_uniform_separated": before_uniform["separated"],
            "after_uniform_separated": after_uniform["separated"],
            "delta_vs_uniform_after": (
                after_slice["separated"] - after_uniform["separated"]
            ),
            "policy": (
                "Stage 8–9 remediation: place under promoted PINNED_TO using "
                "sitting scan-span room (DATED_AS heading scan .. before next "
                "DATED_AS; sessions OBSERVED_ON in span). Abstain when room < k_e "
                "or day_status=nihil_actum (Tier V). "
                "Gate = slice separated↑ and corpus non-decrease; vs uniform. "
                f"Wire = concordance spans + {EDGE_KEY}."
            ),
            "gate": gate,
            **scope_meta(),
        },
        *place_log,
        *align_edges,
        {
            "record_type": "separated_guard",
            "slice_dates": sorted(dates),
            "before": before_slice,
            "after": after_slice,
            "before_uniform": before_uniform,
            "after_uniform": after_uniform,
            "delta_separated": delta_slice,
        },
        {
            "record_type": "summary",
            "n_dates": len(edges),
            "n_placed": len(placed),
            "n_align_edges": len(align_edges),
            "before_slice_separated": before_slice["separated"],
            "after_slice_separated": after_slice["separated"],
            "delta_slice_separated": delta_slice,
            "before_corpus_separated": before_corpus,
            "after_corpus_separated": after_corpus,
            "delta_corpus_separated": delta_corpus,
            "before_uniform_separated": before_uniform["separated"],
            "after_uniform_separated": after_uniform["separated"],
            "gate": gate,
            "next": (
                "Re-run with --wire --push-graph to write concordance + "
                f"{EDGE_KEY} (refuses unless gate=PASS)."
                if gate == "PASS"
                else "NO-GO: do not wire; do not open next lag window on this lever."
            ),
        },
    ]
    # stash preview frame for wire path via module-level is awkward; recompute on wire
    rows[0]["_preview_note"] = "after frame rebuilt on --wire"
    return rows


def push_align_edges(
    graph: nx.MultiDiGraph, align_rows: list[dict[str, Any]]
) -> int:
    """Replace ``ALIGNED_TO:hard_place`` for dates in ``align_rows`` only (other windows kept)."""
    wire_dates = {
        str(row["date"])[:10]
        for row in align_rows
        if row.get("record_type") == "wire_edge" and row.get("date")
    }
    drop = [
        (u, v, k)
        for u, v, k, d in graph.edges(keys=True, data=True)
        if d.get("kind") == ALIGNED_TO
        and k == EDGE_KEY
        and u.startswith("enriched:")
        and u.split(":", 2)[1] in wire_dates
    ]
    graph.remove_edges_from(drop)
    added = 0
    for row in align_rows:
        if row.get("record_type") != "wire_edge":
            continue
        date = str(row["date"])[:10]
        flat_id = str(row["flat_id"])
        if not in_scope(date) or not is_main_series(flat_id):
            continue
        enriched = EnrichedResolution(
            date=date, index=int(row["resolution_index"])
        ).node_id
        htr = HtrResolution.from_flat_id(flat_id).node_id
        if enriched not in graph or htr not in graph:
            continue
        graph.add_edge(
            enriched,
            htr,
            key=EDGE_KEY,
            kind=ALIGNED_TO,
            evidence=Evidence(
                channel=CHANNEL,
                source="sequence_graph.hard_pin_place",
                observed=False,
                confidence=None,
                detail={
                    "session_id": row.get("session_id"),
                    "paragraph_start_index": row.get("paragraph_start_index"),
                    "paragraph_end_index": row.get("paragraph_end_index"),
                },
            ),
        )
        added += 1
    return added


def run_strip_nihil(
    *,
    concordance: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Corpus-wide remediation: strip hard_pin_place attrs on nihil days."""
    if concordance is None:
        concordance = load(CONCORDANCE)
    after, strip_log = strip_nihil_hard_place(concordance)
    before_sep = separated_total(concordance)
    after_sep = separated_total(after)
    dates = {str(r["date"])[:10] for r in strip_log}
    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "strip_nihil",
            "channel": CHANNEL,
            "n_dates_stripped": len(dates),
            "n_rows_stripped": int(sum(r["n_rows"] for r in strip_log)),
            "before_corpus_separated": before_sep,
            "after_corpus_separated": after_sep,
            "delta_corpus_separated": after_sep - before_sep,
            "policy": (
                "Clear resolved_session_id + paragraph spans on nihil_actum days "
                "that hard_pin_place attributed (Tier V remediation)."
            ),
            **scope_meta(),
        },
        *strip_log,
        {
            "record_type": "summary",
            "n_dates_stripped": len(dates),
            "n_rows_stripped": int(sum(r["n_rows"] for r in strip_log)),
            "dates": sorted(dates),
            "before_corpus_separated": before_sep,
            "after_corpus_separated": after_sep,
            "delta_corpus_separated": after_sep - before_sep,
            "gate": "PASS" if strip_log else "NOOP",
            "next": (
                "Re-run metrics_nihil_actum_invariant; expect invariant_passed=True."
                if strip_log
                else "No nihil hard_pin_place attributions found."
            ),
        },
    ]
    return after, rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--write", action="store_true", help=f"persist {OUTPUT_DATASET}")
    parser.add_argument(
        "--wire",
        action="store_true",
        help=f"rewrite {CONCORDANCE} paragraph spans (gate PASS only)",
    )
    parser.add_argument(
        "--push-graph",
        action="store_true",
        help=(
            f"push {EDGE_KEY} edges (gate PASS) or, with --strip-nihil, "
            "drop hard_place edges for stripped dates"
        ),
    )
    parser.add_argument(
        "--strip-nihil",
        action="store_true",
        help=(
            f"remediate Tier V: clear hard_pin_place attributions on "
            f"{NIHIL_STATUS} days in {CONCORDANCE}"
        ),
    )
    args = parser.parse_args(argv)

    if args.strip_nihil:
        after, rows = run_strip_nihil()
        summary = next(r for r in rows if r["record_type"] == "summary")
        print(
            f"strip_nihil  dates={summary['n_dates_stripped']} "
            f"rows={summary['n_rows_stripped']}  "
            f"separated {summary['before_corpus_separated']}→"
            f"{summary['after_corpus_separated']} "
            f"(Δ{summary['delta_corpus_separated']:+d})"
        )
        print(f"  next: {summary.get('next')}")
        path = save_parquet(
            after,
            logical_name=CONCORDANCE,
            script=__file__,
            parent_sources=[CONCORDANCE],
            description=(
                "resolution_concordance after stripping hard_pin_place "
                "attributions on nihil_actum days (Tier V remediation)."
            ),
        )
        print(f"wired concordance: {path}")
        if args.write:
            report = save_semi_structured(
                rows,
                logical_name=STRIP_NIHIL_DATASET,
                script=__file__,
                parent_sources=[CONCORDANCE],
            )
            print(f"wrote strip report {report}")
        if args.push_graph:
            dates = set(summary.get("dates") or [])
            graph = load_graph()
            n = drop_hard_place_edges_for_dates(graph, dates)
            save_loaded_graph(graph)
            print(f"dropped {n} {EDGE_KEY} edges on {len(dates)} dates")
        return

    rows = run_hard_pin_place()
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    print(
        f"hard_pin_place  gate={summary['gate']}  "
        f"dates={summary['n_dates']} placed={summary['n_placed']}  "
        f"align_edges={summary['n_align_edges']}"
    )
    print(
        f"  separated slice: {summary['before_slice_separated']}→"
        f"{summary['after_slice_separated']} "
        f"(Δ{summary['delta_slice_separated']:+d}); "
        f"corpus {summary['before_corpus_separated']}→"
        f"{summary['after_corpus_separated']} "
        f"(Δ{summary['delta_corpus_separated']:+d})"
    )
    print(
        f"  vs uniform: before {summary['before_uniform_separated']}  "
        f"after {summary['after_uniform_separated']}  "
        f"after−uniform={meta['delta_vs_uniform_after']:+d}"
    )
    print(f"  next: {summary.get('next')}")
    print(f"  records: {dict(Counter(r.get('record_type') for r in rows))}")

    if args.write:
        path = save_semi_structured(
            [{k: v for k, v in rows[0].items() if not str(k).startswith("_")}, *rows[1:]],
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[PROMOTE_DATASET, CONCORDANCE],
        )
        from sequence_graph.remediation_run_log import log_hard_pin_place

        log_hard_pin_place(rows)
        print(f"wrote {path}")

    if args.wire or args.push_graph:
        if summary["gate"] != "PASS":
            raise SystemExit(
                f"refusing mutation: gate={summary['gate']} "
                f"(Δslice={summary['delta_slice_separated']}, "
                f"Δcorpus={summary['delta_corpus_separated']})"
            )

    if args.wire:
        edges, _meta = promoted_date_sessions()
        before = load(CONCORDANCE)
        after, _plog, align_edges = apply_placements(before, edges)
        save_parquet(
            after,
            logical_name=CONCORDANCE,
            script=__file__,
            parent_sources=[CONCORDANCE, PROMOTE_DATASET, OUTPUT_DATASET],
            description=(
                "resolution_concordance after hard_pin_place stage 9: paragraph "
                "spans packed onto promoted PINNED_TO session streams for seed window."
            ),
        )
        print(f"wired concordance: {summary['n_placed']} dates placed")
    else:
        align_edges = [r for r in rows if r.get("record_type") == "wire_edge"]

    if args.push_graph:
        if not args.wire:
            # ensure align_edges from fresh apply
            edges, _meta = promoted_date_sessions()
            _after, _plog, align_edges = apply_placements(load(CONCORDANCE), edges)
        graph = load_graph()
        n = push_align_edges(graph, align_edges)
        save_loaded_graph(graph)
        print(f"pushed {n} {EDGE_KEY} edges")


if __name__ == "__main__":
    main()

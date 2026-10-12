"""Hard-evidence recalibration: drop contested production lids, restring, align a→b→c.

When production PINNED_TO disagrees with the physical composite
(Session-OBSERVED_ON-Scan-DATED_AS-SittingDay), ignore production as active lids.
Rebuild the session↔date map from that hard path only, then:

  (a) literal HTR session-opening → enriched resolution seeds
  (b) DP₁ entity + train-fitted TF-IDF fingerprint (fit on tier1 excluding the
      lag window) on soft windows with hard lids
  (c) DP₂ short/opening extend on residue

Hand review notes are held out from lids/seeds; ``--compare-notes`` scores afterward.
No production PINNED_TO wire.

Usage:
    uv run python -m sequence_graph.hard_recalibrate --inventory 3185 --write --compare-notes
"""

from __future__ import annotations

import argparse
import re
import statistics
from collections import Counter, defaultdict
from typing import Any

import networkx as nx
import pandas as pd

from build_alignment_new import enriched_volgnr
from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from sequence_graph.align import CostModel, DpPrinciples, build_entity_overlap_scorer
from sequence_graph.correspondence import DATED_AS, OBSERVED_ON
from sequence_graph.persist import load_graph
from sequence_graph.physical_extents import dated_day_to_sessions
from sequence_graph.physical_pin_shift import production_date_to_session
from sequence_graph.problem_sequence_review import dated_as_review_claims_from_notes
from sequence_graph.resolution_fingerprint_eval import (
    FINGERPRINT_OVERLAP_SCALE,
    TrainFittedTfidfFingerprint,
    fit_fingerprint_on_tier1,
)
from sequence_graph.short_signal import opening_strength
from sequence_graph.sync_gap_align import (
    CHANNEL_SHORT_OPENING,
    MAX_READ_PROJ,
    MAX_REF_PROJ,
    MIN_SIDE,
    _axis_by_inv_sess,
    _enriched_by_date,
    _path_summary,
    _short_unaligned_volgnrs,
    _sorted_flats_for_sessions,
    align_streams,
    build_short_opening_scorer,
    flats_with_aligned_to,
    taken_read_flats,
)

CHANNEL_ENTITY_FINGERPRINT = "entity_fingerprint_dp"


def _chunk_entity_fingerprint_scorer(
    volgnrs: list[str],
    flats: list[str],
    *,
    entity_scorer: Any,
    fingerprint: TrainFittedTfidfFingerprint,
    enr_text: dict[str, str],
    flat_text: dict[str, str],
    scale: float = FINGERPRINT_OVERLAP_SCALE,
) -> Any:
    """One TF-IDF matrix for the chunk + entity lookup (avoids per-cell refit)."""
    fp_mat = scale * fingerprint.similarity_matrix(
        [enr_text.get(v) or "" for v in volgnrs],
        [flat_text.get(f) or "" for f in flats],
    )
    v_index = {v: i for i, v in enumerate(volgnrs)}
    f_index = {f: j for j, f in enumerate(flats)}

    def scorer(volgnr: str, flat_id: str) -> float:
        i, j = v_index[volgnr], f_index[flat_id]
        return float(entity_scorer(volgnr, flat_id)) + float(fp_mat[i, j])

    return scorer
from running_axis.stream import parse_flat_id

OUTPUT_DATASET = "hard_recalibrate_proof"
LITERAL_CHANNEL = "literal_opening"
NORM_RE = re.compile(r"[^a-z0-9\s]+", re.IGNORECASE)
WS_RE = re.compile(r"\s+")
LITERAL_PREFIX = 180
LITERAL_MIN_SCORE = 0.42
CALENDAR_MARGIN_DAYS = 1


def _session_num(session_id: str) -> int | None:
    m = re.search(r"num-(\d+)", session_id or "")
    return int(m.group(1)) if m else None


def _normalize(text: str) -> str:
    t = (text or "").lower()
    t = NORM_RE.sub(" ", t)
    return WS_RE.sub(" ", t).strip()


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _period(date: str) -> pd.Period:
    return pd.Period(str(date), freq="D")


def _shift(date: str, days: int) -> str:
    return str(_period(date) + days)


def pin_status_rows(graph: nx.MultiDiGraph, inventory: str) -> list[dict[str, Any]]:
    """Per-day production vs physical for one inventory (in-scope)."""
    physical = {
        d: [s for s in sess if s.startswith(f"session-{inventory}-")]
        for d, sess in dated_day_to_sessions(graph).items()
        if in_scope(d)
    }
    production = {
        d: s
        for d, s in production_date_to_session(graph).items()
        if in_scope(d) and s.startswith(f"session-{inventory}-")
    }
    dates = sorted(set(physical) | set(production))
    rows: list[dict[str, Any]] = []
    for date in dates:
        phys_list = physical.get(date) or []
        phys = phys_list[0] if len(phys_list) == 1 else None
        prod = production.get(date)
        pn, hn = _session_num(prod or ""), _session_num(phys or "")
        delta = (hn - pn) if pn is not None and hn is not None else None
        rows.append({
            "date": date,
            "production_session": prod,
            "physical_session": phys,
            "physical_sessions": phys_list,
            "pin_delta": delta,
            "disagree": bool(prod and phys and prod != phys),
            "unique_hard": len(phys_list) == 1,
        })
    return rows


def detect_lag_window(
    status: list[dict[str, Any]],
    *,
    delta_set: set[int] | None = None,
    merge_gap_days: int = 7,
) -> dict[str, Any]:
    """Lag window from near-contiguous disagree runs (graph-derived, not notes).

    Builds tight clusters (default gap ≤7d), then unions every cluster that
    intersects August–September (known late-summer regime). Falls back to the
    largest cluster if none touch Aug/Sep.
    """
    delta_set = delta_set or {7, 8, 9}
    lag = [
        r
        for r in status
        if r["disagree"] and r.get("pin_delta") in delta_set
    ]
    if not lag:
        raise SystemExit("no production≠physical lag days with Δ in {7,8,9}")
    dates = [r["date"] for r in lag]
    clusters: list[list[str]] = [[dates[0]]]
    for d in dates[1:]:
        if (_period(d) - _period(clusters[-1][-1])).n <= merge_gap_days:
            clusters[-1].append(d)
        else:
            clusters.append([d])

    def _touches_aug_sep(cluster: list[str]) -> bool:
        return any(x[5:7] in ("08", "09") for x in cluster)

    focus = [c for c in clusters if _touches_aug_sep(c)]
    if focus:
        pick_dates = [d for c in focus for d in c]
    else:
        pick_dates = max(clusters, key=len)
    pick_dates = sorted(pick_dates)
    pick_rows = [r for r in lag if r["date"] in set(pick_dates)]
    hist = Counter(
        int(r["pin_delta"]) for r in pick_rows if r.get("pin_delta") is not None
    )
    return {
        "calendar_lo": pick_dates[0],
        "calendar_hi": pick_dates[-1],
        "n_lag_days": len(pick_rows),
        "median_delta": int(statistics.median([r["pin_delta"] for r in pick_rows])),
        "pin_delta_hist": {str(k): v for k, v in sorted(hist.items())},
        "n_lag_clusters": len(clusters),
        "n_aug_sep_clusters": len(focus),
        "claim_set_dropped": "production_PINNED_TO_as_lid",
        "claim_set_active": "hard_OBSERVED_ON_compose_DATED_AS",
    }


def hard_map_in_window(
    graph: nx.MultiDiGraph,
    inventory: str,
    calendar_lo: str,
    calendar_hi: str,
) -> list[dict[str, Any]]:
    """Unique hard date→session beads inside the window (production ignored)."""
    physical = dated_day_to_sessions(graph)
    production = production_date_to_session(graph)
    rows: list[dict[str, Any]] = []
    for date, sessions in sorted(physical.items()):
        if not (calendar_lo <= date <= calendar_hi) or not in_scope(date):
            continue
        sessions = [s for s in sessions if s.startswith(f"session-{inventory}-")]
        if len(sessions) != 1:
            rows.append({
                "record_type": "hard_map",
                "date": date,
                "session_id": None,
                "unique": False,
                "n_physical": len(sessions),
                "production_session": production.get(date),
                "active": False,
            })
            continue
        sid = sessions[0]
        # scans on path for compare
        scan_nums: list[int] = []
        day = f"day:{date}"
        for u, _v, ed in graph.in_edges(day, data=True):
            if ed.get("kind") != DATED_AS:
                continue
            if graph.nodes[u].get("kind") != "Scan":
                continue
            if graph.nodes[u]["obj"].inventory != inventory:
                continue
            # only if this session observes the scan
            sn = int(graph.nodes[u]["obj"].scan_num)
            sess_node = f"session:{sid}"
            observed = any(
                ed2.get("kind") == OBSERVED_ON and v == u
                for _s, v, ed2 in graph.out_edges(sess_node, data=True)
            )
            if observed:
                scan_nums.append(sn)
        rows.append({
            "record_type": "hard_map",
            "date": date,
            "session_id": sid,
            "session_num": _session_num(sid),
            "unique": True,
            "n_physical": 1,
            "production_session": production.get(date),
            "production_disagrees": production.get(date) not in (None, sid),
            "dated_scans_on_session": sorted(set(scan_nums)),
            "active": True,
        })
    return rows


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


def _enriched_text_by_volgnr() -> dict[str, str]:
    out: dict[str, str] = {}
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if not vid:
            continue
        out[vid] = str(er.get("text") or "")
    return out


def _session_opening_flat(
    session_id: str,
    axis_index: dict[tuple[str, int], list[str]],
    flat_text: dict[str, str],
) -> str | None:
    inv_m = re.search(r"session-(\d+)-num-(\d+)", session_id)
    if not inv_m:
        return None
    inv, num = inv_m.group(1), int(inv_m.group(2))
    flats = axis_index.get((inv, num), [])
    if not flats:
        return None
    # prefer first flat with opening signal; else first flat
    for fid in flats[:5]:
        if opening_strength(flat_text.get(fid) or "") > 0:
            return fid
    return flats[0]


def literal_opening_matches(
    hard_rows: list[dict[str, Any]],
    *,
    calendar_lo: str,
    calendar_hi: str,
    flat_text: dict[str, str],
    enr_text: dict[str, str],
    enr_by_date: dict[str, list[str]],
    axis_index: dict[tuple[str, int], list[str]],
) -> list[dict[str, Any]]:
    """(a) Literal HTR session-opening detection + hard-date seed for DP freeze.

    Modern enriched summaries do not share vocabulary with HTR, so Jaccard to XML
    is not the gate. Literal work is on the HTR side (opening / receipt formulas).
    Each detected opening is seeded to its unique hard-mapped calendar date(s);
    optional weak substring hits to enriched are recorded but not required.
    """
    sess_dates: dict[str, list[str]] = defaultdict(list)
    for r in hard_rows:
        if r.get("active") and r.get("session_id"):
            sess_dates[r["session_id"]].append(r["date"])

    out: list[dict[str, Any]] = []
    for sid, dates in sorted(sess_dates.items()):
        opening = _session_opening_flat(sid, axis_index, flat_text)
        if not opening:
            out.append({
                "record_type": "literal_opening",
                "session_id": sid,
                "opening_flat": None,
                "matched": False,
                "seed_kind": None,
                "channel": LITERAL_CHANNEL,
            })
            continue
        body = flat_text.get(opening) or ""
        strength = opening_strength(body)
        htr_norm = _normalize(body)[:LITERAL_PREFIX]
        # Weak enriched hint: rare HTR tokens (≥6 chars) as substrings on hard dates.
        rare = [t for t in htr_norm.split() if len(t) >= 6][:12]
        weak: list[tuple[int, str, str]] = []
        for d in dates:
            if not (calendar_lo <= d <= calendar_hi):
                continue
            for vid in enr_by_date.get(d, []):
                en = _normalize(enr_text.get(vid) or "")
                hits = sum(1 for t in rare if t in en)
                if hits >= 2:
                    weak.append((hits, vid, d))
        weak.sort(reverse=True)
        weak_vid = weak[0][1] if weak else None
        weak_date = weak[0][2] if weak else None
        # Seed: opening flat + primary hard date (first chronologically).
        primary_date = sorted(dates)[0]
        out.append({
            "record_type": "literal_opening",
            "session_id": sid,
            "opening_flat": opening,
            "opening_strength": strength,
            "matched": True,
            "seed_kind": "htr_opening_on_hard_date",
            "enriched_date": primary_date,
            "volgnr": weak_vid,
            "weak_enriched_hits": weak[0][0] if weak else 0,
            "weak_enriched_date": weak_date,
            "channel": LITERAL_CHANNEL,
            "hard_dates_for_session": dates,
            "snippet": body[:160].replace("\n", " "),
        })
    return out


SESSION_CHUNK = 3  # hard-map session band per DP chunk (keeps k under MAX_*)


def _dp_one_chunk(
    graph: nx.MultiDiGraph,
    *,
    inventory: str,
    seed_lo: str,
    seed_hi: str,
    sess_lo: int,
    sess_hi: int,
    hard_rows: list[dict[str, Any]],
    literal_rows: list[dict[str, Any]],
    enr_by_date: dict[str, list[str]],
    axis_index: dict[tuple[str, int], list[str]],
    flat_text: dict[str, str],
    enriched_by_vid: dict[str, dict[str, Any]],
    entity_scorer: Any,
    fingerprint: TrainFittedTfidfFingerprint,
    enr_text: dict[str, str],
    principles: DpPrinciples,
) -> list[dict[str, Any]]:
    # Editorial stream = hard-mapped dates in this chunk only (±1d), not every
    # intervening calendar day (that explodes k_e under production-style density).
    hard_dates = sorted({
        r["date"]
        for r in hard_rows
        if r.get("active")
        and r.get("session_num") is not None
        and sess_lo <= int(r["session_num"]) <= sess_hi
    })
    date_set: set[str] = set()
    for d in hard_dates:
        for off in range(-1, 2):
            cd = _shift(d, off)
            if in_scope(cd):
                date_set.add(cd)
    volgnrs = []
    for d in sorted(date_set):
        volgnrs.extend(enr_by_date.get(d, []))
    # Exact hard session band (no ± soft margin — HTR density otherwise exceeds MAX_READ).
    soft_sess_lo, soft_sess_hi = sess_lo, sess_hi
    flats = _sorted_flats_for_sessions(inventory, soft_sess_lo, soft_sess_hi, axis_index)
    soft_lo = hard_dates[0] if hard_dates else seed_lo
    soft_hi = hard_dates[-1] if hard_dates else seed_hi
    frozen = set(flats_with_aligned_to(graph))
    for lit in literal_rows:
        if lit.get("matched") and lit.get("opening_flat"):
            frozen.add(lit["opening_flat"])
    flat_strength = {f: opening_strength(flat_text.get(f) or "") for f in flats}
    base: dict[str, Any] = {
        "record_type": "dp_handoff",
        "inventory": inventory,
        "seed_calendar_lo": seed_lo,
        "seed_calendar_hi": seed_hi,
        "soft_calendar_lo": soft_lo,
        "soft_calendar_hi": soft_hi,
        "soft_sess_lo": soft_sess_lo,
        "soft_sess_hi": soft_sess_hi,
        "k_e": len(volgnrs),
        "k_f": len(flats),
        "n_literal_frozen": sum(1 for lit in literal_rows if lit.get("matched")),
        "lids": "hard_map_only",
    }
    rows: list[dict[str, Any]] = []
    if len(volgnrs) < MIN_SIDE or len(flats) < MIN_SIDE:
        rows.append({**base, "status": "skipped_too_small", "dp1_ran": False, "dp2_ran": False})
        return rows
    if len(volgnrs) > MAX_REF_PROJ or len(flats) > MAX_READ_PROJ:
        rows.append({
            **base,
            "status": "dp1_oversize_abstain",
            "dp1_ran": False,
            "dp2_ran": False,
            "claim": "entity_fingerprint_dp_abstain_oversize_no_reseal",
        })
        return rows

    dp1_scorer = _chunk_entity_fingerprint_scorer(
        volgnrs,
        flats,
        entity_scorer=entity_scorer,
        fingerprint=fingerprint,
        enr_text=enr_text,
        flat_text=flat_text,
    )
    dp1, cache1 = align_streams(volgnrs, flats, dp1_scorer)
    frozen = frozen | taken_read_flats(dp1, flats)
    summary1 = _path_summary(dp1, cache1)
    rows.append({
        **base,
        "status": "dp1_ok",
        "dp1_ran": True,
        "aligner": "dp1_entity_fingerprint",
        "evidence_channel": CHANNEL_ENTITY_FINGERPRINT,
        "n_frozen_reads": len(frozen),
        **summary1,
    })

    residue = _short_unaligned_volgnrs(graph, volgnrs, enriched_by_vid)
    free = [f for f in flats if f not in frozen]
    if len(residue) < MIN_SIDE or len(free) < MIN_SIDE:
        rows.append({
            **base,
            "status": "dp2_skipped_too_small",
            "dp2_ran": False,
            "aligner": "dp2_short_opening",
            "n_residue_short": len(residue),
            "n_free_flats": len(free),
        })
        return rows
    if len(residue) > MAX_REF_PROJ or len(free) > MAX_READ_PROJ:
        rows.append({
            **base,
            "status": "dp2_oversize_abstain",
            "dp2_ran": False,
            "aligner": "dp2_short_opening",
            "n_residue_short": len(residue),
            "n_free_flats": len(free),
        })
        return rows

    volgnr_dates = {v: v.split("_")[0] for v in residue if "_" in v}
    flat_dates: dict[str, str] = {}
    for f in free:
        try:
            _inv, snum, _r = parse_flat_id(f)
            sid = f"session-{inventory}-num-{snum}"
            for hr in hard_rows:
                if hr.get("session_id") == sid and hr.get("active"):
                    flat_dates[f] = hr["date"]
                    break
        except Exception:
            continue

    dp2_scorer = build_short_opening_scorer(
        set(residue),
        flat_strength,
        volgnr_dates=volgnr_dates,
        flat_dates=flat_dates,
        principles=principles,
    )
    dp2, cache2 = align_streams(residue, free, dp2_scorer, cost=CostModel())
    summary2 = _path_summary(dp2, cache2)
    rows.append({
        **base,
        "status": "dp2_ok",
        "dp2_ran": True,
        "aligner": "dp2_short_opening",
        "evidence_channel": CHANNEL_SHORT_OPENING,
        "n_residue_short": len(residue),
        "n_free_flats": len(free),
        **summary2,
    })
    return rows


def run_dp_bc(
    graph: nx.MultiDiGraph,
    *,
    inventory: str,
    calendar_lo: str,
    calendar_hi: str,
    hard_rows: list[dict[str, Any]],
    literal_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """(b)/(c) Soft-window DP with hard-map lids; chunk sessions if oversize."""
    active = [r for r in hard_rows if r.get("active")]
    if not active:
        return [{
            "record_type": "dp_handoff",
            "status": "no_hard_lids",
            "dp1_ran": False,
            "dp2_ran": False,
        }]

    # Group active beads by session_num order; chunk for tractability.
    by_sess: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in active:
        by_sess[int(r["session_num"])].append(r)
    sess_order = sorted(by_sess)
    enr_by_date = _enriched_by_date()
    axis_index = _axis_by_inv_sess()
    flat_text = _flat_text_by_id()
    enr_text = _enriched_text_by_volgnr()
    principles = DpPrinciples()
    # Hold out lag-window dates from fingerprint fit so DP1 does not train on the
    # calibration stretch's own tier1 pairs.
    exclude_dates = {
        r["date"] for r in hard_rows if calendar_lo <= r["date"] <= calendar_hi
    }
    fingerprint, fp_meta = fit_fingerprint_on_tier1(exclude_dates=exclude_dates)
    entity_scorer = build_entity_overlap_scorer()
    enriched_by_vid: dict[str, dict[str, Any]] = {}
    for er in load("enriched_resolutions_1626_1630"):
        vid = enriched_volgnr(er)
        if vid:
            enriched_by_vid[vid] = er

    rows: list[dict[str, Any]] = [
        {
            "record_type": "fingerprint_fit",
            "exclude_calendar_lo": calendar_lo,
            "exclude_calendar_hi": calendar_hi,
            **fp_meta,
        }
    ]
    for i in range(0, len(sess_order), SESSION_CHUNK):
        chunk_nums = sess_order[i : i + SESSION_CHUNK]
        beads = [b for n in chunk_nums for b in by_sess[n]]
        seed_lo = min(b["date"] for b in beads)
        seed_hi = max(b["date"] for b in beads)
        # keep chunk inside caller window
        seed_lo = max(seed_lo, calendar_lo)
        seed_hi = min(seed_hi, calendar_hi)
        if seed_lo > seed_hi:
            continue
        chunk_rows = _dp_one_chunk(
            graph,
            inventory=inventory,
            seed_lo=seed_lo,
            seed_hi=seed_hi,
            sess_lo=min(chunk_nums),
            sess_hi=max(chunk_nums),
            hard_rows=hard_rows,
            literal_rows=literal_rows,
            enr_by_date=enr_by_date,
            axis_index=axis_index,
            flat_text=flat_text,
            enriched_by_vid=enriched_by_vid,
            entity_scorer=entity_scorer,
            fingerprint=fingerprint,
            enr_text=enr_text,
            principles=principles,
        )
        for r in chunk_rows:
            r["chunk_sess_lo"] = min(chunk_nums)
            r["chunk_sess_hi"] = max(chunk_nums)
        rows.extend(chunk_rows)
    return rows


def compare_to_notes(
    hard_rows: list[dict[str, Any]],
    literal_rows: list[dict[str, Any]],
    inventory: str,
) -> dict[str, Any]:
    """Held-out score: review date↔scan beads vs hard map (not used as input)."""
    claims = [
        c
        for c in dated_as_review_claims_from_notes()
        if c.get("inventory") == inventory
    ]
    hard_by_date = {
        r["date"]: r for r in hard_rows if r.get("active")
    }
    hit = 0
    detail: list[dict[str, Any]] = []
    for c in claims:
        date = c["date"]
        scan = int(c["scan_num"])
        hr = hard_by_date.get(date)
        on_hard = bool(hr and scan in (hr.get("dated_scans_on_session") or []))
        # also: scan on hard session OBSERVED_ON even if not the DATED_AS scan
        if hr and not on_hard:
            # dated_scans_on_session already filters OBSERVED_ON∩DATED_AS
            pass
        if on_hard:
            hit += 1
        lit = next(
            (
                L
                for L in literal_rows
                if L.get("matched")
                and date in (L.get("hard_dates_for_session") or [])
            ),
            None,
        )
        detail.append({
            "date": date,
            "review_scan": scan,
            "hard_session": (hr or {}).get("session_id"),
            "review_scan_on_hard_dated_path": on_hard,
            "literal_opening_seed_on_hard_date": bool(lit),
            "literal_opening_flat": (lit or {}).get("opening_flat"),
            "weak_enriched_volgnr": (lit or {}).get("volgnr"),
        })
    return {
        "record_type": "compare_notes",
        "held_out": True,
        "n_review_claims": len(claims),
        "n_hard_path_hit": hit,
        "hard_path_hit_rate": round(hit / len(claims), 4) if claims else None,
        "detail": detail,
    }


def run(
    *,
    inventory: str = "3185",
    calendar_lo: str | None = None,
    calendar_hi: str | None = None,
    compare_notes: bool = False,
) -> list[dict[str, Any]]:
    graph = load_graph()
    status = pin_status_rows(graph, inventory)
    window = detect_lag_window(status)
    lo = calendar_lo or window["calendar_lo"]
    hi = calendar_hi or window["calendar_hi"]

    hard_rows = hard_map_in_window(graph, inventory, lo, hi)
    n_active = sum(1 for r in hard_rows if r.get("active"))
    n_shift = sum(1 for r in hard_rows if r.get("production_disagrees"))

    flat_text = _flat_text_by_id()
    enr_text = _enriched_text_by_volgnr()
    enr_by_date = _enriched_by_date()
    axis_index = _axis_by_inv_sess()
    literal_rows = literal_opening_matches(
        hard_rows,
        calendar_lo=lo,
        calendar_hi=hi,
        flat_text=flat_text,
        enr_text=enr_text,
        enr_by_date=enr_by_date,
        axis_index=axis_index,
    )
    n_lit = sum(1 for r in literal_rows if r.get("matched"))

    dp_rows = run_dp_bc(
        graph,
        inventory=inventory,
        calendar_lo=lo,
        calendar_hi=hi,
        hard_rows=hard_rows,
        literal_rows=literal_rows,
    )

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "inventory": inventory,
            "calendar_lo": lo,
            "calendar_hi": hi,
            "detected_lag_lo": window["calendar_lo"],
            "detected_lag_hi": window["calendar_hi"],
            "n_lag_days": window["n_lag_days"],
            "median_delta": window["median_delta"],
            "pin_delta_hist": window["pin_delta_hist"],
            "n_lag_clusters": window.get("n_lag_clusters"),
            "n_aug_sep_clusters": window.get("n_aug_sep_clusters"),
            "claim_set_dropped": window["claim_set_dropped"],
            "claim_set_active": window["claim_set_active"],
            "n_hard_active": n_active,
            "n_hard_vs_production_shift": n_shift,
            "n_literal_matched": n_lit,
            "n_literal_tried": len(literal_rows),
            "dp1_channel": CHANNEL_ENTITY_FINGERPRINT,
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "notes_as_input": False,
            "policy": (
                "Hard recalibration a→b→c. Production PINNED_TO ignored as lids. "
                "Active map = unique OBSERVED_ON∘DATED_AS. DP1 = entity + TF-IDF "
                "fingerprint fitted on tier1 excluding lag window. Hand notes held "
                "out unless compare_notes. No production wire."
            ),
            **scope_meta(),
        }
    ]
    rows.extend(hard_rows)
    rows.extend(literal_rows)
    rows.extend(dp_rows)
    if compare_notes:
        rows.append(compare_to_notes(hard_rows, literal_rows, inventory))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default="3185")
    parser.add_argument("--calendar-lo", default=None)
    parser.add_argument("--calendar-hi", default=None)
    parser.add_argument(
        "--compare-notes",
        action="store_true",
        help="held-out score vs dated_as_review notes (not used as lids/seeds)",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rows = run(
        inventory=args.inventory,
        calendar_lo=args.calendar_lo,
        calendar_hi=args.calendar_hi,
        compare_notes=args.compare_notes,
    )
    meta = next(r for r in rows if r["record_type"] == "meta")
    print(
        f"window {meta['inventory']} {meta['calendar_lo']}..{meta['calendar_hi']}  "
        f"lag_days={meta['n_lag_days']} median_Δ={meta['median_delta']}  "
        f"hard_active={meta['n_hard_active']} shifts_vs_prod={meta['n_hard_vs_production_shift']}  "
        f"literal={meta['n_literal_matched']}/{meta['n_literal_tried']}"
    )
    for r in rows:
        if r["record_type"] == "dp_handoff":
            print(
                f"  DP {r.get('status')}  k_e={r.get('k_e')} k_f={r.get('k_f')}  "
                f"MATCH={r.get('n_match')} entity={r.get('n_match_with_entity')}  "
                f"channel={r.get('evidence_channel')}"
            )
        if r["record_type"] == "compare_notes":
            print(
                f"  COMPARE held-out review: "
                f"{r['n_hard_path_hit']}/{r['n_review_claims']} "
                f"hard-path hit (rate={r['hard_path_hit_rate']})"
            )
            for d in r.get("detail") or []:
                print(
                    f"    {d['date']} scan {d['review_scan']}  "
                    f"on_hard={d['review_scan_on_hard_dated_path']}  "
                    f"opening_seed={d['literal_opening_seed_on_hard_date']}  "
                    f"flat={d.get('literal_opening_flat')}"
                )
    if args.write:
        save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=(
                "Hard-evidence recalibration proof: lag window from pin split; "
                "active lids = unique OBSERVED_ON∘DATED_AS; literal_opening seeds; "
                "DP1 entity+fingerprint (fit excluding window); DP2 short/opening; "
                "optional held-out note compare. No production wire."
            ),
            parent_sources=[
                "sequence_graph_edges",
                "paragraph_axis_1626_1630",
                "alignment_1626_1630",
            ],
        )
        print(f"wrote {OUTPUT_DATASET}")


if __name__ == "__main__":
    main()

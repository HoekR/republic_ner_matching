"""Gold / silver / projection proof for bracket-level editorial↔HTR sequence alignment.

**User, 2026-10-09:** entity comparison *is* sequence comparison. Broad sync gaps are the
work regions. Prove the mechanism on a few samples — preferably random. Perfection is not
the point; an ordered path with MATCH cells that carry entity evidence is.

Three tiers (same DP, different claims):

* **Gold** — random days from `boundary_gold_sample`. Score exact paragraph agreement against
  hand annotation. Reports a number; does not gate on high accuracy.
* **Silver** — random in-scope main-series days with production `PINNED_TO` and legacy
  concordance `ALIGNED_TO` but no gold edge. Ask only whether the DP's MATCH for each silver
  ref lands on the same HTR flat the production pipeline already placed.
* **Projection** — random broad sync-gap brackets (`sequence_graph.sync_gaps`). Build the full
  editorial stream (calendar order) and HTR stream (session-num order, main series only) inside
  the bracket; run `align_bracket`; report path shape. No accuracy claim.

**Trusted brackets — two DPs with soft-window hand-off** (user, 2026-10-09/11): date-trust
geometries are **seeds**, not sealed lids. Soft margins expand editorial/HTR streams past pin
walls; locality is cost (rescaled opening + optional day decay), not membership. DP₁ = entity
overlap; DP₂ = short/opening on residue. Freeze = DP₁ taken ∪ graph ``ALIGNED_TO`` reads.
Same ``align_bracket`` primitive, distinct ``evidence.channel``. No production ``PINNED_TO``.

4562/4861 out (`is_main_series`). Scope bar applied at data entry.

Usage:
    uv run python -m sequence_graph.sync_gap_align --prove
    uv run python -m sequence_graph.sync_gap_align --prove --seed 42 --n-gold 3 --n-silver 3 --n-proj 3
    uv run python -m sequence_graph.sync_gap_align --prove --write --push-graph
    uv run python -m sequence_graph.sync_gap_align --trusted-brackets --write --push-graph
"""

from __future__ import annotations

import argparse
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable

import networkx as nx
import pandas as pd

from build_alignment_new import enriched_volgnr
from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from sequence_graph.align import (
    DELETION_GAP,
    INSERTION_SPLIT,
    MATCH,
    CostModel,
    AlignmentResult,
    DpPrinciples,
    align_bracket,
    build_entity_overlap_scorer,
    run_bracket,
)
from sequence_graph.consolidate import node_aligned_bucket
from sequence_graph.correspondence import ALIGNED_TO, Evidence
from sequence_graph.nodes import EnrichedResolution, HtrResolution
from sequence_graph.persist import load_graph, save_loaded_graph
from sequence_graph.short_signal import classify_enriched, opening_strength
from sequence_graph.sync_gaps import build_broad_gaps
from running_axis.stream import parse_flat_id

OUTPUT_DATASET = "sequence_graph_sync_gap_align_proof"
TRUSTED_BRACKET_DATASET = "session_anchor_shift_bracket_align"
DATE_TRUST_DATASET = "session_anchor_shift_date_trust"
# DP tractability for projection brackets (not a quality gate).
MAX_REF_PROJ = 80
MAX_READ_PROJ = 80
MIN_SIDE = 2

CHANNEL_ENTITY = "entity_dp"
CHANNEL_SHORT_OPENING = "short_opening_dp"

# Soft locality: seeds expand past pin lids (not membership walls).
SOFT_MARGIN_DAYS = 3
SOFT_MARGIN_SESSIONS = 2
# DP₂ overlap in entity-like units so MATCH beats gap_cost=1 under CostModel.
OPEN_ONLY_OVERLAP = 2.0
OPEN_CLOSE_OVERLAP = 3.0


@dataclass(frozen=True)
class PathBatch:
    """One align_bracket result to plow back as ALIGNED_TO:solver edges after the run."""

    tier: str
    volgnrs: tuple[str, ...]
    flat_ids: tuple[str, ...]
    result: AlignmentResult
    detail: dict[str, Any]


def _volgnr(date: str, index: int) -> str:
    return f"{date}_{index}"


def _parse_volgnr(volgnr: str) -> tuple[str, int] | None:
    if len(volgnr) < 12 or volgnr[10] != "_":
        return None
    date, _, idx = volgnr.partition("_")
    if len(date) != 10:
        return None
    try:
        return date, int(idx)
    except ValueError:
        return None


def push_batches_to_graph(graph: nx.MultiDiGraph, batches: list[PathBatch]) -> int:
    """Write MATCH / INSERTION_SPLIT cells as observed=False ALIGNED_TO:solver edges.

    Same non-circularity rule as `add_aligned_to_solver`: these are derived, never gold.
    Key stays `ALIGNED_TO:solver` so `aligned_to_status` counts them as solver_derived.
    Channel comes from ``batch.detail["evidence_channel"]`` (entity_dp / short_opening_dp)
    so the two hand-off aligners stay distinguishable in provenance.
    """
    added = 0
    for batch in batches:
        if batch.result.abstained:
            continue
        channel = str(batch.detail.get("evidence_channel") or "dp_solver")
        for pair in batch.result.pairs:
            if pair.kind not in (MATCH, INSERTION_SPLIT):
                continue
            if pair.ref_index is None or pair.read_index is None:
                continue
            parsed = _parse_volgnr(batch.volgnrs[pair.ref_index])
            if parsed is None:
                continue
            date, index = parsed
            flat_id = batch.flat_ids[pair.read_index]
            if not is_main_series(flat_id):
                continue
            enriched_node = EnrichedResolution(date=date, index=index).node_id
            htr_node = HtrResolution.from_flat_id(flat_id).node_id
            if enriched_node not in graph or htr_node not in graph:
                continue
            graph.add_edge(
                enriched_node,
                htr_node,
                key=f"{ALIGNED_TO}:solver",
                kind=ALIGNED_TO,
                evidence=Evidence(
                    channel=channel,
                    source="sequence_graph.sync_gap_align",
                    observed=False,
                    confidence=None,
                    detail={
                        "move_kind": pair.kind,
                        "step_cost": pair.cost,
                        "cost_model_fitted": False,
                        "total_path_cost": batch.result.total_cost,
                        "tier": batch.tier,
                        **{k: v for k, v in batch.detail.items() if k != "evidence_channel"},
                    },
                ),
            )
            added += 1
    return added


def taken_read_flats(result: AlignmentResult, flats: list[str]) -> set[str]:
    """HTR flats consumed by DP₁ MATCH / INSERTION_SPLIT — frozen for DP₂."""
    taken: set[str] = set()
    for pair in result.pairs:
        if pair.read_index is None:
            continue
        if pair.kind not in (MATCH, INSERTION_SPLIT):
            continue
        if 0 <= pair.read_index < len(flats):
            taken.add(flats[pair.read_index])
    return taken


def rescale_opening_overlap(strength: float) -> float:
    """Map detection strength {0, 0.5, 1.0} → entity-like overlap for CostModel."""
    if strength >= 1.0:
        return OPEN_CLOSE_OVERLAP
    if strength >= 0.5:
        return OPEN_ONLY_OVERLAP
    return 0.0


def build_short_opening_scorer(
    short_volgnrs: set[str],
    flat_strength: dict[str, float],
    *,
    volgnr_dates: dict[str, str] | None = None,
    flat_dates: dict[str, str] | None = None,
    principles: DpPrinciples | None = None,
) -> Callable[[str, str], float]:
    """DP₂ overlap: short enriched × rescaled opening strength (+ optional day decay)."""
    principles = principles or DpPrinciples()
    volgnr_dates = volgnr_dates or {}
    flat_dates = flat_dates or {}

    def scorer(volgnr: str, flat_id: str) -> float:
        if volgnr not in short_volgnrs:
            return 0.0
        ov = rescale_opening_overlap(float(flat_strength.get(flat_id, 0.0)))
        if ov <= 0:
            return 0.0
        d_ref = volgnr_dates.get(volgnr)
        d_read = flat_dates.get(flat_id)
        if d_ref and d_read and len(d_ref) >= 10 and len(d_read) >= 10:
            try:
                delta = abs(
                    (pd.Period(d_ref[:10], freq="D") - pd.Period(d_read[:10], freq="D")).n
                )
            except ValueError:
                delta = 0
            ov *= principles.containment_plausibility(delta)
        return float(ov)

    return scorer


def soft_calendar_span(lo: str, hi: str, *, margin_days: int = SOFT_MARGIN_DAYS) -> tuple[str, str]:
    """Expand ISO day span by margin; scope bar still applied when streaming enriched."""
    lo_p = pd.Period(str(lo)[:10], freq="D") - int(margin_days)
    hi_p = pd.Period(str(hi)[:10], freq="D") + int(margin_days)
    return str(lo_p), str(hi_p)


def soft_session_span(
    sess_lo: int, sess_hi: int, *, margin: int = SOFT_MARGIN_SESSIONS
) -> tuple[int, int]:
    """Expand session-num band; floor at 0 (ids are non-negative)."""
    return max(0, int(sess_lo) - int(margin)), int(sess_hi) + int(margin)


def flats_with_aligned_to(graph: nx.MultiDiGraph) -> set[str]:
    """HTR flat_ids that already carry any ALIGNED_TO (legacy/gold/solver)."""
    taken: set[str] = set()
    for _u, v, ed in graph.edges(data=True):
        if ed.get("kind") != ALIGNED_TO:
            continue
        if graph.nodes[v].get("kind") != "HtrResolution":
            continue
        taken.add(graph.nodes[v]["obj"].flat_id)
    return taken


def _axis_by_inv_sess() -> dict[tuple[str, int], list[str]]:
    """Cache paragraph_axis once: (inventory, session_num) → ordered distinct flats."""
    by: dict[tuple[str, int], list[tuple[int, str]]] = defaultdict(list)
    seen: set[str] = set()
    for row in load("paragraph_axis_1626_1630"):
        flat = str(row["flat_id"])
        if not is_main_series(flat) or flat in seen:
            continue
        seen.add(flat)
        inv, sess, res = parse_flat_id(flat)
        by[(inv, sess)].append((res, flat))
    return {
        key: [f for _r, f in sorted(pairs)]
        for key, pairs in by.items()
    }


def _sorted_flats_for_sessions(
    inventory: str,
    lo_num: int,
    hi_num: int,
    axis_index: dict[tuple[str, int], list[str]] | None = None,
) -> list[str]:
    """Distinct HTR flat_ids in inclusive session-num range, main series, stream order."""
    index = axis_index if axis_index is not None else _axis_by_inv_sess()
    out: list[str] = []
    for num in range(lo_num, hi_num + 1):
        out.extend(index.get((inventory, num), []))
    return out


def _enriched_by_date() -> dict[str, list[str]]:
    """Cache enriched once: date → volgnrs in resolution_index order."""
    by_date: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if not vid:
            continue
        idx = int(er.get("resolution_index") or 0)
        by_date[date].append((idx, vid))
    return {d: [v for _i, v in sorted(pairs)] for d, pairs in by_date.items()}


def _editorial_stream(
    lo_date: str,
    hi_date: str,
    enr_by_date: dict[str, list[str]] | None = None,
) -> list[str]:
    """volgnrs for enriched resolutions with lo_date <= date <= hi_date, in scope."""
    by = enr_by_date if enr_by_date is not None else _enriched_by_date()
    out: list[str] = []
    for date in sorted(d for d in by if lo_date <= d <= hi_date):
        out.extend(by[date])
    return out


def _n_unaligned(graph: nx.MultiDiGraph, volgnrs: list[str]) -> int:
    n = 0
    for vid in volgnrs:
        parsed = _parse_volgnr(vid)
        if parsed is None:
            continue
        date, index = parsed
        node_id = EnrichedResolution(date=date, index=index).node_id
        if node_id not in graph:
            continue
        if node_aligned_bucket(graph, node_id) == "unaligned":
            n += 1
    return n


def _session_num(session_id: str) -> int:
    m = re.search(r"num-(\d+)", session_id)
    if not m:
        raise ValueError(session_id)
    return int(m.group(1))


def align_streams(
    volgnrs: list[str],
    flat_ids: list[str],
    scorer: Callable[[str, str], float],
    cost: CostModel | None = None,
) -> tuple[AlignmentResult, dict[tuple[int, int], float]]:
    """Run `align_bracket` on two ordered streams; return result + overlap cache."""
    cost = cost or CostModel()
    cache: dict[tuple[int, int], float] = {}

    def overlap(i: int, j: int) -> float:
        key = (i, j)
        if key not in cache:
            cache[key] = float(scorer(volgnrs[i], flat_ids[j]))
        return cache[key]

    return align_bracket(len(volgnrs), len(flat_ids), overlap, cost), cache


def _path_summary(
    result: AlignmentResult,
    cache: dict[tuple[int, int], float],
) -> dict[str, Any]:
    kinds = Counter(p.kind for p in result.pairs)
    matches = [p for p in result.pairs if p.kind == MATCH]
    evidenced = sum(
        1
        for p in matches
        if p.ref_index is not None
        and p.read_index is not None
        and cache.get((p.ref_index, p.read_index), 0.0) > 0
    )
    return {
        "abstained": result.abstained,
        "total_cost": round(result.total_cost, 3),
        "n_match": kinds.get(MATCH, 0),
        "n_match_with_entity": evidenced,
        "n_deletion": kinds.get(DELETION_GAP, 0),
        "move_counts": dict(kinds),
        "n_leading_free": result.n_leading_free,
        "n_trailing_free": result.n_trailing_free,
    }


def prove_gold(
    rng: random.Random, n: int, scorer: Callable[[str, str], float]
) -> tuple[list[dict], list[PathBatch]]:
    """Random gold days: run existing `run_bracket`, record exact agreement (not a gate)."""
    gold = load("boundary_gold_sample")
    days = [
        d
        for d in gold["days"]
        if in_scope(str(d["date"])[:10])
        and all(is_main_series(f) for f in (d.get("flat_ids") or []))
        and int(d.get("k_e") or 0) >= MIN_SIDE
        and int(d.get("k_f") or 0) >= MIN_SIDE
    ]
    sample = rng.sample(days, min(n, len(days)))
    rows: list[dict] = []
    batches: list[PathBatch] = []
    for day in sample:
        date = str(day["date"])[:10]
        report = run_bracket(date)
        flat_ids = list(report["flat_ids"])
        volgnrs = [_volgnr(date, i) for i in range(report["k_e"])]
        # Rebuild AlignmentResult-shaped batch via align_streams so push uses real pairs.
        result, _cache = align_streams(volgnrs, flat_ids, scorer)
        batches.append(
            PathBatch(
                tier="gold",
                volgnrs=tuple(volgnrs),
                flat_ids=tuple(flat_ids),
                result=result,
                detail={"date": date},
            )
        )
        rows.append({
            "record_type": "gold",
            "date": date,
            "k_e": report["k_e"],
            "k_f": report["k_f"],
            "abstained": report["abstained"],
            "total_cost": round(float(report["total_cost"]), 3),
            "exact_agreement": report["exact_agreement"],
            "exact_agreement_n": report["exact_agreement_n"],
            "n_match": sum(1 for k, _, _ in report["moves"] if k == MATCH),
            "claim": "exact_agreement_vs_hand_annotation",
        })
    return rows, batches


def _silver_candidates(graph) -> list[dict[str, Any]]:
    """Days with production pin + at least one legacy ALIGNED_TO, no gold ALIGNED_TO on that day."""
    from sequence_graph.correspondence import ALIGNED_TO, PINNED_TO

    gold_dates: set[str] = set()
    legacy_by_date: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for u, v, key, ed in graph.edges(keys=True, data=True):
        if ed.get("kind") != ALIGNED_TO:
            continue
        ev = ed.get("evidence")
        if ev is None:
            continue
        date = graph.nodes[u]["obj"].date
        if not in_scope(date):
            continue
        flat = graph.nodes[v]["obj"].flat_id
        if not is_main_series(flat):
            continue
        if getattr(ev, "observed", False):
            gold_dates.add(date)
            continue
        if getattr(ev, "channel", None) == "legacy_concordance" or (
            isinstance(key, str) and key.endswith(":legacy")
        ):
            vid = _volgnr(date, graph.nodes[u]["obj"].index)
            legacy_by_date[date].append((vid, flat))

    pinned_dates: set[str] = set()
    for node_id, data in graph.nodes(data=True):
        if data.get("kind") != "SittingDay":
            continue
        date = data["obj"].date
        if not in_scope(date) or date in gold_dates:
            continue
        for _u, v, ed in graph.out_edges(node_id, data=True):
            if ed.get("kind") != PINNED_TO:
                continue
            if graph.nodes[v].get("kind") == "Session" and is_main_series(
                graph.nodes[v]["obj"].session_id
            ):
                pinned_dates.add(date)
                break

    out: list[dict[str, Any]] = []
    for date in sorted(pinned_dates & set(legacy_by_date)):
        pairs = legacy_by_date[date]
        if len(pairs) < MIN_SIDE:
            continue
        flats = sorted({f for _v, f in pairs}, key=lambda fid: parse_flat_id(fid))
        volgnrs = sorted({v for v, _f in pairs})
        # keep only pairs that sit on the day's stream
        out.append({
            "date": date,
            "pairs": pairs,
            "volgnrs": volgnrs,
            "flat_ids": flats,
        })
    return out


def prove_silver(
    rng: random.Random, n: int, scorer: Callable[[str, str], float], graph
) -> tuple[list[dict], list[PathBatch]]:
    cands = _silver_candidates(graph)
    if not cands:
        return [{"record_type": "silver", "error": "no_silver_candidates"}], []
    sample = rng.sample(cands, min(n, len(cands)))
    rows: list[dict] = []
    batches: list[PathBatch] = []
    for cand in sample:
        date = cand["date"]
        # Full day streams from enriched + axis (not only silver pairs), then score recovery.
        volgnrs = _editorial_stream(date, date)
        flats: list[str] = []
        seen: set[str] = set()
        for row in load("paragraph_axis_1626_1630"):
            if str(row.get("date") or "")[:10] != date:
                continue
            flat = str(row["flat_id"])
            if not is_main_series(flat) or flat in seen:
                continue
            seen.add(flat)
            flats.append(flat)
        flats.sort(key=lambda fid: parse_flat_id(fid))
        if len(volgnrs) < MIN_SIDE or len(flats) < MIN_SIDE:
            continue
        if len(volgnrs) > MAX_REF_PROJ or len(flats) > MAX_READ_PROJ:
            continue
        result, cache = align_streams(volgnrs, flats, scorer)
        batches.append(
            PathBatch(
                tier="silver",
                volgnrs=tuple(volgnrs),
                flat_ids=tuple(flats),
                result=result,
                detail={"date": date},
            )
        )
        silver_map = {v: f for v, f in cand["pairs"]}
        recovered = 0
        checked = 0
        for p in result.pairs:
            if p.kind != MATCH or p.ref_index is None or p.read_index is None:
                continue
            vid = volgnrs[p.ref_index]
            if vid not in silver_map:
                continue
            checked += 1
            if flats[p.read_index] == silver_map[vid]:
                recovered += 1
        summary = _path_summary(result, cache)
        rows.append({
            "record_type": "silver",
            "date": date,
            "k_e": len(volgnrs),
            "k_f": len(flats),
            "silver_pairs_checked": checked,
            "silver_pairs_recovered": recovered,
            "silver_recovery_rate": (
                round(recovered / checked, 3) if checked else None
            ),
            "claim": "match_recovers_legacy_concordance_flat",
            **summary,
        })
    return rows, batches


def _unaligned_volgnrs(graph: nx.MultiDiGraph, volgnrs: list[str]) -> list[str]:
    out: list[str] = []
    for vid in volgnrs:
        parsed = _parse_volgnr(vid)
        if parsed is None:
            continue
        date, index = parsed
        node_id = EnrichedResolution(date=date, index=index).node_id
        if node_id not in graph:
            continue
        if node_aligned_bucket(graph, node_id) == "unaligned":
            out.append(vid)
    return out


def prove_projection(
    rng: random.Random,
    n: int,
    scorer: Callable[[str, str], float],
    graph,
    *,
    open_mass: bool = False,
    unaligned_refs_only: bool = False,
) -> tuple[list[dict], list[PathBatch]]:
    """Sample sync-gap brackets.

    * ``open_mass`` — keep brackets with unsynced meetings and ≥1 unaligned enriched.
    * ``unaligned_refs_only`` — editorial stream = currently unaligned volgnrs only (HTR
      stream unchanged). Forces MATCH endpoints onto the open mass so coverage can move.
    """
    gaps = build_broad_gaps(graph)
    print("  indexing axis + enriched (once)…")
    axis_index = _axis_by_inv_sess()
    enr_by_date = _enriched_by_date()
    eligible: list[dict] = []
    skipped_open = 0
    for gap in gaps:
        lo_n = _session_num(gap["anchor_lo_session"])
        hi_n = _session_num(gap["anchor_hi_session"])
        volgnrs = _editorial_stream(
            gap["calendar_lo"], gap["calendar_hi"], enr_by_date=enr_by_date
        )
        flats = _sorted_flats_for_sessions(
            gap["inventory"], lo_n, hi_n, axis_index=axis_index
        )
        n_unaligned = _n_unaligned(graph, volgnrs)
        if open_mass:
            if int(gap.get("n_meetings_no_production_pin_in_span") or 0) < 1:
                skipped_open += 1
                continue
            if n_unaligned < 1:
                skipped_open += 1
                continue
        if unaligned_refs_only:
            volgnrs = _unaligned_volgnrs(graph, volgnrs)
        if len(volgnrs) < MIN_SIDE or len(flats) < MIN_SIDE:
            continue
        if len(volgnrs) > MAX_REF_PROJ or len(flats) > MAX_READ_PROJ:
            continue
        eligible.append({
            **gap,
            "_volgnrs": volgnrs,
            "_flats": flats,
            "_n_unaligned": n_unaligned if not unaligned_refs_only else len(volgnrs),
        })
    print(
        f"  eligible brackets={len(eligible)}"
        + (f" (open-mass filter dropped {skipped_open})" if open_mass else "")
        + (" [unaligned-refs-only]" if unaligned_refs_only else "")
    )
    if not eligible:
        return [{"record_type": "projection", "error": "no_eligible_brackets"}], []
    sample = rng.sample(eligible, min(n, len(eligible)))
    rows: list[dict] = []
    batches: list[PathBatch] = []
    for gap in sample:
        volgnrs = gap["_volgnrs"]
        flats = gap["_flats"]
        result, cache = align_streams(volgnrs, flats, scorer)
        batches.append(
            PathBatch(
                tier="projection",
                volgnrs=tuple(volgnrs),
                flat_ids=tuple(flats),
                result=result,
                detail={
                    "inventory": gap["inventory"],
                    "calendar_lo": gap["calendar_lo"],
                    "calendar_hi": gap["calendar_hi"],
                    "anchor_lo_session": gap["anchor_lo_session"],
                    "anchor_hi_session": gap["anchor_hi_session"],
                    "open_mass": open_mass,
                    "unaligned_refs_only": unaligned_refs_only,
                    "n_unaligned_in_stream": gap["_n_unaligned"],
                },
            )
        )
        summary = _path_summary(result, cache)
        crumbs = []
        for p in result.pairs:
            if p.kind != MATCH or p.ref_index is None or p.read_index is None:
                continue
            ov = cache.get((p.ref_index, p.read_index), 0.0)
            if ov <= 0:
                continue
            crumbs.append({
                "volgnr": volgnrs[p.ref_index],
                "flat_id": flats[p.read_index],
                "overlap": round(ov, 3),
            })
            if len(crumbs) >= 3:
                break
        rows.append({
            "record_type": "projection",
            "inventory": gap["inventory"],
            "calendar_lo": gap["calendar_lo"],
            "calendar_hi": gap["calendar_hi"],
            "anchor_lo_session": gap["anchor_lo_session"],
            "anchor_hi_session": gap["anchor_hi_session"],
            "k_e": len(volgnrs),
            "k_f": len(flats),
            "n_unaligned_in_stream": gap["_n_unaligned"],
            "n_meetings_no_production_pin_in_span": gap.get(
                "n_meetings_no_production_pin_in_span"
            ),
            "open_mass": open_mass,
            "unaligned_refs_only": unaligned_refs_only,
            "claim": "ordered_path_only_no_accuracy",
            "example_evidenced_matches": crumbs,
            **summary,
        })
    return rows, batches


def _flat_text_and_dates() -> tuple[dict[str, str], dict[str, str]]:
    """flat_id → (concatenated text, earliest in-scope date label on axis)."""
    parts: dict[str, list[tuple[int, str]]] = defaultdict(list)
    dates: dict[str, str] = {}
    for row in load("paragraph_axis_1626_1630"):
        flat = str(row.get("flat_id") or "")
        if not flat or not is_main_series(flat):
            continue
        try:
            pi = int(row.get("para_index") or 0)
        except (TypeError, ValueError):
            pi = 0
        parts[flat].append((pi, str(row.get("text") or "")))
        date = str(row.get("date") or "")[:10]
        if date and in_scope(date):
            prev = dates.get(flat)
            if prev is None or date < prev:
                dates[flat] = date
    text = {
        fid: " ".join(t for _pi, t in sorted(chunks))
        for fid, chunks in parts.items()
    }
    return text, dates


def _opening_hits(flats: list[str], flat_text: dict[str, str]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for fid in flats:
        text = flat_text.get(fid) or ""
        strength = opening_strength(text)
        if strength <= 0:
            continue
        hits.append({
            "flat_id": fid,
            "strength": strength,
            "snippet": text[:120].replace("\n", " "),
        })
    return hits


def _enriched_by_volgnr() -> dict[str, dict[str, Any]]:
    """volgnr → enriched record (for short / no-decision classification)."""
    out: dict[str, dict[str, Any]] = {}
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if vid:
            out[vid] = er
    return out


def _short_unaligned_volgnrs(
    graph: nx.MultiDiGraph,
    volgnrs: list[str],
    enriched_by_vid: dict[str, dict[str, Any]],
) -> list[str]:
    """Unaligned editorial refs that classify as short / no-decision (DP₂ residue)."""
    out: list[str] = []
    for vid in _unaligned_volgnrs(graph, volgnrs):
        er = enriched_by_vid.get(vid)
        if er is None:
            continue
        if classify_enriched(er):
            out.append(vid)
    return out


def load_trusted_bracket_rows() -> list[dict[str, Any]]:
    """New-bracket geometries from date-trust inventory (text_inside rows)."""
    return [
        r
        for r in load(DATE_TRUST_DATASET)
        if r.get("record_type") == "text_inside"
    ]


def align_trusted_brackets(
    *,
    push_graph: bool = False,
) -> tuple[list[dict[str, Any]], list[PathBatch], nx.MultiDiGraph]:
    """Two DPs with soft-window hand-off; date-trust rows are seeds, not lids.

    Soft margins expand calendar/session spans past pin walls. DP₁ entity on the soft
    editorial×HTR streams; DP₂ short/opening on residue. Freeze = DP₁ taken ∪ any
    graph ``ALIGNED_TO`` read. Oversize after margin → abstain (do not re-seal).
    """
    print("Loading entity-overlap scorer (once)…")
    entity_scorer = build_entity_overlap_scorer()
    print("Loading saved graph…")
    graph = load_graph()
    seeds = load_trusted_bracket_rows()
    print(f"Trusted seeds (report keys): {len(seeds)}")
    print("Indexing axis + enriched + flat text (once)…")
    axis_index = _axis_by_inv_sess()
    enr_by_date = _enriched_by_date()
    enriched_by_vid = _enriched_by_volgnr()
    flat_text, flat_dates = _flat_text_and_dates()
    graph_aligned_flats = flats_with_aligned_to(graph)
    principles = DpPrinciples()
    volgnr_dates = {
        vid: str(er.get("date") or "")[:10]
        for vid, er in enriched_by_vid.items()
    }

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "channel": "entity_dp_then_short_opening_dp_soft_window",
            "parent": DATE_TRUST_DATASET,
            "max_ref": MAX_REF_PROJ,
            "max_read": MAX_READ_PROJ,
            "soft_margin_days": SOFT_MARGIN_DAYS,
            "soft_margin_sessions": SOFT_MARGIN_SESSIONS,
            "open_only_overlap": OPEN_ONLY_OVERLAP,
            "open_close_overlap": OPEN_CLOSE_OVERLAP,
            "evidence_channels": [CHANNEL_ENTITY, CHANNEL_SHORT_OPENING],
            "opening_move_kind": principles.opening_move_kind(),
            "policy": (
                "Soft-window hand-off: date-trust geometries are seeds/report keys, "
                "not sealed lids. DP₁ entity then DP₂ short/opening with rescaled "
                "opening overlap; freeze = DP₁ taken ∪ graph ALIGNED_TO. "
                "No production PINNED_TO wire."
            ),
            **scope_meta(),
        }
    ]
    batches: list[PathBatch] = []
    n_dp1 = n_dp2 = n_skip_size = n_skip_side = n_dp2_skip = 0
    total_openings = 0
    total_match_entity = 0
    total_match_short = 0

    print(
        "\n=== SOFT WINDOWS — DP₁ entity → DP₂ short/opening "
        f"(margin ±{SOFT_MARGIN_DAYS}d / ±{SOFT_MARGIN_SESSIONS} sess) ==="
    )
    for seed in seeds:
        seed_lo = str(seed["calendar_lo"])[:10]
        seed_hi = str(seed["calendar_hi"])[:10]
        seed_sess_lo = _session_num(seed["anchor_lo_session"])
        seed_sess_hi = _session_num(seed["anchor_hi_session"])
        soft_lo, soft_hi = soft_calendar_span(seed_lo, seed_hi)
        soft_sess_lo, soft_sess_hi = soft_session_span(seed_sess_lo, seed_sess_hi)

        volgnrs = _editorial_stream(soft_lo, soft_hi, enr_by_date=enr_by_date)
        flats = _sorted_flats_for_sessions(
            seed["inventory"], soft_sess_lo, soft_sess_hi, axis_index=axis_index
        )
        n_unaligned = _n_unaligned(graph, volgnrs)
        openings = _opening_hits(flats, flat_text)
        total_openings += len(openings)
        flat_strength = {h["flat_id"]: float(h["strength"]) for h in openings}

        base = {
            "record_type": "trusted_bracket",
            "inventory": seed["inventory"],
            "seed_calendar_lo": seed_lo,
            "seed_calendar_hi": seed_hi,
            "seed_anchor_lo_session": seed["anchor_lo_session"],
            "seed_anchor_hi_session": seed["anchor_hi_session"],
            "calendar_lo": soft_lo,
            "calendar_hi": soft_hi,
            "anchor_lo_session": f"session-{seed['inventory']}-num-{soft_sess_lo}",
            "anchor_hi_session": f"session-{seed['inventory']}-num-{soft_sess_hi}",
            "soft_margin_days": SOFT_MARGIN_DAYS,
            "soft_margin_sessions": SOFT_MARGIN_SESSIONS,
            "k_e": len(volgnrs),
            "k_f": len(flats),
            "n_unaligned_in_stream": n_unaligned,
            "n_opening_hits": len(openings),
            "opening_examples": openings[:5],
            "opening_as_dp_move": principles.opening_move_kind(),
            "n_graph_aligned_flats": len(graph_aligned_flats),
        }

        if len(volgnrs) < MIN_SIDE or len(flats) < MIN_SIDE:
            n_skip_side += 1
            rows.append({
                **base,
                "status": "skipped_too_small",
                "dp1_ran": False,
                "dp2_ran": False,
            })
            print(
                f"  SKIP small {seed['inventory']} soft {soft_lo}..{soft_hi}  "
                f"k_e={len(volgnrs)} k_f={len(flats)}  openings={len(openings)}"
            )
            continue

        dp1_result: AlignmentResult | None = None
        frozen: set[str] = set(graph_aligned_flats)
        if len(volgnrs) <= MAX_REF_PROJ and len(flats) <= MAX_READ_PROJ:
            dp1_result, cache1 = align_streams(volgnrs, flats, entity_scorer)
            n_dp1 += 1
            frozen = frozen | taken_read_flats(dp1_result, flats)
            batch1 = PathBatch(
                tier="trusted_bracket_dp1",
                volgnrs=tuple(volgnrs),
                flat_ids=tuple(flats),
                result=dp1_result,
                detail={
                    "inventory": seed["inventory"],
                    "calendar_lo": soft_lo,
                    "calendar_hi": soft_hi,
                    "seed_calendar_lo": seed_lo,
                    "seed_calendar_hi": seed_hi,
                    "source": "date_trust_soft_window",
                    "aligner": "dp1_entity",
                    "evidence_channel": CHANNEL_ENTITY,
                },
            )
            batches.append(batch1)
            summary1 = _path_summary(dp1_result, cache1)
            total_match_entity += int(summary1["n_match_with_entity"])
            crumbs1 = []
            for p in dp1_result.pairs:
                if p.kind != MATCH or p.ref_index is None or p.read_index is None:
                    continue
                ov = cache1.get((p.ref_index, p.read_index), 0.0)
                if ov <= 0:
                    continue
                crumbs1.append({
                    "volgnr": volgnrs[p.ref_index],
                    "flat_id": flats[p.read_index],
                    "overlap": round(ov, 3),
                })
                if len(crumbs1) >= 5:
                    break
            rows.append({
                **base,
                "status": "dp1_ok",
                "dp1_ran": True,
                "aligner": "dp1_entity",
                "evidence_channel": CHANNEL_ENTITY,
                "n_frozen_reads": len(frozen),
                "claim": "entity_path_inside_soft_window",
                "example_evidenced_matches": crumbs1,
                **summary1,
            })
            print(
                f"  DP1 {seed['inventory']} soft {soft_lo}..{soft_hi} "
                f"(seed {seed_lo}..{seed_hi})  "
                f"k_e={len(volgnrs)} k_f={len(flats)}  unaligned={n_unaligned}  "
                f"MATCH={summary1['n_match']} (entity={summary1['n_match_with_entity']})  "
                f"frozen={len(frozen)}  openings={len(openings)}  "
                f"cost={summary1['total_cost']}"
            )
            for c in crumbs1[:2]:
                print(f"    MATCH {c['volgnr']} ↔ {c['flat_id']}  overlap={c['overlap']}")
        else:
            n_skip_size += 1
            rows.append({
                **base,
                "status": "dp1_oversize_abstain",
                "dp1_ran": False,
                "claim": "entity_dp_abstain_oversize_no_reseal",
            })
            print(
                f"  DP1-ABSTAIN-SIZE {seed['inventory']} soft {soft_lo}..{soft_hi}  "
                f"k_e={len(volgnrs)} k_f={len(flats)}  "
                f"unaligned={n_unaligned}  openings={len(openings)}"
            )

        # --- DP₂ hand-off: short unaligned × unclaimed HTR ---
        residue_refs = _short_unaligned_volgnrs(graph, volgnrs, enriched_by_vid)
        free_flats = [f for f in flats if f not in frozen]
        n_open_free = sum(1 for f in free_flats if flat_strength.get(f, 0.0) > 0)

        if len(residue_refs) < MIN_SIDE or len(free_flats) < MIN_SIDE:
            n_dp2_skip += 1
            rows.append({
                **base,
                "record_type": "trusted_bracket_handoff",
                "status": "dp2_skipped_too_small",
                "dp2_ran": False,
                "aligner": "dp2_short_opening",
                "n_residue_short": len(residue_refs),
                "n_free_flats": len(free_flats),
                "n_opening_free": n_open_free,
                "n_frozen_reads": len(frozen),
                "claim": "short_opening_residue_too_thin",
            })
            print(
                f"  DP2-SKIP {seed['inventory']} soft {soft_lo}..{soft_hi}  "
                f"short={len(residue_refs)}  free_flats={len(free_flats)}  "
                f"open_free={n_open_free}"
            )
            continue

        if len(residue_refs) > MAX_REF_PROJ or len(free_flats) > MAX_READ_PROJ:
            n_dp2_skip += 1
            rows.append({
                **base,
                "record_type": "trusted_bracket_handoff",
                "status": "dp2_oversize_abstain",
                "dp2_ran": False,
                "aligner": "dp2_short_opening",
                "n_residue_short": len(residue_refs),
                "n_free_flats": len(free_flats),
                "n_opening_free": n_open_free,
                "n_frozen_reads": len(frozen),
                "claim": "short_opening_dp_abstain_oversize_no_reseal",
            })
            print(
                f"  DP2-ABSTAIN-SIZE {seed['inventory']} soft {soft_lo}..{soft_hi}  "
                f"short={len(residue_refs)}  free_flats={len(free_flats)}"
            )
            continue

        short_set = set(residue_refs)
        dp2_scorer = build_short_opening_scorer(
            short_set,
            flat_strength,
            volgnr_dates=volgnr_dates,
            flat_dates=flat_dates,
            principles=principles,
        )
        dp2_result, cache2 = align_streams(residue_refs, free_flats, dp2_scorer)
        n_dp2 += 1
        batch2 = PathBatch(
            tier="trusted_bracket_dp2",
            volgnrs=tuple(residue_refs),
            flat_ids=tuple(free_flats),
            result=dp2_result,
            detail={
                "inventory": seed["inventory"],
                "calendar_lo": soft_lo,
                "calendar_hi": soft_hi,
                "seed_calendar_lo": seed_lo,
                "seed_calendar_hi": seed_hi,
                "source": "date_trust_soft_window",
                "aligner": "dp2_short_opening",
                "evidence_channel": CHANNEL_SHORT_OPENING,
                "n_frozen_reads": len(frozen),
                "handed_off_from": "dp1_entity" if dp1_result is not None else "no_dp1",
            },
        )
        batches.append(batch2)
        summary2 = _path_summary(dp2_result, cache2)
        n_open_match = int(summary2["n_match_with_entity"])
        total_match_short += n_open_match
        crumbs2 = []
        for p in dp2_result.pairs:
            if p.kind != MATCH or p.ref_index is None or p.read_index is None:
                continue
            ov = cache2.get((p.ref_index, p.read_index), 0.0)
            if ov <= 0:
                continue
            crumbs2.append({
                "volgnr": residue_refs[p.ref_index],
                "flat_id": free_flats[p.read_index],
                "overlap": round(ov, 3),
            })
            if len(crumbs2) >= 5:
                break
        rows.append({
            **base,
            "record_type": "trusted_bracket_handoff",
            "status": "dp2_ok",
            "dp2_ran": True,
            "aligner": "dp2_short_opening",
            "evidence_channel": CHANNEL_SHORT_OPENING,
            "k_e": len(residue_refs),
            "k_f": len(free_flats),
            "n_residue_short": len(residue_refs),
            "n_free_flats": len(free_flats),
            "n_opening_free": n_open_free,
            "n_frozen_reads": len(frozen),
            "claim": "short_opening_path_on_soft_window_residue",
            "example_evidenced_matches": crumbs2,
            **summary2,
        })
        print(
            f"  DP2 {seed['inventory']} soft {soft_lo}..{soft_hi}  "
            f"short={len(residue_refs)} free={len(free_flats)}  "
            f"open_free={n_open_free}  "
            f"MATCH={summary2['n_match']} (opening={n_open_match})  "
            f"DEL={summary2['n_deletion']}  cost={summary2['total_cost']}"
        )
        for c in crumbs2[:3]:
            print(f"    SHORT {c['volgnr']} ↔ {c['flat_id']}  overlap={c['overlap']}")

    rows.append({
        "record_type": "summary",
        "n_brackets": len(seeds),
        "n_dp1_ran": n_dp1,
        "n_dp2_ran": n_dp2,
        "n_dp1_oversize": n_skip_size,
        "n_skipped_too_small": n_skip_side,
        "n_dp2_skipped": n_dp2_skip,
        "n_opening_hits_total": total_openings,
        "n_match_with_entity_total": total_match_entity,
        "n_match_with_opening_total": total_match_short,
        "n_batches": len(batches),
        "soft_margin_days": SOFT_MARGIN_DAYS,
        "soft_margin_sessions": SOFT_MARGIN_SESSIONS,
    })
    print(
        f"\nsummary: dp1={n_dp1}  dp2={n_dp2}  dp1_oversize={n_skip_size}  "
        f"small={n_skip_side}  dp2_skip={n_dp2_skip}  "
        f"opening_hits={total_openings}  "
        f"match_entity={total_match_entity}  match_opening={total_match_short}"
    )

    if push_graph and batches:
        print("\n=== PUSH → ALIGNED_TO:solver (DP₁+DP₂) ===")
        n_edges = push_batches_to_graph(graph, batches)
        coverage = save_loaded_graph(graph)
        rows.append({
            "record_type": "push",
            "n_batches": len(batches),
            "n_solver_edges_written": n_edges,
            "aligned_to_before": coverage["before"],
            "aligned_to_after": coverage["after"],
        })
        print(f"  wrote {n_edges} solver edges from {len(batches)} batches")
        for name, after_value in (coverage["after"] or {}).items():
            before_value = (coverage["before"] or {}).get(name)
            print(f"    {name:<25}{str(before_value):>8} -> {after_value}")

    return rows, batches, graph


def prove(
    *,
    seed: int,
    n_gold: int,
    n_silver: int,
    n_proj: int,
    open_mass: bool = False,
    unaligned_refs_only: bool = False,
) -> tuple[list[dict[str, Any]], list[PathBatch], nx.MultiDiGraph]:
    rng = random.Random(seed)
    print("Loading entity-overlap scorer (once)…")
    scorer = build_entity_overlap_scorer()
    print("Loading saved graph…")
    graph = load_graph()
    batches: list[PathBatch] = []

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "seed": seed,
            "n_gold": n_gold,
            "n_silver": n_silver,
            "n_proj": n_proj,
            "open_mass": open_mass,
            "unaligned_refs_only": unaligned_refs_only,
            "note": (
                "Mechanism proof, not a perfection gate. Gold scores exact agreement; "
                "silver checks recovery of legacy concordance flats; projection only "
                "reports ordered MATCH cells with entity evidence inside random sync gaps. "
                "With open_mass, projection samples brackets that still have unsynced "
                "meetings and unaligned k_e. With unaligned_refs_only, the editorial stream "
                "is filtered to currently unaligned volgnrs so MATCH can move coverage. "
                "MATCH/INSERTION_SPLIT cells are plowed back as ALIGNED_TO:solver when "
                "--push-graph is set."
            ),
            **scope_meta(),
        }
    ]
    print(f"\n=== GOLD (n={n_gold}, seed={seed}) ===")
    gold_rows, gold_batches = prove_gold(rng, n_gold, scorer)
    rows.extend(gold_rows)
    batches.extend(gold_batches)
    for r in gold_rows:
        print(
            f"  {r['date']}  k_e={r['k_e']} k_f={r['k_f']}  "
            f"exact={r['exact_agreement']} (n={r['exact_agreement_n']})  "
            f"matches={r['n_match']}  cost={r['total_cost']}"
        )

    print(f"\n=== SILVER (n={n_silver}, seed={seed}) ===")
    silver_rows, silver_batches = prove_silver(rng, n_silver, scorer, graph)
    rows.extend(silver_rows)
    batches.extend(silver_batches)
    for r in silver_rows:
        if "error" in r:
            print(f"  {r['error']}")
            continue
        print(
            f"  {r['date']}  k_e={r['k_e']} k_f={r['k_f']}  "
            f"silver recovered {r['silver_pairs_recovered']}/{r['silver_pairs_checked']} "
            f"({r['silver_recovery_rate']})  "
            f"match_w_entity={r['n_match_with_entity']}/{r['n_match']}"
        )

    label = "open-mass" if open_mass else "random"
    if unaligned_refs_only:
        label += "+unaligned-refs"
    print(f"\n=== PROJECTION — {label} sync gaps (n={n_proj}, seed={seed}) ===")
    proj_rows, proj_batches = prove_projection(
        rng,
        n_proj,
        scorer,
        graph,
        open_mass=open_mass,
        unaligned_refs_only=unaligned_refs_only,
    )
    rows.extend(proj_rows)
    batches.extend(proj_batches)
    for r in proj_rows:
        if "error" in r:
            print(f"  {r['error']}")
            continue
        print(
            f"  {r['inventory']} {r['calendar_lo']}..{r['calendar_hi']}  "
            f"k_e={r['k_e']} k_f={r['k_f']}  "
            f"unaligned={r.get('n_unaligned_in_stream')}  "
            f"no_pin_meetings={r.get('n_meetings_no_production_pin_in_span')}  "
            f"MATCH={r['n_match']} (entity={r['n_match_with_entity']})  "
            f"DEL={r['n_deletion']}  cost={r['total_cost']}"
        )
        for c in r.get("example_evidenced_matches") or []:
            print(f"    MATCH {c['volgnr']} ↔ {c['flat_id']}  overlap={c['overlap']}")

    return rows, batches, graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prove", action="store_true", help="run gold/silver/projection samples")
    parser.add_argument(
        "--trusted-brackets",
        action="store_true",
        help="DP₁ entity then DP₂ short/opening hand-off inside date-trusted brackets",
    )
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--n-gold", type=int, default=3)
    parser.add_argument("--n-silver", type=int, default=3)
    parser.add_argument("--n-proj", type=int, default=3)
    parser.add_argument(
        "--open-mass",
        action="store_true",
        help=(
            "projection only: sample brackets with unsynced meetings AND ≥1 unaligned "
            "enriched resolution"
        ),
    )
    parser.add_argument(
        "--unaligned-refs-only",
        action="store_true",
        help=(
            "projection only: editorial stream = currently unaligned volgnrs only "
            "(required for --push-graph to move unaligned → solver_derived_only)"
        ),
    )
    parser.add_argument("--write", action="store_true", help="persist proof rows")
    parser.add_argument(
        "--push-graph",
        action="store_true",
        help="after the run, write MATCH/INSERTION_SPLIT as ALIGNED_TO:solver and save the graph",
    )
    args = parser.parse_args()
    if not args.prove and not args.trusted_brackets:
        parser.error("pass --prove and/or --trusted-brackets")

    if args.trusted_brackets:
        rows, batches, graph = align_trusted_brackets(push_graph=args.push_graph)
        if args.write:
            save_semi_structured(
                rows,
                logical_name=TRUSTED_BRACKET_DATASET,
                script=__file__,
                description=(
                    "Soft-window DP hand-off: date-trust seeds expand by "
                    f"±{SOFT_MARGIN_DAYS}d / ±{SOFT_MARGIN_SESSIONS} sessions. "
                    "DP₁ entity then DP₂ short/opening (rescaled overlap); freeze = "
                    "DP₁ taken ∪ graph ALIGNED_TO. Channels entity_dp / "
                    "short_opening_dp. No production PINNED_TO wire."
                ),
                parent_sources=[
                    DATE_TRUST_DATASET,
                    "sequence_graph_nodes",
                    "sequence_graph_edges",
                    "paragraph_axis_1626_1630",
                    "enriched_resolutions_1626_1630",
                ],
            )
            print(f"\nWrote {TRUSTED_BRACKET_DATASET}")
        if not args.prove:
            return

    rows, batches, graph = prove(
        seed=args.seed,
        n_gold=args.n_gold,
        n_silver=args.n_silver,
        n_proj=args.n_proj,
        open_mass=args.open_mass,
        unaligned_refs_only=args.unaligned_refs_only,
    )

    if args.push_graph:
        print("\n=== PUSH → saved graph (ALIGNED_TO:solver) ===")
        n_edges = push_batches_to_graph(graph, batches)
        coverage = save_loaded_graph(graph)
        rows.append({
            "record_type": "push",
            "n_batches": len(batches),
            "n_solver_edges_written": n_edges,
            "aligned_to_before": coverage["before"],
            "aligned_to_after": coverage["after"],
        })
        print(f"  wrote {n_edges} solver edges from {len(batches)} batches")
        print("  ALIGNED_TO coverage before → after:")
        for name, after_value in (coverage["after"] or {}).items():
            before_value = (coverage["before"] or {}).get(name)
            print(f"    {name:<25}{str(before_value):>8} -> {after_value}")

    if args.write:
        save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=(
                "Random gold/silver/projection proof that bracket-level entity sequence "
                "alignment runs on sync gaps (mechanism, not perfection). Optional graph push."
            ),
            parent_sources=[
                "sequence_graph_nodes",
                "sequence_graph_edges",
                "sequence_graph_sync_gaps",
                "boundary_gold_sample",
            ],
        )
        print(f"\nWrote {OUTPUT_DATASET}")


if __name__ == "__main__":
    main()

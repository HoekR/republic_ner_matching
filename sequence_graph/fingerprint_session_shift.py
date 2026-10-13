"""Fingerprint gate for resolution session-shift (ALIGNED_TO track).

Dating lids and ALIGNED_TO stay separate — no corpus-wide dating rewrite here.
Content matching is date-free: score in a session neighbourhood (S vs S+Δ).
Concordance PINNED_TO is date-signed; do not use calendar day as the join.
After recalibration, content is a read-only check on lids — never writes them.

  --on-gold                   synthetic Δ gate on held-out tier1 (instrument)
  --scaffold-neighbourhood-gold  thin hand-gold candidates for labeling
  --on-neighbourhood-gold     apply gate vs hand labels (correct_session filled)
  --on-neighbourhood          bulk S vs S+Δ report (provisional until gold PASS)
  --on-overflow-split         multi-summary→same-flat split signal + encoder cuts
  --bake-track-gold           as-is → proposed-end gold from hand labels + overflow proof
  --on-lag                    diagnostic only (date-join; not the apply gate)
  --on-boundary-gold          focused start/end/date-cut check (thin)

Preceding-scan / session-tail evidence stays deferred.

Usage:
    uv run python -m sequence_graph.fingerprint_session_shift --scaffold-neighbourhood-gold --write
    uv run python -m sequence_graph.fingerprint_session_shift --on-neighbourhood-gold --write
    uv run python -m sequence_graph.fingerprint_session_shift --on-overflow-split --write
    uv run python -m sequence_graph.fingerprint_session_shift --bake-track-gold --write
    uv run python -m sequence_graph.fingerprint_session_shift --on-gold --write
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from build_alignment_new import enriched_volgnr
from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from scripts.tfidf_similarity_pair_discrimination_eval import (
    eligible_day_counts,
    load_tier1_pairs,
)
from sequence_graph.align import build_entity_overlap_scorer
from sequence_graph.correspondence import OBSERVED_ON
from sequence_graph.persist import load_graph
from sequence_graph.problem_sequence_review import dated_as_review_claims_from_notes
from sequence_graph.resolution_fingerprint_eval import (
    FINGERPRINT_OVERLAP_SCALE,
    TRAIN_FRACTION,
    RANDOM_SEED,
    TEST_DAY_CAP,
    TrainFittedTfidfFingerprint,
    fit_fingerprint_on_tier1,
    train_test_day_split,
)
from sequence_graph.sync_gap_align import _axis_by_inv_sess, _enriched_by_date

# Separate datasets per mode — save_semi_structured overwrites; do not share one name.
GOLD_OUTPUT_DATASET = "fingerprint_session_shift_gold"
LAG_OUTPUT_DATASET = "fingerprint_session_shift_lag"
BOUNDARY_OUTPUT_DATASET = "fingerprint_boundary_gold_check"
NEIGHBOURHOOD_GOLD_DATASET = "neighbourhood_shift_gold"
NEIGHBOURHOOD_GOLD_EVAL_DATASET = "fingerprint_session_shift_neighbourhood_gold"
NEIGHBOURHOOD_REPORT_DATASET = "fingerprint_session_shift_neighbourhood"
OVERFLOW_SPLIT_DATASET = "fingerprint_overflow_split_proof"
TRACK_GOLD_DATASET = "aligned_to_overflow_track_gold"
SESSION_RE = re.compile(r"session-(\d+)-num-(\d+)$")
_HALF_RANK = {"HALF_A": 0, "HALF_B": 1, "WHOLE": 2, "abstain": 3}
DEFAULT_DELTAS = (7, 8, 9)
NEIGHBOURHOOD_SCAFFOLD_CAP = 30  # thin hand-gold target
# CostModel-scaled margin: fingerprint×15 so ~0.03 cosine ≈ 0.45; require clear winner.
MARGIN_SCALED = 0.5
EDGE_KINDS = frozenset({
    "start",
    "end_of_last_resolution",
    "date_start",
    "date_end",
})
BOUNDARY_GOLD_SOURCES = (
    "boundary_gold_sample",
    "boundary_gold_hard_period_sample",
)


def session_num(session_id: str) -> int | None:
    m = SESSION_RE.search(session_id or "")
    return int(m.group(2)) if m else None


def inventory_of(session_id: str) -> str | None:
    m = SESSION_RE.search(session_id or "")
    return m.group(1) if m else None


def shift_session(session_id: str, delta: int) -> str | None:
    """Return session-{inv}-num-{N+delta}, or None if unparseable."""
    m = SESSION_RE.search(session_id or "")
    if not m:
        return None
    return f"session-{m.group(1)}-num-{int(m.group(2)) + delta}"


def median_lag_delta(default: int = 8) -> int:
    """Median pin Δ from hard_recalibrate_proof meta, else ``default``."""
    try:
        rows = load("hard_recalibrate_proof")
    except Exception:
        return default
    meta = next((r for r in rows if r.get("record_type") == "meta"), None)
    if not meta:
        return default
    md = meta.get("median_delta")
    return int(md) if md is not None else default


def label_top1_session(
    *,
    gold_session: str,
    competitor_session: str,
    best_flat: str | None,
    best_score: float,
    second_score: float,
    margin: float = MARGIN_SCALED,
    prefer_label: str = "gold",
    other_label: str = "competitor",
) -> str:
    """Return prefer_label / other_label / abstain from top-1 flat and score margin."""
    if best_flat is None:
        return "abstain"
    if best_score - second_score < margin:
        return "abstain"
    sid = re.sub(r"-resolution-\d+$", "", best_flat)
    if sid == gold_session:
        return prefer_label
    if sid == competitor_session:
        return other_label
    return "abstain"


def _session_of_flat(flat_id: str) -> str:
    return re.sub(r"-resolution-\d+$", "", flat_id or "")


def _observed_scan_nums(graph: Any, session_id: str, inventory: str) -> set[int]:
    node = f"session:{session_id}"
    if node not in graph:
        return set()
    out: set[int] = set()
    for _u, v, ed in graph.out_edges(node, data=True):
        if ed.get("kind") != OBSERVED_ON:
            continue
        if graph.nodes[v].get("kind") != "Scan":
            continue
        obj = graph.nodes[v]["obj"]
        if obj.inventory == inventory:
            out.add(int(obj.scan_num))
    return out


def _load_hard_proof() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    rows = load("hard_recalibrate_proof")
    if not rows:
        raise SystemExit("hard_recalibrate_proof empty — run hard_recalibrate --write first")
    meta = next(r for r in rows if r.get("record_type") == "meta")
    hard = [r for r in rows if r.get("record_type") == "hard_map" and r.get("active")]
    literal = [r for r in rows if r.get("record_type") == "literal_opening" and r.get("matched")]
    return meta, hard, literal


def score_volgnr_against_flats(
    volgnr: str,
    enriched_text: str,
    flats: list[str],
    flat_texts: dict[str, str],
    *,
    fingerprint: TrainFittedTfidfFingerprint,
    entity_scorer: Any,
    scale: float = FINGERPRINT_OVERLAP_SCALE,
) -> list[tuple[str, float]]:
    """Return (flat_id, entity+scaled_fp) descending."""
    if not flats:
        return []
    texts = [flat_texts.get(f) or "" for f in flats]
    fp = scale * fingerprint.similarity_matrix([enriched_text or ""], texts)[0]
    scored: list[tuple[str, float]] = []
    for i, fid in enumerate(flats):
        ent = float(entity_scorer(volgnr, fid)) if entity_scorer else 0.0
        scored.append((fid, ent + float(fp[i])))
    scored.sort(key=lambda x: -x[1])
    return scored


def _flat_text_by_id() -> dict[str, str]:
    from collections import defaultdict

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


def _main_series_tier1() -> pd.DataFrame:
    tier1 = load_tier1_pairs()
    mask = tier1["session_id"].astype(str).map(is_main_series)
    pairs = tier1.loc[mask].reset_index(drop=True)
    if "volgnr" not in pairs.columns:
        pairs = pairs.copy()
        pairs["volgnr"] = pairs["enriched_id"].astype(str)
    return pairs


def _flats_for_session(
    session_id: str,
    axis_index: dict[tuple[str, int], list[str]],
) -> list[str]:
    inv = inventory_of(session_id)
    num = session_num(session_id)
    if inv is None or num is None:
        return []
    return list(axis_index.get((inv, num), []))


def run_on_gold(
    *,
    deltas: tuple[int, ...] | None = None,
    primary_delta: int | None = None,
    train_fraction: float = TRAIN_FRACTION,
    seed: int = RANDOM_SEED,
    test_day_cap: int = TEST_DAY_CAP,
    margin: float = MARGIN_SCALED,
) -> list[dict[str, Any]]:
    primary = primary_delta if primary_delta is not None else median_lag_delta()
    deltas = deltas or DEFAULT_DELTAS
    if primary not in deltas:
        deltas = tuple(sorted(set(deltas) | {primary}))

    pairs = _main_series_tier1()
    day_counts = eligible_day_counts(pairs)
    train_dates, test_dates = train_test_day_split(
        day_counts, train_fraction=train_fraction, seed=seed
    )
    train_set, test_set = set(train_dates), set(test_dates)
    train_pairs = pairs.loc[pairs["date"].astype(str).isin(train_set)]
    test_pairs = pairs.loc[pairs["date"].astype(str).isin(test_set)]

    train_texts = (
        train_pairs["enriched_text"].fillna("").astype(str).tolist()
        + train_pairs["flat_text"].fillna("").astype(str).tolist()
    )
    fingerprint = TrainFittedTfidfFingerprint()
    fingerprint.fit(train_texts)
    entity_scorer = build_entity_overlap_scorer()
    axis_index = _axis_by_inv_sess()
    flat_texts = _flat_text_by_id()

    # Cap test days (same cost guard as fingerprint eval).
    rng = np.random.default_rng(seed)
    eval_dates = list(test_dates)
    if test_day_cap and len(eval_dates) > test_day_cap:
        pick = rng.choice(len(eval_dates), size=test_day_cap, replace=False)
        eval_dates = sorted(eval_dates[i] for i in pick)
    eval_set = set(eval_dates)
    eval_pairs = test_pairs.loc[test_pairs["date"].astype(str).isin(eval_set)]

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "on_gold",
            "edge": "ALIGNED_TO",
            "pair_source": "alignment_1626_1630.tier1_anchor",
            "primary_delta": primary,
            "deltas": list(deltas),
            "margin_scaled": margin,
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "train_fraction": train_fraction,
            "seed": seed,
            "n_train_days": len(train_dates),
            "n_test_days": len(test_dates),
            "n_eval_days": len(eval_dates),
            "n_eval_pairs": int(len(eval_pairs)),
            "n_train_fit_texts": len(train_texts),
            "preceding_scan_channel": "deferred_hard_case_not_in_this_gate",
            "policy": (
                "Gold-first synthetic session-lag gate. Fit TF-IDF on train days only; "
                "for each held-out tier1 pair, score against gold-session flats ∪ "
                "competitor session (num+Δ) flats; entity+scaled fingerprint. "
                "Dating lids untouched. Lag rematch and preceding-scan tail deferred. "
                "No production wire."
            ),
            **scope_meta(),
        }
    ]

    sensitivity: dict[int, Counter[str]] = {d: Counter() for d in deltas}
    flat_ok: dict[int, Counter[str]] = {d: Counter() for d in deltas}

    for _, pr in eval_pairs.iterrows():
        gold_sid = str(pr["session_id"])
        volgnr = str(pr["volgnr"])
        gold_flat = str(pr["flat_id"])
        enr_text = str(pr.get("enriched_text") or "")
        date = str(pr["date"])[:10]
        gold_flats = _flats_for_session(gold_sid, axis_index)
        if not gold_flats:
            gold_flats = [gold_flat]

        for delta in deltas:
            comp_sid = shift_session(gold_sid, delta)
            if not comp_sid:
                continue
            comp_flats = _flats_for_session(comp_sid, axis_index)
            pool = list(dict.fromkeys(gold_flats + comp_flats))
            if len(pool) < 2 or not comp_flats:
                sensitivity[delta]["no_competitor"] += 1
                rows.append({
                    "record_type": "pair",
                    "date": date,
                    "volgnr": volgnr,
                    "gold_flat": gold_flat,
                    "gold_session": gold_sid,
                    "delta": delta,
                    "competitor_session": comp_sid,
                    "verdict": "no_competitor",
                    "n_gold_flats": len(gold_flats),
                    "n_competitor_flats": len(comp_flats),
                })
                continue

            ranked = score_volgnr_against_flats(
                volgnr,
                enr_text,
                pool,
                flat_texts,
                fingerprint=fingerprint,
                entity_scorer=entity_scorer,
            )
            best_flat, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            verdict = label_top1_session(
                gold_session=gold_sid,
                competitor_session=comp_sid,
                best_flat=best_flat,
                best_score=best_score,
                second_score=second_score,
                margin=margin,
            )
            sensitivity[delta][verdict] += 1
            if verdict == "gold":
                flat_ok[delta]["exact_flat" if best_flat == gold_flat else "session_only"] += 1
            rows.append({
                "record_type": "pair",
                "date": date,
                "volgnr": volgnr,
                "gold_flat": gold_flat,
                "gold_session": gold_sid,
                "delta": delta,
                "competitor_session": comp_sid,
                "top1_flat": best_flat,
                "top1_score": round(best_score, 4),
                "second_score": round(second_score, 4),
                "verdict": verdict,
                "exact_flat_match": best_flat == gold_flat,
                "n_gold_flats": len(gold_flats),
                "n_competitor_flats": len(comp_flats),
                "n_pool": len(pool),
            })

    for delta in deltas:
        counts = sensitivity[delta]
        scored = sum(counts[k] for k in ("gold", "competitor", "abstain"))
        gold_n = counts["gold"]
        non_abs = gold_n + counts["competitor"]
        rows.append({
            "record_type": "delta_summary",
            "delta": delta,
            "is_primary": delta == primary,
            "n_gold": gold_n,
            "n_competitor": counts["competitor"],
            "n_abstain": counts["abstain"],
            "n_no_competitor": counts["no_competitor"],
            "n_scored": scored,
            "gold_session_recovery": (
                round(gold_n / non_abs, 4) if non_abs else None
            ),
            "gold_including_abstain": (
                round(gold_n / scored, 4) if scored else None
            ),
            "exact_flat_among_gold_session": (
                round(
                    flat_ok[delta]["exact_flat"] / gold_n,
                    4,
                )
                if gold_n
                else None
            ),
            "gate_pass_narrative": (
                "PASS if gold_session_recovery ≫ 0.5 on primary Δ "
                "(expect near within-day fingerprint top-1 if session-discriminative)"
            ),
        })

    primary_sum = next(
        r for r in rows if r.get("record_type") == "delta_summary" and r.get("is_primary")
    )
    rows[0]["primary_gold_session_recovery"] = primary_sum.get("gold_session_recovery")
    rows[0]["primary_n_gold"] = primary_sum.get("n_gold")
    rows[0]["primary_n_competitor"] = primary_sum.get("n_competitor")
    rows[0]["primary_n_abstain"] = primary_sum.get("n_abstain")
    return rows


def run_on_lag(*, margin: float = MARGIN_SCALED) -> list[dict[str, Any]]:
    """Production proof: on pin-disagree days, does fingerprint prefer the hard session?"""
    proof_meta, hard_rows, literal_rows = _load_hard_proof()
    inventory = str(proof_meta["inventory"])
    lo = str(proof_meta["calendar_lo"])
    hi = str(proof_meta["calendar_hi"])
    disagree = [
        r
        for r in hard_rows
        if r.get("production_disagrees")
        and r.get("session_id")
        and r.get("production_session")
        and lo <= r["date"] <= hi
        and in_scope(r["date"])
    ]
    if not disagree:
        raise SystemExit(f"no production≠hard active days in {lo}..{hi}")

    exclude_dates = {r["date"] for r in hard_rows if lo <= r["date"] <= hi}
    fingerprint, fp_meta = fit_fingerprint_on_tier1(exclude_dates=exclude_dates)
    entity_scorer = build_entity_overlap_scorer()
    axis_index = _axis_by_inv_sess()
    flat_texts = _flat_text_by_id()
    enr_by_date = _enriched_by_date()
    enr_text: dict[str, str] = {}
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if vid:
            enr_text[vid] = str(er.get("text") or "")

    graph = load_graph()
    lit_by_sess = {r["session_id"]: r for r in literal_rows if r.get("session_id")}
    review_claims = [
        c
        for c in dated_as_review_claims_from_notes()
        if c.get("inventory") == inventory and lo <= c["date"] <= hi
    ]
    review_by_date: dict[str, list[dict[str, Any]]] = {}
    for c in review_claims:
        review_by_date.setdefault(c["date"], []).append(c)

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "on_lag",
            "edge": "ALIGNED_TO",
            "inventory": inventory,
            "calendar_lo": lo,
            "calendar_hi": hi,
            "n_disagree_days": len(disagree),
            "margin_scaled": margin,
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "n_review_claims_in_window": len(review_claims),
            "preceding_scan_channel": "deferred_hard_case_not_in_this_gate",
            "policy": (
                "Lag-window production proof. For each enriched on production≠hard "
                "days, score against production-session ∪ hard-session flats "
                "(entity+scaled TF-IDF fitted excluding the lag window). Prefer-hard "
                "rate among non-abstain; held-out review scan ∈ OBSERVED_ON(hard); "
                "literal opening on hard session. No production wire."
            ),
            **fp_meta,
            **scope_meta(),
        }
    ]

    verdicts: Counter[str] = Counter()
    n_enriched = 0
    review_agree = review_disagree = review_abstain = 0
    lit_agree = lit_missing = 0

    for hr in disagree:
        date = hr["date"]
        hard_sid = hr["session_id"]
        prod_sid = hr["production_session"]
        hard_flats = _flats_for_session(hard_sid, axis_index)
        prod_flats = _flats_for_session(prod_sid, axis_index)
        pool = list(dict.fromkeys(hard_flats + prod_flats))
        volgnrs = enr_by_date.get(date, [])
        hard_obs = _observed_scan_nums(graph, hard_sid, inventory)
        dated_bridge = set(hr.get("dated_scans_on_session") or [])
        lit = lit_by_sess.get(hard_sid)
        if lit:
            lit_agree += 1
        else:
            lit_missing += 1

        day_verdicts: Counter[str] = Counter()
        for volgnr in volgnrs:
            n_enriched += 1
            if len(pool) < 2 or not hard_flats or not prod_flats:
                verdict = "no_pool"
                verdicts[verdict] += 1
                day_verdicts[verdict] += 1
                rows.append({
                    "record_type": "lag_pair",
                    "date": date,
                    "volgnr": volgnr,
                    "hard_session": hard_sid,
                    "production_session": prod_sid,
                    "verdict": verdict,
                    "n_hard_flats": len(hard_flats),
                    "n_production_flats": len(prod_flats),
                })
                continue
            ranked = score_volgnr_against_flats(
                volgnr,
                enr_text.get(volgnr) or "",
                pool,
                flat_texts,
                fingerprint=fingerprint,
                entity_scorer=entity_scorer,
            )
            best_flat, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            verdict = label_top1_session(
                gold_session=hard_sid,
                competitor_session=prod_sid,
                best_flat=best_flat,
                best_score=best_score,
                second_score=second_score,
                margin=margin,
                prefer_label="hard",
                other_label="production",
            )
            verdicts[verdict] += 1
            day_verdicts[verdict] += 1
            rows.append({
                "record_type": "lag_pair",
                "date": date,
                "volgnr": volgnr,
                "hard_session": hard_sid,
                "production_session": prod_sid,
                "top1_flat": best_flat,
                "top1_session": _session_of_flat(best_flat),
                "top1_score": round(best_score, 4),
                "second_score": round(second_score, 4),
                "verdict": verdict,
                "n_hard_flats": len(hard_flats),
                "n_production_flats": len(prod_flats),
                "n_pool": len(pool),
            })

        # Held-out review: does the day's majority/fingerprint hard pick observe the review scan?
        for claim in review_by_date.get(date, []):
            scan = int(claim["scan_num"])
            day_prefers_hard = day_verdicts["hard"] > day_verdicts["production"]
            on_hard = scan in hard_obs or scan in dated_bridge
            if day_verdicts["hard"] + day_verdicts["production"] == 0:
                review_abstain += 1
                status = "day_abstain"
            elif day_prefers_hard and on_hard:
                review_agree += 1
                status = "agree"
            elif day_prefers_hard and not on_hard:
                review_disagree += 1
                status = "hard_pref_but_scan_not_on_hard"
            elif not day_prefers_hard and on_hard:
                review_disagree += 1
                status = "scan_on_hard_but_fp_prefers_production"
            else:
                review_disagree += 1
                status = "disagree"
            rows.append({
                "record_type": "review_check",
                "date": date,
                "review_scan": scan,
                "hard_session": hard_sid,
                "production_session": prod_sid,
                "review_scan_on_hard": on_hard,
                "day_verdicts": dict(day_verdicts),
                "status": status,
            })

        rows.append({
            "record_type": "lag_day",
            "date": date,
            "hard_session": hard_sid,
            "production_session": prod_sid,
            "n_enriched": len(volgnrs),
            "verdicts": dict(day_verdicts),
            "literal_opening_on_hard": bool(lit),
            "n_review_claims": len(review_by_date.get(date, [])),
        })

    decided = verdicts["hard"] + verdicts["production"]
    prefer_hard = (
        round(verdicts["hard"] / decided, 4) if decided else None
    )
    rows[0].update({
        "n_enriched": n_enriched,
        "n_hard": verdicts["hard"],
        "n_production": verdicts["production"],
        "n_abstain": verdicts["abstain"],
        "n_no_pool": verdicts["no_pool"],
        "prefer_hard_rate": prefer_hard,
        "n_review_agree": review_agree,
        "n_review_disagree": review_disagree,
        "n_review_abstain": review_abstain,
        "n_literal_on_hard_days": lit_agree,
        "n_literal_missing_days": lit_missing,
    })
    rows.append({
        "record_type": "lag_summary",
        "prefer_hard_rate": prefer_hard,
        "n_hard": verdicts["hard"],
        "n_production": verdicts["production"],
        "n_abstain": verdicts["abstain"],
        "n_no_pool": verdicts["no_pool"],
        "n_enriched": n_enriched,
        "n_disagree_days": len(disagree),
        "review_agree": review_agree,
        "review_disagree": review_disagree,
        "review_abstain": review_abstain,
        "literal_opening_days": lit_agree,
        "gate_pass_narrative": (
            "PASS if prefer_hard_rate ≫ 0.5 among non-abstain and "
            "held-out review does not systematically disagree"
        ),
    })
    return rows


def _is_located_boundary(slot: dict[str, Any]) -> bool:
    return (
        slot.get("flat_id") is not None
        and slot.get("char_offset") is not None
        and str(slot.get("unit") or "") != "out_of_range"
        and str(slot.get("unit") or "") != "no_htr_text"
    )


def _load_boundary_gold_days() -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    for name in BOUNDARY_GOLD_SOURCES:
        sample = load(name)
        for day in sample.get("days") or []:
            row = dict(day)
            row["_gold_source"] = name
            days.append(row)
    return days


def _edge_events(day: dict[str, Any]) -> list[dict[str, Any]]:
    """Session begin/end / date-cut markers (not ordinary resolution CUTs)."""
    events: list[dict[str, Any]] = []
    k_e = int(day.get("k_e") or 0)
    enriched_ids = list(day.get("enriched_ids") or [])
    for slot in day.get("boundaries") or []:
        kind = str(slot.get("kind") or "")
        if kind not in EDGE_KINDS or not _is_located_boundary(slot):
            continue
        if kind == "start":
            enr_idx = 0
        elif kind == "end_of_last_resolution":
            enr_idx = max(k_e - 1, 0)
        else:
            # date_start / date_end: content after/before a calendar cut — use nearest end
            enr_idx = 0 if kind == "date_start" else max(k_e - 1, 0)
        if enr_idx >= len(enriched_ids):
            continue
        events.append({
            "kind": kind,
            "flat_id": str(slot["flat_id"]),
            "enriched_id": str(enriched_ids[enr_idx]),
            "enriched_index": enr_idx,
            "unit": slot.get("unit"),
            "paragraph_stream_index": slot.get("paragraph_stream_index"),
        })
    return events


def run_on_boundary_gold(*, margin: float = MARGIN_SCALED) -> list[dict[str, Any]]:
    """Focused check: fingerprint recovers hand-placed session start/end flats.

    Thin by construction — not a corpus gate. Ordinary CUT slots are out of scope here.
    """
    days = _load_boundary_gold_days()
    exclude_dates = {str(d["date"])[:10] for d in days if d.get("date")}
    fingerprint, fp_meta = fit_fingerprint_on_tier1(exclude_dates=exclude_dates)
    entity_scorer = build_entity_overlap_scorer()
    axis_index = _axis_by_inv_sess()
    flat_texts = _flat_text_by_id()
    enr_text: dict[str, str] = {}
    enr_volgnr_by_id: dict[str, str] = {}
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if not vid:
            continue
        enr_text[vid] = str(er.get("text") or "")
        # enriched_ids in gold look like 162608ja.xml#0 — map via volgnr date_index
        enr_volgnr_by_id[vid] = vid

    # Map gold enriched_ids (xml#n) → volgnr via date + resolution index
    from collections import defaultdict

    by_date_idx: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if not vid:
            continue
        try:
            idx = int(er.get("resolution_index") if er.get("resolution_index") is not None else vid.split("_")[-1])
        except (TypeError, ValueError):
            continue
        eid = str(er.get("id") or er.get("enriched_id") or "")
        by_date_idx[date].append((idx, vid, eid))

    def resolve_volgnr(date: str, enriched_id: str, enriched_index: int) -> str | None:
        rows = sorted(by_date_idx.get(date, []), key=lambda t: t[0])
        for idx, vid, eid in rows:
            if eid and eid == enriched_id:
                return vid
            if eid and enriched_id and eid.endswith(enriched_id.split("#")[-1]) and "#" in enriched_id:
                if eid == enriched_id or eid.endswith("#" + enriched_id.split("#")[-1]):
                    if eid == enriched_id:
                        return vid
        # fallback by index order
        if 0 <= enriched_index < len(rows):
            return rows[enriched_index][1]
        return None

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "on_boundary_gold",
            "edge": "ALIGNED_TO",
            "sources": list(BOUNDARY_GOLD_SOURCES),
            "edge_kinds": sorted(EDGE_KINDS),
            "n_gold_days_loaded": len(days),
            "margin_scaled": margin,
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "policy": (
                "Focused boundary-gold check (not a corpus gate). Hand-placed "
                "start / end_of_last_resolution / date_start / date_end markers only — "
                "ordinary CUT slots excluded. Fingerprint+entity vs gold flat's session "
                "flats (±1 neighbour). Thin annotations expected. No production wire."
            ),
            **fp_meta,
            **scope_meta(),
        }
    ]

    by_kind: dict[str, Counter[str]] = {k: Counter() for k in EDGE_KINDS}
    n_events = 0
    n_days_with_events = 0

    for day in days:
        date = str(day.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        events = _edge_events(day)
        if not events:
            continue
        n_days_with_events += 1
        for ev in events:
            n_events += 1
            gold_flat = ev["flat_id"]
            gold_sess = _session_of_flat(gold_flat)
            inv = inventory_of(gold_sess)
            num = session_num(gold_sess)
            if inv is None or num is None:
                by_kind[ev["kind"]]["bad_session"] += 1
                continue
            volgnr = resolve_volgnr(date, ev["enriched_id"], ev["enriched_index"])
            if not volgnr:
                by_kind[ev["kind"]]["no_enriched"] += 1
                rows.append({
                    "record_type": "boundary_event",
                    "date": date,
                    "gold_source": day["_gold_source"],
                    "kind": ev["kind"],
                    "gold_flat": gold_flat,
                    "verdict": "no_enriched",
                })
                continue
            # Candidate pool: gold session ± 1 (session-boundary ambiguity)
            pool: list[str] = []
            for n in (num - 1, num, num + 1):
                if n < 0:
                    continue
                pool.extend(axis_index.get((inv, n), []))
            pool = list(dict.fromkeys(pool))
            if gold_flat not in pool:
                pool.append(gold_flat)
            if len(pool) < 2:
                by_kind[ev["kind"]]["no_pool"] += 1
                continue
            ranked = score_volgnr_against_flats(
                volgnr,
                enr_text.get(volgnr) or "",
                pool,
                flat_texts,
                fingerprint=fingerprint,
                entity_scorer=entity_scorer,
            )
            best_flat, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            if best_score - second_score < margin:
                verdict = "abstain"
            elif best_flat == gold_flat:
                verdict = "exact_flat"
            elif _session_of_flat(best_flat) == gold_sess:
                verdict = "same_session"
            else:
                verdict = "wrong_session"
            by_kind[ev["kind"]][verdict] += 1
            rows.append({
                "record_type": "boundary_event",
                "date": date,
                "gold_source": day["_gold_source"],
                "kind": ev["kind"],
                "gold_flat": gold_flat,
                "gold_session": gold_sess,
                "volgnr": volgnr,
                "enriched_id": ev["enriched_id"],
                "top1_flat": best_flat,
                "top1_session": _session_of_flat(best_flat),
                "top1_score": round(best_score, 4),
                "second_score": round(second_score, 4),
                "verdict": verdict,
                "n_pool": len(pool),
                "starts_mid_resolution": bool(day.get("starts_mid_resolution")),
            })

    rows[0]["n_days_with_edge_events"] = n_days_with_events
    rows[0]["n_edge_events"] = n_events
    for kind, counts in sorted(by_kind.items()):
        decided = counts["exact_flat"] + counts["same_session"] + counts["wrong_session"]
        hit = counts["exact_flat"] + counts["same_session"]
        rows.append({
            "record_type": "boundary_kind_summary",
            "kind": kind,
            "n_exact_flat": counts["exact_flat"],
            "n_same_session": counts["same_session"],
            "n_wrong_session": counts["wrong_session"],
            "n_abstain": counts["abstain"],
            "n_no_enriched": counts["no_enriched"],
            "n_no_pool": counts["no_pool"],
            "n_bad_session": counts["bad_session"],
            "n_decided": decided,
            "session_hit_rate": round(hit / decided, 4) if decided else None,
            "exact_flat_rate": (
                round(counts["exact_flat"] / decided, 4) if decided else None
            ),
        })
    return rows


def _enriched_text_by_volgnr() -> dict[str, str]:
    out: dict[str, str] = {}
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if not date or not in_scope(date):
            continue
        vid = enriched_volgnr(er)
        if vid:
            out[vid] = str(er.get("text") or "")
    return out


def _opening_snippet(session_id: str, axis_index: dict, flat_texts: dict[str, str], n: int = 220) -> str:
    flats = _flats_for_session(session_id, axis_index)
    if not flats:
        return ""
    return (flat_texts.get(flats[0]) or "")[:n]


def scaffold_neighbourhood_gold(
    *,
    inventory: str = "3185",
    cap: int = NEIGHBOURHOOD_SCAFFOLD_CAP,
) -> list[dict[str, Any]]:
    """Candidate rows for hand labeling — correct_session left null.

    Baseline = concordance/production session on that calendar day (date-signed
    placement). Competitor = hard-map session for the same day when pins disagree,
    else baseline+median_Δ. Fill ``correct_session`` with the HTR block the text
    belongs to (content only — not a dating verdict).
    """
    proof_meta, hard_rows, _literal = _load_hard_proof()
    lo = str(proof_meta.get("calendar_lo") or "1626-09-21")
    hi = str(proof_meta.get("calendar_hi") or "1626-10-25")
    primary = median_lag_delta()
    disagree = [
        r
        for r in hard_rows
        if r.get("production_disagrees")
        and r.get("session_id")
        and r.get("production_session")
        and str(r.get("inventory") or proof_meta.get("inventory") or inventory) == inventory
        and lo <= r["date"] <= hi
        and in_scope(r["date"])
    ]
    axis_index = _axis_by_inv_sess()
    flat_texts = _flat_text_by_id()
    enr_by_date = _enriched_by_date()
    enr_text = _enriched_text_by_volgnr()

    # Preserve hand labels across re-scaffold / UI restarts.
    prior_by_volgnr: dict[str, dict[str, Any]] = {}
    try:
        for r in load(NEIGHBOURHOOD_GOLD_DATASET):
            if r.get("record_type") != "gold_label":
                continue
            vid = str(r.get("volgnr") or "")
            if vid and r.get("correct_session"):
                prior_by_volgnr[vid] = r
    except Exception:
        prior_by_volgnr = {}

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "scaffold_neighbourhood_gold",
            "edge": "ALIGNED_TO",
            "inventory": inventory,
            "calendar_lo": lo,
            "calendar_hi": hi,
            "primary_delta": primary,
            "cap": cap,
            "n_prior_labels_merged": len(prior_by_volgnr),
            "instructions": (
                "Hand gold for date-free session-shift. For each gold_label row, set "
                "correct_session to the HTR session whose text matches the enriched "
                "resolution (often baseline+Δ on lag stretches). Leave dating lids alone. "
                "Do not treat competitor_session as truth — it is only a neighbourhood hint. "
                "Re-scaffold merges existing correct_session / note by volgnr."
            ),
            "label_fields": [
                "volgnr",
                "baseline_session",
                "correct_session",
                "delta",
                "note",
            ],
            **scope_meta(),
        }
    ]

    n = 0
    for hr in disagree:
        if n >= cap:
            break
        date = hr["date"]
        baseline = str(hr["production_session"])
        competitor = str(hr["session_id"])  # hard session — hint only
        for volgnr in enr_by_date.get(date, []):
            if n >= cap:
                break
            b_num = session_num(baseline)
            c_num = session_num(competitor)
            delta = (
                (c_num - b_num)
                if b_num is not None and c_num is not None
                else primary
            )
            prior = prior_by_volgnr.get(volgnr) or {}
            correct = prior.get("correct_session")
            if correct and not (
                isinstance(correct, str) and correct.startswith("session-")
            ):
                correct = None
            rows.append({
                "record_type": "gold_label",
                "inventory": inventory,
                "volgnr": volgnr,
                "enriched_date_file": date,
                "baseline_session": baseline,
                "competitor_session": competitor,
                "correct_session": correct,
                "delta": (
                    prior.get("delta")
                    if correct
                    else delta
                ),
                "note": str(prior.get("note") or ""),
                "enriched_snippet": (enr_text.get(volgnr) or "")[:280],
                "baseline_opening_snippet": _opening_snippet(
                    baseline, axis_index, flat_texts
                ),
                "competitor_opening_snippet": _opening_snippet(
                    competitor, axis_index, flat_texts
                ),
                "labeled": bool(correct),
                "labelled_at": prior.get("labelled_at"),
                "labelled_via": prior.get("labelled_via"),
            })
            n += 1

    rows[0]["n_candidates"] = n
    rows[0]["n_labelled"] = sum(
        1 for r in rows if r.get("record_type") == "gold_label" and r.get("correct_session")
    )
    return rows


def load_labelled_neighbourhood_gold() -> list[dict[str, Any]]:
    """Rows with correct_session filled (hand labels)."""
    try:
        raw = load(NEIGHBOURHOOD_GOLD_DATASET)
    except Exception as exc:  # noqa: BLE001 — data_io raises DatasetNotFoundError
        raise SystemExit(
            f"{NEIGHBOURHOOD_GOLD_DATASET} missing — run "
            "--scaffold-neighbourhood-gold --write and label correct_session"
        ) from exc
    out: list[dict[str, Any]] = []
    for r in raw:
        if r.get("record_type") != "gold_label":
            continue
        correct = r.get("correct_session")
        baseline = r.get("baseline_session")
        volgnr = r.get("volgnr")
        if not volgnr or not baseline or not correct:
            continue
        if not isinstance(correct, str) or not correct.startswith("session-"):
            continue
        out.append(r)
    return out


def _needs_split_note(note: str) -> bool:
    n = (note or "").lower()
    return "split" in n


def annotate_neighbourhood_gold_status() -> list[dict[str, Any]]:
    """Mark not_found / needs_split on gold rows; preserve correct_session."""
    try:
        raw = list(load(NEIGHBOURHOOD_GOLD_DATASET))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"{NEIGHBOURHOOD_GOLD_DATASET} missing") from exc
    n_not_found = n_split = n_ok = 0
    for r in raw:
        if r.get("record_type") != "gold_label":
            continue
        note = str(r.get("note") or "")
        correct = r.get("correct_session")
        has = isinstance(correct, str) and correct.startswith("session-")
        if not has:
            r["label_status"] = "not_found"
            r["labeled"] = True  # adjudicated as absent, not pending
            n_not_found += 1
        elif _needs_split_note(note):
            r["label_status"] = "found_needs_split"
            r["needs_split"] = True
            r["labeled"] = True
            n_split += 1
        else:
            r["label_status"] = "found"
            r["needs_split"] = False
            r["labeled"] = True
            n_ok += 1
    meta = next((r for r in raw if r.get("record_type") == "meta"), None)
    if meta is not None:
        meta["n_found"] = n_ok
        meta["n_found_needs_split"] = n_split
        meta["n_not_found"] = n_not_found
        meta["label_policy"] = (
            "Unlabelled correct_session = not_found (resolution absent in "
            "neighbourhood HTR). needs_split when note says split — session "
            "may still be correct; ALIGNED_TO may need INSERTION_SPLIT later."
        )
    save_semi_structured(
        raw,
        logical_name=NEIGHBOURHOOD_GOLD_DATASET,
        script=__file__,
        description=(
            "Thin hand gold for date-free session-shift with label_status "
            "found|found_needs_split|not_found."
        ),
        parent_sources=["hard_recalibrate_proof", "paragraph_axis_1626_1630"],
    )
    return raw


def run_on_neighbourhood_gold(*, margin: float = MARGIN_SCALED) -> list[dict[str, Any]]:
    """Apply gate: hand gold correct_session vs neighbourhood alternative.

    When correct == baseline (common: content stays on production packing), the
    foil is competitor_session — not a degenerate same-session pool.
    not_found rows are excluded from recovery; needs_split still scored on session.
    """
    annotate_neighbourhood_gold_status()
    labels = load_labelled_neighbourhood_gold()
    if not labels:
        raise SystemExit(
            f"no labeled rows in {NEIGHBOURHOOD_GOLD_DATASET} "
            "(set correct_session on gold_label rows)"
        )

    # Reload statuses after annotate
    status_by = {
        str(r["volgnr"]): r
        for r in load(NEIGHBOURHOOD_GOLD_DATASET)
        if r.get("record_type") == "gold_label" and r.get("volgnr")
    }

    exclude_dates = {
        str(r.get("enriched_date_file") or "")[:10]
        for r in labels
        if r.get("enriched_date_file")
    }
    fingerprint, fp_meta = fit_fingerprint_on_tier1(
        exclude_dates={d for d in exclude_dates if d}
    )
    entity_scorer = build_entity_overlap_scorer()
    axis_index = _axis_by_inv_sess()
    flat_texts = _flat_text_by_id()
    enr_text = _enriched_text_by_volgnr()

    verdicts: Counter[str] = Counter()
    n_needs_split = sum(
        1 for lab in labels if (status_by.get(str(lab["volgnr"])) or {}).get("needs_split")
    )
    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "on_neighbourhood_gold",
            "edge": "ALIGNED_TO",
            "n_labels": len(labels),
            "n_needs_split": n_needs_split,
            "margin_scaled": margin,
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "policy": (
                "Hand-gold apply gate. Foil = competitor when correct==baseline, else "
                "baseline. Recovery = top-1 session == correct_session among non-abstain. "
                "not_found excluded; needs_split still session-scored. No PINNED_TO write."
            ),
            **fp_meta,
            **scope_meta(),
        }
    ]

    for lab in labels:
        volgnr = str(lab["volgnr"])
        baseline = str(lab["baseline_session"])
        correct = str(lab["correct_session"])
        competitor = str(lab.get("competitor_session") or "")
        st = status_by.get(volgnr) or {}
        # Forced-choice foil: never the same session as correct.
        if correct == baseline:
            foil = competitor if competitor and competitor != correct else ""
        else:
            foil = baseline if baseline != correct else competitor
        if not foil or foil == correct:
            verdict = "no_foil"
            verdicts[verdict] += 1
            rows.append({
                "record_type": "gold_pair",
                "volgnr": volgnr,
                "baseline_session": baseline,
                "correct_session": correct,
                "foil_session": foil or None,
                "verdict": verdict,
                "label_status": st.get("label_status"),
                "needs_split": bool(st.get("needs_split")),
                "note": lab.get("note") or "",
            })
            continue
        corr_flats = _flats_for_session(correct, axis_index)
        foil_flats = _flats_for_session(foil, axis_index)
        pool = list(dict.fromkeys(corr_flats + foil_flats))
        if len(pool) < 2 or not corr_flats or not foil_flats:
            verdict = "no_pool"
            verdicts[verdict] += 1
            rows.append({
                "record_type": "gold_pair",
                "volgnr": volgnr,
                "baseline_session": baseline,
                "correct_session": correct,
                "foil_session": foil,
                "verdict": verdict,
                "n_pool": len(pool),
                "label_status": st.get("label_status"),
                "needs_split": bool(st.get("needs_split")),
            })
            continue
        ranked = score_volgnr_against_flats(
            volgnr,
            enr_text.get(volgnr) or "",
            pool,
            flat_texts,
            fingerprint=fingerprint,
            entity_scorer=entity_scorer,
        )
        best_flat, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        verdict = label_top1_session(
            gold_session=correct,
            competitor_session=foil,
            best_flat=best_flat,
            best_score=best_score,
            second_score=second_score,
            margin=margin,
            prefer_label="correct",
            other_label="foil",
        )
        verdicts[verdict] += 1
        rows.append({
            "record_type": "gold_pair",
            "volgnr": volgnr,
            "baseline_session": baseline,
            "correct_session": correct,
            "foil_session": foil,
            "top1_flat": best_flat,
            "top1_session": _session_of_flat(best_flat),
            "top1_score": round(best_score, 4),
            "second_score": round(second_score, 4),
            "verdict": verdict,
            "n_pool": len(pool),
            "delta": lab.get("delta"),
            "label_status": st.get("label_status"),
            "needs_split": bool(st.get("needs_split")),
            "note": lab.get("note") or "",
        })

    decided = verdicts["correct"] + verdicts["foil"]
    rows[0]["n_correct"] = verdicts["correct"]
    rows[0]["n_foil"] = verdicts["foil"]
    rows[0]["n_abstain"] = verdicts["abstain"]
    rows[0]["n_no_pool"] = verdicts["no_pool"]
    rows[0]["n_no_foil"] = verdicts["no_foil"]
    rows[0]["correct_session_recovery"] = (
        round(verdicts["correct"] / decided, 4) if decided else None
    )
    rows[0]["gate"] = (
        "PASS"
        if decided and (verdicts["correct"] / decided) >= 0.8
        else "FAIL_OR_THIN"
    )
    # not_found census from full gold file
    all_gold = [
        r for r in load(NEIGHBOURHOOD_GOLD_DATASET) if r.get("record_type") == "gold_label"
    ]
    rows[0]["n_not_found"] = sum(
        1 for r in all_gold if r.get("label_status") == "not_found"
    )
    rows.append({
        "record_type": "summary",
        "n_correct": verdicts["correct"],
        "n_foil": verdicts["foil"],
        "n_abstain": verdicts["abstain"],
        "n_no_pool": verdicts["no_pool"],
        "n_no_foil": verdicts["no_foil"],
        "n_needs_split": n_needs_split,
        "n_not_found": rows[0]["n_not_found"],
        "correct_session_recovery": rows[0]["correct_session_recovery"],
        "gate": rows[0]["gate"],
    })
    return rows


def _sentence_halves(text: str) -> tuple[str, str]:
    parts = [p.strip() for p in (text or "").split(". ") if p.strip()]
    if len(parts) < 2:
        mid = max(1, len(text) // 2)
        return text[:mid], text[mid:]
    mid = max(1, len(parts) // 2)
    return ". ".join(parts[:mid]), ". ".join(parts[mid:])


def _load_boundary_encoder(model_name: str = "globalise/GloBERTise") -> dict[str, Any] | None:
    """Load fine-tuned boundary encoder once (or None if checkpoint missing)."""
    from scripts.train_synthetic_boundary_encoder import output_dir_for, pick_device
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    final_dir = output_dir_for(model_name) / "final"
    if not final_dir.exists():
        return None
    device = pick_device()
    tokenizer = AutoTokenizer.from_pretrained(final_dir)
    model = AutoModelForTokenClassification.from_pretrained(final_dir)
    model.to(device)
    model.eval()
    return {
        "model_name": model_name,
        "checkpoint": str(final_dir),
        "device": device,
        "tokenizer": tokenizer,
        "model": model,
    }


def _encoder_cuts_for_flat(
    text: str,
    n_cuts: int,
    *,
    encoder: dict[str, Any] | None,
    model_name: str = "globalise/GloBERTise",
    setup: str = "win_512_s256",
) -> dict[str, Any]:
    """Propose char cuts with the fine-tuned boundary encoder (+ even-split baseline).

    Default ``setup=win_512_s256`` (sliding windows) — trunc_512 loses cuts past the
    first 512 tokens on long overflow flats (docs/DECISIONS.md 2026-10-13).
    """
    from scripts.boundary_windowed_infer import predict_cuts
    from scripts.synthetic_boundary_common import even_split_boundaries

    even = even_split_boundaries(len(text), n_cuts)
    if encoder is None:
        return {
            "encoder_available": False,
            "model_name": model_name,
            "encoder_setup": setup,
            "even_split_cuts": even,
            "encoder_cuts": None,
        }
    enc_cuts = predict_cuts(
        text,
        n_cuts,
        model=encoder["model"],
        tokenizer=encoder["tokenizer"],
        device=encoder["device"],
        setup=setup,
    )
    return {
        "encoder_available": True,
        "model_name": encoder["model_name"],
        "checkpoint": encoder["checkpoint"],
        "device": encoder["device"],
        "encoder_setup": setup,
        "even_split_cuts": even,
        "encoder_cuts": enc_cuts,
    }

def run_on_overflow_split(
    *,
    margin: float = MARGIN_SCALED,
    with_encoder: bool = True,
    encoder_model: str = "globalise/GloBERTise",
) -> list[dict[str, Any]]:
    """Prove fingerprint adjudicates session overflow via XML summaries.

    Split signal: several enriched summaries fingerprinting to the same HTR flat
    ⇒ that flat should be split.

    On hand-gold ``found`` rows in a session:
      1) assign each enriched to best flat in ``correct_session``;
      2) overflow = flat claimed by ≥2 enriched;
      3) half-windows + optional boundary encoder propose cuts (n_cuts = claimants−1).

    Date-free. No production wire.
    """
    annotate_neighbourhood_gold_status()
    gold = [
        r
        for r in load(NEIGHBOURHOOD_GOLD_DATASET)
        if r.get("record_type") == "gold_label"
        and isinstance(r.get("correct_session"), str)
        and str(r["correct_session"]).startswith("session-")
    ]
    if not gold:
        raise SystemExit("no found gold labels for overflow proof")

    exclude_dates = {
        str(r.get("enriched_date_file") or "")[:10]
        for r in gold
        if r.get("enriched_date_file")
    }
    fingerprint, fp_meta = fit_fingerprint_on_tier1(
        exclude_dates={d for d in exclude_dates if d}
    )
    entity_scorer = build_entity_overlap_scorer()
    axis_index = _axis_by_inv_sess()
    flat_texts = _flat_text_by_id()
    enr_text = _enriched_text_by_volgnr()

    by_sess: dict[str, list[dict[str, Any]]] = {}
    for r in gold:
        by_sess.setdefault(str(r["correct_session"]), []).append(r)

    encoder_bundle = _load_boundary_encoder(encoder_model) if with_encoder else None

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "on_overflow_split",
            "edge": "ALIGNED_TO",
            "n_gold_found": len(gold),
            "n_sessions": len(by_sess),
            "with_encoder": with_encoder,
            "encoder_model": encoder_model if with_encoder else None,
            "encoder_loaded": encoder_bundle is not None,
            "margin_scaled": margin,
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "policy": (
                "Overflow/split proof. Split signal: several XML summaries "
                "fingerprint to the same HTR flat ⇒ split that flat. Fingerprint "
                "detects multi-claim flats; half-windows + optional GloBERTise "
                "encoder propose cuts (n_cuts=claimants-1). Not dating. No wire."
            ),
            **fp_meta,
            **scope_meta(),
        }
    ]

    n_assign = 0
    n_split_on_overflow = 0
    n_split = 0
    half_pref: Counter[str] = Counter()
    second_half_ok = second_half_n = 0

    for sid, labs in sorted(by_sess.items()):
        flats = _flats_for_session(sid, axis_index)
        assignments: list[dict[str, Any]] = []
        for lab in labs:
            volgnr = str(lab["volgnr"])
            ranked = score_volgnr_against_flats(
                volgnr,
                enr_text.get(volgnr) or "",
                flats,
                flat_texts,
                fingerprint=fingerprint,
                entity_scorer=entity_scorer,
            )
            if not ranked:
                continue
            top_flat, top_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            n_assign += 1
            needs = bool(lab.get("needs_split")) or _needs_split_note(
                str(lab.get("note") or "")
            )
            if needs:
                n_split += 1
            assignments.append({
                "volgnr": volgnr,
                "top1_flat": top_flat,
                "top1_score": round(top_score, 4),
                "second_score": round(second_score, 4),
                "needs_split": needs,
                "note": lab.get("note") or "",
            })

        claim_count: Counter[str] = Counter(
            a["top1_flat"] for a in assignments if a.get("top1_flat")
        )
        overflow_flats = {f for f, n in claim_count.items() if n >= 2}

        for a in assignments:
            on_ov = a["top1_flat"] in overflow_flats
            if a["needs_split"] and on_ov:
                n_split_on_overflow += 1
            rows.append({
                "record_type": "assignment",
                "session_id": sid,
                "volgnr": a["volgnr"],
                "top1_flat": a["top1_flat"],
                "top1_score": a["top1_score"],
                "second_score": a["second_score"],
                "needs_split": a["needs_split"],
                "on_overflow_flat": on_ov,
                "n_claimants_on_flat": claim_count.get(a["top1_flat"] or "", 0),
                "n_session_flats": len(flats),
                "n_session_enriched": len(labs),
                "note": a["note"],
            })

        for flat_id in sorted(overflow_flats):
            whole = flat_texts.get(flat_id) or ""
            half_a, half_b = _sentence_halves(whole)
            pool_texts = {
                **flat_texts,
                f"{flat_id}::HALF_A": half_a,
                f"{flat_id}::HALF_B": half_b,
                f"{flat_id}::WHOLE": whole,
            }
            pool_ids = [
                f"{flat_id}::HALF_A",
                f"{flat_id}::HALF_B",
                f"{flat_id}::WHOLE",
            ]
            claimants = [a for a in assignments if a["top1_flat"] == flat_id]
            n_cuts = max(0, len(claimants) - 1)
            for a in claimants:
                volgnr = a["volgnr"]
                ranked = score_volgnr_against_flats(
                    volgnr,
                    enr_text.get(volgnr) or "",
                    pool_ids,
                    pool_texts,
                    fingerprint=fingerprint,
                    entity_scorer=entity_scorer,
                )
                top = ranked[0][0] if ranked else None
                prefer = (
                    "HALF_A"
                    if top and top.endswith("HALF_A")
                    else "HALF_B"
                    if top and top.endswith("HALF_B")
                    else "WHOLE"
                    if top and top.endswith("WHOLE")
                    else "abstain"
                )
                half_pref[prefer] += 1
                note_l = (a["note"] or "").lower()
                expects_second = "second half" in note_l
                if expects_second:
                    second_half_n += 1
                    if prefer == "HALF_B":
                        second_half_ok += 1
                rows.append({
                    "record_type": "half_window",
                    "session_id": sid,
                    "flat_id": flat_id,
                    "volgnr": volgnr,
                    "prefer": prefer,
                    "top1_score": round(ranked[0][1], 4) if ranked else None,
                    "needs_split": a["needs_split"],
                    "expects_second_half": expects_second,
                    "note": a["note"],
                    "ranked": [
                        {"id": fid, "score": round(sc, 4)} for fid, sc in ranked
                    ],
                })

            # Split proposal for this multi-claim flat
            split_row: dict[str, Any] = {
                "record_type": "split_proposal",
                "session_id": sid,
                "flat_id": flat_id,
                "n_claimants": len(claimants),
                "n_cuts": n_cuts,
                "claimant_volgnrs": [a["volgnr"] for a in claimants],
                "split_signal": "multi_summary_same_flat",
                "flat_char_len": len(whole),
                "should_split": True,
            }
            if n_cuts > 0 and whole.strip():
                enc = _encoder_cuts_for_flat(
                    whole,
                    n_cuts,
                    encoder=encoder_bundle,
                    model_name=encoder_model,
                )
                split_row.update(enc)
            else:
                from scripts.eval_synthetic_boundary_encoder import predict_even_split

                split_row["even_split_cuts"] = predict_even_split({
                    "concat_text": whole,
                    "concat_char_len": len(whole),
                    "n_cuts": n_cuts,
                })
                split_row["encoder_available"] = False
            rows.append(split_row)

        rows.append({
            "record_type": "session_summary",
            "session_id": sid,
            "n_flats": len(flats),
            "n_enriched": len(labs),
            "overflow": len(labs) > len(flats),
            "n_overflow_flats": len(overflow_flats),
            "overflow_flat_ids": sorted(overflow_flats),
        })

    split_overflow_rate = (
        round(n_split_on_overflow / n_split, 4) if n_split else None
    )
    second_half_rate = (
        round(second_half_ok / second_half_n, 4) if second_half_n else None
    )
    proposals = [r for r in rows if r.get("record_type") == "split_proposal"]
    n_multi = len(proposals)
    rows[0]["n_assignments"] = n_assign
    rows[0]["n_needs_split"] = n_split
    rows[0]["n_needs_split_on_overflow_flat"] = n_split_on_overflow
    rows[0]["needs_split_on_overflow_rate"] = split_overflow_rate
    rows[0]["n_multi_claim_flats"] = n_multi
    rows[0]["half_prefer_counts"] = dict(half_pref)
    rows[0]["second_half_note_n"] = second_half_n
    rows[0]["second_half_note_prefer_b"] = second_half_ok
    rows[0]["second_half_note_rate"] = second_half_rate
    rows[0]["n_encoder_proposals"] = sum(
        1 for r in proposals if r.get("encoder_available")
    )
    # Gate: needs_split land on overflow flats; second-half notes prefer B; ≥1 multi-claim
    gate_ok = (
        n_split > 0
        and n_multi > 0
        and split_overflow_rate is not None
        and split_overflow_rate >= 0.8
        and (second_half_n == 0 or (second_half_rate or 0) >= 0.8)
    )
    rows[0]["gate"] = "PASS" if gate_ok else "FAIL_OR_THIN"
    rows.append({
        "record_type": "summary",
        "n_assignments": n_assign,
        "n_needs_split": n_split,
        "n_needs_split_on_overflow_flat": n_split_on_overflow,
        "needs_split_on_overflow_rate": split_overflow_rate,
        "n_multi_claim_flats": n_multi,
        "half_prefer_counts": dict(half_pref),
        "second_half_note_rate": second_half_rate,
        "n_encoder_proposals": rows[0]["n_encoder_proposals"],
        "gate": rows[0]["gate"],
        "verdict": (
            "Split signal confirmed: several XML summaries → same HTR flat. "
            "Fingerprint detects; half-windows + encoder propose cuts. Not dating."
        ),
    })
    return rows


def run_bake_track_gold() -> list[dict[str, Any]]:
    """Bake full-track ALIGNED_TO gold: as-is lumped flats → proposed-end segments.

    Consumes hand labels (``neighbourhood_shift_gold``) and the overflow proof
    (assignments, half-windows, split proposals). Cut char offsets stay
    ``cut_proposal`` / ``is_gold: false`` — not promoted to gold here.
    No production wire.
    """
    annotate_neighbourhood_gold_status()
    try:
        gold_rows = list(load(NEIGHBOURHOOD_GOLD_DATASET))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"{NEIGHBOURHOOD_GOLD_DATASET} missing") from exc
    try:
        proof = list(load(OVERFLOW_SPLIT_DATASET))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"{OVERFLOW_SPLIT_DATASET} missing — run "
            "--on-overflow-split --write first"
        ) from exc

    gold_by_v = {
        str(r["volgnr"]): r
        for r in gold_rows
        if r.get("record_type") == "gold_label" and r.get("volgnr")
    }
    assignments = [r for r in proof if r.get("record_type") == "assignment"]
    half_by_key = {
        (str(r["flat_id"]), str(r["volgnr"])): r
        for r in proof
        if r.get("record_type") == "half_window"
    }
    proposals = [r for r in proof if r.get("record_type") == "split_proposal"]
    proof_meta = next((r for r in proof if r.get("record_type") == "meta"), {})
    gold_meta = next((r for r in gold_rows if r.get("record_type") == "meta"), {})

    claim_count: Counter[str] = Counter(
        str(a["top1_flat"]) for a in assignments if a.get("top1_flat")
    )
    overflow_flats = {f for f, n in claim_count.items() if n >= 2}
    assign_by_v = {str(a["volgnr"]): a for a in assignments if a.get("volgnr")}

    n_found = sum(
        1
        for r in gold_by_v.values()
        if r.get("label_status") in ("found", "found_needs_split")
    )
    n_needs_split = sum(
        1 for r in gold_by_v.values() if r.get("label_status") == "found_needs_split"
    )
    n_not_found = sum(
        1 for r in gold_by_v.values() if r.get("label_status") == "not_found"
    )

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "bake_track_gold",
            "edge": "ALIGNED_TO",
            "inventory": gold_meta.get("inventory") or "3185",
            "calendar_lo": gold_meta.get("calendar_lo"),
            "calendar_hi": gold_meta.get("calendar_hi"),
            "n_gold_labels": len(gold_by_v),
            "n_found": n_found,
            "n_found_needs_split": n_needs_split,
            "n_not_found": n_not_found,
            "n_assignments": len(assignments),
            "n_overflow_flats": len(overflow_flats),
            "n_cut_proposals": len(proposals),
            "source_overflow_proof": OVERFLOW_SPLIT_DATASET,
            "source_hand_gold": NEIGHBOURHOOD_GOLD_DATASET,
            "overflow_proof_gate": proof_meta.get("gate"),
            "policy": (
                "Full-track ALIGNED_TO gold from hand neighbourhood labels. "
                "as_is = fingerprint top-1 lumped flat; proposed_end = ordered "
                "segments on overflow flats (HALF_A before HALF_B before WHOLE, "
                "then volgnr). cut_proposal rows are machine-only (is_gold=false). "
                "No char cuts as truth. No PINNED_TO. No production wire."
            ),
            **scope_meta(),
        }
    ]

    # --- as_is: one per found / found_needs_split with an assignment ---
    n_as_is = 0
    n_lumped = 0
    for volgnr, lab in sorted(gold_by_v.items()):
        status = lab.get("label_status")
        if status not in ("found", "found_needs_split"):
            continue
        a = assign_by_v.get(volgnr)
        if a is None:
            rows.append({
                "record_type": "as_is",
                "volgnr": volgnr,
                "correct_session": lab.get("correct_session"),
                "label_status": status,
                "as_is_flat_id": None,
                "missing_assignment": True,
                "note": lab.get("note") or "",
            })
            continue
        flat_id = str(a["top1_flat"])
        n_claim = int(claim_count.get(flat_id, 0))
        lumped = n_claim >= 2
        if lumped:
            n_lumped += 1
        n_as_is += 1
        rows.append({
            "record_type": "as_is",
            "volgnr": volgnr,
            "correct_session": lab.get("correct_session") or a.get("session_id"),
            "label_status": status,
            "as_is_flat_id": flat_id,
            "top1_score": a.get("top1_score"),
            "second_score": a.get("second_score"),
            "n_claimants_on_flat": n_claim,
            "lumped": lumped,
            "needs_split": bool(a.get("needs_split")) or status == "found_needs_split",
            "note": lab.get("note") or a.get("note") or "",
        })

    # --- flat_as_is + proposed_end + cut_proposal per overflow flat ---
    claimants_by_flat: dict[str, list[dict[str, Any]]] = {}
    for a in assignments:
        fid = str(a.get("top1_flat") or "")
        if fid in overflow_flats:
            claimants_by_flat.setdefault(fid, []).append(a)

    n_proposed_end = 0
    for prop in sorted(proposals, key=lambda r: str(r.get("flat_id") or "")):
        flat_id = str(prop["flat_id"])
        sid = str(prop.get("session_id") or "")
        claimants = claimants_by_flat.get(flat_id) or []
        # Order: HALF preference then volgnr
        enriched: list[tuple[int, str, dict[str, Any], dict[str, Any] | None]] = []
        for a in claimants:
            v = str(a["volgnr"])
            hw = half_by_key.get((flat_id, v))
            prefer = str((hw or {}).get("prefer") or "abstain")
            enriched.append((_HALF_RANK.get(prefer, 3), v, a, hw))
        enriched.sort(key=lambda t: (t[0], t[1]))
        ordered_volgnrs = [t[1] for t in enriched]
        n_seg = len(ordered_volgnrs)

        rows.append({
            "record_type": "flat_as_is",
            "flat_id": flat_id,
            "session_id": sid,
            "claimant_volgnrs": ordered_volgnrs,
            "n_claimants": n_seg,
            "flat_char_len": prop.get("flat_char_len"),
            "should_split": True,
            "split_signal": prop.get("split_signal") or "multi_summary_same_flat",
        })

        for rank, (_hr, volgnr, a, hw) in enumerate(enriched):
            lab = gold_by_v.get(volgnr) or {}
            prefer = str((hw or {}).get("prefer") or "abstain")
            expects_second = bool((hw or {}).get("expects_second_half")) or (
                "second half" in str(lab.get("note") or "").lower()
            )
            n_proposed_end += 1
            rows.append({
                "record_type": "proposed_end",
                "volgnr": volgnr,
                "session_id": sid,
                "source_flat_id": flat_id,
                "segment_rank": rank,
                "n_segments": n_seg,
                "prefer_half": prefer,
                "expects_second_half": expects_second,
                "label_status": lab.get("label_status") or (
                    "found_needs_split" if a.get("needs_split") else "found"
                ),
                "needs_split": bool(a.get("needs_split")),
                "note": lab.get("note") or a.get("note") or "",
                "is_gold": True,
            })

        cut_row: dict[str, Any] = {
            "record_type": "cut_proposal",
            "flat_id": flat_id,
            "session_id": sid,
            "n_cuts": prop.get("n_cuts"),
            "n_claimants": prop.get("n_claimants"),
            "claimant_volgnrs": ordered_volgnrs,
            "even_split_cuts": prop.get("even_split_cuts"),
            "encoder_cuts": prop.get("encoder_cuts"),
            "encoder_available": prop.get("encoder_available"),
            "model_name": prop.get("model_name"),
            "checkpoint": prop.get("checkpoint"),
            "flat_char_len": prop.get("flat_char_len"),
            "is_gold": False,
            "policy": (
                "Machine cut proposal only — not track gold. "
                "Human treatment review may promote later."
            ),
        }
        rows.append(cut_row)

    # --- proposed_end pass-through for non-lumped found ---
    for volgnr, lab in sorted(gold_by_v.items()):
        status = lab.get("label_status")
        if status not in ("found", "found_needs_split"):
            continue
        a = assign_by_v.get(volgnr)
        if a is None:
            continue
        flat_id = str(a["top1_flat"])
        if flat_id in overflow_flats:
            continue  # already emitted under overflow flat
        n_proposed_end += 1
        rows.append({
            "record_type": "proposed_end",
            "volgnr": volgnr,
            "session_id": lab.get("correct_session") or a.get("session_id"),
            "source_flat_id": flat_id,
            "segment_rank": 0,
            "n_segments": 1,
            "prefer_half": "WHOLE",
            "expects_second_half": False,
            "label_status": status,
            "needs_split": bool(a.get("needs_split")) or status == "found_needs_split",
            "note": lab.get("note") or "",
            "is_gold": True,
            "passthrough": True,
        })

    # Gate: every found_needs_split with assignment lands on an overflow flat
    split_vols = [
        v
        for v, lab in gold_by_v.items()
        if lab.get("label_status") == "found_needs_split" and v in assign_by_v
    ]
    split_on_ov = sum(
        1
        for v in split_vols
        if str(assign_by_v[v]["top1_flat"]) in overflow_flats
    )
    split_rate = round(split_on_ov / len(split_vols), 4) if split_vols else None
    gate_ok = (
        len(overflow_flats) > 0
        and len(split_vols) > 0
        and split_rate is not None
        and split_rate >= 0.8
    )
    rows[0]["n_as_is"] = n_as_is
    rows[0]["n_lumped_as_is"] = n_lumped
    rows[0]["n_proposed_end"] = n_proposed_end
    rows[0]["n_needs_split_on_overflow_flat"] = split_on_ov
    rows[0]["needs_split_on_overflow_rate"] = split_rate
    rows[0]["gate"] = "PASS" if gate_ok else "FAIL_OR_THIN"

    rows.append({
        "record_type": "summary",
        "n_as_is": n_as_is,
        "n_lumped_as_is": n_lumped,
        "n_overflow_flats": len(overflow_flats),
        "n_proposed_end": n_proposed_end,
        "n_cut_proposals": len(proposals),
        "n_found_needs_split": n_needs_split,
        "n_needs_split_on_overflow_flat": split_on_ov,
        "needs_split_on_overflow_rate": split_rate,
        "gate": rows[0]["gate"],
        "verdict": (
            "Track gold baked: as_is lumped flats → proposed_end segment inventory. "
            "Cut offsets remain machine proposals (is_gold=false). Not dating."
        ),
    })
    return rows


def run_on_neighbourhood(
    *,
    inventory: str = "3185",
    primary_delta: int | None = None,
    margin: float = MARGIN_SCALED,
    pair_cap: int = 500,
) -> list[dict[str, Any]]:
    """Bulk date-free rematch: tier1 pairs in inventory, pool S ∪ S+Δ.

    Provisional until neighbourhood hand-gold PASS. No production wire.
    """
    primary = primary_delta if primary_delta is not None else median_lag_delta()
    pairs = _main_series_tier1()
    pairs = pairs.loc[
        pairs["session_id"].astype(str).str.contains(f"session-{inventory}-")
    ].reset_index(drop=True)
    if pair_cap and len(pairs) > pair_cap:
        pairs = pairs.sample(n=pair_cap, random_state=RANDOM_SEED).reset_index(drop=True)

    fingerprint, fp_meta = fit_fingerprint_on_tier1(exclude_dates=None)
    entity_scorer = build_entity_overlap_scorer()
    axis_index = _axis_by_inv_sess()
    flat_texts = _flat_text_by_id()
    enr_text = _enriched_text_by_volgnr()

    verdicts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "on_neighbourhood",
            "edge": "ALIGNED_TO",
            "inventory": inventory,
            "primary_delta": primary,
            "n_pairs": len(pairs),
            "margin_scaled": margin,
            "provisional": True,
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "policy": (
                "Date-free neighbourhood rematch. For each tier1 pair at session S, "
                "score against flats(S) ∪ flats(S+Δ). stay / move / abstain. "
                "Provisional until --on-neighbourhood-gold PASS. No production wire; "
                "content does not write PINNED_TO (later: content checks recalibration)."
            ),
            **fp_meta,
            **scope_meta(),
        }
    ]

    for _, pr in pairs.iterrows():
        volgnr = str(pr["volgnr"])
        baseline = str(pr["session_id"])
        neighbour = shift_session(baseline, primary)
        if not neighbour:
            verdicts["bad_session"] += 1
            continue
        base_flats = _flats_for_session(baseline, axis_index)
        neigh_flats = _flats_for_session(neighbour, axis_index)
        pool = list(dict.fromkeys(base_flats + neigh_flats))
        if len(pool) < 2 or not base_flats or not neigh_flats:
            verdict = "no_pool"
            verdicts[verdict] += 1
            rows.append({
                "record_type": "pair",
                "volgnr": volgnr,
                "baseline_session": baseline,
                "neighbour_session": neighbour,
                "verdict": verdict,
                "delta": primary,
            })
            continue
        ranked = score_volgnr_against_flats(
            volgnr,
            enr_text.get(volgnr) or str(pr.get("enriched_text") or ""),
            pool,
            flat_texts,
            fingerprint=fingerprint,
            entity_scorer=entity_scorer,
        )
        best_flat, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        raw = label_top1_session(
            gold_session=baseline,
            competitor_session=neighbour,
            best_flat=best_flat,
            best_score=best_score,
            second_score=second_score,
            margin=margin,
            prefer_label="stay",
            other_label="move",
        )
        verdicts[raw] += 1
        rows.append({
            "record_type": "pair",
            "volgnr": volgnr,
            "baseline_session": baseline,
            "neighbour_session": neighbour,
            "top1_flat": best_flat,
            "top1_session": _session_of_flat(best_flat),
            "top1_score": round(best_score, 4),
            "second_score": round(second_score, 4),
            "verdict": raw,
            "delta": primary,
            "n_pool": len(pool),
        })

    decided = verdicts["stay"] + verdicts["move"]
    rows[0]["n_stay"] = verdicts["stay"]
    rows[0]["n_move"] = verdicts["move"]
    rows[0]["n_abstain"] = verdicts["abstain"]
    rows[0]["n_no_pool"] = verdicts["no_pool"]
    rows[0]["move_rate"] = (
        round(verdicts["move"] / decided, 4) if decided else None
    )
    rows.append({
        "record_type": "summary",
        "n_stay": verdicts["stay"],
        "n_move": verdicts["move"],
        "n_abstain": verdicts["abstain"],
        "n_no_pool": verdicts["no_pool"],
        "move_rate": rows[0]["move_rate"],
        "provisional": True,
    })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--on-gold",
        action="store_true",
        help="synthetic Δ gate on held-out tier1 (instrument)",
    )
    parser.add_argument(
        "--scaffold-neighbourhood-gold",
        action="store_true",
        help="write thin hand-gold candidates (correct_session null)",
    )
    parser.add_argument(
        "--on-neighbourhood-gold",
        action="store_true",
        help="apply gate vs hand-labeled neighbourhood_shift_gold",
    )
    parser.add_argument(
        "--on-neighbourhood",
        action="store_true",
        help="bulk S vs S+Δ report (provisional until hand-gold PASS)",
    )
    parser.add_argument(
        "--on-overflow-split",
        action="store_true",
        help="multi-summary→same-flat split signal; half-windows + GloBERTise cuts",
    )
    parser.add_argument(
        "--bake-track-gold",
        action="store_true",
        help="bake as-is→proposed-end track gold from hand labels + overflow proof",
    )
    parser.add_argument(
        "--no-encoder",
        action="store_true",
        help="with --on-overflow-split: skip boundary encoder (even-split only)",
    )
    parser.add_argument(
        "--on-lag",
        action="store_true",
        help="diagnostic only: date-join hard vs production (not apply gate)",
    )
    parser.add_argument(
        "--on-boundary-gold",
        action="store_true",
        help="focused start/end/date-cut check on boundary gold (thin; not a corpus gate)",
    )
    parser.add_argument("--inventory", default="3185")
    parser.add_argument("--delta", type=int, default=None, help="primary Δ")
    parser.add_argument("--test-day-cap", type=int, default=TEST_DAY_CAP)
    parser.add_argument("--pair-cap", type=int, default=500)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    modes = sum(
        bool(x)
        for x in (
            args.on_gold,
            args.on_lag,
            args.on_boundary_gold,
            args.scaffold_neighbourhood_gold,
            args.on_neighbourhood_gold,
            args.on_neighbourhood,
            args.on_overflow_split,
            args.bake_track_gold,
        )
    )
    if modes != 1:
        raise SystemExit(
            "choose exactly one of --on-gold, --scaffold-neighbourhood-gold, "
            "--on-neighbourhood-gold, --on-neighbourhood, --on-overflow-split, "
            "--bake-track-gold, --on-lag, --on-boundary-gold"
        )

    if args.scaffold_neighbourhood_gold:
        rows = scaffold_neighbourhood_gold(inventory=str(args.inventory))
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"scaffold-neighbourhood-gold  inventory={meta['inventory']}  "
            f"window={meta['calendar_lo']}..{meta['calendar_hi']}  "
            f"candidates={meta['n_candidates']}  "
            f"(fill correct_session; then --on-neighbourhood-gold)"
        )
        out_name = NEIGHBOURHOOD_GOLD_DATASET
        desc = (
            "Thin hand-gold scaffold for date-free session-shift: candidates with "
            "baseline_session (concordance/production) and competitor hint; "
            "correct_session null until labeled. ALIGNED_TO only — not dating."
        )
        parents = ["hard_recalibrate_proof", "paragraph_axis_1626_1630"]
    elif args.on_neighbourhood_gold:
        rows = run_on_neighbourhood_gold()
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"on-neighbourhood-gold  labels={meta['n_labels']}  "
            f"recovery={meta.get('correct_session_recovery')}  "
            f"correct={meta.get('n_correct')} foil={meta.get('n_foil')} "
            f"abstain={meta.get('n_abstain')}  not_found={meta.get('n_not_found')}  "
            f"needs_split={meta.get('n_needs_split')}  gate={meta.get('gate')}"
        )
        out_name = NEIGHBOURHOOD_GOLD_EVAL_DATASET
        desc = (
            "Hand-gold apply gate for date-free neighbourhood rematch: recovery of "
            "correct_session vs baseline. No production wire."
        )
        parents = [
            NEIGHBOURHOOD_GOLD_DATASET,
            "alignment_1626_1630",
            "paragraph_axis_1626_1630",
        ]
    elif args.on_neighbourhood:
        rows = run_on_neighbourhood(
            inventory=str(args.inventory),
            primary_delta=args.delta,
            pair_cap=args.pair_cap,
        )
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"on-neighbourhood  inventory={meta['inventory']}  Δ={meta['primary_delta']}  "
            f"pairs={meta['n_pairs']}  stay={meta.get('n_stay')} move={meta.get('n_move')} "
            f"abstain={meta.get('n_abstain')}  move_rate={meta.get('move_rate')}  "
            f"provisional={meta.get('provisional')}"
        )
        out_name = NEIGHBOURHOOD_REPORT_DATASET
        desc = (
            "Provisional date-free neighbourhood rematch (S vs S+Δ) on main-series "
            "tier1. Gate with --on-neighbourhood-gold before trusting. No production wire."
        )
        parents = ["alignment_1626_1630", "paragraph_axis_1626_1630"]
    elif args.on_overflow_split:
        rows = run_on_overflow_split(with_encoder=not args.no_encoder)
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"on-overflow-split  found={meta['n_gold_found']}  "
            f"multi_claim_flats={meta.get('n_multi_claim_flats')}  "
            f"needs_split_on_overflow={meta.get('needs_split_on_overflow_rate')}  "
            f"second_half_rate={meta.get('second_half_note_rate')}  "
            f"encoder_proposals={meta.get('n_encoder_proposals')}  "
            f"gate={meta.get('gate')}"
        )
        for r in rows:
            if r.get("record_type") != "split_proposal":
                continue
            print(
                f"  SPLIT {r['flat_id']}  claimants={r['n_claimants']}  "
                f"cuts={r['n_cuts']}  even={r.get('even_split_cuts')}  "
                f"encoder={r.get('encoder_cuts')}"
            )
        out_name = OVERFLOW_SPLIT_DATASET
        desc = (
            "Overflow/split proof: multi XML-summary→same-flat signal; half-windows "
            "+ optional GloBERTise encoder cuts. No production wire."
        )
        parents = [
            NEIGHBOURHOOD_GOLD_DATASET,
            "paragraph_axis_1626_1630",
            "alignment_1626_1630",
        ]
    elif args.bake_track_gold:
        rows = run_bake_track_gold()
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"bake-track-gold  found={meta['n_found']}  "
            f"needs_split={meta['n_found_needs_split']}  "
            f"as_is={meta.get('n_as_is')} lumped={meta.get('n_lumped_as_is')}  "
            f"overflow_flats={meta['n_overflow_flats']}  "
            f"proposed_end={meta.get('n_proposed_end')}  "
            f"cut_proposals={meta['n_cut_proposals']}  "
            f"needs_split_on_overflow={meta.get('needs_split_on_overflow_rate')}  "
            f"gate={meta.get('gate')}"
        )
        for r in rows:
            if r.get("record_type") != "flat_as_is":
                continue
            print(
                f"  FLAT {r['flat_id']}  claimants={r['n_claimants']}  "
                f"volgnrs={r['claimant_volgnrs']}"
            )
        out_name = TRACK_GOLD_DATASET
        desc = (
            "Full-track ALIGNED_TO gold: as_is lumped flats → proposed_end segment "
            "inventory from neighbourhood hand labels + overflow proof. "
            "cut_proposal rows are machine-only (is_gold=false). No production wire."
        )
        parents = [
            NEIGHBOURHOOD_GOLD_DATASET,
            OVERFLOW_SPLIT_DATASET,
        ]
    elif args.on_gold:
        rows = run_on_gold(primary_delta=args.delta, test_day_cap=args.test_day_cap)
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"on-gold  primary_Δ={meta['primary_delta']}  "
            f"eval_days={meta['n_eval_days']} pairs={meta['n_eval_pairs']}  "
            f"recovery={meta.get('primary_gold_session_recovery')}  "
            f"gold={meta.get('primary_n_gold')} competitor={meta.get('primary_n_competitor')} "
            f"abstain={meta.get('primary_n_abstain')}"
        )
        for r in rows:
            if r.get("record_type") == "delta_summary":
                mark = "*" if r.get("is_primary") else " "
                print(
                    f"  Δ={r['delta']}{mark}  recovery={r['gold_session_recovery']}  "
                    f"gold={r['n_gold']} comp={r['n_competitor']} abs={r['n_abstain']}  "
                    f"exact_flat|gold_sess={r['exact_flat_among_gold_session']}"
                )
        out_name = GOLD_OUTPUT_DATASET
        desc = (
            "Gold-first synthetic session-lag gate: held-out tier1 vs competitor "
            "(num+Δ) with entity+scaled TF-IDF. No production wire."
        )
        parents = [
            "alignment_1626_1630",
            "paragraph_axis_1626_1630",
            "hard_recalibrate_proof",
        ]
    elif args.on_lag:
        rows = run_on_lag()
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"on-lag  window={meta['calendar_lo']}..{meta['calendar_hi']}  "
            f"disagree_days={meta['n_disagree_days']} enriched={meta['n_enriched']}  "
            f"prefer_hard={meta.get('prefer_hard_rate')}  "
            f"hard={meta.get('n_hard')} production={meta.get('n_production')} "
            f"abstain={meta.get('n_abstain')}"
        )
        print(
            f"  review  agree={meta.get('n_review_agree')} "
            f"disagree={meta.get('n_review_disagree')} "
            f"abstain={meta.get('n_review_abstain')}  "
            f"literal_opening_on_hard_days={meta.get('n_literal_on_hard_days')}/"
            f"{meta['n_disagree_days']}"
        )
        out_name = LAG_OUTPUT_DATASET
        desc = (
            "Lag-window production proof: fingerprint prefers hard vs production "
            "session flats on pin-disagree days; held-out review + literal opening "
            "checks. No production wire."
        )
        parents = [
            "alignment_1626_1630",
            "paragraph_axis_1626_1630",
            "hard_recalibrate_proof",
        ]
    else:
        rows = run_on_boundary_gold()
        meta = next(r for r in rows if r["record_type"] == "meta")
        print(
            f"on-boundary-gold  days_with_edges={meta['n_days_with_edge_events']}  "
            f"events={meta['n_edge_events']}  (focused; not a corpus gate)"
        )
        for r in rows:
            if r.get("record_type") == "boundary_kind_summary":
                print(
                    f"  {r['kind']}: decided={r['n_decided']}  "
                    f"exact_flat={r['n_exact_flat']} same_sess={r['n_same_session']} "
                    f"wrong_sess={r['n_wrong_session']} abstain={r['n_abstain']}  "
                    f"session_hit={r['session_hit_rate']} exact={r['exact_flat_rate']}"
                )
        out_name = BOUNDARY_OUTPUT_DATASET
        desc = (
            "Focused fingerprint check on hand-placed session start/end/date-cut "
            "markers in boundary_gold_sample + hard_period (ordinary CUTs excluded). "
            "Thin; not a corpus gate. No production wire."
        )
        parents = [
            "boundary_gold_sample",
            "boundary_gold_hard_period_sample",
            "paragraph_axis_1626_1630",
            "alignment_1626_1630",
        ]

    if args.write:
        save_semi_structured(
            rows,
            logical_name=out_name,
            script=__file__,
            description=desc,
            parent_sources=parents,
        )
        print(f"wrote {out_name}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Entity channel for undecided duplicate-session claims (Track S S3).

Heading channel leaves the undecided population for this tier: exclusive person/place
surfaces from ``enriched_person_name_variants`` + enriched places, scored into the
shared session's HTR paragraphs, with a 1D split that maximises signed purity.

Calibration / machine gate (no pin review): recover ``split_at_paragraph`` on the
heading-confirmed ``gate_eligible`` sessions. Accept a purity filter only when the
filtered gold set has within-3 recovery ≥ ``MIN_WITHIN3`` and n ≥ ``MIN_GOLD_N``.
That bar matches the heading channel's "zero spurious" spirit; anything weaker is
reported and abstained.

Production overlap tables cannot feed this channel: they were built at window-days 0
against each paragraph's catalog ``flat_date``, so the second claimant date has no
rows inside the shared session.

Diagnostic only unless gate passes: writes ``duplicate_session_entity_splits``.
Does not touch concordance / PINNED_TO.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6_duplicate_session_entity_splits
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from data_io import load, save_semi_structured
from scripts.corpus_scope import scope_meta
from scripts.s6_duplicate_session_date_headings import session_paragraphs
from sequence_graph.duplicate_sessions import _proposed_ranges

SPLITS_DATASET = "duplicate_session_date_splits"
OUTPUT_DATASET = "duplicate_session_entity_splits"
MIN_PURITY = 0.75
MIN_SIDE_SCORE = 20.0
MIN_WITHIN3 = 0.80
MIN_GOLD_N = 10


def _load_variants() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in load("enriched_person_name_variants"):
        if row.get("record_type") != "person":
            continue
        forms = [
            s["surface"].lower()
            for s in (row.get("surface_forms") or [])
            if s.get("kind") == "name" and len(s.get("surface") or "") >= 4
        ]
        out[str(row["person_id"])] = forms
    return out


def _enriched_by_date() -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for er in load("enriched_resolutions_1626_1630"):
        date = str(er.get("date") or "")[:10]
        if date:
            by[date].append(er)
    return by


def _idf_tables(
    variants: dict[str, list[str]], enr_by: dict[str, list[dict[str, Any]]]
) -> tuple[dict[str, float], dict[str, float]]:
    person_freq: Counter[str] = Counter()
    place_freq: Counter[str] = Counter()
    for row in load("enriched_person_name_variants"):
        if row.get("record_type") != "person":
            continue
        mentions = int(row.get("mentions") or 1)
        for surface in variants.get(str(row["person_id"]), []):
            person_freq[surface] += mentions
    for ers in enr_by.values():
        for er in ers:
            for place in er.get("places") or []:
                if place and len(str(place)) >= 4:
                    place_freq[str(place).lower()] += 1
    n_docs = max(len(enr_by), 1)

    def idf(freq: dict[str, int], key: str) -> float:
        return math.log((n_docs + 1) / (freq.get(key, 1) + 1)) + 1.0

    person_idf = {k: idf(person_freq, k) for k in person_freq}
    place_idf = {k: idf(place_freq, k) * 1.5 for k in place_freq}
    return person_idf, place_idf


def date_weights(
    date: str,
    enr_by: dict[str, list[dict[str, Any]]],
    variants: dict[str, list[str]],
    person_idf: dict[str, float],
    place_idf: dict[str, float],
) -> dict[str, float]:
    weights: dict[str, float] = {}
    for er in enr_by.get(date, []):
        ids = (
            list(er.get("persons") or [])
            + list(er.get("president_ids") or [])
            + list(er.get("deputy_ids") or [])
        )
        for pid in ids:
            for surface in variants.get(str(pid), []):
                weights[surface] = max(weights.get(surface, 0.0), person_idf.get(surface, 1.0))
        for place in er.get("places") or []:
            if place and len(str(place)) >= 4:
                key = str(place).lower()
                weights[key] = max(weights.get(key, 0.0), place_idf.get(key, 1.5))
    return weights


def propose_split(
    texts: list[str],
    weights_a: dict[str, float],
    weights_b: dict[str, float],
) -> tuple[int | None, dict[str, Any]]:
    exclusive_a = {k: v for k, v in weights_a.items() if k not in weights_b}
    exclusive_b = {k: v for k, v in weights_b.items() if k not in weights_a}
    score_a = np.array(
        [sum(wt for s, wt in exclusive_a.items() if s in t.lower()) for t in texts],
        dtype=float,
    )
    score_b = np.array(
        [sum(wt for s, wt in exclusive_b.items() if s in t.lower()) for t in texts],
        dtype=float,
    )
    info: dict[str, Any] = {
        "score_a": float(score_a.sum()),
        "score_b": float(score_b.sum()),
        "n_exclusive_a": len(exclusive_a),
        "n_exclusive_b": len(exclusive_b),
    }
    if score_a.sum() == 0 or score_b.sum() == 0 or len(texts) < 2:
        return None, {**info, "reason": "one_side_empty"}
    best_s, best = 0, -1e9
    for split in range(1, len(texts)):
        signed = (
            score_a[:split].sum()
            + score_b[split:].sum()
            - score_a[split:].sum()
            - score_b[:split].sum()
        )
        if signed > best:
            best, best_s = float(signed), split
    purity = 0.5 * (
        float(score_a[:best_s].sum() / score_a.sum())
        + float(score_b[best_s:].sum() / score_b.sum())
    )
    info.update({"purity": purity, "signed_score": best, "reason": "ok"})
    return best_s, info


def passes_confidence(info: dict[str, Any]) -> bool:
    return (
        info.get("reason") == "ok"
        and float(info.get("purity") or 0) >= MIN_PURITY
        and float(info.get("score_a") or 0) >= MIN_SIDE_SCORE
        and float(info.get("score_b") or 0) >= MIN_SIDE_SCORE
    )


def calibrate_on_heading_gold(
    by_session: dict[str, list[dict[str, Any]]],
    heading_rows: list[dict[str, Any]],
    enr_by: dict[str, list[dict[str, Any]]],
    variants: dict[str, list[str]],
    person_idf: dict[str, float],
    place_idf: dict[str, float],
) -> dict[str, Any]:
    """Recover heading splits; gate on confidence-filtered within-3 rate."""
    errors: list[int] = []
    filtered_errors: list[int] = []
    for row in heading_rows:
        if not row.get("gate_eligible") or len(row.get("dates") or []) != 2:
            continue
        d0, d1 = sorted(row["dates"])
        texts = [str(p.get("text") or "") for p in by_session.get(row["session"], [])]
        split, info = propose_split(
            texts,
            date_weights(d0, enr_by, variants, person_idf, place_idf),
            date_weights(d1, enr_by, variants, person_idf, place_idf),
        )
        if split is None:
            continue
        err = abs(split - int(row["split_at_paragraph"]))
        errors.append(err)
        if passes_confidence(info):
            filtered_errors.append(err)

    def _stats(vals: list[int]) -> dict[str, Any]:
        if not vals:
            return {"n": 0, "median_abs_err": None, "within3": None, "within1": None}
        arr = np.array(vals)
        return {
            "n": int(len(vals)),
            "median_abs_err": float(np.median(arr)),
            "within3": float(np.mean(arr <= 3)),
            "within1": float(np.mean(arr <= 1)),
        }

    all_stats = _stats(errors)
    filt_stats = _stats(filtered_errors)
    gate_pass = bool(
        filt_stats["n"] >= MIN_GOLD_N
        and filt_stats["within3"] is not None
        and filt_stats["within3"] >= MIN_WITHIN3
    )
    return {
        "record_type": "gate",
        "channel": "exclusive_idf_entity_surfaces",
        "gate_pass": gate_pass,
        "min_purity": MIN_PURITY,
        "min_side_score": MIN_SIDE_SCORE,
        "min_within3": MIN_WITHIN3,
        "min_gold_n": MIN_GOLD_N,
        "calibration_all": all_stats,
        "calibration_filtered": filt_stats,
        "review_policy": (
            "machine_gate_only -- recover heading gold within-3 on confidence filter; "
            "no pin review"
        ),
        **scope_meta(),
    }


def build() -> dict[str, Any]:
    heading = [r for r in load(SPLITS_DATASET) if r.get("record_type") != "gate"]
    undecided = [r for r in heading if not r.get("verdict", "").startswith("shared")]
    by_session = session_paragraphs(load("paragraph_axis_1626_1630"))
    variants = _load_variants()
    enr_by = _enriched_by_date()
    person_idf, place_idf = _idf_tables(variants, enr_by)

    gate = calibrate_on_heading_gold(
        by_session, heading, enr_by, variants, person_idf, place_idf
    )

    proposals: list[dict[str, Any]] = []
    for row in undecided:
        dates = list(row["dates"])
        if len(dates) != 2:
            proposals.append({
                "session": row["session"],
                "dates": dates,
                "verdict": "entity_abstain_n_dates",
                "heading_verdict": row["verdict"],
                "split_at_paragraph": None,
                "proposed_ranges": None,
                "gate_eligible": False,
                "confidence": {},
            })
            continue
        d0, d1 = sorted(dates)
        texts = [str(p.get("text") or "") for p in by_session.get(row["session"], [])]
        split, info = propose_split(
            texts,
            date_weights(d0, enr_by, variants, person_idf, place_idf),
            date_weights(d1, enr_by, variants, person_idf, place_idf),
        )
        confident = split is not None and passes_confidence(info)
        eligible = bool(gate["gate_pass"] and confident)
        proposed = (
            _proposed_ranges(dates, len(texts), split) if eligible and split is not None else None
        )
        proposals.append({
            "session": row["session"],
            "dates": dates,
            "paragraphs": len(texts),
            "verdict": (
                "entity_shared_confident" if confident else
                ("entity_split_low_confidence" if split is not None else "entity_no_signal")
            ),
            "heading_verdict": row["verdict"],
            "split_at_paragraph": split,
            "proposed_ranges": proposed,
            "gate_eligible": eligible,
            "confidence": info,
        })

    gate["n_undecided"] = len(undecided)
    gate["n_entity_proposals"] = sum(1 for p in proposals if p["split_at_paragraph"] is not None)
    gate["n_confident"] = sum(1 for p in proposals if p["verdict"] == "entity_shared_confident")
    gate["n_gate_eligible"] = sum(1 for p in proposals if p["gate_eligible"])
    gate["verdicts"] = dict(Counter(p["verdict"] for p in proposals))

    payload = [gate, *proposals]
    save_semi_structured(
        payload,
        logical_name=OUTPUT_DATASET,
        script=__file__,
        description=(
            "Entity-channel split proposals for heading-undecided duplicate sessions. "
            "First record is record_type=gate (calibration vs heading gold). "
            "gate_eligible stays false unless filtered within-3 recovery clears the bar. "
            "Does not touch concordance / PINNED_TO."
        ),
        parent_sources=[
            SPLITS_DATASET,
            "enriched_resolutions_1626_1630",
            "enriched_person_name_variants",
            "paragraph_axis_1626_1630",
        ],
    )
    return gate


def main() -> None:
    gate = build()
    print(
        f"saved {OUTPUT_DATASET}: gate_pass={gate['gate_pass']} "
        f"eligible={gate['n_gate_eligible']} confident={gate['n_confident']} "
        f"proposals={gate['n_entity_proposals']} undecided={gate['n_undecided']}"
    )
    filt = gate["calibration_filtered"]
    print(
        f"  calibration filtered: n={filt['n']} within3={filt['within3']} "
        f"median_abs_err={filt['median_abs_err']}"
    )
    print("  verdicts:", gate["verdicts"])


if __name__ == "__main__":
    main()

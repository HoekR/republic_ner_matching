#!/usr/bin/env python3
"""Step 1 of plans/SHORT_RESOLUTION_SIDE_PLAN.md — freeze the experiment split.

Builds a leakage-safe sample manifest of HTR candidate units for the
short-resolution LLM alignment side track. Split unit is the session-day
(calendar date). No LLM calls; deterministic signals only.

Usage:
    uv run python scripts/build_short_resolution_llm_sample.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from align_short_resolutions import (
    CLOSE_WINDOW,
    OPEN_WINDOW,
    RESOLUTION_ID_RE,
    SHORT_TEXT_CHAR_LIMIT,
    build_formula_searchers,
    classify_enriched,
)
from data_io import load, save_semi_structured

OUTPUT_DATASET = "short_resolution_llm_sample_manifest"
PARENT_SOURCES = [
    "enriched_resolutions_1626_1630",
    "resolutions_flat",
    "alignment_1626_1630",
    "boundary_gold_sample",
]

RANDOM_SEED = 42
TARGET_CANDIDATES = 80
SHORT_HTR_CHAR_LIMIT = 400
YEAR_START = "1626-01-01"
YEAR_END = "1630-12-31"

# Day quotas before candidate thinning (boundary-gold days are forced into test).
SPLIT_DAY_QUOTAS = {"train": 14, "dev": 8, "test": 10}

SESSION_SORT_RE = re.compile(
    r"session-(?P<inventory>\d+)-num-(?P<num>\d+)-resolution-(?P<order>\d+)$"
)


def date_str(value: Any) -> str | None:
    raw = str(value or "")[:10]
    if len(raw) == 10 and raw.startswith("16"):
        return raw
    return None


def enriched_id_of(resolution: dict[str, Any]) -> str:
    volgnr = resolution.get("volgnr")
    if volgnr is not None and str(volgnr).strip() and str(volgnr).lower() != "none":
        return str(volgnr).strip()
    file_name = resolution.get("file") or "unknown"
    return f"{file_name}::{resolution.get('resolution_index')}"


def parse_flat_id(flat_id: str) -> dict[str, Any]:
    match = SESSION_SORT_RE.match(flat_id) or RESOLUTION_ID_RE.match(flat_id)
    if not match:
        return {
            "session_key": flat_id,
            "inventory": "",
            "session_num": 0,
            "order": 0,
        }
    groups = match.groupdict()
    session_key = (
        f"session-{groups['inventory']}-num-{groups['num']}"
        if "inventory" in groups
        else groups.get("session") or flat_id
    )
    return {
        "session_key": session_key,
        "inventory": groups.get("inventory") or "",
        "session_num": int(groups["num"]) if groups.get("num") else 0,
        "order": int(groups["order"]),
    }


def length_class(text_len: int, limit: int) -> str:
    return "short" if 0 < text_len < limit else "long"


def day_segmentation_class(k_e: int, k_f: int) -> str:
    if k_e == k_f:
        return "matched_count"
    if k_f < k_e:
        return "under_segmented"
    return "over_segmented"


def position_stratum(htr_length: str, is_session_initial: bool) -> str:
    position = "initial" if is_session_initial else "non_initial"
    return f"{htr_length}_{position}"


def composite_stratum(row: dict[str, Any]) -> str:
    return "|".join(
        [
            row["position_stratum"],
            row["enriched_class"],
            row["day_segmentation"],
            row["anchor_class"],
            "spillover" if row["possible_spillover"] else "no_spillover",
        ]
    )


def formula_scores(
    text: str,
    opener: Any,
    closer: Any,
) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    open_matches = opener.find_matches({"id": "x", "text": text[:OPEN_WINDOW]})
    if not open_matches:
        return None, None
    open_score = max(match.levenshtein_similarity for match in open_matches)
    open_end = max(match.end for match in open_matches)
    close_matches = closer.find_matches(
        {"id": "x", "text": text[open_end : open_end + CLOSE_WINDOW]}
    )
    if not close_matches:
        return open_score, None
    close_score = max(match.levenshtein_similarity for match in close_matches)
    return open_score, close_score


def load_windowed_flat() -> pd.DataFrame:
    flat = load("resolutions_flat")
    dates = flat["date"].astype(str).str[:10]
    mask = (dates >= YEAR_START) & (dates <= YEAR_END)
    out = flat.loc[mask].copy()
    out["date_str"] = out["date"].astype(str).str[:10]
    out["resolutions_text"] = out["resolutions_text"].fillna("").astype(str)
    parsed = out["id"].astype(str).map(parse_flat_id)
    out["session_key"] = parsed.map(lambda p: p["session_key"])
    out["inventory"] = parsed.map(lambda p: p["inventory"])
    out["session_num"] = parsed.map(lambda p: p["session_num"])
    out["order"] = parsed.map(lambda p: p["order"])
    out["htr_text_len"] = out["resolutions_text"].str.len()
    return out.sort_values(
        ["date_str", "inventory", "session_num", "order", "id"],
        kind="mergesort",
    ).reset_index(drop=True)


def load_enriched_by_date() -> dict[str, list[dict[str, Any]]]:
    enriched = load("enriched_resolutions_1626_1630")
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for resolution in enriched:
        day = date_str(resolution.get("date"))
        if not day or day < YEAR_START or day > YEAR_END:
            continue
        reason = classify_enriched(resolution)
        text = resolution.get("text") or ""
        by_date[day].append(
            {
                "enriched_id": enriched_id_of(resolution),
                "resolution_index": int(resolution.get("resolution_index") or 0),
                "text_len": len(text),
                "enriched_reason": reason,
                "enriched_class": (
                    "short_no_decision" if reason else "substantive"
                ),
            }
        )
    for day, rows in by_date.items():
        rows.sort(key=lambda row: row["resolution_index"])
    return by_date


def alignment_by_flat_id(alignment: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Prefer the strongest deterministic alignment row per flat HTR id."""
    tier_rank = {
        "tier1_anchor": 0,
        "tier2_interpolated": 1,
        "tier2_adjacent": 2,
        "tier2_merged_page": 3,
        "tier3_head_template": 4,
        "tier3_tail": 5,
    }
    work = alignment.copy()
    work["flat_id"] = work["flat_id"].astype(str)
    work["date"] = work["date"].astype(str).str[:10]
    work["tier_rank"] = work["confidence_tier"].map(lambda t: tier_rank.get(str(t), 9))
    work["overlap_score_num"] = pd.to_numeric(work["overlap_score"], errors="coerce").fillna(0.0)
    work = work.sort_values(
        ["tier_rank", "overlap_score_num"], ascending=[True, False], kind="mergesort"
    )
    best: dict[str, dict[str, Any]] = {}
    for row in work.itertuples(index=False):
        flat_id = str(row.flat_id)
        if flat_id in best:
            continue
        best[flat_id] = {
            "enriched_id": str(row.enriched_id),
            "confidence_tier": str(row.confidence_tier),
            "overlap_score": float(row.overlap_score_num),
            "match_kind": str(getattr(row, "match_kind", "") or ""),
        }
    return best


def build_day_candidates(
    flat_day: pd.DataFrame,
    enriched_day: list[dict[str, Any]],
    alignment_lookup: dict[str, dict[str, Any]],
    opener: Any,
    closer: Any,
    boundary_gold_dates: set[str],
) -> list[dict[str, Any]]:
    if flat_day.empty or not enriched_day:
        return []

    date = str(flat_day.iloc[0]["date_str"])
    k_e = len(enriched_day)
    k_f = len(flat_day)
    segmentation = day_segmentation_class(k_e, k_f)
    min_order_by_session = (
        flat_day.groupby("session_key", sort=False)["order"].transform("min")
    )

    rows: list[dict[str, Any]] = []
    for day_position, (_, flat_row) in enumerate(flat_day.iterrows()):
        flat_id = str(flat_row["id"])
        text = str(flat_row["resolutions_text"])
        text_len = int(flat_row["htr_text_len"])
        open_score, close_score = formula_scores(text, opener, closer)
        htr_len_class = length_class(text_len, SHORT_HTR_CHAR_LIMIT)
        # Formula receipt/no-decision also counts as short for the pilot strata.
        if open_score is not None and close_score is not None:
            htr_len_class = "short"
        is_session_initial = int(flat_row["order"]) == int(min_order_by_session.iloc[day_position])

        aligned = alignment_lookup.get(flat_id)
        paired_enriched = (
            enriched_day[day_position] if day_position < len(enriched_day) else None
        )
        if aligned is not None:
            enriched_id = aligned["enriched_id"]
            enriched_meta = next(
                (e for e in enriched_day if e["enriched_id"] == enriched_id),
                paired_enriched,
            )
            confidence_tier = aligned["confidence_tier"]
            overlap_score = aligned["overlap_score"]
            match_kind = aligned["match_kind"]
        else:
            enriched_meta = paired_enriched
            enriched_id = enriched_meta["enriched_id"] if enriched_meta else ""
            confidence_tier = ""
            overlap_score = None
            match_kind = ""

        if enriched_meta is None:
            enriched_class = "unpaired"
            enriched_reason = None
            enriched_text_len = None
        else:
            enriched_class = enriched_meta["enriched_class"]
            enriched_reason = enriched_meta["enriched_reason"]
            enriched_text_len = enriched_meta["text_len"]

        anchor_class = (
            "strong_tier1"
            if confidence_tier == "tier1_anchor"
            else "weak_or_none"
        )
        possible_spillover = bool(
            segmentation == "under_segmented"
            and (
                text_len >= SHORT_HTR_CHAR_LIMIT
                or (open_score is not None and close_score is None)
                or confidence_tier in {"tier2_merged_page", "tier2_adjacent"}
            )
        )
        possible_continuation = bool(
            (not is_session_initial)
            and (
                confidence_tier in {"tier2_adjacent", "tier2_merged_page"}
                or match_kind in {"adjacent", "merged_page"}
            )
        )

        row = {
            "record_type": "candidate",
            "session_day": date,
            "enriched_id": enriched_id,
            "htr_id": flat_id,
            "session_key": str(flat_row["session_key"]),
            "session_order": int(flat_row["order"]),
            "day_position": day_position,
            "is_session_initial": is_session_initial,
            "htr_text_len": text_len,
            "enriched_text_len": enriched_text_len,
            "htr_length_class": htr_len_class,
            "position_stratum": position_stratum(htr_len_class, is_session_initial),
            "enriched_class": enriched_class,
            "enriched_reason": enriched_reason,
            "day_segmentation": segmentation,
            "k_e": k_e,
            "k_f": k_f,
            "counts_matched": k_e == k_f,
            "anchor_class": anchor_class,
            "alignment_confidence_tier": confidence_tier or None,
            "alignment_overlap_score": overlap_score,
            "alignment_match_kind": match_kind or None,
            "formula_open_score": open_score,
            "formula_close_score": close_score,
            "possible_spillover": possible_spillover,
            "possible_continuation": possible_continuation,
            "is_boundary_gold_day": date in boundary_gold_dates,
        }
        row["stratum"] = composite_stratum(row)
        rows.append(row)
    return rows


def assert_split_gate(candidates: list[dict[str, Any]]) -> None:
    days_by_split: dict[str, set[str]] = defaultdict(set)
    for row in candidates:
        days_by_split[row["split"]].add(row["session_day"])

    overlaps = []
    splits = sorted(days_by_split)
    for i, left in enumerate(splits):
        for right in splits[i + 1 :]:
            shared = days_by_split[left] & days_by_split[right]
            if shared:
                overlaps.append((left, right, sorted(shared)[:5]))
    if overlaps:
        raise RuntimeError(f"Session-day leakage across splits: {overlaps}")

    short_initial = sum(1 for row in candidates if row["position_stratum"] == "short_initial")
    short_non_initial = sum(
        1 for row in candidates if row["position_stratum"] == "short_non_initial"
    )
    if short_initial == 0 or short_non_initial == 0:
        raise RuntimeError(
            "Gate failed: sample cannot distinguish positional from semantic effects "
            f"(short_initial={short_initial}, short_non_initial={short_non_initial})."
        )


def prioritize_key(row: dict[str, Any]) -> tuple[int, int, str, int]:
    """Prefer short-initial / short-non-initial balance, then weak-anchor / spillover."""
    preference = {
        "short_initial": 0,
        "short_non_initial": 1,
        "long_initial": 2,
        "long_non_initial": 3,
    }
    return (
        preference.get(row["position_stratum"], 9),
        0 if row["anchor_class"] == "weak_or_none" else 1,
        row["session_day"],
        row["day_position"],
    )


def select_days(
    all_candidates: list[dict[str, Any]],
    boundary_gold_dates: set[str],
    rng: Any,
) -> dict[str, str]:
    """Map session_day -> split. Boundary-gold days are forced into test."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_candidates:
        by_day[row["session_day"]].append(row)

    def day_has_stratum(day: str, stratum: str) -> bool:
        return any(row["position_stratum"] == stratum for row in by_day[day])

    eligible_days = sorted(
        day
        for day, rows in by_day.items()
        if any(row["position_stratum"].startswith("short_") for row in rows)
    )

    gold_test = sorted(day for day in eligible_days if day in boundary_gold_dates)
    non_gold = [day for day in eligible_days if day not in boundary_gold_dates]

    # Ensure both short-initial and short-non-initial days exist outside gold if possible.
    short_initial_days = [d for d in non_gold if day_has_stratum(d, "short_initial")]
    short_non_initial_days = [
        d for d in non_gold if day_has_stratum(d, "short_non_initial")
    ]
    rng.shuffle(short_initial_days)
    rng.shuffle(short_non_initial_days)
    rng.shuffle(non_gold)

    assignment: dict[str, str] = {day: "test" for day in gold_test}

    def take(pool: list[str], n: int, split: str) -> None:
        needed = n
        for day in pool:
            if needed <= 0:
                break
            if day in assignment:
                continue
            assignment[day] = split
            needed -= 1

    # Seed each split with both position strata before filling quotas.
    for split, quota in SPLIT_DAY_QUOTAS.items():
        seed_n = max(1, quota // 4)
        take(short_initial_days, seed_n, split)
        take(short_non_initial_days, seed_n, split)

    remaining_test_slots = max(0, SPLIT_DAY_QUOTAS["test"] - sum(1 for s in assignment.values() if s == "test"))
    take(non_gold, remaining_test_slots, "test")
    take(non_gold, SPLIT_DAY_QUOTAS["dev"], "dev")
    take(non_gold, SPLIT_DAY_QUOTAS["train"], "train")

    # If train/dev still short, borrow more non-gold days.
    for split in ("train", "dev", "test"):
        have = sum(1 for s in assignment.values() if s == split)
        take(non_gold, max(0, SPLIT_DAY_QUOTAS[split] - have), split)

    return assignment


def select_candidates(
    all_candidates: list[dict[str, Any]],
    day_split: dict[str, str],
) -> list[dict[str, Any]]:
    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_candidates:
        split = day_split.get(row["session_day"])
        if not split:
            continue
        item = dict(row)
        item["split"] = split
        by_split[split].append(item)

    # Aim for roughly even candidate counts, with short strata preferred.
    per_split_target = {
        "train": max(24, TARGET_CANDIDATES // 2),
        "dev": max(16, TARGET_CANDIDATES // 4),
        "test": max(16, TARGET_CANDIDATES - (TARGET_CANDIDATES // 2) - (TARGET_CANDIDATES // 4)),
    }

    selected: list[dict[str, Any]] = []
    for split, target in per_split_target.items():
        pool = sorted(by_split.get(split, []), key=prioritize_key)
        # Round-robin across position strata so short-non-initial cannot be starved.
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in pool:
            buckets[row["position_stratum"]].append(row)
        order = [
            "short_initial",
            "short_non_initial",
            "long_initial",
            "long_non_initial",
        ]
        picked: list[dict[str, Any]] = []
        while len(picked) < target and any(buckets[name] for name in order):
            for name in order:
                if len(picked) >= target:
                    break
                if buckets[name]:
                    picked.append(buckets[name].pop(0))
        selected.extend(picked)

    selected.sort(key=lambda row: (row["split"], row["session_day"], row["day_position"]))
    return selected


def build_manifest_meta(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    split_days = defaultdict(set)
    for row in candidates:
        split_days[row["split"]].add(row["session_day"])
    return {
        "record_type": "manifest_meta",
        "random_seed": RANDOM_SEED,
        "target_candidates": TARGET_CANDIDATES,
        "short_htr_char_limit": SHORT_HTR_CHAR_LIMIT,
        "short_enriched_char_limit": SHORT_TEXT_CHAR_LIMIT,
        "n_candidates": len(candidates),
        "n_session_days": len({row["session_day"] for row in candidates}),
        "split_day_counts": {k: len(v) for k, v in sorted(split_days.items())},
        "split_candidate_counts": dict(Counter(row["split"] for row in candidates)),
        "position_stratum_counts": dict(Counter(row["position_stratum"] for row in candidates)),
        "boundary_gold_days_in_test": sorted(
            {
                row["session_day"]
                for row in candidates
                if row["is_boundary_gold_day"] and row["split"] == "test"
            }
        ),
        "gate": {
            "no_session_day_leakage": True,
            "short_initial": sum(
                1 for row in candidates if row["position_stratum"] == "short_initial"
            ),
            "short_non_initial": sum(
                1 for row in candidates if row["position_stratum"] == "short_non_initial"
            ),
        },
    }


def main() -> None:
    import random

    rng = random.Random(RANDOM_SEED)
    opener, closer = build_formula_searchers()

    gold = load("boundary_gold_sample")
    boundary_gold_dates = {str(day["date"])[:10] for day in gold.get("days", [])}

    print("Loading enriched / flat / alignment …")
    enriched_by_date = load_enriched_by_date()
    flat = load_windowed_flat()
    alignment_lookup = alignment_by_flat_id(load("alignment_1626_1630"))

    all_candidates: list[dict[str, Any]] = []
    for date, flat_day in flat.groupby("date_str", sort=True):
        enriched_day = enriched_by_date.get(str(date), [])
        all_candidates.extend(
            build_day_candidates(
                flat_day,
                enriched_day,
                alignment_lookup,
                opener,
                closer,
                boundary_gold_dates,
            )
        )
    print(f"Built {len(all_candidates)} HTR candidate rows over {flat['date_str'].nunique()} days")

    day_split = select_days(all_candidates, boundary_gold_dates, rng)
    selected = select_candidates(all_candidates, day_split)
    assert_split_gate(selected)

    meta = build_manifest_meta(selected)
    output_rows = [meta, *selected]
    path = save_semi_structured(
        output_rows,
        logical_name=OUTPUT_DATASET,
        parent_sources=PARENT_SOURCES,
        description=(
            "Frozen train/dev/test sample manifest for the short-resolution LLM "
            "alignment side plan (session-day split; HTR candidates with strata "
            "and deterministic signals)."
        ),
        script=__file__,
    )

    print(f"Wrote {len(selected)} candidates (+ meta) to {path}")
    print("split days:", meta["split_day_counts"])
    print("split candidates:", meta["split_candidate_counts"])
    print("position strata:", meta["position_stratum_counts"])
    print(
        "gate ok: short_initial="
        f"{meta['gate']['short_initial']}, short_non_initial={meta['gate']['short_non_initial']}"
    )


if __name__ == "__main__":
    main()

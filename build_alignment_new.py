#!/usr/bin/env python3
"""Generate alignment preview, stratified ground truth, and verification HTML.

This script executes the anchor-based sequence matching pipeline to perfectly 
align enriched and flat resolutions chronologically. It uses pre-calculated 
Excel overlap files to establish immovable anchors and bypasses raw text extraction.

Usage:
    uv run python build_alignment_new.py
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from generate_alignment.build_alignment_artifacts import write_verification_html


MatchKind = Literal["both", "places_only", "orgs_only", "none"]


ROOT = Path(__file__).resolve().parent
DATADIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

ENRICHED_FILE = DATADIR / "enriched_resolutions_1626_1630_complete.json"
RESOLUTIONS_FILE = DATADIR / "resolutions_flat.parquet"
LOC_ENTITIES_FILE = DATADIR / "LOC-entities.json"
PER_ENTITIES_FILE = DATADIR / "PER-entities.json"
ORG_ENTITIES_FILE = DATADIR / "ORG-entities.json"
LOC_ANNOTATIONS_FILE = DATADIR / "LOC-annotations.json"
ORG_ANNOTATIONS_FILE = DATADIR / "ORG-annotations.json"
PLACE_OVERLAP_FILE = DATADIR / "place_overlap_1626_1630.xlsx"
ORG_OVERLAP_FILE = DATADIR / "org_overlap_1626_1630.xlsx"
PER_OVERLAP_FILE = DATADIR / "per_overlap_1626_1630.xlsx"

PERSON_SIGNAL_SCALE = 0.2

SESSION_ID_PATTERN = re.compile(r"(session-\d+)")
NO_ANCHOR_DIAG_SCORE = -1e9
DEFAULT_MIN_OVERLAP_SCORE = 2.0


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_entity_names(path: Path) -> dict[str, str]:
    entities = load_json(path)
    return {
        str(item.get("id")): str(item.get("name", ""))
        for item in entities
        if item.get("id") and item.get("name")
    }


def load_data() -> tuple[list[dict[str, Any]], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, dict, dict]:
    print("Loading data files...")
    enriched_all = load_json(ENRICHED_FILE)
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    
    # Pre-process dates and session ids for grouping
    res_df["date_str"] = res_df["date"].astype(str).str[:10]
    res_df["session_id"] = res_df["id"].astype(str).str.extract(SESSION_ID_PATTERN, expand=False)

    # Load canonical names for preview purposes
    loc_names = load_entity_names(LOC_ENTITIES_FILE)
    per_names = load_entity_names(PER_ENTITIES_FILE)
    org_names = load_entity_names(ORG_ENTITIES_FILE)

    print("Loading overlap matrices (Excel)...")
    places_df = pd.read_excel(PLACE_OVERLAP_FILE)
    orgs_df = pd.read_excel(ORG_OVERLAP_FILE)

    print(f"✓ Loaded {len(enriched_all)} enriched resolutions")
    print(f"✓ Loaded {len(res_df)} flat resolutions")
    print(f"✓ Loaded {len(places_df)} place overlaps and {len(orgs_df)} org overlaps")
    
    return enriched_all, res_df, places_df, orgs_df, loc_names, per_names, org_names


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value)


def candidate_text(candidate: pd.Series) -> str:
    text = candidate.get("resolutions_text")
    if not text or str(text) == "nan":
        text = candidate.get("paragraph_texts")
    if not text or str(text) == "nan":
        text = candidate.get("paragraph_text")
    return as_text(text)


def enriched_text(enriched: dict[str, Any]) -> str:
    return as_text(enriched.get("text"))


def enriched_volgnr(enriched: dict[str, Any]) -> str | None:
    """Return the enriched resolution key used in overlap spreadsheets."""
    volgnr = enriched.get("volgnr")
    if volgnr is not None and str(volgnr).strip() and str(volgnr).lower() != "none":
        return str(volgnr).strip()

    date_raw = str(enriched.get("date", ""))[:10]
    resolution_index = enriched.get("resolution_index")
    if len(date_raw) == 10 and resolution_index is not None:
        return f"{date_raw}_{int(resolution_index)}"
    return None


def build_paragraph_to_resolution_map(
    annotation_files: list[Path],
    paragraph_ids: set[str],
) -> dict[str, str]:
    """Map HTR paragraph ids to flat resolution ids via annotation references."""
    mapping: dict[str, str] = {}
    remaining = set(paragraph_ids)
    for path in annotation_files:
        if not remaining:
            break
        if not path.exists():
            print(f"⚠ Annotation file not found, skipping: {path}")
            continue
        print(f"Indexing paragraph ids from {path.name}...")
        for item in load_json(path):
            ref = item.get("reference") or {}
            paragraph_id = ref.get("paragraph_id")
            resolution_id = ref.get("resolution_id")
            if paragraph_id is None or resolution_id is None:
                continue
            paragraph_key = str(paragraph_id).strip()
            if paragraph_key not in remaining:
                continue
            mapping[paragraph_key] = str(resolution_id).strip()
            remaining.discard(paragraph_key)

    if remaining:
        print(f"⚠ Could not resolve {len(remaining)} paragraph_ids to flat resolution ids")
    print(f"✓ Resolved {len(mapping)} paragraph_ids to flat resolution ids")
    return mapping


def resolve_enriched_entities(
    enriched: dict[str, Any],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
) -> dict[str, list[str]]:
    places = [loc_names.get(str(item), str(item)) for item in enriched.get("places", []) if item]
    persons = [per_names.get(str(item), str(item)) for item in enriched.get("persons", []) if item]
    orgs_raw = enriched.get("organizations") or enriched.get("institutions") or []
    orgs = [org_names.get(str(item), str(item)) for item in orgs_raw if item]
    return {"places": places, "persons": persons, "orgs": orgs}


def matched_entity_names(names: list[str], flat_text: str) -> list[str]:
    flat_text_lower = flat_text.lower()
    return [name for name in names if name and name.lower() in flat_text_lower]


def classify_match_kind(shared_places: set[str], shared_orgs: set[str]) -> MatchKind:
    has_places = bool(shared_places)
    has_orgs = bool(shared_orgs)
    if has_places and has_orgs:
        return "both"
    if has_places:
        return "places_only"
    if has_orgs:
        return "orgs_only"
    return "none"


def match_kind_label(match_kind: MatchKind) -> str:
    return {
        "both": "Places + orgs",
        "places_only": "Places only",
        "orgs_only": "Organizations only",
        "none": "No entity anchor",
    }[match_kind]


def build_overlap_lookups(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    persons_df: pd.DataFrame | None = None,
) -> tuple[
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
]:
    """Build place-only, org-only, person-only, and combined Excel overlap lookups."""
    place_lookup: dict[tuple[str, str], set[str]] = {}
    org_lookup: dict[tuple[str, str], set[str]] = {}
    person_lookup: dict[tuple[str, str], set[str]] = {}
    combined_lookup: dict[tuple[str, str], set[str]] = {}

    for source_df, target_lookup in (
        (places_df, place_lookup),
        (orgs_df, org_lookup),
    ):
        for _, row in source_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]) or pd.isna(row["name"]):
                continue
            volgnr = str(row["volgnr"]).strip()
            paragraph_id = str(row["paragraph_id"]).strip()
            flat_id = paragraph_to_resolution.get(paragraph_id)
            if not flat_id:
                continue
            pair = (volgnr, flat_id)
            entity_name = str(row["name"]).strip()
            target_lookup.setdefault(pair, set()).add(entity_name)
            combined_lookup.setdefault(pair, set()).add(entity_name)

    if persons_df is not None and not persons_df.empty:
        for _, row in persons_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]) or pd.isna(row["name"]):
                continue
            volgnr = str(row["volgnr"]).strip()
            paragraph_id = str(row["paragraph_id"]).strip()
            flat_id = paragraph_to_resolution.get(paragraph_id)
            if not flat_id:
                continue
            pair = (volgnr, flat_id)
            entity_name = str(row["name"]).strip()
            person_lookup.setdefault(pair, set()).add(entity_name)
            combined_lookup.setdefault(pair, set()).add(entity_name)

    return place_lookup, org_lookup, person_lookup, combined_lookup


def extract_session_id(flat_id: str) -> str | None:
    match = SESSION_ID_PATTERN.search(flat_id)
    return match.group(1) if match else None


def build_date_to_session_map(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
) -> dict[str, set[str]]:
    """Map enriched calendar dates to flat HTR session blocks via Excel anchors."""
    date_to_sessions: dict[str, set[str]] = {}
    for source_df in (places_df, orgs_df):
        for _, row in source_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]):
                continue
            volgnr = str(row["volgnr"]).strip()
            if len(volgnr) < 10:
                continue
            date_str = volgnr[:10]
            paragraph_id = str(row["paragraph_id"]).strip()
            flat_id = paragraph_to_resolution.get(paragraph_id)
            if not flat_id:
                continue
            session_id = extract_session_id(flat_id)
            if session_id:
                date_to_sessions.setdefault(date_str, set()).add(session_id)
    return date_to_sessions


def select_flat_candidates(
    res_df: pd.DataFrame,
    current_date: str,
    enriched_period: pd.Period,
    date_to_session_map: dict[str, set[str]],
    date_window_days: int,
    session_first: bool,
) -> tuple[pd.DataFrame, str]:
    """Return flat resolutions for alignment and a short label describing pool logic."""
    if session_first:
        mapped_sessions = date_to_session_map.get(current_date)
        if mapped_sessions:
            pool = res_df[res_df["session_id"].isin(mapped_sessions)].copy()
            return pool, f"session({len(mapped_sessions)})"

    if date_window_days > 0:
        pool = res_df[
            (res_df["date_period"] >= enriched_period - date_window_days)
            & (res_df["date_period"] <= enriched_period + date_window_days)
        ].copy()
        return pool, f"window±{date_window_days}"

    pool = res_df[res_df["date_str"] == current_date].copy()
    return pool, "same-day"


def pair_key_from_alignment(match: dict[str, Any]) -> tuple[str, str]:
    return (
        enriched_volgnr(match["enriched"]) or "",
        str(match["flat_record"]["id"]),
    )


def evaluate_against_labeled(
    alignments: list[dict[str, Any]],
    labeled_path: Path,
) -> None:
    """Backtest proposed pairs against prior manual verdicts, if available."""
    if not labeled_path.exists():
        return

    labeled = load_json(labeled_path)
    if not isinstance(labeled, list):
        return

    verdict_by_pair: dict[tuple[str, str], str] = {}
    for record in labeled:
        verdict = record.get("verdict")
        if not verdict:
            continue
        verdict_by_pair[(str(record.get("enriched_id", "")), str(record.get("flat_id", "")))] = str(verdict)

    if not verdict_by_pair:
        return

    proposed = {pair_key_from_alignment(match) for match in alignments}
    proposed_both = {
        pair_key_from_alignment(match)
        for match in alignments
        if match.get("match_kind") == "both"
    }
    judged_pairs = set(verdict_by_pair)
    still_proposed = judged_pairs & proposed
    still_proposed_both = judged_pairs & proposed_both
    dropped = judged_pairs - proposed

    retained_correct = sum(1 for key in still_proposed if verdict_by_pair[key] == "correct")
    retained_fp = sum(1 for key in still_proposed if verdict_by_pair[key] == "false_positive")
    dropped_correct = sum(1 for key in dropped if verdict_by_pair[key] == "correct")
    dropped_fp = sum(1 for key in dropped if verdict_by_pair[key] == "false_positive")

    precision = retained_correct / len(still_proposed) if still_proposed else 0.0
    both_correct = sum(1 for key in still_proposed_both if verdict_by_pair[key] == "correct")
    both_fp = sum(1 for key in still_proposed_both if verdict_by_pair[key] == "false_positive")
    both_precision = both_correct / len(still_proposed_both) if still_proposed_both else 0.0
    print("\n📊 Backtest vs prior manual labels")
    print(f"   Judged pairs in reference: {len(judged_pairs)}")
    print(f"   Still proposed: {len(still_proposed)} (correct {retained_correct}, FP {retained_fp})")
    print(f"   Dropped: {len(dropped)} (correct {dropped_correct}, FP {dropped_fp})")
    print(f"   Precision on retained judged pairs: {precision:.1%}")
    print(
        f"   Both-kind retained: {len(still_proposed_both)} "
        f"(correct {both_correct}, FP {both_fp}, precision {both_precision:.1%})"
    )


def period_from_date(value: Any) -> pd.Period | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return pd.Period(str(value)[:10], freq="D")
    except (TypeError, ValueError):
        return None


def date_diff_days(left: pd.Period | None, right: pd.Period | None) -> int | None:
    if left is None or right is None:
        return None
    return abs((left - right).n)


def resolve_shared_entities(
    enriched: dict[str, Any],
    flat_record: pd.Series,
    pair_key: tuple[str, str],
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    date_window_days: int,
) -> dict[str, Any]:
    shared_places_excel = set(place_lookup.get(pair_key, set()))
    shared_orgs_excel = set(org_lookup.get(pair_key, set()))
    flat_text = candidate_text(flat_record)
    resolved = resolve_enriched_entities(enriched, loc_names, per_names, org_names)

    shared_places_text = set(matched_entity_names(resolved["places"], flat_text))
    shared_orgs_text = set(matched_entity_names(resolved["orgs"], flat_text))

    enriched_period = period_from_date(enriched.get("date"))
    flat_period = period_from_date(flat_record.get("date_str") or flat_record.get("date"))
    day_gap = date_diff_days(enriched_period, flat_period)
    is_same_day = day_gap == 0 if day_gap is not None else False
    allow_text_fallback = date_window_days > 0 and not is_same_day

    if allow_text_fallback:
        shared_places = shared_places_excel or shared_places_text
        shared_orgs = shared_orgs_excel or shared_orgs_text
        evidence_source = "excel+text" if (shared_places_text or shared_orgs_text) and not (shared_places_excel or shared_orgs_excel) else "excel"
    else:
        shared_places = shared_places_excel
        shared_orgs = shared_orgs_excel
        evidence_source = "excel"

    shared_entities = shared_places | shared_orgs
    match_kind = classify_match_kind(shared_places, shared_orgs)
    return {
        "shared_places": shared_places,
        "shared_orgs": shared_orgs,
        "shared_places_excel": shared_places_excel,
        "shared_orgs_excel": shared_orgs_excel,
        "shared_places_text": shared_places_text,
        "shared_orgs_text": shared_orgs_text,
        "shared_entities": shared_entities,
        "match_kind": match_kind,
        "evidence_source": evidence_source,
        "enriched_period": enriched_period,
        "flat_period": flat_period,
        "date_diff_days": day_gap,
        "is_same_day": is_same_day,
        "enriched_entities": resolved,
    }


# --- ALIGNMENT MATHEMATICS ---

def calculate_idf_weights(all_overlaps_df: pd.DataFrame) -> dict[str, float]:
    """Calculates IDF weight for overlapping entities based on their frequency."""
    names = all_overlaps_df['name'].dropna().astype(str).str.strip().tolist()
    total_docs = len(all_overlaps_df)
    counts = Counter(names)
    return {ent: math.log(total_docs / count) for ent, count in counts.items() if count > 0}


def score_typed_overlap(
    enriched_id: str,
    target_id: str,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    person_signal_scale: float = PERSON_SIGNAL_SCALE,
) -> tuple[float, float, float]:
    """Return anchor (place+org), person, and combined IDF-weighted scores."""
    pair = (enriched_id, target_id)
    anchor_entities = place_lookup.get(pair, set()) | org_lookup.get(pair, set())
    person_entities = person_lookup.get(pair, set())
    anchor_score = sum(idf_weights.get(entity, 1.0) for entity in anchor_entities)
    person_score = person_signal_scale * sum(
        idf_weights.get(entity, 1.0) for entity in person_entities
    )
    return anchor_score, person_score, anchor_score + person_score


def align_session(
    enriched_ids: list[str], 
    flat_ids: list[str], 
    overlap_lookup: dict[tuple[str, str], set[str]], 
    idf_weights: dict[str, float], 
    gap_penalty: float = 0.1,
    anchor_only_diagonal: bool = True,
) -> list[tuple]:
    """Needleman-Wunsch sequence alignment using pre-calculated Excel overlap anchors."""
    n = len(enriched_ids)
    m = len(flat_ids)
    
    dp = np.zeros((n + 1, m + 1))
    tb = np.zeros((n + 1, m + 1), dtype=int) 
    
    for i in range(1, n + 1):
        dp[i][0] = dp[i-1][0] - gap_penalty
        tb[i][0] = 2
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j-1] - gap_penalty
        tb[0][j] = 3
        
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            e_id = enriched_ids[i-1]
            f_id = flat_ids[j-1]
            
            shared_entities = overlap_lookup.get((e_id, f_id), set())
            match_score = sum(idf_weights.get(e, 1.0) for e in shared_entities)
            
            if anchor_only_diagonal and match_score == 0:
                diag = NO_ANCHOR_DIAG_SCORE
            else:
                diag = dp[i-1][j-1] + match_score
            up = dp[i-1][j] - gap_penalty
            left = dp[i][j-1] - gap_penalty
            
            best = max(diag, up, left)
            dp[i][j] = best
            
            if best == diag:
                tb[i][j] = 1
            elif best == up:
                tb[i][j] = 2
            else:
                tb[i][j] = 3
                
    i, j = n, m
    alignments = []
    while i > 0 or j > 0:
        if tb[i][j] == 1:
            alignments.append((i-1, j-1))
            i -= 1
            j -= 1
        elif tb[i][j] == 2:
            alignments.append((i-1, None))
            i -= 1
        else:
            alignments.append((None, j-1))
            j -= 1
            
    return alignments[::-1]


def build_stratified_verification_sample(
    alignments: list[dict[str, Any]],
    sample_size: int,
    seed: int = 9673,
    min_overlap_score: float = 0.0,
    verification_match_kind: str = "both",
) -> list[dict[str, Any]]:
    """Prefer anchored pairs, stratified by month and place/org match kind."""
    anchored = [
        item for item in alignments
        if not item["is_gap_fill"] and item["overlap_score"] >= min_overlap_score
    ]
    if verification_match_kind == "both":
        anchored = [item for item in anchored if item.get("match_kind") == "both"]
    elif verification_match_kind == "not_places_only":
        anchored = [item for item in anchored if item.get("match_kind") != "places_only"]
    pool = anchored if anchored else alignments
    if not pool or sample_size <= 0:
        return []

    ranked = sorted(pool, key=lambda item: (-item["overlap_score"], item.get("date", "")))
    by_bucket: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in ranked:
        month = str(item.get("date", ""))[:7]
        by_bucket[(month, item.get("match_kind", "none"))].append(item)

    months = sorted({month for month, _ in by_bucket})
    kinds = ["both", "places_only", "orgs_only"]
    target_per_bucket = max(1, sample_size // max(1, len(months) * len(kinds)))
    chosen: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for month in months:
        for kind in kinds:
            for item in by_bucket.get((month, kind), [])[:target_per_bucket]:
                key = (enriched_volgnr(item["enriched"]) or "", str(item["flat_record"]["id"]))
                if key in seen_keys:
                    continue
                chosen.append(item)
                seen_keys.add(key)
                if len(chosen) >= sample_size:
                    break
            if len(chosen) >= sample_size:
                break
        if len(chosen) >= sample_size:
            break

    if len(chosen) < sample_size:
        for item in ranked:
            key = (enriched_volgnr(item["enriched"]) or "", str(item["flat_record"]["id"]))
            if key in seen_keys:
                continue
            chosen.append(item)
            seen_keys.add(key)
            if len(chosen) >= sample_size:
                break

    random.seed(seed)
    random.shuffle(chosen)
    return chosen[:sample_size]


def export_ground_truth_records(
    alignments: list[dict[str, Any]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    ground_truth: list[dict[str, Any]] = []
    aggregate_counts = {
        "places": {"enriched": 0, "found_in_flat": 0},
        "persons": {"enriched": 0, "found_in_flat": 0},
        "organizations": {"enriched": 0, "found_in_flat": 0},
    }

    for sample_id, match in enumerate(alignments, 1):
        enriched = match["enriched"]
        flat = match["flat_record"]
        enriched_entities = match["enriched_entities"]
        flat_text = candidate_text(flat)

        found_places = sorted(match["shared_places"])
        found_orgs = sorted(match["shared_orgs"])
        found_persons = matched_entity_names(enriched_entities["persons"], flat_text)

        aggregate_counts["places"]["enriched"] += len(enriched_entities["places"])
        aggregate_counts["places"]["found_in_flat"] += len(found_places)
        aggregate_counts["persons"]["enriched"] += len(enriched_entities["persons"])
        aggregate_counts["persons"]["found_in_flat"] += len(found_persons)
        aggregate_counts["organizations"]["enriched"] += len(enriched_entities["orgs"])
        aggregate_counts["organizations"]["found_in_flat"] += len(found_orgs)

        is_summary_anchor = match["match_kind"] == "both" and match["is_same_day"]
        ground_truth.append(
            {
                "sample_id": sample_id,
                "enriched_id": enriched_volgnr(enriched),
                "flat_id": str(flat["id"]),
                "enriched_date": str(enriched.get("date", ""))[:10],
                "flat_date": str(match["flat_period"]) if match.get("flat_period") is not None else str(flat.get("date", ""))[:10],
                "date_diff_days": match.get("date_diff_days"),
                "is_same_day": match.get("is_same_day", False),
                "is_summary_anchor": is_summary_anchor,
                "match_kind": match.get("match_kind", "none"),
                "evidence_source": match.get("evidence_source", "excel"),
                "confidence_score": match.get("overlap_score", 0.0),
                "entities": {
                    "places": {
                        "enriched": enriched_entities["places"],
                        "found_in_flat": found_places,
                        "matched_count": len(found_places),
                        "total_in_enriched": len(enriched_entities["places"]),
                    },
                    "persons": {
                        "enriched": enriched_entities["persons"],
                        "found_in_flat": found_persons,
                        "matched_count": len(found_persons),
                        "total_in_enriched": len(enriched_entities["persons"]),
                    },
                    "organizations": {
                        "enriched": enriched_entities["orgs"],
                        "found_in_flat": found_orgs,
                        "matched_count": len(found_orgs),
                        "total_in_enriched": len(enriched_entities["orgs"]),
                    },
                },
                "shared_places_excel": sorted(match.get("shared_places_excel", set())),
                "shared_orgs_excel": sorted(match.get("shared_orgs_excel", set())),
                "shared_places_text": sorted(match.get("shared_places_text", set())),
                "shared_orgs_text": sorted(match.get("shared_orgs_text", set())),
                "enriched_preview": enriched_text(enriched)[:300],
                "flat_preview": flat_text[:300],
            }
        )

    json_file = output_dir / "ground_truth_stratified_matches.json"
    jsonl_file = output_dir / "ground_truth_stratified_matches.jsonl"
    parquet_file = output_dir / "ground_truth_stratified_matches.parquet"

    json_file.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(jsonl_file, "w", encoding="utf-8") as handle:
        for record in ground_truth:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    pd.DataFrame(
        [
            {
                "sample_id": item["sample_id"],
                "enriched_id": item["enriched_id"],
                "flat_id": item["flat_id"],
                "enriched_date": item["enriched_date"],
                "flat_date": item["flat_date"],
                "date_diff_days": item["date_diff_days"],
                "is_same_day": item["is_same_day"],
                "match_kind": item["match_kind"],
                "evidence_source": item["evidence_source"],
                "is_summary_anchor": item["is_summary_anchor"],
                "confidence_score": item["confidence_score"],
                "place_matches": item["entities"]["places"]["matched_count"],
                "person_matches": item["entities"]["persons"]["matched_count"],
                "org_matches": item["entities"]["organizations"]["matched_count"],
                "enriched_preview": item["enriched_preview"],
                "flat_preview": item["flat_preview"],
            }
            for item in ground_truth
        ]
    ).to_parquet(parquet_file, index=False)

    summary_file = output_dir / "ground_truth_stratified_matches_summary.json"
    summary_file.write_text(
        json.dumps(
            {
                "samples": len(ground_truth),
                "summary_anchors": sum(item["is_summary_anchor"] for item in ground_truth),
                "same_day_matches": sum(item["is_same_day"] for item in ground_truth),
                "match_kind_counts": dict(Counter(item["match_kind"] for item in ground_truth)),
                "aggregate_entity_counts": aggregate_counts,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"✅ Ground truth exported: {len(ground_truth)} samples")
    print(f"  Match kinds: {dict(Counter(item['match_kind'] for item in ground_truth))}")
    return ground_truth


def write_preview_html(
    preview_sample: list[dict[str, Any]],
    output_path: Path,
    date_window_days: int,
) -> None:
    kind_styles = {
        "both": "#e8f5e9",
        "places_only": "#e3f2fd",
        "orgs_only": "#fff3e0",
        "none": "#fafafa",
    }

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("<html><body style='font-family: sans-serif; max-width: 1100px; margin: auto;'>")
        handle.write("<h1>Alignment Previews (Excel Anchors)</h1>")
        handle.write(
            f"<p>Date window: ±{date_window_days} day(s). "
            "Badges show whether overlap evidence is place-only, org-only, or both.</p>"
        )
        if not preview_sample:
            handle.write(
                "<p><i>No anchored matches were found. "
                "Check volgnr derivation and paragraph-to-resolution mapping.</i></p>"
            )

        for match in preview_sample:
            match_kind = match.get("match_kind", "none")
            badge = match_kind_label(match_kind)
            bg = kind_styles.get(match_kind, "#ffffff")
            enr_preview = escape(enriched_text(match["enriched"])[:500])
            flat_preview = escape(candidate_text(match["flat_record"])[:500])
            date_note = "same day" if match.get("is_same_day") else f"{match.get('date_diff_days')} day gap"

            handle.write(
                f"<div style='border-bottom: 1px solid #ccc; padding-bottom: 20px; margin-bottom: 20px; background:{bg};'>"
            )
            handle.write(
                f"<h3>Date: {match['date']} → flat {match.get('flat_period', '')} "
                f"({date_note}; score {match['overlap_score']:.2f}) "
                f"<span style='font-size: 0.8em;'>[{badge}]</span></h3>"
            )
            handle.write(
                f"<p><b>IDs:</b> enriched {escape(enriched_volgnr(match['enriched']) or '')} "
                f"→ flat {escape(str(match['flat_record'].get('id', '')))}</p>"
            )
            handle.write(
                f"<p><b>Shared places:</b> "
                f"<span style='color:#1565c0;'>{', '.join(sorted(match.get('shared_places', []))) or '—'}</span></p>"
            )
            handle.write(
                f"<p><b>Shared organizations:</b> "
                f"<span style='color:#e65100;'>{', '.join(sorted(match.get('shared_orgs', []))) or '—'}</span></p>"
            )
            if match.get("evidence_source") == "excel+text":
                handle.write("<p><i>Cross-day match: entity evidence supplemented from flat text.</i></p>")
            handle.write(
                "<div style='display: grid; grid-template-columns: 1fr 1fr; gap: 12px;'>"
                f"<p style='background-color: #f0f7ff; padding: 10px; border-left: 4px solid #0066cc;'>"
                f"<b>Enriched Text</b><br><i>{enr_preview}...</i></p>"
                f"<p style='background-color: #f9f9f9; padding: 10px; border-left: 4px solid #007bff;'>"
                f"<b>Flat Text</b><br><i>{flat_preview}...</i></p>"
                "</div>"
            )
            handle.write("</div>")
        handle.write("</body></html>")


# --- PIPELINE ---

def run(
    preview_limit: int = 8,
    stratified_size: int = 50,
    gap_penalty: float = 0.1,
    date_window_days: int = 0,
    verification_page_size: int = 5,
    session_first: bool = True,
    anchor_only_diagonal: bool = True,
    min_overlap_score: float = DEFAULT_MIN_OVERLAP_SCORE,
    verification_match_kind: str = "both",
) -> None:
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    enriched_all, res_df, places_df, orgs_df, loc_names, per_names, org_names = load_data()
    res_df["date_period"] = pd.PeriodIndex(res_df["date_str"], freq="D")

    # 1. Normalize and merge the Excel overlap data
    print("Pre-processing overlap dictionaries...")
    if 'naam' in orgs_df.columns and 'name' not in orgs_df.columns:
        orgs_df = orgs_df.rename(columns={'naam': 'name'})
    if 'naam' in places_df.columns and 'name' not in places_df.columns:
        places_df = places_df.rename(columns={'naam': 'name'})

    all_overlaps = pd.concat(
        [
            places_df[["volgnr", "paragraph_id", "name"]],
            orgs_df[["volgnr", "paragraph_id", "name"]],
        ],
        ignore_index=True,
    )

    paragraph_ids = {
        str(paragraph_id).strip()
        for paragraph_id in all_overlaps["paragraph_id"].dropna().astype(str)
        if str(paragraph_id).strip()
    }
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )

    place_lookup, org_lookup, _person_lookup, overlap_lookup = build_overlap_lookups(
        places_df,
        orgs_df,
        paragraph_to_resolution,
    )
    date_to_session_map = build_date_to_session_map(
        places_df,
        orgs_df,
        paragraph_to_resolution,
    )
    print(f"✓ Session map: {len(date_to_session_map)} enriched dates → flat sessions")

    # 3. Calculate IDF Weights using the Excel overlap data
    idf_weights = calculate_idf_weights(all_overlaps)

    # 4. Prepare Enriched items (extract dates and set up objects for grouping)
    enriched_by_date = {}
    for enriched in enriched_all:
        date_raw = str(enriched.get("date", ""))[:10]
        enriched["date_str"] = date_raw if len(date_raw) == 10 else None
        
        resolved = resolve_enriched_entities(enriched, loc_names, per_names, org_names)
        enriched["entity_set"] = set(resolved["places"] + resolved["orgs"])
        
        if enriched["date_str"]:
            enriched_by_date.setdefault(enriched["date_str"], []).append(enriched)

    # 5. Perform Sequence Alignment
    all_alignments = []
    session_pool_days = 0
    fallback_pool_days = 0
    print(
        f"Aligning sessions mathematically "
        f"(session-first={session_first}, anchor-only diagonal={anchor_only_diagonal}, "
        f"min overlap={min_overlap_score}, date window: ±{date_window_days} day(s))..."
    )
    
    for current_date, day_enriched in enriched_by_date.items():
        enriched_period = period_from_date(current_date)
        if enriched_period is None:
            continue

        day_flat, pool_label = select_flat_candidates(
            res_df,
            current_date,
            enriched_period,
            date_to_session_map,
            date_window_days,
            session_first=session_first and date_window_days == 0,
        )
        if pool_label.startswith("session"):
            session_pool_days += 1
        else:
            fallback_pool_days += 1
        if day_flat.empty:
            continue
            
        day_enriched = sorted(day_enriched, key=lambda x: int(x.get("resolution_index", 0)))
        day_flat = day_flat.sort_values(["date_str", "id"])
        
        day_enriched_ids = [enriched_volgnr(e) or "" for e in day_enriched]
        day_flat_ids = day_flat["id"].astype(str).tolist()
        
        session_matches = align_session(
            enriched_ids=day_enriched_ids, 
            flat_ids=day_flat_ids, 
            overlap_lookup=overlap_lookup, 
            idf_weights=idf_weights, 
            gap_penalty=gap_penalty,
            anchor_only_diagonal=anchor_only_diagonal,
        )
        
        for e_idx, f_idx in session_matches:
            if e_idx is None or f_idx is None:
                continue

            e_record = day_enriched[e_idx]
            f_record = day_flat.iloc[f_idx]
            e_id = enriched_volgnr(e_record) or ""
            f_id = str(f_record["id"])
            pair_key = (e_id, f_id)

            entity_info = resolve_shared_entities(
                e_record,
                f_record,
                pair_key,
                place_lookup,
                org_lookup,
                loc_names,
                per_names,
                org_names,
                date_window_days=date_window_days,
            )
            overlap_score = sum(idf_weights.get(entity, 1.0) for entity in entity_info["shared_entities"])
            if entity_info["match_kind"] == "none" or overlap_score < min_overlap_score:
                continue

            all_alignments.append({
                "date": current_date,
                "pool_mode": pool_label,
                "session_id": f_record.get("session_id"),
                "enriched": e_record,
                "flat_record": f_record,
                "shared_entities": entity_info["shared_entities"],
                "shared_places": entity_info["shared_places"],
                "shared_orgs": entity_info["shared_orgs"],
                "shared_places_excel": entity_info["shared_places_excel"],
                "shared_orgs_excel": entity_info["shared_orgs_excel"],
                "shared_places_text": entity_info["shared_places_text"],
                "shared_orgs_text": entity_info["shared_orgs_text"],
                "match_kind": entity_info["match_kind"],
                "evidence_source": entity_info["evidence_source"],
                "enriched_entities": entity_info["enriched_entities"],
                "enriched_period": entity_info["enriched_period"],
                "flat_period": entity_info["flat_period"],
                "date_diff_days": entity_info["date_diff_days"],
                "is_same_day": entity_info["is_same_day"],
                "overlap_score": overlap_score,
                "is_gap_fill": entity_info["match_kind"] == "none",
            })

    print(f"✓ Total aligned resolution pairs: {len(all_alignments)}")
    if session_first and date_window_days == 0:
        print(f"  Session pools: {session_pool_days} days | fallback same-day pools: {fallback_pool_days} days")
    anchored_count = sum(1 for item in all_alignments if not item["is_gap_fill"])
    print(f"✓ Anchored pairs with Excel entity overlap: {anchored_count}")
    print(f"  Match kinds: {dict(Counter(item['match_kind'] for item in all_alignments if not item['is_gap_fill']))}")

    # --- ARTIFACT GENERATION ---

    anchored_matches = [a for a in all_alignments if not a["is_gap_fill"]]
    preview_candidates: list[dict[str, Any]] = []
    per_kind_limit = max(2, preview_limit // 3)
    for kind in ("both", "places_only", "orgs_only"):
        kind_matches = sorted(
            [item for item in anchored_matches if item["match_kind"] == kind],
            key=lambda item: item["overlap_score"],
            reverse=True,
        )[:per_kind_limit]
        preview_candidates.extend(kind_matches)
    if len(preview_candidates) < preview_limit:
        seen = {
            (enriched_volgnr(item["enriched"]), str(item["flat_record"]["id"]))
            for item in preview_candidates
        }
        for item in sorted(anchored_matches, key=lambda row: row["overlap_score"], reverse=True):
            key = (enriched_volgnr(item["enriched"]), str(item["flat_record"]["id"]))
            if key in seen:
                continue
            preview_candidates.append(item)
            seen.add(key)
            if len(preview_candidates) >= preview_limit:
                break

    preview_html_path = OUTPUT_DIR / "matched_resolutions_sample.html"
    write_preview_html(preview_candidates[:preview_limit], preview_html_path, date_window_days)
    print(f"✓ Saved preview HTML: {preview_html_path}")

    if stratified_size > 0 and all_alignments:
        stratified_alignments = build_stratified_verification_sample(
            all_alignments,
            sample_size=stratified_size,
            min_overlap_score=min_overlap_score,
            verification_match_kind=verification_match_kind,
        )
        ground_truth = export_ground_truth_records(stratified_alignments, OUTPUT_DIR)
        write_verification_html(
            ground_truth,
            OUTPUT_DIR / "verify_ground_truth.html",
            page_size=verification_page_size,
        )
        print(f"✓ Saved verification HTML: {OUTPUT_DIR / 'verify_ground_truth.html'}")

    evaluate_against_labeled(all_alignments, OUTPUT_DIR / "ground_truth_labeled.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview-limit", type=int, default=8)
    parser.add_argument("--stratified-size", type=int, default=50)
    parser.add_argument("--gap-penalty", type=float, default=0.1)
    parser.add_argument(
        "--date-window-days",
        type=int,
        default=0,
        help="Include flat resolutions within ±N days of the enriched session date (0 = same day only).",
    )
    parser.add_argument(
        "--verification-page-size",
        type=int,
        default=5,
        help="Samples per page in verify_ground_truth.html.",
    )
    parser.add_argument(
        "--session-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pool flat resolutions by mapped session id instead of calendar date (default on).",
    )
    parser.add_argument(
        "--anchor-only-diagonal",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Disallow NW diagonal matches without Excel entity overlap (default on).",
    )
    parser.add_argument(
        "--min-overlap-score",
        type=float,
        default=DEFAULT_MIN_OVERLAP_SCORE,
        help="Minimum IDF-weighted overlap score to export a pair.",
    )
    parser.add_argument(
        "--verification-match-kind",
        choices=["any", "both", "not_places_only"],
        default="both",
        help="Filter stratified verification sample by entity overlap type (default: both).",
    )
    args = parser.parse_args()
    
    run(
        preview_limit=args.preview_limit,
        stratified_size=args.stratified_size,
        gap_penalty=args.gap_penalty,
        date_window_days=args.date_window_days,
        verification_page_size=args.verification_page_size,
        session_first=args.session_first,
        anchor_only_diagonal=args.anchor_only_diagonal,
        min_overlap_score=args.min_overlap_score,
        verification_match_kind=args.verification_match_kind,
    )
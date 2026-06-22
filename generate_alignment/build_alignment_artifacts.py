#!/usr/bin/env python3
"""Generate alignment preview, stratified ground truth, and verification HTML.

This script extracts the generation flow that previously lived in
`date_tolerance_preview.ipynb` so the outputs can be reproduced from a single
command.

Usage:
    uv run python generate_alignment/build_alignment_artifacts.py
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DATADIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

ENRICHED_FILE = DATADIR / "enriched_resolutions_1626_1630_complete.json"
RESOLUTIONS_FILE = DATADIR / "resolutions_flat.parquet"
LOC_ENTITIES_FILE = DATADIR / "LOC-entities.json"
PER_ENTITIES_FILE = DATADIR / "PER-entities.json"
ORG_ENTITIES_FILE = DATADIR / "ORG-entities.json"


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


def load_data() -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, str], dict[str, str], dict[str, str]]:
    print("Loading data files...")
    enriched_all = load_json(ENRICHED_FILE)
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    res_df["date_period"] = pd.PeriodIndex(res_df["date"].astype(str), freq="D")

    loc_names = load_entity_names(LOC_ENTITIES_FILE)
    per_names = load_entity_names(PER_ENTITIES_FILE)
    org_names = load_entity_names(ORG_ENTITIES_FILE)

    print(f"✓ Loaded {len(enriched_all)} enriched resolutions")
    print(f"✓ Loaded {len(res_df)} flat resolutions")
    print(f"✓ Loaded {len(loc_names)} LOC canonical names")
    print(f"✓ Loaded {len(per_names)} PER canonical names")
    print(f"✓ Loaded {len(org_names)} ORG canonical names")
    return enriched_all, res_df, loc_names, per_names, org_names


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value)


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


def normalized_entity_names(names: list[str]) -> set[str]:
    return {name.strip().lower() for name in names if name and name.strip()}


def matched_entity_names(names: list[str], flat_text: str) -> list[str]:
    return [name for name in names if name and name.lower() in flat_text]


def format_entity_summary(entity_map: dict[str, list[str]], flat_text: str | None = None) -> str:
    parts: list[str] = []
    flat_text_lower = flat_text.lower() if flat_text else ""
    for entity_type, label in (("places", "Places"), ("persons", "Persons"), ("orgs", "Orgs")):
        names = entity_map.get(entity_type, [])
        if flat_text_lower:
            names = [name for name in names if name and name.lower() in flat_text_lower]
        if names:
            parts.append(f"{label}: {', '.join(escape(name) for name in names)}")
    return "<br>".join(parts) if parts else "—"


def build_entity_frequency_index(
    enriched_all: list[dict[str, Any]],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
) -> dict[str, Counter[str]]:
    frequencies: dict[str, Counter[str]] = {
        "places": Counter(),
        "persons": Counter(),
        "organizations": Counter(),
    }

    for enriched in enriched_all:
        resolved = resolve_enriched_entities(enriched, loc_names, per_names, org_names)
        for entity_type, names in resolved.items():
            frequency_key = "organizations" if entity_type == "orgs" else entity_type
            for name in normalized_entity_names(names):
                frequencies[frequency_key][name] += 1

    return frequencies


def candidate_text(candidate: pd.Series) -> str:
    text = candidate.get("resolutions_text")
    if not text or str(text) == "nan":
        text = candidate.get("paragraph_texts")
    if not text or str(text) == "nan":
        text = candidate.get("paragraph_text")
    return as_text(text).lower()


def score_candidate(
    enriched_entities: dict[str, list[str]],
    flat_text: str,
    enriched_date: pd.Period,
    candidate_date_raw: Any,
) -> dict[str, Any]:
    candidate_date = None
    if candidate_date_raw is not None and str(candidate_date_raw).strip():
        try:
            candidate_date = pd.Period(str(candidate_date_raw)[:10], freq="D")
        except (TypeError, ValueError):
            candidate_date = None

    place_matches = sum(1 for name in enriched_entities["places"] if name and name.lower() in flat_text)
    person_matches = sum(1 for name in enriched_entities["persons"] if name and name.lower() in flat_text)
    org_matches = sum(1 for name in enriched_entities["orgs"] if name and name.lower() in flat_text)
    total_matches = place_matches + person_matches + org_matches
    same_day = candidate_date == enriched_date
    date_diff_days = abs((candidate_date - enriched_date).n) if candidate_date is not None else None
    entity_types_matched = sum(1 for value in (place_matches, person_matches, org_matches) if value > 0)
    place_weight = place_matches * 300
    score = (same_day * 10000) + place_weight + (person_matches * 100) + (org_matches * 100) + entity_types_matched
    if not same_day and date_diff_days is not None:
        score -= 50 * date_diff_days
    return {
        "candidate_date": candidate_date,
        "place_matches": place_matches,
        "person_matches": person_matches,
        "org_matches": org_matches,
        "total_matches": total_matches,
        "same_day": same_day,
        "entity_types_matched": entity_types_matched,
        "place_weight": place_weight,
        "score": score,
    }


def build_date_anchor_map(
    enriched_all: list[dict[str, Any]],
    res_df: pd.DataFrame,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
) -> dict[str, str]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    enriched_periods: list[pd.Period] = []
    for enriched in enriched_all:
        date_raw = enriched.get("date")
        try:
            enriched_periods.append(pd.Period(str(date_raw)[:10], freq="D"))
        except (TypeError, ValueError):
            enriched_periods.append(None)

    for enriched, date in zip(enriched_all, enriched_periods):
        if date is None:
            continue
        resolved = resolve_enriched_entities(enriched, loc_names, per_names, org_names)
        if sum(len(values) for values in resolved.values()) == 0:
            continue

        date_key = str(date)
        place_count = len(normalized_entity_names(resolved["places"]))
        org_count = len(normalized_entity_names(resolved["orgs"]))
        person_count = len(normalized_entity_names(resolved["persons"]))
        by_date.setdefault(date_key, []).append(
            {
                "enriched": enriched,
                "date": date,
                "place_count": place_count,
                "org_count": org_count,
                "person_count": person_count,
                "strength": (place_count * 1000) + (org_count * 1200) + (person_count * 100),
            }
        )

    anchor_entries: list[tuple[pd.Period, pd.Period]] = []
    anchor_map: dict[str, str] = {}

    for date_key, records in by_date.items():
        best_record = max(
            records,
            key=lambda item: (
                item["strength"],
                item["place_count"],
                item["org_count"],
                item["person_count"],
                -int(item["enriched"].get("resolution_index", 0)),
            ),
        )
        match = find_best_match(best_record["enriched"], res_df, loc_names, per_names, org_names, window_days=3)
        if not match:
            continue
        if not (match["same_day"] and match["total_matches"] >= 2):
            continue

        try:
            flat_date = pd.Period(str(match["best_match"].get("date"))[:10], freq="D")
        except (TypeError, ValueError):
            continue

        anchor_map[date_key] = str(flat_date)
        anchor_entries.append((best_record["date"], flat_date))

    anchor_entries.sort(key=lambda item: item[0])
    for left, right in zip(anchor_entries, anchor_entries[1:]):
        left_enriched, left_flat = left
        right_enriched, right_flat = right
        gap = int((right_enriched - left_enriched).n)
        if gap <= 1:
            continue
        for offset in range(1, gap):
            enriched_key = str(left_enriched + offset)
            if enriched_key not in anchor_map:
                anchor_map[enriched_key] = str(left_flat + offset)

    return anchor_map


def resolve_anchor_window(
    enriched_date: pd.Period,
    anchor_map: dict[str, str] | None,
    window_days: int,
) -> tuple[pd.Period, int]:
    if not anchor_map:
        return enriched_date, window_days

    date_key = str(enriched_date)
    anchor_date_raw = anchor_map.get(date_key)
    if not anchor_date_raw:
        return enriched_date, window_days

    try:
        anchor_date = pd.Period(str(anchor_date_raw)[:10], freq="D")
    except (TypeError, ValueError):
        return enriched_date, window_days

    return anchor_date, min(window_days, 1)


def find_best_match(
    enriched: dict[str, Any],
    res_df: pd.DataFrame,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    window_days: int = 3,
    anchor_map: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not enriched.get("date"):
        return None

    try:
        enriched_date = pd.Period(str(enriched["date"])[:10], freq="D")
    except (TypeError, ValueError):
        return None

    enriched_entities = resolve_enriched_entities(enriched, loc_names, per_names, org_names)
    if sum(len(values) for values in enriched_entities.values()) == 0:
        return None

    anchor_date, window_days = resolve_anchor_window(enriched_date, anchor_map, window_days)

    date_min = anchor_date - window_days
    date_max = anchor_date + window_days
    candidates = res_df[(res_df["date_period"] >= date_min) & (res_df["date_period"] <= date_max)].copy()
    if candidates.empty:
        return None

    scored_candidates = []
    for _, candidate in candidates.iterrows():
        flat_text = candidate_text(candidate)
        score = score_candidate(enriched_entities, flat_text, enriched_date, candidate["date_period"])
        scored_candidates.append({"candidate": candidate, **score})

    best = max(scored_candidates, key=lambda item: item["score"])
    if best["total_matches"] == 0:
        return None

    best_match = best["candidate"]
    best_flat_date = best_match["date_period"]
    top_candidates = sorted(
        scored_candidates,
        key=lambda item: (
            -item["score"],
            item["candidate"]["date_period"],
            item["candidate"].get("id", ""),
        ),
    )[:3]
    return {
        "enriched": enriched,
        "best_match": best_match,
        "enriched_entities": enriched_entities,
        "place_matches": best["place_matches"],
        "person_matches": best["person_matches"],
        "org_matches": best["org_matches"],
        "total_matches": best["total_matches"],
        "total_places": len(enriched_entities["places"]),
        "total_persons": len(enriched_entities["persons"]),
        "total_orgs": len(enriched_entities["orgs"]),
        "is_summary_anchor": best["same_day"] and best["total_matches"] >= 2,
        "same_day": best["same_day"],
        "score": best["score"],
        "date_diff_days": abs((best_flat_date - enriched_date).n) if best_flat_date is not None else None,
        "top_candidates": [
            {
                "id": item["candidate"].get("id"),
                "date": str(item["candidate"].get("date_period")) if item["candidate"].get("date_period") is not None else None,
                "score": item["score"],
                "same_day": item["same_day"],
                "date_diff_days": abs((item["candidate"]["date_period"] - enriched_date).n) if item["candidate"].get("date_period") is not None else None,
                "place_matches": item["place_matches"],
                "person_matches": item["person_matches"],
                "org_matches": item["org_matches"],
                "total_matches": item["total_matches"],
            }
            for item in top_candidates
        ],
    }


def build_baseline_preview_matches(
    enriched_all: list[dict[str, Any]],
    res_df: pd.DataFrame,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    anchor_map: dict[str, str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    preview_matches: list[dict[str, Any]] = []
    for enriched in enriched_all:
        if len(preview_matches) >= limit:
            break
        match = find_best_match(enriched, res_df, loc_names, per_names, org_names, anchor_map=anchor_map)
        if match:
            preview_matches.append(match)
    print(f"✓ Found {len(preview_matches)} baseline preview matches with entity overlap")
    print(f"  Summary anchors: {sum(1 for item in preview_matches if item['is_summary_anchor'])}")
    return preview_matches


def build_preview_matches(
    enriched_all: list[dict[str, Any]],
    res_df: pd.DataFrame,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    anchor_map: dict[str, str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    place_frequency: Counter[str] = Counter()
    org_frequency: Counter[str] = Counter()
    enriched_place_records: list[dict[str, Any]] = []
    enriched_org_place_records: list[dict[str, Any]] = []

    for enriched in enriched_all:
        if not enriched.get("date"):
            continue
        resolved = resolve_enriched_entities(enriched, loc_names, per_names, org_names)
        place_names = normalized_entity_names(resolved["places"])
        org_names_found = normalized_entity_names(resolved["orgs"])
        if not place_names and not org_names_found:
            continue
        place_frequency.update(place_names)
        org_frequency.update(org_names_found)
        record = {
            "enriched": enriched,
            "resolved": resolved,
            "place_names": place_names,
            "org_names": org_names_found,
            "place_count": len(place_names),
            "org_count": len(org_names_found),
            "place_frequency_score": sum(place_frequency[name] for name in place_names),
            "org_frequency_score": sum(org_frequency[name] for name in org_names_found),
        }
        if place_names and org_names_found:
            enriched_org_place_records.append(record)
        enriched_place_records.append(
            record
        )

    if not enriched_place_records:
        print("No place-rich enriched resolutions found; falling back to baseline preview selection.")
        return build_baseline_preview_matches(enriched_all, res_df, loc_names, per_names, org_names, anchor_map=anchor_map, limit=limit)

    enriched_org_place_records.sort(
        key=lambda item: (
            -item["place_count"],
            -item["org_count"],
            -item["place_frequency_score"],
            -item["org_frequency_score"],
            item["enriched"].get("date") or "",
        )
    )
    enriched_place_records.sort(
        key=lambda item: (
            -item["place_count"],
            -item["org_count"],
            -item["place_frequency_score"],
            -item["org_frequency_score"],
            item["enriched"].get("date") or "",
        )
    )

    scan_limit = min(len(enriched_place_records), max(limit * 200, 1000))
    org_place_pool = enriched_org_place_records[:scan_limit]
    place_only_pool = [record for record in enriched_place_records if not record["org_names"]][:scan_limit]

    preview_matches: list[dict[str, Any]] = []
    def collect_matches(records: list[dict[str, Any]], require_org_overlap: bool) -> None:
        for record in records:
            if len(preview_matches) >= limit:
                return

            match = find_best_match(record["enriched"], res_df, loc_names, per_names, org_names, anchor_map=anchor_map)
            if not match:
                continue

            flat_text = candidate_text(match["best_match"])
            matched_places = matched_entity_names(match["enriched_entities"]["places"], flat_text)
            matched_orgs = matched_entity_names(match["enriched_entities"]["orgs"], flat_text)
            if not matched_places:
                continue
            if require_org_overlap and not matched_orgs:
                continue

            place_strength = len(matched_places)
            org_strength = len(matched_orgs)
            place_frequency_strength = sum(place_frequency[name.lower()] for name in normalized_entity_names(matched_places))
            org_frequency_strength = sum(org_frequency[name.lower()] for name in normalized_entity_names(matched_orgs))
            total_matches = match["place_matches"] + match["person_matches"] + match["org_matches"]
            entity_types_matched = sum(1 for value in (match["place_matches"], match["person_matches"], match["org_matches"]) if value > 0)
            match["matched_places"] = matched_places
            match["matched_orgs"] = matched_orgs
            match["matched_places_count"] = place_strength
            match["matched_orgs_count"] = org_strength
            match["place_anchor_score"] = (
                (place_strength * 10000)
                + (org_strength * 8000)
                + (place_frequency_strength * 100)
                + (org_frequency_strength * 100)
                + (1000 if match["same_day"] else 0)
                + (total_matches * 50)
                + entity_types_matched
            )
            preview_matches.append(match)

    collect_matches(org_place_pool, require_org_overlap=True)
    if len(preview_matches) < limit:
        collect_matches(place_only_pool, require_org_overlap=False)

    preview_matches.sort(
        key=lambda item: (
            -item["place_anchor_score"],
            -item["place_matches"],
            -(item["place_matches"] + item["person_matches"] + item["org_matches"]),
            item["date_diff_days"] if item["date_diff_days"] is not None else 9999,
        )
    )

    deduped_matches: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, Any, Any]] = set()
    for item in preview_matches:
        key = (
            item["enriched"].get("file"),
            item["enriched"].get("resolution_index"),
            item["best_match"].get("id"),
        )
        if key in seen_keys:
            continue
        deduped_matches.append(item)
        seen_keys.add(key)
        if len(deduped_matches) >= limit:
            break

    print(f"✓ Found {len(deduped_matches)} preview matches with place/org overlap")
    print(f"  Place/org enriched candidates scanned: {len(org_place_pool)}")
    print(f"  Place-only fallback candidates scanned: {len(place_only_pool)}")
    print(f"  Summary anchors: {sum(1 for item in deduped_matches if item['is_summary_anchor'])}")
    return deduped_matches


def build_stratified_matches(
    enriched_all: list[dict[str, Any]],
    res_df: pd.DataFrame,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    anchor_map: dict[str, str] | None = None,
    sample_size: int = 30,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in enriched_all:
        date_raw = item.get("date")
        if not date_raw:
            continue
        try:
            dated_period = pd.Period(str(date_raw)[:10], freq="D")
        except (TypeError, ValueError):
            continue
        rows.append({"date": dated_period, "enriched": item})

    dated = pd.DataFrame(rows).reset_index(drop=True)

    if dated.empty:
        return []

    dated["year_month"] = pd.PeriodIndex(dated["date"].astype(str), freq="M")
    months = sorted(dated["year_month"].unique())
    items_per_month = max(1, sample_size // max(1, len(months)))

    print("\n📅 Stratified sampling across corpus:")
    print(f"   Months covered: {len(months)}")
    print(f"   Items per month: {items_per_month}")

    stratified_indices: list[int] = []
    for month in months:
        month_data = dated[dated["year_month"] == month]
        if month_data.empty:
            continue

        ranked_month_rows: list[tuple[int, int, int, int, pd.Period, int]] = []
        for idx, row in month_data.iterrows():
            enriched_item = row["enriched"]
            resolved = resolve_enriched_entities(enriched_item, loc_names, per_names, org_names)
            place_count = len(normalized_entity_names(resolved["places"]))
            org_count = len(normalized_entity_names(resolved["orgs"]))
            person_count = len(normalized_entity_names(resolved["persons"]))
            entity_types_matched = sum(1 for value in (place_count, person_count, org_count) if value > 0)
            verification_anchor_score = (
                (place_count * 1000)
                + (org_count * 1200)
                + (person_count * 100)
                + (entity_types_matched * 10)
                + (1 if place_count > 0 and org_count > 0 else 0)
            )
            ranked_month_rows.append(
                (
                    -verification_anchor_score,
                    -place_count,
                    -org_count,
                    -person_count,
                    row["date"],
                    idx,
                )
            )

        ranked_month_rows.sort()
        chosen_indices = [item[-1] for item in ranked_month_rows[: min(items_per_month, len(ranked_month_rows))]]
        stratified_indices.extend(chosen_indices)

    stratified_indices = sorted(set(stratified_indices))
    random.seed(9673)
    random.shuffle(stratified_indices)

    stratified_matches: list[dict[str, Any]] = []
    for i, idx in enumerate(stratified_indices, 1):
        enriched_item = dated.at[idx, "enriched"]
        if isinstance(enriched_item, dict):
            match = find_best_match(enriched_item, res_df, loc_names, per_names, org_names, anchor_map=anchor_map)
            if match:
                stratified_matches.append(match)
        if i % 10 == 0:
            print(f"  Progress: {i}/{len(stratified_indices)}", end="\r")

    print()
    print(f"✓ Stratified matches: {len(stratified_matches)}")
    print(f"  Summary anchors: {sum(1 for item in stratified_matches if item['is_summary_anchor'])}")
    return stratified_matches


def build_focus_matches(
    enriched_all: list[dict[str, Any]],
    res_df: pd.DataFrame,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    focus_entities: list[str],
    anchor_map: dict[str, str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    focus_terms = normalized_entity_names(focus_entities)
    if not focus_terms:
        return []

    focus_matches: list[dict[str, Any]] = []
    for enriched in enriched_all:
        if len(focus_matches) >= limit:
            break
        resolved = resolve_enriched_entities(enriched, loc_names, per_names, org_names)
        resolved_names = normalized_entity_names(resolved["places"] + resolved["persons"] + resolved["orgs"])
        if any(term in name or name in term for term in focus_terms for name in resolved_names):
            match = find_best_match(enriched, res_df, loc_names, per_names, org_names, anchor_map=anchor_map)
            if match:
                focus_matches.append(match)

    print(f"✓ Focus matches: {len(focus_matches)}")
    if focus_matches:
        print(f"  Focus entities: {', '.join(sorted(focus_terms))}")
    return focus_matches


def build_frequency_matches(
    enriched_all: list[dict[str, Any]],
    res_df: pd.DataFrame,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    anchor_map: dict[str, str] | None = None,
    top_n: int = 10,
    limit: int = 12,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    frequencies = build_entity_frequency_index(enriched_all, loc_names, per_names, org_names)
    ranked_entities: list[dict[str, Any]] = []
    for entity_type, counter in frequencies.items():
        for name, count in counter.most_common(top_n):
            ranked_entities.append({"entity_type": entity_type, "name": name, "count": count})

    ranked_entities.sort(key=lambda item: (-item["count"], item["entity_type"], item["name"]))
    if not ranked_entities:
        return [], []

    selected: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, Any, Any]] = set()
    for entity in ranked_entities:
        if len(selected) >= limit:
            break
        entity_name = entity["name"]
        entity_matches: list[dict[str, Any]] = []
        for enriched in enriched_all:
            resolved = resolve_enriched_entities(enriched, loc_names, per_names, org_names)
            names = normalized_entity_names(resolved["places"] + resolved["persons"] + resolved["orgs"])
            if entity_name in names:
                match = find_best_match(enriched, res_df, loc_names, per_names, org_names, anchor_map=anchor_map)
                if match:
                    key = (
                        match["enriched"].get("file"),
                        match["enriched"].get("resolution_index"),
                        match["best_match"].get("id"),
                    )
                    if key not in seen_keys:
                        entity_matches.append(match)
                        seen_keys.add(key)
                        break

        selected.extend(entity_matches)

    print(f"✓ Frequent entity candidates: {len(ranked_entities)}")
    if ranked_entities:
        print("  Top entities:")
        for item in ranked_entities[: min(5, len(ranked_entities))]:
            print(f"    - {item['name']} ({item['entity_type']}): {item['count']}")
    print(f"✓ Frequency matches: {len(selected)}")
    return selected, ranked_entities


def build_html_rows(samples: list[dict[str, Any]], preview_count: int = 8) -> list[str]:
    rows: list[str] = []
    for i, sample in enumerate(samples[:preview_count], 1):
        enriched = sample["enriched"]
        best_match = sample["best_match"]
        enr_date = pd.Period(str(enriched["date"])[:10], freq="D")
        flat_date_raw = best_match.get("date_period") or best_match.get("date")
        if isinstance(flat_date_raw, pd.Period):
            flat_date = str(flat_date_raw)
        else:
            flat_date = str(pd.Period(str(flat_date_raw)[:10], freq="D"))
        flat_text_full = as_text(best_match.get("resolutions_text") or best_match.get("paragraph_texts") or best_match.get("paragraph_text") or "")
        flat_text = flat_text_full[:150]
        enr_text = as_text(enriched.get("text", ""))[:150]
        entity_summary = format_entity_summary(sample.get("enriched_entities", {}), flat_text_full)
        same_day_marker = "●" if sample["same_day"] else " "
        anchor_badge = " 🔗" if sample["is_summary_anchor"] else ""
        rows.append(
            f"""
        <tr class="{'summary-anchor' if sample['is_summary_anchor'] else ''}">
            <td class="num">{i}</td>
            <td class="id">{enriched.get('file', '')}#{enriched.get('resolution_index', '')}</td>
            <td class="date">{str(enr_date) if enr_date is not None else ''}</td>
            <td class="text">{enr_text}</td>
            <td class="entities">{sample['total_places']}p, {sample['total_persons']}ps, {sample['total_orgs']}o</td>
            <td class="found-entities">{entity_summary}</td>
            <td class="arrow">{same_day_marker}↓</td>
            <td class="id">{best_match.get('id', '')}</td>
            <td class="date">{flat_date}</td>
            <td class="diff">{sample['date_diff_days']:+d}d{anchor_badge}</td>
            <td class="text">{flat_text}</td>
            <td class="matches"><strong>{sample['place_matches']}/{sample['total_places']}</strong> p, <strong>{sample['person_matches']}/{sample['total_persons']}</strong> ps, <strong>{sample['org_matches']}/{sample['total_orgs']}</strong> o</td>
        </tr>
            """
        )
    return rows


def write_preview_html(
    samples: list[dict[str, Any]],
    output_file: Path,
    report_title: str = "Resolution Alignment with Summary Anchors (±3 days)",
    report_heading: str = "Resolution Alignment with Summary Anchor Heuristic",
) -> None:
    rows = "".join(build_html_rows(samples))
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{report_title}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        h1 {{ color: #333; border-bottom: 3px solid #0066cc; padding-bottom: 10px; }}
        .info {{ background-color: #e8f4f8; border-left: 4px solid #0066cc; padding: 12px; margin-bottom: 20px; border-radius: 4px; }}
        .legend {{ background-color: #fff3cd; border-left: 4px solid #ff9800; padding: 12px; margin-bottom: 20px; border-radius: 4px; font-size: 0.9em; }}
        table {{ width: 100%; border-collapse: collapse; background-color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-radius: 4px; overflow: hidden; }}
        th {{ background-color: #0066cc; color: white; padding: 12px; text-align: left; font-weight: 600; }}
        td {{ padding: 12px; border-bottom: 1px solid #eee; font-size: 0.9em; }}
        tr:hover {{ background-color: #f9f9f9; }}
        tr.summary-anchor {{ background-color: #e8f5e9; }}
        tr.summary-anchor:hover {{ background-color: #c8e6c9; }}
        td.num {{ background-color: #f0f0f0; font-weight: bold; width: 40px; text-align: center; }}
        td.id {{ font-family: 'Courier New', monospace; font-size: 0.85em; color: #666; }}
        td.date {{ font-weight: 500; text-align: center; width: 100px; }}
        td.diff {{ background-color: #fff3cd; font-weight: 500; text-align: center; width: 100px; }}
        td.arrow {{ text-align: center; font-weight: bold; color: #0066cc; width: 50px; }}
        td.text {{ color: #555; max-width: 180px; word-break: break-word; }}
        td.entities {{ background-color: #e3f2fd; text-align: center; width: 100px; font-size: 0.85em; }}
        td.found-entities {{ background-color: #fffde7; text-align: left; width: 240px; font-size: 0.82em; line-height: 1.35; }}
        td.matches {{ background-color: #f3e5f5; text-align: center; width: 140px; font-weight: 500; font-size: 0.85em; }}
        .summary {{ margin-top: 20px; padding: 15px; background-color: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; color: #155724; }}
    </style>
</head>
<body>
    <h1>{report_heading}</h1>
    <div class="info">
        <strong>Matching Strategy:</strong><br>
        • Date window: ±3 days<br>
        • Entity matching: Canonical names from LOC, PER, ORG entities<br>
        • <strong>Summary Anchor Heuristic:</strong> Same-day resolutions with multiple entity types are treated as "summary" anchors
    </div>
    <div class="legend">
        <strong>Visual Indicators:</strong><br>
        • <strong>🔗</strong> = Summary anchor (same-day + multiple entity types: best matching signal)<br>
        • <strong>●</strong> = Same-day match (strong signal even without summary anchor)<br>
        • <strong style="background-color: #e8f5e9; padding: 2px 4px;">Green row</strong> = Summary anchor row
    </div>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Enriched ID</th>
                <th>Enr Date</th>
                <th>Enriched Text</th>
                <th>Entities</th>
                <th>Entities Found</th>
                <th></th>
                <th>Flat ID</th>
                <th>Flat Date</th>
                <th>Date Diff</th>
                <th>Flat Text</th>
                <th>Matched</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    <div class="summary">
        <strong>✓ Report Generated</strong><br>
        Total with found entities: {len(samples)}<br>
        Summary anchors (same-day + multi-type): {sum(1 for item in samples if item['is_summary_anchor'])}<br>
        Same-day matches: {sum(1 for item in samples if item['same_day'])}
    </div>
</body>
</html>
"""
    output_file.write_text(html_content, encoding="utf-8")
    print(f"✓ HTML report saved to: {output_file}")


def export_ground_truth(samples: list[dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    ground_truth: list[dict[str, Any]] = []
    aggregate_counts = {
        "places": {"enriched": 0, "found_in_flat": 0},
        "persons": {"enriched": 0, "found_in_flat": 0},
        "organizations": {"enriched": 0, "found_in_flat": 0},
    }
    for sample_id, sample in enumerate(samples, 1):
        enriched = sample["enriched"]
        flat = sample["best_match"]
        flat_text = as_text(flat.get("resolutions_text") or flat.get("paragraph_texts") or flat.get("paragraph_text") or "").lower()
        enriched_entities = sample["enriched_entities"]

        found_places = [name for name in enriched_entities["places"] if name and name.lower() in flat_text]
        found_persons = [name for name in enriched_entities["persons"] if name and name.lower() in flat_text]
        found_orgs = [name for name in enriched_entities["orgs"] if name and name.lower() in flat_text]

        aggregate_counts["places"]["enriched"] += len(enriched_entities["places"])
        aggregate_counts["places"]["found_in_flat"] += len(found_places)
        aggregate_counts["persons"]["enriched"] += len(enriched_entities["persons"])
        aggregate_counts["persons"]["found_in_flat"] += len(found_persons)
        aggregate_counts["organizations"]["enriched"] += len(enriched_entities["orgs"])
        aggregate_counts["organizations"]["found_in_flat"] += len(found_orgs)

        enriched_date = None
        flat_date = None
        try:
            enriched_date = pd.Period(str(enriched.get("date", ""))[:10], freq="D")
        except (TypeError, ValueError):
            pass
        try:
            flat_date = pd.Period(str(flat.get("date", ""))[:10], freq="D")
        except (TypeError, ValueError):
            pass

        ground_truth.append(
            {
                "sample_id": sample_id,
                "enriched_date": str(enriched.get("date", "")),
                "flat_date": str(flat_date) if flat_date is not None else str(flat.get("date", "")),
                "date_diff_days": abs((enriched_date - flat_date).n) if enriched_date is not None and flat_date is not None else None,
                "is_same_day": sample["same_day"],
                "is_summary_anchor": sample["is_summary_anchor"],
                "confidence_score": sample["score"],
                "entities": {
                    "places": {
                        "enriched": enriched_entities["places"],
                        "found_in_flat": found_places,
                        "matched_count": sample["place_matches"],
                        "total_in_enriched": sample["total_places"],
                    },
                    "persons": {
                        "enriched": enriched_entities["persons"],
                        "found_in_flat": found_persons,
                        "matched_count": sample["person_matches"],
                        "total_in_enriched": sample["total_persons"],
                    },
                    "organizations": {
                        "enriched": enriched_entities["orgs"],
                        "found_in_flat": found_orgs,
                        "matched_count": sample["org_matches"],
                        "total_in_enriched": sample["total_orgs"],
                    },
                },
                "enriched_preview": as_text(enriched.get("text", ""))[:300],
                "flat_preview": as_text(flat.get("resolutions_text") or flat.get("paragraph_texts") or flat.get("paragraph_text") or "")[:300],
            }
        )

    json_file = output_dir / "ground_truth_stratified_matches.json"
    jsonl_file = output_dir / "ground_truth_stratified_matches.jsonl"
    parquet_file = output_dir / "ground_truth_stratified_matches.parquet"
    alias_file = output_dir / "ground_truth_matches.json"

    json_file.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(jsonl_file, "w", encoding="utf-8") as handle:
        for record in ground_truth:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    gt_df = pd.DataFrame(
        [
            {
                "sample_id": item["sample_id"],
                "enriched_date": item["enriched_date"],
                "flat_date": item["flat_date"],
                "date_diff_days": item["date_diff_days"],
                "is_same_day": item["is_same_day"],
                "is_summary_anchor": item["is_summary_anchor"],
                "confidence_score": item["confidence_score"],
                "place_matches": item["entities"]["places"]["matched_count"],
                "person_matches": item["entities"]["persons"]["matched_count"],
                "org_matches": item["entities"]["organizations"]["matched_count"],
            }
            for item in ground_truth
        ]
    )
    gt_df.to_parquet(parquet_file, index=False)
    alias_file.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False), encoding="utf-8")

    summary_file = output_dir / "ground_truth_stratified_matches_summary.json"
    summary_file.write_text(
        json.dumps(
            {
                "samples": len(ground_truth),
                "summary_anchors": sum(item["is_summary_anchor"] for item in ground_truth),
                "same_day_matches": sum(item["is_same_day"] for item in ground_truth),
                "aggregate_entity_counts": aggregate_counts,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"✅ Ground truth exported: {len(ground_truth)} samples")
    print(f"  Summary anchors: {sum(item['is_summary_anchor'] for item in ground_truth)}")
    print(f"  Entity counts: {aggregate_counts}")
    print(gt_df.to_string(index=False))
    return ground_truth


def export_matched_pairs_evidence(samples: list[dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    evidence_rows: list[dict[str, Any]] = []

    for sample in samples:
        entities = sample["entities"]
        place_found = entities["places"]["found_in_flat"]
        person_found = entities["persons"]["found_in_flat"]
        org_found = entities["organizations"]["found_in_flat"]

        evidence_summary = "; ".join(
            part
            for part in [
                f"date: {'same-day' if sample['is_same_day'] else str(sample['date_diff_days']) + ' day gap'}",
                f"places: {entities['places']['matched_count']}/{entities['places']['total_in_enriched']} matched" + (f" ({', '.join(place_found[:5])})" if place_found else ""),
                f"persons: {entities['persons']['matched_count']}/{entities['persons']['total_in_enriched']} matched" + (f" ({', '.join(person_found[:5])})" if person_found else ""),
                f"orgs: {entities['organizations']['matched_count']}/{entities['organizations']['total_in_enriched']} matched" + (f" ({', '.join(org_found[:5])})" if org_found else ""),
                f"anchor: {'yes' if sample['is_summary_anchor'] else 'no'}",
                "top candidates: "
                + ", ".join(
                    f"{candidate.get('id')}@{candidate.get('date')} score={candidate.get('score')}"
                    for candidate in sample.get('top_candidates', [])[:3]
                ),
            ]
            if part
        )

        evidence_rows.append(
            {
                "sample_id": sample["sample_id"],
                "enriched_date": sample["enriched_date"],
                "flat_date": sample["flat_date"],
                "date_diff_days": sample["date_diff_days"],
                "is_same_day": sample["is_same_day"],
                "is_summary_anchor": sample["is_summary_anchor"],
                "confidence_score": sample["confidence_score"],
                "top_candidates": sample.get("top_candidates", []),
                "evidence_summary": evidence_summary,
                "places_found_in_flat": place_found,
                "persons_found_in_flat": person_found,
                "organizations_found_in_flat": org_found,
                "enriched_preview": sample["enriched_preview"],
                "flat_preview": sample["flat_preview"],
            }
        )

    evidence_json = output_dir / "matched_pairs_evidence.json"
    evidence_jsonl = output_dir / "matched_pairs_evidence.jsonl"
    evidence_csv = output_dir / "matched_pairs_evidence.csv"

    evidence_json.write_text(json.dumps(evidence_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(evidence_jsonl, "w", encoding="utf-8") as handle:
        for record in evidence_rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    pd.DataFrame(evidence_rows).to_csv(evidence_csv, index=False)
    print(f"✓ Matched-pairs evidence exported: {len(evidence_rows)} rows")
    return evidence_rows


def export_curated_matched_pairs(samples: list[dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    curated_rows = [item for item in samples if item["is_summary_anchor"]]

    curated_json = output_dir / "matched_pairs_curated.json"
    curated_jsonl = output_dir / "matched_pairs_curated.jsonl"
    curated_csv = output_dir / "matched_pairs_curated.csv"

    curated_json.write_text(json.dumps(curated_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(curated_jsonl, "w", encoding="utf-8") as handle:
        for record in curated_rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    pd.DataFrame(curated_rows).to_csv(curated_csv, index=False)
    print(f"✓ Curated matched-pairs subset exported: {len(curated_rows)} rows")
    print(f"  Gaps relative to evidence set: {len(samples) - len(curated_rows)} rows")
    return curated_rows


def write_verification_html(
    ground_truth: list[dict[str, Any]],
    output_file: Path,
    page_size: int = 5,
) -> None:
    samples_json = json.dumps(ground_truth, ensure_ascii=False)
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Ground Truth Verification</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f0f2f5;
            padding: 20px;
        }}
        .header {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header h1 {{ color: #2c3e50; margin-bottom: 10px; }}
        .progress-bar {{
            width: 100%;
            height: 30px;
            background: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
            margin-top: 10px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #4CAF50, #45a049);
            transition: width 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
        }}
        .sample-container {{
            background: white;
            border-radius: 8px;
            margin-bottom: 15px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .sample-header {{
            background: #2c3e50;
            color: white;
            padding: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .sample-number {{ font-size: 18px; font-weight: bold; }}
        .sample-meta {{ font-size: 12px; opacity: 0.8; }}
        .sample-body {{ padding: 20px; }}
        .comparison {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        .text-box {{
            border: 1px solid #ddd;
            padding: 15px;
            border-radius: 5px;
            background: #f9f9f9;
        }}
        .text-box h3 {{
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 14px;
            text-transform: uppercase;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }}
        .text-box .text {{
            font-size: 14px;
            line-height: 1.6;
            color: #333;
            font-family: 'Georgia', serif;
            white-space: pre-wrap;
        }}
        .metadata {{
            background: #f0f7ff;
            padding: 12px;
            border-left: 4px solid #3498db;
            border-radius: 3px;
            margin-bottom: 15px;
            font-size: 13px;
        }}
        .metadata-row {{
            display: grid;
            grid-template-columns: 120px 1fr;
            margin-bottom: 6px;
        }}
        .metadata-label {{ font-weight: bold; color: #2c3e50; }}
        .metadata-value {{ color: #555; }}
        .entities {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 10px;
            margin-bottom: 15px;
        }}
        .entity-type {{
            background: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            border-left: 3px solid #3498db;
        }}
        .entity-type h4 {{
            font-size: 12px;
            color: #2c3e50;
            margin-bottom: 5px;
        }}
        .entity-count {{
            font-size: 16px;
            font-weight: bold;
            color: #3498db;
        }}
        .verdict-buttons {{
            display: flex;
            gap: 10px;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 2px solid #eee;
        }}
        button {{
            flex: 1;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            transition: all 0.3s;
        }}
        button:hover {{ transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
        .btn-correct {{ background: #4CAF50; color: white; border-color: #45a049; }}
        .btn-correct:hover {{ background: #45a049; }}
        .btn-false {{ background: #f44336; color: white; border-color: #da190b; }}
        .btn-false:hover {{ background: #da190b; }}
        .btn-uncertain {{ background: #ff9800; color: white; border-color: #e68900; }}
        .btn-uncertain:hover {{ background: #e68900; }}
        .verdict-status {{
            margin-top: 10px;
            padding: 8px 12px;
            border-radius: 3px;
            font-size: 13px;
            font-weight: bold;
            text-align: center;
        }}
        .verdict-correct {{ background: #c8e6c9; color: #2e7d32; }}
        .verdict-false {{ background: #ffcdd2; color: #c62828; }}
        .verdict-uncertain {{ background: #ffe0b2; color: #e65100; }}
        .summary {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .summary-row {{
            display: grid;
            grid-template-columns: 150px 1fr;
            margin-bottom: 8px;
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }}
        .summary-row:last-child {{ border-bottom: none; }}
        .summary-label {{ font-weight: bold; color: #2c3e50; }}
        .summary-value {{ color: #555; }}
        .note {{
            background: #fff3cd;
            border-left: 4px solid #ff9800;
            padding: 12px;
            border-radius: 4px;
            margin-top: 12px;
        }}
        .actions {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 12px;
        }}
        .actions button {{
            flex: 0 0 auto;
            background: #0066cc;
            color: white;
            border-color: #0052a3;
        }}
        .pagination {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-top: 12px;
            flex-wrap: wrap;
        }}
        .pagination-bottom {{
            background: white;
            padding: 16px 20px;
            border-radius: 8px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .pagination button {{
            flex: 0 0 auto;
            background: #374151;
            color: white;
            border-color: #1f2937;
            min-width: 120px;
        }}
        .pagination button:disabled {{
            opacity: 0.45;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }}
        .page-info {{
            font-size: 13px;
            color: #555;
        }}
        .entity-table {{
            width: 100%;
            margin-top: 14px;
            border-collapse: collapse;
            background: white;
            border-radius: 6px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .entity-table th, .entity-table td {{
            padding: 8px 10px;
            border-bottom: 1px solid #eee;
            font-size: 13px;
            text-align: left;
        }}
        .entity-table th {{
            background: #f7f9fc;
            color: #2c3e50;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Ground Truth Verification</h1>
        <p>Review each matched enriched-to-flat resolution pair. Verify if they truly match.</p>
        <div class="note">
            <strong>Workflow:</strong> label each sample as correct, false positive, or uncertain. The labels persist in your browser until you export the summary.
        </div>
        <div class="actions">
            <button onclick="exportVerification()">Export Summary</button>
        </div>
        <div class="pagination">
            <button class="prev-page-button" onclick="previousPage()">Previous</button>
            <div class="page-info">Page 1 of 1</div>
            <button class="next-page-button" onclick="nextPage()">Next</button>
        </div>
        <table class="entity-table">
            <thead>
                <tr><th>Entity type</th><th>Enriched total</th><th>Matched total</th></tr>
            </thead>
            <tbody>
                <tr><td>Places</td><td id="placesEnrichedTotal">0</td><td id="placesMatchedTotal">0</td></tr>
                <tr><td>Persons</td><td id="personsEnrichedTotal">0</td><td id="personsMatchedTotal">0</td></tr>
                <tr><td>Organizations</td><td id="orgsEnrichedTotal">0</td><td id="orgsMatchedTotal">0</td></tr>
            </tbody>
        </table>
        <div class="progress-bar">
            <div class="progress-fill" id="progressFill" style="width: 0%">0%</div>
        </div>
    </div>

    <div id="samplesContainer"></div>

    <div class="pagination pagination-bottom">
        <button class="prev-page-button" onclick="previousPage()">Previous</button>
        <div class="page-info">Page 1 of 1</div>
        <button class="next-page-button" onclick="nextPage()">Next</button>
    </div>

    <div class="summary">
        <h2>Verification Summary</h2>
        <div class="summary-row"><div class="summary-label">Total Samples:</div><div class="summary-value" id="totalCount">0</div></div>
        <div class="summary-row"><div class="summary-label">Correct:</div><div class="summary-value" id="correctCount">0</div></div>
        <div class="summary-row"><div class="summary-label">False Positives:</div><div class="summary-value" id="falseCount">0</div></div>
        <div class="summary-row"><div class="summary-label">Uncertain:</div><div class="summary-value" id="uncertainCount">0</div></div>
        <div class="summary-row"><div class="summary-label">Not Verified:</div><div class="summary-value" id="notVerifiedCount">0</div></div>
        <div class="summary-row"><div class="summary-label">Total Enriched Entities:</div><div class="summary-value" id="totalEnrichedEntities">0</div></div>
        <div class="summary-row"><div class="summary-label">Matched Entities:</div><div class="summary-value" id="totalMatchedEntities">0</div></div>
        <div class="summary-row"><div class="summary-label">Places / Persons / Orgs:</div><div class="summary-value" id="entityTypeCounts">0 / 0 / 0</div></div>
    </div>

    <script>
        const samples = {samples_json};
        const verdicts = {{}};
        const pageSize = {page_size};
        let currentPage = 1;

        function totalPages() {{
            return Math.max(1, Math.ceil(samples.length / pageSize));
        }}

        function clampPage(page) {{
            return Math.min(Math.max(page, 1), totalPages());
        }}

        function renderSamples() {{
            const container = document.getElementById('samplesContainer');
            container.innerHTML = '';

            const start = (currentPage - 1) * pageSize;
            const pageSamples = samples.slice(start, start + pageSize);

            pageSamples.forEach((sample) => {{
                const sampleId = sample.sample_id;
                const verdict = verdicts[sampleId] || null;

                let verdictClass = '';
                let verdictText = '';
                if (verdict === 0) {{
                    verdictClass = 'verdict-correct';
                    verdictText = '✓ CORRECT';
                }} else if (verdict === 1) {{
                    verdictClass = 'verdict-false';
                    verdictText = '✗ FALSE POSITIVE';
                }} else if (verdict === '?') {{
                    verdictClass = 'verdict-uncertain';
                    verdictText = '? UNCERTAIN';
                }}

                const html = `
                    <div class="sample-container">
                        <div class="sample-header">
                            <div>
                                <div class="sample-number">Sample #${{sampleId}}</div>
                                <div class="sample-meta">Enriched: ${{sample.enriched_date}} | Flat: ${{sample.flat_date}}</div>
                            </div>
                            <div>${{sample.is_summary_anchor ? '🔗 Summary Anchor' : ''}}</div>
                        </div>
                        <div class="sample-body">
                            <div class="metadata">
                                <div class="metadata-row">
                                    <div class="metadata-label">Dates Match:</div>
                                    <div class="metadata-value">${{sample.is_same_day ? '✓ Same day' : '✗ ' + sample.date_diff_days + ' days apart'}}</div>
                                </div>
                                <div class="metadata-row">
                                    <div class="metadata-label">Confidence:</div>
                                    <div class="metadata-value">${{sample.confidence_score}} (higher = more certain)</div>
                                </div>
                            </div>

                            <div class="entities">
                                <div class="entity-type">
                                    <h4>📍 Places</h4>
                                    <div class="entity-count">${{sample.entities.places.matched_count}}/${{sample.entities.places.total_in_enriched}}</div>
                                </div>
                                <div class="entity-type">
                                    <h4>👤 Persons</h4>
                                    <div class="entity-count">${{sample.entities.persons.matched_count}}/${{sample.entities.persons.total_in_enriched}}</div>
                                </div>
                                <div class="entity-type">
                                    <h4>🏢 Organizations</h4>
                                    <div class="entity-count">${{sample.entities.organizations.matched_count}}/${{sample.entities.organizations.total_in_enriched}}</div>
                                </div>
                            </div>

                            <div class="comparison">
                                <div class="text-box">
                                    <h3>Enriched Resolution</h3>
                                    <div class="text">${{sample.enriched_preview}}</div>
                                </div>
                                <div class="text-box">
                                    <h3>Flat Resolution (HTR)</h3>
                                    <div class="text">${{sample.flat_preview}}</div>
                                </div>
                            </div>

                            <div class="verdict-buttons">
                                <button class="btn-correct" onclick="setVerdict(${{sampleId}}, 0)">Correct</button>
                                <button class="btn-false" onclick="setVerdict(${{sampleId}}, 1)">False Positive</button>
                                <button class="btn-uncertain" onclick="setVerdict(${{sampleId}}, '?')">Uncertain</button>
                            </div>

                            ${{verdictText ? `<div class="verdict-status ${{verdictClass}}">${{verdictText}}</div>` : ''}}
                        </div>
                    </div>
                `;

                container.insertAdjacentHTML('beforeend', html);
            }});

            updatePagination();
        }}

        function updatePagination() {{
            const total = totalPages();
            const pageLabel = `Page ${{currentPage}} of ${{total}}`;
            document.querySelectorAll('.page-info').forEach((element) => {{
                element.textContent = pageLabel;
            }});
            document.querySelectorAll('.prev-page-button').forEach((button) => {{
                button.disabled = currentPage <= 1;
            }});
            document.querySelectorAll('.next-page-button').forEach((button) => {{
                button.disabled = currentPage >= total;
            }});
        }}

        function previousPage() {{
            currentPage = clampPage(currentPage - 1);
            renderSamples();
        }}

        function nextPage() {{
            currentPage = clampPage(currentPage + 1);
            renderSamples();
        }}

        function setVerdict(sampleId, verdict) {{
            verdicts[sampleId] = verdict;
            renderSamples();
            updateSummary();
            saveToLocalStorage();
        }}

        function updateSummary() {{
            const total = samples.length;
            const correct = Object.values(verdicts).filter(v => v === 0).length;
            const falsePos = Object.values(verdicts).filter(v => v === 1).length;
            const uncertain = Object.values(verdicts).filter(v => v === '?').length;
            const notVerified = total - Object.keys(verdicts).length;
            const enrichedTotals = {{ places: 0, persons: 0, organizations: 0 }};
            const matchedTotals = {{ places: 0, persons: 0, organizations: 0 }};

            samples.forEach((sample) => {{
                enrichedTotals.places += sample.entities.places.total_in_enriched;
                enrichedTotals.persons += sample.entities.persons.total_in_enriched;
                enrichedTotals.organizations += sample.entities.organizations.total_in_enriched;
                matchedTotals.places += sample.entities.places.matched_count;
                matchedTotals.persons += sample.entities.persons.matched_count;
                matchedTotals.organizations += sample.entities.organizations.matched_count;
            }});

            document.getElementById('totalCount').textContent = total;
            document.getElementById('correctCount').textContent = correct;
            document.getElementById('falseCount').textContent = falsePos;
            document.getElementById('uncertainCount').textContent = uncertain;
            document.getElementById('notVerifiedCount').textContent = notVerified;
            document.getElementById('totalEnrichedEntities').textContent = enrichedTotals.places + enrichedTotals.persons + enrichedTotals.organizations;
            document.getElementById('totalMatchedEntities').textContent = matchedTotals.places + matchedTotals.persons + matchedTotals.organizations;
            document.getElementById('entityTypeCounts').textContent = `${{enrichedTotals.places}} / ${{enrichedTotals.persons}} / ${{enrichedTotals.organizations}}`;
            document.getElementById('placesEnrichedTotal').textContent = enrichedTotals.places;
            document.getElementById('placesMatchedTotal').textContent = matchedTotals.places;
            document.getElementById('personsEnrichedTotal').textContent = enrichedTotals.persons;
            document.getElementById('personsMatchedTotal').textContent = matchedTotals.persons;
            document.getElementById('orgsEnrichedTotal').textContent = enrichedTotals.organizations;
            document.getElementById('orgsMatchedTotal').textContent = matchedTotals.organizations;

            const percentage = Math.round((Object.keys(verdicts).length / total) * 100);
            document.getElementById('progressFill').style.width = percentage + '%';
            document.getElementById('progressFill').textContent = percentage + '%';
        }}

        function saveToLocalStorage() {{
            localStorage.setItem('verdicts', JSON.stringify(verdicts));
        }}

        function loadFromLocalStorage() {{
            const saved = localStorage.getItem('verdicts');
            if (saved) {{
                Object.assign(verdicts, JSON.parse(saved));
            }}
        }}

        function exportVerification() {{
            const correct = samples.filter(s => verdicts[s.sample_id] === 0);
            const report = {{
                total: samples.length,
                verified: Object.keys(verdicts).length,
                correct: correct.length,
                false_positives: Object.values(verdicts).filter(v => v === 1).length,
                uncertain: Object.values(verdicts).filter(v => v === '?').length,
                accuracy: (correct.length / samples.length * 100).toFixed(1),
                verdicts: verdicts,
            }};

            const json = JSON.stringify(report, null, 2);
            const blob = new Blob([json], {{ type: 'application/json' }});
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'ground_truth_verification_summary.json';
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);

            console.log(json);
            alert('Verification summary downloaded as ground_truth_verification_summary.json');
        }}

        window.addEventListener('load', () => {{
            loadFromLocalStorage();
            renderSamples();
            updateSummary();
        }});
    </script>
</body>
</html>
"""
    output_file.write_text(html_content, encoding="utf-8")
    print(f"✓ Verification interface saved to: {output_file}")


def run(
    preview_limit: int,
    stratified_size: int,
    focus_entities: list[str] | None = None,
    focus_limit: int = 10,
    verification_page_size: int = 5,
) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    enriched_all, res_df, loc_names, per_names, org_names = load_data()
    anchor_map = build_date_anchor_map(enriched_all, res_df, loc_names, per_names, org_names)
    print(f"✓ Anchor map: {len(anchor_map)} confirmed date anchors")

    preview_matches = build_preview_matches(enriched_all, res_df, loc_names, per_names, org_names, anchor_map=anchor_map, limit=preview_limit)
    write_preview_html(preview_matches, OUTPUT_DIR / "matched_resolutions_sample.html")

    stratified_matches = build_stratified_matches(enriched_all, res_df, loc_names, per_names, org_names, anchor_map=anchor_map, sample_size=stratified_size)
    focus_matches: list[dict[str, Any]] = []
    if focus_entities:
        focus_matches = build_focus_matches(
            enriched_all,
            res_df,
            loc_names,
            per_names,
            org_names,
            focus_entities,
            anchor_map=anchor_map,
            limit=focus_limit,
        )

    combined_matches = list(stratified_matches)

    if focus_matches:
        seen_keys = {
            (
                item["enriched"].get("file"),
                item["enriched"].get("resolution_index"),
                item["best_match"].get("id"),
            )
            for item in stratified_matches
        }
        for item in focus_matches:
            key = (
                item["enriched"].get("file"),
                item["enriched"].get("resolution_index"),
                item["best_match"].get("id"),
            )
            if key not in seen_keys:
                combined_matches.append(item)
                seen_keys.add(key)

    if combined_matches:
        ground_truth = export_ground_truth(combined_matches, OUTPUT_DIR)
        export_matched_pairs_evidence(ground_truth, OUTPUT_DIR)
        export_curated_matched_pairs(ground_truth, OUTPUT_DIR)
        write_verification_html(ground_truth, OUTPUT_DIR / "verify_ground_truth.html", page_size=verification_page_size)
    else:
        print("No stratified matches were produced; skipping ground-truth export.")


def run_frequency_sampling(
    preview_limit: int,
    top_n: int,
    limit: int,
) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    enriched_all, res_df, loc_names, per_names, org_names = load_data()

    frequency_matches, frequency_entities = build_frequency_matches(
        enriched_all,
        res_df,
        loc_names,
        per_names,
        org_names,
        anchor_map=anchor_map,
        top_n=top_n,
        limit=limit,
    )

    if not frequency_matches:
        print("No frequency-driven matches were produced; skipping frequency report export.")
        return

    output_html = OUTPUT_DIR / "matched_resolutions_frequency_sample.html"
    write_preview_html(
        frequency_matches,
        output_html,
        report_title="Frequency-Based Resolution Sample",
        report_heading="Frequency-Driven Resolution Sampling",
    )

    summary_file = OUTPUT_DIR / "frequency_sample_summary.json"
    summary_file.write_text(
        json.dumps(
            {
                "samples": len(frequency_matches),
                "previewed_entities": len(frequency_entities),
                "top_entities": frequency_entities,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"✓ Frequency report saved to: {output_html}")
    print(f"✓ Frequency summary saved to: {summary_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate alignment preview and ground-truth exports.")
    parser.add_argument("--preview-limit", type=int, default=8, help="Number of preview rows to render in the HTML sample report.")
    parser.add_argument("--stratified-size", type=int, default=30, help="Target sample size for stratified ground-truth generation.")
    parser.add_argument(
        "--focus-entity",
        action="append",
        default=[],
        help="Bias the sample toward specific entity names. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--focus-limit",
        type=int,
        default=10,
        help="How many focused matches to try adding on top of the stratified sample.",
    )
    parser.add_argument(
        "--verification-page-size",
        type=int,
        default=5,
        help="How many verification samples to show per page in the ground-truth HTML.",
    )
    parser.add_argument(
        "--frequency-report",
        action="store_true",
        help="Generate a separate frequency-based sample report instead of the ground-truth verification output.",
    )
    parser.add_argument(
        "--frequency-top-n",
        type=int,
        default=5,
        help="How many of the most frequent entities per entity type to consider for the frequency report.",
    )
    parser.add_argument(
        "--frequency-limit",
        type=int,
        default=12,
        help="How many frequency-driven matches to include in the separate frequency report.",
    )
    args = parser.parse_args()
    if args.frequency_report:
        run_frequency_sampling(
            preview_limit=args.preview_limit,
            top_n=args.frequency_top_n,
            limit=args.frequency_limit,
        )
    else:
        run(
            preview_limit=args.preview_limit,
            stratified_size=args.stratified_size,
            focus_entities=args.focus_entity,
            focus_limit=args.focus_limit,
            verification_page_size=args.verification_page_size,
        )


if __name__ == "__main__":
    main()

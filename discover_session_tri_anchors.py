#!/usr/bin/env python3
"""Discover begin / middle / end anchors per calendar-day sitting.

In flat ids, ``session-3186`` is an **inventory volume** (a year's book), not a
single meeting. A *session* is one sitting **per calendar day**. Anchors and
interpolation are scoped to ``(inventory_id, calendar_date)`` and never cross
day or inventory boundaries.

Usage:
    uv run python discover_session_tri_anchors.py
    uv run python discover_session_tri_anchors.py --inventories session-3186 --dates 1627-09-02
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from analyze_sequence_entity_overlap import (
    build_enriched_by_date,
    paragraphs_in_sessions,
    parse_paragraph_position,
)
from build_alignment_new import (
    ENRICHED_FILE,
    LOC_ENTITIES_FILE,
    ORG_ENTITIES_FILE,
    OUTPUT_DIR,
    PER_ENTITIES_FILE,
    PERSON_SIGNAL_SCALE,
    RESOLUTIONS_FILE,
    build_date_to_session_map,
    build_paragraph_to_resolution_map,
    enriched_volgnr,
    extract_session_id,
    load_entity_names,
    load_json,
    paragraph_mapping_annotation_files,
    resolve_enriched_entities,
)
from entity_bridge_review import (
    APPROVAL_SCORE_BONUS,
    QUEUE_FILE,
    REVIEW_HTML,
    approval_bonus_for_pair,
    build_entity_bridge_queue,
    filtered_entity_names,
    load_bridge_decisions,
    write_entity_bridge_review_html,
)

MIN_ANCHOR_SCORE = 2.0
DEFAULT_OFFSET_PENALTY = 0.35
MIDDLE_THIRD_START = 1 / 3
MIDDLE_THIRD_END = 2 / 3


def classify_bridge_kind(has_place: bool, has_org: bool, has_person: bool) -> str:
    parts: list[str] = []
    if has_place:
        parts.append("place")
    if has_org:
        parts.append("org")
    if has_person:
        parts.append("person")
    return "+".join(parts) if parts else "none"


def qualifies_anchor_pair(
    anchor_score: float,
    person_score: float,
    combined_score: float,
    *,
    has_place: bool,
    has_org: bool,
    has_person: bool,
    same_day: bool,
    require_same_day: bool = True,
) -> bool:
    """Accept place, org, or person bridges when combined IDF score clears threshold."""
    if require_same_day and not same_day:
        return False
    if not (has_place or has_org or has_person):
        return False
    return combined_score >= MIN_ANCHOR_SCORE


def bridge_tags_for_pair(
    enriched_id: str,
    paragraph_id: str,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    *,
    rejected: set[str] | None = None,
) -> dict[str, list[str]]:
    rejected = rejected or set()
    return {
        "places": sorted(
            filtered_entity_names(
                place_lookup.get((enriched_id, paragraph_id), set()),
                enriched_id,
                paragraph_id,
                "place",
                rejected,
            )
        ),
        "orgs": sorted(
            filtered_entity_names(
                org_lookup.get((enriched_id, paragraph_id), set()),
                enriched_id,
                paragraph_id,
                "org",
                rejected,
            )
        ),
        "persons": sorted(
            filtered_entity_names(
                person_lookup.get((enriched_id, paragraph_id), set()),
                enriched_id,
                paragraph_id,
                "person",
                rejected,
            )
        ),
    }


def collect_overlap_tags_by_volgnr(
    volgnr: str,
    paragraph_ids: set[str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None,
) -> dict[str, list[str]]:
    tags = {"places": set(), "orgs": set(), "persons": set()}
    paragraph_filter = {str(pid) for pid in paragraph_ids}
    for source_df, key in (
        (places_df, "places"),
        (orgs_df, "orgs"),
        (persons_df, "persons"),
    ):
        if source_df is None or source_df.empty:
            continue
        mask = (source_df["volgnr"].astype(str) == volgnr) & (
            source_df["paragraph_id"].astype(str).isin(paragraph_filter)
        )
        for name in source_df.loc[mask, "name"].dropna().astype(str):
            cleaned = name.strip()
            if cleaned:
                tags[key].add(cleaned)
    return {key: sorted(values) for key, values in tags.items()}


def collect_overlap_tags_by_paragraph(
    paragraph_id: str,
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None,
) -> dict[str, list[str]]:
    tags = {"places": set(), "orgs": set(), "persons": set()}
    for source_df, key in (
        (places_df, "places"),
        (orgs_df, "orgs"),
        (persons_df, "persons"),
    ):
        if source_df is None or source_df.empty:
            continue
        mask = source_df["paragraph_id"].astype(str) == paragraph_id
        for name in source_df.loc[mask, "name"].dropna().astype(str):
            cleaned = name.strip()
            if cleaned:
                tags[key].add(cleaned)
    return {key: sorted(values) for key, values in tags.items()}


def build_enriched_tag_list(
    enriched_items: list[dict[str, Any]],
    paragraph_ids: list[str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None,
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
) -> list[dict[str, Any]]:
    paragraph_filter = set(paragraph_ids)
    tagged: list[dict[str, Any]] = []
    for item in enriched_items:
        enriched_id = enriched_volgnr(item) or ""
        if not enriched_id:
            continue
        editorial = resolve_enriched_entities(item, loc_names, per_names, org_names)
        overlap_bridges = collect_overlap_tags_by_volgnr(
            enriched_id,
            paragraph_filter,
            places_df,
            orgs_df,
            persons_df,
        )
        tagged.append(
            {
                "enriched_id": enriched_id,
                "resolution_index": item.get("resolution_index"),
                "editorial": {
                    "places": editorial["places"],
                    "orgs": editorial["orgs"],
                    "persons": editorial["persons"],
                },
                "overlap_bridges": overlap_bridges,
            }
        )
    return tagged


def build_flat_tag_list(
    paragraph_ids: list[str],
    paragraph_to_resolution: dict[str, str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for paragraph_id in paragraph_ids:
        tagged.append(
            {
                "paragraph_id": paragraph_id,
                "resolution_id": paragraph_to_resolution.get(paragraph_id, ""),
                "overlap_tags": collect_overlap_tags_by_paragraph(
                    paragraph_id,
                    places_df,
                    orgs_df,
                    persons_df,
                ),
            }
        )
    return tagged


def invert_date_to_sessions(date_to_sessions: dict[str, set[str]]) -> dict[str, list[str]]:
    session_to_dates: dict[str, list[str]] = defaultdict(list)
    for date_str, sessions in date_to_sessions.items():
        for session_id in sessions:
            session_to_dates[session_id].append(date_str)
    for session_id in session_to_dates:
        session_to_dates[session_id] = sorted(set(session_to_dates[session_id]))
    return dict(session_to_dates)


def load_manual_pin_records(
    output_dir: Path,
    *,
    paragraph_to_resolution: dict[str, str] | None = None,
    places_df: pd.DataFrame | None = None,
    orgs_df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    from session_chain_alignment import load_manual_pin_records as _load

    return _load(
        output_dir,
        paragraph_to_resolution=paragraph_to_resolution,
        places_df=places_df,
        orgs_df=orgs_df,
    )


@dataclass
class AnchorRecord:
    role: str
    enriched_id: str
    enriched_index: int
    paragraph_id: str
    paragraph_index: int
    enriched_date: str
    flat_date: str
    anchor_score: float
    person_score: float
    combined_score: float
    same_day: bool
    has_place: bool
    has_org: bool
    has_person: bool
    match_kind: str
    bridge_tags: dict[str, list[str]]
    source: str
    confidence: float


@dataclass
class DailyTriAnchors:
    """Tri-anchors for one calendar-day sitting inside an inventory volume."""

    inventory_id: str
    calendar_date: str
    enriched_count: int
    paragraph_count: int
    complete: bool
    start: AnchorRecord | None = None
    middle: AnchorRecord | None = None
    end: AnchorRecord | None = None
    notes: list[str] = field(default_factory=list)
    enriched_tagged: list[dict[str, Any]] = field(default_factory=list)
    flat_tagged: list[dict[str, Any]] = field(default_factory=list)

    @property
    def day_key(self) -> str:
        return make_day_key(self.inventory_id, self.calendar_date)

    @property
    def session_id(self) -> str:
        """Backward-compatible alias (inventory volume id in flat ids)."""
        return self.inventory_id

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["day_key"] = self.day_key
        payload["session_id"] = self.inventory_id
        for role in ("start", "middle", "end"):
            value = getattr(self, role)
            payload[role] = asdict(value) if value else None
        return payload


# Backward-compatible alias
SessionTriAnchors = DailyTriAnchors


def make_day_key(inventory_id: str, calendar_date: str) -> str:
    return f"{inventory_id}|{calendar_date}"


def parse_day_key(day_key: str) -> tuple[str, str]:
    inventory_id, calendar_date = day_key.split("|", 1)
    return inventory_id, calendar_date


def build_paragraph_flat_dates(
    paragraph_to_resolution: dict[str, str],
    res_df: pd.DataFrame,
) -> dict[str, str]:
    resolution_dates = dict(
        zip(res_df["id"].astype(str), res_df["date"].astype(str).str[:10], strict=False)
    )
    return {
        paragraph_id: resolution_dates.get(str(resolution_id), "")
        for paragraph_id, resolution_id in paragraph_to_resolution.items()
    }


def iter_inventory_calendar_days(
    date_to_sessions: dict[str, set[str]],
    *,
    inventory_filter: set[str] | None = None,
    date_filter: set[str] | None = None,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for calendar_date in sorted(date_to_sessions):
        if date_filter and calendar_date not in date_filter:
            continue
        for inventory_id in sorted(date_to_sessions[calendar_date]):
            if inventory_filter and inventory_id not in inventory_filter:
                continue
            pairs.append((inventory_id, calendar_date))
    return pairs


def enriched_items_for_day(
    calendar_date: str,
    enriched_by_date: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    items = list(enriched_by_date.get(calendar_date, []))
    items.sort(key=lambda row: int(row.get("resolution_index", 0)))
    return items


def enriched_volgnrs_for_inventory_day(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    inventory_id: str,
    calendar_date: str,
    paragraph_to_resolution: dict[str, str],
) -> set[str]:
    volgnrs: set[str] = set()
    for source_df in (places_df, orgs_df):
        for _, row in source_df.iterrows():
            if pd.isna(row.get("volgnr")) or pd.isna(row.get("paragraph_id")):
                continue
            volgnr = str(row["volgnr"]).strip()
            if not volgnr.startswith(calendar_date):
                continue
            paragraph_id = str(row["paragraph_id"]).strip()
            flat_id = paragraph_to_resolution.get(paragraph_id, "")
            if extract_session_id(flat_id) != inventory_id:
                continue
            volgnrs.add(volgnr)
    return volgnrs


def enriched_items_for_inventory_day(
    inventory_id: str,
    calendar_date: str,
    enriched_by_date: dict[str, list[dict[str, Any]]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    date_to_sessions: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Enriched resolutions for one inventory sitting on a calendar day."""
    day_items = enriched_items_for_day(calendar_date, enriched_by_date)
    volgnrs = enriched_volgnrs_for_inventory_day(
        places_df,
        orgs_df,
        inventory_id,
        calendar_date,
        paragraph_to_resolution,
    )
    if volgnrs:
        return [item for item in day_items if (enriched_volgnr(item) or "") in volgnrs]
    sessions_on_date = date_to_sessions.get(calendar_date, set()) if date_to_sessions else set()
    if sessions_on_date == {inventory_id}:
        return day_items
    return []


def paragraphs_for_inventory_on_date(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    inventory_id: str,
    calendar_date: str,
    paragraph_flat_dates: dict[str, str],
) -> list[str]:
    inventory_paragraphs = paragraphs_in_sessions(places_df, orgs_df, {inventory_id})
    day_paragraphs = [
        paragraph_id
        for paragraph_id in inventory_paragraphs
        if paragraph_flat_dates.get(paragraph_id, "")[:10] == calendar_date
    ]
    return sorted(day_paragraphs, key=lambda pid: parse_paragraph_position(pid) or (0, 0, 0))


def pin_map_for_day(
    inventory_id: str,
    calendar_date: str,
    enriched_ids: list[str],
    paragraph_ids: list[str],
    manual_pins: list[dict[str, Any]],
    state_pins: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """enriched_id -> paragraph_id for explicit pins on this inventory day."""
    mapping: dict[str, str] = {}
    for record in list(manual_pins) + list(state_pins or []):
        if str(record.get("session_id", "")) != inventory_id:
            continue
        enriched_id = str(record.get("enriched_id", ""))
        if not enriched_id.startswith(calendar_date):
            continue
        paragraph_id = str(
            record.get("paragraph_id") or record.get("corrected_paragraph_id") or ""
        )
        if enriched_id in enriched_ids and paragraph_id in paragraph_ids:
            mapping[enriched_id] = paragraph_id
    return mapping


# Deprecated inventory-year helpers kept for imports elsewhere.
def enriched_items_for_session(
    session_id: str,
    enriched_by_date: dict[str, list[dict[str, Any]]],
    session_to_dates: dict[str, list[str]],
    date_to_sessions: dict[str, set[str]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for date_str in session_to_dates.get(session_id, []):
        if session_id not in date_to_sessions.get(date_str, set()):
            continue
        for item in enriched_by_date.get(date_str, []):
            enriched_id = enriched_volgnr(item) or ""
            if not enriched_id or enriched_id in seen:
                continue
            items.append(item)
            seen.add(enriched_id)
    items.sort(
        key=lambda row: (
            str(row.get("date", ""))[:10],
            int(row.get("resolution_index", 0)),
        )
    )
    return items


def pin_map_for_session(
    session_id: str,
    enriched_ids: list[str],
    paragraph_ids: list[str],
    manual_pins: list[dict[str, Any]],
    state_pins: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """enriched_id -> paragraph_id for explicit pins in this session."""
    mapping: dict[str, str] = {}
    for record in list(manual_pins) + list(state_pins or []):
        if str(record.get("session_id", "")) != session_id:
            continue
        enriched_id = str(record.get("enriched_id", ""))
        paragraph_id = str(
            record.get("paragraph_id") or record.get("corrected_paragraph_id") or ""
        )
        if enriched_id in enriched_ids and paragraph_id in paragraph_ids:
            mapping[enriched_id] = paragraph_id
    return mapping


def score_pair(
    enriched_id: str,
    enriched_date: str,
    paragraph_id: str,
    flat_date: str,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    *,
    approved_bridges: set[str] | None = None,
    rejected_bridges: set[str] | None = None,
) -> tuple[float, float, float, bool, bool, bool, bool]:
    approved_bridges = approved_bridges or set()
    rejected_bridges = rejected_bridges or set()
    pair = (enriched_id, paragraph_id)
    place_names = filtered_entity_names(
        place_lookup.get(pair, set()), enriched_id, paragraph_id, "place", rejected_bridges
    )
    org_names = filtered_entity_names(
        org_lookup.get(pair, set()), enriched_id, paragraph_id, "org", rejected_bridges
    )
    person_names = filtered_entity_names(
        person_lookup.get(pair, set()), enriched_id, paragraph_id, "person", rejected_bridges
    )
    anchor_score = sum(idf_weights.get(name, 1.0) for name in place_names | org_names)
    person_score = PERSON_SIGNAL_SCALE * sum(idf_weights.get(name, 1.0) for name in person_names)
    combined = anchor_score + person_score + approval_bonus_for_pair(
        enriched_id,
        paragraph_id,
        place_lookup,
        org_lookup,
        person_lookup,
        approved_bridges,
        idf_weights,
        bonus=APPROVAL_SCORE_BONUS,
    )
    has_place = bool(place_names)
    has_org = bool(org_names)
    has_person = bool(person_names)
    same_day = bool(enriched_date and flat_date and enriched_date[:10] == flat_date[:10])
    return anchor_score, person_score, combined, same_day, has_place, has_org, has_person


def make_anchor_record(
    role: str,
    enriched_id: str,
    enriched_index: int,
    enriched_date: str,
    paragraph_id: str,
    paragraph_index: int,
    flat_date: str,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    *,
    source: str,
    approved_bridges: set[str] | None = None,
    rejected_bridges: set[str] | None = None,
) -> AnchorRecord:
    anchor_score, person_score, combined, same_day, has_place, has_org, has_person = score_pair(
        enriched_id,
        enriched_date,
        paragraph_id,
        flat_date,
        place_lookup,
        org_lookup,
        person_lookup,
        idf_weights,
        approved_bridges=approved_bridges,
        rejected_bridges=rejected_bridges,
    )
    bridge_tags = bridge_tags_for_pair(
        enriched_id,
        paragraph_id,
        place_lookup,
        org_lookup,
        person_lookup,
        rejected=rejected_bridges,
    )
    return AnchorRecord(
        role=role,
        enriched_id=enriched_id,
        enriched_index=enriched_index,
        paragraph_id=paragraph_id,
        paragraph_index=paragraph_index,
        enriched_date=enriched_date[:10],
        flat_date=flat_date[:10],
        anchor_score=round(anchor_score, 3),
        person_score=round(person_score, 3),
        combined_score=round(combined, 3),
        same_day=same_day,
        has_place=has_place,
        has_org=has_org,
        has_person=has_person,
        match_kind=classify_bridge_kind(has_place, has_org, has_person),
        bridge_tags=bridge_tags,
        source=source,
        confidence=round(min(1.0, combined / 10.0), 3) if source != "pin" else 1.0,
    )


def candidate_from_pin(
    role: str,
    enriched_id: str,
    enriched_index: int,
    enriched_date: str,
    paragraph_id: str,
    paragraph_index: int,
    flat_date: str,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    *,
    approved_bridges: set[str] | None = None,
    rejected_bridges: set[str] | None = None,
) -> AnchorRecord:
    return make_anchor_record(
        role,
        enriched_id,
        enriched_index,
        enriched_date,
        paragraph_id,
        paragraph_index,
        flat_date,
        place_lookup,
        org_lookup,
        person_lookup,
        idf_weights,
        source="pin",
        approved_bridges=approved_bridges,
        rejected_bridges=rejected_bridges,
    )


def best_auto_candidate_in_range(
    role: str,
    enriched_ids: list[str],
    enriched_dates: list[str],
    paragraph_ids: list[str],
    paragraph_dates: list[str],
    index_range: range,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    *,
    require_same_day: bool = True,
    approved_bridges: set[str] | None = None,
    rejected_bridges: set[str] | None = None,
) -> AnchorRecord | None:
    best: AnchorRecord | None = None
    for enriched_index in index_range:
        enriched_id = enriched_ids[enriched_index]
        enriched_date = enriched_dates[enriched_index]
        for paragraph_index, paragraph_id in enumerate(paragraph_ids):
            flat_date = paragraph_dates[paragraph_index]
            anchor_score, person_score, combined, same_day, has_place, has_org, has_person = score_pair(
                enriched_id,
                enriched_date,
                paragraph_id,
                flat_date,
                place_lookup,
                org_lookup,
                person_lookup,
                idf_weights,
                approved_bridges=approved_bridges,
                rejected_bridges=rejected_bridges,
            )
            if not qualifies_anchor_pair(
                anchor_score,
                person_score,
                combined,
                has_place=has_place,
                has_org=has_org,
                has_person=has_person,
                same_day=same_day,
                require_same_day=require_same_day,
            ):
                continue
            record = make_anchor_record(
                role,
                enriched_id,
                enriched_index,
                enriched_date,
                paragraph_id,
                paragraph_index,
                flat_date,
                place_lookup,
                org_lookup,
                person_lookup,
                idf_weights,
                source="auto",
                approved_bridges=approved_bridges,
                rejected_bridges=rejected_bridges,
            )
            if best is None or record.combined_score > best.combined_score:
                best = record
    return best


def pick_boundary_candidate(
    role: str,
    enriched_ids: list[str],
    enriched_dates: list[str],
    paragraph_ids: list[str],
    paragraph_dates: list[str],
    pin_map: dict[str, str],
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    *,
    from_start: bool,
    approved_bridges: set[str] | None = None,
    rejected_bridges: set[str] | None = None,
) -> AnchorRecord | None:
    indices = range(len(enriched_ids))
    if from_start:
        scan = indices
    else:
        scan = reversed(indices)
    for enriched_index in scan:
        enriched_id = enriched_ids[enriched_index]
        if enriched_id in pin_map:
            paragraph_id = pin_map[enriched_id]
            return candidate_from_pin(
                role,
                enriched_id,
                enriched_index,
                enriched_dates[enriched_index],
                paragraph_id,
                paragraph_ids.index(paragraph_id),
                paragraph_dates[paragraph_ids.index(paragraph_id)],
                place_lookup,
                org_lookup,
                person_lookup,
                idf_weights,
                approved_bridges=approved_bridges,
                rejected_bridges=rejected_bridges,
            )
        enriched_date = enriched_dates[enriched_index]
        best_for_row: AnchorRecord | None = None
        for paragraph_index, paragraph_id in enumerate(paragraph_ids):
            flat_date = paragraph_dates[paragraph_index]
            anchor_score, person_score, combined, same_day, has_place, has_org, has_person = score_pair(
                enriched_id,
                enriched_date,
                paragraph_id,
                flat_date,
                place_lookup,
                org_lookup,
                person_lookup,
                idf_weights,
                approved_bridges=approved_bridges,
                rejected_bridges=rejected_bridges,
            )
            if not qualifies_anchor_pair(
                anchor_score,
                person_score,
                combined,
                has_place=has_place,
                has_org=has_org,
                has_person=has_person,
                same_day=same_day,
            ):
                continue
            record = make_anchor_record(
                role,
                enriched_id,
                enriched_index,
                enriched_date,
                paragraph_id,
                paragraph_index,
                flat_date,
                place_lookup,
                org_lookup,
                person_lookup,
                idf_weights,
                source="auto",
                approved_bridges=approved_bridges,
                rejected_bridges=rejected_bridges,
            )
            if best_for_row is None or record.combined_score > best_for_row.combined_score:
                best_for_row = record
        if best_for_row is not None:
            return best_for_row
    return None


def enforce_monotonic_tri_anchors(
    start: AnchorRecord | None,
    middle: AnchorRecord | None,
    end: AnchorRecord | None,
) -> tuple[AnchorRecord | None, AnchorRecord | None, AnchorRecord | None, list[str]]:
    notes: list[str] = []
    if not start or not middle or not end:
        return start, middle, end, notes
    if not (start.enriched_index < middle.enriched_index < end.enriched_index):
        notes.append("enriched order violated; dropping middle anchor")
        middle = None
    elif not (start.paragraph_index < middle.paragraph_index < end.paragraph_index):
        notes.append("paragraph order violated; dropping middle anchor")
        middle = None
    return start, middle, end, notes


def discover_tri_anchors_for_day(
    inventory_id: str,
    calendar_date: str,
    enriched_by_date: dict[str, list[dict[str, Any]]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None,
    paragraph_flat_dates: dict[str, str],
    paragraph_to_resolution: dict[str, str],
    date_to_sessions: dict[str, set[str]],
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    manual_pins: list[dict[str, Any]],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    state_pins: list[dict[str, Any]] | None = None,
    *,
    approved_bridges: set[str] | None = None,
    rejected_bridges: set[str] | None = None,
) -> DailyTriAnchors:
    enriched_items = enriched_items_for_inventory_day(
        inventory_id,
        calendar_date,
        enriched_by_date,
        places_df,
        orgs_df,
        paragraph_to_resolution,
        date_to_sessions,
    )
    paragraph_ids = paragraphs_for_inventory_on_date(
        places_df,
        orgs_df,
        inventory_id,
        calendar_date,
        paragraph_flat_dates,
    )
    enriched_ids = [enriched_volgnr(item) or "" for item in enriched_items]
    enriched_dates = [calendar_date] * len(enriched_ids)
    paragraph_dates = [paragraph_flat_dates.get(pid, "")[:10] for pid in paragraph_ids]
    pin_map = pin_map_for_day(
        inventory_id,
        calendar_date,
        enriched_ids,
        paragraph_ids,
        manual_pins,
        state_pins,
    )
    enriched_tagged = build_enriched_tag_list(
        enriched_items,
        paragraph_ids,
        places_df,
        orgs_df,
        persons_df,
        loc_names,
        per_names,
        org_names,
    )
    flat_tagged = build_flat_tag_list(
        paragraph_ids,
        paragraph_to_resolution,
        places_df,
        orgs_df,
        persons_df,
    )

    notes: list[str] = []
    if not enriched_ids:
        notes.append("no enriched resolutions on calendar day")
    if not paragraph_ids:
        notes.append("no flat paragraphs on calendar day for inventory")
    if len(enriched_ids) < 3:
        notes.append("fewer than 3 enriched resolutions on day")
    if len(paragraph_ids) < 3:
        notes.append("fewer than 3 flat paragraphs on day")

    start = pick_boundary_candidate(
        "start",
        enriched_ids,
        enriched_dates,
        paragraph_ids,
        paragraph_dates,
        pin_map,
        place_lookup,
        org_lookup,
        person_lookup,
        idf_weights,
        from_start=True,
        approved_bridges=approved_bridges,
        rejected_bridges=rejected_bridges,
    )
    end = pick_boundary_candidate(
        "end",
        enriched_ids,
        enriched_dates,
        paragraph_ids,
        paragraph_dates,
        pin_map,
        place_lookup,
        org_lookup,
        person_lookup,
        idf_weights,
        from_start=False,
        approved_bridges=approved_bridges,
        rejected_bridges=rejected_bridges,
    )

    middle: AnchorRecord | None = None
    if len(enriched_ids) >= 3:
        lower = int(len(enriched_ids) * MIDDLE_THIRD_START)
        upper = max(lower + 1, int(len(enriched_ids) * MIDDLE_THIRD_END))
        middle_range = range(lower, min(upper, len(enriched_ids)))
        pinned_middle = [
            (idx, enriched_ids[idx]) for idx in middle_range if enriched_ids[idx] in pin_map
        ]
        if pinned_middle:
            idx, enriched_id = max(pinned_middle, key=lambda item: item[0])
            paragraph_id = pin_map[enriched_id]
            middle = candidate_from_pin(
                "middle",
                enriched_id,
                idx,
                enriched_dates[idx],
                paragraph_id,
                paragraph_ids.index(paragraph_id),
                paragraph_dates[paragraph_ids.index(paragraph_id)],
                place_lookup,
                org_lookup,
                person_lookup,
                idf_weights,
                approved_bridges=approved_bridges,
                rejected_bridges=rejected_bridges,
            )
        else:
            middle = best_auto_candidate_in_range(
                "middle",
                enriched_ids,
                enriched_dates,
                paragraph_ids,
                paragraph_dates,
                middle_range,
                place_lookup,
                org_lookup,
                person_lookup,
                idf_weights,
                approved_bridges=approved_bridges,
                rejected_bridges=rejected_bridges,
            )

    start, middle, end, mono_notes = enforce_monotonic_tri_anchors(start, middle, end)
    notes.extend(mono_notes)
    if len(enriched_ids) == 2 and start and end and not middle:
        complete = True
        notes.append("two-resolution day: start/end only")
    else:
        complete = start is not None and middle is not None and end is not None

    return DailyTriAnchors(
        inventory_id=inventory_id,
        calendar_date=calendar_date,
        enriched_count=len(enriched_ids),
        paragraph_count=len(paragraph_ids),
        complete=complete,
        start=start,
        middle=middle,
        end=end,
        notes=notes,
        enriched_tagged=enriched_tagged,
        flat_tagged=flat_tagged,
    )


def discover_tri_anchors_for_session(
    session_id: str,
    enriched_by_date: dict[str, list[dict[str, Any]]],
    session_to_dates: dict[str, list[str]],
    date_to_sessions: dict[str, set[str]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    paragraph_flat_dates: dict[str, str],
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    manual_pins: list[dict[str, Any]],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    persons_df: pd.DataFrame | None = None,
    state_pins: list[dict[str, Any]] | None = None,
) -> DailyTriAnchors:
    """Deprecated: use ``discover_tri_anchors_for_day``."""
    first_date = session_to_dates.get(session_id, [None])[0] if session_to_dates.get(session_id) else None
    if not first_date:
        return DailyTriAnchors(
            inventory_id=session_id,
            calendar_date="",
            enriched_count=0,
            paragraph_count=0,
            complete=False,
            notes=["no dates for inventory"],
        )
    return discover_tri_anchors_for_day(
        session_id,
        first_date,
        enriched_by_date,
        places_df,
        orgs_df,
        persons_df,
        paragraph_flat_dates,
        paragraph_to_resolution,
        date_to_sessions,
        place_lookup,
        org_lookup,
        person_lookup,
        idf_weights,
        manual_pins,
        loc_names,
        per_names,
        org_names,
        state_pins,
    )


def discover_all_daily_tri_anchors(
    date_to_sessions: dict[str, set[str]],
    enriched_by_date: dict[str, list[dict[str, Any]]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None,
    paragraph_to_resolution: dict[str, str],
    res_df: pd.DataFrame,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    manual_pins: list[dict[str, Any]],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    state_pins: list[dict[str, Any]] | None = None,
    *,
    inventory_filter: set[str] | None = None,
    date_filter: set[str] | None = None,
    output_dir: Path | None = None,
) -> dict[str, DailyTriAnchors]:
    paragraph_flat_dates = build_paragraph_flat_dates(paragraph_to_resolution, res_df)
    approved_bridges, rejected_bridges = load_bridge_decisions(output_dir or OUTPUT_DIR)
    results: dict[str, DailyTriAnchors] = {}
    for inventory_id, calendar_date in iter_inventory_calendar_days(
        date_to_sessions,
        inventory_filter=inventory_filter,
        date_filter=date_filter,
    ):
        if not enriched_by_date.get(calendar_date):
            continue
        day = discover_tri_anchors_for_day(
            inventory_id,
            calendar_date,
            enriched_by_date,
            places_df,
            orgs_df,
            persons_df,
            paragraph_flat_dates,
            paragraph_to_resolution,
            date_to_sessions,
            place_lookup,
            org_lookup,
            person_lookup,
            idf_weights,
            manual_pins,
            loc_names,
            per_names,
            org_names,
            state_pins,
            approved_bridges=approved_bridges,
            rejected_bridges=rejected_bridges,
        )
        if day.enriched_count == 0 and day.paragraph_count == 0:
            continue
        results[day.day_key] = day
    return results


def discover_all_tri_anchors(
    session_ids: list[str],
    enriched_by_date: dict[str, list[dict[str, Any]]],
    date_to_sessions: dict[str, set[str]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None,
    paragraph_to_resolution: dict[str, str],
    res_df: pd.DataFrame,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    manual_pins: list[dict[str, Any]],
    loc_names: dict[str, str],
    per_names: dict[str, str],
    org_names: dict[str, str],
    state_pins: list[dict[str, Any]] | None = None,
    *,
    date_filter: set[str] | None = None,
) -> dict[str, DailyTriAnchors]:
    return discover_all_daily_tri_anchors(
        date_to_sessions,
        enriched_by_date,
        places_df,
        orgs_df,
        persons_df,
        paragraph_to_resolution,
        res_df,
        place_lookup,
        org_lookup,
        person_lookup,
        idf_weights,
        manual_pins,
        loc_names,
        per_names,
        org_names,
        state_pins,
        inventory_filter=set(session_ids),
        date_filter=date_filter,
    )


def _format_tag_cell(tags: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for key, label in (("places", "LOC"), ("orgs", "ORG"), ("persons", "PER")):
        values = tags.get(key) or []
        if values:
            parts.append(f"{label}: {', '.join(escape(v) for v in values)}")
    return "<br>".join(parts) if parts else "<em>none</em>"


def write_tri_anchor_review_html(
    anchors: dict[str, DailyTriAnchors],
    output_path: Path,
) -> None:
    anchor_rows: list[str] = []
    day_sections: list[str] = []
    for day_key in sorted(anchors):
        item = anchors[day_key]
        for role in ("start", "middle", "end"):
            record = getattr(item, role)
            if not record:
                anchor_rows.append(
                    f"<tr><td>{escape(item.inventory_id)}</td>"
                    f"<td>{escape(item.calendar_date)}</td><td>{role}</td>"
                    f"<td colspan='10'><em>missing</em></td></tr>"
                )
                continue
            bridge = _format_tag_cell(record.bridge_tags)
            anchor_rows.append(
                "<tr>"
                f"<td>{escape(item.inventory_id)}</td>"
                f"<td>{escape(item.calendar_date)}</td>"
                f"<td>{escape(role)}</td>"
                f"<td>{escape(record.enriched_id)}</td>"
                f"<td>{escape(record.paragraph_id)}</td>"
                f"<td>{record.combined_score}</td>"
                f"<td>{escape(record.match_kind)}</td>"
                f"<td>{'yes' if record.same_day else 'no'}</td>"
                f"<td>{escape(record.source)}</td>"
                f"<td>{record.enriched_index}/{item.enriched_count}</td>"
                f"<td>{record.paragraph_index}/{item.paragraph_count}</td>"
                f"<td>{bridge}</td>"
                "</tr>"
            )

        enriched_rows = []
        for row in item.enriched_tagged:
            editorial = _format_tag_cell(row.get("editorial", {}))
            bridges = _format_tag_cell(row.get("overlap_bridges", {}))
            enriched_rows.append(
                "<tr>"
                f"<td>{escape(str(row.get('enriched_id', '')))}</td>"
                f"<td>{escape(str(row.get('resolution_index', '')))}</td>"
                f"<td>{editorial}</td>"
                f"<td>{bridges}</td>"
                "</tr>"
            )
        flat_rows = []
        for row in item.flat_tagged:
            flat_rows.append(
                "<tr>"
                f"<td>{escape(str(row.get('paragraph_id', '')))}</td>"
                f"<td>{escape(str(row.get('resolution_id', '')))}</td>"
                f"<td>{_format_tag_cell(row.get('overlap_tags', {}))}</td>"
                "</tr>"
            )
        day_sections.append(
            f"<details><summary><strong>{escape(day_key)}</strong> "
            f"({item.enriched_count} enriched / {item.paragraph_count} flat paragraphs; "
            f"{'complete' if item.complete else 'incomplete'})</summary>"
            "<h3>Enriched resolutions (editorial tags + overlap bridges)</h3>"
            "<table><tr><th>Enriched id</th><th>Idx</th><th>Editorial tags</th>"
            "<th>Overlap bridges (day)</th></tr>"
            f"{''.join(enriched_rows) or '<tr><td colspan=4><em>none</em></td></tr>'}"
            "</table>"
            "<h3>Flat paragraphs (HTR overlap tags)</h3>"
            "<table><tr><th>Paragraph id</th><th>Resolution id</th><th>Overlap tags</th></tr>"
            f"{''.join(flat_rows) or '<tr><td colspan=3><em>none</em></td></tr>'}"
            "</table></details>"
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Daily tri-anchors</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.35rem 0.5rem; text-align: left; vertical-align: top; }}
th {{ background: #f5f5f5; }}
details {{ margin: 1rem 0; }}
</style></head><body>
<h1>Daily tri-anchor review (inventory volume × calendar day)</h1>
<table>
<tr><th>Inventory</th><th>Date</th><th>Role</th><th>Enriched</th><th>Paragraph</th>
<th>Score</th><th>Bridge</th><th>Same day</th><th>Source</th>
<th>Enr idx</th><th>Para idx</th><th>Matched bridge tags</th></tr>
{''.join(anchor_rows)}
</table>
<h2>Tagged items per day</h2>
{''.join(day_sections)}
</body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def load_alignment_context(output_dir: Path) -> dict[str, Any]:
    from analyze_sequence_entity_overlap import build_typed_paragraph_lookups
    from build_alignment_new import (
        LOC_ANNOTATIONS_FILE,
        ORG_ANNOTATIONS_FILE,
        ORG_OVERLAP_FILE,
        PER_OVERLAP_FILE,
        PLACE_OVERLAP_FILE,
        calculate_idf_weights,
    )

    enriched_all = load_json(ENRICHED_FILE)
    places_df = pd.read_excel(PLACE_OVERLAP_FILE)
    orgs_df = pd.read_excel(ORG_OVERLAP_FILE)
    persons_df = pd.read_excel(PER_OVERLAP_FILE) if PER_OVERLAP_FILE.exists() else pd.DataFrame()
    if "naam" in orgs_df.columns and "name" not in orgs_df.columns:
        orgs_df = orgs_df.rename(columns={"naam": "name"})
    if "naam" in places_df.columns and "name" not in places_df.columns:
        places_df = places_df.rename(columns={"naam": "name"})

    paragraph_id_frames = [places_df["paragraph_id"], orgs_df["paragraph_id"]]
    if not persons_df.empty:
        paragraph_id_frames.append(persons_df["paragraph_id"])
    paragraph_ids = {
        str(paragraph_id).strip()
        for paragraph_id in pd.concat(paragraph_id_frames).dropna().astype(str)
        if str(paragraph_id).strip()
    }
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        paragraph_mapping_annotation_files(),
        paragraph_ids,
    )
    _, place_lookup, org_lookup, person_lookup = build_typed_paragraph_lookups(
        places_df,
        orgs_df,
        persons_df if not persons_df.empty else None,
    )
    overlap_frames = [
        places_df[["volgnr", "paragraph_id", "name"]],
        orgs_df[["volgnr", "paragraph_id", "name"]],
    ]
    if not persons_df.empty:
        overlap_frames.append(persons_df[["volgnr", "paragraph_id", "name"]])
    idf_weights = calculate_idf_weights(pd.concat(overlap_frames, ignore_index=True))
    enriched_by_date = build_enriched_by_date(enriched_all)
    date_to_sessions = build_date_to_session_map(places_df, orgs_df, paragraph_to_resolution)
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    manual_pins = load_manual_pin_records(
        output_dir,
        paragraph_to_resolution=paragraph_to_resolution,
        places_df=places_df,
        orgs_df=orgs_df,
    )
    state_pins: list[dict[str, Any]] = []
    state_path = output_dir / "alignment_state.json"
    if state_path.exists():
        state_pins = load_json(state_path).get("curated_pins", [])

    session_ids = sorted(
        {
            extract_session_id(str(resolution_id))
            for resolution_id in paragraph_to_resolution.values()
            if extract_session_id(str(resolution_id))
        },
        key=lambda sid: int(sid.split("-")[1]) if sid and sid.split("-")[1].isdigit() else 0,
    )

    loc_names = load_entity_names(LOC_ENTITIES_FILE)
    per_names = load_entity_names(PER_ENTITIES_FILE)
    org_names = load_entity_names(ORG_ENTITIES_FILE)

    return {
        "enriched_by_date": enriched_by_date,
        "date_to_sessions": date_to_sessions,
        "paragraph_to_resolution": paragraph_to_resolution,
        "places_df": places_df,
        "orgs_df": orgs_df,
        "persons_df": persons_df if not persons_df.empty else None,
        "res_df": res_df,
        "place_lookup": place_lookup,
        "org_lookup": org_lookup,
        "person_lookup": person_lookup,
        "idf_weights": idf_weights,
        "manual_pins": manual_pins,
        "state_pins": state_pins,
        "inventory_ids": session_ids,
        "loc_names": loc_names,
        "per_names": per_names,
        "org_names": org_names,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover daily tri-anchors per inventory sitting")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--inventories",
        "--sessions",
        dest="inventories",
        nargs="*",
        help="Limit to inventory volume ids (session-3186 = book, not a day)",
    )
    parser.add_argument("--dates", nargs="*", help="Limit to calendar dates YYYY-MM-DD")
    args = parser.parse_args()

    ctx = load_alignment_context(args.output_dir)
    inventory_filter = set(args.inventories) if args.inventories else None
    date_filter = set(args.dates) if args.dates else None

    anchors = discover_all_daily_tri_anchors(
        ctx["date_to_sessions"],
        ctx["enriched_by_date"],
        ctx["places_df"],
        ctx["orgs_df"],
        ctx["persons_df"],
        ctx["paragraph_to_resolution"],
        ctx["res_df"],
        ctx["place_lookup"],
        ctx["org_lookup"],
        ctx["person_lookup"],
        ctx["idf_weights"],
        ctx["manual_pins"],
        ctx["loc_names"],
        ctx["per_names"],
        ctx["org_names"],
        ctx["state_pins"],
        inventory_filter=inventory_filter,
        date_filter=date_filter,
        output_dir=args.output_dir,
    )

    payload = {
        "unit": "inventory_calendar_day",
        "scoring": {
            "min_anchor_score": MIN_ANCHOR_SCORE,
            "offset_penalty": DEFAULT_OFFSET_PENALTY,
        },
        "day_count": len(anchors),
        "complete_count": sum(1 for item in anchors.values() if item.complete),
        "days": {key: item.to_dict() for key, item in anchors.items()},
    }
    json_path = args.output_dir / "daily_tri_anchors.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # Legacy path for scripts expecting the old filename
    legacy_path = args.output_dir / "session_tri_anchors.json"
    legacy_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_tri_anchor_review_html(anchors, args.output_dir / "daily_tri_anchors_review.html")

    approved, rejected = load_bridge_decisions(args.output_dir)
    bridge_tasks = build_entity_bridge_queue(
        anchors,
        place_lookup=ctx["place_lookup"],
        org_lookup=ctx["org_lookup"],
        person_lookup=ctx["person_lookup"],
        paragraph_to_resolution=ctx["paragraph_to_resolution"],
        enriched_by_date=ctx["enriched_by_date"],
        idf_weights=ctx["idf_weights"],
    )
    (args.output_dir / QUEUE_FILE).write_text(
        json.dumps({"task_count": len(bridge_tasks), "tasks": bridge_tasks}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_entity_bridge_review_html(
        bridge_tasks,
        args.output_dir / REVIEW_HTML,
        approved=approved,
        rejected=rejected,
    )

    print(f"Inventory-days scanned: {len(anchors)}")
    print(f"Complete tri-anchors: {payload['complete_count']}")
    print(f"Wrote {json_path}")
    print(f"Wrote {args.output_dir / 'daily_tri_anchors_review.html'}")
    print(f"Entity bridge tasks: {len(bridge_tasks)} → {args.output_dir / REVIEW_HTML}")


if __name__ == "__main__":
    main()

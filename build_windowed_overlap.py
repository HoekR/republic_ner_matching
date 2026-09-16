#!/usr/bin/env python3
"""Rebuild place/org overlap tables with a calendar-date window.

The legacy notebook joins enriched and flat entity bridges on exact same
calendar day (canonical entity name). This script generalises that to
``|enriched_date − flat_date| ≤ N`` and matches via three passes:

1. **canonical** — enriched label ↔ flat entity registry name
2. **variant** — entity-linked surface set harvested from annotation ``tag_text``
   (e.g. editorial ``Engeland`` ↔ HTR ``Engelant`` via ``L0001860``)
3. **tag_text** — substring fallback when enriched label appears inside HTR span

Variant registries are written to ``data/derived/loc_tag_variants_1626_1630.json``,
``org_tag_variants_1626_1630.json``, and ``dat_paragraph_dates_1626_1630.json``.

Annotation inputs resolve from ``data/annotations/`` (LOC, ORG, PER, DAT).

Outputs versioned Excel files under ``data/derived/`` so the canonical
same-day tables remain untouched.

Usage:
    uv run python build_windowed_overlap.py
    uv run python build_windowed_overlap.py --window-days 3
    uv run python build_windowed_overlap.py --window-days 0 --compare-legacy
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from tqdm import tqdm

from build_alignment_new import (
    DATADIR,
    DATADIR_BAK,
    DAT_ANNOTATIONS_FILE,
    ENRICHED_FILE,
    LOC_ANNOTATIONS_FILE,
    LOC_ENTITIES_FILE,
    ORG_ANNOTATIONS_FILE,
    ORG_ENTITIES_FILE,
    PLACE_OVERLAP_FILE,
    ORG_OVERLAP_FILE,
    RESOLUTIONS_FILE,
    load_entity_names,
    load_json,
    resolve_data_file,
)

DERIVED_DIR = DATADIR / "derived"
PERIOD_START = pd.Period("1626-01-01", freq="D")
PERIOD_END = pd.Period("1630-12-31", freq="D")
MIN_TAG_TEXT_MATCH_LEN = 3
WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(value or "").strip().lower())


def normalize_text_series(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(WHITESPACE_PATTERN, " ", regex=True)
    )


_DAYS_IN_MONTH: dict[int, int] = {
    month: days
    for month, days in enumerate(
        [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31],
        start=1,
    )
}


def to_period_index_from_iso(iso_strings: pd.Series) -> pd.PeriodIndex:
    """Parse ``YYYY-MM-DD`` strings to daily PeriodIndex without datetime (pre-1678 safe)."""
    iso = iso_strings.fillna("").astype(str).str[:10]
    year = pd.to_numeric(iso.str.slice(0, 4), errors="coerce")
    month = pd.to_numeric(iso.str.slice(5, 7), errors="coerce")
    day = pd.to_numeric(iso.str.slice(8, 10), errors="coerce")
    is_leap = year.mod(4).eq(0) & (year.mod(100).ne(0) | year.mod(400).eq(0))
    max_day = month.map(_DAYS_IN_MONTH)
    max_day = max_day.where(month.ne(2), other=np.where(is_leap, 29, 28))
    valid = month.between(1, 12) & day.between(1, 31) & day.le(max_day)
    periods = pd.Series(pd.NaT, index=iso.index, dtype="period[D]")
    if valid.any():
        periods.loc[valid] = pd.PeriodIndex(iso.loc[valid], freq="D")
    return pd.PeriodIndex(periods, freq="D")


def period_diff_series(anchor: pd.Period, periods: pd.Series | pd.PeriodIndex) -> pd.Series:
    ref_index = periods.index if isinstance(periods, pd.Series) else periods
    peri = pd.PeriodIndex(periods, freq="D")
    return pd.Series(np.abs(peri.asi8 - anchor.ordinal), index=ref_index)


def _coalesce_flat_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Prefer enriched column names; fall back to ``_flat`` merge suffixes."""
    out = frame.copy()
    for col in (
        "paragraph_id",
        "flat_date",
        "flat_date_period",
        "name",
        "tag_text",
        "date_diff_days",
        "date_match_source",
        "dat_hook_date",
    ):
        flat_col = f"{col}_flat"
        if col not in out.columns and flat_col in out.columns:
            out[col] = out[flat_col]
    if "resolution_id_enriched" not in out.columns and "resolution_id" in out.columns:
        out["resolution_id_enriched"] = out["resolution_id"]
    if "enriched_date_enriched" in out.columns and "enriched_date" not in out.columns:
        out["enriched_date"] = out["enriched_date_enriched"]
    return out


def apply_date_window_columns(
    frame: pd.DataFrame,
    enriched_date: pd.Period,
    window_days: int,
    flat_period_col: str = "flat_date_period",
    dat_hook_col: str = "dat_hook_date",
) -> pd.DataFrame:
    """Add ``date_diff_days`` and ``date_match_source``; keep rows inside the window."""
    if frame.empty:
        return frame
    out = _coalesce_flat_columns(frame).reset_index(drop=True)
    if flat_period_col not in out.columns:
        return out.iloc[0:0].copy()
    out = _rehydrate_period_columns(out)
    flat_diff = period_diff_series(enriched_date, out[flat_period_col])
    dat_diff = pd.Series(np.inf, index=out.index, dtype="float64")
    if dat_hook_col in out.columns:
        hook_iso = out[dat_hook_col].fillna("").astype(str)
        has_hook = hook_iso.str.len().gt(0)
        if has_hook.any():
            hook_periods = to_period_index_from_iso(hook_iso)
            hook_diff = period_diff_series(enriched_date, hook_periods)
            dat_diff = dat_diff.where(~has_hook, hook_diff)
    out["date_diff_days"] = pd.concat([flat_diff, dat_diff], axis=1).min(axis=1).astype(int)
    out["date_match_source"] = np.where(
        flat_diff.le(window_days),
        "flat_calendar",
        np.where(dat_diff.le(window_days), "dat_annotation", "flat_calendar"),
    )
    return out.loc[out["date_diff_days"].le(window_days)].copy()


@dataclass
class EntityVariantLookup:
    """Entity-linked surface forms harvested from annotation tag_text spans."""

    entity_variants: dict[str, set[str]] = field(default_factory=dict)
    label_to_entities: dict[str, set[str]] = field(default_factory=dict)
    entity_canonical: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_annotations(cls, annot_df: pd.DataFrame, entity_col: str) -> EntityVariantLookup:
        frame = annot_df[[entity_col, "name", "tag_text_norm"]].copy()
        frame = frame.rename(columns={entity_col: "entity_id"})
        frame["entity_id"] = frame["entity_id"].fillna("").astype(str).str.strip()
        frame = frame.loc[frame["entity_id"].ne("")].copy()
        frame["canonical"] = normalize_text_series(frame["name"])
        frame["tag_surface"] = frame["tag_text_norm"].fillna("").astype(str).str.strip()

        entity_canonical = (
            frame.loc[frame["canonical"].ne(""), ["entity_id", "canonical"]]
            .drop_duplicates("entity_id", keep="first")
            .set_index("entity_id")["canonical"]
            .to_dict()
        )

        canonical_surfaces = (
            frame.loc[frame["canonical"].ne(""), ["entity_id", "canonical"]]
            .rename(columns={"canonical": "surface"})
        )
        tag_surfaces = frame.loc[
            frame["tag_surface"].str.len().ge(MIN_TAG_TEXT_MATCH_LEN),
            ["entity_id", "tag_surface"],
        ].rename(columns={"tag_surface": "surface"})
        surfaces = pd.concat([canonical_surfaces, tag_surfaces], ignore_index=True).drop_duplicates()

        entity_variants = surfaces.groupby("entity_id", sort=False)["surface"].apply(set).to_dict()
        label_to_entities = surfaces.groupby("surface", sort=False)["entity_id"].apply(set).to_dict()

        return cls(
            entity_variants=entity_variants,
            label_to_entities=label_to_entities,
            entity_canonical=entity_canonical,
        )

    def surfaces_for_label(self, label: str) -> set[str]:
        """All normalized surfaces linked to the same entity/entities as ``label``."""
        norm = normalize_text(label)
        if not norm:
            return set()
        surfaces = {norm}
        for entity_id in self.label_to_entities.get(norm, set()):
            surfaces |= self.entity_variants.get(entity_id, set())
        return surfaces

    def to_registry(self, layer: str) -> dict[str, Any]:
        entities: dict[str, dict[str, Any]] = {}
        for entity_id, surfaces in sorted(self.entity_variants.items()):
            canonical = self.entity_canonical.get(entity_id, "")
            entities[entity_id] = {
                "canonical_name": canonical,
                "surfaces": sorted(surfaces),
            }
        return {
            "layer": layer,
            "entity_count": len(entities),
            "surface_pair_count": sum(len(item["surfaces"]) for item in entities.values()),
            "entities": entities,
        }


def write_variant_registry(lookup: EntityVariantLookup, path: Path, layer: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(lookup.to_registry(layer), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def extract_entity_id(item: dict[str, Any]) -> str:
    """Resolve entity id from annotation record (top-level or provenance URN)."""
    entity_key = str(item.get("entity") or "").strip()
    if entity_key:
        return entity_key
    provenance = item.get("provenance") or {}
    target = provenance.get("target") or []
    raw_target = str(target[-1]) if target else ""
    if raw_target.startswith("urn:republic:entity:"):
        return raw_target.rsplit(":", 1)[-1]
    return raw_target.strip()

INSTELLING_INFO_FILE = resolve_data_file(
    DATADIR / "instelling_info.json",
    DATADIR / "reference" / "instelling_info.json",
    DATADIR_BAK / "instelling_info.json",
)


def period_days(value: Any) -> pd.Period:
    iso = pd.Series([str(value)[:10]])
    return to_period_index_from_iso(iso)[0]


def period_diff_days(left: pd.Period, right: pd.Period) -> int:
    return abs(int(left.ordinal - right.ordinal))


def candidate_dates(center: pd.Period, window_days: int) -> list[pd.Period]:
    return [center + offset for offset in range(-window_days, window_days + 1)]


def load_institution_names(path: Path) -> dict[str, str]:
    payload = load_json(path)
    rows = payload.get("instelling", payload if isinstance(payload, list) else [])
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {}
    valid = frame["ID_instelling"].notna() & frame["naam"].notna()
    subset = frame.loc[valid, ["ID_instelling", "naam"]].astype(str)
    return dict(zip(subset["ID_instelling"], subset["naam"].str.strip()))


def build_enriched_places(enriched_all: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(enriched_all)
    frame["resolution_id"] = frame.index
    frame = frame.loc[frame["date"].notna() & frame["resolution_index"].notna()].copy()
    frame["enriched_date"] = to_period_index_from_iso(frame["date"].astype(str))
    frame = frame.loc[
        frame["enriched_date"].notna()
        & frame["enriched_date"].ge(PERIOD_START)
        & frame["enriched_date"].le(PERIOD_END)
    ].copy()
    frame["volgnr"] = frame["volgnr"].where(
        frame["volgnr"].notna() & frame["volgnr"].astype(str).str.strip().ne(""),
        frame["date"].astype(str).str[:10] + "_" + frame["resolution_index"].astype(int).astype(str),
    )
    exploded = frame.explode("places", ignore_index=True)
    exploded = exploded.loc[exploded["places"].notna()].copy()
    exploded["place_name"] = exploded["places"].astype(str).str.strip()
    exploded = exploded.loc[exploded["place_name"].ne("")].copy()
    return exploded.assign(date=exploded["enriched_date"].astype(str))[
        ["resolution_id", "place_name", "enriched_date", "volgnr", "date"]
    ]


def build_enriched_orgs(
    enriched_all: list[dict[str, Any]],
    institution_names: dict[str, str],
) -> pd.DataFrame:
    frame = pd.DataFrame(enriched_all)
    frame["resolution_id"] = frame.index
    frame = frame.loc[frame["date"].notna() & frame["resolution_index"].notna()].copy()
    frame["enriched_date"] = to_period_index_from_iso(frame["date"].astype(str))
    frame = frame.loc[
        frame["enriched_date"].notna()
        & frame["enriched_date"].ge(PERIOD_START)
        & frame["enriched_date"].le(PERIOD_END)
    ].copy()
    frame["volgnr"] = frame["volgnr"].where(
        frame["volgnr"].notna() & frame["volgnr"].astype(str).str.strip().ne(""),
        frame["date"].astype(str).str[:10] + "_" + frame["resolution_index"].astype(int).astype(str),
    )
    exploded = frame.explode("institutions", ignore_index=True)
    exploded = exploded.loc[exploded["institutions"].notna()].copy()
    exploded["institution_id"] = exploded["institutions"].astype(str).str.strip()
    exploded["naam"] = exploded["institution_id"].map(institution_names).fillna(exploded["institution_id"])
    return exploded.assign(date=exploded["enriched_date"].astype(str))[
        ["resolution_id", "institution_id", "naam", "enriched_date", "volgnr", "date"]
    ]


def _annotation_reference_frame(raw: list[dict[str, Any]], entity_col: str) -> pd.DataFrame:
    """Single JSON pass; downstream column ops stay vectorized."""
    refs = [item.get("reference") or {} for item in raw]
    return pd.DataFrame(
        {
            entity_col: [extract_entity_id(item) for item in raw],
            "paragraph_id": [str(ref.get("paragraph_id") or "").strip() for ref in refs],
            "resolution_id": [str(ref.get("resolution_id") or "").strip() for ref in refs],
            "tag_text": [str(ref.get("tag_text") or "").strip() for ref in refs],
        }
    )


def flatten_loc_annotations(path: Path, loc_names: dict[str, str]) -> pd.DataFrame:
    frame = _annotation_reference_frame(load_json(path), entity_col="entity_nr")
    frame = frame.loc[frame["entity_nr"].ne("") & frame["paragraph_id"].ne("")].copy()
    frame["name"] = frame["entity_nr"].map(loc_names).fillna("").astype(str).str.strip()
    frame["tag_text_norm"] = normalize_text_series(frame["tag_text"])
    return frame


def flatten_org_annotations(path: Path, org_names: dict[str, str]) -> pd.DataFrame:
    frame = _annotation_reference_frame(load_json(path), entity_col="entity")
    frame = frame.loc[frame["entity"].ne("") & frame["paragraph_id"].ne("")].copy()
    frame["name"] = frame["entity"].map(org_names).fillna("").astype(str).str.strip()
    frame["tag_text_norm"] = normalize_text_series(frame["tag_text"])
    return frame


def flatten_dat_annotations(path: Path) -> pd.DataFrame:
    """DAT layer: resolved calendar dates anchored to HTR paragraphs."""
    raw = load_json(path)
    refs = [item.get("reference") or {} for item in raw]
    frame = pd.DataFrame(
        {
            "paragraph_id": [str(ref.get("paragraph_id") or "").strip() for ref in refs],
            "resolution_id": [str(ref.get("resolution_id") or "").strip() for ref in refs],
            "annotated_date": [str(item.get("date") or "")[:10] for item in raw],
            "tag_text": [str(ref.get("tag_text") or "").strip() for ref in refs],
        }
    )
    frame = frame.loc[frame["paragraph_id"].ne("") & frame["annotated_date"].ne("")].copy()
    frame["annotated_date_period"] = to_period_index_from_iso(frame["annotated_date"])
    frame = frame.loc[
        frame["annotated_date_period"].notna()
        & frame["annotated_date_period"].ge(PERIOD_START)
        & frame["annotated_date_period"].le(PERIOD_END)
    ].copy()
    frame["tag_text_norm"] = normalize_text_series(frame["tag_text"])
    return frame


def write_dat_paragraph_registry(dat_df: pd.DataFrame, path: Path) -> dict[str, int]:
    """Paragraph-level DAT hooks for downstream date alignment."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for paragraph_id, chunk in dat_df.groupby("paragraph_id", sort=True):
        grouped[str(paragraph_id)] = chunk[["annotated_date", "tag_text"]].to_dict(orient="records")
    payload = {
        "layer": "DAT",
        "paragraph_count": len(grouped),
        "annotation_count": len(dat_df),
        "paragraphs": grouped,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "paragraph_count": len(grouped),
        "annotation_count": len(dat_df),
    }


def attach_flat_dates(annot_df: pd.DataFrame, res_df: pd.DataFrame) -> pd.DataFrame:
    flat_dates = (
        res_df[["id", "date"]]
        .rename(columns={"id": "resolution_id", "date": "flat_date"})
        .copy()
    )
    flat_dates["resolution_id"] = flat_dates["resolution_id"].astype(str)
    flat_dates["flat_date"] = flat_dates["flat_date"].astype(str).str[:10]
    merged = annot_df.merge(flat_dates, on="resolution_id", how="left")
    merged = merged.loc[merged["flat_date"].notna()].copy()
    merged["flat_date_period"] = to_period_index_from_iso(merged["flat_date"])
    return merged.loc[
        merged["flat_date_period"].notna()
        & merged["flat_date_period"].ge(PERIOD_START)
        & merged["flat_date_period"].le(PERIOD_END)
    ].copy()


def _rehydrate_period_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Restore ``Period`` dtypes lost in ``to_dict(orient='records')`` round-trips."""
    out = frame.copy()
    for col in ("flat_date_period", "annotated_date_period", "enriched_date"):
        if col in out.columns:
            out[col] = to_period_index_from_iso(out[col].astype(str))
    return out


def _group_records_by_period(
    frame: pd.DataFrame,
    period_col: str,
) -> dict[pd.Period, list[dict[str, Any]]]:
    if frame.empty:
        return {}
    grouped: dict[pd.Period, list[dict[str, Any]]] = {}
    for period, chunk in frame.groupby(period_col, sort=False):
        records = chunk.to_dict(orient="records")
        for record in records:
            record[period_col] = period
        grouped[period] = records
    return grouped


def index_flat_rows_by_date(flat_df: pd.DataFrame) -> dict[pd.Period, list[dict[str, str]]]:
    return _group_records_by_period(flat_df, "flat_date_period")


def index_flat_rows_with_dat_hooks(
    flat_df: pd.DataFrame,
    dat_df: pd.DataFrame,
) -> dict[pd.Period, list[dict[str, Any]]]:
    """Index entity rows by flat HTR calendar date and by DAT-resolved dates."""
    flat = flat_df.assign(date_match_source="flat_calendar")
    by_date: dict[pd.Period, list[dict[str, Any]]] = defaultdict(list)
    for period, records in _group_records_by_period(flat, "flat_date_period").items():
        by_date[period].extend(records)

    if dat_df.empty or flat_df.empty:
        return by_date

    hooks = (
        dat_df[["paragraph_id", "annotated_date", "annotated_date_period", "tag_text"]]
        .rename(columns={"tag_text": "dat_tag_text"})
        .merge(flat_df, on="paragraph_id", how="inner", suffixes=("_dat", "_flat"))
    )
    hooks = hooks.assign(
        dat_hook_date=hooks["annotated_date"],
        date_match_source="dat_annotation",
    )
    if "tag_text_flat" in hooks.columns:
        hooks["tag_text"] = hooks["tag_text_flat"]
    for period, records in _group_records_by_period(hooks, "annotated_date_period").items():
        by_date[period].extend(records)
    return by_date


def tag_text_match_mask(enriched_label: str, flat_day: pd.DataFrame) -> pd.Series:
    """Substring fallback: enriched label appears inside HTR tag_text."""
    norm = normalize_text(enriched_label)
    if len(norm) < MIN_TAG_TEXT_MATCH_LEN:
        return pd.Series(False, index=flat_day.index)
    exact = flat_day["tag_text_norm"].eq(norm)
    contains = flat_day["tag_text_norm"].str.contains(re.escape(norm), na=False, regex=True)
    return exact | contains


def variant_match_mask(
    enriched_label: str,
    flat_day: pd.DataFrame,
    variant_lookup: EntityVariantLookup,
) -> pd.Series:
    """Entity-linked exact match on harvested canonical/tag_text surface forms."""
    surfaces = variant_lookup.surfaces_for_label(enriched_label)
    if not surfaces:
        return pd.Series(False, index=flat_day.index)
    tag_hit = flat_day["tag_text_norm"].isin(surfaces)
    name_hit = flat_day["name"].map(normalize_text).isin(surfaces)
    return tag_hit | name_hit


def filter_within_window(
    enriched_date: pd.Period,
    flat_day: pd.DataFrame,
    window_days: int,
) -> pd.DataFrame:
    return apply_date_window_columns(flat_day, enriched_date, window_days)


def _match_keys(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["volgnr"].astype(str)
        + "\0"
        + frame["paragraph_id"].astype(str)
        + "\0"
        + frame["name"].astype(str).str.strip()
    )


def _append_cross_matches(
    enriched_rows: pd.DataFrame,
    flat_hits: pd.DataFrame,
    match_kind: str,
    covered_keys: set[str],
    stats: dict[str, int],
    rows: list[dict[str, Any]],
    build_row: Callable[[pd.Series, str], dict[str, Any]],
) -> None:
    if enriched_rows.empty or flat_hits.empty:
        return
    enriched_side = enriched_rows.copy()
    if "resolution_id" in enriched_side.columns:
        enriched_side["resolution_id_enriched"] = enriched_side["resolution_id"]
    combined = enriched_side.merge(flat_hits, how="cross", suffixes=("", "_flat"))
    combined = _coalesce_flat_columns(combined)
    combined = combined.loc[combined["name"].astype(str).str.strip().ne("")].copy()
    if combined.empty:
        return
    combined["_match_key"] = _match_keys(combined)
    combined = combined.loc[~combined["_match_key"].isin(covered_keys)].drop_duplicates("_match_key")
    if combined.empty:
        return
    covered_keys.update(combined["_match_key"].tolist())
    stats[f"{match_kind}_matches"] += len(combined)
    rows.extend(combined.apply(lambda row: build_row(row, match_kind), axis=1).tolist())


def windowed_entity_overlap(
    enriched_df: pd.DataFrame,
    flat_by_date: dict[pd.Period, list[dict[str, str]]],
    window_days: int,
    enriched_key_col: str,
    build_row: Callable[[pd.Series, str], dict[str, Any]],
    progress_label: str,
    variant_lookup: EntityVariantLookup | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict[str, Any]] = []
    stats = {
        "canonical_matches": 0,
        "variant_matches": 0,
        "tag_text_matches": 0,
        "output_rows": 0,
    }
    covered_keys: set[str] = set()

    grouped = enriched_df.groupby("enriched_date", sort=False)
    for enriched_date, group in tqdm(grouped, desc=progress_label, unit="day"):
        candidate_rows: list[dict[str, str]] = []
        for candidate_date in candidate_dates(enriched_date, window_days):
            candidate_rows.extend(flat_by_date.get(candidate_date, []))
        if not candidate_rows:
            continue
        flat_day = _rehydrate_period_columns(pd.DataFrame(candidate_rows))
        if flat_day.empty:
            continue

        canonical = group.merge(
            flat_day,
            left_on=enriched_key_col,
            right_on="name",
            how="inner",
            suffixes=("", "_flat"),
        )
        if "resolution_id" in canonical.columns:
            canonical["resolution_id_enriched"] = canonical["resolution_id"]
        if not canonical.empty:
            canonical = apply_date_window_columns(canonical, enriched_date, window_days)
            if not canonical.empty:
                canonical = canonical.loc[canonical["name"].astype(str).str.strip().ne("")].copy()
                canonical["_match_key"] = _match_keys(canonical)
                canonical = canonical.loc[~canonical["_match_key"].isin(covered_keys)].drop_duplicates(
                    "_match_key"
                )
                if not canonical.empty:
                    covered_keys.update(canonical["_match_key"].tolist())
                    stats["canonical_matches"] += len(canonical)
                    canonical = _coalesce_flat_columns(canonical)
                    rows.extend(canonical.apply(lambda row: build_row(row, "canonical"), axis=1).tolist())

        in_window = filter_within_window(enriched_date, flat_day, window_days)
        if in_window.empty:
            continue

        for enriched_label, enriched_rows in group.groupby(enriched_key_col, sort=False):
            label = str(enriched_label)
            if variant_lookup is not None:
                variant_hits = in_window.loc[variant_match_mask(label, in_window, variant_lookup)]
                _append_cross_matches(
                    enriched_rows, variant_hits, "variant", covered_keys, stats, rows, build_row
                )
            tag_hits = in_window.loc[tag_text_match_mask(label, in_window)]
            _append_cross_matches(
                enriched_rows, tag_hits, "tag_text", covered_keys, stats, rows, build_row
            )

    if not rows:
        return pd.DataFrame(), stats

    output = pd.DataFrame(rows).drop_duplicates(
        subset=["volgnr", "paragraph_id", "name"],
        keep="first",
    )
    stats["output_rows"] = len(output)
    return output.sort_values(["date", "volgnr", "paragraph_id"]).reset_index(drop=True), stats


def build_place_row(row: pd.Series, match_kind: str) -> dict[str, Any]:
    return {
        "place_name": row["place_name"],
        "date": str(row["enriched_date"]),
        "volgnr": row["volgnr"],
        "name": row["name"],
        "paragraph_id": row["paragraph_id"],
        "enriched_date": str(row["enriched_date"]),
        "flat_date": row["flat_date"],
        "date_diff_days": int(row["date_diff_days"]),
        "match_kind": match_kind,
        "tag_text": row.get("tag_text", ""),
        "date_match_source": row.get("date_match_source", "flat_calendar"),
        "dat_hook_date": row.get("dat_hook_date", ""),
    }


def build_org_row(row: pd.Series, match_kind: str) -> dict[str, Any]:
    resolution_id = row.get("resolution_id_enriched", row.get("resolution_id"))
    resolution_id_val = int(resolution_id) if pd.notna(resolution_id) else 0
    return {
        "resolution_id": resolution_id_val,
        "institution_id": row["institution_id"],
        "naam": row["naam"],
        "date": str(row["enriched_date"]),
        "volgnr": row["volgnr"],
        "name": row["name"],
        "paragraph_id": row["paragraph_id"],
        "enriched_date": str(row["enriched_date"]),
        "flat_date": row["flat_date"],
        "date_diff_days": int(row["date_diff_days"]),
        "match_kind": match_kind,
        "tag_text": row.get("tag_text", ""),
        "date_match_source": row.get("date_match_source", "flat_calendar"),
        "dat_hook_date": row.get("dat_hook_date", ""),
    }


def windowed_place_overlap(
    enriched_places: pd.DataFrame,
    flat_by_date: dict[pd.Period, list[dict[str, str]]],
    window_days: int,
    variant_lookup: EntityVariantLookup | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    return windowed_entity_overlap(
        enriched_places,
        flat_by_date,
        window_days,
        enriched_key_col="place_name",
        build_row=build_place_row,
        progress_label="Place window matches",
        variant_lookup=variant_lookup,
    )


def windowed_org_overlap(
    enriched_orgs: pd.DataFrame,
    flat_by_date: dict[pd.Period, list[dict[str, str]]],
    window_days: int,
    variant_lookup: EntityVariantLookup | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    return windowed_entity_overlap(
        enriched_orgs,
        flat_by_date,
        window_days,
        enriched_key_col="naam",
        build_row=build_org_row,
        progress_label="Org window matches",
        variant_lookup=variant_lookup,
    )


def compare_with_legacy(
    rebuilt: pd.DataFrame,
    legacy_path: Path,
    key_cols: list[str],
    label: str,
) -> dict[str, Any]:
    legacy = pd.read_excel(legacy_path)
    legacy_keys = set(map(tuple, legacy[key_cols].astype(str).values.tolist()))
    rebuilt_keys = set(map(tuple, rebuilt[key_cols].astype(str).values.tolist()))
    return {
        "label": label,
        "legacy_rows": len(legacy),
        "rebuilt_rows": len(rebuilt),
        "legacy_only": len(legacy_keys - rebuilt_keys),
        "rebuilt_only": len(rebuilt_keys - legacy_keys),
        "shared": len(legacy_keys & rebuilt_keys),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build windowed place/org overlap tables (M8)")
    parser.add_argument("--window-days", type=int, default=3, help="Calendar window (default: 3)")
    parser.add_argument(
        "--compare-legacy",
        action="store_true",
        help="When window-days=0, compare rebuilt rows to legacy same-day Excel files",
    )
    parser.add_argument("--output-dir", type=Path, default=DERIVED_DIR)
    args = parser.parse_args()

    if args.window_days < 0:
        raise SystemExit("--window-days must be >= 0")

    enriched_all = load_json(ENRICHED_FILE)
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    loc_names = load_entity_names(LOC_ENTITIES_FILE)
    org_names = load_entity_names(ORG_ENTITIES_FILE)
    institution_names = load_institution_names(INSTELLING_INFO_FILE)

    enriched_places = build_enriched_places(enriched_all)
    enriched_orgs = build_enriched_orgs(enriched_all, institution_names)
    loc_df = attach_flat_dates(flatten_loc_annotations(LOC_ANNOTATIONS_FILE, loc_names), res_df)
    org_df = attach_flat_dates(flatten_org_annotations(ORG_ANNOTATIONS_FILE, org_names), res_df)
    dat_df = flatten_dat_annotations(DAT_ANNOTATIONS_FILE)
    loc_variants = EntityVariantLookup.from_annotations(loc_df, entity_col="entity_nr")
    org_variants = EntityVariantLookup.from_annotations(org_df, entity_col="entity")
    loc_by_date = index_flat_rows_with_dat_hooks(loc_df, dat_df)
    org_by_date = index_flat_rows_with_dat_hooks(org_df, dat_df)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    loc_variant_path = args.output_dir / "loc_tag_variants_1626_1630.json"
    org_variant_path = args.output_dir / "org_tag_variants_1626_1630.json"
    dat_registry_path = args.output_dir / "dat_paragraph_dates_1626_1630.json"
    write_variant_registry(loc_variants, loc_variant_path, layer="LOC")
    write_variant_registry(org_variants, org_variant_path, layer="ORG")
    dat_stats = write_dat_paragraph_registry(dat_df, dat_registry_path)

    print(f"  DAT hooks: {dat_stats['annotation_count']} annotations, "
          f"{dat_stats['paragraph_count']} paragraphs")
    print(f"  ORG annotations: {ORG_ANNOTATIONS_FILE}")
    print(f"  DAT annotations: {DAT_ANNOTATIONS_FILE}")

    place_overlap, place_stats = windowed_place_overlap(
        enriched_places, loc_by_date, args.window_days, variant_lookup=loc_variants
    )
    org_overlap, org_stats = windowed_org_overlap(
        enriched_orgs, org_by_date, args.window_days, variant_lookup=org_variants
    )

    suffix = "same_day" if args.window_days == 0 else f"window_{args.window_days}d"
    place_path = args.output_dir / f"place_overlap_{suffix}_1626_1630.xlsx"
    org_path = args.output_dir / f"org_overlap_{suffix}_1626_1630.xlsx"
    place_overlap.to_excel(place_path, index=False)
    org_overlap.to_excel(org_path, index=False)

    place_same_day = int((place_overlap["date_diff_days"] == 0).sum()) if len(place_overlap) else 0
    org_same_day = int((org_overlap["date_diff_days"] == 0).sum()) if len(org_overlap) else 0

    print("\n=== M8 windowed overlap rebuild ===")
    print(f"  window_days: {args.window_days}")
    print(f"  enriched place rows: {len(enriched_places)}")
    print(f"  enriched org rows: {len(enriched_orgs)}")
    print(f"  place overlap rows: {len(place_overlap)} ({place_same_day} same-day)")
    print(
        f"    canonical={place_stats['canonical_matches']}, "
        f"variant={place_stats['variant_matches']}, "
        f"tag_text={place_stats['tag_text_matches']}"
    )
    print(f"  org overlap rows: {len(org_overlap)} ({org_same_day} same-day)")
    print(
        f"    canonical={org_stats['canonical_matches']}, "
        f"variant={org_stats['variant_matches']}, "
        f"tag_text={org_stats['tag_text_matches']}"
    )
    print(f"  wrote: {place_path}")
    print(f"  wrote: {org_path}")
    print(f"  wrote: {loc_variant_path}")
    print(f"  wrote: {org_variant_path}")
    print(f"  wrote: {dat_registry_path}")

    if args.compare_legacy and args.window_days == 0:
        place_cmp = compare_with_legacy(
            place_overlap,
            PLACE_OVERLAP_FILE,
            ["volgnr", "paragraph_id", "name"],
            "place_overlap",
        )
        org_cmp = compare_with_legacy(
            org_overlap,
            ORG_OVERLAP_FILE,
            ["volgnr", "paragraph_id", "name"],
            "org_overlap",
        )
        for cmp in (place_cmp, org_cmp):
            print(
                f"\n  Legacy compare ({cmp['label']}): "
                f"shared={cmp['shared']}, legacy_only={cmp['legacy_only']}, rebuilt_only={cmp['rebuilt_only']}"
            )


if __name__ == "__main__":
    main()

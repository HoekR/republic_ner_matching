#!/usr/bin/env python3
"""Build person overlap Excel bridge for 1626-1630 alignment.

Joins enriched person surface forms (from XML) to PER annotations on the same
calendar date when the surface form appears in the annotation tag_text.

Usage:
    uv run python build_per_overlap.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from build_alignment_new import (
    DATADIR,
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    PER_ENTITIES_FILE,
    RESOLUTIONS_FILE,
    build_paragraph_to_resolution_map,
    load_json,
)

PER_ANNOTATIONS_FILE = DATADIR / "PER-annotations.json"

PERSON_SURFACES_FILE = DATADIR / "person_surfaces_1626_1630.parquet"
OUTPUT_FILE = DATADIR / "per_overlap_1626_1630.xlsx"

PERIOD_START = pd.Period("1626-01-01", freq="D")
PERIOD_END = pd.Period("1630-12-31", freq="D")

WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(value or "").strip().lower())


def surname_token(surface_name: str) -> str:
    """Return a short matching token from an editorial surface form."""
    text = normalize_text(surface_name)
    if not text:
        return ""
    if "," in text:
        return text.split(",", 1)[0].strip()
    parts = text.split()
    return parts[-1] if parts else text


def load_per_entity_names(path: Path) -> dict[str, str]:
    entities = load_json(path)
    return {
        str(item.get("id")): str(item.get("name", "")).strip()
        for item in entities
        if item.get("id") and item.get("name")
    }


def flatten_per_annotations(path: Path) -> pd.DataFrame:
    print(f"Loading PER annotations from {path.name}...")
    rows: list[dict[str, str]] = []
    for item in tqdm(load_json(path), desc="PER annotations", unit="rec"):
        ref = item.get("reference") or {}
        paragraph_id = ref.get("paragraph_id")
        resolution_id = ref.get("resolution_id")
        tag_text = ref.get("tag_text")
        entity = item.get("entity")
        if not paragraph_id or not tag_text or not entity:
            continue
        rows.append(
            {
                "entity": str(entity),
                "tag_text": str(tag_text),
                "tag_text_norm": normalize_text(tag_text),
                "paragraph_id": str(paragraph_id).strip(),
                "resolution_id": str(resolution_id).strip(),
            }
        )
    return pd.DataFrame(rows)


def attach_flat_dates(per_df: pd.DataFrame, res_df: pd.DataFrame) -> pd.DataFrame:
    flat_dates = (
        res_df[["id", "date"]]
        .rename(columns={"id": "resolution_id", "date": "flat_date"})
        .copy()
    )
    flat_dates["resolution_id"] = flat_dates["resolution_id"].astype(str)
    flat_dates["flat_date"] = flat_dates["flat_date"].astype(str).str[:10]
    merged = per_df.merge(flat_dates, on="resolution_id", how="left")
    merged["date"] = pd.PeriodIndex(merged["flat_date"].astype(str), freq="D")
    return merged


def build_per_overlap(
    surfaces_df: pd.DataFrame,
    per_dated: pd.DataFrame,
    per_names: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    dated_surfaces = surfaces_df.copy()
    dated_surfaces["date"] = pd.PeriodIndex(dated_surfaces["date"].astype(str), freq="D")
    dated_surfaces = dated_surfaces[
        (dated_surfaces["date"] >= PERIOD_START) & (dated_surfaces["date"] <= PERIOD_END)
    ].copy()
    dated_surfaces["surface_norm"] = dated_surfaces["surface_name"].map(normalize_text)
    dated_surfaces["surname_token"] = dated_surfaces["surface_name"].map(surname_token)

    per_window = per_dated[
        (per_dated["date"] >= PERIOD_START) & (per_dated["date"] <= PERIOD_END)
    ].copy()

    stats = {
        "surface_rows_in_period": len(dated_surfaces),
        "per_rows_in_period": len(per_window),
        "exact_surface_matches": 0,
        "surname_token_matches": 0,
        "output_rows": 0,
    }

    exact_parts: list[pd.DataFrame] = []
    for date_value, surface_group in tqdm(
        dated_surfaces.groupby("date", sort=False),
        desc="Matching by date",
        unit="day",
    ):
        per_day = per_window[per_window["date"] == date_value]
        if per_day.empty:
            continue
        for _, surface_row in surface_group.iterrows():
            surface_norm = surface_row["surface_norm"]
            if len(surface_norm) < 3:
                continue
            hits = per_day[per_day["tag_text_norm"].str.contains(re.escape(surface_norm), na=False)]
            if hits.empty:
                continue
            stats["exact_surface_matches"] += len(hits)
            chunk = hits.copy()
            for col in ("volgnr", "person_id", "surface_name", "canonical_name", "xml_file", "resolution_index"):
                chunk[col] = surface_row[col]
            exact_parts.append(chunk)

    exact_df = (
        pd.concat(exact_parts, ignore_index=True)
        if exact_parts
        else pd.DataFrame(columns=list(per_window.columns) + ["volgnr", "person_id", "surface_name", "canonical_name"])
    )

    matched_keys = set(
        zip(
            exact_df.get("volgnr", pd.Series(dtype=str)),
            exact_df.get("paragraph_id", pd.Series(dtype=str)),
            exact_df.get("person_id", pd.Series(dtype=float)),
        )
    ) if not exact_df.empty else set()

    token_parts: list[pd.DataFrame] = []
    if not exact_df.empty:
        covered_volgnr = set(exact_df["volgnr"].astype(str))
    else:
        covered_volgnr = set()

    for date_value, surface_group in dated_surfaces.groupby("date", sort=False):
        per_day = per_window[per_window["date"] == date_value]
        if per_day.empty:
            continue
        for _, surface_row in surface_group.iterrows():
            if str(surface_row["volgnr"]) in covered_volgnr:
                continue
            token = surface_row["surname_token"]
            if len(token) < 4:
                continue
            hits = per_day[per_day["tag_text_norm"].str.contains(rf"\b{re.escape(token)}\b", na=False)]
            if hits.empty:
                continue
            stats["surname_token_matches"] += len(hits)
            chunk = hits.copy()
            for col in ("volgnr", "person_id", "surface_name", "canonical_name", "xml_file", "resolution_index"):
                chunk[col] = surface_row[col]
            token_parts.append(chunk)

    token_df = pd.concat(token_parts, ignore_index=True) if token_parts else pd.DataFrame()
    combined = pd.concat([exact_df, token_df], ignore_index=True) if not token_df.empty else exact_df
    if combined.empty:
        return combined, stats

    combined["name"] = combined["entity"].map(per_names).fillna("")
    combined = combined.drop_duplicates(
        subset=["volgnr", "paragraph_id", "person_id", "entity"],
        keep="first",
    )
    combined["date"] = combined["date"].astype(str)
    output = combined[
        [
            "person_id",
            "surface_name",
            "canonical_name",
            "date",
            "volgnr",
            "name",
            "paragraph_id",
            "entity",
            "tag_text",
            "resolution_id",
        ]
    ].sort_values(["date", "volgnr", "paragraph_id"])
    stats["output_rows"] = len(output)
    return output, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Build per_overlap_1626_1630.xlsx")
    parser.add_argument("--surfaces", type=Path, default=PERSON_SURFACES_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()

    if not args.surfaces.exists():
        raise SystemExit(
            f"Missing {args.surfaces}. Run extract_xml_person_surfaces.py first."
        )

    surfaces_df = pd.read_parquet(args.surfaces)
    per_df = flatten_per_annotations(PER_ANNOTATIONS_FILE)
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    per_dated = attach_flat_dates(per_df, res_df)
    per_names = load_per_entity_names(PER_ENTITIES_FILE)

    overlap_df, stats = build_per_overlap(surfaces_df, per_dated, per_names)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    overlap_df.to_excel(args.output, index=False)

    paragraph_ids = set(overlap_df["paragraph_id"].dropna().astype(str))
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )
    resolved = sum(1 for pid in paragraph_ids if pid in paragraph_to_resolution)

    print("\n=== PER overlap build ===")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print(f"  paragraph_ids_resolved: {resolved}/{len(paragraph_ids)}")
    print(f"\n✓ Wrote {len(overlap_df)} rows to {args.output}")

    if len(overlap_df):
        print("\nSample rows:")
        print(overlap_df.head(8).to_string(index=False))


if __name__ == "__main__":
    main()

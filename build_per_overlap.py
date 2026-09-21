#!/usr/bin/env python3
"""Build person overlap Excel bridge for 1626-1630 alignment.

Joins enriched person surface forms (from XML) to PER annotations on the same
calendar date, using the same three-pass framework as build_windowed_overlap.py
(canonical exact match, entity-linked variant match, tag_text substring), plus
a person-specific surname-token fallback pass. See docs/DECISIONS.md
2026-09-19 ("excel-overlap-builder-audit") -- this rebuild adds the variant
pass that was previously missing for PER (exact substring + surname-token
only).

Usage:
    uv run python build_per_overlap.py
    uv run python build_per_overlap.py --window-days 0 --compare-legacy
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

from build_alignment_new import (
    DATADIR,
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    PER_ANNOTATIONS_FILE,
    PER_ENTITIES_FILE,
    PER_OVERLAP_FILE,
    PERSON_SURFACES_FILE,
    RESOLUTIONS_FILE,
    build_paragraph_to_resolution_map,
    load_json,
)
from build_windowed_overlap import (
    EntityVariantLookup,
    _append_cross_matches,
    _match_keys,
    _rehydrate_period_columns,
    apply_date_window_columns,
    attach_flat_dates,
    candidate_dates,
    compare_with_legacy,
    index_flat_rows_by_date,
    normalize_text,
    to_period_index_from_iso,
    windowed_entity_overlap,
)

DERIVED_DIR = DATADIR / "derived"
PERIOD_START = pd.Period("1626-01-01", freq="D")
PERIOD_END = pd.Period("1630-12-31", freq="D")

WHITESPACE_PATTERN = re.compile(r"\s+")


def surname_token(surface_name: str) -> str:
    """Return a short matching token from an editorial surface form."""
    text = normalize_text(surface_name)
    if not text:
        return ""
    if "," in text:
        return text.split(",", 1)[0].strip()
    parts = text.split()
    return parts[-1] if parts else text


def surname_token_match_mask(token: str, flat_day: pd.DataFrame) -> pd.Series:
    """Whole-word surname fallback: last editorial token as a bare word in HTR tag_text."""
    if len(token) < 4:
        return pd.Series(False, index=flat_day.index)
    pattern = rf"\b{re.escape(token)}\b"
    return flat_day["tag_text_norm"].str.contains(pattern, na=False, regex=True)


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


def build_per_row(row: pd.Series, match_kind: str) -> dict[str, Any]:
    return {
        "person_id": row["person_id"],
        "surface_name": row["surface_name"],
        "canonical_name": row["canonical_name"],
        "date": str(row["enriched_date"]),
        "volgnr": row["volgnr"],
        "name": row["name"],
        "paragraph_id": row["paragraph_id"],
        "entity": row["entity"],
        "tag_text": row.get("tag_text", ""),
        "resolution_id": row.get("resolution_id", ""),
        "match_kind": match_kind,
        "date_diff_days": int(row["date_diff_days"]),
        "date_match_source": row.get("date_match_source", "flat_calendar"),
    }


def _surname_token_pass(
    dated_surfaces: pd.DataFrame,
    per_by_date: dict[pd.Period, list[dict[str, Any]]],
    window_days: int,
    covered_keys: set[str],
    stats: dict[str, int],
) -> list[dict[str, Any]]:
    """4th pass, PER-specific: last-token whole-word fallback for rows the
    canonical/variant/tag_text passes missed. Not part of the shared
    windowed_entity_overlap driver (LOC/ORG have no equivalent token pass), so
    it re-walks the same per-day windowing the driver uses internally."""
    rows: list[dict[str, Any]] = []
    for enriched_date, group in dated_surfaces.groupby("enriched_date", sort=False):
        candidate_rows: list[dict[str, Any]] = []
        for candidate_date in candidate_dates(enriched_date, window_days):
            candidate_rows.extend(per_by_date.get(candidate_date, []))
        if not candidate_rows:
            continue
        flat_day = _rehydrate_period_columns(pd.DataFrame(candidate_rows))
        if flat_day.empty:
            continue
        in_window = apply_date_window_columns(flat_day, enriched_date, window_days)
        if in_window.empty:
            continue
        for _, surface_row in group.iterrows():
            token = surface_row["surname_token"]
            if len(token) < 4:
                continue
            hits = in_window.loc[surname_token_match_mask(token, in_window)]
            if hits.empty:
                continue
            enriched_row = pd.DataFrame([surface_row])
            _append_cross_matches(
                enriched_row, hits, "surname_token", covered_keys, stats, rows, build_per_row
            )
    return rows


def build_per_overlap(
    surfaces_df: pd.DataFrame,
    per_dated: pd.DataFrame,
    per_names: dict[str, str],
    window_days: int = 0,
) -> tuple[pd.DataFrame, dict[str, int]]:
    dated_surfaces = surfaces_df.copy()
    dated_surfaces["enriched_date"] = to_period_index_from_iso(dated_surfaces["date"].astype(str))
    dated_surfaces = dated_surfaces[
        dated_surfaces["enriched_date"].notna()
        & dated_surfaces["enriched_date"].ge(PERIOD_START)
        & dated_surfaces["enriched_date"].le(PERIOD_END)
    ].copy()
    dated_surfaces["surname_token"] = dated_surfaces["surface_name"].map(surname_token)

    per_dated = per_dated.copy()
    per_dated["name"] = per_dated["entity"].map(per_names).fillna("")
    per_variants = EntityVariantLookup.from_annotations(per_dated, entity_col="entity")
    per_by_date = index_flat_rows_by_date(per_dated)

    overlap, stats = windowed_entity_overlap(
        dated_surfaces,
        per_by_date,
        window_days,
        enriched_key_col="surface_name",
        build_row=build_per_row,
        progress_label="Person window matches",
        variant_lookup=per_variants,
    )

    covered_keys = set(_match_keys(overlap)) if not overlap.empty else set()
    stats["surname_token_matches"] = 0
    token_rows = _surname_token_pass(dated_surfaces, per_by_date, window_days, covered_keys, stats)

    all_rows = (overlap.to_dict("records") if not overlap.empty else []) + token_rows
    if not all_rows:
        return pd.DataFrame(), stats

    output = pd.DataFrame(all_rows).drop_duplicates(
        subset=["volgnr", "paragraph_id", "name"], keep="first"
    )
    stats["output_rows"] = len(output)
    return output.sort_values(["date", "volgnr", "paragraph_id"]).reset_index(drop=True), stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Build per_overlap_1626_1630.xlsx")
    parser.add_argument("--surfaces", type=Path, default=PERSON_SURFACES_FILE)
    parser.add_argument(
        "--window-days", type=int, default=0, help="Calendar window (default: 0, same-day only)"
    )
    parser.add_argument("--output-dir", type=Path, default=DERIVED_DIR)
    parser.add_argument(
        "--compare-legacy",
        action="store_true",
        help="When window-days=0, compare rebuilt rows to the current per_overlap_1626_1630.xlsx",
    )
    args = parser.parse_args()

    if args.window_days < 0:
        raise SystemExit("--window-days must be >= 0")
    if not args.surfaces.exists():
        raise SystemExit(f"Missing {args.surfaces}. Run extract_xml_person_surfaces.py first.")

    surfaces_df = pd.read_parquet(args.surfaces)
    per_df = flatten_per_annotations(PER_ANNOTATIONS_FILE)
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    per_dated = attach_flat_dates(per_df, res_df)
    per_names = load_per_entity_names(PER_ENTITIES_FILE)

    overlap_df, stats = build_per_overlap(surfaces_df, per_dated, per_names, window_days=args.window_days)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "same_day" if args.window_days == 0 else f"window_{args.window_days}d"
    output_path = args.output_dir / f"per_overlap_{suffix}_1626_1630.xlsx"
    overlap_df.to_excel(output_path, index=False)

    paragraph_ids = set(overlap_df["paragraph_id"].dropna().astype(str)) if len(overlap_df) else set()
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )
    resolved = sum(1 for pid in paragraph_ids if pid in paragraph_to_resolution)

    print("\n=== PER variant-aware overlap build ===")
    print(f"  window_days: {args.window_days}")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print(f"  paragraph_ids_resolved: {resolved}/{len(paragraph_ids)}")
    print(f"\n✓ Wrote {len(overlap_df)} rows to {output_path}")

    if len(overlap_df):
        print("\nSample rows:")
        print(overlap_df.head(8).to_string(index=False))

    if args.compare_legacy and args.window_days == 0:
        cmp = compare_with_legacy(
            overlap_df,
            PER_OVERLAP_FILE,
            ["volgnr", "paragraph_id", "name"],
            "per_overlap",
        )
        print(
            f"\n  Legacy compare ({cmp['label']}): "
            f"shared={cmp['shared']}, legacy_only={cmp['legacy_only']}, rebuilt_only={cmp['rebuilt_only']}"
        )


if __name__ == "__main__":
    main()

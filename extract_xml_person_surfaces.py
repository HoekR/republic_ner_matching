#!/usr/bin/env python3
"""Extract person surface forms from XML, PER annotations, and flat resolutions.

Maps enriched ``file`` + ``resolution_index`` to ``<persoon idnr=…>`` text inside
the matching ``<resolutie>`` block (not the session presentielijst). Builds a
versioned ``persons_info_with_surfaces`` file with separate XML / PER / flat buckets.

Usage:
    uv run python extract_xml_person_surfaces.py
    uv run python extract_xml_person_surfaces.py --zip data/resoluties_staten_generaal_1626-1630.zip
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd
from tqdm import tqdm

from build_alignment_new import (
    DATADIR,
    ENRICHED_FILE,
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    ORG_OVERLAP_FILE,
    OUTPUT_DIR,
    PER_ANNOTATIONS_FILE,
    PER_ENTITIES_FILE,
    PER_OVERLAP_FILE,
    PERSON_SURFACES_FILE,
    PERSONS_INFO_FILE,
    PLACE_OVERLAP_FILE,
    RESOLUTIONS_FILE,
    XML_ZIP_FILE,
    build_paragraph_to_resolution_map,
    load_json,
)

XML_ZIP_DEFAULT = XML_ZIP_FILE
ALIGNMENT_STATE_FILE = OUTPUT_DIR / "alignment_state.json"
OUTPUT_DEFAULT = DATADIR / "derived" / "person_surfaces_1626_1630.parquet"
AUGMENTED_PERSONS_INFO_JSON = DATADIR / "derived" / "persons_info_with_surfaces_1626_1630.json"
AUGMENTED_PERSONS_INFO_PARQUET = DATADIR / "derived" / "persons_info_with_surfaces_1626_1630.parquet"
SURFACE_NAMES_FLAT_PARQUET = DATADIR / "derived" / "person_surface_names_1626_1630.parquet"

PERIOD_START = pd.Period("1626-01-01", freq="D")
PERIOD_END = pd.Period("1630-12-31", freq="D")

DOCTYPE_PATTERN = re.compile(r"<!DOCTYPE[^>]*>", re.IGNORECASE | re.DOTALL)
WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_surface_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", str(value or "").strip())


def normalize_surface_key(value: str) -> str:
    return clean_surface_text(value).lower()


def load_persons_info(path: Path) -> dict[int, dict[str, str]]:
    frame = pd.read_json(path)
    lookup: dict[int, dict[str, str]] = {}
    for _, row in frame.iterrows():
        person_id = row.get("Id_persoon")
        if pd.isna(person_id):
            continue
        lookup[int(person_id)] = {
            "canonical_name": str(row.get("fullname") or row.get("short_name") or "").strip(),
            "short_name": str(row.get("short_name") or "").strip(),
        }
    return lookup


def load_persons_info_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_json(path)
    if "Id_persoon" not in frame.columns:
        raise ValueError(f"Expected Id_persoon column in {path}")
    return frame.copy()


def collect_all_person_surfaces_from_zip(zip_path: Path) -> dict[int, set[str]]:
    """Scan every XML file for ``<persoon idnr=…>`` surface forms."""
    xml_index = build_xml_index(zip_path)
    surfaces_by_id: dict[int, set[str]] = defaultdict(set)
    with zipfile.ZipFile(zip_path) as archive:
        for member_path in xml_index.values():
            root = parse_xml_bytes(archive.read(member_path))
            for person_id, surface in persons_in_element(root):
                surfaces_by_id[int(person_id)].add(surface)
    return dict(surfaces_by_id)


def build_augmented_persons_info(
    persons_info_path: Path,
    xml_by_id: dict[int, set[str]],
    per_by_id: dict[int, set[str]] | None = None,
    flat_by_id: dict[int, set[str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Merge XML, PER, and flat surface names into persons_info (versioned output)."""
    base = load_persons_info_frame(persons_info_path)
    per_by_id = per_by_id or {}
    flat_by_id = flat_by_id or {}

    stats = {
        "persons_info_rows": len(base),
        "person_ids_with_xml_surfaces": 0,
        "person_ids_with_per_surfaces": 0,
        "person_ids_with_flat_surfaces": 0,
        "person_ids_only_in_xml": 0,
        "total_unique_surfaces_union": 0,
        "total_xml_surface_pairs": 0,
        "total_per_surface_pairs": 0,
        "total_flat_surface_pairs": 0,
    }

    augmented_rows: list[dict[str, Any]] = []
    flat_rows: list[dict[str, Any]] = []
    known_ids = set(base["Id_persoon"].astype(int))

    def append_flat_rows(
        person_id: int,
        canonical_name: str,
        surfaces: set[str],
        source: str,
    ) -> None:
        for surface in sorted(surfaces):
            flat_rows.append(
                {
                    "person_id": person_id,
                    "surface_name": surface,
                    "canonical_name": canonical_name,
                    "source": source,
                }
            )

    for _, row in base.iterrows():
        person_id = int(row["Id_persoon"])
        canonical = str(row.get("fullname") or row.get("short_name") or "").strip()
        xml_surfaces = set(xml_by_id.get(person_id, set()))
        per_surfaces = set(per_by_id.get(person_id, set()))
        flat_surfaces = set(flat_by_id.get(person_id, set()))
        union = sorted(xml_surfaces | per_surfaces | flat_surfaces)

        if xml_surfaces:
            stats["person_ids_with_xml_surfaces"] += 1
        if per_surfaces:
            stats["person_ids_with_per_surfaces"] += 1
        if flat_surfaces:
            stats["person_ids_with_flat_surfaces"] += 1
        stats["total_xml_surface_pairs"] += len(xml_surfaces)
        stats["total_per_surface_pairs"] += len(per_surfaces)
        stats["total_flat_surface_pairs"] += len(flat_surfaces)
        stats["total_unique_surfaces_union"] += len(union)

        augmented_rows.append(
            {
                "Id_persoon": person_id,
                "fullname": str(row.get("fullname") or "").strip(),
                "short_name": str(row.get("short_name") or "").strip(),
                "surface_names_xml": sorted(xml_surfaces),
                "surface_names_per": sorted(per_surfaces),
                "surface_names_flat": sorted(flat_surfaces),
                "surface_names": union,
                "surface_count": len(union),
            }
        )
        append_flat_rows(person_id, canonical, xml_surfaces, "xml")
        append_flat_rows(person_id, canonical, per_surfaces, "per")
        append_flat_rows(person_id, canonical, flat_surfaces, "flat")

    extra_ids = set(xml_by_id) | set(per_by_id) | set(flat_by_id)
    for person_id in sorted(extra_ids):
        if person_id in known_ids:
            continue
        xml_surfaces = set(xml_by_id.get(person_id, set()))
        per_surfaces = set(per_by_id.get(person_id, set()))
        flat_surfaces = set(flat_by_id.get(person_id, set()))
        if not (xml_surfaces or per_surfaces or flat_surfaces):
            continue
        if xml_surfaces and person_id not in known_ids:
            stats["person_ids_only_in_xml"] += 1
        union = sorted(xml_surfaces | per_surfaces | flat_surfaces)
        stats["total_xml_surface_pairs"] += len(xml_surfaces)
        stats["total_per_surface_pairs"] += len(per_surfaces)
        stats["total_flat_surface_pairs"] += len(flat_surfaces)
        stats["total_unique_surfaces_union"] += len(union)

        augmented_rows.append(
            {
                "Id_persoon": person_id,
                "fullname": "",
                "short_name": "",
                "surface_names_xml": sorted(xml_surfaces),
                "surface_names_per": sorted(per_surfaces),
                "surface_names_flat": sorted(flat_surfaces),
                "surface_names": union,
                "surface_count": len(union),
            }
        )
        append_flat_rows(person_id, "", xml_surfaces, "xml")
        append_flat_rows(person_id, "", per_surfaces, "per")
        append_flat_rows(person_id, "", flat_surfaces, "flat")

    augmented = pd.DataFrame(augmented_rows).sort_values("Id_persoon").reset_index(drop=True)
    flat = (
        pd.DataFrame(flat_rows).sort_values(["person_id", "source", "surface_name"]).reset_index(drop=True)
        if flat_rows
        else pd.DataFrame(columns=["person_id", "surface_name", "canonical_name", "source"])
    )
    return augmented, flat, stats


def resolution_text_lookup(res_df: pd.DataFrame) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for _, row in res_df.iterrows():
        resolution_id = str(row["id"])
        text = row.get("resolutions_text")
        if not text or str(text) == "nan":
            text = row.get("paragraph_texts")
        if isinstance(text, str) and text.startswith("["):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    text = " ".join(str(item) for item in parsed if item)
            except (SyntaxError, ValueError):
                pass
        lookup[resolution_id] = clean_surface_text(str(text or ""))
    return lookup


def build_entity_to_person_map(per_overlap_df: pd.DataFrame) -> dict[str, set[int]]:
    mapping: dict[str, set[int]] = defaultdict(set)
    for _, row in per_overlap_df.iterrows():
        entity = str(row.get("entity", "")).strip()
        person_id = row.get("person_id")
        if entity and pd.notna(person_id):
            mapping[entity].add(int(person_id))
    return dict(mapping)


def collect_per_forms(
    per_overlap_path: Path,
    per_annotations_path: Path,
    res_df: pd.DataFrame,
) -> tuple[dict[int, set[str]], dict[str, int]]:
    """Collect PER ``tag_text`` spans mapped to ``Id_persoon``."""
    stats = {
        "per_overlap_rows": 0,
        "per_annotations_in_period": 0,
        "per_forms_added_from_overlap": 0,
        "per_forms_added_from_annotations": 0,
    }
    forms: dict[int, set[str]] = defaultdict(set)

    if not per_overlap_path.exists():
        return {}, stats

    overlap_df = pd.read_excel(per_overlap_path)
    stats["per_overlap_rows"] = len(overlap_df)
    entity_to_person = build_entity_to_person_map(overlap_df)

    for _, row in overlap_df.iterrows():
        person_id = int(row["person_id"])
        tag_text = clean_surface_text(str(row.get("tag_text", "")))
        if tag_text:
            forms[person_id].add(tag_text)
            stats["per_forms_added_from_overlap"] += 1

    if not per_annotations_path.exists():
        return dict(forms), stats

    flat_dates = (
        res_df[["id", "date"]]
        .rename(columns={"id": "resolution_id", "date": "flat_date"})
        .copy()
    )
    flat_dates["resolution_id"] = flat_dates["resolution_id"].astype(str)
    flat_dates["flat_date"] = flat_dates["flat_date"].astype(str).str[:10]
    date_lookup = flat_dates.set_index("resolution_id")["flat_date"].to_dict()

    for item in tqdm(load_json(per_annotations_path), desc="PER tag_text harvest", unit="rec"):
        ref = item.get("reference") or {}
        resolution_id = str(ref.get("resolution_id") or "").strip()
        tag_text = clean_surface_text(str(ref.get("tag_text") or ""))
        entity = str(item.get("entity") or "").strip()
        if not resolution_id or not tag_text or not entity:
            continue
        flat_date = date_lookup.get(resolution_id)
        if not flat_date:
            continue
        try:
            period = pd.Period(flat_date, freq="D")
        except ValueError:
            continue
        if period < PERIOD_START or period > PERIOD_END:
            continue
        stats["per_annotations_in_period"] += 1
        for person_id in entity_to_person.get(entity, set()):
            if tag_text not in forms[person_id]:
                stats["per_forms_added_from_annotations"] += 1
            forms[person_id].add(tag_text)

    return dict(forms), stats


def collect_flat_forms(
    per_overlap_path: Path,
    xml_by_id: dict[int, set[str]],
    per_by_id: dict[int, set[str]],
    res_df: pd.DataFrame,
    enriched_all: list[dict[str, Any]],
    alignment_state_path: Path,
) -> tuple[dict[int, set[str]], dict[str, int]]:
    """Harvest spellings observed in flat resolution text (substring search, not PER spans)."""
    stats = {
        "flat_forms_from_linked_resolutions": 0,
        "flat_forms_from_pin_paragraphs": 0,
    }
    forms: dict[int, set[str]] = defaultdict(set)
    res_text = resolution_text_lookup(res_df)
    enriched_by_id = {enriched_volgnr(item) or "": item for item in enriched_all}
    paragraph_to_resolution: dict[str, str] = {}

    if per_overlap_path.exists():
        overlap_df = pd.read_excel(per_overlap_path)
        paragraph_to_resolution = {
            str(row["paragraph_id"]).strip(): str(row["resolution_id"]).strip()
            for _, row in overlap_df.iterrows()
            if pd.notna(row.get("paragraph_id")) and pd.notna(row.get("resolution_id"))
        }
        linked_resolutions: dict[int, set[str]] = defaultdict(set)
        for _, row in overlap_df.iterrows():
            person_id = int(row["person_id"])
            resolution_id = str(row.get("resolution_id", "")).strip()
            if resolution_id:
                linked_resolutions[person_id].add(resolution_id)

        for person_id, resolution_ids in linked_resolutions.items():
            for resolution_id in resolution_ids:
                before = len(forms[person_id])
                _add_candidates_from_text(
                    person_id,
                    res_text.get(resolution_id, ""),
                    xml_by_id,
                    per_by_id,
                    forms,
                )
                stats["flat_forms_from_linked_resolutions"] += len(forms[person_id]) - before

    if alignment_state_path.exists():
        state = json.loads(alignment_state_path.read_text(encoding="utf-8"))
        for pin in state.get("curated_pins", []):
            paragraph_id = str(pin.get("paragraph_id", "")).strip()
            enriched_id = str(pin.get("enriched_id", "")).strip()
            if not paragraph_id or not enriched_id:
                continue
            enriched = enriched_by_id.get(enriched_id)
            if not enriched:
                continue
            resolution_id = paragraph_to_resolution.get(paragraph_id, "")
            if not resolution_id:
                match = re.match(r"(session-\d+-num-\d+)-para-\d+$", paragraph_id)
                if match:
                    prefix = match.group(1)
                    resolution_id = next(
                        (rid for rid in res_text if rid.startswith(prefix + "-resolution-")),
                        "",
                    )
            text = res_text.get(resolution_id, "")
            for person_ref in enriched.get("persons") or []:
                before = len(forms[int(person_ref)])
                _add_candidates_from_text(
                    int(person_ref),
                    text,
                    xml_by_id,
                    per_by_id,
                    forms,
                )
                stats["flat_forms_from_pin_paragraphs"] += len(forms[int(person_ref)]) - before

    return dict(forms), stats


def _add_candidates_from_text(
    person_id: int,
    text: str,
    xml_by_id: dict[int, set[str]],
    per_by_id: dict[int, set[str]],
    forms: dict[int, set[str]],
) -> None:
    if not text:
        return
    text_lower = text.lower()
    candidates = set(xml_by_id.get(person_id, set())) | set(per_by_id.get(person_id, set()))
    for candidate in candidates:
        token = clean_surface_text(candidate)
        if len(token) < 3:
            continue
        if token.lower() in text_lower:
            forms[person_id].add(token)


def write_augmented_persons_info(
    augmented: pd.DataFrame,
    flat: pd.DataFrame,
    json_path: Path,
    parquet_path: Path,
    flat_parquet_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    records = augmented.to_dict(orient="records")
    json_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    augmented.to_parquet(parquet_path, index=False)
    flat.to_parquet(flat_parquet_path, index=False)


def build_xml_index(zip_path: Path) -> dict[str, str]:
    """Map XML basename (e.g. 163003ap.xml) to zip member path."""
    index: dict[str, str] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".xml"):
                continue
            if "__MACOSX" in name or "/.svn/" in name:
                continue
            basename = Path(name).name
            index[basename] = name
    return index


def parse_xml_bytes(payload: bytes) -> ET.Element:
    text = payload.decode("utf-8", errors="replace")
    text = DOCTYPE_PATTERN.sub("", text, count=1)
    return ET.fromstring(text)


def resolutie_blocks(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//resolutie")


def persons_in_element(element: ET.Element) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for persoon in element.iter("persoon"):
        idnr = persoon.get("idnr")
        if not idnr:
            continue
        surface = " ".join("".join(persoon.itertext()).split())
        if surface:
            pairs.append((str(idnr), surface))
    return pairs


def surfaces_for_resolution(
    archive: zipfile.ZipFile,
    member_path: str,
    resolution_index: int,
    expected_person_ids: list[str] | None = None,
) -> list[dict[str, str]]:
    root = parse_xml_bytes(archive.read(member_path))
    blocks = resolutie_blocks(root)
    if not blocks:
        return []
    if resolution_index < 0 or resolution_index >= len(blocks):
        return []

    expected = {str(pid) for pid in (expected_person_ids or []) if pid}
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for person_id, surface in persons_in_element(blocks[resolution_index]):
        if expected and person_id not in expected:
            continue
        key = (person_id, surface)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"person_id": person_id, "surface_name": surface})
    return rows


def extract_all_surfaces(
    enriched_all: list[dict[str, Any]],
    zip_path: Path,
    persons_info: dict[int, dict[str, str]],
) -> tuple[pd.DataFrame, dict[str, int]]:
    xml_index = build_xml_index(zip_path)
    stats = {
        "enriched_total": len(enriched_all),
        "with_persons_field": 0,
        "xml_found": 0,
        "xml_missing": 0,
        "resolution_index_out_of_range": 0,
        "surface_rows": 0,
        "enriched_with_surfaces": 0,
        "person_ids_unmapped_canonical": 0,
    }

    records: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        for enriched in enriched_all:
            person_ids = enriched.get("persons") or []
            if not person_ids:
                continue
            stats["with_persons_field"] += 1

            xml_file = str(enriched.get("file") or "").strip()
            member_path = xml_index.get(xml_file)
            if not member_path:
                stats["xml_missing"] += 1
                continue
            stats["xml_found"] += 1

            resolution_index = int(enriched.get("resolution_index") or 0)
            volgnr = enriched_volgnr(enriched)
            date_str = str(enriched.get("date", ""))[:10]
            surfaces = surfaces_for_resolution(
                archive,
                member_path,
                resolution_index,
                [str(pid) for pid in person_ids],
            )
            if not surfaces:
                blocks = resolutie_blocks(parse_xml_bytes(archive.read(member_path)))
                if resolution_index >= len(blocks):
                    stats["resolution_index_out_of_range"] += 1
                continue

            stats["enriched_with_surfaces"] += 1
            for row in surfaces:
                person_id = int(row["person_id"])
                canonical = persons_info.get(person_id, {}).get("canonical_name", "")
                if not canonical:
                    stats["person_ids_unmapped_canonical"] += 1
                records.append(
                    {
                        "volgnr": volgnr,
                        "date": date_str,
                        "xml_file": xml_file,
                        "resolution_index": resolution_index,
                        "person_id": person_id,
                        "surface_name": row["surface_name"],
                        "canonical_name": canonical,
                    }
                )
                stats["surface_rows"] += 1

    return pd.DataFrame.from_records(records), stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract XML person surface forms.")
    parser.add_argument("--zip", type=Path, default=XML_ZIP_DEFAULT)
    parser.add_argument("--enriched", type=Path, default=ENRICHED_FILE)
    parser.add_argument("--persons-info", type=Path, default=PERSONS_INFO_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument(
        "--augmented-persons-info",
        type=Path,
        default=AUGMENTED_PERSONS_INFO_JSON,
        help="Versioned persons_info + XML surface_names (does not overwrite persons_info.json)",
    )
    parser.add_argument(
        "--augmented-persons-info-parquet",
        type=Path,
        default=AUGMENTED_PERSONS_INFO_PARQUET,
    )
    parser.add_argument(
        "--surface-names-flat",
        type=Path,
        default=SURFACE_NAMES_FLAT_PARQUET,
    )
    parser.add_argument("--per-overlap", type=Path, default=PER_OVERLAP_FILE)
    parser.add_argument("--per-annotations", type=Path, default=PER_ANNOTATIONS_FILE)
    parser.add_argument("--resolutions", type=Path, default=RESOLUTIONS_FILE)
    parser.add_argument("--alignment-state", type=Path, default=ALIGNMENT_STATE_FILE)
    args = parser.parse_args()

    if not args.zip.exists():
        raise SystemExit(f"XML zip not found: {args.zip}")

    enriched_all = json.loads(args.enriched.read_text(encoding="utf-8"))
    persons_info = load_persons_info(args.persons_info)
    print(f"Loaded {len(enriched_all)} enriched resolutions")
    print(f"Loaded {len(persons_info)} persons_info records")

    df, stats = extract_all_surfaces(enriched_all, args.zip, persons_info)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)

    print("\nScanning all XML <persoon> tags for surface inventory...")
    xml_by_id = collect_all_person_surfaces_from_zip(args.zip)

    res_df = pd.read_parquet(args.resolutions, columns=["id", "date", "paragraph_texts", "resolutions_text"])

    print("Collecting PER annotation forms...")
    per_by_id, per_stats = collect_per_forms(args.per_overlap, args.per_annotations, res_df)

    print("Collecting flat-resolution surface forms...")
    flat_by_id, flat_stats = collect_flat_forms(
        args.per_overlap,
        xml_by_id,
        per_by_id,
        res_df,
        enriched_all,
        args.alignment_state,
    )

    augmented, flat_surfaces, augment_stats = build_augmented_persons_info(
        args.persons_info,
        xml_by_id,
        per_by_id=per_by_id,
        flat_by_id=flat_by_id,
    )
    write_augmented_persons_info(
        augmented,
        flat_surfaces,
        args.augmented_persons_info,
        args.augmented_persons_info_parquet,
        args.surface_names_flat,
    )

    print("\n=== XML person surface extraction ===")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print(f"\n✓ Wrote {len(df)} resolution-level rows to {args.output}")

    print("\n=== Augmented persons_info ===")
    for key, value in augment_stats.items():
        print(f"  {key}: {value}")
    print(f"  unique_person_ids_in_xml: {len(xml_by_id)}")
    print(f"  unique_person_ids_in_per: {len(per_by_id)}")
    print(f"  unique_person_ids_in_flat: {len(flat_by_id)}")
    print("\n=== PER form harvest ===")
    for key, value in per_stats.items():
        print(f"  {key}: {value}")
    print("\n=== Flat form harvest ===")
    for key, value in flat_stats.items():
        print(f"  {key}: {value}")
    print(f"\n✓ Wrote augmented persons_info JSON: {args.augmented_persons_info}")
    print(f"✓ Wrote augmented persons_info parquet: {args.augmented_persons_info_parquet}")
    print(f"✓ Wrote flat surface lookup parquet: {args.surface_names_flat}")

    if len(df):
        print("\nSample rows:")
        print(df.head(8).to_string(index=False))


if __name__ == "__main__":
    main()

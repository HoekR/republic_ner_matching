#!/usr/bin/env python3
"""Evaluate person overlap signal on labeled ground-truth pairs.

Compares place/org-only vs place/org/person overlap at the GT flat resolution
for each labeled enriched_id → flat_id pair.

Usage:
    uv run python evaluate_person_overlap_labeled.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analyze_sequence_entity_overlap import anchor_paragraphs_for_pair
from build_alignment_new import (
    DATADIR,
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    OUTPUT_DIR,
    PLACE_OVERLAP_FILE,
    ORG_OVERLAP_FILE,
    build_overlap_lookups,
    build_paragraph_to_resolution_map,
    calculate_idf_weights,
)

PER_OVERLAP_FILE = DATADIR / "per_overlap_1626_1630.xlsx"
LABELED_FILE = OUTPUT_DIR / "ground_truth_labeled.json"
REPORT_FILE = OUTPUT_DIR / "person_overlap_evaluation.json"

PERSON_SIGNAL_SCALE = 0.2


def overlap_score(
    enriched_id: str,
    flat_id: str,
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    entity_filter: set[str] | None = None,
    scale: float = 1.0,
) -> float:
    entities = lookup.get((enriched_id, flat_id), set())
    if entity_filter is not None:
        entities = {entity for entity in entities if entity in entity_filter}
    return scale * sum(idf_weights.get(entity, 1.0) for entity in entities)


def main() -> None:
    labeled = json.loads(LABELED_FILE.read_text(encoding="utf-8"))
    places_df = pd.read_excel(PLACE_OVERLAP_FILE)
    orgs_df = pd.read_excel(ORG_OVERLAP_FILE)
    persons_df = pd.read_excel(PER_OVERLAP_FILE) if PER_OVERLAP_FILE.exists() else pd.DataFrame()

    if "naam" in orgs_df.columns and "name" not in orgs_df.columns:
        orgs_df = orgs_df.rename(columns={"naam": "name"})

    paragraph_ids = {
        str(paragraph_id).strip()
        for paragraph_id in pd.concat(
            [places_df["paragraph_id"], orgs_df["paragraph_id"], persons_df.get("paragraph_id", pd.Series(dtype=str))]
        ).dropna().astype(str)
        if str(paragraph_id).strip()
    }
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )
    place_lookup, org_lookup, person_lookup, combined_lookup = build_overlap_lookups(
        places_df,
        orgs_df,
        paragraph_to_resolution,
        persons_df=persons_df if not persons_df.empty else None,
    )

    all_frames = [
        places_df[["volgnr", "paragraph_id", "name"]],
        orgs_df[["volgnr", "paragraph_id", "name"]],
    ]
    if not persons_df.empty:
        all_frames.append(persons_df[["volgnr", "paragraph_id", "name"]])
    idf_weights = calculate_idf_weights(pd.concat(all_frames, ignore_index=True))
    person_entities = set(persons_df["name"].dropna().astype(str)) if not persons_df.empty else set()

    rows: list[dict] = []
    for record in labeled:
        enriched_id = str(record.get("enriched_id", ""))
        flat_id = str(record.get("flat_id", ""))
        verdict = record.get("verdict", "unknown")
        place_score = overlap_score(enriched_id, flat_id, place_lookup, idf_weights)
        org_score = overlap_score(enriched_id, flat_id, org_lookup, idf_weights)
        anchor_score = place_score + org_score
        person_score = overlap_score(
            enriched_id,
            flat_id,
            person_lookup,
            idf_weights,
            scale=PERSON_SIGNAL_SCALE,
        )
        combined_score = anchor_score + person_score
        anchors = anchor_paragraphs_for_pair(
            enriched_id,
            flat_id,
            places_df,
            orgs_df,
            paragraph_to_resolution,
        )
        rows.append(
            {
                "enriched_id": enriched_id,
                "flat_id": flat_id,
                "verdict": verdict,
                "place_score": round(place_score, 3),
                "org_score": round(org_score, 3),
                "anchor_score": round(anchor_score, 3),
                "person_score": round(person_score, 3),
                "combined_score": round(combined_score, 3),
                "gt_anchor_paragraphs": len(anchors),
                "has_person_overlap": person_score > 0,
            }
        )

    frame = pd.DataFrame(rows)
    summary = {
        "pairs": len(frame),
        "with_person_overlap_at_gt": int(frame["has_person_overlap"].sum()),
        "person_overlap_rate": round(float(frame["has_person_overlap"].mean()), 3),
        "mean_anchor_score_correct": round(
            float(frame.loc[frame["verdict"] == "correct", "anchor_score"].mean()), 3
        ),
        "mean_anchor_score_false_positive": round(
            float(frame.loc[frame["verdict"] == "false_positive", "anchor_score"].mean()), 3
        ),
        "mean_person_score_correct": round(
            float(frame.loc[frame["verdict"] == "correct", "person_score"].mean()), 3
        ),
        "mean_person_score_false_positive": round(
            float(frame.loc[frame["verdict"] == "false_positive", "person_score"].mean()), 3
        ),
        "mean_combined_score_correct": round(
            float(frame.loc[frame["verdict"] == "correct", "combined_score"].mean()), 3
        ),
        "mean_combined_score_false_positive": round(
            float(frame.loc[frame["verdict"] == "false_positive", "combined_score"].mean()), 3
        ),
        "person_signal_scale": PERSON_SIGNAL_SCALE,
        "per_overlap_rows": int(len(persons_df)),
        "person_entities_in_idf": len(person_entities),
    }

    REPORT_FILE.write_text(json.dumps({"summary": summary, "pairs": rows}, indent=2), encoding="utf-8")

    print("=== Person overlap evaluation (labeled 50) ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print(f"\n✓ Wrote {REPORT_FILE}")


if __name__ == "__main__":
    main()

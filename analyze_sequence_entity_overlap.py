#!/usr/bin/env python3
"""Diagnose sequence-level entity overlap on labeled ground truth.

Compares paragraph-primary vs resolution-level flat axes, computes overlap-matrix
metrics per labeled pair, and writes a strategic review HTML (Review R1).

Usage:
    uv run python analyze_sequence_entity_overlap.py
    uv run python analyze_sequence_entity_overlap.py --labeled output/ground_truth_labeled.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
import pandas as pd

from build_alignment_new import (
    DATADIR,
    LOC_ANNOTATIONS_FILE,
    ORG_ANNOTATIONS_FILE,
    ORG_OVERLAP_FILE,
    OUTPUT_DIR,
    PLACE_OVERLAP_FILE,
    SESSION_ID_PATTERN,
    align_session,
    build_paragraph_to_resolution_map,
    calculate_idf_weights,
    enriched_volgnr,
    extract_session_id,
    load_json,
)


PARAGRAPH_ID_PATTERN = re.compile(r"session-(\d+)-num-(\d+)-para-(\d+)$")
RESOLUTION_ID_PATTERN = re.compile(r"session-(\d+)-num-(\d+)-resolution-(\d+)$")

DEFAULT_LABELED = OUTPUT_DIR / "ground_truth_labeled.json"


def parse_paragraph_position(paragraph_id: str) -> tuple[int, int, int] | None:
    match = PARAGRAPH_ID_PATTERN.search(str(paragraph_id).strip())
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def parse_resolution_position(resolution_id: str) -> tuple[int, int, int] | None:
    match = RESOLUTION_ID_PATTERN.search(str(resolution_id).strip())
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def session_num_from_id(session_id: str | None) -> int | None:
    if not session_id:
        return None
    match = re.search(r"session-(\d+)", session_id)
    return int(match.group(1)) if match else None


def build_paragraph_overlap_lookup(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None = None,
) -> dict[tuple[str, str], set[str]]:
    """Map (volgnr, paragraph_id) -> entity names without resolution collapse."""
    _, _, _, combined = build_typed_paragraph_lookups(places_df, orgs_df, persons_df)
    return combined


def build_typed_paragraph_lookups(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    persons_df: pd.DataFrame | None = None,
) -> tuple[
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
    dict[tuple[str, str], set[str]],
]:
    """Return combined, place-only, org-only, and person-only paragraph lookups."""
    place_lookup: dict[tuple[str, str], set[str]] = {}
    org_lookup: dict[tuple[str, str], set[str]] = {}
    person_lookup: dict[tuple[str, str], set[str]] = {}
    combined_lookup: dict[tuple[str, str], set[str]] = {}

    for source_df, target_lookup in ((places_df, place_lookup), (orgs_df, org_lookup)):
        for _, row in source_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]) or pd.isna(row["name"]):
                continue
            volgnr = str(row["volgnr"]).strip()
            paragraph_id = str(row["paragraph_id"]).strip()
            entity_name = str(row["name"]).strip()
            target_lookup.setdefault((volgnr, paragraph_id), set()).add(entity_name)
            combined_lookup.setdefault((volgnr, paragraph_id), set()).add(entity_name)

    if persons_df is not None and not persons_df.empty:
        for _, row in persons_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]) or pd.isna(row["name"]):
                continue
            volgnr = str(row["volgnr"]).strip()
            paragraph_id = str(row["paragraph_id"]).strip()
            entity_name = str(row["name"]).strip()
            person_lookup.setdefault((volgnr, paragraph_id), set()).add(entity_name)
            combined_lookup.setdefault((volgnr, paragraph_id), set()).add(entity_name)

    return combined_lookup, place_lookup, org_lookup, person_lookup


def build_resolution_overlap_lookup(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
) -> dict[tuple[str, str], set[str]]:
    lookup: dict[tuple[str, str], set[str]] = {}
    for source_df in (places_df, orgs_df):
        for _, row in source_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]) or pd.isna(row["name"]):
                continue
            volgnr = str(row["volgnr"]).strip()
            paragraph_id = str(row["paragraph_id"]).strip()
            resolution_id = paragraph_to_resolution.get(paragraph_id)
            if not resolution_id:
                continue
            entity_name = str(row["name"]).strip()
            lookup.setdefault((volgnr, resolution_id), set()).add(entity_name)
    return lookup


def anchor_paragraphs_for_pair(
    enriched_id: str,
    flat_id: str,
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
) -> list[str]:
    paragraphs: set[str] = set()
    for source_df in (places_df, orgs_df):
        for _, row in source_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]):
                continue
            volgnr = str(row["volgnr"]).strip()
            paragraph_id = str(row["paragraph_id"]).strip()
            if volgnr != enriched_id:
                continue
            if paragraph_to_resolution.get(paragraph_id) == flat_id:
                paragraphs.add(paragraph_id)
    return sorted(paragraphs, key=lambda pid: parse_paragraph_position(pid) or (0, 0, 0))


def resolve_pin_paragraph_id(
    enriched_id: str,
    resolution_id: str | None,
    paragraph_id: str | None,
    auto_paragraph_id: str | None,
    paragraph_to_resolution: dict[str, str],
    places_df: pd.DataFrame | None = None,
    orgs_df: pd.DataFrame | None = None,
) -> str | None:
    """Resolve a paragraph pin from explicit id, auto paragraph, anchors, or first in resolution."""
    if paragraph_id:
        resolved = str(paragraph_id).strip()
        return resolved or None

    if not resolution_id:
        return None
    resolution_id = str(resolution_id).strip()

    if auto_paragraph_id:
        auto_paragraph_id = str(auto_paragraph_id).strip()
        if paragraph_to_resolution.get(auto_paragraph_id) == resolution_id:
            return auto_paragraph_id

    if places_df is not None and orgs_df is not None:
        anchors = anchor_paragraphs_for_pair(
            enriched_id,
            resolution_id,
            places_df,
            orgs_df,
            paragraph_to_resolution,
        )
        if anchors:
            return anchors[0]

    paragraphs = [
        paragraph
        for paragraph, flat_id in paragraph_to_resolution.items()
        if flat_id == resolution_id
    ]
    if paragraphs:
        return sorted(paragraphs, key=lambda pid: parse_paragraph_position(pid) or (0, 0, 0))[0]
    return None


def paragraphs_in_sessions(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    session_ids: set[str],
) -> list[str]:
    paragraphs: set[str] = set()
    for source_df in (places_df, orgs_df):
        for paragraph_id in source_df["paragraph_id"].dropna().astype(str):
            paragraph_id = paragraph_id.strip()
            session_id = extract_session_id(paragraph_id)
            if session_id in session_ids:
                paragraphs.add(paragraph_id)
    return sorted(paragraphs, key=lambda pid: parse_paragraph_position(pid) or (0, 0, 0))


def adjacent_session_ids(session_id: str) -> set[str]:
    session_num = session_num_from_id(session_id)
    if session_num is None:
        return {session_id}
    return {session_id, f"session-{session_num - 1}", f"session-{session_num + 1}"}


def resolutions_in_sessions(res_df: pd.DataFrame, session_ids: set[str]) -> list[str]:
    subset = res_df[res_df["session_id"].isin(session_ids)].copy()
    subset["sort_key"] = subset["id"].astype(str).map(parse_resolution_position)
    subset = subset[subset["sort_key"].notna()]
    return subset.sort_values("sort_key")["id"].astype(str).tolist()


def overlap_score(
    enriched_id: str,
    flat_id: str,
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
) -> float:
    entities = lookup.get((enriched_id, flat_id), set())
    return sum(idf_weights.get(entity, 1.0) for entity in entities)


def compute_overlap_matrix(
    enriched_ids: list[str],
    flat_ids: list[str],
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
) -> np.ndarray:
    matrix = np.zeros((len(enriched_ids), len(flat_ids)), dtype=float)
    for i, enriched_id in enumerate(enriched_ids):
        for j, flat_id in enumerate(flat_ids):
            matrix[i, j] = overlap_score(enriched_id, flat_id, lookup, idf_weights)
    return matrix


def nearest_paragraph_index(paragraph_ids: list[str], anchor: str) -> int:
    if anchor in paragraph_ids:
        return paragraph_ids.index(anchor)
    position = parse_paragraph_position(anchor)
    if position is None:
        return -1
    return min(
        range(len(paragraph_ids)),
        key=lambda idx: abs(
            (parse_paragraph_position(paragraph_ids[idx]) or (0, 0, 0))[1:] - position[1:]
        ),
    )


@dataclass
class AxisMetrics:
    axis: str
    variant: str
    enriched_index: int
    flat_index: int
    flat_id: str
    diag_score: float
    off_diag_max: float
    diag_margin: float
    neighborhood_score: float
    band_energy: float
    nw_flat_index: int | None = None
    nw_score: float = 0.0


def compute_axis_metrics(
    enriched_ids: list[str],
    flat_ids: list[str],
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    enriched_index: int,
    flat_index: int,
    axis: str,
    variant: str,
    gap_penalty: float = 0.1,
) -> AxisMetrics:
    matrix = compute_overlap_matrix(enriched_ids, flat_ids, lookup, idf_weights)
    diag_score = float(matrix[enriched_index, flat_index]) if matrix.size and flat_index >= 0 else 0.0

    off_diag_max = 0.0
    if matrix.size and enriched_index < matrix.shape[0] and flat_index >= 0:
        row = matrix[enriched_index].copy()
        row[flat_index] = -1.0
        off_diag_max = float(row.max())

    neighborhood_score = 0.0
    if flat_index >= 0:
        for di, dj in ((-1, -1), (-1, 1), (1, -1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)):
            ii = enriched_index + di
            jj = flat_index + dj
            if 0 <= ii < matrix.shape[0] and 0 <= jj < matrix.shape[1]:
                neighborhood_score += float(matrix[ii, jj])

    alignment = align_session(
        enriched_ids,
        flat_ids,
        lookup,
        idf_weights,
        gap_penalty=gap_penalty,
        anchor_only_diagonal=True,
    )
    band_energy = 0.0
    nw_flat_index: int | None = None
    nw_score = 0.0
    for enriched_pos, flat_pos in alignment:
        if enriched_pos == enriched_index and flat_pos is not None:
            nw_flat_index = flat_pos
            nw_score = float(matrix[enriched_pos, flat_pos])
        if enriched_pos is not None and flat_pos is not None:
            band_energy += float(matrix[enriched_pos, flat_pos])

    return AxisMetrics(
        axis=axis,
        variant=variant,
        enriched_index=enriched_index,
        flat_index=flat_index,
        flat_id=flat_ids[flat_index] if flat_ids and 0 <= flat_index < len(flat_ids) else "",
        diag_score=diag_score,
        off_diag_max=off_diag_max,
        diag_margin=diag_score - off_diag_max,
        neighborhood_score=neighborhood_score,
        band_energy=band_energy,
        nw_flat_index=nw_flat_index,
        nw_score=nw_score,
    )


def build_enriched_by_date(enriched_all: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    enriched_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for enriched in enriched_all:
        date_raw = str(enriched.get("date", ""))[:10]
        if len(date_raw) == 10:
            enriched_by_date[date_raw].append(enriched)
    for date_key in enriched_by_date:
        enriched_by_date[date_key].sort(key=lambda item: int(item.get("resolution_index", 0)))
    return enriched_by_date


def analyze_labeled_pairs(
    labeled: list[dict[str, Any]],
    enriched_by_date: dict[str, list[dict[str, Any]]],
    res_df: pd.DataFrame,
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    paragraph_lookup: dict[tuple[str, str], set[str]],
    resolution_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for record in labeled:
        verdict = record.get("verdict")
        if not verdict:
            continue

        enriched_id = str(record["enriched_id"])
        flat_resolution_id = str(record["flat_id"])
        enriched_date = str(record["enriched_date"])
        session_id = extract_session_id(flat_resolution_id) or "unknown"

        day_enriched = enriched_by_date.get(enriched_date, [])
        enriched_ids = [enriched_volgnr(item) or "" for item in day_enriched]
        enriched_index = next(
            (index for index, volgnr in enumerate(enriched_ids) if volgnr == enriched_id),
            -1,
        )

        anchor_paragraphs = anchor_paragraphs_for_pair(
            enriched_id,
            flat_resolution_id,
            places_df,
            orgs_df,
            paragraph_to_resolution,
        )
        primary_anchor = anchor_paragraphs[0] if anchor_paragraphs else None

        paragraph_variants = {
            "within_session": {session_id} if session_id != "unknown" else set(),
            "cross_session": adjacent_session_ids(session_id) if session_id != "unknown" else set(),
        }

        axis_metrics: list[AxisMetrics] = []
        heatmaps: dict[str, Any] = {}

        for variant_name, session_ids in paragraph_variants.items():
            paragraph_ids = paragraphs_in_sessions(places_df, orgs_df, session_ids)
            if not paragraph_ids or enriched_index < 0:
                continue
            paragraph_index = (
                nearest_paragraph_index(paragraph_ids, primary_anchor) if primary_anchor else -1
            )
            metrics = compute_axis_metrics(
                enriched_ids,
                paragraph_ids,
                paragraph_lookup,
                idf_weights,
                enriched_index,
                paragraph_index,
                axis="paragraph",
                variant=variant_name,
            )
            axis_metrics.append(metrics)
            matrix = compute_overlap_matrix(enriched_ids, paragraph_ids, paragraph_lookup, idf_weights)
            heatmaps[f"paragraph_{variant_name}"] = {
                "enriched_ids": enriched_ids,
                "flat_ids": paragraph_ids,
                "matrix": matrix.tolist(),
                "gt_enriched_index": enriched_index,
                "gt_flat_index": paragraph_index,
                "nw_flat_index": metrics.nw_flat_index,
            }

        resolution_ids = resolutions_in_sessions(res_df, paragraph_variants["within_session"])
        resolution_index = (
            resolution_ids.index(flat_resolution_id) if flat_resolution_id in resolution_ids else -1
        )
        if resolution_ids and enriched_index >= 0 and resolution_index >= 0:
            resolution_metrics = compute_axis_metrics(
                enriched_ids,
                resolution_ids,
                resolution_lookup,
                idf_weights,
                enriched_index,
                resolution_index,
                axis="resolution",
                variant="baseline",
            )
            axis_metrics.append(resolution_metrics)
            matrix = compute_overlap_matrix(enriched_ids, resolution_ids, resolution_lookup, idf_weights)
            heatmaps["resolution_baseline"] = {
                "enriched_ids": enriched_ids,
                "flat_ids": resolution_ids,
                "matrix": matrix.tolist(),
                "gt_enriched_index": enriched_index,
                "gt_flat_index": resolution_index,
                "nw_flat_index": resolution_metrics.nw_flat_index,
            }

        paragraph_within = next(
            (m for m in axis_metrics if m.axis == "paragraph" and m.variant == "within_session"),
            None,
        )
        resolution_baseline = next((m for m in axis_metrics if m.axis == "resolution"), None)
        paragraph_gain = None
        if paragraph_within and resolution_baseline:
            paragraph_gain = paragraph_within.diag_margin - resolution_baseline.diag_margin

        results.append(
            {
                "sample_id": record.get("sample_id"),
                "verdict": verdict,
                "enriched_id": enriched_id,
                "flat_id": flat_resolution_id,
                "enriched_date": enriched_date,
                "session_id": session_id,
                "anchor_paragraphs": anchor_paragraphs,
                "enriched_index": enriched_index,
                "metrics": [
                    {
                        "axis": metric.axis,
                        "variant": metric.variant,
                        "flat_index": metric.flat_index,
                        "flat_id": metric.flat_id,
                        "diag_score": round(metric.diag_score, 4),
                        "off_diag_max": round(metric.off_diag_max, 4),
                        "diag_margin": round(metric.diag_margin, 4),
                        "neighborhood_score": round(metric.neighborhood_score, 4),
                        "band_energy": round(metric.band_energy, 4),
                        "nw_flat_index": metric.nw_flat_index,
                        "nw_score": round(metric.nw_score, 4),
                        "nw_matches_gt": metric.nw_flat_index == metric.flat_index,
                    }
                    for metric in axis_metrics
                ],
                "paragraph_vs_resolution_gain": (
                    round(paragraph_gain, 4) if paragraph_gain is not None else None
                ),
                "heatmaps": heatmaps,
            }
        )

    return results


def aggregate_metrics(
    results: list[dict[str, Any]],
    verdict: str,
    axis: str,
    variant: str,
) -> dict[str, float | int | None]:
    margins: list[float] = []
    neighborhoods: list[float] = []
    nw_matches: list[bool] = []
    for result in results:
        if result.get("verdict") != verdict:
            continue
        for metric in result.get("metrics", []):
            if metric.get("axis") == axis and metric.get("variant") == variant:
                margins.append(float(metric["diag_margin"]))
                neighborhoods.append(float(metric["neighborhood_score"]))
                nw_matches.append(bool(metric["nw_matches_gt"]))
    return {
        "count": len(margins),
        "mean_diag_margin": round(mean(margins), 4) if margins else None,
        "mean_neighborhood_score": round(mean(neighborhoods), 4) if neighborhoods else None,
        "nw_matches_gt_rate": round(sum(nw_matches) / len(nw_matches), 4) if nw_matches else None,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    gains = [
        float(result["paragraph_vs_resolution_gain"])
        for result in results
        if result.get("paragraph_vs_resolution_gain") is not None
    ]

    by_session: dict[str, dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "false_positive": 0, "uncertain": 0}
    )
    for result in results:
        by_session[result["session_id"]][str(result["verdict"])] += 1

    paragraph_within = {
        "correct": aggregate_metrics(results, "correct", "paragraph", "within_session"),
        "false_positive": aggregate_metrics(results, "false_positive", "paragraph", "within_session"),
    }
    para_correct = paragraph_within["correct"].get("mean_diag_margin")
    para_fp = paragraph_within["false_positive"].get("mean_diag_margin")

    return {
        "pairs_analyzed": len(results),
        "by_verdict": dict(Counter(result["verdict"] for result in results)),
        "paragraph_within_session": paragraph_within,
        "paragraph_cross_session": {
            "correct": aggregate_metrics(results, "correct", "paragraph", "cross_session"),
            "false_positive": aggregate_metrics(results, "false_positive", "paragraph", "cross_session"),
        },
        "resolution_baseline": {
            "correct": aggregate_metrics(results, "correct", "resolution", "baseline"),
            "false_positive": aggregate_metrics(results, "false_positive", "resolution", "baseline"),
        },
        "mean_paragraph_vs_resolution_gain": round(mean(gains), 4) if gains else None,
        "sessions": dict(sorted(by_session.items())),
        "go_no_go": {
            "paragraph_beats_resolution": bool(gains) and mean(gains) > 0,
            "margin_separates_verdicts": (
                para_correct is not None and para_fp is not None and para_correct > para_fp
            ),
        },
    }


def heatmap_color(value: float, max_value: float) -> str:
    if max_value <= 0:
        return "#ffffff"
    intensity = min(1.0, value / max_value)
    red = int(255 - intensity * 180)
    blue = int(255 - intensity * 40)
    return f"rgb({red}, 220, {blue})"


def write_diagnostic_html(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    output_path: Path,
) -> None:
    session_rows = []
    for session_id, counts in summary.get("sessions", {}).items():
        session_results = [r for r in results if r["session_id"] == session_id]
        margins = [
            m["diag_margin"]
            for r in session_results
            for m in r.get("metrics", [])
            if m.get("axis") == "paragraph" and m.get("variant") == "within_session"
        ]
        gains = [
            r["paragraph_vs_resolution_gain"]
            for r in session_results
            if r.get("paragraph_vs_resolution_gain") is not None
        ]
        session_rows.append(
            {
                "session_id": session_id,
                "counts": counts,
                "mean_margin": round(mean(margins), 4) if margins else None,
                "mean_gain": round(mean(gains), 4) if gains else None,
            }
        )
    session_rows.sort(key=lambda row: (row["mean_margin"] is None, row["mean_margin"] or 0.0))
    worst_sessions = [row["session_id"] for row in session_rows[:3]]

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>Sequence Overlap Diagnostic (Review R1)</title>",
        "<style>",
        "body { font-family: Georgia, serif; margin: 24px; color: #222; }",
        "h1, h2, h3 { color: #1a365d; }",
        "table { border-collapse: collapse; margin: 16px 0; width: 100%; }",
        "th, td { border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }",
        "th { background: #edf2f7; }",
        ".go { color: #22543d; font-weight: bold; }",
        ".nogo { color: #9b2c2c; font-weight: bold; }",
        ".heatmap { display: grid; gap: 1px; margin: 8px 0 20px; }",
        ".cell { width: 18px; height: 18px; }",
        ".session-block { margin-bottom: 40px; padding-bottom: 20px; border-bottom: 2px solid #e2e8f0; }",
        ".meta { color: #4a5568; font-size: 0.95em; }",
        "</style></head><body>",
        "<h1>Sequence Overlap Diagnostic (Review R1)</h1>",
        "<p class='meta'>Strategic review after Phase 1. Compare paragraph vs resolution axes before changing the pipeline.</p>",
        "<h2>Go / No-Go signals</h2><ul>",
    ]

    go_para = summary["go_no_go"].get("paragraph_beats_resolution")
    go_margin = summary["go_no_go"].get("margin_separates_verdicts")
    parts.append(
        f"<li>Paragraph beats resolution (mean gain): "
        f"<span class='{'go' if go_para else 'nogo'}'>{go_para}</span></li>"
    )
    parts.append(
        f"<li>Diag margin separates correct vs false positive: "
        f"<span class='{'go' if go_margin else 'nogo'}'>{go_margin}</span></li>"
    )
    parts.append("</ul>")

    parts.append(
        "<h2>Aggregate metrics</h2><table>"
        "<tr><th>Axis</th><th>Verdict</th><th>Count</th>"
        "<th>Mean diag margin</th><th>Mean neighborhood</th><th>NW matches GT</th></tr>"
    )
    for axis_name, block in (
        ("Paragraph within session", summary["paragraph_within_session"]),
        ("Paragraph cross session", summary["paragraph_cross_session"]),
        ("Resolution baseline", summary["resolution_baseline"]),
    ):
        for verdict in ("correct", "false_positive"):
            row = block.get(verdict, {})
            parts.append(
                "<tr>"
                f"<td>{escape(axis_name)}</td>"
                f"<td>{escape(verdict)}</td>"
                f"<td>{row.get('count', 0)}</td>"
                f"<td>{row.get('mean_diag_margin', '')}</td>"
                f"<td>{row.get('mean_neighborhood_score', '')}</td>"
                f"<td>{row.get('nw_matches_gt_rate', '')}</td>"
                "</tr>"
            )
    parts.append("</table>")

    parts.append(
        "<h2>Per-session summary</h2><table>"
        "<tr><th>Session</th><th>Correct</th><th>False positive</th><th>Uncertain</th>"
        "<th>Mean diag margin</th><th>Paragraph gain</th></tr>"
    )
    for row in session_rows:
        counts = row["counts"]
        parts.append(
            "<tr>"
            f"<td>{escape(row['session_id'])}</td>"
            f"<td>{counts.get('correct', 0)}</td>"
            f"<td>{counts.get('false_positive', 0)}</td>"
            f"<td>{counts.get('uncertain', 0)}</td>"
            f"<td>{row['mean_margin']}</td>"
            f"<td>{row['mean_gain']}</td>"
            "</tr>"
        )
    parts.append("</table>")

    parts.append("<h2>Session heatmaps (worst sessions)</h2>")
    for session_id in worst_sessions:
        session_results = [r for r in results if r["session_id"] == session_id]
        if not session_results:
            continue
        parts.append(f"<div class='session-block'><h3>{escape(session_id)}</h3>")
        for result in session_results[:8]:
            heatmap = result.get("heatmaps", {}).get("paragraph_within_session")
            if not heatmap:
                continue
            matrix = np.array(heatmap["matrix"], dtype=float)
            max_value = float(matrix.max()) if matrix.size else 1.0
            gt_i = heatmap["gt_enriched_index"]
            gt_j = heatmap["gt_flat_index"]
            nw_j = heatmap.get("nw_flat_index")
            parts.append(
                f"<h4>Sample {result['sample_id']} — {escape(result['enriched_id'])} "
                f"({escape(str(result['verdict']))})</h4>"
            )
            parts.append(
                f"<p class='meta'>GT paragraph index {gt_j}; NW chose {nw_j}; "
                f"anchors: {escape(', '.join(result.get('anchor_paragraphs') or []))}</p>"
            )
            parts.append(
                f"<div class='heatmap' style='grid-template-columns: repeat({matrix.shape[1]}, 18px);'>"
            )
            for i in range(matrix.shape[0]):
                for j in range(matrix.shape[1]):
                    value = float(matrix[i, j])
                    border = "2px solid #111" if (i == gt_i and j == gt_j) else "1px solid #eee"
                    if i == gt_i and j == nw_j and nw_j != gt_j:
                        border = "2px solid #d69e2e"
                    parts.append(
                        f"<div class='cell' title='e{i}/p{j}: {value:.2f}' "
                        f"style='background:{heatmap_color(value, max_value)}; border:{border};'></div>"
                    )
            parts.append("</div>")
        parts.append("</div>")

    parts.append(
        "<h2>Review checklist</h2><ol>"
        "<li>Does paragraph axis show higher diag margin than resolution baseline?</li>"
        "<li>Do correct pairs cluster on the GT diagonal in worst sessions?</li>"
        "<li>Is cross-session pooling better than within-session for border sessions?</li>"
        "<li>If yes to 1–2, approve Phase 3 paragraph-level NW.</li>"
        "</ol></body></html>"
    )

    output_path.write_text("".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze sequence-level entity overlap on labeled ground truth.")
    parser.add_argument("--labeled", type=Path, default=DEFAULT_LABELED)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    if not args.labeled.exists():
        raise FileNotFoundError(f"Labeled ground truth not found: {args.labeled}")

    labeled = load_json(args.labeled)
    if not isinstance(labeled, list):
        raise ValueError("Labeled JSON must be a list of records.")

    enriched_all = load_json(DATADIR / "enriched_resolutions_1626_1630_complete.json")
    res_df = pd.read_parquet(DATADIR / "resolutions_flat.parquet")
    res_df["date_str"] = res_df["date"].astype(str).str[:10]
    res_df["session_id"] = res_df["id"].astype(str).str.extract(SESSION_ID_PATTERN, expand=False)

    places_df = pd.read_excel(PLACE_OVERLAP_FILE)
    orgs_df = pd.read_excel(ORG_OVERLAP_FILE)
    if "naam" in orgs_df.columns and "name" not in orgs_df.columns:
        orgs_df = orgs_df.rename(columns={"naam": "name"})
    if "naam" in places_df.columns and "name" not in places_df.columns:
        places_df = places_df.rename(columns={"naam": "name"})

    paragraph_ids = {
        str(paragraph_id).strip()
        for paragraph_id in pd.concat([places_df["paragraph_id"], orgs_df["paragraph_id"]]).dropna().astype(str)
        if str(paragraph_id).strip()
    }
    paragraph_to_resolution = build_paragraph_to_resolution_map(
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )

    paragraph_lookup = build_paragraph_overlap_lookup(places_df, orgs_df)
    resolution_lookup = build_resolution_overlap_lookup(places_df, orgs_df, paragraph_to_resolution)
    all_overlaps = pd.concat(
        [places_df[["volgnr", "paragraph_id", "name"]], orgs_df[["volgnr", "paragraph_id", "name"]]],
        ignore_index=True,
    )
    idf_weights = calculate_idf_weights(all_overlaps)
    enriched_by_date = build_enriched_by_date(enriched_all)

    results = analyze_labeled_pairs(
        labeled,
        enriched_by_date,
        res_df,
        places_df,
        orgs_df,
        paragraph_to_resolution,
        paragraph_lookup,
        resolution_lookup,
        idf_weights,
    )
    summary = summarize_results(results)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = args.output_dir / "sequence_overlap_analysis.json"
    summary_path = args.output_dir / "sequence_overlap_summary.json"
    html_path = args.output_dir / "verify_sequence_diagnostic.html"

    slim_results = [{k: v for k, v in result.items() if k != "heatmaps"} for result in results]
    analysis_path.write_text(json.dumps(slim_results, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_diagnostic_html(results, summary, html_path)

    print(f"✓ Analysis: {analysis_path} ({len(results)} pairs)")
    print(f"✓ Summary: {summary_path}")
    print(f"✓ Review R1 HTML: {html_path}")
    print(f"  Paragraph beats resolution: {summary['go_no_go']['paragraph_beats_resolution']}")
    print(f"  Margin separates verdicts: {summary['go_no_go']['margin_separates_verdicts']}")
    if summary.get("mean_paragraph_vs_resolution_gain") is not None:
        print(f"  Mean paragraph vs resolution gain: {summary['mean_paragraph_vs_resolution_gain']:.4f}")


if __name__ == "__main__":
    main()

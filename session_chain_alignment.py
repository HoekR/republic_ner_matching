#!/usr/bin/env python3
"""Ordered session-chain alignment with propagation from best sessions.

Sessions are ranked by labeled precision, aligned in chronological order,
with border hints propagated forward/backward from high-quality sessions.

Usage:
    uv run python session_chain_alignment.py
    uv run python session_chain_alignment.py --sessions session-3186 session-3187
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np
import pandas as pd

from sequence_review_ui import (
    build_alignment_audit_records,
    build_correction_records,
    build_day_sequence_payload,
    build_pin_placement_tasks,
    build_search_tasks,
    build_session_comparison_payload,
    write_alignment_audit_html,
    write_day_sequence_html,
    write_pin_placement_html,
    write_resolution_search_html,
    write_sequence_alignment_html,
    write_session_heatmap_comparison_html,
)
from analyze_sequence_entity_overlap import (
    aggregate_metrics,
    anchor_paragraphs_for_pair,
    build_enriched_by_date,
    build_paragraph_overlap_lookup,
    paragraphs_in_sessions,
    parse_paragraph_position,
    resolve_pin_paragraph_id,
    session_num_from_id,
)
from build_alignment_new import (
    DATADIR,
    ENRICHED_FILE,
    LOC_ANNOTATIONS_FILE,
    NO_ANCHOR_DIAG_SCORE,
    ORG_ANNOTATIONS_FILE,
    ORG_OVERLAP_FILE,
    OUTPUT_DIR,
    PER_OVERLAP_FILE,
    PERSON_SIGNAL_SCALE,
    PLACE_OVERLAP_FILE,
    RESOLUTIONS_FILE,
    SESSION_ID_PATTERN,
    align_session,
    build_date_to_session_map,
    build_paragraph_to_resolution_map,
    calculate_idf_weights,
    enriched_volgnr,
    extract_session_id,
    load_json,
    score_typed_overlap,
)


PIN_BONUS = 50.0
DEFAULT_OFFSET_PENALTY = 0.35
DEFAULT_LABELED = OUTPUT_DIR / "ground_truth_labeled.json"
DEFAULT_CURATED = OUTPUT_DIR / "ground_truth_curated.json"
STATE_PATH = OUTPUT_DIR / "alignment_state.json"


@dataclass
class SessionRank:
    session_id: str
    session_num: int
    correct: int
    false_positive: int
    uncertain: int
    precision: float
    mean_diag_margin: float | None = None


@dataclass
class SessionBorder:
    session_id: str
    last_enriched_id: str | None = None
    last_paragraph_id: str | None = None
    last_global_index: int | None = None
    first_enriched_id: str | None = None
    first_paragraph_id: str | None = None
    first_global_index: int | None = None


@dataclass
class AlignmentState:
    version: int
    scoring_params: dict[str, float]
    session_order: list[str]
    session_ranks: list[dict[str, Any]]
    locked_sessions: list[str] = field(default_factory=list)
    curated_pins: list[dict[str, str]] = field(default_factory=list)
    rejected_pairs: list[dict[str, str]] = field(default_factory=list)
    alignments: list[dict[str, Any]] = field(default_factory=list)
    borders: list[dict[str, Any]] = field(default_factory=list)
    propagation_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "scoring_params": self.scoring_params,
            "session_order": self.session_order,
            "session_ranks": self.session_ranks,
            "locked_sessions": self.locked_sessions,
            "curated_pins": self.curated_pins,
            "rejected_pairs": self.rejected_pairs,
            "alignments": self.alignments,
            "borders": self.borders,
            "propagation_report": self.propagation_report,
        }


def align_session_with_hints(
    enriched_ids: list[str],
    flat_ids: list[str],
    overlap_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    gap_penalty: float = 0.1,
    anchor_only_diagonal: bool = True,
    pinned: dict[int, int] | None = None,
    expected_offset: int | None = None,
    offset_penalty: float = DEFAULT_OFFSET_PENALTY,
    blocked: set[tuple[str, str]] | None = None,
    place_lookup: dict[tuple[str, str], set[str]] | None = None,
    org_lookup: dict[tuple[str, str], set[str]] | None = None,
    person_lookup: dict[tuple[str, str], set[str]] | None = None,
    person_signal_scale: float = PERSON_SIGNAL_SCALE,
) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch with optional pin bonuses and soft positional hints."""
    n = len(enriched_ids)
    m = len(flat_ids)
    pinned = pinned or {}
    blocked = blocked or set()
    use_typed_scoring = place_lookup is not None and org_lookup is not None

    dp = np.zeros((n + 1, m + 1))
    tb = np.zeros((n + 1, m + 1), dtype=int)

    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] - gap_penalty
        tb[i][0] = 2
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] - gap_penalty
        tb[0][j] = 3

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            e_id = enriched_ids[i - 1]
            f_id = flat_ids[j - 1]
            if (e_id, f_id) in blocked and (i - 1) not in pinned:
                diag = NO_ANCHOR_DIAG_SCORE
            else:
                if use_typed_scoring:
                    anchor_score, _person_score, match_score = score_typed_overlap(
                        e_id,
                        f_id,
                        place_lookup or {},
                        org_lookup or {},
                        person_lookup or {},
                        idf_weights,
                        person_signal_scale=person_signal_scale,
                    )
                    gate_score = anchor_score
                else:
                    shared_entities = overlap_lookup.get((e_id, f_id), set())
                    match_score = sum(idf_weights.get(entity, 1.0) for entity in shared_entities)
                    gate_score = match_score
                if anchor_only_diagonal and gate_score == 0 and (i - 1) not in pinned:
                    diag = NO_ANCHOR_DIAG_SCORE
                else:
                    diag = dp[i - 1][j - 1] + match_score
                    if (i - 1) in pinned and pinned[i - 1] == j - 1:
                        diag += PIN_BONUS
                    elif (i - 1) in pinned:
                        diag = NO_ANCHOR_DIAG_SCORE
                    if expected_offset is not None:
                        diag -= offset_penalty * abs((j - 1) - (expected_offset + (i - 1)))

            up = dp[i - 1][j] - gap_penalty
            left = dp[i][j - 1] - gap_penalty
            best = max(diag, up, left)
            dp[i][j] = best
            if best == diag:
                tb[i][j] = 1
            elif best == up:
                tb[i][j] = 2
            else:
                tb[i][j] = 3

    i, j = n, m
    alignment: list[tuple[int | None, int | None]] = []
    while i > 0 or j > 0:
        if tb[i][j] == 1:
            alignment.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif tb[i][j] == 2:
            alignment.append((i - 1, None))
            i -= 1
        else:
            alignment.append((None, j - 1))
            j -= 1
    return alignment[::-1]


def rank_sessions(
    labeled: list[dict[str, Any]],
    analysis: list[dict[str, Any]] | None = None,
) -> list[SessionRank]:
    by_session: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "false_positive": 0, "uncertain": 0})
    margins_by_session: dict[str, list[float]] = defaultdict(list)

    for record in labeled:
        session_id = extract_session_id(str(record.get("flat_id", ""))) or "unknown"
        verdict = str(record.get("verdict", ""))
        if verdict in {"correct", "false_positive", "uncertain"}:
            by_session[session_id][verdict] += 1

    if analysis:
        for result in analysis:
            session_id = result.get("session_id", "unknown")
            for metric in result.get("metrics", []):
                if metric.get("axis") == "paragraph" and metric.get("variant") == "within_session":
                    margins_by_session[session_id].append(float(metric["diag_margin"]))

    ranks: list[SessionRank] = []
    for session_id, counts in by_session.items():
        if session_id == "unknown":
            continue
        total = counts["correct"] + counts["false_positive"] + counts["uncertain"]
        precision = counts["correct"] / total if total else 0.0
        margins = margins_by_session.get(session_id, [])
        ranks.append(
            SessionRank(
                session_id=session_id,
                session_num=session_num_from_id(session_id) or 0,
                correct=counts["correct"],
                false_positive=counts["false_positive"],
                uncertain=counts["uncertain"],
                precision=round(precision, 4),
                mean_diag_margin=round(mean(margins), 4) if margins else None,
            )
        )
    ranks.sort(key=lambda item: (-item.precision, -(item.mean_diag_margin or 0.0), item.session_num))
    return ranks


def invert_date_to_sessions(date_to_sessions: dict[str, set[str]]) -> dict[str, list[str]]:
    session_to_dates: dict[str, list[str]] = defaultdict(list)
    for date_str, sessions in date_to_sessions.items():
        for session_id in sessions:
            session_to_dates[session_id].append(date_str)
    for session_id in session_to_dates:
        session_to_dates[session_id] = sorted(set(session_to_dates[session_id]))
    return dict(session_to_dates)


def build_global_paragraph_stream(
    session_order: list[str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
) -> tuple[list[str], dict[str, tuple[int, int]], dict[str, int]]:
    global_paragraphs: list[str] = []
    session_ranges: dict[str, tuple[int, int]] = {}
    global_index_by_paragraph: dict[str, int] = {}

    for session_id in session_order:
        paragraphs = paragraphs_in_sessions(places_df, orgs_df, {session_id})
        start = len(global_paragraphs)
        global_paragraphs.extend(paragraphs)
        end = len(global_paragraphs) - 1
        session_ranges[session_id] = (start, end)
        for offset, paragraph_id in enumerate(paragraphs):
            global_index_by_paragraph[paragraph_id] = start + offset

    return global_paragraphs, session_ranges, global_index_by_paragraph


def curated_pins_for_session(
    curated: list[dict[str, Any]],
    session_id: str,
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    enriched_ids: list[str],
    paragraph_ids: list[str],
) -> dict[int, int]:
    pins: dict[int, int] = {}
    for record in curated:
        flat_id = str(record.get("flat_id", ""))
        if extract_session_id(flat_id) != session_id:
            continue
        enriched_id = str(record.get("enriched_id", ""))
        if enriched_id not in enriched_ids:
            continue
        anchor_paragraphs = anchor_paragraphs_for_pair(
            enriched_id,
            flat_id,
            places_df,
            orgs_df,
            paragraph_to_resolution,
        )
        if not anchor_paragraphs:
            continue
        paragraph_id = anchor_paragraphs[0]
        if paragraph_id not in paragraph_ids:
            continue
        pins[enriched_ids.index(enriched_id)] = paragraph_ids.index(paragraph_id)
    return pins


def direct_pins_for_session(
    pin_records: list[dict[str, Any]],
    session_id: str,
    enriched_ids: list[str],
    paragraph_ids: list[str],
) -> dict[int, int]:
    """Map explicit enriched_id → paragraph_id pins (manual corrections)."""
    pins: dict[int, int] = {}
    for record in pin_records:
        if str(record.get("session_id", "")) != session_id:
            continue
        enriched_id = str(record.get("enriched_id", ""))
        paragraph_id = str(
            record.get("paragraph_id") or record.get("corrected_paragraph_id") or ""
        )
        if enriched_id not in enriched_ids or paragraph_id not in paragraph_ids:
            continue
        pins[enriched_ids.index(enriched_id)] = paragraph_ids.index(paragraph_id)
    return pins


def load_manual_pin_records(
    output_dir: Path,
    *,
    paragraph_to_resolution: dict[str, str] | None = None,
    places_df: pd.DataFrame | None = None,
    orgs_df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Load researcher corrections from alignment state and corrective ground truth."""
    records: list[dict[str, Any]] = []
    state_path = output_dir / "alignment_state.json"
    corrective_path = output_dir / "corrective_ground_truth.json"

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for pin in state.get("curated_pins", []):
            if pin.get("source") == "manual_correction":
                records.append(pin)

    if corrective_path.exists():
        for item in json.loads(corrective_path.read_text(encoding="utf-8")):
            if item.get("action") != "confirmed":
                continue
            paragraph_id = item.get("corrected_paragraph_id")
            if not paragraph_id and paragraph_to_resolution is not None:
                paragraph_id = resolve_pin_paragraph_id(
                    enriched_id=str(item.get("enriched_id", "")),
                    resolution_id=item.get("corrected_resolution_id") or item.get("auto_flat_id"),
                    paragraph_id=item.get("corrected_paragraph_id"),
                    auto_paragraph_id=item.get("auto_paragraph_id"),
                    paragraph_to_resolution=paragraph_to_resolution,
                    places_df=places_df,
                    orgs_df=orgs_df,
                )
            if paragraph_id:
                records.append(
                    {
                        "enriched_id": item["enriched_id"],
                        "paragraph_id": paragraph_id,
                        "session_id": item.get("session_id"),
                        "resolution_id": item.get("corrected_resolution_id"),
                        "source": "manual_correction",
                    }
                )

    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        paragraph_id = str(
            record.get("paragraph_id") or record.get("corrected_paragraph_id") or ""
        )
        key = (str(record.get("enriched_id", "")), paragraph_id)
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def build_blocked_paragraph_links(
    rejected_pairs: list[dict[str, str]],
    paragraph_to_resolution: dict[str, str],
    corrective_records: list[dict[str, Any]] | None = None,
) -> set[tuple[str, str]]:
    """enriched_id + paragraph_id pairs that must not be re-proposed after rejection."""
    blocked: set[tuple[str, str]] = set()
    resolution_to_paragraphs: dict[str, list[str]] = defaultdict(list)
    for paragraph_id, resolution_id in paragraph_to_resolution.items():
        resolution_to_paragraphs[str(resolution_id)].append(str(paragraph_id))

    for item in rejected_pairs:
        enriched_id = str(item.get("enriched_id", ""))
        resolution_id = str(item.get("flat_id", ""))
        if not enriched_id or not resolution_id:
            continue
        for paragraph_id in resolution_to_paragraphs.get(resolution_id, []):
            blocked.add((enriched_id, paragraph_id))

    for item in corrective_records or []:
        if item.get("action") != "rejected":
            continue
        enriched_id = str(item.get("enriched_id", ""))
        paragraph_id = str(item.get("auto_paragraph_id") or "")
        if enriched_id and paragraph_id:
            blocked.add((enriched_id, paragraph_id))

    return blocked


def load_corrective_records(output_dir: Path) -> list[dict[str, Any]]:
    corrective_path = output_dir / "corrective_ground_truth.json"
    if not corrective_path.exists():
        return []
    payload = json.loads(corrective_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def load_rejected_pairs(output_dir: Path, labeled: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Merge labeled false positives with imported rejections."""
    rejected: list[dict[str, str]] = [
        {
            "enriched_id": str(record["enriched_id"]),
            "flat_id": str(record["flat_id"]),
        }
        for record in labeled
        if record.get("verdict") == "false_positive"
    ]
    reject_keys = {(item["enriched_id"], item["flat_id"]) for item in rejected}

    state_path = output_dir / "alignment_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for item in state.get("rejected_pairs", []):
            key = (str(item.get("enriched_id", "")), str(item.get("flat_id", "")))
            if key[0] and key[1] and key not in reject_keys:
                rejected.append({"enriched_id": key[0], "flat_id": key[1]})
                reject_keys.add(key)

    corrective_path = output_dir / "corrective_ground_truth.json"
    if corrective_path.exists():
        for item in json.loads(corrective_path.read_text(encoding="utf-8")):
            if item.get("action") != "rejected":
                continue
            flat_id = str(item.get("auto_flat_id") or "")
            enriched_id = str(item.get("enriched_id") or "")
            key = (enriched_id, flat_id)
            if enriched_id and flat_id and key not in reject_keys:
                rejected.append({"enriched_id": enriched_id, "flat_id": flat_id})
                reject_keys.add(key)
    return rejected


def evaluate_chain_on_labeled(
    labeled: list[dict[str, Any]],
    alignments: list[dict[str, Any]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
) -> dict[str, dict[str, Any]]:
    by_enriched = {item["enriched_id"]: item["paragraph_id"] for item in alignments}
    by_session: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"correct_margin": [], "fp_margin": []})
    nw_correct: dict[str, list[bool]] = defaultdict(list)

    for record in labeled:
        verdict = record.get("verdict")
        if verdict not in {"correct", "false_positive"}:
            continue
        enriched_id = str(record["enriched_id"])
        flat_id = str(record["flat_id"])
        session_id = extract_session_id(flat_id) or "unknown"
        proposed_paragraph = by_enriched.get(enriched_id)
        anchors = anchor_paragraphs_for_pair(
            enriched_id, flat_id, places_df, orgs_df, paragraph_to_resolution
        )
        if not anchors:
            continue
        gt_paragraph = anchors[0]
        matches = proposed_paragraph == gt_paragraph
        nw_correct[session_id].append(matches)
        # margin proxy: 1 if match else 0 for chain evaluation
        bucket = "correct_margin" if verdict == "correct" else "fp_margin"
        by_session[session_id][bucket].append(1.0 if matches else 0.0)

    return {
        session_id: {
            "session_id": session_id,
            "count": len(values["correct_margin"]) + len(values["fp_margin"]),
            "chain_match_rate_correct": round(mean(values["correct_margin"]), 4) if values["correct_margin"] else None,
            "chain_match_rate_false_positive": round(mean(values["fp_margin"]), 4) if values["fp_margin"] else None,
            "nw_correct": round(mean(nw_correct[session_id]), 4) if nw_correct[session_id] else None,
        }
        for session_id, values in by_session.items()
    }


def evaluate_labeled_pairs(
    labeled: list[dict[str, Any]],
    proposed: dict[tuple[str, str], str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
) -> dict[str, Any]:
    """Precision = share of proposed alignments whose paragraph matches GT anchor."""
    judged = [record for record in labeled if record.get("verdict") in {"correct", "false_positive"}]
    retained = 0
    matches_gt = 0
    labeled_correct = 0
    labeled_false_positive = 0
    for record in judged:
        enriched_id = str(record["enriched_id"])
        flat_id = str(record["flat_id"])
        proposed_paragraph = proposed.get((enriched_id, flat_id))
        anchors = anchor_paragraphs_for_pair(
            enriched_id, flat_id, places_df, orgs_df, paragraph_to_resolution
        )
        if not proposed_paragraph or not anchors:
            continue
        retained += 1
        if record["verdict"] == "correct":
            labeled_correct += 1
        else:
            labeled_false_positive += 1
        if proposed_paragraph == anchors[0]:
            matches_gt += 1
    precision = matches_gt / retained if retained else 0.0
    return {
        "judged_pairs": len(judged),
        "proposed_pairs": retained,
        "matches_gt": matches_gt,
        "mismatches_gt": retained - matches_gt,
        "labeled_correct": labeled_correct,
        "labeled_false_positive": labeled_false_positive,
        "precision": round(precision, 4),
    }


def propagation_metrics_for_session(
    labeled: list[dict[str, Any]],
    analysis: list[dict[str, Any]],
    session_id: str,
) -> dict[str, Any]:
    session_labeled = [
        record
        for record in labeled
        if extract_session_id(str(record.get("flat_id", ""))) == session_id
        and record.get("verdict") in {"correct", "false_positive"}
    ]
    session_analysis = [result for result in analysis if result.get("session_id") == session_id]
    if not session_labeled:
        return {"session_id": session_id, "count": 0}
    correct = aggregate_metrics(session_analysis, "correct", "paragraph", "within_session")
    false_positive = aggregate_metrics(session_analysis, "false_positive", "paragraph", "within_session")
    return {
        "session_id": session_id,
        "count": len(session_labeled),
        "correct_margin": correct.get("mean_diag_margin"),
        "false_positive_margin": false_positive.get("mean_diag_margin"),
        "nw_correct": correct.get("nw_matches_gt_rate"),
        "nw_false_positive": false_positive.get("nw_matches_gt_rate"),
    }


def write_interactive_heatmaps_html(
    results: list[dict[str, Any]],
    session_order: list[str],
    output_path: Path,
) -> None:
    payload = []
    for result in results:
        heatmap = result.get("heatmaps", {}).get("paragraph_within_session")
        if not heatmap:
            continue
        payload.append(
            {
                "sample_id": result.get("sample_id"),
                "session_id": result.get("session_id"),
                "verdict": result.get("verdict"),
                "enriched_id": result.get("enriched_id"),
                "flat_id": result.get("flat_id"),
                "enriched_ids": heatmap["enriched_ids"],
                "flat_ids": heatmap["flat_ids"],
                "matrix": heatmap["matrix"],
                "gt_enriched_index": heatmap["gt_enriched_index"],
                "gt_flat_index": heatmap["gt_flat_index"],
                "nw_flat_index": heatmap.get("nw_flat_index"),
            }
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>Interactive Sequence Heatmaps</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #222; }}
h1, h2 {{ color: #1a365d; }}
.meta {{ color: #4a5568; }}
#tooltip {{
  position: fixed; display: none; background: #1a202c; color: #fff;
  padding: 10px 12px; border-radius: 6px; font-size: 13px; max-width: 420px;
  z-index: 1000; pointer-events: none; line-height: 1.4;
}}
.heatmap {{ display: grid; gap: 1px; margin: 12px 0 24px; }}
.cell {{
  width: 20px; height: 20px; border: 1px solid #edf2f7; cursor: crosshair;
}}
.cell.gt {{ outline: 2px solid #111; }}
.cell.nw {{ outline: 2px solid #d69e2e; }}
.block {{ margin-bottom: 36px; padding-bottom: 18px; border-bottom: 1px solid #e2e8f0; }}
</style></head><body>
<h1>Interactive Sequence Heatmaps</h1>
<p class='meta'>Hover a cell for enriched/paragraph ids and overlap score. Black outline = ground truth; gold = NW choice.</p>
<div id='tooltip'></div>
<div id='root'></div>
<script>
const DATA = {json.dumps(payload, ensure_ascii=False)};
const SESSION_ORDER = {json.dumps(session_order)};
const tooltip = document.getElementById('tooltip');
const root = document.getElementById('root');

function color(value, maxValue) {{
  if (maxValue <= 0) return '#ffffff';
  const t = Math.min(1, value / maxValue);
  const red = Math.round(255 - t * 180);
  const blue = Math.round(255 - t * 40);
  return `rgb(${{red}}, 220, ${{blue}})`;
}}

function showTip(event, text) {{
  tooltip.style.display = 'block';
  tooltip.innerHTML = text;
  tooltip.style.left = (event.clientX + 12) + 'px';
  tooltip.style.top = (event.clientY + 12) + 'px';
}}

function hideTip() {{ tooltip.style.display = 'none'; }}

const bySession = {{}};
for (const item of DATA) {{
  bySession[item.session_id] = bySession[item.session_id] || [];
  bySession[item.session_id].push(item);
}}

for (const sessionId of SESSION_ORDER) {{
  const items = bySession[sessionId];
  if (!items) continue;
  const section = document.createElement('section');
  section.className = 'block';
  section.innerHTML = `<h2>${{sessionId}}</h2>`;
  for (const item of items) {{
    const block = document.createElement('div');
    block.innerHTML = `<h3>Sample ${{item.sample_id}} — ${{item.enriched_id}} (${{item.verdict}})</h3>
      <p class='meta'>GT paragraph index ${{item.gt_flat_index}}; NW chose ${{item.nw_flat_index}}</p>`;
    const matrix = item.matrix;
    const maxValue = Math.max(...matrix.flat(), 1);
    const grid = document.createElement('div');
    grid.className = 'heatmap';
    grid.style.gridTemplateColumns = `repeat(${{matrix[0].length}}, 20px)`;
    for (let i = 0; i < matrix.length; i++) {{
      for (let j = 0; j < matrix[i].length; j++) {{
        const value = matrix[i][j];
        const cell = document.createElement('div');
        cell.className = 'cell';
        if (i === item.gt_enriched_index && j === item.gt_flat_index) cell.classList.add('gt');
        if (i === item.gt_enriched_index && j === item.nw_flat_index && j !== item.gt_flat_index) cell.classList.add('nw');
        cell.style.background = color(value, maxValue);
        const enrichedId = item.enriched_ids[i] || '';
        const paragraphId = item.flat_ids[j] || '';
        cell.addEventListener('mousemove', (event) => showTip(
          event,
          `<b>Score:</b> ${{value.toFixed(2)}}<br>` +
          `<b>Enriched:</b> ${{enrichedId}}<br>` +
          `<b>Paragraph:</b> ${{paragraphId}}`
        ));
        cell.addEventListener('mouseleave', hideTip);
        grid.appendChild(cell);
      }}
    }}
    block.appendChild(grid);
    section.appendChild(block);
  }}
  root.appendChild(section);
}}
</script></body></html>"""
    output_path.write_text(html, encoding="utf-8")


def run_chain_alignment(
    labeled: list[dict[str, Any]],
    curated: list[dict[str, Any]],
    manual_pin_records: list[dict[str, Any]],
    rejected_pairs: list[dict[str, str]],
    blocked_links: set[tuple[str, str]],
    enriched_by_date: dict[str, list[dict[str, Any]]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    paragraph_lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
    date_to_sessions: dict[str, set[str]],
    session_order: list[str],
    session_ranks: list[SessionRank],
    offset_penalty: float,
    state_version: int = 1,
    place_lookup: dict[tuple[str, str], set[str]] | None = None,
    org_lookup: dict[tuple[str, str], set[str]] | None = None,
    person_lookup: dict[tuple[str, str], set[str]] | None = None,
) -> AlignmentState:
    session_to_dates = invert_date_to_sessions(date_to_sessions)
    _, session_ranges, global_index_by_paragraph = build_global_paragraph_stream(
        session_order, places_df, orgs_df
    )

    lock_threshold = 0.65
    locked_sessions = [rank.session_id for rank in session_ranks if rank.precision >= lock_threshold]
    lock_priority = [rank.session_id for rank in session_ranks if rank.session_id in locked_sessions]

    alignments_out: list[dict[str, Any]] = []
    borders_out: list[dict[str, Any]] = []
    curated_pins_out: list[dict[str, str]] = []
    proposed_pairs: dict[tuple[str, str], str] = {}
    reject_keys = {(item["enriched_id"], item["flat_id"]) for item in rejected_pairs}

    prev_border: SessionBorder | None = None

    for session_id in session_order:
        paragraph_ids = paragraphs_in_sessions(places_df, orgs_df, {session_id})
        if not paragraph_ids:
            continue

        dates = session_to_dates.get(session_id, [])
        session_alignments: list[dict[str, Any]] = []
        expected_offset: int | None = None

        if prev_border and prev_border.last_global_index is not None:
            range_start, _ = session_ranges[session_id]
            expected_offset = prev_border.last_global_index + 1 - range_start

        for date_str in dates:
            day_enriched = enriched_by_date.get(date_str, [])
            enriched_ids = [enriched_volgnr(item) or "" for item in day_enriched]
            if not enriched_ids:
                continue

            manual_pins = direct_pins_for_session(
                manual_pin_records,
                session_id,
                enriched_ids,
                paragraph_ids,
            )
            pins = curated_pins_for_session(
                curated,
                session_id,
                places_df,
                orgs_df,
                paragraph_to_resolution,
                enriched_ids,
                paragraph_ids,
            )
            pins.update(manual_pins)
            manual_enriched = {
                enriched_ids[idx] for idx in manual_pins
            }
            for enriched_idx, paragraph_idx in pins.items():
                enriched_id = enriched_ids[enriched_idx]
                curated_pins_out.append(
                    {
                        "enriched_id": enriched_id,
                        "paragraph_id": paragraph_ids[paragraph_idx],
                        "session_id": session_id,
                        "source": "manual_correction" if enriched_id in manual_enriched else "curated_verification",
                    }
                )

            use_hints = bool(pins) or expected_offset is not None or bool(blocked_links)
            if use_hints:
                alignment = align_session_with_hints(
                    enriched_ids,
                    paragraph_ids,
                    paragraph_lookup,
                    idf_weights,
                    pinned=pins,
                    expected_offset=expected_offset,
                    offset_penalty=offset_penalty,
                    blocked=blocked_links,
                    place_lookup=place_lookup,
                    org_lookup=org_lookup,
                    person_lookup=person_lookup,
                )
            else:
                alignment = align_session(
                    enriched_ids,
                    paragraph_ids,
                    paragraph_lookup,
                    idf_weights,
                    anchor_only_diagonal=True,
                )

            for enriched_pos, flat_pos in alignment:
                if enriched_pos is None or flat_pos is None:
                    continue
                enriched_id = enriched_ids[enriched_pos]
                paragraph_id = paragraph_ids[flat_pos]
                resolution_id = paragraph_to_resolution.get(paragraph_id, "")
                if (enriched_id, resolution_id) in reject_keys:
                    continue
                proposed_pairs[(enriched_id, resolution_id)] = paragraph_id
                session_alignments.append(
                    {
                        "enriched_id": enriched_id,
                        "paragraph_id": paragraph_id,
                        "resolution_id": resolution_id,
                        "enriched_date": date_str,
                        "session_id": session_id,
                        "global_paragraph_index": global_index_by_paragraph.get(paragraph_id),
                        "pinned": enriched_pos in pins and pins[enriched_pos] == flat_pos,
                        "propagated_hint": use_hints and enriched_pos not in pins,
                    }
                )

            matched = [item for item in alignment if item[0] is not None and item[1] is not None]
            if matched:
                _, last_flat_pos = matched[-1]
                expected_offset = last_flat_pos + 1

        if session_alignments:
            alignments_out.extend(session_alignments)
            first = session_alignments[0]
            last = session_alignments[-1]
            border = SessionBorder(
                session_id=session_id,
                first_enriched_id=first["enriched_id"],
                first_paragraph_id=first["paragraph_id"],
                first_global_index=first["global_paragraph_index"],
                last_enriched_id=last["enriched_id"],
                last_paragraph_id=last["paragraph_id"],
                last_global_index=last["global_paragraph_index"],
            )
            borders_out.append(
                {
                    "session_id": border.session_id,
                    "first_enriched_id": border.first_enriched_id,
                    "first_paragraph_id": border.first_paragraph_id,
                    "first_global_index": border.first_global_index,
                    "last_enriched_id": border.last_enriched_id,
                    "last_paragraph_id": border.last_paragraph_id,
                    "last_global_index": border.last_global_index,
                }
            )
            prev_border = border
        elif prev_border:
            expected_offset = None

    return AlignmentState(
        version=state_version,
        scoring_params={
            "offset_penalty": offset_penalty,
            "pin_bonus": PIN_BONUS,
            "lock_precision_threshold": lock_threshold,
        },
        session_order=session_order,
        session_ranks=[rank.__dict__ for rank in session_ranks],
        locked_sessions=lock_priority,
        curated_pins=curated_pins_out,
        rejected_pairs=rejected_pairs,
        alignments=alignments_out,
        borders=borders_out,
        propagation_report={
            "evaluation": evaluate_labeled_pairs(
                labeled,
                proposed_pairs,
                places_df,
                orgs_df,
                paragraph_to_resolution,
            ),
            "lock_priority_order": lock_priority,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ordered session-chain alignment with propagation.")
    parser.add_argument("--labeled", type=Path, default=DEFAULT_LABELED)
    parser.add_argument("--curated", type=Path, default=DEFAULT_CURATED)
    parser.add_argument("--analysis", type=Path, default=OUTPUT_DIR / "sequence_overlap_analysis.json")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--offset-penalty", type=float, default=DEFAULT_OFFSET_PENALTY)
    parser.add_argument(
        "--audit-sample-per-session",
        type=int,
        default=25,
        help="Evenly spaced propagated links per session in the audit queue",
    )
    parser.add_argument(
        "--search-gap-sample-per-session",
        type=int,
        default=8,
        help="Max chain-gap search tasks per session (default 8; 0 = none)",
    )
    parser.add_argument(
        "--search-include-all-gaps",
        action="store_true",
        help="Include all chain-gap days in search_tasks (can be 400+ tasks)",
    )
    parser.add_argument(
        "--skip-import-corrections",
        action="store_true",
        help="Do not auto-import sequence_correction_summary*.json before alignment",
    )
    args = parser.parse_args()

    if not args.skip_import_corrections:
        from import_sequence_correction import auto_import_corrections

        import_summary = auto_import_corrections(args.output_dir)
        if import_summary:
            print(
                "Imported correction exports: "
                f"{import_summary['confirmed_pins_added']} pins, "
                f"{import_summary['rejected']} rejections "
                f"from {len(import_summary.get('source_files', []))} file(s)"
            )

    labeled = load_json(args.labeled)
    curated = load_json(args.curated) if args.curated.exists() else []
    analysis = load_json(args.analysis) if args.analysis.exists() else []
    if not isinstance(labeled, list):
        raise ValueError("Labeled JSON must be a list.")

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
        [LOC_ANNOTATIONS_FILE, ORG_ANNOTATIONS_FILE],
        paragraph_ids,
    )
    from analyze_sequence_entity_overlap import build_typed_paragraph_lookups

    paragraph_lookup, place_lookup, org_lookup, person_lookup = build_typed_paragraph_lookups(
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
    all_overlaps = pd.concat(overlap_frames, ignore_index=True)
    idf_weights = calculate_idf_weights(all_overlaps)
    enriched_by_date = build_enriched_by_date(enriched_all)
    date_to_sessions = build_date_to_session_map(places_df, orgs_df, paragraph_to_resolution)

    session_ranks = rank_sessions(labeled, analysis if isinstance(analysis, list) else None)
    session_order = sorted({rank.session_id for rank in session_ranks}, key=lambda sid: session_num_from_id(sid) or 0)

    manual_pin_records = load_manual_pin_records(
        args.output_dir,
        paragraph_to_resolution=paragraph_to_resolution,
        places_df=places_df,
        orgs_df=orgs_df,
    )
    rejected_pairs = load_rejected_pairs(args.output_dir, labeled)
    corrective_records = load_corrective_records(args.output_dir)
    blocked_links = build_blocked_paragraph_links(
        rejected_pairs,
        paragraph_to_resolution,
        corrective_records,
    )
    existing_version = 0
    if STATE_PATH.exists():
        existing_version = int(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("version", 0))

    state = run_chain_alignment(
        labeled,
        curated if isinstance(curated, list) else [],
        manual_pin_records,
        rejected_pairs,
        blocked_links,
        enriched_by_date,
        places_df,
        orgs_df,
        paragraph_to_resolution,
        paragraph_lookup,
        idf_weights,
        date_to_sessions,
        session_order,
        session_ranks,
        args.offset_penalty,
        state_version=existing_version + 1,
        place_lookup=place_lookup,
        org_lookup=org_lookup,
        person_lookup=person_lookup,
    )

    # Build full diagnostic results with heatmaps for interactive HTML.
    res_df = pd.read_parquet(RESOLUTIONS_FILE)
    res_df["session_id"] = res_df["id"].astype(str).str.extract(SESSION_ID_PATTERN, expand=False)
    from analyze_sequence_entity_overlap import analyze_labeled_pairs, build_resolution_overlap_lookup

    resolution_lookup = build_resolution_overlap_lookup(places_df, orgs_df, paragraph_to_resolution)
    full_results = analyze_labeled_pairs(
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
    chain_results = full_results
    before_metrics = {
        rank.session_id: propagation_metrics_for_session(labeled, analysis if isinstance(analysis, list) else [], rank.session_id)
        for rank in session_ranks
    }
    after_metrics = evaluate_chain_on_labeled(
        labeled,
        state.alignments,
        places_df,
        orgs_df,
        paragraph_to_resolution,
    )
    state.propagation_report["before_by_session"] = before_metrics
    state.propagation_report["after_by_session"] = after_metrics

    args.output_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.output_dir / "alignment_state.json"
    state_path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    heatmap_path = args.output_dir / "verify_sequence_heatmaps.html"
    write_interactive_heatmaps_html(full_results, session_order, heatmap_path)

    chain_by_enriched = {
        item["enriched_id"]: item["paragraph_id"] for item in state.alignments
    }
    preview_by_enriched = {
        str(record["enriched_id"]): record.get("enriched_preview", "")
        for record in labeled
        if record.get("enriched_id")
    }
    for result in full_results:
        eid = result.get("enriched_id")
        if eid and eid in preview_by_enriched:
            result["enriched_preview"] = preview_by_enriched[eid]

    comparison_sessions = build_session_comparison_payload(
        full_results,
        state.propagation_report,
        chain_by_enriched,
        labeled,
        res_df,
        paragraph_to_resolution,
    )
    comparison_path = args.output_dir / "verify_session_heatmap_comparison.html"
    write_session_heatmap_comparison_html(comparison_sessions, comparison_path)

    correction_records = build_correction_records(
        full_results,
        labeled,
        chain_by_enriched,
        paragraph_to_resolution,
        places_df,
        orgs_df,
        res_df,
        session_order,
        review_only=False,
    )
    correction_path = args.output_dir / "verify_sequence_alignment.html"
    write_sequence_alignment_html(correction_records, session_order, correction_path)
    corrections_json_path = args.output_dir / "sequence_correction_records.json"
    corrections_json_path.write_text(
        json.dumps(correction_records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    search_tasks = build_search_tasks(
        labeled,
        full_results,
        chain_by_enriched,
        paragraph_to_resolution,
        places_df,
        orgs_df,
        rejected_pairs,
        corrective_records,
        manual_pin_records,
        state.alignments,
        enriched_by_date,
        chain_gap_sample_per_session=args.search_gap_sample_per_session,
        include_all_chain_gaps=args.search_include_all_gaps,
    )
    search_path = args.output_dir / "verify_resolution_search.html"
    write_resolution_search_html(
        search_tasks,
        res_df,
        paragraph_to_resolution,
        search_path,
        year_min=1626,
        year_max=1630,
        places_df=places_df,
        orgs_df=orgs_df,
    )
    search_tasks_path = args.output_dir / "search_tasks.json"
    search_tasks_path.write_text(
        json.dumps(search_tasks, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    day_sequences = build_day_sequence_payload(
        enriched_by_date,
        res_df,
        state.alignments,
        labeled,
        rejected_pairs,
        state.curated_pins,
        places_df,
        orgs_df,
        paragraph_to_resolution,
    )
    day_sequence_path = args.output_dir / "verify_day_sequences.html"
    write_day_sequence_html(day_sequences, day_sequence_path)

    audit_payload = build_alignment_audit_records(
        state.alignments,
        labeled,
        state.curated_pins,
        rejected_pairs,
        enriched_by_date,
        res_df,
        paragraph_to_resolution,
        places_df,
        orgs_df,
        session_ranks,
        per_session_sample=args.audit_sample_per_session,
        place_lookup=place_lookup,
        org_lookup=org_lookup,
        person_lookup=person_lookup,
        idf_weights=idf_weights,
    )
    audit_path = args.output_dir / "verify_alignment_audit.html"
    write_alignment_audit_html(audit_payload, audit_path)
    audit_json_path = args.output_dir / "alignment_audit_queue.json"
    audit_json_path.write_text(
        json.dumps(audit_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    propagation_path = args.output_dir / "propagation_report.json"
    propagation_path.write_text(
        json.dumps(state.propagation_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    from build_pin_coverage_report import build_coverage_grid

    coverage_report = build_coverage_grid(
        state.to_dict(),
        state.alignments,
        places_df,
        orgs_df,
        persons_df,
        paragraph_to_resolution,
        enriched_all,
    )
    coverage_path = args.output_dir / "pin_coverage_report.json"
    placement_queue_path = args.output_dir / "pin_placement_queue.json"
    coverage_path.write_text(json.dumps(coverage_report, indent=2, ensure_ascii=False), encoding="utf-8")
    placement_queue_path.write_text(
        json.dumps(coverage_report["placement_queue"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    pin_placement_tasks = build_pin_placement_tasks(
        coverage_report["placement_queue"],
        enriched_by_date,
        places_df,
        orgs_df,
    )
    pin_placement_path = args.output_dir / "verify_pin_placement.html"
    write_pin_placement_html(
        pin_placement_tasks,
        res_df,
        paragraph_to_resolution,
        pin_placement_path,
        places_df=places_df,
        orgs_df=orgs_df,
    )

    print(f"✓ Alignment state: {state_path}")
    print(f"✓ Propagation report: {propagation_path}")
    print(f"✓ Interactive heatmaps: {heatmap_path}")
    print(f"✓ Session comparison: {comparison_path}")
    print(f"✓ Manual correction UI: {correction_path}")
    print(f"✓ Resolution search UI: {search_path} ({len(search_tasks)} tasks)")
    print(
        f"✓ Pin placement UI: {pin_placement_path} "
        f"({len(pin_placement_tasks)} gap tasks; "
        f"{coverage_report['summary']['cells_with_pins']}/{coverage_report['summary']['total_cells']} cells covered)"
    )
    print(f"✓ Day sequence view: {day_sequence_path} ({len(day_sequences)} days)")
    print(
        f"✓ Alignment audit UI: {audit_path} "
        f"(queue {audit_payload['summary']['audit_queue']} / {audit_payload['summary']['total_alignments']} total)"
    )
    print(f"✓ Correction records: {corrections_json_path}")
    print(f"  Blocked paragraph links: {len(blocked_links)}")
    print("  Session rank order (best first):")
    for rank in session_ranks:
        print(
            f"    {rank.session_id}: precision={rank.precision:.1%} "
            f"({rank.correct}/{rank.correct + rank.false_positive + rank.uncertain})"
        )
    print(f"  Locked sessions: {state.locked_sessions}")
    evaluation = state.propagation_report["evaluation"]
    print(
        f"  Alignment precision (paragraph matches GT): {evaluation['precision']:.1%} "
        f"({evaluation['matches_gt']}/{evaluation['proposed_pairs']})"
    )


if __name__ == "__main__":
    main()

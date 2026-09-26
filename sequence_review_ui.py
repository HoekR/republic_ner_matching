#!/usr/bin/env python3
"""HTML review UIs for sequence alignment: session heatmap comparison and manual correction."""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd

from analyze_sequence_entity_overlap import (
    anchor_paragraphs_for_pair,
    paragraphs_in_sessions,
    parse_paragraph_position,
    parse_resolution_position,
)
from build_alignment_new import (
    SESSION_ID_PATTERN,
    as_text,
    calculate_idf_weights,
    candidate_text,
    enriched_text,
    enriched_volgnr,
    extract_session_id,
    score_typed_overlap,
)


CORRECTION_CLI_BLOCK = """<pre style="margin:8px 0 0;font-size:0.82rem;white-space:pre-wrap;background:#f7fafc;padding:8px;border-radius:4px">uv run python import_sequence_correction.py --correction output/sequence_correction_summary.json
uv run python session_chain_alignment.py</pre>"""


def _color(value: float, max_value: float) -> str:
    if max_value <= 0:
        return "#ffffff"
    intensity = min(1.0, value / max_value)
    red = int(255 - intensity * 180)
    blue = int(255 - intensity * 40)
    return f"rgb({red}, 220, {blue})"


def build_session_comparison_payload(
    results: list[dict[str, Any]],
    propagation_report: dict[str, Any] | None,
    chain_by_enriched: dict[str, str],
    labeled: list[dict[str, Any]] | None = None,
    res_df: pd.DataFrame | None = None,
    paragraph_to_resolution: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build per-session comparison data: correct vs FP slice rows, paragraph vs resolution."""
    labeled_by_id = {
        str(record.get("enriched_id", "")): record for record in (labeled or [])
    }
    by_session: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_session.setdefault(result.get("session_id", "unknown"), []).append(result)

    sessions: list[dict[str, Any]] = []
    for session_id, session_results in sorted(by_session.items()):
        before = (propagation_report or {}).get("before_by_session", {}).get(session_id, {})
        after = (propagation_report or {}).get("after_by_session", {}).get(session_id, {})

        slices: list[dict[str, Any]] = []
        for result in sorted(session_results, key=lambda item: (item.get("verdict", ""), item.get("sample_id", 0))):
            para_hm = result.get("heatmaps", {}).get("paragraph_within_session")
            res_hm = result.get("heatmaps", {}).get("resolution_baseline")
            if not para_hm:
                continue

            enriched_i = para_hm["gt_enriched_index"]
            para_row = para_hm["matrix"][enriched_i] if enriched_i < len(para_hm["matrix"]) else []
            res_row = (
                res_hm["matrix"][enriched_i]
                if res_hm and enriched_i < len(res_hm["matrix"])
                else []
            )
            chain_paragraph = chain_by_enriched.get(result.get("enriched_id", ""))
            chain_index = None
            if chain_paragraph and chain_paragraph in para_hm["flat_ids"]:
                chain_index = para_hm["flat_ids"].index(chain_paragraph)

            labeled_row = labeled_by_id.get(str(result.get("enriched_id", "")), {})
            enriched_preview = (
                result.get("enriched_preview") or labeled_row.get("enriched_preview") or ""
            )[:400]
            flat_preview = (labeled_row.get("flat_preview") or "")[:400]
            paragraph_previews: list[str] = []
            if res_df is not None and paragraph_to_resolution:
                previews = paragraph_text_previews(
                    para_hm["flat_ids"], paragraph_to_resolution, res_df
                )
                paragraph_previews = [previews.get(pid, "")[:280] for pid in para_hm["flat_ids"]]

            slices.append(
                {
                    "sample_id": result.get("sample_id"),
                    "verdict": result.get("verdict"),
                    "enriched_id": result.get("enriched_id"),
                    "flat_id": result.get("flat_id"),
                    "enriched_preview": enriched_preview,
                    "flat_preview": flat_preview,
                    "chain_paragraph_id": chain_paragraph,
                    "diag_margin": next(
                        (
                            metric["diag_margin"]
                            for metric in result.get("metrics", [])
                            if metric.get("axis") == "paragraph" and metric.get("variant") == "within_session"
                        ),
                        None,
                    ),
                    "gt_flat_index": para_hm["gt_flat_index"],
                    "nw_flat_index": para_hm.get("nw_flat_index"),
                    "chain_flat_index": chain_index,
                    "paragraph_row": para_row,
                    "resolution_row": res_row,
                    "paragraph_ids": para_hm["flat_ids"],
                    "paragraph_previews": paragraph_previews,
                    "nw_matches_gt": para_hm.get("nw_flat_index") == para_hm["gt_flat_index"],
                }
            )

        correct_margins = [s["diag_margin"] for s in slices if s["verdict"] == "correct" and s["diag_margin"] is not None]
        fp_margins = [
            s["diag_margin"] for s in slices if s["verdict"] == "false_positive" and s["diag_margin"] is not None
        ]

        sessions.append(
            {
                "session_id": session_id,
                "before": before,
                "after": after,
                "mean_margin_correct": round(mean(correct_margins), 4) if correct_margins else None,
                "mean_margin_fp": round(mean(fp_margins), 4) if fp_margins else None,
                "slices": slices,
            }
        )

    return sessions


def write_session_heatmap_comparison_html(
    sessions: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Session-level heatmap comparison: correct vs FP slices, paragraph vs resolution rows."""
    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>Session Heatmap Comparison</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #222; }}
h1, h2, h3 {{ color: #1a365d; }}
.meta {{ color: #4a5568; font-size: 0.92em; }}
table {{ border-collapse: collapse; margin: 12px 0; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; }}
th {{ background: #edf2f7; }}
.session {{ margin-bottom: 48px; padding-bottom: 24px; border-bottom: 3px solid #cbd5e0; }}
.compare-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 16px 0; }}
.panel h4 {{ margin: 8px 0; }}
.slice-row {{ margin: 14px 0; padding: 10px; background: #f7fafc; border-radius: 6px; cursor: help; }}
.slice-row.correct {{ border-left: 4px solid #38a169; }}
.slice-row.false_positive {{ border-left: 4px solid #e53e3e; }}
.slice-row.uncertain {{ border-left: 4px solid #d69e2e; }}
.heatmap {{ display: grid; gap: 1px; overflow-x: auto; margin-top: 6px; }}
.cell {{ width: 8px; height: 18px; border: 1px solid #edf2f7; }}
.cell.gt {{ outline: 2px solid #111; z-index: 1; }}
.cell.nw {{ outline: 2px solid #d69e2e; }}
.cell.chain {{ outline: 2px solid #3182ce; }}
#tooltip {{
  position: fixed; display: none; background: #1a202c; color: #fff;
  padding: 10px 12px; border-radius: 6px; font-size: 12px; z-index: 1000; pointer-events: none;
  max-width: 440px; line-height: 1.45; white-space: normal;
}}
#tooltip .label {{ color: #90cdf4; font-weight: 600; margin-top: 6px; }}
#tooltip .label:first-child {{ margin-top: 0; }}
.legend span {{ margin-right: 16px; }}
.legend .gt {{ border-bottom: 3px solid #111; }}
.legend .nw {{ border-bottom: 3px solid #d69e2e; }}
.legend .chain {{ border-bottom: 3px solid #3182ce; }}
</style></head><body>
<h1>Session Heatmap Comparison</h1>
<p class='meta'>Each row is one labeled pair: overlap scores along the paragraph (or resolution) axis for that enriched resolution.
Black = ground-truth paragraph; gold = baseline NW; blue = chain alignment. Hover a sample row or heatmap cell for text.</p>
<p class='legend'><span class='gt'>■ GT</span><span class='nw'>■ NW</span><span class='chain'>■ Chain</span></p>
<div id='tooltip'></div>
<div id='root'></div>
<script>
const SESSIONS = {json.dumps(sessions, ensure_ascii=False)};
const tooltip = document.getElementById('tooltip');
const root = document.getElementById('root');

function color(value, maxValue) {{
  if (maxValue <= 0) return '#ffffff';
  const t = Math.min(1, value / maxValue);
  const red = Math.round(255 - t * 180);
  const blue = Math.round(255 - t * 40);
  return `rgb(${{red}}, 220, ${{blue}})`;
}}

function esc(s) {{
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function tip(event, text) {{
  tooltip.style.display = 'block';
  tooltip.innerHTML = text;
  tooltip.style.left = Math.min(event.clientX + 12, window.innerWidth - 460) + 'px';
  tooltip.style.top = Math.min(event.clientY + 12, window.innerHeight - 120) + 'px';
}}
function hideTip() {{ tooltip.style.display = 'none'; }}

function sampleTip(slice) {{
  const chainIdx = slice.chain_flat_index;
  const chainText = (chainIdx != null && slice.paragraph_previews)
    ? slice.paragraph_previews[chainIdx] : '';
  return `<div class="label">Enriched</div>${{esc(slice.enriched_preview) || '—'}}`
    + `<div class="label">Flat (verification GT)</div>${{esc(slice.flat_preview) || '—'}}`
    + (chainText ? `<div class="label">Chain-linked flat</div>${{esc(chainText)}}` : '');
}}

function renderRow(container, row, slice, ids, previews, gt, nw, chain, label) {{
  const maxValue = Math.max(...row, 1);
  const wrap = document.createElement('div');
  wrap.innerHTML = `<div class='meta'>${{label}} (${{row.length}} columns)</div>`;
  const grid = document.createElement('div');
  grid.className = 'heatmap';
  grid.style.gridTemplateColumns = `repeat(${{row.length}}, 8px)`;
  row.forEach((value, j) => {{
    const cell = document.createElement('div');
    cell.className = 'cell';
    if (j === gt) cell.classList.add('gt');
    if (j === nw && nw !== gt) cell.classList.add('nw');
    if (j === chain && chain !== gt && chain !== nw) cell.classList.add('chain');
    if (j === chain && chain === gt) cell.classList.add('gt');
    cell.style.background = color(value, maxValue);
    const pid = ids[j] || '';
    const preview = (previews && previews[j]) ? `<div class="label">Text</div>${{esc(previews[j])}}` : '';
    const markers = [];
    if (j === gt) markers.push('GT');
    if (j === nw) markers.push('NW');
    if (j === chain) markers.push('Chain');
    cell.addEventListener('mousemove', e => tip(e,
      `<b>${{label}}</b> j=${{j}} score=${{value.toFixed(2)}}`
      + (markers.length ? ` · ${{markers.join(', ')}}` : '')
      + `<br>${{esc(pid)}}` + preview));
    cell.addEventListener('mouseleave', hideTip);
    grid.appendChild(cell);
  }});
  wrap.appendChild(grid);
  container.appendChild(wrap);
}}

for (const session of SESSIONS) {{
  const section = document.createElement('section');
  section.className = 'session';
  section.innerHTML = `
    <h2>${{session.session_id}}</h2>
    <table>
      <tr><th></th><th>Before NW (correct)</th><th>Before NW (FP)</th><th>After chain</th><th>Mean margin correct</th><th>Mean margin FP</th></tr>
      <tr>
        <td>Metrics</td>
        <td>${{session.before?.nw_correct ?? '—'}}</td>
        <td>${{session.before?.nw_false_positive ?? '—'}}</td>
        <td>${{session.after?.nw_correct ?? '—'}}</td>
        <td>${{session.mean_margin_correct ?? '—'}}</td>
        <td>${{session.mean_margin_fp ?? '—'}}</td>
      </tr>
    </table>
    <div class='compare-grid'>
      <div class='panel'><h3>Correct pairs</h3><div id='c-${{session.session_id}}'></div></div>
      <div class='panel'><h3>False positives</h3><div id='f-${{session.session_id}}'></div></div>
    </div>`;
  root.appendChild(section);

  const correctPanel = section.querySelector(`#c-${{session.session_id}}`);
  const fpPanel = section.querySelector(`#f-${{session.session_id}}`);

  for (const slice of session.slices) {{
    const target = slice.verdict === 'correct' ? correctPanel : fpPanel;
    if (!target) continue;
    const row = document.createElement('div');
    row.className = `slice-row ${{slice.verdict}}`;
    row.innerHTML = `<h4>Sample ${{slice.sample_id}} — ${{slice.enriched_id}}</h4>
      <p class='meta'>margin=${{slice.diag_margin}}; GT j=${{slice.gt_flat_index}}; NW j=${{slice.nw_flat_index}}; chain j=${{slice.chain_flat_index}}</p>`;
    row.addEventListener('mouseenter', e => tip(e, sampleTip(slice)));
    row.addEventListener('mousemove', e => tip(e, sampleTip(slice)));
    row.addEventListener('mouseleave', hideTip);
    renderRow(row, slice.paragraph_row, slice, slice.paragraph_ids, slice.paragraph_previews, slice.gt_flat_index, slice.nw_flat_index, slice.chain_flat_index, 'Paragraph');
    if (slice.resolution_row.length) {{
      renderRow(row, slice.resolution_row, slice, slice.paragraph_ids.slice(0, slice.resolution_row.length), slice.paragraph_previews, slice.gt_flat_index, slice.nw_flat_index, null, 'Resolution');
    }}
    target.appendChild(row);
  }}
}}
</script></body></html>"""
    output_path.write_text(html, encoding="utf-8")


def build_typed_paragraph_lookups(
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
) -> tuple[dict[tuple[str, str], set[str]], dict[tuple[str, str], set[str]]]:
    place_lookup: dict[tuple[str, str], set[str]] = {}
    org_lookup: dict[tuple[str, str], set[str]] = {}
    for source_df, target in ((places_df, place_lookup), (orgs_df, org_lookup)):
        for _, row in source_df.iterrows():
            if pd.isna(row["volgnr"]) or pd.isna(row["paragraph_id"]) or pd.isna(row["name"]):
                continue
            key = (str(row["volgnr"]).strip(), str(row["paragraph_id"]).strip())
            target.setdefault(key, set()).add(str(row["name"]).strip())
    return place_lookup, org_lookup


def paragraph_text_previews(
    paragraph_ids: list[str],
    paragraph_to_resolution: dict[str, str],
    res_df: pd.DataFrame,
) -> dict[str, str]:
    text_by_resolution = {
        str(row["id"]): candidate_text(row)[:320]
        for _, row in res_df.iterrows()
    }
    previews: dict[str, str] = {}
    for paragraph_id in paragraph_ids:
        resolution_id = paragraph_to_resolution.get(paragraph_id, "")
        previews[paragraph_id] = text_by_resolution.get(resolution_id, "")
    return previews


def rank_paragraph_candidates(
    enriched_id: str,
    paragraph_ids: list[str],
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    idf_place: dict[str, float],
    idf_org: dict[str, float],
    center_paragraph: str | None,
    limit: int = 18,
) -> list[dict[str, Any]]:
    """Rank paragraph candidates by dual place/org signals with agreement bonus."""
    scored: list[dict[str, Any]] = []
    for paragraph_id in paragraph_ids:
        places = place_lookup.get((enriched_id, paragraph_id), set())
        orgs = org_lookup.get((enriched_id, paragraph_id), set())
        score_place = sum(idf_place.get(name, 1.0) for name in places)
        score_org = sum(idf_org.get(name, 1.0) for name in orgs)
        agreement = min(score_place, score_org) if places and orgs else 0.0
        total = score_place + score_org + (0.5 * agreement)
        scored.append(
            {
                "paragraph_id": paragraph_id,
                "places": sorted(places),
                "orgs": sorted(orgs),
                "score_place": round(score_place, 3),
                "score_org": round(score_org, 3),
                "score_total": round(total, 3),
                "signal": (
                    "both" if places and orgs else ("places_only" if places else ("orgs_only" if orgs else "none"))
                ),
            }
        )

    scored.sort(key=lambda item: (-item["score_total"], item["paragraph_id"]))
    if center_paragraph and center_paragraph in paragraph_ids:
        top_ids = {item["paragraph_id"] for item in scored[:limit]}
        center_item = next(item for item in scored if item["paragraph_id"] == center_paragraph)
        ranked = scored[:limit]
        if center_paragraph not in top_ids:
            ranked = ranked[:-1] + [center_item]
            ranked.sort(key=lambda item: (-item["score_total"], item["paragraph_id"]))
    else:
        ranked = scored[:limit]

    # Add local sequence context: neighbours in full paragraph list
    index_by_id = {pid: idx for idx, pid in enumerate(paragraph_ids)}
    for item in ranked:
        idx = index_by_id.get(item["paragraph_id"])
        item["stream_index"] = idx
    ranked.sort(key=lambda item: (item["stream_index"] is None, item["stream_index"] or 0))
    return ranked


def build_correction_records(
    results: list[dict[str, Any]],
    labeled: list[dict[str, Any]],
    chain_by_enriched: dict[str, str],
    paragraph_to_resolution: dict[str, str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    res_df: pd.DataFrame,
    session_order: list[str],
    candidate_limit: int = 18,
    review_only: bool = False,
) -> list[dict[str, Any]]:
    """Build annotation tasks: ranked text previews + separate place/org signals."""
    place_lookup, org_lookup = build_typed_paragraph_lookups(places_df, orgs_df)
    idf_place = calculate_idf_weights(places_df)
    idf_org = calculate_idf_weights(orgs_df)

    labeled_by_id = {str(record.get("enriched_id", "")): record for record in labeled}
    priority = {"false_positive": 0, "uncertain": 1, "correct": 2}
    records: list[dict[str, Any]] = []

    for result in results:
        enriched_id = str(result.get("enriched_id", ""))
        flat_id = str(result.get("flat_id", ""))
        verdict = str(result.get("verdict", ""))
        session_id = str(result.get("session_id", ""))
        para_hm = result.get("heatmaps", {}).get("paragraph_within_session")
        if not para_hm:
            continue

        labeled_row = labeled_by_id.get(enriched_id, {})
        proposed_paragraph = chain_by_enriched.get(enriched_id)
        if not proposed_paragraph:
            gt_j = para_hm.get("gt_flat_index", -1)
            if 0 <= gt_j < len(para_hm["flat_ids"]):
                proposed_paragraph = para_hm["flat_ids"][gt_j]

        anchor_paragraphs = result.get("anchor_paragraphs") or []
        auto_paragraph = anchor_paragraphs[0] if anchor_paragraphs else proposed_paragraph

        nw_matches = para_hm.get("nw_flat_index") == para_hm.get("gt_flat_index")
        needs_review = verdict in {"false_positive", "uncertain"} or not nw_matches
        if review_only and not needs_review:
            continue

        stream_ids = para_hm["flat_ids"]
        candidates = rank_paragraph_candidates(
            enriched_id,
            stream_ids,
            place_lookup,
            org_lookup,
            idf_place,
            idf_org,
            center_paragraph=proposed_paragraph or auto_paragraph,
            limit=candidate_limit,
        )
        candidate_ids = [item["paragraph_id"] for item in candidates]
        text_previews = paragraph_text_previews(candidate_ids, paragraph_to_resolution, res_df)

        enriched_places = sorted(labeled_row.get("shared_places_excel") or [])
        enriched_orgs = sorted(labeled_row.get("shared_orgs_excel") or [])
        if not enriched_places and not enriched_orgs:
            enriched_places = sorted(
                place_lookup.get((enriched_id, auto_paragraph or ""), set())
            )
            enriched_orgs = sorted(org_lookup.get((enriched_id, auto_paragraph or ""), set()))

        for item in candidates:
            item["text_preview"] = text_previews.get(item["paragraph_id"], "")
            item["is_auto"] = item["paragraph_id"] == (proposed_paragraph or auto_paragraph)
            item["resolution_id"] = paragraph_to_resolution.get(item["paragraph_id"], "")

        records.append(
            {
                "correction_id": str(result.get("sample_id")),
                "session_id": session_id,
                "enriched_id": enriched_id,
                "enriched_date": result.get("enriched_date") or labeled_row.get("enriched_date"),
                "auto_flat_id": flat_id,
                "auto_paragraph_id": proposed_paragraph or auto_paragraph,
                "enriched_preview": (
                    result.get("enriched_preview") or labeled_row.get("enriched_preview", "")
                )[:500],
                "flat_preview_auto": (labeled_row.get("flat_preview") or "")[:500],
                "enriched_places": enriched_places,
                "enriched_orgs": enriched_orgs,
                "candidates": candidates,
                "verdict": verdict,
                "needs_review": needs_review,
                "nw_matches_gt": nw_matches,
                "priority": priority.get(verdict, 9),
            }
        )

    records.sort(key=lambda item: (item["priority"], item.get("session_id", ""), int(item["correction_id"])))
    return records


def write_sequence_alignment_html(
    records: list[dict[str, Any]],
    session_order: list[str],
    output_path: Path,
    page_size: int = 1,
) -> None:
    """R2 UI: click-to-select paragraph correction with place/org signals."""
    payload = json.dumps(records, ensure_ascii=False)
    order_json = json.dumps(session_order, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>Alignment Correction Annotator</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; background: #eef2f7; margin: 0; color: #1a202c; }}
.header {{ background: white; padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
h1 {{ margin: 0 0 6px; color: #1a365d; font-size: 1.4rem; }}
.meta {{ color: #4a5568; font-size: 0.92rem; }}
.toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; align-items: center; }}
.toolbar button {{ padding: 8px 14px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }}
.toolbar .primary {{ background: #2b6cb0; color: white; }}
.toolbar .muted {{ background: #4a5568; color: white; }}
.toolbar label {{ font-size: 0.9rem; }}
.main {{ display: grid; grid-template-columns: 1fr 1.2fr; gap: 16px; padding: 16px 24px 40px; max-width: 1400px; }}
.panel {{ background: white; border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
.panel h2 {{ margin: 0 0 12px; font-size: 1rem; color: #2d3748; }}
.preview {{ font-family: Georgia, serif; font-size: 0.95rem; line-height: 1.55; background: #f7fafc; padding: 12px; border-radius: 8px; white-space: pre-wrap; max-height: 220px; overflow-y: auto; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }}
.chip {{ font-size: 0.75rem; padding: 3px 8px; border-radius: 999px; }}
.chip.place {{ background: #bee3f8; color: #2c5282; }}
.chip.org {{ background: #faf089; color: #744210; }}
.candidate {{ border: 2px solid #e2e8f0; border-radius: 8px; padding: 10px; margin-bottom: 8px; cursor: pointer; transition: border-color .15s; }}
.candidate:hover {{ border-color: #90cdf4; }}
.candidate.selected {{ border-color: #2b6cb0; background: #ebf8ff; }}
.candidate.auto {{ border-left: 4px solid #d69e2e; }}
.candidate .hdr {{ display: flex; justify-content: space-between; font-size: 0.8rem; color: #718096; margin-bottom: 6px; }}
.candidate .scores {{ font-size: 0.78rem; color: #4a5568; }}
.candidate .text {{ font-family: Georgia, serif; font-size: 0.88rem; line-height: 1.45; color: #2d3748; max-height: 72px; overflow: hidden; }}
.badge {{ font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; background: #edf2f7; }}
.badge.both {{ background: #c6f6d5; }}
.badge.fp {{ background: #fed7d7; }}
.actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }}
.actions button {{ flex: 1; min-width: 120px; padding: 10px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }}
.btn-confirm {{ background: #38a169; color: white; }}
.btn-auto {{ background: #3182ce; color: white; }}
.btn-reject {{ background: #e53e3e; color: white; }}
.btn-skip {{ background: #a0aec0; color: white; }}
.status {{ margin-top: 12px; padding: 10px; border-radius: 6px; font-size: 0.9rem; display: none; }}
.status.show {{ display: block; }}
.status.confirmed {{ background: #c6f6d5; }}
.status.rejected {{ background: #fed7d7; }}
.status.uncertain {{ background: #feebc8; }}
.pagination {{ display: flex; justify-content: center; gap: 16px; padding: 12px; }}
.pagination button {{ padding: 10px 20px; background: #4a5568; color: white; border: none; border-radius: 6px; cursor: pointer; }}
.note {{ margin: 0 24px 20px; padding: 12px 16px; background: #ebf8ff; border-left: 4px solid #3182ce; font-size: 0.9rem; }}
</style></head><body>
<div class='header'>
  <h1>Alignment Correction Annotator</h1>
  <p class='meta'>Click the flat paragraph that matches the enriched resolution. Place and org signals are shown separately — prefer candidates where both agree.</p>
  <div class='toolbar'>
    <span id='progress' class='meta'>0 / 0</span>
    <label><input type='checkbox' id='reviewOnly' checked> Needs review only</label>
    <button class='primary' onclick='exportCorrections()'>Export corrections</button>
    <button class='muted' onclick='clearStorage()'>Clear saved</button>
  </div>
</div>
<p class='note'><b>Workflow:</b> 1) Read enriched text (left). 2) Click matching paragraph (right). 3) Confirm — or Confirm auto if correct, Reject if no match, Skip if uncertain. Export → move <code>sequence_correction_summary.json</code> to <code>output/</code>, then run:{CORRECTION_CLI_BLOCK}</p>
<div id='task'></div>
<div class='pagination'>
  <button id='prevBtn' onclick='changePage(-1)'>← Previous</button>
  <span id='pageInfo' class='meta'>Page 1</span>
  <button id='nextBtn' onclick='changePage(1)'>Next →</button>
</div>
<script>
const ALL_RECORDS = {payload};
const STORAGE_KEY = 'sequence_alignment_corrections_v2';
let RECORDS = [];
let page = 0;
let corrections = {{}};
let selectedParagraph = null;

function loadStorage() {{
  try {{ corrections = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch(e) {{ corrections = {{}}; }}
}}
function saveStorage() {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(corrections)); }}

function applyFilter() {{
  const reviewOnly = document.getElementById('reviewOnly').checked;
  RECORDS = reviewOnly ? ALL_RECORDS.filter(r => r.needs_review) : ALL_RECORDS;
  page = Math.min(page, Math.max(0, Math.ceil(RECORDS.length / 1) - 1));
  render();
}}

function esc(s) {{
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function chips(names, cls) {{
  return (names || []).map(n => `<span class="chip ${{cls}}">${{esc(n)}}</span>`).join('');
}}

function render() {{
  if (!RECORDS.length) {{
    document.getElementById('task').innerHTML = '<p class="meta" style="padding:24px">No records match filter.</p>';
    return;
  }}
  const rec = RECORDS[page];
  const saved = corrections[rec.correction_id];
  selectedParagraph = saved?.corrected_paragraph_id || selectedParagraph || rec.auto_paragraph_id;

  const verdictBadge = rec.verdict === 'false_positive' ? '<span class="badge fp">prior: false positive</span>' : '';
  const autoCand = rec.candidates.find(c => c.is_auto);

  let candidatesHtml = rec.candidates.map(c => `
    <div class="candidate ${{c.is_auto ? 'auto' : ''}} ${{c.paragraph_id === selectedParagraph ? 'selected' : ''}}"
         data-pid="${{esc(c.paragraph_id)}}" onclick="selectCandidate('${{rec.correction_id}}', '${{c.paragraph_id}}')">
      <div class="hdr">
        <span>#${{c.stream_index ?? '?'}} · ${{esc(c.paragraph_id)}}</span>
        <span class="scores">place ${{c.score_place}} · org ${{c.score_org}} · <span class="badge ${{c.signal === 'both' ? 'both' : ''}}">${{c.signal}}</span></span>
      </div>
      <div class="chips">${{chips(c.places, 'place')}}${{chips(c.orgs, 'org')}}</div>
      <div class="text">${{esc(c.text_preview) || '(no text preview)'}}</div>
    </div>`).join('');

  document.getElementById('task').innerHTML = `
    <div style="padding:0 24px 8px" class="meta">${{esc(rec.session_id)}} · ${{esc(rec.enriched_id)}} · ${{esc(rec.enriched_date)}} ${{verdictBadge}}</div>
    <div class="main">
      <div class="panel">
        <h2>Enriched resolution</h2>
        <div class="chips">${{chips(rec.enriched_places, 'place')}}${{chips(rec.enriched_orgs, 'org')}}</div>
        <div class="preview">${{esc(rec.enriched_preview)}}</div>
        <h2 style="margin-top:16px">Auto-linked flat (likely wrong if FP)</h2>
        <div class="meta">${{esc(rec.auto_flat_id)}}</div>
        <div class="preview">${{esc(rec.flat_preview_auto)}}</div>
      </div>
      <div class="panel">
        <h2>Pick matching paragraph (${{rec.candidates.length}} candidates, ranked)</h2>
        <div id="candidates">${{candidatesHtml}}</div>
        <div class="actions">
          <button class="btn-confirm" onclick="saveCorrection('${{rec.correction_id}}', 'confirmed')">Confirm selection</button>
          <button class="btn-auto" onclick="confirmAuto('${{rec.correction_id}}')">Confirm auto</button>
          <button class="btn-reject" onclick="saveCorrection('${{rec.correction_id}}', 'rejected')">No match</button>
          <button class="btn-skip" onclick="saveCorrection('${{rec.correction_id}}', 'uncertain')">Uncertain</button>
        </div>
        <div id="status-${{rec.correction_id}}" class="status ${{saved ? 'show ' + saved.action : ''}}">${{saved ? 'Saved: ' + saved.action : ''}}</div>
      </div>
    </div>`;

  if (saved) {{
    const st = document.getElementById('status-' + rec.correction_id);
    st.textContent = 'Saved: ' + saved.action + (saved.corrected_paragraph_id ? ' → ' + saved.corrected_paragraph_id : '');
  }}

  document.getElementById('progress').textContent = `${{Object.keys(corrections).length}} saved · task ${{page + 1}} / ${{RECORDS.length}} (${{ALL_RECORDS.length}} total)`;
  document.getElementById('pageInfo').textContent = `Task ${{page + 1}} / ${{RECORDS.length}}`;
  document.getElementById('prevBtn').disabled = page <= 0;
  document.getElementById('nextBtn').disabled = page >= RECORDS.length - 1;
}}

function selectCandidate(correctionId, paragraphId) {{
  selectedParagraph = paragraphId;
  render();
}}

function confirmAuto(correctionId) {{
  const rec = RECORDS.find(r => r.correction_id === correctionId);
  selectedParagraph = rec.auto_paragraph_id;
  saveCorrection(correctionId, 'confirmed');
}}

function saveCorrection(id, action) {{
  const rec = RECORDS.find(r => r.correction_id === id) || ALL_RECORDS.find(r => r.correction_id === id);
  const pid = action === 'rejected' ? null : (selectedParagraph || rec.auto_paragraph_id);
  const cand = rec.candidates.find(c => c.paragraph_id === pid) || {{}};
  corrections[id] = {{
    correction_id: id,
    enriched_id: rec.enriched_id,
    session_id: rec.session_id,
    action: action,
    corrected_paragraph_id: pid,
    corrected_resolution_id: cand.resolution_id || null,
    auto_paragraph_id: rec.auto_paragraph_id,
    auto_flat_id: rec.auto_flat_id,
    prior_verdict: rec.verdict,
    place_score: cand.score_place ?? null,
    org_score: cand.score_org ?? null,
    signal: cand.signal ?? null,
    timestamp: new Date().toISOString(),
  }};
  saveStorage();
  if (page < RECORDS.length - 1 && action !== 'uncertain') page += 1;
  render();
}}

function exportCorrections() {{
  const payload = {{
    total: ALL_RECORDS.length,
    filtered: RECORDS.length,
    corrected: Object.values(corrections).filter(c => c.action === 'confirmed').length,
    rejected: Object.values(corrections).filter(c => c.action === 'rejected').length,
    uncertain: Object.values(corrections).filter(c => c.action === 'uncertain').length,
    corrections: corrections,
  }};
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{type:'application/json'}}));
  a.download = 'sequence_correction_summary.json';
  a.click();
}}

function clearStorage() {{
  if (confirm('Clear all saved corrections?')) {{ corrections = {{}}; localStorage.removeItem(STORAGE_KEY); render(); }}
}}

function changePage(d) {{
  page = Math.max(0, Math.min(RECORDS.length - 1, page + d));
  selectedParagraph = null;
  render();
}}

document.getElementById('reviewOnly').addEventListener('change', () => {{ page = 0; applyFilter(); }});
loadStorage();
applyFilter();
</script></body></html>"""
    output_path.write_text(html, encoding="utf-8")


def _resolution_index_text(row: pd.Series) -> str:
    """Searchable flat text: prefer resolutions_text, else join parsed paragraph_texts."""
    for field in ("resolutions_text", "paragraph_texts", "paragraph_text"):
        raw = row.get(field)
        if raw is None or str(raw) == "nan" or not str(raw).strip():
            continue
        if field == "paragraph_texts" and isinstance(raw, str) and raw.strip().startswith("["):
            try:
                paragraphs = ast.literal_eval(raw)
                if isinstance(paragraphs, list) and paragraphs:
                    return " ".join(str(part) for part in paragraphs if part)
            except (SyntaxError, ValueError):
                pass
        text = as_text(raw)
        if text.strip():
            return text
    return ""


def _entity_names_by_resolution(
    paragraph_to_resolution: dict[str, str],
    places_df: pd.DataFrame | None,
    orgs_df: pd.DataFrame | None,
) -> dict[str, set[str]]:
    names_by_resolution: dict[str, set[str]] = defaultdict(set)
    for source_df in (places_df, orgs_df):
        if source_df is None or source_df.empty:
            continue
        name_col = "name" if "name" in source_df.columns else "naam"
        for _, row in source_df.iterrows():
            paragraph_id = str(row.get("paragraph_id", "")).strip()
            resolution_id = paragraph_to_resolution.get(paragraph_id)
            entity_name = str(row.get(name_col, "")).strip().lower()
            if resolution_id and entity_name:
                names_by_resolution[str(resolution_id)].add(entity_name)
    return names_by_resolution


def suggested_search_terms_for_enriched(
    enriched_id: str,
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
) -> list[str]:
    """Entity names from overlap rows for this enrichment (HTR-robust search hints)."""
    terms: set[str] = set()
    for source_df in (places_df, orgs_df):
        name_col = "name" if "name" in source_df.columns else "naam"
        rows = source_df[source_df["volgnr"].astype(str) == enriched_id]
        for value in rows[name_col].dropna().astype(str):
            token = value.strip().lower()
            if len(token) >= 3:
                terms.add(token)
    return sorted(terms)


def build_resolution_search_index(
    res_df: pd.DataFrame,
    year_min: int,
    year_max: int,
    paragraph_to_resolution: dict[str, str] | None = None,
    places_df: pd.DataFrame | None = None,
    orgs_df: pd.DataFrame | None = None,
) -> list[dict[str, str]]:
    subset = res_df[(res_df["year"] >= year_min) & (res_df["year"] <= year_max)].copy()
    if "session_id" not in subset.columns:
        subset["session_id"] = subset["id"].astype(str).str.extract(SESSION_ID_PATTERN, expand=False)
    entity_names = _entity_names_by_resolution(
        paragraph_to_resolution or {},
        places_df,
        orgs_df,
    )
    index: list[dict[str, str]] = []
    for _, row in subset.iterrows():
        resolution_id = str(row["id"])
        text = _resolution_index_text(row)
        entities = " ".join(sorted(entity_names.get(resolution_id, set())))
        if not text.strip() and not entities:
            continue
        index.append(
            {
                "id": resolution_id,
                "date": str(row.get("date", ""))[:10],
                "session_id": str(row.get("session_id") or ""),
                "text": text[:1200],
                "entities": entities[:600],
            }
        )
    return index


def build_resolution_paragraph_map(
    paragraph_to_resolution: dict[str, str],
    res_df: pd.DataFrame,
) -> dict[str, list[dict[str, str]]]:
    text_by_resolution = {
        str(row["id"]): candidate_text(row)
        for _, row in res_df.iterrows()
    }
    by_resolution: dict[str, list[str]] = defaultdict(list)
    for paragraph_id, resolution_id in paragraph_to_resolution.items():
        by_resolution[str(resolution_id)].append(str(paragraph_id))

    paragraph_map: dict[str, list[dict[str, str]]] = {}
    for resolution_id, paragraph_ids in by_resolution.items():
        ordered = sorted(paragraph_ids, key=lambda pid: parse_paragraph_position(pid) or (0, 0, 0))
        resolution_text = text_by_resolution.get(resolution_id, "")
        items: list[dict[str, str]] = []
        for paragraph_id in ordered:
            items.append(
                {
                    "paragraph_id": paragraph_id,
                    "preview": resolution_text[:500],
                }
            )
        paragraph_map[resolution_id] = items
    return paragraph_map


def build_search_tasks(
    labeled: list[dict[str, Any]],
    results: list[dict[str, Any]],
    chain_by_enriched: dict[str, str],
    paragraph_to_resolution: dict[str, str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    rejected_pairs: list[dict[str, str]],
    corrective_records: list[dict[str, Any]],
    manual_pin_records: list[dict[str, Any]],
    alignments: list[dict[str, Any]] | None = None,
    enriched_by_date: dict[str, list[dict[str, Any]]] | None = None,
    chain_gap_sample_per_session: int = 8,
    include_all_chain_gaps: bool = False,
) -> list[dict[str, Any]]:
    """Tasks for manual search: prioritized mismatches and a sampled gap queue."""
    labeled_by_id = {str(record.get("enriched_id", "")): record for record in labeled}
    reject_keys = {(item["enriched_id"], item["flat_id"]) for item in rejected_pairs}
    confirmed_enriched = {
        str(item.get("enriched_id", ""))
        for item in corrective_records
        if item.get("action") == "confirmed"
    }
    confirmed_enriched.update(str(item.get("enriched_id", "")) for item in manual_pin_records)

    blocked_by_enriched: dict[str, list[str]] = defaultdict(list)
    for item in corrective_records:
        if item.get("action") == "rejected" and item.get("auto_paragraph_id"):
            blocked_by_enriched[str(item["enriched_id"])].append(str(item["auto_paragraph_id"]))

    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()

    def sibling_hint_resolution(enriched_id: str, enriched_date: str) -> str | None:
        if not enriched_by_date:
            return None
        day_rows = enriched_by_date.get(enriched_date, [])
        enriched_ids = [enriched_volgnr(item) or "" for item in day_rows]
        if enriched_id not in enriched_ids:
            return None
        index = enriched_ids.index(enriched_id)
        for neighbor_index in (index - 1, index + 1):
            if 0 <= neighbor_index < len(enriched_ids):
                paragraph_id = chain_by_enriched.get(enriched_ids[neighbor_index])
                if paragraph_id:
                    return paragraph_to_resolution.get(paragraph_id)
        return None

    def add_task(
        enriched_id: str,
        labeled_row: dict[str, Any] | None,
        result: dict[str, Any] | None,
        reason: str,
        enriched_record: dict[str, Any] | None = None,
    ) -> None:
        if enriched_id in seen or enriched_id in confirmed_enriched:
            return
        labeled_row = labeled_row or {}
        enriched_record = enriched_record or {}
        enriched_date = (
            labeled_row.get("enriched_date")
            or (result or {}).get("enriched_date")
            or str(enriched_record.get("date", ""))[:10]
        )
        flat_id = str(labeled_row.get("flat_id", ""))
        chain_paragraph = chain_by_enriched.get(enriched_id)
        if flat_id:
            anchors = anchor_paragraphs_for_pair(
                enriched_id,
                flat_id,
                places_df,
                orgs_df,
                paragraph_to_resolution,
            )
            gt_paragraph = anchors[0] if anchors else None
        else:
            gt_paragraph = None
        auto_resolution = paragraph_to_resolution.get(chain_paragraph or "", "")
        hint_resolution = sibling_hint_resolution(enriched_id, enriched_date) if not chain_paragraph else None
        if hint_resolution and reason == "chain_gap":
            reason = "same_day_split"
        session_id = (
            extract_session_id(flat_id)
            or (result or {}).get("session_id")
            or _session_for_enriched_date(enriched_date, alignments or [])
        )
        preview = (
            labeled_row.get("enriched_preview")
            or (result or {}).get("enriched_preview")
            or enriched_text(enriched_record)
        )[:600]
        tasks.append(
            {
                "task_id": str(
                    (result or {}).get("sample_id")
                    or labeled_row.get("sample_id")
                    or enriched_id
                ),
                "enriched_id": enriched_id,
                "enriched_date": enriched_date,
                "flat_id": flat_id or None,
                "session_id": session_id,
                "enriched_preview": preview,
                "flat_preview_auto": (labeled_row.get("flat_preview") or "")[:600],
                "auto_paragraph_id": chain_paragraph,
                "auto_resolution_id": auto_resolution or None,
                "hint_resolution_id": hint_resolution,
                "gt_paragraph_id": gt_paragraph,
                "blocked_paragraph_ids": blocked_by_enriched.get(enriched_id, []),
                "reason": reason,
                "prior_verdict": labeled_row.get("verdict"),
                "in_verification_sample": bool(labeled_row),
                "suggested_search_terms": suggested_search_terms_for_enriched(
                    enriched_id,
                    places_df,
                    orgs_df,
                ),
            }
        )
        seen.add(enriched_id)

    for result in results:
        enriched_id = str(result.get("enriched_id", ""))
        labeled_row = labeled_by_id.get(enriched_id)
        if not labeled_row:
            continue
        flat_id = str(labeled_row.get("flat_id", ""))
        chain_paragraph = chain_by_enriched.get(enriched_id)
        anchors = anchor_paragraphs_for_pair(
            enriched_id,
            flat_id,
            places_df,
            orgs_df,
            paragraph_to_resolution,
        )
        gt_paragraph = anchors[0] if anchors else None
        is_mismatch = bool(chain_paragraph and gt_paragraph and chain_paragraph != gt_paragraph)
        is_rejected = (enriched_id, flat_id) in reject_keys
        if is_mismatch:
            add_task(enriched_id, labeled_row, result, "chain_mismatch")
        elif is_rejected:
            add_task(enriched_id, labeled_row, result, "rejected_no_pin")

    for labeled_row in labeled:
        enriched_id = str(labeled_row.get("enriched_id", ""))
        if not enriched_id or enriched_id in seen or enriched_id in confirmed_enriched:
            continue
        verdict = str(labeled_row.get("verdict", ""))
        if verdict in {"false_positive", "uncertain"}:
            add_task(
                enriched_id,
                labeled_row,
                None,
                "verification_sample",
            )

    if enriched_by_date and alignments is not None:
        review_dates = {
            str(record.get("enriched_date", ""))[:10]
            for record in labeled
            if record.get("enriched_date")
        }
        gap_candidates: list[dict[str, Any]] = []
        for date_str in sorted(review_dates):
            if not date_str:
                continue
            for enriched_record in enriched_by_date.get(date_str, []):
                enriched_id = enriched_volgnr(enriched_record) or ""
                if not enriched_id or enriched_id in chain_by_enriched:
                    continue
                if enriched_id in seen or enriched_id in confirmed_enriched:
                    continue
                labeled_row = labeled_by_id.get(enriched_id)
                enriched_date = date_str
                flat_id = str(labeled_row.get("flat_id", "")) if labeled_row else ""
                hint_resolution = sibling_hint_resolution(enriched_id, enriched_date)
                reason = "same_day_split" if hint_resolution else "chain_gap"
                session_id = (
                    extract_session_id(flat_id)
                    if flat_id
                    else _session_for_enriched_date(enriched_date, alignments or [])
                )
                preview = (
                    (labeled_row or {}).get("enriched_preview")
                    or enriched_text(enriched_record)
                )[:600]
                gap_candidates.append(
                    {
                        "task_id": str(
                            (labeled_row or {}).get("sample_id") or enriched_id
                        ),
                        "enriched_id": enriched_id,
                        "enriched_date": enriched_date,
                        "flat_id": flat_id or None,
                        "session_id": session_id,
                        "enriched_preview": preview,
                        "flat_preview_auto": ((labeled_row or {}).get("flat_preview") or "")[:600],
                        "auto_paragraph_id": None,
                        "auto_resolution_id": None,
                        "hint_resolution_id": hint_resolution,
                        "gt_paragraph_id": None,
                        "blocked_paragraph_ids": blocked_by_enriched.get(enriched_id, []),
                        "reason": reason,
                        "prior_verdict": (labeled_row or {}).get("verdict"),
                        "in_verification_sample": bool(labeled_row),
                        "suggested_search_terms": suggested_search_terms_for_enriched(
                            enriched_id,
                            places_df,
                            orgs_df,
                        ),
                    }
                )

        if include_all_chain_gaps:
            for task in gap_candidates:
                if task["enriched_id"] not in seen:
                    tasks.append(task)
                    seen.add(task["enriched_id"])
        elif chain_gap_sample_per_session > 0:
            by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for task in gap_candidates:
                by_session[str(task.get("session_id") or "unknown")].append(task)
            for session_id in sorted(by_session):
                session_tasks = by_session[session_id]
                session_tasks.sort(
                    key=lambda item: (
                        0 if item.get("reason") == "same_day_split" else 1,
                        item.get("enriched_date") or "",
                        item.get("enriched_id") or "",
                    )
                )
                for task in session_tasks[:chain_gap_sample_per_session]:
                    if task["enriched_id"] in seen:
                        continue
                    tasks.append(task)
                    seen.add(task["enriched_id"])

    priority = {
        "chain_mismatch": 0,
        "rejected_no_pin": 1,
        "verification_sample": 2,
        "same_day_split": 3,
        "chain_gap": 4,
    }
    tasks.sort(
        key=lambda item: (
            priority.get(item["reason"], 9),
            item.get("session_id") or "",
            item.get("enriched_date") or "",
            item.get("enriched_id") or "",
        )
    )
    return tasks


def _session_for_enriched_date(
    enriched_date: str,
    alignments: list[dict[str, Any]],
) -> str | None:
    for alignment in alignments:
        if str(alignment.get("enriched_date", ""))[:10] == enriched_date:
            return str(alignment.get("session_id", "")) or None
    return None


def build_pin_placement_tasks(
    placement_queue: list[dict[str, Any]],
    enriched_by_date: dict[str, list[dict[str, Any]]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Convert coverage-gap queue rows into resolution-search task records."""
    enriched_lookup: dict[str, dict[str, Any]] = {}
    for rows in enriched_by_date.values():
        for enriched in rows:
            enriched_id = enriched_volgnr(enriched) or ""
            if enriched_id:
                enriched_lookup[enriched_id] = enriched

    tasks: list[dict[str, Any]] = []
    for item in placement_queue:
        enriched_id = str(item.get("enriched_id", ""))
        enriched = enriched_lookup.get(enriched_id, {})
        tasks.append(
            {
                "task_id": str(item.get("task_id") or enriched_id),
                "enriched_id": enriched_id,
                "enriched_date": str(item.get("enriched_date") or enriched.get("date", ""))[:10],
                "flat_id": None,
                "session_id": item.get("session_id"),
                "enriched_preview": enriched_text(enriched)[:600] if enriched else "",
                "flat_preview_auto": "",
                "auto_paragraph_id": None,
                "auto_resolution_id": None,
                "hint_resolution_id": item.get("hint_resolution_id"),
                "gt_paragraph_id": None,
                "blocked_paragraph_ids": [],
                "reason": "pin_placement_gap",
                "prior_verdict": None,
                "in_verification_sample": False,
                "overlap_score": item.get("overlap_score"),
                "candidate_count": item.get("candidate_count"),
                "year": item.get("year"),
                "suggested_search_terms": suggested_search_terms_for_enriched(
                    enriched_id,
                    places_df,
                    orgs_df,
                ),
            }
        )
    return tasks


def write_pin_placement_html(
    tasks: list[dict[str, Any]],
    res_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    output_path: Path,
    *,
    places_df: pd.DataFrame | None = None,
    orgs_df: pd.DataFrame | None = None,
) -> None:
    """Pin-placement gap queue — same export path as resolution search."""
    write_resolution_search_html(
        tasks,
        res_df,
        paragraph_to_resolution,
        output_path,
        places_df=places_df,
        orgs_df=orgs_df,
        page_title="Pin Placement Queue",
        page_heading="Systematic pin placement (year × session gaps)",
        page_note=(
            "<p class='note'><b>Goal:</b> place one verified pin per empty year×session cell. "
            "Tasks are ranked by place/org/person overlap — not auto-pinned. "
            "Export uses the same <code>sequence_correction_summary.json</code> path as resolution search.</p>"
        ),
        storage_key="pin_placement_pins_v1",
    )


def write_resolution_search_html(
    tasks: list[dict[str, Any]],
    res_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    output_path: Path,
    year_min: int = 1626,
    year_max: int = 1630,
    places_df: pd.DataFrame | None = None,
    orgs_df: pd.DataFrame | None = None,
    page_title: str = "Resolution Search Annotator",
    page_heading: str = "Resolution search annotator",
    page_note: str | None = None,
    storage_key: str = "resolution_search_pins_v1",
) -> None:
    """Manual search UI: query flat resolutions, pick paragraph, export pins."""
    search_index = build_resolution_search_index(
        res_df,
        year_min,
        year_max,
        paragraph_to_resolution=paragraph_to_resolution,
        places_df=places_df,
        orgs_df=orgs_df,
    )
    paragraph_map = build_resolution_paragraph_map(paragraph_to_resolution, res_df)
    sessions = sorted({task.get("session_id") for task in tasks if task.get("session_id")})

    index_js_path = output_path.with_name("resolution_search_index.js")
    paragraphs_js_path = output_path.with_name("resolution_paragraphs.js")
    index_js_path.write_text(
        "window.RESOLUTION_SEARCH_INDEX = "
        + json.dumps(search_index, ensure_ascii=False)
        + ";",
        encoding="utf-8",
    )
    paragraphs_js_path.write_text(
        "window.RESOLUTION_PARAGRAPHS = "
        + json.dumps(paragraph_map, ensure_ascii=False)
        + ";",
        encoding="utf-8",
    )

    tasks_json = json.dumps(tasks, ensure_ascii=False)
    sessions_json = json.dumps(sessions, ensure_ascii=False)
    title_esc = escape(page_title)
    heading_esc = escape(page_heading)
    default_note = (
        f"<p class='note'><b>What you annotate:</b> pins become <code>curated_pins</code> on re-run — not new rows "
        f"in the 50-item verification sample. Each re-run rebuilds this list: sample mismatches, rejections, and "
        f"<b>unlinked enrichments</b> on review days (including same-day splits). Jump to a task via the dropdown or "
        f"<code>verify_resolution_search.html#1626-02-25_3</code>. Workflow: search → pick resolution → pick paragraph "
        f"→ <b>Pin match</b>. Search uses HTR text <i>plus</i> overlap entity names; empty search lists same-day "
        f"resolutions. Export → move <code>sequence_correction_summary.json</code> to <code>output/</code>, then run:"
        f"{CORRECTION_CLI_BLOCK}</p>"
    )
    note_block = page_note if page_note is not None else default_note

    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>{title_esc}</title>
<script src='resolution_search_index.js'></script>
<script src='resolution_paragraphs.js'></script>
<style>
body {{ font-family: 'Segoe UI', sans-serif; background: #f0f4f8; margin: 0; color: #1a202c; }}
.header {{ background: white; padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
h1 {{ margin: 0 0 6px; color: #1a365d; font-size: 1.35rem; }}
.meta {{ color: #4a5568; font-size: 0.9rem; }}
.toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; align-items: center; }}
.toolbar button {{ padding: 8px 14px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }}
.toolbar .primary {{ background: #2b6cb0; color: white; }}
.toolbar .muted {{ background: #4a5568; color: white; }}
.layout {{ display: grid; grid-template-columns: 1fr 1.1fr; gap: 16px; padding: 16px 24px 32px; max-width: 1500px; }}
.panel {{ background: white; border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
.panel h2 {{ margin: 0 0 10px; font-size: 1rem; color: #2d3748; }}
.preview {{ font-family: Georgia, serif; font-size: 0.94rem; line-height: 1.55; background: #f7fafc; padding: 12px; border-radius: 8px; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }}
.chip {{ font-size: 0.78rem; padding: 4px 10px; border-radius: 999px; background: #e2e8f0; cursor: pointer; }}
.chip:hover {{ background: #bee3f8; }}
.chip.active {{ background: #2b6cb0; color: white; }}
.search-row {{ display: flex; gap: 8px; margin: 10px 0; }}
.search-row input {{ flex: 1; padding: 10px; border: 1px solid #cbd5e0; border-radius: 6px; font-size: 0.95rem; }}
.search-row button {{ padding: 10px 16px; background: #2b6cb0; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }}
.filters {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; font-size: 0.88rem; }}
.filters select, .filters input {{ padding: 6px 8px; border-radius: 6px; border: 1px solid #cbd5e0; }}
.result-meta {{ font-size: 0.85rem; color: #4a5568; margin: 6px 0 8px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
.result-meta button {{ padding: 4px 10px; border: none; border-radius: 4px; background: #4a5568; color: white; cursor: pointer; font-size: 0.82rem; }}
.result {{ border: 2px solid #e2e8f0; border-radius: 8px; padding: 10px; margin-bottom: 8px; cursor: pointer; }}
.result:hover {{ border-color: #90cdf4; }}
.result.selected {{ border-color: #2b6cb0; background: #ebf8ff; }}
.result .hdr {{ display: flex; justify-content: space-between; font-size: 0.8rem; color: #718096; margin-bottom: 6px; }}
.result .text {{ font-family: Georgia, serif; font-size: 0.88rem; line-height: 1.45; }}
.result mark {{ background: #faf089; padding: 0 2px; }}
.paragraph {{ border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px; margin-bottom: 6px; cursor: pointer; }}
.paragraph:hover {{ border-color: #63b3ed; }}
.paragraph.selected {{ border-color: #2b6cb0; background: #ebf8ff; }}
.paragraph .pid {{ font-size: 0.75rem; color: #718096; }}
.badge {{ font-size: 0.72rem; padding: 2px 6px; border-radius: 4px; background: #fed7d7; }}
.badge.mismatch {{ background: #feebc8; }}
.badge.split {{ background: #e9d8fd; }}
.badge.gap {{ background: #e2e8f0; }}
.hint-box {{ margin: 10px 0; padding: 10px; background: #faf5ff; border-radius: 6px; font-size: 0.88rem; }}
.actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
.actions button {{ flex: 1; min-width: 120px; padding: 10px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; }}
.btn-pin {{ background: #38a169; color: white; }}
.btn-reject {{ background: #e53e3e; color: white; }}
.btn-skip {{ background: #a0aec0; color: white; }}
.note {{ margin: 0 24px 16px; padding: 12px 16px; background: #ebf8ff; border-left: 4px solid #3182ce; font-size: 0.9rem; }}
.pagination {{ display: flex; justify-content: center; gap: 16px; padding: 12px; }}
.pagination button {{ padding: 10px 20px; background: #4a5568; color: white; border: none; border-radius: 6px; cursor: pointer; }}
#results {{ max-height: 620px; overflow-y: auto; }}
</style></head><body>
<div class='header'>
  <h1>{heading_esc}</h1>
  <p class='meta'>Search flat resolutions by your own terms, then pinpoint the matching paragraph. Rejected auto-links stay blocked after <code>session_chain_alignment.py</code>.</p>
  <div class='toolbar'>
    <span id='progress' class='meta'>0 / 0</span>
    <label class='meta'>Task <select id='taskJump' onchange='jumpToTask(this.value)'></select></label>
    <label class='meta'>Show <select id='reasonFilter' onchange='applyReasonFilter()'><option value="">all reasons</option><option value="pin_placement_gap">pin gap</option><option value="same_day_split">same-day split</option><option value="chain_gap">chain gap</option><option value="chain_mismatch">mismatch</option><option value="rejected_no_pin">rejected</option></select></label>
    <button class='primary' onclick='exportPins()'>Export pins</button>
    <button class='muted' onclick='clearStorage()'>Clear saved</button>
  </div>
</div>
{note_block}
<div id='task'></div>
<div class='pagination'>
  <button id='prevBtn' onclick='changePage(-1)'>← Previous</button>
  <span id='pageInfo' class='meta'>Task 1</span>
  <button id='nextBtn' onclick='changePage(1)'>Next →</button>
</div>
<script>
const TASKS = {tasks_json};
const ALL_TASKS = TASKS;
let TASKS_FILTERED = [...ALL_TASKS];
const SESSIONS = {sessions_json};
const STORAGE_KEY = '{storage_key}';
let page = 0;
let pins = {{}};
let selectedResolution = null;
let selectedParagraph = null;
let lastScored = [];
let resultsShown = 40;
let currentAnchorDate = '';

function loadStorage() {{
  try {{ pins = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch(e) {{ pins = {{}}; }}
}}
function saveStorage() {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(pins)); }}

function applyReasonFilter() {{
  const reason = document.getElementById('reasonFilter')?.value || '';
  TASKS_FILTERED = reason ? ALL_TASKS.filter(t => t.reason === reason) : [...ALL_TASKS];
  page = 0;
  populateTaskJump();
  render();
}}

function populateTaskJump() {{
  const select = document.getElementById('taskJump');
  if (!select) return;
  select.innerHTML = TASKS_FILTERED.map((t, i) =>
    `<option value="${{i}}">${{esc(t.enriched_id)}} (${{t.reason}})</option>`
  ).join('');
  if (TASKS_FILTERED[page]) select.value = String(page);
}}

function jumpToTask(index) {{
  page = Math.max(0, Math.min(TASKS_FILTERED.length - 1, Number(index) || 0));
  selectedResolution = null;
  selectedParagraph = null;
  render();
}}

function applyHashTask() {{
  const enrichedId = decodeURIComponent((location.hash || '').slice(1));
  if (!enrichedId) return;
  const idx = ALL_TASKS.findIndex(t => t.enriched_id === enrichedId);
  if (idx < 0) return;
  const reason = document.getElementById('reasonFilter')?.value || '';
  TASKS_FILTERED = reason ? ALL_TASKS.filter(t => t.reason === reason) : [...ALL_TASKS];
  const filteredIdx = TASKS_FILTERED.findIndex(t => t.enriched_id === enrichedId);
  if (filteredIdx >= 0) page = filteredIdx;
}}

function esc(s) {{
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function highlight(text, terms) {{
  let out = esc(text);
  for (const term of terms) {{
    if (!term || term.length < 2) continue;
    const re = new RegExp('(' + term.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
    out = out.replace(re, '<mark>$1</mark>');
  }}
  return out;
}}

function activeTerms() {{
  const input = document.getElementById('searchInput');
  const typed = (input?.value || '').trim();
  if (!typed) return [];
  return [...new Set(typed.split(/\\s+/).filter(Boolean).map(t => t.toLowerCase()))];
}}

function normalizeSearchText(value) {{
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\\u0300-\\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}}

function termMatches(hay, term) {{
  if (!term) return false;
  if (hay.includes(term)) return true;
  const normHay = normalizeSearchText(hay);
  const normTerm = normalizeSearchText(term);
  if (!normTerm) return false;
  if (normHay.includes(normTerm)) return true;
  if (normTerm.length < 5) return false;
  const words = normHay.split(/\\s+/).filter(Boolean);
  for (const word of words) {{
    if (word === normTerm) return true;
    if (Math.abs(word.length - normTerm.length) > 2) continue;
    let edits = 0;
    const limit = word.length > 6 ? 2 : 1;
    const maxLen = Math.max(word.length, normTerm.length);
    for (let i = 0, j = 0; i < word.length && j < normTerm.length;) {{
      if (word[i] === normTerm[j]) {{ i++; j++; continue; }}
      edits++;
      if (edits > limit) break;
      if (word.length > normTerm.length) i++;
      else if (normTerm.length > word.length) j++;
      else {{ i++; j++; }}
    }}
    if (edits <= limit) return true;
  }}
  return false;
}}

function rowHaystack(row) {{
  return (row.text + ' ' + row.id + ' ' + (row.entities || '')).toLowerCase();
}}

function dateDistance(rowDate, anchorDate) {{
  if (!anchorDate || !rowDate) return 999999;
  const a = Date.parse(anchorDate);
  const b = Date.parse(rowDate);
  if (Number.isNaN(a) || Number.isNaN(b)) return 999999;
  return Math.abs(b - a);
}}

function compareScored(a, b, sortMode, anchorDate) {{
  if (sortMode === 'date-asc') return a.row.date.localeCompare(b.row.date);
  if (sortMode === 'date-desc') return b.row.date.localeCompare(a.row.date);
  if (b.hits !== a.hits) return b.hits - a.hits;
  const dist = dateDistance(a.row.date, anchorDate) - dateDistance(b.row.date, anchorDate);
  if (dist !== 0) return dist;
  return a.row.date.localeCompare(b.row.date);
}}

function runSearch() {{
  resultsShown = 40;
  const terms = activeTerms();
  const sessionFilter = document.getElementById('sessionFilter')?.value || '';
  const yearFilter = document.getElementById('yearFilter')?.value || '';
  const sortMode = document.getElementById('sortMode')?.value || 'relevance';
  const anchorDate = currentAnchorDate;
  const scored = [];
  for (const row of (window.RESOLUTION_SEARCH_INDEX || [])) {{
    if (sessionFilter && row.session_id !== sessionFilter) continue;
    if (yearFilter && !String(row.date).startsWith(yearFilter)) continue;
    const hay = rowHaystack(row);
    let hits = 0;
    for (const term of terms) {{
      if (termMatches(hay, term)) hits += 1;
    }}
    if (!terms.length) {{
      if (selectedResolution) {{
        const hinted = (window.RESOLUTION_SEARCH_INDEX || []).find(r => r.id === selectedResolution);
        if (hinted) {{
          lastScored = [{{row: hinted, hits: 0}}];
          renderResults();
          return;
        }}
      }}
      if (anchorDate && row.date === anchorDate) {{
        scored.push({{row, hits: 0}});
        continue;
      }}
      if (sessionFilter || yearFilter) scored.push({{row, hits: 0}});
      continue;
    }}
    if (hits > 0) scored.push({{row, hits}});
  }}
  scored.sort((a, b) => compareScored(a, b, sortMode, anchorDate));
  lastScored = scored;
  renderResults();
}}

function loadMoreResults() {{
  resultsShown += 40;
  renderResults();
}}

function renderResults() {{
  const root = document.getElementById('results');
  const meta = document.getElementById('resultMeta');
  if (!root) return;
  const terms = activeTerms();
  const total = lastScored.length;
  const visible = lastScored.slice(0, resultsShown);
  if (!visible.length) {{
    if (meta) meta.innerHTML = '';
    root.innerHTML = '<p class="meta">No results. Try entity names from the hint chips, fewer terms, another year, or clear search to browse same-day resolutions.</p>';
    return;
  }}
  if (meta) {{
    const more = total > resultsShown
      ? `<button type="button" onclick="loadMoreResults()">Show more</button>`
      : '';
    meta.innerHTML = `<span>${{total}} match${{total === 1 ? '' : 'es'}} — showing 1–${{Math.min(resultsShown, total)}}</span>${{more}}`;
  }}
  root.innerHTML = visible.map(item => {{
    const row = item.row;
    return `
    <div class="result ${{selectedResolution === row.id ? 'selected' : ''}}" onclick="selectResolution('${{esc(row.id)}}')">
      <div class="hdr"><span>${{esc(row.date)}} · ${{esc(row.session_id)}}</span><span>${{esc(row.id)}}</span></div>
      <div class="text">${{highlight(row.text, terms)}}</div>
    </div>`;
  }}).join('');
  renderParagraphs();
}}

function selectResolution(resolutionId) {{
  selectedResolution = resolutionId;
  selectedParagraph = null;
  renderResults();
}}

function renderParagraphs() {{
  const root = document.getElementById('paragraphs');
  if (!root) return;
  if (!selectedResolution) {{
    root.innerHTML = '<p class="meta">Select a resolution to see paragraphs.</p>';
    return;
  }}
  const items = (window.RESOLUTION_PARAGRAPHS || {{}})[selectedResolution] || [];
  if (!items.length) {{
    root.innerHTML = '<p class="meta">No paragraph mapping for this resolution.</p>';
    return;
  }}
  root.innerHTML = items.map(item => `
    <div class="paragraph ${{selectedParagraph === item.paragraph_id ? 'selected' : ''}}"
         onclick="selectParagraph('${{esc(item.paragraph_id)}}')">
      <div class="pid">${{esc(item.paragraph_id)}}</div>
      <div>${{esc(item.preview)}}</div>
    </div>`).join('');
}}

function selectParagraph(paragraphId) {{
  selectedParagraph = paragraphId;
  renderParagraphs();
}}

function render() {{
  if (!TASKS_FILTERED.length) {{
    document.getElementById('task').innerHTML = '<p class="meta" style="padding:24px">No search tasks match filter.</p>';
    return;
  }}
  const task = TASKS_FILTERED[page];
  const saved = pins[task.task_id];
  currentAnchorDate = task.enriched_date || '';
  const taskYear = (task.enriched_date || '').slice(0, 4);
  const indexYears = [...new Set((window.RESOLUTION_SEARCH_INDEX || []).map(r => String(r.date).slice(0, 4)))].sort();
  selectedResolution = saved?.corrected_resolution_id || selectedResolution;
  if (!saved?.corrected_resolution_id && task.hint_resolution_id) {{
    selectedResolution = task.hint_resolution_id;
  }}
  selectedParagraph = saved?.corrected_paragraph_id || selectedParagraph;
  const savedQuery = (saved?.search_terms || []).join(' ');
  const suggestedTerms = task.suggested_search_terms || [];
  const defaultQuery = savedQuery || suggestedTerms.join(' ');

  const reasonBadge = {{
    chain_mismatch: '<span class="badge mismatch">chain ≠ GT</span>',
    rejected_no_pin: '<span class="badge">rejected</span>',
    same_day_split: '<span class="badge split">same-day split</span>',
    chain_gap: '<span class="badge gap">no chain link</span>',
    pin_placement_gap: '<span class="badge split">pin gap</span>',
  }}[task.reason] || '';

  document.getElementById('task').innerHTML = `
    <div style="padding:0 24px 8px" class="meta">${{esc(task.session_id)}} · ${{esc(task.enriched_id)}} · ${{esc(task.enriched_date)}} ${{reasonBadge}} ${{task.in_verification_sample ? '' : '· not in 50-sample'}}</div>
    <div class="layout">
      <div class="panel">
        <h2>Enriched resolution (search from this)</h2>
        <div class="preview">${{esc(task.enriched_preview)}}</div>
        ${{suggestedTerms.length ? `<div class="chips">${{suggestedTerms.map(t => `<span class="chip">${{esc(t)}}</span>`).join('')}}</div><p class="meta">Overlap entity hints (searchable even when HTR is garbled).</p>` : ''}}
        ${{task.hint_resolution_id ? `<div class="hint-box"><b>Neighbor hint:</b> another resolution on this day links to <code>${{esc(task.hint_resolution_id)}}</code>. Select it on the right, then pick the matching <b>paragraph</b> (often the next para in the same flat resolution).</div>` : ''}}
        <h2 style="margin-top:14px">Blocked auto-link</h2>
        <p class="meta">${{esc(task.auto_paragraph_id)}} → ${{esc(task.auto_resolution_id)}}</p>
        <div class="preview">${{esc(task.flat_preview_auto)}}</div>
        ${{task.gt_paragraph_id ? `<p class="meta">GT paragraph (diagnostic): ${{esc(task.gt_paragraph_id)}}</p>` : ''}}
      </div>
      <div class="panel">
        <h2>Search flat resolutions (${{window.RESOLUTION_SEARCH_INDEX?.length || 0}} in index)</h2>
        <div class="filters">
          <label>Session <select id="sessionFilter" onchange="runSearch()"><option value="">all</option>${{SESSIONS.map(s => `<option value="${{esc(s)}}" ${{s===task.session_id?'selected':''}}>${{esc(s)}}</option>`).join('')}}</select></label>
          <label>Year <select id="yearFilter" onchange="runSearch()"><option value="">all years</option>${{indexYears.map(y => `<option value="${{esc(y)}}" ${{y===taskYear?'selected':''}}>${{esc(y)}}</option>`).join('')}}</select></label>
          <label>Sort <select id="sortMode" onchange="runSearch()"><option value="relevance">relevance (near task date)</option><option value="date-asc">date ↑</option><option value="date-desc">date ↓</option></select></label>
        </div>
        <div class="search-row">
          <input id="searchInput" placeholder="Search terms…" onkeydown="if(event.key==='Enter')runSearch()">
          <button onclick="runSearch()">Search</button>
        </div>
        <div id="resultMeta" class="result-meta"></div>
        <div id="results"></div>
        <h2 style="margin-top:14px">Pinpoint paragraph</h2>
        <div id="paragraphs"></div>
        <div class="actions">
          <button class="btn-pin" onclick="savePin('confirmed')">Pin match</button>
          <button class="btn-reject" onclick="savePin('rejected')">Keep blocked (no match)</button>
          <button class="btn-skip" onclick="savePin('uncertain')">Uncertain</button>
        </div>
      </div>
    </div>`;

  const searchInput = document.getElementById('searchInput');
  if (searchInput) searchInput.value = defaultQuery;
  runSearch();
  populateTaskJump();
  document.getElementById('progress').textContent = `${{Object.keys(pins).length}} saved · task ${{page + 1}} / ${{TASKS_FILTERED.length}} (${{ALL_TASKS.length}} total)`;
  document.getElementById('pageInfo').textContent = `Task ${{page + 1}} / ${{TASKS_FILTERED.length}}`;
  document.getElementById('prevBtn').disabled = page <= 0;
  document.getElementById('nextBtn').disabled = page >= TASKS_FILTERED.length - 1;
}}

function savePin(action) {{
  const task = TASKS_FILTERED[page];
  pins[task.task_id] = {{
    correction_id: task.task_id,
    enriched_id: task.enriched_id,
    session_id: task.session_id,
    action: action,
    corrected_paragraph_id: action === 'confirmed' ? selectedParagraph : null,
    corrected_resolution_id: action === 'confirmed' ? selectedResolution : null,
    auto_paragraph_id: task.auto_paragraph_id,
    auto_flat_id: task.flat_id,
    prior_verdict: task.prior_verdict,
    search_terms: activeTerms(),
    timestamp: new Date().toISOString(),
  }};
  saveStorage();
  if (page < TASKS_FILTERED.length - 1 && action !== 'uncertain') page += 1;
  selectedResolution = null;
  selectedParagraph = null;
  render();
}}

function exportPins() {{
  const payload = {{
    total: ALL_TASKS.length,
    corrected: Object.values(pins).filter(p => p.action === 'confirmed').length,
    rejected: Object.values(pins).filter(p => p.action === 'rejected').length,
    uncertain: Object.values(pins).filter(p => p.action === 'uncertain').length,
    corrections: pins,
  }};
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{type:'application/json'}}));
  a.download = 'sequence_correction_summary.json';
  a.click();
}}

function clearStorage() {{
  if (confirm('Clear saved pins?')) {{ pins = {{}}; localStorage.removeItem(STORAGE_KEY); render(); }}
}}

function changePage(delta) {{
  page = Math.max(0, Math.min(TASKS_FILTERED.length - 1, page + delta));
  selectedResolution = null;
  selectedParagraph = null;
  render();
}}

loadStorage();
applyHashTask();
populateTaskJump();
render();
</script></body></html>"""
    output_path.write_text(html, encoding="utf-8")


def build_day_sequence_payload(
    enriched_by_date: dict[str, list[dict[str, Any]]],
    res_df: pd.DataFrame,
    alignments: list[dict[str, Any]],
    labeled: list[dict[str, Any]],
    rejected_pairs: list[dict[str, str]],
    curated_pins: list[dict[str, str]],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    focus_dates: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Side-by-side day views where chain or verification links are known."""
    alignment_by_enriched = {str(item["enriched_id"]): item for item in alignments}
    labeled_by_enriched = {str(item.get("enriched_id", "")): item for item in labeled}
    reject_keys = {(item["enriched_id"], item["flat_id"]) for item in rejected_pairs}
    pin_sources = {
        str(item.get("enriched_id", "")): str(item.get("source", ""))
        for item in curated_pins
    }

    if focus_dates is None:
        focus_dates = sorted(
            {
                str(item.get("enriched_date", ""))[:10]
                for item in labeled
                if item.get("enriched_date")
            }
            | {
                str(item.get("enriched_date", ""))[:10]
                for item in alignments
                if item.get("enriched_date")
                and str(item.get("enriched_id", "")) in labeled_by_enriched
            }
        )
    else:
        focus_dates = sorted(focus_dates)

    flat_by_date: dict[str, pd.DataFrame] = {}
    for date_str in focus_dates:
        day_flat = res_df[res_df["date"].astype(str).str[:10] == date_str].copy()
        if day_flat.empty:
            continue
        day_flat["sort_key"] = day_flat["id"].astype(str).map(
            lambda rid: parse_resolution_position(rid) or (0, 0, 0)
        )
        flat_by_date[date_str] = day_flat.sort_values("sort_key")

    days: list[dict[str, Any]] = []
    for date_str in focus_dates:
        enriched_rows = enriched_by_date.get(date_str, [])
        flat_frame = flat_by_date.get(date_str)
        if not enriched_rows and (flat_frame is None or flat_frame.empty):
            continue

        link_counter = 0
        resolution_to_links: dict[str, list[str]] = defaultdict(list)
        enriched_items: list[dict[str, Any]] = []

        for enriched in enriched_rows:
            enriched_id = enriched_volgnr(enriched) or ""
            alignment = alignment_by_enriched.get(enriched_id)
            labeled_row = labeled_by_enriched.get(enriched_id, {})
            flat_id = str(labeled_row.get("flat_id", ""))
            link_resolution = str(alignment.get("resolution_id", "")) if alignment else ""
            link_paragraph = str(alignment.get("paragraph_id", "")) if alignment else ""
            link_id = None
            link_status = "gap"

            if alignment:
                link_counter += 1
                link_id = f"L{link_counter}"
                if alignment.get("pinned") or pin_sources.get(enriched_id) == "manual_correction":
                    link_status = "pinned"
                else:
                    link_status = "chain"
                if flat_id and link_resolution and link_resolution != flat_id:
                    link_status = "mismatch"
                if (enriched_id, flat_id) in reject_keys:
                    link_status = "rejected"
                resolution_to_links[link_resolution].append(link_id)

            gt_paragraph = None
            if flat_id:
                anchors = anchor_paragraphs_for_pair(
                    enriched_id,
                    flat_id,
                    places_df,
                    orgs_df,
                    paragraph_to_resolution,
                )
                gt_paragraph = anchors[0] if anchors else None

            enriched_items.append(
                {
                    "enriched_id": enriched_id,
                    "resolution_index": enriched.get("resolution_index"),
                    "preview": enriched_text(enriched)[:360],
                    "link_id": link_id,
                    "link_status": link_status,
                    "link_resolution_id": link_resolution or None,
                    "link_paragraph_id": link_paragraph or None,
                    "verdict": labeled_row.get("verdict"),
                    "gt_resolution_id": flat_id or None,
                    "gt_paragraph_id": gt_paragraph,
                    "in_sample": bool(labeled_row),
                }
            )

        flat_items: list[dict[str, Any]] = []
        if flat_frame is not None:
            for _, row in flat_frame.iterrows():
                resolution_id = str(row["id"])
                flat_items.append(
                    {
                        "resolution_id": resolution_id,
                        "session_id": extract_session_id(resolution_id),
                        "preview": candidate_text(row)[:360],
                        "link_ids": resolution_to_links.get(resolution_id, []),
                        "is_gt": resolution_id
                        in {
                            str(item.get("gt_resolution_id"))
                            for item in enriched_items
                            if item.get("gt_resolution_id")
                        },
                        "is_chain": resolution_id
                        in {
                            str(item.get("link_resolution_id"))
                            for item in enriched_items
                            if item.get("link_resolution_id")
                        },
                    }
                )

        aligned_count = sum(1 for item in enriched_items if item.get("link_id"))
        sample_count = sum(1 for item in enriched_items if item.get("in_sample"))
        if aligned_count == 0 and sample_count == 0:
            continue

        sessions = sorted(
            {
                extract_session_id(str(item.get("resolution_id", "")))
                for item in flat_items
                if item.get("session_id")
            }
            | {
                extract_session_id(str(item.get("gt_resolution_id", "")))
                for item in enriched_items
                if item.get("gt_resolution_id")
            }
        )

        days.append(
            {
                "date": date_str,
                "sessions": sessions,
                "enriched_count": len(enriched_items),
                "flat_count": len(flat_items),
                "aligned_count": aligned_count,
                "sample_count": sample_count,
                "enriched_items": enriched_items,
                "flat_items": flat_items,
            }
        )

    days.sort(key=lambda item: item["date"])
    return days


def write_day_sequence_html(
    days: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Interactive side-by-side enriched vs flat resolution sequences per day."""
    data_js_path = output_path.with_name("day_sequence_data.js")
    data_js_path.write_text(
        "window.DAY_SEQUENCES = " + json.dumps(days, ensure_ascii=False) + ";",
        encoding="utf-8",
    )

    html = """<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>Day Sequence Alignment</title>
<script src='day_sequence_data.js'></script>
<style>
body { font-family: 'Segoe UI', sans-serif; background: #edf2f7; margin: 0; color: #1a202c; }
.header { background: white; padding: 18px 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
h1 { margin: 0 0 6px; color: #1a365d; font-size: 1.35rem; }
.meta { color: #4a5568; font-size: 0.9rem; }
.toolbar { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; align-items: center; }
.toolbar select { padding: 8px 10px; border-radius: 6px; border: 1px solid #cbd5e0; min-width: 220px; }
.toolbar label { font-size: 0.88rem; }
.legend { display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 24px 0; font-size: 0.82rem; }
.legend span { padding: 3px 8px; border-radius: 4px; }
.legend .pinned { background: #c6f6d5; }
.legend .chain { background: #bee3f8; }
.legend .mismatch { background: #feebc8; }
.legend .rejected { background: #fed7d7; }
.legend .gap { background: #e2e8f0; }
.day-meta { margin: 12px 24px 0; font-size: 0.9rem; color: #4a5568; }
.sequence-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px 24px 32px; max-width: 1500px; }
.col { background: white; border-radius: 10px; padding: 14px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
.col h2 { margin: 0 0 12px; font-size: 1rem; color: #2d3748; }
.stack { display: flex; flex-direction: column; gap: 8px; max-height: 72vh; overflow-y: auto; }
.card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; position: relative; }
.card .hdr { display: flex; justify-content: space-between; gap: 8px; font-size: 0.78rem; color: #718096; margin-bottom: 6px; }
.card .text { font-family: Georgia, serif; font-size: 0.9rem; line-height: 1.45; }
.card.pinned { border-left: 4px solid #38a169; background: #f0fff4; }
.card.chain { border-left: 4px solid #3182ce; background: #ebf8ff; }
.card.mismatch { border-left: 4px solid #dd6b20; background: #fffaf0; }
.card.rejected { border-left: 4px solid #e53e3e; background: #fff5f5; }
.card.gap { border-left: 4px solid #cbd5e0; }
.card.sample { box-shadow: inset 0 0 0 1px #805ad5; }
.card.highlight { outline: 2px solid #2b6cb0; }
.card.gt-target { box-shadow: inset 0 0 0 1px #38a169; }
.link-badge { display: inline-block; min-width: 1.6rem; text-align: center; font-size: 0.72rem; font-weight: 700; padding: 2px 6px; border-radius: 999px; background: #2d3748; color: white; margin-right: 6px; }
.badge { font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; background: #edf2f7; }
.badge.correct { background: #c6f6d5; }
.badge.fp { background: #fed7d7; }
.note { margin: 0 24px 12px; padding: 12px 16px; background: #ebf8ff; border-left: 4px solid #3182ce; font-size: 0.9rem; }
</style></head><body>
<div class='header'>
  <h1>Day Sequence Alignment</h1>
  <p class='meta'>Enriched and flat resolution sequences for the same sitting day. Matching link badges connect known alignments; hover to highlight both sides.</p>
  <div class='toolbar'>
    <label>Date <select id='dateSelect'></select></label>
    <label><input type='checkbox' id='sampleOnly'> verification sample days only</label>
    <label><input type='checkbox' id='linkedOnly'> hide unlinked enriched</label>
  </div>
</div>
<div class='legend'>
  <span class='pinned'>pinned</span>
  <span class='chain'>chain</span>
  <span class='mismatch'>chain ≠ GT</span>
  <span class='rejected'>rejected</span>
  <span class='gap'>no link</span>
</div>
<p class='note'>Read down each column as the day's resolution order. Grey <b>no link</b> enriched cards → use <a href="verify_resolution_search.html">Resolution Search</a> (or the per-card link). Pins are not added to the 50-sample automatically; re-run <code>session_chain_alignment.py</code> after import.</p>
<p id='dayMeta' class='day-meta'></p>
<div class='sequence-grid'>
  <div class='col'><h2>Enriched resolutions</h2><div id='enrichedCol' class='stack'></div></div>
  <div class='col'><h2>Flat HTR resolutions</h2><div id='flatCol' class='stack'></div></div>
</div>
<script>
const ALL_DAYS = window.DAY_SEQUENCES || [];
let DAYS = [...ALL_DAYS];
let activeLink = null;

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function applyFilters() {
  const sampleOnly = document.getElementById('sampleOnly').checked;
  DAYS = sampleOnly ? ALL_DAYS.filter(d => d.sample_count > 0) : [...ALL_DAYS];
  populateDateSelect();
  renderDay();
}

function populateDateSelect() {
  const select = document.getElementById('dateSelect');
  const current = select.value;
  select.innerHTML = DAYS.map(d =>
    `<option value="${esc(d.date)}">${esc(d.date)} (${d.aligned_count}/${d.enriched_count} linked, ${d.flat_count} flat)</option>`
  ).join('');
  if (current && DAYS.some(d => d.date === current)) select.value = current;
}

function verdictBadge(verdict) {
  if (verdict === 'correct') return '<span class="badge correct">verified correct</span>';
  if (verdict === 'false_positive') return '<span class="badge fp">verified FP</span>';
  return '';
}

function renderCard(className, linkIds, header, body, onEnter, onLeave) {
  const div = document.createElement('div');
  div.className = `card ${className}`;
  if (linkIds && linkIds.length) {
    linkIds.forEach(id => div.dataset.link = id);
  }
  div.innerHTML = `<div class="hdr">${header}</div><div class="text">${body}</div>`;
  div.addEventListener('mouseenter', onEnter);
  div.addEventListener('mouseleave', onLeave);
  return div;
}

function setHighlight(linkId) {
  activeLink = linkId;
  document.querySelectorAll('.card').forEach(card => {
    card.classList.toggle('highlight', linkId && card.dataset.link === linkId);
  });
}

function renderDay() {
  const select = document.getElementById('dateSelect');
  const day = DAYS.find(d => d.date === select.value) || DAYS[0];
  if (!day) {
    document.getElementById('dayMeta').textContent = 'No day data.';
    return;
  }
  if (select.value !== day.date) select.value = day.date;

  const linkedOnly = document.getElementById('linkedOnly').checked;
  document.getElementById('dayMeta').textContent =
    `${day.date} · sessions ${day.sessions.join(', ')} · ${day.enriched_count} enriched · ${day.flat_count} flat · ${day.aligned_count} chain links · ${day.sample_count} in verification sample`;

  const enrichedRoot = document.getElementById('enrichedCol');
  const flatRoot = document.getElementById('flatCol');
  enrichedRoot.innerHTML = '';
  flatRoot.innerHTML = '';

  for (const item of day.enriched_items) {
    if (linkedOnly && !item.link_id) continue;
    const classes = [item.link_status || 'gap'];
    if (item.in_sample) classes.push('sample');
    const header = `<span>${item.link_id ? `<span class="link-badge">${esc(item.link_id)}</span>` : ''}${esc(item.enriched_id)} #${item.resolution_index ?? '?'}</span><span>${verdictBadge(item.verdict)}</span>`;
    const gt = item.gt_resolution_id ? `<div class="meta">GT flat: ${esc(item.gt_resolution_id)}</div>` : '';
    const pinLink = (item.link_status === 'gap')
      ? `<div class="meta"><a href="verify_resolution_search.html#${encodeURIComponent(item.enriched_id)}">Search &amp; pin →</a></div>`
      : '';
    const card = renderCard(
      classes.join(' '),
      item.link_id ? [item.link_id] : [],
      header,
      esc(item.preview) + gt + pinLink,
      () => setHighlight(item.link_id || null),
      () => setHighlight(null),
    );
    enrichedRoot.appendChild(card);
  }

  for (const item of day.flat_items) {
    const classes = [];
    if (item.is_gt) classes.push('gt-target');
    if (item.is_chain && !item.is_gt) classes.push('chain');
    const badges = (item.link_ids || []).map(id => `<span class="link-badge">${esc(id)}</span>`).join('');
    const header = `<span>${badges}${esc(item.resolution_id)}</span><span>${esc(item.session_id || '')}</span>`;
    const card = renderCard(
      classes.join(' '),
      item.link_ids || [],
      header,
      esc(item.preview),
      () => setHighlight((item.link_ids || [])[0] || null),
      () => setHighlight(null),
    );
    flatRoot.appendChild(card);
  }
}

document.getElementById('dateSelect').addEventListener('change', renderDay);
document.getElementById('sampleOnly').addEventListener('change', applyFilters);
document.getElementById('linkedOnly').addEventListener('change', renderDay);

applyFilters();
</script></body></html>"""
    output_path.write_text(html, encoding="utf-8")


def build_alignment_audit_records(
    alignments: list[dict[str, Any]],
    labeled: list[dict[str, Any]],
    curated_pins: list[dict[str, str]],
    rejected_pairs: list[dict[str, str]],
    enriched_by_date: dict[str, list[dict[str, Any]]],
    res_df: pd.DataFrame,
    paragraph_to_resolution: dict[str, str],
    places_df: pd.DataFrame,
    orgs_df: pd.DataFrame,
    session_ranks: list[Any] | None = None,
    per_session_sample: int = 25,
    place_lookup: dict[tuple[str, str], set[str]] | None = None,
    org_lookup: dict[tuple[str, str], set[str]] | None = None,
    person_lookup: dict[tuple[str, str], set[str]] | None = None,
    idf_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a risk-prioritized audit queue over chain alignments (not training labels)."""
    precision_by_session: dict[str, float] = {}
    if session_ranks:
        for rank in session_ranks:
            session_id = getattr(rank, "session_id", None) or rank.get("session_id", "")
            precision = getattr(rank, "precision", None)
            if precision is None:
                precision = rank.get("precision", 0.0)
            precision_by_session[str(session_id)] = float(precision)

    enriched_lookup: dict[str, dict[str, Any]] = {}
    for rows in enriched_by_date.values():
        for enriched in rows:
            enriched_id = enriched_volgnr(enriched) or ""
            if enriched_id:
                enriched_lookup[enriched_id] = enriched

    labeled_by_enriched = {
        str(item.get("enriched_id", "")): item for item in labeled if item.get("enriched_id")
    }
    pin_enriched = {str(item.get("enriched_id", "")) for item in curated_pins}
    reject_keys = {
        (str(item.get("enriched_id", "")), str(item.get("flat_id", "")))
        for item in rejected_pairs
    }

    text_by_resolution = {
        str(row["id"]): candidate_text(row)[:500] for _, row in res_df.iterrows()
    }
    text_by_paragraph = {
        paragraph_id: text_by_resolution.get(resolution_id, "")[:500]
        for paragraph_id, resolution_id in paragraph_to_resolution.items()
    }

    gt_paragraph_by_enriched: dict[str, str | None] = {}
    for enriched_id, labeled_row in labeled_by_enriched.items():
        gt_flat_id = str(labeled_row.get("flat_id", ""))
        if not gt_flat_id:
            continue
        anchors = anchor_paragraphs_for_pair(
            enriched_id,
            gt_flat_id,
            places_df,
            orgs_df,
            paragraph_to_resolution,
        )
        gt_paragraph_by_enriched[enriched_id] = anchors[0] if anchors else None

    def flat_preview(paragraph_id: str, resolution_id: str) -> str:
        text = text_by_paragraph.get(paragraph_id, "")
        if not text and resolution_id:
            text = text_by_resolution.get(resolution_id, "")
        return text[:500]

    propagated_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records: list[dict[str, Any]] = []

    for alignment in alignments:
        enriched_id = str(alignment.get("enriched_id", ""))
        paragraph_id = str(alignment.get("paragraph_id", ""))
        resolution_id = str(alignment.get("resolution_id", ""))
        session_id = str(alignment.get("session_id", ""))
        enriched_date = str(alignment.get("enriched_date", ""))[:10]
        pinned = bool(alignment.get("pinned"))
        propagated = bool(alignment.get("propagated_hint"))

        labeled_row = labeled_by_enriched.get(enriched_id, {})
        gt_flat_id = str(labeled_row.get("flat_id", ""))
        prior_verdict = str(labeled_row.get("verdict", "")) if labeled_row else ""
        gt_paragraph = gt_paragraph_by_enriched.get(enriched_id) if gt_flat_id else None

        matches_labeled_gt = None
        if gt_paragraph and paragraph_id:
            matches_labeled_gt = paragraph_id == gt_paragraph

        enriched = enriched_lookup.get(enriched_id, {})
        overlap_scores: dict[str, float] = {}
        if place_lookup is not None and org_lookup is not None and idf_weights is not None:
            anchor_score, person_score, combined_score = score_typed_overlap(
                enriched_id,
                paragraph_id,
                place_lookup,
                org_lookup,
                person_lookup or {},
                idf_weights,
            )
            overlap_scores = {
                "place_overlap_score": round(
                    sum(idf_weights.get(e, 1.0) for e in place_lookup.get((enriched_id, paragraph_id), set())),
                    3,
                ),
                "org_overlap_score": round(
                    sum(idf_weights.get(e, 1.0) for e in org_lookup.get((enriched_id, paragraph_id), set())),
                    3,
                ),
                "person_overlap_score": round(person_score, 3),
                "anchor_overlap_score": round(anchor_score, 3),
                "combined_overlap_score": round(combined_score, 3),
            }
        record = {
            "audit_id": enriched_id,
            "enriched_id": enriched_id,
            "enriched_date": enriched_date,
            "session_id": session_id,
            "paragraph_id": paragraph_id,
            "resolution_id": resolution_id,
            "enriched_preview": enriched_text(enriched)[:500] if enriched else "",
            "flat_preview": flat_preview(paragraph_id, resolution_id),
            "link_kind": "pinned" if pinned else ("propagated" if propagated else "chain"),
            "prior_verdict": prior_verdict or None,
            "gt_flat_id": gt_flat_id or None,
            "gt_paragraph_id": gt_paragraph,
            "gt_flat_preview": (
                flat_preview(gt_paragraph, gt_flat_id) if gt_paragraph and gt_flat_id else None
            ),
            "matches_labeled_gt": matches_labeled_gt,
            "session_precision": precision_by_session.get(session_id),
            "rejected_pair": bool(gt_flat_id and (enriched_id, gt_flat_id) in reject_keys),
            "manually_pinned": enriched_id in pin_enriched or pinned,
            **overlap_scores,
        }

        if pinned or enriched_id in pin_enriched:
            record["audit_bucket"] = "verified"
            record["in_queue"] = False
        elif enriched_id in labeled_by_enriched:
            record["audit_bucket"] = "labeled_sample"
            record["in_queue"] = bool(
                prior_verdict in {"false_positive", "uncertain"}
                or matches_labeled_gt is False
            )
        elif propagated:
            propagated_by_session[session_id].append(alignment)
            record["audit_bucket"] = "propagated_pool"
            record["in_queue"] = False
        else:
            record["audit_bucket"] = "other"
            record["in_queue"] = False

        records.append(record)

    sampled_enriched: set[str] = set()
    for session_id, session_alignments in propagated_by_session.items():
        items = sorted(
            session_alignments,
            key=lambda item: str(item.get("enriched_date", "")),
        )
        if not items:
            continue
        if len(items) <= per_session_sample:
            chosen = items
        else:
            step = len(items) / per_session_sample
            chosen = [items[int(index * step)] for index in range(per_session_sample)]
        for alignment in chosen:
            sampled_enriched.add(str(alignment.get("enriched_id", "")))

    queue_priority = {
        "labeled_sample": 0,
        "stratified_sample": 1,
        "propagated_pool": 2,
        "other": 3,
        "verified": 4,
    }

    for record in records:
        enriched_id = record["enriched_id"]
        if record["audit_bucket"] == "propagated_pool" and enriched_id in sampled_enriched:
            record["audit_bucket"] = "stratified_sample"
            record["in_queue"] = True

    records.sort(
        key=lambda item: (
            0 if item.get("in_queue") else 1,
            queue_priority.get(str(item.get("audit_bucket")), 9),
            -(item.get("session_precision") or 0.0),
            item.get("enriched_date", ""),
            item.get("enriched_id", ""),
        )
    )

    summary = {
        "total_alignments": len(alignments),
        "verified_pins": sum(1 for item in records if item["audit_bucket"] == "verified"),
        "labeled_sample": sum(1 for item in records if item["audit_bucket"] == "labeled_sample"),
        "stratified_sample": sum(1 for item in records if item["audit_bucket"] == "stratified_sample"),
        "propagated_pool": sum(1 for item in records if item["audit_bucket"] == "propagated_pool"),
        "audit_queue": sum(1 for item in records if item["in_queue"]),
        "per_session_sample": per_session_sample,
    }
    return {"summary": summary, "records": records}


def write_alignment_audit_html(
    audit_payload: dict[str, Any],
    output_path: Path,
    data_path: Path | None = None,
) -> None:
    """Side-by-side audit UI for propagated chain links (confirm / reject / skip)."""
    data_path = data_path or output_path.with_name("alignment_audit_data.js")
    data_path.write_text(
        "window.ALIGNMENT_AUDIT=" + json.dumps(audit_payload, ensure_ascii=False) + ";",
        encoding="utf-8",
    )

    summary = audit_payload.get("summary", {})
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Chain alignment audit</title>
<script src="{data_path.name}"></script>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; background: #f4f6f8; color: #1a202c; }}
.header {{ background: #1a365d; color: #fff; padding: 20px 24px; }}
.header h1 {{ margin: 0 0 8px; font-size: 1.35rem; }}
.meta {{ margin: 0; opacity: 0.92; font-size: 0.92rem; max-width: 920px; line-height: 1.45; }}
.toolbar {{ display: flex; flex-wrap: wrap; gap: 14px 20px; padding: 14px 24px; background: #fff; border-bottom: 1px solid #e2e8f0; align-items: center; }}
.panel {{ margin: 16px 24px 24px; background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); padding: 18px 20px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: #718096; margin: 12px 0 6px; }}
.preview {{ font-family: Georgia, serif; font-size: 0.95rem; line-height: 1.55; background: #f7fafc; padding: 12px; border-radius: 8px; white-space: pre-wrap; max-height: 280px; overflow-y: auto; border: 1px solid #e2e8f0; }}
.meta-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.78rem; background: #edf2f7; }}
.badge.queue {{ background: #feebc8; }}
.badge.verified {{ background: #c6f6d5; }}
.badge.mismatch {{ background: #fed7d7; }}
.badge.weak {{ background: #fefcbf; }}
.actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }}
button {{ padding: 8px 14px; border-radius: 6px; border: 1px solid #cbd5e0; background: #fff; cursor: pointer; }}
button.primary {{ background: #2b6cb0; color: #fff; border-color: #2b6cb0; }}
button.danger {{ background: #c53030; color: #fff; border-color: #c53030; }}
.progress {{ font-size: 0.9rem; color: #4a5568; }}
.note {{ margin: 0 24px 12px; padding: 12px 16px; background: #ebf8ff; border-left: 4px solid #3182ce; font-size: 0.9rem; line-height: 1.45; }}
.gt {{ border-left: 3px solid #805ad5; padding-left: 10px; margin-top: 8px; }}
.export {{ margin: 0 24px 24px; }}
{CORRECTION_CLI_BLOCK}
</style></head><body>
<div class="header">
  <h1>Chain alignment audit</h1>
  <p class="meta">Risk-based spot-check of propagated chain links. Confirmed audits become pins; rejections block the pair on re-run. Do not treat unaudited propagated links as training labels.</p>
</div>
<p class="note">Queue: {summary.get('audit_queue', 0)} items ({summary.get('per_session_sample', 25)} evenly spaced propagated links per session + labeled mismatches). Total chain: {summary.get('total_alignments', 0)} ({summary.get('verified_pins', 0)} already pinned). <b>Workflow:</b> Confirm / Reject each link → <b>Export audit decisions</b> → move <code>sequence_correction_summary.json</code> to <code>output/</code>, then run:{CORRECTION_CLI_BLOCK}</p>
<div class="toolbar">
  <label><input type="checkbox" id="queueOnly" checked> audit queue only</label>
  <label>Session <select id="sessionFilter"><option value="">all</option></select></label>
  <label>Bucket <select id="bucketFilter">
    <option value="">all</option>
    <option value="stratified_sample">stratified sample</option>
    <option value="labeled_sample">labeled sample</option>
    <option value="verified">verified pins</option>
  </select></label>
  <span class="progress" id="progress"></span>
</div>
<div class="panel" id="card"></div>
<div class="actions panel">
  <button type="button" class="primary" id="confirmBtn">Confirm chain link</button>
  <button type="button" class="danger" id="rejectBtn">Reject chain link</button>
  <button type="button" id="skipBtn">Skip</button>
  <button type="button" id="prevBtn">Previous</button>
  <button type="button" id="nextBtn">Next</button>
</div>
<div class="export panel">
  <button type="button" id="exportBtn">Export audit decisions</button>
  <button type="button" id="clearBtn">Clear saved decisions</button>
  <p id="exportStatus"></p>
</div>
<script>
const PAYLOAD = window.ALIGNMENT_AUDIT || {{ summary: {{}}, records: [] }};
const ALL = PAYLOAD.records || [];
const STORAGE_KEY = 'alignment_audit_decisions_v1';
let FILTERED = [];
let INDEX = 0;
let DECISIONS = {{}};

function loadStorage() {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) DECISIONS = JSON.parse(raw);
  }} catch (err) {{
    DECISIONS = {{}};
  }}
}}

function saveStorage() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(DECISIONS));
}}

function esc(s) {{
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function applyFilters() {{
  const queueOnly = document.getElementById('queueOnly').checked;
  const session = document.getElementById('sessionFilter').value;
  const bucket = document.getElementById('bucketFilter').value;
  FILTERED = ALL.filter(item => {{
    if (queueOnly && !item.in_queue) return false;
    if (session && item.session_id !== session) return false;
    if (bucket && item.audit_bucket !== bucket) return false;
    return true;
  }});
  if (INDEX >= FILTERED.length) INDEX = Math.max(0, FILTERED.length - 1);
  render();
}}

function badgeRow(item) {{
  const parts = [
    `<span class="badge">${{esc(item.link_kind)}}</span>`,
    `<span class="badge">${{esc(item.audit_bucket)}}</span>`,
    item.in_queue ? '<span class="badge queue">in queue</span>' : '',
    item.manually_pinned ? '<span class="badge verified">pinned</span>' : '',
    item.matches_labeled_gt === false ? '<span class="badge mismatch">≠ labeled GT</span>' : '',
    (item.session_precision != null && item.session_precision < 0.65) ? '<span class="badge weak">weak session</span>' : '',
    item.prior_verdict ? `<span class="badge">${{esc(item.prior_verdict)}}</span>` : '',
  ];
  return parts.filter(Boolean).join(' ');
}}

function render() {{
  const card = document.getElementById('card');
  const progress = document.getElementById('progress');
  if (!FILTERED.length) {{
    card.innerHTML = '<p>No records match the current filters.</p>';
    progress.textContent = '0 / 0';
    return;
  }}
  const item = FILTERED[INDEX];
  const decision = DECISIONS[item.audit_id];
  const gtBlock = item.gt_paragraph_id
    ? `<div class="gt"><div class="label">Labeled GT paragraph (${{esc(item.gt_paragraph_id)}})</div><div class="preview">${{esc(item.gt_flat_preview) || '—'}}</div></div>`
    : '';
  card.innerHTML = `
    <div class="meta-row">${{badgeRow(item)}}</div>
    <p><b>${{esc(item.enriched_id)}}</b> · ${{esc(item.enriched_date)}} · ${{esc(item.session_id)}}</p>
    <p>Chain → paragraph <code>${{esc(item.paragraph_id)}}</code> · resolution <code>${{esc(item.resolution_id)}}</code></p>
    ${{decision ? `<p><b>Your decision:</b> ${{esc(decision.action)}}</p>` : ''}}
    <div class="grid">
      <div><div class="label">Enriched text</div><div class="preview">${{esc(item.enriched_preview) || '—'}}</div></div>
      <div><div class="label">Flat paragraph (chain)</div><div class="preview">${{esc(item.flat_preview) || '—'}}</div></div>
    </div>
    ${{gtBlock}}
    <p style="margin-top:12px"><a href="verify_day_sequences.html">Day sequence view</a> · <a href="verify_resolution_search.html#${{encodeURIComponent(item.enriched_id)}}">Search / correct</a></p>`;
  progress.textContent = `${{INDEX + 1}} / ${{FILTERED.length}} · ${{Object.keys(DECISIONS).length}} saved`;
}}

function storeDecision(action) {{
  const item = FILTERED[INDEX];
  if (!item) return;
  const confirmed = action === 'confirmed';
  DECISIONS[item.audit_id] = {{
    correction_id: item.audit_id,
    enriched_id: item.enriched_id,
    session_id: item.session_id,
    action: action,
    corrected_paragraph_id: confirmed ? item.paragraph_id : null,
    corrected_resolution_id: confirmed ? item.resolution_id : null,
    auto_paragraph_id: item.paragraph_id,
    auto_flat_id: item.resolution_id,
    prior_verdict: item.prior_verdict,
    audit_bucket: item.audit_bucket,
    source: 'chain_audit',
    timestamp: new Date().toISOString(),
  }};
  saveStorage();
  if (INDEX < FILTERED.length - 1) INDEX += 1;
  render();
}}

document.getElementById('confirmBtn').addEventListener('click', () => storeDecision('confirmed'));
document.getElementById('rejectBtn').addEventListener('click', () => storeDecision('rejected'));
document.getElementById('skipBtn').addEventListener('click', () => {{ if (INDEX < FILTERED.length - 1) INDEX += 1; render(); }});
document.getElementById('prevBtn').addEventListener('click', () => {{ if (INDEX > 0) INDEX -= 1; render(); }});
document.getElementById('nextBtn').addEventListener('click', () => {{ if (INDEX < FILTERED.length - 1) INDEX += 1; render(); }});
document.getElementById('queueOnly').addEventListener('change', applyFilters);
document.getElementById('sessionFilter').addEventListener('change', applyFilters);
document.getElementById('bucketFilter').addEventListener('change', applyFilters);

document.getElementById('exportBtn').addEventListener('click', () => {{
  const values = Object.values(DECISIONS);
  const payload = {{
    total: ALL.filter(item => item.in_queue).length,
    filtered: FILTERED.length,
    corrected: values.filter(item => item.action === 'confirmed').length,
    rejected: values.filter(item => item.action === 'rejected').length,
    uncertain: values.filter(item => item.action === 'uncertain').length,
    source: 'chain_audit',
    corrections: DECISIONS,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'sequence_correction_summary.json';
  anchor.click();
  URL.revokeObjectURL(url);
  document.getElementById('exportStatus').textContent =
    `Exported ${{values.length}} decisions (${{payload.corrected}} confirmed, ${{payload.rejected}} rejected). Move file to output/ and run import + chain re-run (see note above).`;
}});

document.getElementById('clearBtn').addEventListener('click', () => {{
  if (!confirm('Clear all saved audit decisions in this browser?')) return;
  DECISIONS = {{}};
  localStorage.removeItem(STORAGE_KEY);
  render();
  document.getElementById('exportStatus').textContent = 'Cleared saved decisions.';
}});

const sessions = [...new Set(ALL.map(item => item.session_id).filter(Boolean))].sort();
const sessionSelect = document.getElementById('sessionFilter');
sessions.forEach(sessionId => {{
  const option = document.createElement('option');
  option.value = sessionId;
  option.textContent = sessionId;
  sessionSelect.appendChild(option);
}});

loadStorage();
applyFilters();
</script></body></html>"""
    output_path.write_text(html, encoding="utf-8")

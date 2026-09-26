#!/usr/bin/env python3
"""S3 — boundary gold annotation UI.

Renders a self-contained HTML page for hand-labeling the 50 session-days in
output/boundary_gold_sample.json (docs/SEGMENTATION_TRANSFER.md §10).

For each day: shows the K_e enriched resolutions (left) in order, and the
ordered flat-paragraph stream as one editable text block (right). Annotate by
typing the cut marker directly into the text at each resolution boundary —
anywhere, including mid-paragraph or mid-word — rather than clicking. A day is
"complete" once exactly K_e - 1 cut markers are present. Progress is saved to
localStorage as you go.

Sessions do not always split cleanly at the day boundary, so extra affordances
handle the edges and internal gaps:
  - An optional END marker marks where a resolution's content actually ends.
    Used alone at the end of the text, it marks where the last (K_e-th)
    resolution ends when that is before the end of the shown text (trailing
    text is spillover belonging to the next session/day). Used mid-text
    immediately before a START marker, it brackets a gap.
  - An optional START marker marks where the next resolution's content
    actually begins, when it is not immediately after the previous one — e.g.
    a session-heading formula like "Praeside et Praesentibus..." sits between
    two resolutions and belongs to neither. Text between an END and the next
    START marker is excluded as boilerplate, not attributed to any resolution.
    A START marker counts as an internal boundary the same way a cut marker
    does (K_e - 1 total transitions = cut markers + START markers).
  - A "first fragment is a continuation" checkbox flags that the visible text
    does not start a fresh resolution — it continues a resolution begun on a
    previous day — since there is no earlier text available to place a cut in.

Workflow:
    1. uv run python build_boundary_annotation_ui.py
    2. Open output/boundary_annotation_ui.html in a browser. Read, and type
       the cut marker (shown in the toolbar) at each plain internal boundary;
       use END + START around any boilerplate/header gap between two
       resolutions; use END alone if the last resolution ends before the
       visible text does; tick the checkbox if the first fragment is a
       continuation.
    3. Click "Export annotations" -> saves boundary_gold_annotations.json.
    4. Move it into output/, then run:
       uv run python merge_boundary_annotations.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from build_alignment_new import OUTPUT_DIR, as_text, enriched_text, load_data, sort_key_res_id

SAMPLE_FILE = OUTPUT_DIR / "boundary_gold_sample.json"
OUT_HTML = OUTPUT_DIR / "boundary_annotation_ui.html"
MARKER = "|||CUT|||"  # typed inline into the text at each resolution boundary
MARKER_END = "|||END|||"  # optional: true end of a resolution (last resolution, or before a gap)
MARKER_START = "|||START RES|||"  # optional: true start of the next resolution, after a boilerplate gap
SEPARATOR = "\n\n"  # joins paragraphs into one editable block; must match merge_boundary_annotations.py


def flat_paragraph_stream(res_df, flat_ids: list[str]) -> list[dict[str, Any]]:
    """Flatten paragraph_texts across flat_ids (in canonical resolution order)."""
    ordered_ids = sorted(flat_ids, key=sort_key_res_id)
    stream = []
    for flat_id in ordered_ids:
        rows = res_df[res_df["id"] == flat_id]
        if rows.empty:
            continue
        paragraphs = rows.iloc[0].get("paragraph_texts")
        if isinstance(paragraphs, str):
            try:
                paragraphs = json.loads(paragraphs)
            except (TypeError, ValueError):
                paragraphs = [paragraphs]
        if not isinstance(paragraphs, list):
            paragraphs = [paragraphs] if paragraphs else []
        for i, p in enumerate(paragraphs):
            text = as_text(p).strip()
            if text:
                stream.append({"flat_id": flat_id, "para_index": i, "text": text})
    return stream


def enriched_previews(enriched_all: list[dict[str, Any]], date_str: str) -> list[dict[str, Any]]:
    day_items = [e for e in enriched_all if str(e.get("date", ""))[:10] == date_str]
    day_items.sort(key=lambda e: e.get("resolution_index", 0))
    return [
        {
            "key": str(e.get("volgnr") or f"{e.get('file')}#{e.get('resolution_index')}"),
            "text": enriched_text(e)[:600],
        }
        for e in day_items
    ]


def build_day_payloads(sample_days: list[dict[str, Any]], enriched_all, res_df) -> list[dict[str, Any]]:
    payloads = []
    for day in sample_days:
        payloads.append(
            {
                "date": day["date"],
                "k_e": day["k_e"],
                "k_f": day["k_f"],
                "stratum": day["stratum"],
                "enriched": enriched_previews(enriched_all, day["date"]),
                "paragraphs": flat_paragraph_stream(res_df, day["flat_ids"]),
            }
        )
    return payloads


def render_html(payloads: list[dict[str, Any]]) -> str:
    data_json = json.dumps(payloads, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>Boundary Gold Annotator</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; background: #eef2f7; margin: 0; color: #1a202c; }}
.header {{ background: white; padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
h1 {{ margin: 0 0 6px; color: #1a365d; font-size: 1.4rem; }}
.meta {{ color: #4a5568; font-size: 0.92rem; }}
.toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; align-items: center; }}
.toolbar button {{ padding: 8px 14px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }}
.toolbar .primary {{ background: #2b6cb0; color: white; }}
.toolbar .muted {{ background: #4a5568; color: white; }}
.toolbar code {{ background: #edf2f7; padding: 2px 6px; border-radius: 4px; }}
.main {{ display: grid; grid-template-columns: 1fr 1.3fr; gap: 16px; padding: 16px 24px 40px; max-width: 1500px; }}
.panel {{ background: white; border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); max-height: 78vh; overflow-y: auto; }}
.panel h2 {{ margin: 0 0 12px; font-size: 1rem; color: #2d3748; }}
.enr-item {{ font-family: Georgia, serif; font-size: 0.88rem; line-height: 1.5; background: #f7fafc; padding: 10px; border-radius: 8px; margin-bottom: 8px; white-space: pre-wrap; }}
.enr-item .idx {{ font-family: 'Segoe UI', sans-serif; font-size: 0.75rem; color: #718096; margin-bottom: 4px; }}
#editor {{ width: 100%; min-height: 60vh; box-sizing: border-box; font-family: Georgia, serif; font-size: 0.92rem; line-height: 1.6; padding: 10px; border: 1px solid #cbd5e0; border-radius: 8px; resize: vertical; }}
.progress {{ font-weight: 600; }}
.progress.ok {{ color: #2f855a; }}
.progress.bad {{ color: #c53030; }}
.pagination {{ display: flex; justify-content: center; gap: 16px; padding: 12px; }}
.pagination button {{ padding: 10px 20px; background: #4a5568; color: white; border: none; border-radius: 6px; cursor: pointer; }}
.note {{ margin: 0 24px 20px; padding: 12px 16px; background: #ebf8ff; border-left: 4px solid #3182ce; font-size: 0.9rem; }}
.flag-row {{ margin: 10px 0 0; font-size: 0.88rem; color: #4a5568; }}
.flag-row label {{ display: flex; align-items: center; gap: 6px; }}
</style></head><body>
<div class='header'>
  <h1>Boundary Gold Annotator</h1>
  <p class='meta'>Left: K_e enriched resolutions for the day, in order. Right: the flat-paragraph stream as editable text.
  Type the marker <code>{MARKER}</code> directly into the text at each plain resolution boundary (anywhere — mid-paragraph and mid-word are fine).
  If a boilerplate/header gap sits between two resolutions (e.g. a session heading), bracket it with <code>{MARKER_END}</code> before the gap and
  <code>{MARKER_START}</code> after it instead of a cut marker. Place exactly K_e - 1 total transitions (cut markers + START markers).
  If the last resolution ends before the visible text does (trailing text belongs to another session), place a lone <code>{MARKER_END}</code> at its true end.
  If the first fragment is a continuation from a previous day, tick the checkbox below the editor.</p>
  <div class='toolbar'>
    <span id='progress' class='meta'>0 / 0</span>
    <button class='muted' onclick='insertMarker()'>Insert cut marker</button>
    <button class='muted' onclick='insertEndMarker()'>Insert END marker</button>
    <button class='muted' onclick='insertStartMarker()'>Insert START marker</button>
    <button class='primary' onclick='exportAnnotations()'>Export annotations</button>
    <button class='muted' onclick='clearStorage()'>Clear saved</button>
  </div>
</div>
<p class='note'><b>Workflow:</b> type <code>{MARKER}</code> at plain cut points, bracket boilerplate gaps with <code>{MARKER_END}</code> … <code>{MARKER_START}</code>, use a lone <code>{MARKER_END}</code> if the last resolution ends early, export, move <code>boundary_gold_annotations.json</code> into <code>output/</code>, then run <code>uv run python merge_boundary_annotations.py</code>.</p>
<div id='task'></div>
<div class='pagination'>
  <button id='prevBtn' onclick='changePage(-1)'>&larr; Previous</button>
  <span id='pageInfo' class='meta'>Day 1</span>
  <button id='nextBtn' onclick='changePage(1)'>Next &rarr;</button>
</div>
<script>
const DAYS = {data_json};
const MARKER = {json.dumps(MARKER)};
const MARKER_END = {json.dumps(MARKER_END)};
const MARKER_START = {json.dumps(MARKER_START)};
const SEPARATOR = {json.dumps(SEPARATOR)};
const STORAGE_KEY = 'boundary_gold_annotations_v4';
const LEGACY_STORAGE_PREFIX = 'boundary_gold_annotations_';
let page = 0;
let annotations = {{}};  // date -> {{ text, startsMid }}

function loadStorage() {{
  try {{
    const current = localStorage.getItem(STORAGE_KEY);
    if (current) {{
      annotations = JSON.parse(current) || {{}};
      return;
    }}
  }} catch(e) {{ annotations = {{}}; }}

  const legacyKeys = Object.keys(localStorage)
    .filter(key => key.startsWith(LEGACY_STORAGE_PREFIX) && key !== STORAGE_KEY)
    .sort((a, b) => {{
      const parseVersion = (key) => {{
        const match = key.match(/v(\\d+)$/);
        return match ? parseInt(match[1], 10) : 0;
      }};
      return parseVersion(b) - parseVersion(a);
    }});

  for (const key of legacyKeys) {{
    try {{
      const parsed = JSON.parse(localStorage.getItem(key) || '{{}}');
      if (parsed && typeof parsed === 'object' && Object.keys(parsed).length) {{
        annotations = parsed;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(annotations));
        return;
      }}
    }} catch(e) {{
      // Ignore unreadable legacy keys and continue.
    }}
  }}

  annotations = {{}};
}}
function saveStorage() {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(annotations)); }}

function esc(s) {{
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function countOccurrences(text, marker) {{
  return text.split(marker).length - 1;
}}

function baseTextFor(day) {{
  return day.paragraphs.map(p => p.text).join(SEPARATOR);
}}

function stateFor(day) {{
  if (!annotations[day.date]) annotations[day.date] = {{ text: baseTextFor(day), startsMid: false }};
  return annotations[day.date];
}}

function textFor(day) {{
  return stateFor(day).text;
}}

function onEdit() {{
  const day = DAYS[page];
  const el = document.getElementById('editor');
  stateFor(day).text = el.value;
  saveStorage();
  updateProgress();
}}

function toggleStartsMid() {{
  const day = DAYS[page];
  stateFor(day).startsMid = document.getElementById('startsMid').checked;
  saveStorage();
}}

function insertAtCursor(marker) {{
  const el = document.getElementById('editor');
  const start = el.selectionStart, end = el.selectionEnd;
  el.value = el.value.slice(0, start) + marker + el.value.slice(end);
  el.selectionStart = el.selectionEnd = start + marker.length;
  el.focus();
  onEdit();
}}

function insertMarker() {{ insertAtCursor(MARKER); }}
function insertEndMarker() {{ insertAtCursor(MARKER_END); }}
function insertStartMarker() {{ insertAtCursor(MARKER_START); }}

function countTransitions(text) {{
  return countOccurrences(text, MARKER) + countOccurrences(text, MARKER_START);
}}

function isDayComplete(day) {{
  const s = stateFor(day);
  return countTransitions(s.text) === day.k_e - 1;
}}

function updateProgress() {{
  const day = DAYS[page];
  const needed = day.k_e - 1;
  const current = countTransitions(textFor(day));
  const hasEnd = countOccurrences(textFor(day), MARKER_END) > 0;
  document.getElementById('dayCount').className = `progress ${{current === needed ? 'ok' : 'bad'}}`;
  document.getElementById('dayCount').textContent = `${{current}} / ${{needed}} transitions placed (cut + START)${{hasEnd ? ' · END marker used' : ''}}`;

  const doneDays = DAYS.filter(isDayComplete).length;
  document.getElementById('progress').textContent = `${{doneDays}} / ${{DAYS.length}} days complete`;
}}

function render() {{
  const day = DAYS[page];
  const state = stateFor(day);

  const enrichedHtml = day.enriched.map((e, i) => `
    <div class="enr-item"><div class="idx">#${{i + 1}} &middot; ${{esc(e.key)}}</div>${{esc(e.text)}}</div>`).join('');

  document.getElementById('task').innerHTML = `
    <div style="padding:0 24px 8px" class="meta">${{esc(day.date)}} &middot; K_e=${{day.k_e}} K_f=${{day.k_f}} &middot; stratum ${{esc(day.stratum)}}
      &middot; <span id="dayCount" class="progress"></span></div>
    <div class="main">
      <div class="panel"><h2>Enriched resolutions (${{day.enriched.length}})</h2>${{enrichedHtml}}</div>
      <div class="panel"><h2>Flat paragraph stream (edit to add markers)</h2>
        <textarea id="editor" oninput="onEdit()" spellcheck="false">${{esc(textFor(day))}}</textarea>
        <div class="flag-row"><label><input type="checkbox" id="startsMid" ${{state.startsMid ? 'checked' : ''}} onchange="toggleStartsMid()">
          First fragment is <b>not</b> the start of a new resolution (continues from a previous day)</label></div>
      </div>
    </div>`;

  updateProgress();
  document.getElementById('pageInfo').textContent = `Day ${{page + 1}} / ${{DAYS.length}}`;
  document.getElementById('prevBtn').disabled = page <= 0;
  document.getElementById('nextBtn').disabled = page >= DAYS.length - 1;
}}

function exportAnnotations() {{
  const payload = {{
    marker: MARKER,
    marker_end: MARKER_END,
    marker_start: MARKER_START,
    separator: SEPARATOR,
    total_days: DAYS.length,
    complete_days: DAYS.filter(isDayComplete).length,
    annotations: annotations,
  }};
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {{type:'application/json'}}));
  a.download = 'boundary_gold_annotations.json';
  a.click();
}}

function clearStorage() {{
  if (confirm('Clear all saved annotations?')) {{ annotations = {{}}; localStorage.removeItem(STORAGE_KEY); render(); }}
}}

function changePage(d) {{
  page = Math.max(0, Math.min(DAYS.length - 1, page + d));
  render();
}}

loadStorage();
render();
</script>
</body></html>
"""


def main() -> None:
    sample = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    enriched_all, res_df, *_ = load_data()
    payloads = build_day_payloads(sample["days"], enriched_all, res_df)
    OUT_HTML.write_text(render_html(payloads), encoding="utf-8")
    print(f"Wrote {OUT_HTML} with {len(payloads)} days to annotate.")


if __name__ == "__main__":
    main()

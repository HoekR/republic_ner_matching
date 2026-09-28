#!/usr/bin/env python3
"""Lumped-paragraph mid-cut annotation UI (static HTML export — legacy).

Prefer the Flask app (disk-backed, same pattern as trifecta ``gold_labeller``):

    uv run lumped-paragraph-gold-ui
    # http://127.0.0.1:5055

This script still writes a standalone HTML file if you want an offline snapshot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve

SCAFFOLD_DATASET = "lumped_paragraph_gold_scaffold"
OUT_HTML = PROJECT_ROOT / "output" / "lumped_paragraph_annotation_ui.html"
MARKER = "|||CUT|||"


def load_candidates() -> list[dict[str, Any]]:
    rows = load(SCAFFOLD_DATASET)
    return [r for r in rows if r.get("record_type") == "candidate"]


def render_html(candidates: list[dict[str, Any]]) -> str:
    data_json = json.dumps(candidates, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<title>Lumped Paragraph Gold Annotator</title>
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
.main {{ display: grid; grid-template-columns: 0.9fr 1.4fr; gap: 16px; padding: 16px 24px 24px; max-width: 1500px; }}
.panel {{ background: white; border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); max-height: 78vh; overflow-y: auto; }}
.panel h2 {{ margin: 0 0 12px; font-size: 1rem; color: #2d3748; }}
.side-item {{ font-size: 0.88rem; line-height: 1.45; background: #f7fafc; padding: 10px; border-radius: 8px; margin-bottom: 8px; }}
.side-item .idx {{ font-size: 0.75rem; color: #718096; margin-bottom: 4px; }}
#editor {{ width: 100%; min-height: 42vh; box-sizing: border-box; font-family: Georgia, serif; font-size: 0.92rem; line-height: 1.6; padding: 10px; border: 1px solid #cbd5e0; border-radius: 8px; resize: vertical; }}
#paragraphNotes, #cutNotes {{ width: 100%; box-sizing: border-box; font-family: 'Segoe UI', sans-serif; font-size: 0.88rem; line-height: 1.45; padding: 8px; border: 1px solid #cbd5e0; border-radius: 8px; resize: vertical; }}
#paragraphNotes {{ min-height: 4.5rem; margin-top: 10px; }}
#cutNotes {{ min-height: 3.5rem; margin-top: 8px; }}
.progress {{ font-weight: 600; }}
.progress.ok {{ color: #2f855a; }}
.progress.bad {{ color: #c53030; }}
.pagination {{ display: flex; justify-content: center; gap: 16px; padding: 12px; }}
.pagination button {{ padding: 10px 20px; background: #4a5568; color: white; border: none; border-radius: 6px; cursor: pointer; }}
.note {{ margin: 0 24px 12px; padding: 12px 16px; background: #ebf8ff; border-left: 4px solid #3182ce; font-size: 0.9rem; }}
.flag-row {{ margin: 10px 0 0; font-size: 0.88rem; color: #4a5568; display: flex; flex-wrap: wrap; gap: 16px; }}
.flag-row label {{ display: flex; align-items: center; gap: 6px; }}
label.block {{ display: block; margin-top: 10px; font-size: 0.8rem; color: #4a5568; font-weight: 600; }}
</style></head><body>
<div class='header'>
  <h1>Lumped Paragraph Gold Annotator</h1>
  <p class='meta'>One continuous HTR paragraph that concordance says holds 2+ resolutions.
  Type <code>{MARKER}</code> at each interior cut (where the next resolution begins).
  Use notes when the material is cluttered or the offset is approximate.</p>
  <div class='toolbar'>
    <span id='progress' class='meta'>0 / 0</span>
    <button class='muted' onclick='insertMarker()'>Insert cut marker</button>
    <button class='primary' onclick='exportAnnotations()'>Export annotations</button>
    <button class='muted' onclick='clearStorage()'>Clear saved</button>
  </div>
</div>
<p class='note'><b>Workflow:</b> place exactly <i>expected_cuts</i> markers (shown per item),
optionally tick uncertain/clutter and write notes, export, move
<code>lumped_paragraph_gold_annotations.json</code> into <code>output/</code>, then
<code>uv run python scripts/merge_lumped_paragraph_annotations.py</code>.</p>
<div id='task'></div>
<div class='pagination'>
  <button id='prevBtn' onclick='changePage(-1)'>&larr; Previous</button>
  <span id='pageInfo' class='meta'>Item 1</span>
  <button id='nextBtn' onclick='changePage(1)'>Next &rarr;</button>
</div>
<script>
const ITEMS = {data_json};
const MARKER = {json.dumps(MARKER)};
const STORAGE_KEY = 'lumped_paragraph_gold_annotations_v1';
let page = 0;
let annotations = {{}};

function loadStorage() {{
  try {{
    annotations = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}') || {{}};
  }} catch(e) {{ annotations = {{}}; }}
}}
function saveStorage() {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(annotations)); }}

function esc(s) {{
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function countCuts(text) {{
  return String(text || '').split(MARKER).length - 1;
}}

function stateFor(item) {{
  const id = item.example_id;
  if (!annotations[id]) {{
    annotations[id] = {{
      text: item.text,
      paragraph_notes: item.paragraph_notes || '',
      cut_notes: '',
      uncertain: !!item.uncertain,
      clutter: !!item.clutter,
      skip: false,
    }};
  }}
  return annotations[id];
}}

function onEdit() {{
  const item = ITEMS[page];
  const s = stateFor(item);
  s.text = document.getElementById('editor').value;
  s.paragraph_notes = document.getElementById('paragraphNotes').value;
  s.cut_notes = document.getElementById('cutNotes').value;
  s.uncertain = document.getElementById('uncertain').checked;
  s.clutter = document.getElementById('clutter').checked;
  s.skip = document.getElementById('skip').checked;
  saveStorage();
  updateProgress();
}}

function insertMarker() {{
  const el = document.getElementById('editor');
  const start = el.selectionStart, end = el.selectionEnd;
  el.value = el.value.slice(0, start) + MARKER + el.value.slice(end);
  el.selectionStart = el.selectionEnd = start + MARKER.length;
  el.focus();
  onEdit();
}}

function isComplete(item) {{
  const s = stateFor(item);
  if (s.skip) return true;
  return countCuts(s.text) === item.expected_cuts;
}}

function updateProgress() {{
  const item = ITEMS[page];
  const s = stateFor(item);
  const current = countCuts(s.text);
  const needed = item.expected_cuts;
  const ok = s.skip || current === needed;
  document.getElementById('itemCount').className = `progress ${{ok ? 'ok' : 'bad'}}`;
  document.getElementById('itemCount').textContent = s.skip
    ? 'skipped'
    : `${{current}} / ${{needed}} cuts placed`;
  const done = ITEMS.filter(isComplete).length;
  document.getElementById('progress').textContent = `${{done}} / ${{ITEMS.length}} items complete`;
}}

function render() {{
  const item = ITEMS[page];
  const s = stateFor(item);
  const ids = (item.resolution_ids || []).map((id, i) =>
    `<div class="side-item"><div class="idx">res #${{i + 1}} · idx ${{esc((item.resolution_indices || [])[i])}}</div>${{esc(id)}}</div>`
  ).join('');

  document.getElementById('task').innerHTML = `
    <div style="padding:0 24px 8px" class="meta">
      ${{esc(item.example_id)}} · ${{esc(item.date)}} · paragraph ${{item.paragraph_stream_index}}
      · ${{item.n_resolutions}} resolutions · expected_cuts=${{item.expected_cuts}}
      · <span id="itemCount" class="progress"></span>
    </div>
    <div class="main">
      <div class="panel">
        <h2>Concordance resolutions sharing this paragraph</h2>
        ${{ids || '<p class="meta">No resolution ids</p>'}}
        <p class="meta" style="margin-top:12px">flat_id: ${{esc(item.flat_id || '')}} · chars: ${{item.text_char_len}}</p>
      </div>
      <div class="panel">
        <h2>Paragraph HTR (edit to add cut markers)</h2>
        <textarea id="editor" oninput="onEdit()" spellcheck="false">${{esc(s.text)}}</textarea>
        <div class="flag-row">
          <label><input type="checkbox" id="uncertain" ${{s.uncertain ? 'checked' : ''}} onchange="onEdit()"> uncertain cut(s)</label>
          <label><input type="checkbox" id="clutter" ${{s.clutter ? 'checked' : ''}} onchange="onEdit()"> cluttered / hard HTR</label>
          <label><input type="checkbox" id="skip" ${{s.skip ? 'checked' : ''}} onchange="onEdit()"> skip (not annotatable)</label>
        </div>
        <label class="block" for="paragraphNotes">Paragraph notes</label>
        <textarea id="paragraphNotes" oninput="onEdit()" placeholder="Whole-paragraph comments (run-on clerk hand, spillover, …)">${{esc(s.paragraph_notes)}}</textarea>
        <label class="block" for="cutNotes">Cut notes</label>
        <textarea id="cutNotes" oninput="onEdit()" placeholder="Per-cut comments: approx ±N chars; formula visible; illegible onset; …">${{esc(s.cut_notes)}}</textarea>
      </div>
    </div>`;
  updateProgress();
  document.getElementById('pageInfo').textContent = `Item ${{page + 1}} / ${{ITEMS.length}}`;
  document.getElementById('prevBtn').disabled = page <= 0;
  document.getElementById('nextBtn').disabled = page >= ITEMS.length - 1;
}}

function changePage(delta) {{
  page = Math.max(0, Math.min(ITEMS.length - 1, page + delta));
  render();
}}

function exportAnnotations() {{
  const payload = {{
    marker: MARKER,
    exported_at: new Date().toISOString(),
    annotations: annotations,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'lumped_paragraph_gold_annotations.json';
  a.click();
}}

function clearStorage() {{
  if (!confirm('Clear all saved lumped-paragraph annotations in this browser?')) return;
  localStorage.removeItem(STORAGE_KEY);
  annotations = {{}};
  render();
}}

loadStorage();
render();
</script></body></html>
"""


def main() -> None:
    resolve(SCAFFOLD_DATASET)
    candidates = load_candidates()
    if not candidates:
        raise SystemExit(
            f"No candidates in {SCAFFOLD_DATASET}. "
            "Run: uv run python scripts/build_lumped_paragraph_gold_scaffold.py"
        )
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(render_html(candidates), encoding="utf-8")
    print(f"Wrote {OUT_HTML} ({len(candidates)} candidates)")
    print("Open in a browser, annotate, Export, then merge_lumped_paragraph_annotations.py")


if __name__ == "__main__":
    main()

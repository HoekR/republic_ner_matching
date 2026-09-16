#!/usr/bin/env python3
"""Build a self-contained UI for reviewing non-automatic session-date mappings."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve
from scripts.s4_session_date_mapping_predictions import _as_list


LEDGER_DATASET = "session_date_status_1626_1630"
ENRICHED_DATASET = "enriched_resolutions_1626_1630"
FLAT_DATASET = "resolutions_flat"
AXIS_DATASET = "paragraph_axis_1626_1630"
OUTPUT_DATASET = "s4_session_date_mapping_review_ui"
DECISIONS_DATASET = "s4_session_date_mapping_decisions"
REVIEW_STATUSES = {"A", "X", "?", "-1", "+1", "N"}
CANDIDATE_COLUMNS = (
    "trusted_session_ids",
    "exact_date_session_ids",
    "previous_day_session_ids",
    "next_day_session_ids",
)


def _text(value: Any) -> str:
    if value is None or (not isinstance(value, (list, tuple)) and pd.isna(value)):
        return ""
    return " ".join(str(item) for item in value if item) if isinstance(value, (list, tuple)) else str(value)


def _candidate_text(record: dict[str, Any]) -> str:
    for column in ("resolutions_text", "paragraph_texts", "paragraph_text"):
        text = _text(record.get(column))
        if text:
            return text
    return ""


def _resolution_sort_key(flat_id: str) -> tuple[int, int, int]:
    match = re.search(r"session-(\d+)-num-(\d+)-resolution-(\d+)", flat_id)
    return tuple(int(value) for value in match.groups()) if match else (0, 0, 0)


def candidate_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return an ordered candidate union with the evidence lists that contain it."""
    candidates: dict[str, list[str]] = {}
    for column in CANDIDATE_COLUMNS:
        for session_id in _as_list(row.get(column)):
            candidates.setdefault(session_id, []).append(column)
    return [{"session_id": session_id, "sources": sources} for session_id, sources in candidates.items()]


def queue_rows(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    """Select manual-review rows in canonical inventory/date order."""
    rows = ledger.loc[ledger["status_code"].isin(REVIEW_STATUSES)].sort_values(["inventory_id", "enriched_date"])
    return [row for row in rows.to_dict(orient="records")]


def stratified_sample(rows: list[dict[str, Any]], per_status: int, seed: int = 42) -> list[dict[str, Any]]:
    """Return up to ``per_status`` rows per ledger status, in canonical order."""
    frame = pd.DataFrame(rows)
    sampled = frame.groupby("status_code", group_keys=False).apply(
        lambda group: group.sample(n=min(len(group), per_status), random_state=seed)
    )
    return [row for row in sampled.sort_values(["inventory_id", "enriched_date"]).to_dict(orient="records")]


def _json_value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
        return None
    return value


def build_payloads(
    ledger: pd.DataFrame,
    enriched_records: list[dict[str, Any]],
    flat: pd.DataFrame,
    axis: list[dict[str, Any]],
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assemble complete evidence for each manually reviewable ledger row."""
    enriched_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in enriched_records:
        enriched_by_date[str(record.get("date", ""))[:10]].append(record)
    for records in enriched_by_date.values():
        records.sort(key=lambda item: item.get("resolution_index", 0))

    flat_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in flat.to_dict(orient="records"):
        session_id = str(record.get("id", "")).split("-resolution-", 1)[0]
        flat_by_session[session_id].append({"flat_id": str(record.get("id", "")), "text": _candidate_text(record)})
    for records in flat_by_session.values():
        records.sort(key=lambda item: _resolution_sort_key(item["flat_id"]))

    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        session_id = str(record.get("flat_id", "")).split("-resolution-", 1)[0]
        axis_by_session[session_id].append(
            {"axis_id": str(record.get("axis_id", "")), "flat_id": str(record.get("flat_id", "")), "text": str(record.get("text", ""))}
        )

    payloads: list[dict[str, Any]] = []
    for row in rows if rows is not None else queue_rows(ledger):
        evidence = {key: _json_value(value) for key, value in row.items()}
        candidates = []
        for candidate in candidate_sources(row):
            session_id = candidate["session_id"]
            candidates.append({**candidate, "resolutions": flat_by_session[session_id], "paragraphs": axis_by_session[session_id]})
        payloads.append(
            {
                "session_date_key": str(row["session_date_key"]),
                "ledger": evidence,
                "enriched": [
                    {"key": str(item.get("volgnr") or f"{row['enriched_date']}_{item.get('resolution_index', '')}"), "text": _text(item.get("text"))}
                    for item in enriched_by_date[str(row["enriched_date"])]
                ],
                "candidates": candidates,
            }
        )
    return payloads


def render_html(payloads: list[dict[str, Any]], decisions_filename: str) -> str:
    """Render a localStorage-backed review application with embedded evidence."""
    data = json.dumps(payloads, ensure_ascii=False)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Session-Date Mapping Review</title>
<style>:root{{font-family:Georgia,serif;color:#17202a;background:#f2f0e8}}body{{margin:0}}header,main{{max-width:1500px;margin:auto;padding:18px}}header{{background:#fff;border-bottom:1px solid #c9c5ba}}h1,h2,h3,p{{margin:0}}h1{{font-size:24px}}.toolbar,.pagination,.actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:12px}}button,select,textarea{{font:inherit}}button{{border:1px solid #53606a;background:#fff;padding:7px 11px;cursor:pointer}}button.primary{{background:#176b61;color:#fff;border-color:#176b61}}button:disabled{{opacity:.45;cursor:not-allowed}}.meta{{font:13px ui-monospace,monospace;color:#52606d}}.grid{{display:grid;grid-template-columns:minmax(280px,.8fr) minmax(400px,1.2fr);gap:16px;margin-top:16px}}section{{background:#fff;border:1px solid #c9c5ba;padding:14px;min-width:0}}.evidence{{white-space:pre-wrap;line-height:1.45;font-size:14px;border-top:1px solid #ddd6c8;padding:10px 0}}details{{border-top:1px solid #ddd6c8;padding:10px 0}}summary{{cursor:pointer;font-weight:bold}}.candidate{{border-left:4px solid #176b61;padding-left:10px;margin-top:9px}}textarea{{box-sizing:border-box;width:100%;min-height:72px;margin-top:8px}}.error{{color:#a61b1b;font-weight:bold}}.ok{{color:#176b61;font-weight:bold}}@media(max-width:760px){{header,main{{padding:12px}}.grid{{grid-template-columns:1fr}}}}</style></head><body>
<header><h1>Session-Date Mapping Review</h1><p class="meta" id="progress"></p><div class="toolbar"><button class="primary" onclick="exportDecisions()">Export decisions</button><button onclick="clearStorage()">Clear saved decisions</button></div></header><main><p id="error" class="error"></p><div id="task"></div><div class="pagination"><button id="prev" onclick="changePage(-1)">Previous</button><span class="meta" id="page"></span><button id="next" onclick="changePage(1)">Next</button></div></main>
<script>const ROWS={data};const STORAGE_KEY='s4_session_date_mapping_review_v1';let page=0,decisions={{}};
function esc(value){{return String(value??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}}
function loadStorage(){{try{{decisions=JSON.parse(localStorage.getItem(STORAGE_KEY)||'{{}}')}}catch(e){{decisions={{}}}}}}
function saveStorage(){{localStorage.setItem(STORAGE_KEY,JSON.stringify(decisions))}}
function current(){{return ROWS[page]}}function state(row){{return decisions[row.session_date_key]||{{action:'defer',selected_session_id:null,note:'',client_timestamp:null}}}}
function validate(row,value){{if(!['approve','no_match','defer'].includes(value.action))return 'Choose an action.';if(value.action==='approve'&&!row.candidates.some(c=>c.session_id===value.selected_session_id))return 'Choose one displayed candidate.';if(value.action==='approve'&&['-1','+1'].includes(row.ledger.status_code)&&!value.note.trim())return 'A note is required for a nearby approval.';return ''}}
function onEdit(){{const row=current(),value=state(row);value.action=document.querySelector('input[name=action]:checked')?.value||'';value.selected_session_id=document.getElementById('candidate').value||null;value.note=document.getElementById('note').value;value.client_timestamp=new Date().toISOString();const error=validate(row,value);document.getElementById('error').textContent=error;if(!error){{decisions[row.session_date_key]=value;saveStorage()}}updateProgress()}}
function updateProgress(){{const complete=ROWS.filter(row=>decisions[row.session_date_key]&&!validate(row,decisions[row.session_date_key])).length;document.getElementById('progress').textContent=`${{complete}} / ${{ROWS.length}} valid decisions saved`;}}
function render(){{const row=current(),value=state(row),ledger=row.ledger;const evidence=Object.entries(ledger).map(([key,val])=>`<div class="evidence"><b>${{esc(key)}}</b>: ${{esc(Array.isArray(val)?val.join(', '):val)}}</div>`).join('');const enriched=row.enriched.map(item=>`<div class="evidence"><b>${{esc(item.key)}}</b><br>${{esc(item.text)}}</div>`).join('');const candidates=row.candidates.map(candidate=>`<details class="candidate"><summary>${{esc(candidate.session_id)}} (${{esc(candidate.sources.join(', '))}})</summary><h3>Resolutions</h3>${{candidate.resolutions.map(item=>`<div class="evidence"><b>${{esc(item.flat_id)}}</b><br>${{esc(item.text)}}</div>`).join('')||'<p class="meta">No flat resolution records.</p>'}}<h3>Paragraph axis</h3>${{candidate.paragraphs.map(item=>`<div class="evidence"><b>${{esc(item.axis_id)}}</b><br>${{esc(item.text)}}</div>`).join('')||'<p class="meta">No paragraph-axis records.</p>'}}</details>`).join('');document.getElementById('task').innerHTML=`<div class="grid"><section><h2>Ledger evidence</h2>${{evidence}}</section><section><h2>Decision</h2><div class="actions"><label><input type="radio" name="action" value="approve" ${{value.action==='approve'?'checked':''}} onchange="onEdit()"> Choose candidate</label><label><input type="radio" name="action" value="no_match" ${{value.action==='no_match'?'checked':''}} onchange="onEdit()"> No match</label><label><input type="radio" name="action" value="defer" ${{value.action==='defer'?'checked':''}} onchange="onEdit()"> Defer</label></div><select id="candidate" onchange="onEdit()"><option value="">Select candidate</option>${{row.candidates.map(c=>`<option value="${{esc(c.session_id)}}" ${{value.selected_session_id===c.session_id?'selected':''}}>${{esc(c.session_id)}} (${{esc(c.sources.join(', '))}})</option>`).join('')}}</select><textarea id="note" placeholder="Review note" oninput="onEdit()">${{esc(value.note)}}</textarea><h2>Enriched resolutions</h2>${{enriched}}<h2>HTR candidates</h2>${{candidates||'<p class="meta">No inventory-local candidates; record no match or defer.</p>'}}</section></div>`;document.getElementById('page').textContent=`${{page+1}} / ${{ROWS.length}}`;document.getElementById('prev').disabled=page===0;document.getElementById('next').disabled=page===ROWS.length-1;document.getElementById('error').textContent=validate(row,value);updateProgress()}}
function changePage(delta){{page=Math.max(0,Math.min(ROWS.length-1,page+delta));render()}}function exportDecisions(){{const decided=ROWS.filter(row=>decisions[row.session_date_key]);const invalid=decided.filter(row=>validate(row,decisions[row.session_date_key]));if(invalid.length){{document.getElementById('error').textContent=`${{invalid.length}} saved decision(s) are invalid; fix before export.`;return}}if(!decided.length){{document.getElementById('error').textContent='No decisions saved yet.';return}}const payload={{format:'s4_session_date_mapping_decisions_v1',exported_at:new Date().toISOString(),total_queue:ROWS.length,status_counts:ROWS.reduce((counts,row)=>{{counts[row.ledger.status_code]=(counts[row.ledger.status_code]||0)+1;return counts}},{{}}),decisions:decided.map(row=>({{session_date_key:row.session_date_key,ledger_status:row.ledger.status_code,evidence:row.ledger,...decisions[row.session_date_key]}}))}};const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}}));a.download={json.dumps(decisions_filename)};a.click()}}function clearStorage(){{if(confirm('Clear saved decisions?')){{decisions={{}};localStorage.removeItem(STORAGE_KEY);render()}}}}loadStorage();render();</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-per-status", type=int, default=None, help="Cap rows per ledger status for a stratified sample")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for --sample-per-status")
    args = parser.parse_args()

    ledger = load(LEDGER_DATASET)
    rows = queue_rows(ledger)
    if args.sample_per_status is not None:
        rows = stratified_sample(rows, args.sample_per_status, args.seed)
    payloads = build_payloads(ledger, load(ENRICHED_DATASET), load(FLAT_DATASET), load(AXIS_DATASET), rows=rows)
    output = Path(resolve(OUTPUT_DATASET))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(payloads, Path(resolve(DECISIONS_DATASET)).name), encoding="utf-8")
    print(f"Wrote {len(payloads)} review rows to {output}")


if __name__ == "__main__":
    main()
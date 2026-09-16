#!/usr/bin/env python3
"""Review and approve enriched↔flat entity bridges (place / org / person).

Builds a queue from daily tri-anchor inventories, serves an HTML reviewer, and
imports researcher decisions into ``approved_entity_bridges.json``.

Usage:
    uv run python entity_bridge_review.py --from-tri-anchors
    uv run python entity_bridge_review.py --import output/entity_bridge_approval_summary.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from build_alignment_new import OUTPUT_DIR, enriched_volgnr, load_json

ENTITY_TYPES = ("place", "org", "person")
APPROVED_BRIDGES_FILE = "approved_entity_bridges.json"
REJECTED_BRIDGES_FILE = "rejected_entity_bridges.json"
QUEUE_FILE = "entity_bridge_queue.json"
REVIEW_HTML = "verify_entity_bridge_review.html"
EXPORT_FILENAME = "entity_bridge_approval_summary.json"
APPROVAL_SCORE_BONUS = 5.0


def make_bridge_id(
    enriched_id: str,
    paragraph_id: str,
    entity_type: str,
    name: str,
) -> str:
    return f"{enriched_id}|{paragraph_id}|{entity_type}|{name}"


def parse_bridge_id(bridge_id: str) -> tuple[str, str, str, str]:
    enriched_id, paragraph_id, entity_type, name = bridge_id.split("|", 3)
    return enriched_id, paragraph_id, entity_type, name


def load_bridge_decisions(output_dir: Path) -> tuple[set[str], set[str]]:
    approved: set[str] = set()
    rejected: set[str] = set()
    approved_path = output_dir / APPROVED_BRIDGES_FILE
    rejected_path = output_dir / REJECTED_BRIDGES_FILE
    if approved_path.exists():
        payload = load_json(approved_path)
        for item in payload.get("bridges", []):
            bridge_id = str(item.get("bridge_id", ""))
            if bridge_id:
                approved.add(bridge_id)
    if rejected_path.exists():
        payload = load_json(rejected_path)
        for item in payload.get("bridges", []):
            bridge_id = str(item.get("bridge_id", ""))
            if bridge_id:
                rejected.add(bridge_id)
    return approved, rejected


def filtered_entity_names(
    names: set[str],
    enriched_id: str,
    paragraph_id: str,
    entity_type: str,
    rejected: set[str],
) -> set[str]:
    return {
        name
        for name in names
        if make_bridge_id(enriched_id, paragraph_id, entity_type, name) not in rejected
    }


def approval_bonus_for_pair(
    enriched_id: str,
    paragraph_id: str,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    approved: set[str],
    idf_weights: dict[str, float],
    *,
    bonus: float = APPROVAL_SCORE_BONUS,
) -> float:
    pair = (enriched_id, paragraph_id)
    total = 0.0
    for entity_type, lookup in (
        ("place", place_lookup),
        ("org", org_lookup),
        ("person", person_lookup),
    ):
        for name in lookup.get(pair, set()):
            if make_bridge_id(enriched_id, paragraph_id, entity_type, name) in approved:
                total += bonus
    return total


def build_entity_bridge_queue(
    anchors: dict[str, Any],
    *,
    place_lookup: dict[tuple[str, str], set[str]],
    org_lookup: dict[tuple[str, str], set[str]],
    person_lookup: dict[tuple[str, str], set[str]],
    paragraph_to_resolution: dict[str, str],
    enriched_by_date: dict[str, list[dict[str, Any]]] | None = None,
    idf_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Flatten overlap bridges per inventory-day into review tasks."""
    enriched_text: dict[str, str] = {}
    if enriched_by_date:
        for items in enriched_by_date.values():
            for item in items:
                volgnr = enriched_volgnr(item) or ""
                if volgnr:
                    enriched_text[volgnr] = str(item.get("text", ""))[:500]

    anchor_bridge_ids: set[str] = set()
    for day in anchors.values():
        for role in ("start", "middle", "end"):
            record = getattr(day, role, None) if not isinstance(day, dict) else day.get(role)
            if not record:
                continue
            bridge_tags = (
                record.get("bridge_tags", {})
                if isinstance(record, dict)
                else getattr(record, "bridge_tags", {})
            )
            enriched_id = record["enriched_id"] if isinstance(record, dict) else record.enriched_id
            paragraph_id = record["paragraph_id"] if isinstance(record, dict) else record.paragraph_id
            for entity_type, key in (("place", "places"), ("org", "orgs"), ("person", "persons")):
                for name in bridge_tags.get(key, []):
                    anchor_bridge_ids.add(make_bridge_id(enriched_id, paragraph_id, entity_type, name))

    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for day_key in sorted(anchors):
        day = anchors[day_key]
        inventory_id = day.inventory_id if hasattr(day, "inventory_id") else day["inventory_id"]
        calendar_date = day.calendar_date if hasattr(day, "calendar_date") else day["calendar_date"]
        enriched_tagged = (
            day.enriched_tagged if hasattr(day, "enriched_tagged") else day.get("enriched_tagged", [])
        )
        flat_tagged = day.flat_tagged if hasattr(day, "flat_tagged") else day.get("flat_tagged", [])
        enriched_ids = [row["enriched_id"] for row in enriched_tagged]
        paragraph_ids = [row["paragraph_id"] for row in flat_tagged]
        editorial_by_enriched = {
            row["enriched_id"]: row.get("editorial", {}) for row in enriched_tagged
        }
        flat_tags_by_paragraph = {
            row["paragraph_id"]: row.get("overlap_tags", {}) for row in flat_tagged
        }

        for enriched_id in enriched_ids:
            for paragraph_id in paragraph_ids:
                pair = (enriched_id, paragraph_id)
                resolution_id = paragraph_to_resolution.get(paragraph_id, "")
                for entity_type, lookup, editorial_key, flat_key in (
                    ("place", place_lookup, "places", "places"),
                    ("org", org_lookup, "orgs", "orgs"),
                    ("person", person_lookup, "persons", "persons"),
                ):
                    for name in sorted(lookup.get(pair, set())):
                        bridge_id = make_bridge_id(enriched_id, paragraph_id, entity_type, name)
                        if bridge_id in seen:
                            continue
                        seen.add(bridge_id)
                        anchor_score = 0.0
                        person_score = 0.0
                        combined_score = 0.0
                        if idf_weights is not None:
                            from build_alignment_new import score_typed_overlap

                            anchor_score, person_score, combined_score = score_typed_overlap(
                                enriched_id,
                                paragraph_id,
                                place_lookup,
                                org_lookup,
                                person_lookup,
                                idf_weights,
                            )
                        tasks.append(
                            {
                                "bridge_id": bridge_id,
                                "day_key": day_key,
                                "inventory_id": inventory_id,
                                "calendar_date": calendar_date,
                                "enriched_id": enriched_id,
                                "paragraph_id": paragraph_id,
                                "resolution_id": resolution_id,
                                "entity_type": entity_type,
                                "name": name,
                                "in_anchor": bridge_id in anchor_bridge_ids,
                                "anchor_score": round(anchor_score, 3),
                                "combined_score": round(combined_score, 3),
                                "editorial_enriched": sorted(
                                    editorial_by_enriched.get(enriched_id, {}).get(editorial_key, [])
                                ),
                                "overlap_flat": sorted(
                                    flat_tags_by_paragraph.get(paragraph_id, {}).get(flat_key, [])
                                ),
                                "enriched_preview": enriched_text.get(enriched_id, ""),
                            }
                        )

    tasks.sort(
        key=lambda item: (
            0 if item["in_anchor"] else 1,
            item["day_key"],
            item["enriched_id"],
            item["paragraph_id"],
            item["entity_type"],
            item["name"],
        )
    )
    return tasks


def write_entity_bridge_review_html(
    tasks: list[dict[str, Any]],
    output_path: Path,
    *,
    approved: set[str] | None = None,
    rejected: set[str] | None = None,
) -> None:
    approved = approved or set()
    rejected = rejected or set()
    payload = json.dumps(tasks, ensure_ascii=False)
    approved_json = json.dumps(sorted(approved), ensure_ascii=False)
    rejected_json = json.dumps(sorted(rejected), ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Entity bridge review</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 1100px; }}
.toolbar {{ display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }}
button {{ padding: 0.4rem 0.75rem; cursor: pointer; }}
button.approve {{ background: #def7e6; border: 1px solid #6fbf8a; }}
button.reject {{ background: #fde8e8; border: 1px solid #d88484; }}
button.active-approve {{ box-shadow: inset 0 0 0 2px #2f9e44; }}
button.active-reject {{ box-shadow: inset 0 0 0 2px #c92a2a; }}
.task {{ border: 1px solid #ddd; border-radius: 6px; padding: 0.75rem; margin: 0.75rem 0; }}
.meta {{ color: #555; font-size: 0.92rem; }}
.tags {{ font-size: 0.9rem; margin-top: 0.35rem; }}
.anchor-flag {{ color: #0b7285; font-weight: 600; }}
.preview {{ background: #f8f9fa; padding: 0.5rem; border-radius: 4px; margin-top: 0.35rem; font-size: 0.88rem; }}
.note {{ background: #fff9db; padding: 0.75rem; border-radius: 4px; }}
</style></head><body>
<h1>Approve entity bridges (place / org / person)</h1>
<p class="note"><b>Workflow:</b> Approve or reject each proposed name bridge between an enriched resolution and a flat paragraph.
Export → save <code>{EXPORT_FILENAME}</code> to <code>output/</code>, then run:
<pre style="margin:8px 0 0">uv run python entity_bridge_review.py --import output/{EXPORT_FILENAME}</pre></p>
<div class="toolbar">
  <button class="primary" onclick="exportDecisions()">Export decisions</button>
  <span id="stats"></span>
</div>
<div id="tasks"></div>
<script>
const TASKS = {payload};
const INITIAL_APPROVED = new Set({approved_json});
const INITIAL_REJECTED = new Set({rejected_json});
const decisions = {{}};

function loadInitial() {{
  INITIAL_APPROVED.forEach(id => decisions[id] = 'approved');
  INITIAL_REJECTED.forEach(id => decisions[id] = 'rejected');
}}

function tagList(label, values) {{
  if (!values || !values.length) return `<div class="tags"><b>${{label}}:</b> <em>none</em></div>`;
  return `<div class="tags"><b>${{label}}:</b> ${{values.map(v => `<code>${{v}}</code>`).join(', ')}}</div>`;
}}

function render() {{
  const root = document.getElementById('tasks');
  root.innerHTML = '';
  let approved = 0, rejected = 0, pending = 0;
  TASKS.forEach(task => {{
    const action = decisions[task.bridge_id] || 'pending';
    if (action === 'approved') approved++;
    else if (action === 'rejected') rejected++;
    else pending++;
    const anchor = task.in_anchor ? `<span class="anchor-flag">tri-anchor bridge</span> ` : '';
    const card = document.createElement('div');
    card.className = 'task';
    card.innerHTML = `
      <div class="meta">${{anchor}}<b>${{task.day_key}}</b> · ${{task.entity_type}} · <code>${{task.name}}</code></div>
      <div class="meta">enriched <code>${{task.enriched_id}}</code> ↔ paragraph <code>${{task.paragraph_id}}</code></div>
      <div class="meta">resolution <code>${{task.resolution_id}}</code> · combined score ${{task.combined_score}}</div>
      ${{tagList('Editorial (enriched)', task.editorial_enriched)}}
      ${{tagList('Overlap (flat paragraph)', task.overlap_flat)}}
      ${{task.enriched_preview ? `<div class="preview">${{task.enriched_preview}}</div>` : ''}}
      <div style="margin-top:0.5rem">
        <button class="approve ${{action === 'approved' ? 'active-approve' : ''}}" onclick="setDecision('${{task.bridge_id}}', 'approved')">Approve</button>
        <button class="reject ${{action === 'rejected' ? 'active-reject' : ''}}" onclick="setDecision('${{task.bridge_id}}', 'rejected')">Reject</button>
        <button onclick="setDecision('${{task.bridge_id}}', 'pending')">Clear</button>
      </div>`;
    root.appendChild(card);
  }});
  document.getElementById('stats').textContent =
    `${{approved}} approved · ${{rejected}} rejected · ${{pending}} pending · ${{TASKS.length}} total`;
}}

function setDecision(bridgeId, action) {{
  if (action === 'pending') delete decisions[bridgeId];
  else decisions[bridgeId] = action;
  render();
}}

function exportDecisions() {{
  const bridges = {{}};
  Object.entries(decisions).forEach(([bridgeId, action]) => {{
    if (action === 'pending') return;
    const task = TASKS.find(item => item.bridge_id === bridgeId) || {{}};
    bridges[bridgeId] = {{
      action,
      bridge_id: bridgeId,
      day_key: task.day_key || '',
      enriched_id: task.enriched_id || '',
      paragraph_id: task.paragraph_id || '',
      resolution_id: task.resolution_id || '',
      entity_type: task.entity_type || '',
      name: task.name || '',
      timestamp: new Date().toISOString(),
    }};
  }});
  const payload = {{
    exported_at: new Date().toISOString(),
    bridge_count: Object.keys(bridges).length,
    bridges,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '{EXPORT_FILENAME}';
  a.click();
}}

loadInitial();
render();
</script></body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def import_bridge_approvals(
    export_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    export = load_json(export_path)
    bridges_raw = export.get("bridges", {})
    if isinstance(bridges_raw, list):
        items = bridges_raw
    else:
        items = list(bridges_raw.values())

    approved_path = output_dir / APPROVED_BRIDGES_FILE
    rejected_path = output_dir / REJECTED_BRIDGES_FILE
    existing_approved = {item["bridge_id"]: item for item in load_json(approved_path).get("bridges", [])} if approved_path.exists() else {}
    existing_rejected = {item["bridge_id"]: item for item in load_json(rejected_path).get("bridges", [])} if rejected_path.exists() else {}

    counts = {"approved": 0, "rejected": 0, "skipped": 0}
    for item in items:
        action = str(item.get("action", ""))
        bridge_id = str(item.get("bridge_id", ""))
        if not bridge_id or action not in {"approved", "rejected"}:
            counts["skipped"] += 1
            continue
        record = {
            "bridge_id": bridge_id,
            "day_key": item.get("day_key", ""),
            "enriched_id": item.get("enriched_id", ""),
            "paragraph_id": item.get("paragraph_id", ""),
            "resolution_id": item.get("resolution_id", ""),
            "entity_type": item.get("entity_type", ""),
            "name": item.get("name", ""),
            "source": "entity_bridge_review",
            "timestamp": item.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        }
        if action == "approved":
            existing_approved[bridge_id] = record
            existing_rejected.pop(bridge_id, None)
            counts["approved"] += 1
        else:
            existing_rejected[bridge_id] = record
            existing_approved.pop(bridge_id, None)
            counts["rejected"] += 1

    stamp = datetime.now(timezone.utc).isoformat()
    approved_payload = {
        "version": 1,
        "updated_at": stamp,
        "bridge_count": len(existing_approved),
        "bridges": sorted(existing_approved.values(), key=lambda row: row["bridge_id"]),
    }
    rejected_payload = {
        "version": 1,
        "updated_at": stamp,
        "bridge_count": len(existing_rejected),
        "bridges": sorted(existing_rejected.values(), key=lambda row: row["bridge_id"]),
    }
    approved_path.write_text(json.dumps(approved_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    rejected_path.write_text(json.dumps(rejected_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "approved_total": len(existing_approved),
        "rejected_total": len(existing_rejected),
        **counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Entity bridge review and import")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--import", dest="import_path", type=Path, help="Import approval export JSON")
    parser.add_argument(
        "--from-tri-anchors",
        action="store_true",
        help="Rebuild queue + HTML from output/daily_tri_anchors.json",
    )
    parser.add_argument("--inventories", nargs="*", help="Filter queue to inventory ids")
    parser.add_argument("--dates", nargs="*", help="Filter queue to calendar dates")
    args = parser.parse_args()

    if args.import_path:
        summary = import_bridge_approvals(args.import_path, args.output_dir)
        print(f"Imported bridge decisions: {summary}")
        return

    if not args.from_tri_anchors:
        parser.error("Specify --from-tri-anchors or --import")

    from discover_session_tri_anchors import (
        DailyTriAnchors,
        discover_all_daily_tri_anchors,
        load_alignment_context,
    )

    tri_path = args.output_dir / "daily_tri_anchors.json"
    if tri_path.exists():
        tri_payload = load_json(tri_path)
        anchors = {
            key: DailyTriAnchors(
                inventory_id=value["inventory_id"],
                calendar_date=value["calendar_date"],
                enriched_count=value["enriched_count"],
                paragraph_count=value["paragraph_count"],
                complete=value["complete"],
                notes=value.get("notes", []),
                enriched_tagged=value.get("enriched_tagged", []),
                flat_tagged=value.get("flat_tagged", []),
            )
            for key, value in tri_payload.get("days", {}).items()
        }
        ctx = load_alignment_context(args.output_dir)
    else:
        ctx = load_alignment_context(args.output_dir)
        inventory_filter = set(args.inventories) if args.inventories else None
        date_filter = set(args.dates) if args.dates else None
        anchors = discover_all_daily_tri_anchors(
            ctx["date_to_sessions"],
            ctx["enriched_by_date"],
            ctx["places_df"],
            ctx["orgs_df"],
            ctx["persons_df"],
            ctx["paragraph_to_resolution"],
            ctx["res_df"],
            ctx["place_lookup"],
            ctx["org_lookup"],
            ctx["person_lookup"],
            ctx["idf_weights"],
            ctx["manual_pins"],
            ctx["loc_names"],
            ctx["per_names"],
            ctx["org_names"],
            ctx["state_pins"],
            inventory_filter=inventory_filter,
            date_filter=date_filter,
        )

    if args.inventories or args.dates:
        inv_filter = set(args.inventories or [])
        date_filter = set(args.dates or [])
        anchors = {
            key: day
            for key, day in anchors.items()
            if (not inv_filter or day.inventory_id in inv_filter)
            and (not date_filter or day.calendar_date in date_filter)
        }

    approved, rejected = load_bridge_decisions(args.output_dir)
    tasks = build_entity_bridge_queue(
        anchors,
        place_lookup=ctx["place_lookup"],
        org_lookup=ctx["org_lookup"],
        person_lookup=ctx["person_lookup"],
        paragraph_to_resolution=ctx["paragraph_to_resolution"],
        enriched_by_date=ctx["enriched_by_date"],
        idf_weights=ctx["idf_weights"],
    )
    queue_path = args.output_dir / QUEUE_FILE
    queue_path.write_text(
        json.dumps({"task_count": len(tasks), "tasks": tasks}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    html_path = args.output_dir / REVIEW_HTML
    write_entity_bridge_review_html(tasks, html_path, approved=approved, rejected=rejected)
    print(f"Bridge tasks: {len(tasks)} ({sum(1 for t in tasks if t['in_anchor'])} in tri-anchors)")
    print(f"Wrote {queue_path}")
    print(f"Wrote {html_path}")


if __name__ == "__main__":
    main()

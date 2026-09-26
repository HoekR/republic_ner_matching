#!/usr/bin/env python3
"""Render diagnostic calendar heatmaps for the session-date evidence ledger."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from data_io import load, resolve


LEDGER_DATASET = "session_date_status_1626_1630"
OUTPUT_DATASET = "session_date_status_1626_1630_heatmap"
STATUS_COLORS = {
    "T": "#276749",
    "A": "#975a16",
    "E": "#2563eb",
    "X": "#b45309",
    "N": "#9ca3af",
    "-1": "#0f766e",
    "+1": "#7c3aed",
    "?": "#be123c",
}


def _json_value(value: object) -> object:
    return value.tolist() if hasattr(value, "tolist") else value


def _tooltip(row: pd.Series) -> str:
    candidates = {
        "trusted": row["trusted_session_ids"],
        "exact": row["exact_date_session_ids"],
        "previous": row["previous_day_session_ids"],
        "next": row["next_day_session_ids"],
    }
    return "\n".join(
        (
            str(row["session_date_key"]),
            f"status: {row['status_code']} ({row['status_detail']})",
            f"trusted anchors: {row['trusted_anchor_count']}",
            f"fallback distance: {row['fallback_distance'] if pd.notna(row['fallback_distance']) else 'none'}",
            f"HTR paragraphs: {row['exact_date_paragraph_count']}",
            f"candidates: {json.dumps(candidates, ensure_ascii=True, default=_json_value)}",
        )
    )


def _calendar_panel(inventory_id: int, rows: pd.DataFrame) -> str:
    dates = pd.PeriodIndex(rows["enriched_date"], freq="D")
    start = dates.min().start_time.date()
    end = dates.max().start_time.date()
    days = pd.date_range(start, end, freq="D")
    by_date = {row.enriched_date: row for row in rows.itertuples(index=False)}
    first_weekday = days[0].weekday()
    cells = ['<span class="blank"></span>' for _ in range(first_weekday)]
    for day in days:
        date_text = day.strftime("%Y-%m-%d")
        row = by_date.get(date_text)
        if row is None:
            cells.append('<span class="empty"></span>')
            continue
        color = STATUS_COLORS[row.status_code]
        tooltip = _tooltip(pd.Series(row._asdict()))
        cells.append(
            f'<span class="day status-{html.escape(row.status_code)}" style="background:{color}" '
            f'title="{html.escape(tooltip)}">{day.day}<b>{html.escape(row.status_code)}</b></span>'
        )
    counts = Counter(rows["status_code"])
    count_text = " ".join(f"{status}: {counts.get(status, 0)}" for status in STATUS_COLORS)
    return f"""<section class=\"panel\"><h2>Inventory {inventory_id}</h2><p>{html.escape(count_text)}</p>
<div class=\"weekdays\"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span><span>Sun</span></div>
<div class=\"calendar\">{''.join(cells)}</div></section>"""


def render_heatmap(ledger: pd.DataFrame) -> str:
    required = {"inventory_id", "enriched_date", "status_code", "session_date_key", "trusted_anchor_count", "exact_date_paragraph_count", "fallback_distance", "status_detail", "trusted_session_ids", "exact_date_session_ids", "previous_day_session_ids", "next_day_session_ids"}
    missing = required.difference(ledger.columns)
    if missing:
        raise ValueError(f"Ledger lacks heatmap fields: {sorted(missing)}")
    panels = [_calendar_panel(int(inventory_id), rows) for inventory_id, rows in ledger.groupby("inventory_id", sort=True)]
    legend = "".join(f'<span><i style="background:{color}"></i>{html.escape(status)}</span>' for status, color in STATUS_COLORS.items())
    return f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Session-Date Status</title>
<style>:root{{font-family:Georgia,serif;color:#1f2937;background:#f5f3ed}}body{{margin:0}}main{{max-width:1440px;margin:auto;padding:24px}}h1,h2,p{{margin:0}}h1{{font-size:28px}}.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:16px 0 24px;font-family:ui-monospace,monospace}}.legend span{{display:flex;gap:5px;align-items:center}}.legend i{{width:14px;height:14px;display:inline-block}}.panels{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}}.panel{{border:1px solid #c9c5ba;background:#fff;padding:14px}}.panel h2{{font-size:18px}}.panel p{{font:12px ui-monospace,monospace;margin:6px 0 10px;color:#4b5563}}.weekdays,.calendar{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:3px}}.weekdays{{font:11px ui-monospace,monospace;color:#4b5563;margin-bottom:3px;text-align:center}}.day,.empty,.blank{{aspect-ratio:1;min-height:30px;box-sizing:border-box}}.day{{color:#fff;display:flex;flex-direction:column;justify-content:space-between;padding:3px;font:11px ui-monospace,monospace;cursor:help}}.day b{{font-size:13px;align-self:flex-end}}.empty{{background:#ece9df}}@media(max-width:480px){{main{{padding:14px}}.panels{{grid-template-columns:1fr}}.day{{min-height:38px}}}}</style></head>
<body><main><h1>Session-Date Evidence Status</h1><div class=\"legend\">{legend}</div><div class=\"panels\">{''.join(panels)}</div></main></body></html>"""


def main() -> None:
    ledger = load(LEDGER_DATASET)
    output = Path(resolve(OUTPUT_DATASET))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_heatmap(ledger), encoding="utf-8")
    print(f"Wrote {len(ledger)} ledger rows across {ledger['inventory_id'].nunique()} panels to {output}")


if __name__ == "__main__":
    main()
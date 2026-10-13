"""Disk-backed review notes / gold verdicts for the P5 axis viewer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOTES_PATH = PROJECT_ROOT / "output" / "p5_axis_viewer_notes.json"

# Gold-truth style day verdicts (hand review of P5 cuts / bindings).
VERDICTS: tuple[str, ...] = (
    "ok",
    "binding_wrong",
    "cuts_wrong",
    "mixed",
    "skip",
)
VERDICT_LABELS: dict[str, str] = {
    "ok": "ok — bindings and cuts look fine",
    "binding_wrong": "binding_wrong — summaries do not belong on this HTR",
    "cuts_wrong": "cuts_wrong — binding ok-ish, cut positions bad",
    "mixed": "mixed — some hosts ok, some not",
    "skip": "skip — not reviewable / come back later",
}


def notes_path() -> Path:
    try:
        from data_io import resolve

        return Path(resolve("p5_axis_viewer_notes"))
    except Exception:
        return DEFAULT_NOTES_PATH


def _empty() -> dict[str, Any]:
    return {
        "format": "p5_axis_day_review_v1",
        "updated_at": None,
        "days": {},
    }


def load_notes() -> dict[str, Any]:
    path = notes_path()
    if not path.exists():
        return _empty()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return _empty()
    base = _empty()
    base["days"] = data.get("days") if isinstance(data.get("days"), dict) else {}
    base["updated_at"] = data.get("updated_at")
    base["format"] = data.get("format") or base["format"]
    return base


def save_notes(payload: dict[str, Any]) -> Path:
    path = notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["format"] = "p5_axis_day_review_v1"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def day_notes(notes: dict[str, Any], date: str) -> dict[str, Any]:
    block = (notes.get("days") or {}).get(str(date)[:10]) or {}
    verdict = str(block.get("verdict") or "")
    if verdict not in VERDICTS:
        verdict = ""
    return {
        "day_notes": str(block.get("day_notes") or ""),
        "hosts": dict(block.get("hosts") or {}),
        "verdict": verdict,
        "labelled": bool(block.get("labelled")),
        "labelled_at": block.get("labelled_at"),
    }


def update_day_notes(
    notes: dict[str, Any],
    date: str,
    *,
    day_notes_text: str | None = None,
    host_notes: dict[str, str] | None = None,
    verdict: str | None = None,
    labelled: bool | None = None,
) -> dict[str, Any]:
    """Merge notes / gold verdict for one date. ``host_notes`` keys are axis_id."""
    days = dict(notes.get("days") or {})
    key = str(date)[:10]
    block = dict(days.get(key) or {})
    if day_notes_text is not None:
        block["day_notes"] = str(day_notes_text)
    hosts = dict(block.get("hosts") or {})
    if host_notes is not None:
        for axis_id, text in host_notes.items():
            aid = str(axis_id)
            value = str(text or "").strip()
            if value:
                hosts[aid] = value
            elif aid in hosts:
                del hosts[aid]
        block["hosts"] = hosts
    if verdict is not None:
        verdict_s = str(verdict).strip()
        if verdict_s and verdict_s not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict_s!r}; expected one of {VERDICTS}")
        block["verdict"] = verdict_s
    if labelled is not None:
        block["labelled"] = bool(labelled)
        if labelled:
            block["labelled_at"] = datetime.now(timezone.utc).isoformat()
    days[key] = block
    notes = dict(notes)
    notes["days"] = days
    return notes


def review_stats(sample_dates: Sequence[str], notes: dict[str, Any]) -> dict[str, int]:
    """Gold-style progress over a fixed sample window."""
    total = len(sample_dates)
    labelled = 0
    for date in sample_dates:
        block = day_notes(notes, date)
        if block.get("labelled") and block.get("verdict"):
            labelled += 1
    return {"labelled": labelled, "total": total, "remaining": total - labelled}


def next_unlabelled_date(
    sample_dates: Sequence[str],
    notes: dict[str, Any],
) -> str | None:
    for date in sample_dates:
        block = day_notes(notes, str(date))
        if not (block.get("labelled") and block.get("verdict")):
            return str(date)[:10]
    return None

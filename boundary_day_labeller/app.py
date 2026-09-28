"""Flask UI for session-day boundary gold (hard-period sample).

Disk-backed like trifecta ``gold_labeller`` / ``lumped_paragraph_labeller``.
Supports CUT, END, START RES, DATE_END, DATE_START markers.

Usage:
    uv run python scripts/build_hard_period_boundary_sample.py   # once
    uv run boundary-day-gold-ui
    # http://127.0.0.1:5056
    uv run python merge_boundary_annotations.py \\
      --sample output/boundary_gold_hard_period_sample.json \\
      --annotations output/boundary_gold_hard_period_annotations.json \\
      --annotator YOUR_NAME
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from build_alignment_new import OUTPUT_DIR, load_data
from build_boundary_annotation_ui import (
    MARKER,
    MARKER_DATE_END,
    MARKER_DATE_START,
    MARKER_END,
    MARKER_START,
    SEPARATOR,
    flat_paragraph_stream,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 5056
DEFAULT_SAMPLE = OUTPUT_DIR / "boundary_gold_hard_period_sample.json"
DEFAULT_ANNOTATIONS = OUTPUT_DIR / "boundary_gold_hard_period_annotations.json"


def _empty_state() -> dict[str, Any]:
    return {
        "format": "boundary_day_gold_annotations_v1",
        "marker": MARKER,
        "marker_end": MARKER_END,
        "marker_start": MARKER_START,
        "marker_date_end": MARKER_DATE_END,
        "marker_date_start": MARKER_DATE_START,
        "separator": SEPARATOR,
        "updated_at": None,
        "annotations": {},
    }


def load_sample(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    base = _empty_state()
    base.update({k: data.get(k, base[k]) for k in base})
    anns = data.get("annotations") or {}
    base["annotations"] = anns if isinstance(anns, dict) else {}
    return base


def save_state(state: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(state)
    out["updated_at"] = datetime.now(timezone.utc).isoformat()
    out["format"] = "boundary_day_gold_annotations_v1"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def count_marker(text: str, marker: str) -> int:
    return len(str(text or "").split(marker)) - 1


def resolution_transitions(text: str) -> int:
    return count_marker(text, MARKER) + count_marker(text, MARKER_START)


def is_labelled(ann: dict[str, Any] | None) -> bool:
    return bool(ann and ann.get("labelled"))


def create_app(
    *,
    sample_path: Path | None = None,
    annotations_path: Path | None = None,
) -> Flask:
    sample_path = Path(sample_path or DEFAULT_SAMPLE)
    annotations_path = Path(annotations_path or DEFAULT_ANNOTATIONS)

    app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
    app.config["SAMPLE_PATH"] = str(sample_path)
    app.config["ANNOTATIONS_PATH"] = str(annotations_path)

    # Heavy load once at startup.
    sample = load_sample(sample_path)
    _, res_df, *_ = load_data()
    days: list[dict[str, Any]] = []
    for day in sample.get("days") or []:
        paragraphs = flat_paragraph_stream(res_df, day["flat_ids"])
        base_text = SEPARATOR.join(p["text"] for p in paragraphs)
        days.append(
            {
                **day,
                "paragraphs": paragraphs,
                "base_text": base_text,
                "n_paragraphs": len(paragraphs),
            }
        )
    app.config["DAYS"] = days
    by_date = {str(d["date"])[:10]: d for d in days}
    app.config["BY_DATE"] = by_date

    def _state() -> dict[str, Any]:
        return load_state(Path(app.config["ANNOTATIONS_PATH"]))

    def _stats(state: dict[str, Any]) -> dict[str, int]:
        anns = state.get("annotations") or {}
        labelled = sum(1 for d in days if is_labelled(anns.get(str(d["date"])[:10])))
        return {"total": len(days), "labelled": labelled, "pending": len(days) - labelled}

    def _row(date: str, state: dict[str, Any]) -> dict[str, Any]:
        day = by_date[date]
        ann = (state.get("annotations") or {}).get(date) or {}
        text = str(ann.get("text") if ann.get("text") is not None else day["base_text"])
        return {
            **day,
            "text": text,
            "startsMid": bool(ann.get("startsMid")),
            "notes": str(ann.get("notes") or ""),
            "labelled": is_labelled(ann),
            "n_transitions": resolution_transitions(text),
            "n_date_markers": count_marker(text, MARKER_DATE_END) + count_marker(text, MARKER_DATE_START),
            "needed": int(day["k_e"]) - 1,
        }

    @app.get("/")
    def index():
        if not days:
            return "<p>No days in sample.</p>", 404
        state = _state()
        anns = state.get("annotations") or {}
        nxt = next((str(d["date"])[:10] for d in days if not is_labelled(anns.get(str(d["date"])[:10]))), None)
        return redirect(url_for("label_day", date=nxt or str(days[0]["date"])[:10]))

    @app.get("/label/<date>")
    def label_day(date: str):
        date = str(date)[:10]
        if date not in by_date:
            abort(404)
        state = _state()
        dates = [str(d["date"])[:10] for d in days]
        idx = dates.index(date)
        row = _row(date, state)
        return render_template(
            "label.html",
            row=row,
            index=idx,
            prev_id=dates[idx - 1] if idx else None,
            next_id=dates[idx + 1] if idx + 1 < len(dates) else None,
            stats=_stats(state),
            markers={
                "cut": MARKER,
                "end": MARKER_END,
                "start": MARKER_START,
                "date_end": MARKER_DATE_END,
                "date_start": MARKER_DATE_START,
            },
            state_file=app.config["ANNOTATIONS_PATH"],
            cuts_ok=row["n_transitions"] == row["needed"],
        )

    @app.get("/api/stats")
    def api_stats():
        return jsonify(_stats(_state()))

    @app.post("/api/save/<date>")
    def api_save(date: str):
        date = str(date)[:10]
        if date not in by_date:
            abort(404)
        payload = request.get_json(silent=True) or {}
        state = _state()
        anns = dict(state.get("annotations") or {})
        anns[date] = {
            "text": str(payload.get("text") if payload.get("text") is not None else by_date[date]["base_text"]),
            "startsMid": bool(payload.get("startsMid")),
            "notes": str(payload.get("notes") or ""),
            "labelled": True if "labelled" not in payload else bool(payload.get("labelled")),
        }
        state["annotations"] = anns
        path = save_state(state, Path(app.config["ANNOTATIONS_PATH"]))
        row = _row(date, state)
        return jsonify({"ok": True, "path": str(path), "row": {"date": date, **{k: row[k] for k in ("labelled", "n_transitions", "needed", "n_date_markers")}}, "stats": _stats(state), "updated_at": state.get("updated_at")})

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Session-day boundary gold UI (hard-period sample)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not args.sample.exists():
        raise SystemExit(
            f"Sample not found: {args.sample}\n"
            "Run: uv run python scripts/build_hard_period_boundary_sample.py"
        )

    app = create_app(sample_path=args.sample, annotations_path=args.annotations)
    print(f"Sample: {args.sample}")
    print(f"Persisting to {args.annotations}")
    print(f"Open http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=args.debug or bool(os.environ.get("FLASK_DEBUG")))


if __name__ == "__main__":
    main()

"""Flask app for lumped-paragraph mid-cut gold labelling.

Mirrors ``trifecta-annotation/gold_labeller``: Jinja templates, POST /api/save/<id>,
disk persistence (JSON) on every save.

Usage:
    uv run python scripts/build_lumped_paragraph_gold_scaffold.py   # once
    uv run lumped-paragraph-gold-ui
    # open http://127.0.0.1:5055
    uv run python scripts/merge_lumped_paragraph_annotations.py --annotator YOUR_NAME
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from lumped_paragraph_labeller.store import (
    MARKER,
    VERDICTS,
    annotations_path,
    count_cuts,
    load_annotations,
    load_candidates,
    merge_row,
    next_unlabelled_id,
    record_index,
    save_annotations,
    stats,
    update_annotation,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 5055


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )

    def _candidates():
        return load_candidates()

    def _annotations():
        return load_annotations()

    @app.get("/")
    def index():
        candidates = _candidates()
        if not candidates:
            return (
                "<p>No scaffold candidates. Run "
                "<code>uv run python scripts/build_lumped_paragraph_gold_scaffold.py</code></p>",
                404,
            )
        ann = _annotations()
        example_id = next_unlabelled_id(candidates, ann) or str(candidates[0]["example_id"])
        return redirect(url_for("label_record", example_id=example_id))

    @app.get("/label/<path:example_id>")
    def label_record(example_id: str):
        candidates = _candidates()
        ann = _annotations()
        try:
            idx = record_index(candidates, example_id)
        except KeyError:
            abort(404)
        candidate = candidates[idx]
        row = merge_row(candidate, (ann.get("annotations") or {}).get(example_id))
        prev_id = str(candidates[idx - 1]["example_id"]) if idx > 0 else None
        next_id = str(candidates[idx + 1]["example_id"]) if idx + 1 < len(candidates) else None
        st = stats(candidates, ann)
        n_cuts = count_cuts(str(row.get("text") or ""))
        expected = int(row.get("expected_cuts") or 0)
        verdict = str(row.get("verdict") or "cuts")
        cuts_ok = verdict != "cuts" or n_cuts == expected
        return render_template(
            "label.html",
            row=row,
            index=idx,
            prev_id=prev_id,
            next_id=next_id,
            stats=st,
            marker=MARKER,
            n_cuts=n_cuts,
            expected_cuts=expected,
            cuts_ok=cuts_ok,
            verdict=verdict,
            verdicts=VERDICTS,
            state_file=str(annotations_path()),
        )

    @app.get("/api/stats")
    def api_stats():
        return jsonify(stats(_candidates(), _annotations()))

    @app.post("/api/save/<path:example_id>")
    def api_save(example_id: str):
        candidates = _candidates()
        payload = request.get_json(silent=True) or {}
        try:
            updated = update_annotation(_annotations(), example_id, payload, candidates=candidates)
        except KeyError:
            abort(404)
        path = save_annotations(updated)
        row = merge_row(
            next(c for c in candidates if str(c["example_id"]) == example_id),
            (updated.get("annotations") or {}).get(example_id),
        )
        return jsonify(
            {
                "ok": True,
                "path": str(path),
                "row": row,
                "stats": stats(candidates, updated),
                "updated_at": updated.get("updated_at"),
            }
        )

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Lumped-paragraph gold labelling web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    print(f"Persisting to {annotations_path()}")
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug or bool(os.environ.get("FLASK_DEBUG")),
    )


if __name__ == "__main__":
    main()

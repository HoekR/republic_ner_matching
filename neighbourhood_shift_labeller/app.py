"""Flask UI for neighbourhood session-shift hand gold.

Label ``correct_session`` by content (baseline vs competitor hint, or other).
Not a dating verdict. Persists into ``neighbourhood_shift_gold``.

Usage:
    uv run python -m sequence_graph.fingerprint_session_shift --scaffold-neighbourhood-gold --write
    uv run neighbourhood-shift-gold-ui
    # http://127.0.0.1:5057
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from sequence_graph.align import build_entity_overlap_scorer
from sequence_graph.fingerprint_session_shift import (
    NEIGHBOURHOOD_GOLD_DATASET,
    _enriched_text_by_volgnr,
    _flat_text_by_id,
    _flats_for_session,
    score_volgnr_against_flats,
    session_num,
)
from sequence_graph.resolution_fingerprint_eval import fit_fingerprint_on_tier1
from sequence_graph.sync_gap_align import _axis_by_inv_sess

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 5057
SESSION_RE = re.compile(r"^session-\d+-num-\d+$")
SNIPPET = 320


def _is_labelled(row: dict[str, Any]) -> bool:
    if row.get("label_status") == "not_found":
        return True
    correct = row.get("correct_session")
    return bool(isinstance(correct, str) and correct.startswith("session-"))


class MatchContext:
    """Best-in-session HTR flat for an enriched text (not session opening)."""

    def __init__(self) -> None:
        print("Loading match context (axis + fingerprint)…")
        self.axis = _axis_by_inv_sess()
        self.flat_texts = _flat_text_by_id()
        self.enr_text = _enriched_text_by_volgnr()
        self.fingerprint, _meta = fit_fingerprint_on_tier1(exclude_dates=None)
        self.entity_scorer = build_entity_overlap_scorer()
        print("Match context ready.")

    def best_in_session(
        self,
        volgnr: str,
        session_id: str,
        *,
        enriched_fallback: str = "",
    ) -> dict[str, Any]:
        flats = _flats_for_session(session_id, self.axis)
        text = self.enr_text.get(volgnr) or enriched_fallback or ""
        if not flats or not text.strip():
            return {
                "flat_id": None,
                "score": None,
                "snippet": "",
                "n_flats": len(flats),
            }
        ranked = score_volgnr_against_flats(
            volgnr,
            text,
            flats,
            self.flat_texts,
            fingerprint=self.fingerprint,
            entity_scorer=self.entity_scorer,
        )
        best_flat, best_score = ranked[0]
        return {
            "flat_id": best_flat,
            "score": round(float(best_score), 4),
            "snippet": (self.flat_texts.get(best_flat) or "")[:SNIPPET],
            "n_flats": len(flats),
        }

    def card_view(self, row: dict[str, Any]) -> dict[str, Any]:
        """Augment a gold_label row with best-match foils (openings demoted)."""
        volgnr = str(row.get("volgnr") or "")
        baseline = str(row.get("baseline_session") or "")
        competitor = str(row.get("competitor_session") or "")
        fallback = str(row.get("enriched_snippet") or "")
        full = self.enr_text.get(volgnr) or fallback
        base_hit = self.best_in_session(volgnr, baseline, enriched_fallback=fallback)
        comp_hit = self.best_in_session(volgnr, competitor, enriched_fallback=fallback)
        return {
            **row,
            "enriched_full_snippet": full[:SNIPPET],
            "baseline_best_flat": base_hit["flat_id"],
            "baseline_best_score": base_hit["score"],
            "baseline_best_snippet": base_hit["snippet"],
            "baseline_n_flats": base_hit["n_flats"],
            "competitor_best_flat": comp_hit["flat_id"],
            "competitor_best_score": comp_hit["score"],
            "competitor_best_snippet": comp_hit["snippet"],
            "competitor_n_flats": comp_hit["n_flats"],
        }


def _load_rows() -> list[dict[str, Any]]:
    try:
        raw = list(load(NEIGHBOURHOOD_GOLD_DATASET))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"{NEIGHBOURHOOD_GOLD_DATASET} missing — run "
            "uv run python -m sequence_graph.fingerprint_session_shift "
            "--scaffold-neighbourhood-gold --write"
        ) from exc
    return raw


def _candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("record_type") == "gold_label" and r.get("volgnr")]


def _review_id(row: dict[str, Any]) -> str:
    return f"neigh:{row.get('inventory')}:{row.get('volgnr')}"


def _persist(rows: list[dict[str, Any]]) -> None:
    meta = next((r for r in rows if r.get("record_type") == "meta"), None)
    cands = _candidates(rows)
    labelled = sum(1 for r in cands if _is_labelled(r))
    if meta is not None:
        meta["n_candidates"] = len(cands)
        meta["n_labelled"] = labelled
        meta["ui_saved_at"] = datetime.now(timezone.utc).isoformat()
    save_semi_structured(
        rows,
        logical_name=NEIGHBOURHOOD_GOLD_DATASET,
        script=__file__,
        description=(
            "Thin hand gold for date-free ALIGNED_TO session-shift "
            "(labelled via neighbourhood-shift-gold-ui)."
        ),
        parent_sources=["hard_recalibrate_proof", "paragraph_axis_1626_1630"],
    )


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
    rows = _load_rows()
    cands = _candidates(rows)
    if not cands:
        raise SystemExit(f"no gold_label candidates in {NEIGHBOURHOOD_GOLD_DATASET}")
    app.config["ROWS"] = rows
    app.config["CANDIDATES"] = cands
    by_id = {_review_id(r): r for r in cands}
    app.config["BY_ID"] = by_id
    ids = [_review_id(r) for r in cands]
    app.config["IDS"] = ids
    app.config["MATCH"] = MatchContext()

    def _stats() -> dict[str, int]:
        labelled = sum(1 for r in app.config["CANDIDATES"] if _is_labelled(r))
        total = len(app.config["CANDIDATES"])
        return {"total": total, "labelled": labelled, "pending": total - labelled}

    @app.get("/")
    def index():
        ids = app.config["IDS"]
        by_id = app.config["BY_ID"]
        nxt = next((i for i in ids if not _is_labelled(by_id[i])), None)
        return redirect(url_for("label_card", review_id=nxt or ids[0]))

    @app.get("/label/<path:review_id>")
    def label_card(review_id: str):
        by_id = app.config["BY_ID"]
        if review_id not in by_id:
            abort(404)
        ids = app.config["IDS"]
        idx = ids.index(review_id)
        raw = by_id[review_id]
        row = app.config["MATCH"].card_view(raw)
        return render_template(
            "label.html",
            row=row,
            review_id=review_id,
            labelled=_is_labelled(raw),
            index=idx,
            prev_id=ids[idx - 1] if idx else None,
            next_id=ids[idx + 1] if idx + 1 < len(ids) else None,
            stats=_stats(),
        )

    @app.get("/api/stats")
    def api_stats():
        return jsonify(_stats())

    @app.post("/api/save/<path:review_id>")
    def api_save(review_id: str):
        by_id = app.config["BY_ID"]
        if review_id not in by_id:
            abort(404)
        payload = request.get_json(silent=True) or {}
        choice = str(payload.get("choice") or "")
        other = str(payload.get("other_session") or "").strip()
        note = str(payload.get("note") or "")
        row = by_id[review_id]
        baseline = str(row.get("baseline_session") or "")
        competitor = str(row.get("competitor_session") or "")

        if choice == "baseline":
            correct = baseline
            status = "found"
        elif choice == "competitor":
            correct = competitor
            status = "found"
        elif choice == "other":
            correct = other
            if not SESSION_RE.match(correct):
                return jsonify({"ok": False, "error": "other_session must look like session-3185-num-150"}), 400
            status = "found"
        elif choice == "not_found":
            correct = None
            status = "not_found"
        elif choice == "clear":
            correct = None
            status = None
        else:
            return jsonify({
                "ok": False,
                "error": "choice must be baseline|competitor|other|not_found|clear",
            }), 400

        row["correct_session"] = correct
        row["note"] = note
        if status == "not_found":
            row["label_status"] = "not_found"
            row["needs_split"] = False
            row["labeled"] = True
        elif correct:
            split = "split" in note.lower()
            row["label_status"] = "found_needs_split" if split else "found"
            row["needs_split"] = split
            row["labeled"] = True
        else:
            row["label_status"] = None
            row["needs_split"] = False
            row["labeled"] = False
        b_num = session_num(baseline)
        c_num = session_num(correct) if correct else None
        row["delta"] = (
            (c_num - b_num) if b_num is not None and c_num is not None else row.get("delta")
        )
        row["labelled_at"] = datetime.now(timezone.utc).isoformat()
        row["labelled_via"] = "neighbourhood-shift-gold-ui"

        _persist(app.config["ROWS"])
        stats = _stats()
        ids = app.config["IDS"]
        idx = ids.index(review_id)
        next_id = None
        for j in range(idx + 1, len(ids)):
            if not _is_labelled(by_id[ids[j]]):
                next_id = ids[j]
                break
        if next_id is None:
            next_id = next((i for i in ids if not _is_labelled(by_id[i])), None)
        return jsonify({
            "ok": True,
            "review_id": review_id,
            "correct_session": correct,
            "labelled": bool(correct),
            "stats": stats,
            "next_id": next_id,
        })

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Neighbourhood session-shift hand gold UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    print(f"Dataset: {NEIGHBOURHOOD_GOLD_DATASET}")
    print(f"Open http://{args.host}:{args.port}/")
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug or bool(os.environ.get("FLASK_DEBUG")),
    )


if __name__ == "__main__":
    main()

"""Flask read-only viewer for P5 gated axis successor.

Usage:
    uv run p5-axis-viewer
    # http://127.0.0.1:5059
    # ?filter=accepted|rejected|all  (default accepted)
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from p5_axis_viewer.notes import (
    VERDICT_LABELS,
    VERDICTS,
    day_notes,
    load_notes,
    next_unlabelled_date,
    notes_path,
    review_stats,
    save_notes,
    update_day_notes,
)
from p5_axis_viewer.store import (
    FilterMode,
    day_context,
    day_index,
    day_resolutions,
    day_shifted_resolutions,
    host_views,
    list_days,
    list_days_in_range,
    stats,
    summary,
    tier_day_payload,
    unplaced_resolutions,
    unsplit_resolutions,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 5059
FILTERS: tuple[FilterMode, ...] = (
    "corpus",
    "accepted",
    "rejected",
    "all",
    "suspect",
)


def _mode() -> FilterMode:
    raw = str(request.args.get("filter") or "corpus").strip().lower()
    if raw not in FILTERS:
        return "corpus"
    return raw  # type: ignore[return-value]


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )

    @app.get("/")
    def index():
        mode = _mode()
        days = list_days(mode=mode)
        if not days:
            return (
                "<p>No days for this filter. For ledger filters, run "
                "<code>uv run python -m scripts.s6c_p5_persist_axis_successor</code>; "
                "for corpus, check concordance scope.</p>",
                404,
            )
        return redirect(
            url_for("day_view", date=str(days[0]["enriched_date"]), filter=mode)
        )

    @app.get("/range")
    def range_index():
        """Hand-review index for an inclusive date window."""
        mode = _mode()
        start = str(request.args.get("from") or request.args.get("start") or "").strip()[:10]
        end = str(request.args.get("to") or request.args.get("end") or start).strip()[:10]
        if not start or not start[0].isdigit():
            return (
                "<p>Usage: <code>/range?from=1629-02-05&amp;to=1629-02-10&amp;filter=corpus</code></p>",
                400,
            )
        if not end or not end[0].isdigit():
            end = start
        days = list_days_in_range(start, end, mode=mode)
        if not days and mode != "corpus":
            days = list_days_in_range(start, end, mode="corpus")
            mode = "corpus"
        return render_template(
            "range.html",
            days=days,
            start=min(start, end),
            end=max(start, end),
            mode=mode,
            filters=FILTERS,
            stats=stats(mode),
        )

    @app.get("/day/<date>")
    def day_view(date: str):
        mode = _mode()
        range_from = str(request.args.get("from") or "").strip()[:10] or None
        range_to = str(request.args.get("to") or "").strip()[:10] or None
        if range_from and range_to:
            days = list_days_in_range(range_from, range_to, mode=mode)
            if not days:
                days = list_days_in_range(range_from, range_to, mode="corpus")
                mode = "corpus"
        else:
            days = list_days(mode=mode)
        if not days:
            abort(404)
        try:
            idx = day_index(days, date)
        except KeyError:
            # Date not in current filter — fall back to full corpus calendar.
            days_all = list_days(mode="corpus")
            try:
                day_index(days_all, date)
            except KeyError:
                abort(404)
            return redirect(url_for("day_view", date=date, filter="corpus"))
        day = days[idx]
        prev_date = str(days[idx - 1]["enriched_date"]) if idx > 0 else None
        next_date = str(days[idx + 1]["enriched_date"]) if idx + 1 < len(days) else None
        date = str(day["enriched_date"])
        resolutions = day_resolutions(date)
        hosts = host_views(day, resolutions)
        ctx = day_context(date, resolutions)
        ctx["n_content_suspect_hosts"] = sum(
            1 for h in hosts if h.get("content_suspect")
        )
        ctx["day_suspect"] = bool(day.get("day_accepted")) and ctx[
            "n_content_suspect_hosts"
        ] > 0
        notes = day_notes(load_notes(), date)
        for host in hosts:
            host["review_notes"] = (notes.get("hosts") or {}).get(
                str(host.get("axis_id") or ""), ""
            )
        return render_template(
            "day.html",
            day=day,
            context=ctx,
            hosts=hosts,
            unsplit=unsplit_resolutions(day, resolutions),
            shifted=day_shifted_resolutions(day, resolutions),
            unplaced=unplaced_resolutions(day, resolutions),
            index=idx,
            prev_date=prev_date,
            next_date=next_date,
            mode=mode,
            filters=FILTERS,
            stats=stats(mode),
            summary=summary(),
            day_notes_text=notes.get("day_notes") or "",
            notes_file=str(notes_path()),
            range_from=range_from,
            range_to=range_to,
        )

    def _range_args() -> tuple[str | None, str | None]:
        range_from = str(request.args.get("from") or "").strip()[:10] or None
        range_to = str(request.args.get("to") or "").strip()[:10] or None
        return range_from, range_to

    def _sample_days(range_from: str, range_to: str) -> list[dict]:
        days = list_days_in_range(range_from, range_to, mode="corpus")
        return days

    @app.get("/tier/<date>")
    def tier_day(date: str):
        """Three same-day evidence tiers with cross-tier edges (hover = text)."""
        range_from, range_to = _range_args()
        mode = "corpus"
        if range_from and range_to:
            days = list_days_in_range(range_from, range_to, mode=mode)
        else:
            days = list_days(mode=mode)
        if not days:
            abort(404)
        try:
            idx = day_index(days, date)
        except KeyError:
            abort(404)
        day = days[idx]
        date = str(day["enriched_date"])
        prev_date = str(days[idx - 1]["enriched_date"]) if idx > 0 else None
        next_date = str(days[idx + 1]["enriched_date"]) if idx + 1 < len(days) else None
        payload = tier_day_payload(date)
        return render_template(
            "tier.html",
            payload=payload,
            index=idx,
            prev_date=prev_date,
            next_date=next_date,
            range_from=range_from,
            range_to=range_to,
            stats=stats("corpus"),
        )

    @app.get("/review")
    def review_start():
        """Jump to first unlabelled day in the sample window (gold queue)."""
        range_from, range_to = _range_args()
        if not range_from or not range_to:
            return (
                "<p>Usage: <code>/review?from=1629-02-05&amp;to=1629-02-10</code></p>",
                400,
            )
        days = _sample_days(range_from, range_to)
        if not days:
            abort(404)
        sample = [str(d["enriched_date"]) for d in days]
        target = next_unlabelled_date(sample, load_notes()) or sample[0]
        return redirect(
            url_for(
                "review_day",
                date=target,
                **{"from": range_from, "to": range_to},
            )
        )

    @app.get("/review/<date>")
    def review_day(date: str):
        """Gold-truth style one-day review with Save & next."""
        range_from, range_to = _range_args()
        if not range_from or not range_to:
            range_from = date[:10]
            range_to = date[:10]
        days = _sample_days(range_from, range_to)
        if not days:
            abort(404)
        try:
            idx = day_index(days, date)
        except KeyError:
            abort(404)
        day = days[idx]
        date = str(day["enriched_date"])
        prev_date = str(days[idx - 1]["enriched_date"]) if idx > 0 else None
        next_date = str(days[idx + 1]["enriched_date"]) if idx + 1 < len(days) else None
        sample = [str(d["enriched_date"]) for d in days]
        notes_all = load_notes()
        review = day_notes(notes_all, date)
        resolutions = day_resolutions(date)
        hosts = host_views(day, resolutions)
        for host in hosts:
            host["review_notes"] = (review.get("hosts") or {}).get(
                str(host.get("axis_id") or ""), ""
            )
        ctx = day_context(date, resolutions)
        ctx["n_content_suspect_hosts"] = sum(
            1 for h in hosts if h.get("content_suspect")
        )
        ctx["day_suspect"] = bool(day.get("day_accepted")) and ctx[
            "n_content_suspect_hosts"
        ] > 0
        rstats = review_stats(sample, notes_all)
        return render_template(
            "review.html",
            day=day,
            context=ctx,
            hosts=hosts,
            unsplit=unsplit_resolutions(day, resolutions),
            review=review,
            index=idx,
            prev_date=prev_date,
            next_date=next_date,
            next_unlabelled=next_unlabelled_date(sample, notes_all),
            range_from=range_from,
            range_to=range_to,
            review_stats=rstats,
            verdicts=VERDICTS,
            verdict_labels=VERDICT_LABELS,
            notes_file=str(notes_path()),
            stats=stats("corpus"),
        )

    @app.post("/api/notes/<date>")
    def api_notes(date: str):
        payload = request.get_json(silent=True) or {}
        host_notes = payload.get("hosts")
        if host_notes is not None and not isinstance(host_notes, dict):
            return jsonify({"ok": False, "error": "hosts must be an object"}), 400
        try:
            updated = update_day_notes(
                load_notes(),
                date,
                day_notes_text=payload.get("day_notes"),
                host_notes={str(k): str(v) for k, v in (host_notes or {}).items()},
                verdict=payload.get("verdict"),
                labelled=payload.get("labelled"),
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        path = save_notes(updated)
        return jsonify(
            {
                "ok": True,
                "path": str(path),
                "notes": day_notes(updated, date),
                "updated_at": updated.get("updated_at"),
            }
        )

    @app.post("/api/review/<date>")
    def api_review(date: str):
        """Persist gold verdict + notes; return next unlabelled in window."""
        payload = request.get_json(silent=True) or {}
        host_notes = payload.get("hosts")
        if host_notes is not None and not isinstance(host_notes, dict):
            return jsonify({"ok": False, "error": "hosts must be an object"}), 400
        verdict = payload.get("verdict")
        if not verdict:
            return jsonify({"ok": False, "error": "verdict required"}), 400
        try:
            updated = update_day_notes(
                load_notes(),
                date,
                day_notes_text=payload.get("day_notes"),
                host_notes={str(k): str(v) for k, v in (host_notes or {}).items()},
                verdict=str(verdict),
                labelled=True if payload.get("labelled", True) else False,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        path = save_notes(updated)
        range_from = str(payload.get("from") or request.args.get("from") or "").strip()[:10]
        range_to = str(payload.get("to") or request.args.get("to") or "").strip()[:10]
        sample: list[str] = []
        nxt = None
        rstats = {"labelled": 0, "total": 0, "remaining": 0}
        if range_from and range_to:
            sample = [
                str(d["enriched_date"]) for d in _sample_days(range_from, range_to)
            ]
            nxt = next_unlabelled_date(sample, updated)
            rstats = review_stats(sample, updated)
        return jsonify(
            {
                "ok": True,
                "path": str(path),
                "notes": day_notes(updated, date),
                "next_unlabelled": nxt,
                "review_stats": rstats,
                "updated_at": updated.get("updated_at"),
            }
        )

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="P5 axis successor read-only viewer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    print(
        f"P5 axis viewer → http://{args.host}:{args.port}/  "
        f"(filter=corpus|accepted|rejected|all|suspect); notes → {notes_path()}"
    )
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug or bool(os.environ.get("FLASK_DEBUG")),
    )


if __name__ == "__main__":
    main()

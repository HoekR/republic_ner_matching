"""Local API for the stretch conflict viewer — notes + date↔scan claims.

Serves JSON and accepts day-note edits into ``problem_sequence_review_notes``,
then re-exports ``viz/sequence_stretch/public/stretch.json``.

Usage (with Vite proxy)::

    uv run python -m sequence_graph.stretch_viz_server
    cd viz/sequence_stretch && pnpm dev

POST /api/day-note  JSON body:
    inventory, date, note, flag?, scan_num?, claim_date?

No production PINNED_TO wire. Review claims stay note-shaped only.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from scripts.corpus_scope import in_scope, is_main_series
from sequence_graph.physical_pin_review import iiif_for_scan
from sequence_graph.problem_sequence_review import load_notes, save_notes
from sequence_graph.stretch_viz_export import DEFAULT_OUT, export_stretch

_CONTAINS_LINE_RE = re.compile(
    r"https?://\S+\s+contains\s+date\s+\d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)


def upsert_day_note(
    *,
    inventory: str,
    date: str,
    note: str,
    flag: str = "seen",
    scan_num: int | None = None,
    claim_date: str | None = None,
) -> dict[str, Any]:
    if not is_main_series(inventory):
        raise ValueError(f"inventory not main series: {inventory}")
    if not in_scope(date):
        raise ValueError(f"date out of scope: {date}")
    claim_date = claim_date or date
    if claim_date and not in_scope(claim_date):
        raise ValueError(f"claim_date out of scope: {claim_date}")

    text = (note or "").strip()
    if scan_num is not None:
        url = iiif_for_scan(inventory, int(scan_num))
        claim_line = f"{url} contains date {claim_date}"
        # Drop prior contains-date lines; keep free-text diagnosis.
        body_lines = [
            ln
            for ln in text.splitlines()
            if not _CONTAINS_LINE_RE.search(ln.strip())
        ]
        body = "\n".join(body_lines).strip()
        text = f"{claim_line}\n{body}".strip() if body else claim_line

    rid = f"day:{inventory}:{date}"
    notes = load_notes()
    prev = notes.get(rid) or {}
    notes[rid] = {
        "review_id": rid,
        "card_kind": "day_note",
        "flag": flag or prev.get("flag") or "seen",
        "note": text,
        "inventory": inventory,
        "calendar_lo": date,
        "calendar_hi": date,
        "anchor_lo_session": prev.get("anchor_lo_session"),
        "anchor_hi_session": prev.get("anchor_hi_session"),
        "n_unaligned": prev.get("n_unaligned"),
        "n_opening_hits": prev.get("n_opening_hits"),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    save_notes(notes)
    export_stretch(inventory=inventory)
    return notes[rid]


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/api/stretch", "/stretch.json"):
            export_stretch()
            data = json.loads(DEFAULT_OUT.read_text(encoding="utf-8"))
            self._json(200, data)
            return
        if path == "/api/health":
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/day-note":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return
        try:
            scan = body.get("scan_num")
            scan_num = int(scan) if scan not in (None, "") else None
            row = upsert_day_note(
                inventory=str(body.get("inventory") or "3185"),
                date=str(body["date"]),
                note=str(body.get("note") or ""),
                flag=str(body.get("flag") or "seen"),
                scan_num=scan_num,
                claim_date=(
                    str(body["claim_date"])
                    if body.get("claim_date")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
            return
        data = json.loads(DEFAULT_OUT.read_text(encoding="utf-8"))
        self._json(200, {"saved": row, "stretch": data})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[stretch-viz] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    export_stretch()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"stretch viz API on http://{args.host}:{args.port}  "
        f"(POST /api/day-note, GET /api/stretch)"
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()

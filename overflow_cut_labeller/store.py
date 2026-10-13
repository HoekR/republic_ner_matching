"""Candidates + disk-backed annotations for overflow cut review.

Candidates come from ``overflow_align_apply`` residuals ``needs_human_cuts``.
Machine cut offsets are pre-inserted as ``|||CUT|||`` markers; approve stores
parsed ``gold_offsets`` (still not a production ``ALIGNED_TO`` wire).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve
from sequence_graph.fingerprint_session_shift import (
    _enriched_text_by_volgnr,
    _flat_text_by_id,
)

APPLY_DATASET = "overflow_align_apply"
ANNOTATIONS_LOGICAL = "overflow_cut_reviews"
MARKER = "|||CUT|||"
VERDICTS = ("approve", "defer", "skip")

DEFAULT_ANNOTATIONS_PATH = PROJECT_ROOT / "output" / "overflow_cut_reviews.json"


def annotations_path() -> Path:
    try:
        return Path(resolve(ANNOTATIONS_LOGICAL))
    except Exception:
        return DEFAULT_ANNOTATIONS_PATH


def apply_cuts_as_markers(text: str, cuts: list[int], *, marker: str = MARKER) -> str:
    """Insert ``marker`` at sorted interior offsets (char indices into raw text).

    Does not pad missing slots — only the valid unique offsets present in
    ``cuts`` become markers (machine proposals already have the right count).
    """
    if not text or not cuts:
        return text
    cleaned = sorted({int(c) for c in cuts if 0 < int(c) < len(text)})
    parts: list[str] = []
    prev = 0
    for cut in cleaned:
        parts.append(text[prev:cut])
        parts.append(marker)
        prev = cut
    parts.append(text[prev:])
    return "".join(parts)


def offsets_from_marked_text(marked: str, *, marker: str = MARKER) -> list[int]:
    """Recover cut offsets in marker-free text from a marked string."""
    if not marked or marker not in marked:
        return []
    offsets: list[int] = []
    cursor = 0
    raw_pos = 0
    while True:
        idx = marked.find(marker, cursor)
        if idx < 0:
            break
        raw_pos += idx - cursor
        offsets.append(raw_pos)
        cursor = idx + len(marker)
    return offsets


def strip_markers(marked: str, *, marker: str = MARKER) -> str:
    return str(marked or "").replace(marker, "")


def count_cuts(text: str, *, marker: str = MARKER) -> int:
    return len(str(text or "").split(marker)) - 1


def load_candidates() -> list[dict[str, Any]]:
    """Build review cards for each ``needs_human_cuts`` residual."""
    resolve(APPLY_DATASET)
    rows = list(load(APPLY_DATASET))
    needs = [r for r in rows if r.get("kind") == "needs_human_cuts" and r.get("flat_id")]
    flat_apply = {
        str(r["flat_id"]): r
        for r in rows
        if r.get("record_type") == "flat_apply"
        and r.get("cut_source") == "encoder"
        and r.get("flat_id")
    }
    flat_texts = _flat_text_by_id()
    enr_texts = _enriched_text_by_volgnr()
    out: list[dict[str, Any]] = []
    for residual in needs:
        flat_id = str(residual["flat_id"])
        apply_row = flat_apply.get(flat_id) or {}
        machine_cuts = list(residual.get("cuts") or apply_row.get("cuts") or [])
        claimants = list(apply_row.get("claimant_volgnrs") or [])
        raw = flat_texts.get(flat_id) or ""
        expected = max(0, len(claimants) - 1) if claimants else len(machine_cuts)
        seeded = apply_cuts_as_markers(raw, [int(c) for c in machine_cuts])
        claimant_cards = [
            {
                "volgnr": v,
                "text": enr_texts.get(v) or "",
                "char_len": len(enr_texts.get(v) or ""),
            }
            for v in claimants
        ]
        out.append({
            "example_id": flat_id,
            "flat_id": flat_id,
            "session_id": residual.get("session_id") or apply_row.get("session_id"),
            "n_claimants": int(residual.get("size_claimants") or len(claimants) or 0),
            "size_matched": residual.get("size_matched"),
            "size_insertion_split": residual.get("size_insertion_split"),
            "size_deletion": residual.get("size_deletion"),
            "order_match_rate": residual.get("order_match_rate"),
            "machine_cuts": [int(c) for c in machine_cuts],
            "expected_cuts": expected,
            "flat_char_len": len(raw),
            "raw_text": raw,
            "seeded_text": seeded,
            "claimants": claimant_cards,
            "note_seed": residual.get("note") or "",
        })
    out.sort(key=lambda r: str(r["example_id"]))
    return out


def empty_annotations() -> dict[str, Any]:
    return {
        "marker": MARKER,
        "format": "overflow_cut_reviews_v1",
        "updated_at": None,
        "annotations": {},
    }


def load_annotations(path: Path | None = None) -> dict[str, Any]:
    p = path or annotations_path()
    if not p.exists():
        return empty_annotations()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_annotations()
    if not isinstance(data, dict):
        return empty_annotations()
    data.setdefault("marker", MARKER)
    data.setdefault("format", "overflow_cut_reviews_v1")
    data.setdefault("annotations", {})
    if not isinstance(data["annotations"], dict):
        data["annotations"] = {}
    return data


def save_annotations(state: dict[str, Any], path: Path | None = None) -> Path:
    p = path or annotations_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "marker": MARKER,
        "format": "overflow_cut_reviews_v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "annotations": dict(state.get("annotations") or {}),
    }
    payload = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(p)
    return p


def normalize_annotation(row: dict[str, Any]) -> dict[str, Any]:
    verdict = str(row.get("verdict") or "defer").strip()
    if verdict not in VERDICTS:
        verdict = "defer"
    marked = str(row.get("text") or "")
    offsets = offsets_from_marked_text(marked)
    return {
        "text": marked,
        "gold_offsets": offsets,
        "verdict": verdict,
        "note": str(row.get("note") or ""),
        "uncertain": bool(row.get("uncertain")),
        "labelled": bool(row.get("labelled")) or verdict in {"approve", "skip"},
        "labelled_at": row.get("labelled_at"),
        "is_gold": verdict == "approve",
    }


def default_annotation(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": str(candidate.get("seeded_text") or candidate.get("raw_text") or ""),
        "gold_offsets": list(candidate.get("machine_cuts") or []),
        "verdict": "defer",
        "note": "",
        "uncertain": False,
        "labelled": False,
        "labelled_at": None,
        "is_gold": False,
    }


def merge_row(candidate: dict[str, Any], annotation: dict[str, Any] | None) -> dict[str, Any]:
    base = default_annotation(candidate)
    if annotation:
        base.update(normalize_annotation(annotation))
        if "text" in annotation and annotation.get("text") is not None:
            base["text"] = str(annotation.get("text"))
            base["gold_offsets"] = offsets_from_marked_text(base["text"])
    row = dict(candidate)
    row.update(base)
    return row


def is_labelled_row(row: dict[str, Any]) -> bool:
    return bool(row.get("labelled")) or str(row.get("verdict") or "") in {"approve", "skip"}


def stats(candidates: list[dict[str, Any]], annotations: dict[str, Any]) -> dict[str, int]:
    ann = annotations.get("annotations") or {}
    labelled = 0
    by_verdict = {key: 0 for key in VERDICTS}
    for candidate in candidates:
        row = merge_row(candidate, ann.get(str(candidate["example_id"])))
        if is_labelled_row(row):
            labelled += 1
            verdict = str(row.get("verdict") or "defer")
            if verdict in by_verdict:
                by_verdict[verdict] += 1
    return {
        "total": len(candidates),
        "labelled": labelled,
        "pending": len(candidates) - labelled,
        **{f"verdict_{key}": value for key, value in by_verdict.items()},
    }


def record_index(candidates: list[dict[str, Any]], example_id: str) -> int:
    for index, candidate in enumerate(candidates):
        if str(candidate["example_id"]) == str(example_id):
            return index
    raise KeyError(example_id)


def next_unlabelled_id(
    candidates: list[dict[str, Any]],
    annotations: dict[str, Any],
    *,
    start: int = 0,
) -> str | None:
    ann = annotations.get("annotations") or {}
    n = len(candidates)
    if n == 0:
        return None
    for offset in range(n):
        index = (start + offset) % n
        row = merge_row(candidates[index], ann.get(str(candidates[index]["example_id"])))
        if not is_labelled_row(row):
            return str(candidates[index]["example_id"])
    return None


def update_annotation(
    annotations: dict[str, Any],
    example_id: str,
    payload: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    known = {str(c["example_id"]) for c in candidates}
    if example_id not in known:
        raise KeyError(example_id)
    candidate = next(c for c in candidates if str(c["example_id"]) == example_id)
    current = merge_row(candidate, (annotations.get("annotations") or {}).get(example_id))
    verdict = str(payload.get("verdict") or current.get("verdict") or "defer").strip()
    if verdict not in VERDICTS:
        raise ValueError(f"invalid verdict: {verdict}")
    marked = str(payload.get("text") if payload.get("text") is not None else current["text"])
    updated = normalize_annotation(
        {
            "text": marked,
            "verdict": verdict,
            "note": str(payload.get("note") or ""),
            "uncertain": bool(payload.get("uncertain")),
            "labelled": True if "labelled" not in payload else bool(payload.get("labelled")),
            "labelled_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if verdict == "approve":
        expected = int(candidate.get("expected_cuts") or 0)
        if expected > 0 and len(updated["gold_offsets"]) != expected:
            # Soft: allow, but mark uncertain so promote step can gate.
            updated["uncertain"] = True
    out = dict(annotations)
    anns = dict(out.get("annotations") or {})
    anns[example_id] = updated
    out["annotations"] = anns
    return out

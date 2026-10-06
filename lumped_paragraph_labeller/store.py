"""Disk-backed store for lumped-paragraph gold labelling."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_io import load, resolve

SCAFFOLD_DATASET = "lumped_paragraph_gold_scaffold"
ANNOTATIONS_LOGICAL = "lumped_paragraph_gold_annotations"
MARKER = "|||CUT|||"
# Marks where resolution text begins when the paragraph opens with non-resolution
# matter (attendance list, heading). At most one per paragraph, and never a cut:
# it is the paragraph's head offset, not an interior resolution start. Introduced
# by hand in the 2026-09-28 pass (1629-07-25#p0) before the tooling knew it.
START_MARKER = "|||START|||"

# cuts: mid_paragraph offsets present
# no_cut: human says one/partial resolution — no interior cut
# false_lump: concordance n_share collapse is wrong (quarantine)
# skip: not annotatable / wrong session-date content
VERDICTS = ("cuts", "no_cut", "false_lump", "skip")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANNOTATIONS_PATH = PROJECT_ROOT / "output" / "lumped_paragraph_gold_annotations.json"


def annotations_path() -> Path:
    try:
        return Path(resolve(ANNOTATIONS_LOGICAL))
    except Exception:
        return DEFAULT_ANNOTATIONS_PATH


def load_candidates() -> list[dict[str, Any]]:
    resolve(SCAFFOLD_DATASET)
    return [r for r in load(SCAFFOLD_DATASET) if r.get("record_type") == "candidate"]


def empty_annotations() -> dict[str, Any]:
    return {
        "marker": MARKER,
        "format": "lumped_paragraph_gold_annotations_v2",
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
    data.setdefault("format", "lumped_paragraph_gold_annotations_v2")
    data.setdefault("annotations", {})
    if not isinstance(data["annotations"], dict):
        data["annotations"] = {}
    # Normalize legacy rows (v1 had skip/labelled only).
    for example_id, row in list(data["annotations"].items()):
        if not isinstance(row, dict):
            continue
        data["annotations"][example_id] = normalize_annotation(row)
    return data


def save_annotations(state: dict[str, Any], path: Path | None = None) -> Path:
    p = path or annotations_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    anns = {
        key: normalize_annotation(value)
        for key, value in dict(state.get("annotations") or {}).items()
        if isinstance(value, dict)
    }
    out = {
        "marker": MARKER,
        "format": "lumped_paragraph_gold_annotations_v2",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "annotations": anns,
    }
    payload = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(p)
    return p


def count_cuts(text: str, marker: str = MARKER) -> int:
    return len(str(text or "").split(marker)) - 1


def infer_verdict(row: dict[str, Any], *, marker: str = MARKER) -> str:
    """Infer verdict for legacy saves (skip / 0-cut labelled / cuts)."""
    explicit = str(row.get("verdict") or "").strip()
    if explicit in VERDICTS:
        return explicit
    if row.get("skip"):
        return "skip"
    n_cuts = count_cuts(str(row.get("text") or ""), marker=marker)
    if row.get("labelled") and n_cuts == 0:
        notes = f"{row.get('paragraph_notes') or ''} {row.get('cut_notes') or ''}".lower()
        if any(token in notes for token in ("false lump", "collapse", "out of place", "wrong date")):
            return "false_lump"
        return "no_cut"
    if row.get("labelled") and n_cuts > 0:
        return "cuts"
    return "cuts"


def normalize_annotation(row: dict[str, Any]) -> dict[str, Any]:
    verdict = infer_verdict(row)
    return {
        "text": str(row.get("text") or ""),
        "paragraph_notes": str(row.get("paragraph_notes") or ""),
        "cut_notes": str(row.get("cut_notes") or ""),
        "uncertain": bool(row.get("uncertain")),
        "clutter": bool(row.get("clutter")),
        "skip": verdict == "skip",
        "verdict": verdict,
        "labelled": bool(row.get("labelled")) or verdict in {"no_cut", "false_lump", "skip", "cuts"},
    }


def default_annotation(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": str(candidate.get("text") or ""),
        "paragraph_notes": str(candidate.get("paragraph_notes") or ""),
        "cut_notes": "",
        "uncertain": False,
        "clutter": False,
        "skip": False,
        "verdict": "cuts",
        "labelled": False,
    }


def merge_row(candidate: dict[str, Any], annotation: dict[str, Any] | None) -> dict[str, Any]:
    base = default_annotation(candidate)
    if annotation:
        normalized = normalize_annotation(annotation)
        base.update(normalized)
        # Preserve raw text from annotation even when empty string is intentional.
        if "text" in annotation and annotation.get("text") is not None:
            base["text"] = str(annotation.get("text"))
    row = dict(candidate)
    row.update(base)
    return row


def is_labelled_row(row: dict[str, Any]) -> bool:
    if row.get("verdict") in {"no_cut", "false_lump", "skip"}:
        return True
    if row.get("skip"):
        return True
    return bool(row.get("labelled"))


def stats(candidates: list[dict[str, Any]], annotations: dict[str, Any]) -> dict[str, int]:
    ann = annotations.get("annotations") or {}
    labelled = 0
    by_verdict = {key: 0 for key in VERDICTS}
    for candidate in candidates:
        row = merge_row(candidate, ann.get(str(candidate["example_id"])))
        if is_labelled_row(row):
            labelled += 1
            verdict = str(row.get("verdict") or infer_verdict(row))
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
    verdict = str(payload.get("verdict") or current.get("verdict") or "cuts").strip()
    if verdict not in VERDICTS:
        raise ValueError(f"invalid verdict: {verdict}")
    updated = normalize_annotation(
        {
            "text": str(payload.get("text") if payload.get("text") is not None else current["text"]),
            "paragraph_notes": str(payload.get("paragraph_notes") or ""),
            "cut_notes": str(payload.get("cut_notes") or ""),
            "uncertain": bool(payload.get("uncertain")),
            "clutter": bool(payload.get("clutter")),
            "skip": verdict == "skip",
            "verdict": verdict,
            "labelled": True if "labelled" not in payload else bool(payload.get("labelled")),
        }
    )
    out = dict(annotations)
    anns = dict(out.get("annotations") or {})
    anns[example_id] = updated
    out["annotations"] = anns
    return out

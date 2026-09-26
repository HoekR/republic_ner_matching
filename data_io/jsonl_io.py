"""JSONL I/O with .meta.toml sidecars (Phase 1–2)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

from data_io.manifest import get_manager, resolve
from data_io.provenance import ProvenanceRecord, git_commit_hash, write_sidecar


def _resolve_output_path(
    *,
    logical_name: str | None,
    out_path: str | Path | None,
) -> Path:
    if logical_name:
        return resolve(logical_name)
    if out_path is None:
        raise ValueError("Provide logical_name or out_path")
    return Path(out_path).expanduser().resolve()


def save_jsonl(
    records: list[dict[str, Any]],
    *,
    logical_name: str | None = None,
    out_path: str | Path | None = None,
    phase: str = "explore",
    parent_sources: list[str] | None = None,
    description: str = "",
    script: str | None = None,
) -> Path:
    path = _resolve_output_path(logical_name=logical_name, out_path=out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    if logical_name:
        manager = get_manager()
        dataset = manager.dataset(logical_name)
        phase = dataset.phase or phase
        if not description:
            description = dataset.description
        if parent_sources is None and dataset.parent:
            parent_sources = [dataset.parent]

    record = ProvenanceRecord(
        logical_name=logical_name or path.stem,
        phase=phase,
        parent_sources=parent_sources or [],
        description=description,
        created_by_script=script or "",
        record_count=len(records),
        git_commit=git_commit_hash(path.parent),
    )
    write_sidecar(path, record)
    return path


def save_semi_structured(
    records: list[dict[str, Any]],
    *,
    logical_name: str | None = None,
    out_path: str | Path | None = None,
    parent_sources: list[str] | None = None,
    description: str = "",
    script: str | None = None,
) -> Path:
    return save_jsonl(
        records,
        logical_name=logical_name,
        out_path=out_path,
        phase="semi",
        parent_sources=parent_sources,
        description=description,
        script=script,
    )


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

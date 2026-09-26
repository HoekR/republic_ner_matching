"""Provenance metadata for pipeline outputs (sidecar + embedded headers)."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomli_w


DH_META_PREFIX = "dh."
PROVENANCE_JSON_SUFFIX = ".provenance.json"


@dataclass
class ProvenanceRecord:
    logical_name: str
    phase: str
    parent_sources: list[str] = field(default_factory=list)
    description: str = ""
    created_at: str = ""
    created_by_script: str = ""
    record_count: int | None = None
    git_commit: str | None = None
    python_version: str = ""
    columns: list[str] | None = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if not self.python_version:
            self.python_version = platform.python_version()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}

    def to_parquet_metadata(self) -> dict[bytes, bytes]:
        return {
            f"{DH_META_PREFIX}{k}".encode(): json.dumps(v).encode()
            for k, v in self.to_dict().items()
        }


def git_commit_hash(repo_root: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_root or Path.cwd(),
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def sidecar_path_for(data_path: Path, *, phase: str) -> Path:
    if phase == "frozen":
        return data_path.with_suffix(data_path.suffix + ".meta.json")
    return data_path.with_suffix(".meta.toml")


def provenance_json_path_for(data_path: Path) -> Path:
    """Additional JSON sidecar required by some specs (always written)."""
    return data_path.with_suffix(PROVENANCE_JSON_SUFFIX)


def write_sidecar(data_path: Path, record: ProvenanceRecord) -> Path:
    sidecar = sidecar_path_for(data_path, phase=record.phase)
    payload = record.to_dict()
    if record.phase == "frozen":
        sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        sidecar.write_text(tomli_w.dumps(payload), encoding="utf-8")
    # Policy/compat: also write a stable JSON provenance file.
    provenance_json = provenance_json_path_for(data_path)
    provenance_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return sidecar


def read_sidecar(data_path: Path, *, phase: str | None = None) -> dict[str, Any] | None:
    candidates: list[Path] = []
    # Prefer the explicit JSON provenance if present.
    candidates.append(provenance_json_path_for(data_path))
    if phase == "frozen":
        candidates.append(data_path.with_suffix(data_path.suffix + ".meta.json"))
    elif phase in {"explore", "semi"}:
        candidates.append(data_path.with_suffix(".meta.toml"))
    else:
        candidates.extend(
            [
                data_path.with_suffix(data_path.suffix + ".meta.json"),
                data_path.with_suffix(".meta.toml"),
            ]
        )
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(text)
        import tomllib

        return tomllib.loads(text)
    return None


def read_parquet_embedded_metadata(schema_metadata: dict[bytes, bytes] | None) -> dict[str, Any]:
    if not schema_metadata:
        return {}
    out: dict[str, Any] = {}
    for key, value in schema_metadata.items():
        key_str = key.decode() if isinstance(key, bytes) else str(key)
        if not key_str.startswith(DH_META_PREFIX):
            continue
        field_name = key_str.removeprefix(DH_META_PREFIX)
        raw = value.decode() if isinstance(value, bytes) else str(value)
        try:
            out[field_name] = json.loads(raw)
        except json.JSONDecodeError:
            out[field_name] = raw
    return out

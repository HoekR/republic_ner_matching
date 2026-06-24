"""Parquet I/O with embedded metadata and .meta.json sidecars (Phase 3)."""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data_io.manifest import get_manager, resolve
from data_io.provenance import (
    ProvenanceRecord,
    git_commit_hash,
    read_parquet_embedded_metadata,
    read_sidecar,
    write_sidecar,
)


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


def save_parquet(
    df: pd.DataFrame,
    *,
    logical_name: str | None = None,
    out_path: str | Path | None = None,
    phase: str = "frozen",
    parent_sources: list[str] | None = None,
    description: str = "",
    script: str | None = None,
) -> Path:
    path = _resolve_output_path(logical_name=logical_name, out_path=out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if logical_name:
        manager = get_manager()
        dataset = manager.dataset(logical_name)
        phase = dataset.phase or phase
        if not description:
            description = dataset.description
        if parent_sources is None and dataset.parent:
            parent_sources = [dataset.parent]

    provenance = ProvenanceRecord(
        logical_name=logical_name or path.stem,
        phase=phase,
        parent_sources=parent_sources or [],
        description=description,
        created_by_script=script or "",
        record_count=len(df),
        git_commit=git_commit_hash(path.parent),
        columns=list(df.columns),
    )

    table = pa.Table.from_pandas(df, preserve_index=False)
    existing = table.schema.metadata or {}
    merged_metadata = dict(existing)
    merged_metadata.update(provenance.to_parquet_metadata())
    table = table.replace_schema_metadata(merged_metadata)
    pq.write_table(table, path)
    write_sidecar(path, provenance)
    return path


def load_parquet(
    logical_name: str | None = None,
    path: str | Path | None = None,
    *,
    warn_missing_sidecar: bool = True,
) -> pd.DataFrame:
    resolved = resolve(logical_name) if logical_name else Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)

    table = pq.read_table(resolved)
    embedded = read_parquet_embedded_metadata(table.schema.metadata)
    if warn_missing_sidecar and embedded and read_sidecar(resolved, phase="frozen") is None:
        warnings.warn(
            f"Parquet file has embedded provenance but no sidecar: {resolved}",
            stacklevel=2,
        )
    return table.to_pandas()

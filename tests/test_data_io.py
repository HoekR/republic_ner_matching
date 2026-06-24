"""Tests for data_io manifest and provenance I/O."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from data_io.jsonl_io import load_jsonl, save_semi_structured
from data_io.manifest import DataManager, TierUnavailableError
from data_io.parquet_io import load_parquet, save_parquet
from data_io.provenance import read_parquet_embedded_metadata, read_sidecar


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    manifest = tmp_path / "data_manifest.toml"
    manifest.write_text(
        """
[tiers.hot]
root = "{root}"
mount_check = ""

[tiers.warm]
root = "{warm}"
mount_check = "{warm}"

[tiers.scratch]
root = "{scratch}"
mount_check = "{scratch}"

[datasets.sample_jsonl]
tier = "scratch"
path = "out/sample.jsonl"
phase = "semi"
description = "Test semi-structured output"
parent = "sample_parent"

[datasets.sample_parquet]
tier = "warm"
path = "out/sample.parquet"
phase = "frozen"
description = "Test frozen output"
parent = ""
""".format(
            root=str(tmp_path / "hot"),
            warm=str(tmp_path / "warm"),
            scratch=str(tmp_path / "scratch"),
        ),
        encoding="utf-8",
    )
    for directory in ("hot", "warm", "scratch"):
        (tmp_path / directory).mkdir()
    (tmp_path / "scratch" / "out").mkdir()
    (tmp_path / "warm" / "out").mkdir()
    return tmp_path


def test_resolve_paths(manifest_dir: Path) -> None:
    manager = DataManager(manifest_dir / "data_manifest.toml")
    assert manager.resolve("sample_jsonl") == manifest_dir / "scratch" / "out" / "sample.jsonl"


def test_tier_unavailable_raises(tmp_path: Path) -> None:
    manifest = tmp_path / "data_manifest.toml"
    missing = tmp_path / "missing_volume"
    manifest.write_text(
        f"""
[tiers.warm]
root = "{missing / 'data'}"
mount_check = "{missing}"

[datasets.x]
tier = "warm"
path = "file.parquet"
phase = "frozen"
""",
        encoding="utf-8",
    )
    manager = DataManager(manifest)
    with pytest.raises(TierUnavailableError):
        manager.resolve("x")


def test_save_semi_structured_sidecar(manifest_dir: Path) -> None:
    import os

    os.chdir(manifest_dir)
    records = [{"id": 1, "text": "hello"}]
    path = save_semi_structured(
        records,
        logical_name="sample_jsonl",
        script="test_script.py",
    )
    assert path.exists()
    sidecar = read_sidecar(path, phase="semi")
    assert sidecar is not None
    assert sidecar["logical_name"] == "sample_jsonl"
    assert sidecar["phase"] == "semi"
    assert sidecar["record_count"] == 1
    assert load_jsonl(path) == records


def test_save_parquet_metadata_and_sidecar(manifest_dir: Path) -> None:
    import os

    os.chdir(manifest_dir)
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    path = save_parquet(df, logical_name="sample_parquet", script="test_script.py")
    assert path.exists()

    table = pq.read_table(path)
    embedded = read_parquet_embedded_metadata(table.schema.metadata)
    assert embedded["logical_name"] == "sample_parquet"
    assert embedded["record_count"] == 2

    sidecar = read_sidecar(path, phase="frozen")
    assert sidecar is not None
    assert sidecar["columns"] == ["a", "b"]

    loaded = load_parquet(path=path, warn_missing_sidecar=False)
    assert len(loaded) == 2


def test_local_override_merge(manifest_dir: Path) -> None:
    override = manifest_dir / "data_manifest.local.toml"
    override.write_text(
        """
[datasets.sample_jsonl]
path = "out/overridden.jsonl"
""",
        encoding="utf-8",
    )
    manager = DataManager(manifest_dir / "data_manifest.toml")
    assert manager.resolve("sample_jsonl").name == "overridden.jsonl"

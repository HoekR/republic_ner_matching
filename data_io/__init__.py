"""Data manifest resolution and provenance-aware I/O."""

from data_io.jsonl_io import load_jsonl, save_jsonl, save_semi_structured
from data_io.loaders import load
from data_io.manifest import (
    DataManager,
    DatasetNotFoundError,
    TierUnavailableError,
    find_manifest_path,
    get_manager,
    resolve,
)
from data_io.parquet_io import load_parquet, save_parquet
from data_io.provenance import ProvenanceRecord

__all__ = [
    "DataManager",
    "DatasetNotFoundError",
    "ProvenanceRecord",
    "TierUnavailableError",
    "find_manifest_path",
    "get_manager",
    "load",
    "load_jsonl",
    "load_parquet",
    "resolve",
    "run_check",
    "save_jsonl",
    "save_parquet",
    "save_semi_structured",
]


def run_check(*args, **kwargs):  # noqa: ANN002, ANN003
    from data_io.check import run_check as _run_check

    return _run_check(*args, **kwargs)

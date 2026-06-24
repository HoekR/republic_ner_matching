"""Dispatch load() by file suffix."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pandas as pd

from data_io.jsonl_io import load_jsonl
from data_io.manifest import resolve
from data_io.parquet_io import load_parquet


def load(logical_name: str | None = None, path: str | Path | None = None) -> Any:
    resolved = resolve(logical_name) if logical_name else Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)

    suffixes = resolved.suffixes
    if resolved.suffix == ".gz" and len(suffixes) >= 2:
        inner = "".join(suffixes[:-1])
    else:
        inner = resolved.suffix

    if inner == ".parquet":
        return load_parquet(path=resolved)
    if inner == ".jsonl":
        return load_jsonl(resolved)
    if inner == ".json":
        with resolved.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    if inner in {".tsv", ".csv"} or resolved.name.endswith((".tsv.gz", ".csv.gz")):
        return pd.read_csv(resolved, sep="\t" if ".tsv" in resolved.name else ",")
    if inner == ".gz":
        with gzip.open(resolved, "rt", encoding="utf-8") as handle:
            return handle.read()

    return resolved

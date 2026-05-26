"""Preprocessing utilities for NER PER-layer annotations.

Functions:
    load_inventory_metadata(path) -> dict[int, dict]
    load_ner(path, inv_lookup, year_min, year_max, chunk_size) -> pd.DataFrame
    clean_span(text) -> str
    split_multi_person(text) -> list[str]
"""

import json
import pathlib
import re

import pandas as pd

# Dutch honorifics and titles to strip before matching.
# Use \.? + lookahead instead of trailing \b so the period is consumed.
_TITLE_RE = re.compile(
    r"\b(mr|meester|heere|hertog|grave|graeve|graaf|marquis|monsr?"
    r"|vrouwe?|jonkheer|de\s+heer|de\s+jonge|jhr|ds|dr|prof)\.?(?=\s|$)",
    re.IGNORECASE,
)

# Split multi-person spans on Dutch conjunctions and punctuation
_SPLIT_RE = re.compile(r"\s+ende\s+|,\s*|;\s*", re.IGNORECASE)


def load_inventory_metadata(path: str | pathlib.Path) -> dict[int, dict]:
    """Load inventory_metadata.json and return a dict keyed by inventory_num.

    For entries where ``year`` is a list, ``year_start`` is used as the
    canonical year.

    Returns:
        {inventory_num: {year, year_start, period_start, period_end, ...}}
    """
    path = pathlib.Path(path)
    data = json.loads(path.read_text())
    result: dict[int, dict] = {}
    for entry in data:
        inv_num = entry.get("inventory_num")
        if not isinstance(inv_num, int):
            continue
        year = entry.get("year")
        year_start = entry.get("year_start")
        # Normalise multi-year entries
        if isinstance(year, list):
            year = year_start if isinstance(year_start, int) else year[0]
        if not isinstance(year, int):
            continue
        result[inv_num] = {
            "year": year,
            "year_start": year_start if isinstance(year_start, int) else year,
            "period_start": entry.get("period_start"),
            "period_end": entry.get("period_end"),
        }
    return result


def load_ner(
    path: str | pathlib.Path,
    inv_lookup: dict[int, dict],
    year_min: int | None = None,
    year_max: int | None = None,
    chunk_size: int = 100_000,
) -> pd.DataFrame:
    """Load NER PER-layer TSV (optionally gzipped) in chunks.

    The file has columns:
        layer, inv, resolution_id, paragraph_id, tag_text, offset, end, tag_length

    Each row is joined with ``inv_lookup`` to derive a ``year`` column, then
    filtered to [year_min, year_max] if provided.

    Returns:
        DataFrame with columns: inv, resolution_id, paragraph_id, tag_text, year
    """
    path = pathlib.Path(path)
    compression = "gzip" if path.suffix == ".gz" else "infer"

    chunks = []
    for chunk in pd.read_csv(
        path,
        sep="\t",
        compression=compression,
        chunksize=chunk_size,
        usecols=["inv", "resolution_id", "paragraph_id", "tag_text"],
        dtype={"inv": "Int64", "resolution_id": str, "paragraph_id": str, "tag_text": str},
        low_memory=False,
    ):
        # Derive year from inv_lookup
        chunk = chunk.copy()
        chunk["year"] = chunk["inv"].map(
            lambda x: inv_lookup.get(int(x), {}).get("year") if pd.notna(x) else None
        )
        chunk = chunk[chunk["year"].notna()]
        chunk["year"] = chunk["year"].astype(int)

        if year_min is not None:
            chunk = chunk[chunk["year"] >= year_min]
        if year_max is not None:
            chunk = chunk[chunk["year"] <= year_max]

        chunk = chunk[chunk["tag_text"].notna() & (chunk["tag_text"].str.strip() != "")]
        chunks.append(chunk)

    if not chunks:
        return pd.DataFrame(columns=["inv", "resolution_id", "paragraph_id", "tag_text", "year"])

    return pd.concat(chunks, ignore_index=True)


def clean_span(text: str) -> str:
    """Strip Dutch titles and normalise whitespace; return lowercased result."""
    text = _TITLE_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def split_multi_person(text: str) -> list[str]:
    """Split a span that may contain multiple names joined by 'ende', ',' or ';'.

    Each part is cleaned with :func:`clean_span`.  Empty parts are dropped.

    Example:
        >>> split_multi_person("Slicher ende Hop")
        ['slicher', 'hop']
    """
    parts = _SPLIT_RE.split(text)
    result = []
    for part in parts:
        cleaned = clean_span(part)
        if cleaned:
            result.append(cleaned)
    return result

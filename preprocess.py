"""Preprocessing utilities for NER PER-layer annotations.

Functions:
    load_inventory_metadata(path) -> dict[int, dict]
    load_ner(path, inv_lookup, year_min, year_max, chunk_size) -> pd.DataFrame
    normalize_name_for_matching(text) -> str
    clean_span(text) -> str
    mask_name_pattern(text, unknown=False) -> str
    extract_title(text) -> str
    split_multi_person(text) -> list[str]
"""

import json
import pathlib
import re
from typing import Callable

import pandas as pd

# Non-identifying honorifics — strip before matching (carry no identity value).
_HONORIFIC_RE = re.compile(
    r"\b(mr|meester|monsr?|de\s+heer|ds|dr|prof|ra.?dt)\.?(?=\s|$)",
    re.IGNORECASE,
)

# Noble / rank titles — extract separately; the estate name that follows is
# valuable for disambiguation (e.g. "grave van Rechteren" → title="grave",
# span retains "van Rechteren" for TF-IDF matching).
_NOBLE_TITLE_RE = re.compile(
    r"\b(heere?|hertog|grave|graeve|graaf|marquis|vrouwe?|jonkheer|jhr|de\s+jonge)\.?(?=\s|$)",
    re.IGNORECASE,
)

# Interposition (tussenvoegsel) abbreviation normalisation.
# Applied before matching so that span text and delegate patterns use the same
# canonical form.  Order matters: most-specific patterns first.
#
# Common abbreviated forms in 17th/18th-century Dutch:
#   v.d.r. / v.d.r  → van der
#   v.d.e. / v.d.e  → van de
#   v.d.   / vd     → van de   (ambiguous; "van de" is more frequent than "van den")
#   v.     / v      → van      (only when followed by a capitalised name token)
#   d.     / d      → de       (rare as standalone abbreviation)
#   op d.           → op de
#   in 't           → in het   (rare, keep as-is — 't already low-IDF)
_INTERP_NORMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bv\.?\s*d\.?\s*r\.?(?=\s|$)", re.IGNORECASE), "van der"),
    (re.compile(r"\bv\.?\s*d\.?\s*e\.?(?=\s|$)", re.IGNORECASE), "van de"),
    (re.compile(r"\bv\.?\s*d\.?(?=\s|$)",         re.IGNORECASE), "van de van der"),
    (re.compile(r"\bop\s+d\.?(?=\s|$)",           re.IGNORECASE), "op de"),
    # bare "v." only when directly followed by a word character
    (re.compile(r"\bv\.(?=\s+\w)",                re.IGNORECASE), "van"),
]

# Conservative phonetic normalisation for Dutch historical spelling variants.
# These rules intentionally target high-frequency OCR/orthography drift patterns
# seen in names and surnames and mirror the Track B soundex principles in PLAN.md.
_SPELLING_NORMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ae", re.IGNORECASE), "aa"),
    (re.compile(r"eij", re.IGNORECASE), "ij"),
    (re.compile(r"ey", re.IGNORECASE), "ij"),
    (re.compile(r"uij", re.IGNORECASE), "ui"),
    (re.compile(r"uy", re.IGNORECASE), "ui"),
    # Keep ck/x-family rules in a strict order to avoid over-replacement.
    (re.compile(r"ckx", re.IGNORECASE), "ks"),
    (re.compile(r"cks", re.IGNORECASE), "ks"),
    (re.compile(r"x", re.IGNORECASE), "ks"),
    (re.compile(r"kk", re.IGNORECASE), "k"),
    (re.compile(r"ck", re.IGNORECASE), "k"),
    (re.compile(r"ngh", re.IGNORECASE), "ng"),
    (re.compile(r"gh", re.IGNORECASE), "g"),
    (re.compile(r"(?<!s)ch", re.IGNORECASE), "g"),
    (re.compile(r"c", re.IGNORECASE), "k"),
    (re.compile(r"ph", re.IGNORECASE), "f"),
    (re.compile(r"y", re.IGNORECASE), "ij"),
]

# Targeted long-s OCR confusions (s ↔ f) seen in raw spans.
# Keep this list conservative and evidence-driven to avoid changing genuine
# names that start with "F".
_LONG_S_NORMS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    (re.compile(r"\bfch", re.IGNORECASE), "sch"),
    (re.compile(r"\braadpenfionaris\b", re.IGNORECASE), "raadpensionaris"),
    (re.compile(r"\bminifter\b", re.IGNORECASE), "minister"),
    (re.compile(r"\bmajeft(eyt|eit)\b", re.IGNORECASE), lambda m: f"majest{m.group(1)}"),
    (re.compile(r"\brefident\b", re.IGNORECASE), "resident"),
    (re.compile(r"\bfecretaris\b", re.IGNORECASE), "secretaris"),
    (re.compile(r"\bconful\b", re.IGNORECASE), "consul"),
    (re.compile(r"\bamfterdam\b", re.IGNORECASE), "amsterdam"),
    (re.compile(r"\bkeyferlijcke\b", re.IGNORECASE), "keyserlijcke"),
    (re.compile(r"\bkeyferinne\b", re.IGNORECASE), "keyserinne"),
    (re.compile(r"\bheynfius\b", re.IGNORECASE), "heynsius"),
    (re.compile(r"\bwafsenaer\b", re.IGNORECASE), "wassenaer"),
]

# Split multi-person spans on Dutch conjunctions and punctuation
_SPLIT_RE = re.compile(r"\s+ende\s+|,\s*|;\s*", re.IGNORECASE)
_PATTERN_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]+(?:[-'][A-Za-zÀ-ÿ]+)*|\d+|[^\w\s]", re.UNICODE)
_NAME_PARTICLES = {
    "van",
    "de",
    "den",
    "der",
    "ten",
    "te",
    "tot",
    "op",
    "in",
    "het",
    "en",
}


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


def normalize_interpositions(text: str) -> str:
    """Expand abbreviated Dutch tussenvoegsels to their canonical form.

    Applies to both NER span text and delegate pattern strings so both sides
    of the TF-IDF comparison use the same surface form.
    """
    for pattern, replacement in _INTERP_NORMS:
        text = pattern.sub(replacement, text)
    return text


def normalize_spelling_variants(text: str) -> str:
    """Normalise historical Dutch spelling variants to a shared form.

    This is a light-weight phonetic canonicalisation layer so variants like
    ``Broeckhuijsen`` and ``Broeckhuysen`` converge before vector scoring.
    """
    for pattern, replacement in _LONG_S_NORMS:
        text = pattern.sub(replacement, text)
    for pattern, replacement in _SPELLING_NORMS:
        text = pattern.sub(replacement, text)
    return text


def normalize_name_for_matching(text: str) -> str:
    """Canonicalise name text for matching without stripping identity tokens.

    Intended for delegate pattern indexing and pre-cleaned name spans where we
    want between-variant stability (interpositions + orthography) but do not
    want to remove meaningful title/name words.
    """
    text = normalize_interpositions(text)
    text = normalize_spelling_variants(text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def extract_title(text: str) -> str:
    """Return the first noble/rank title found in *text*, or empty string.

    Titles preceded by a stripped honorific (e.g. "de heer") are not matched
    because :func:`clean_span` removes those honorifics first.  Call
    ``extract_title`` on the *original* raw span to capture the title before
    honorific stripping, or accept that "de heer" produces no title.
    """
    # strip non-identifying honorifics first so "de heer" doesn't leave a
    # dangling "heer" that the noble-title regex would pick up as a title.
    cleaned = _HONORIFIC_RE.sub(" ", text)
    m = _NOBLE_TITLE_RE.search(cleaned)
    return m.group(0).strip().lower() if m else ""


def clean_span(text: str) -> str:
    """Strip non-identifying honorifics, normalise whitespace; return lowercased result.

    Noble titles (grave, hertog, jonkheer, …) are intentionally kept so the
    estate name that follows them remains available for TF-IDF matching.
    Use :func:`extract_title` to capture the title itself as a separate field.
    """
    text = _HONORIFIC_RE.sub(" ", text)
    return normalize_name_for_matching(text)


def mask_name_pattern(text: str | None, unknown: bool = False) -> str:
    """Convert name-like text into a non-identifying structural signature.

    This keeps token layout and particles (van/de/der/...) visible for pattern
    analysis, while replacing lexical identity tokens with length markers.
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return "[UNK_NAME]" if unknown else ""

    value = re.sub(r"\s+", " ", str(text)).strip()
    if not value:
        return "[UNK_NAME]" if unknown else ""

    masked_tokens: list[str] = []
    for token in _PATTERN_TOKEN_RE.findall(value):
        if token.isdigit():
            masked_tokens.append(f"D{len(token)}")
            continue

        if re.fullmatch(r"[A-Za-zÀ-ÿ]+(?:[-'][A-Za-zÀ-ÿ]+)*", token):
            lower = token.lower()
            if lower in _NAME_PARTICLES:
                masked_tokens.append(lower)
            elif len(token) == 1:
                masked_tokens.append("I")
            else:
                masked_tokens.append(f"N{len(token)}")
            continue

        masked_tokens.append(token)

    masked = " ".join(masked_tokens)
    if unknown:
        return f"[UNK_NAME] {masked}" if masked else "[UNK_NAME]"
    return masked


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

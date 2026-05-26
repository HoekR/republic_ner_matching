"""Dual TF-IDF matching engine for NER span → delegate resolution.

Adapted from streamlit_worksheet/utils.py build_suggestion_store /
query_suggestions.  No Streamlit dependency.  No province constraint
(NER spans carry no province context).

Typical usage::

    import pandas as pd
    from match import build_store, match_ner

    delegates = pd.read_parquet('data/delegates_reference.parquet')
    store = build_store(delegates)

    ner = pd.DataFrame({'tag_text': ['heinsius', 'slingelandt'], 'year': [1710, 1730]})
    results = match_ner(store, ner, top_k=5)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Weight of char n-gram similarity vs word n-gram similarity
_CHAR_WEIGHT = 0.6
_WORD_WEIGHT = 0.4

# Default matching parameters
DEFAULT_YEAR_TOLERANCE = 15
DEFAULT_MIN_SCORE = 0.1
DEFAULT_TOP_K = 5


def _patterns_to_document(pattern_str: str | None) -> str:
    """Convert a semicolon-separated pattern string to a space-joined document."""
    if not pattern_str or not isinstance(pattern_str, str):
        return ""
    tokens = [t.strip() for t in pattern_str.split(";") if t.strip()]
    return " ".join(tokens)


def build_store(delegates_df: pd.DataFrame) -> dict[str, Any]:
    """Build dual TF-IDF store from delegates reference DataFrame.

    Parameters
    ----------
    delegates_df:
        DataFrame with at least columns:
        ``cons_id_str``, ``pattern``, ``minjaar``, ``maxjaar``.
        The ``pattern`` column is a semicolon-separated string of name variants.

    Returns
    -------
    dict with keys:
        ``vec_char``, ``vec_word``, ``mat_char``, ``mat_word``,
        ``ids``, ``meta``

        Where ``meta`` is a list of dicts with ``cons_id_str``, ``fullname``,
        ``minjaar``, ``maxjaar`` for each row in the index.
    """
    df = delegates_df.copy()
    df = df[df["cons_id_str"].notna()].reset_index(drop=True)

    # Build one text document per delegate
    documents = df["pattern"].apply(_patterns_to_document).tolist()

    vec_char = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        min_df=1,
        lowercase=True,
    )
    vec_word = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=1,
        lowercase=True,
    )

    mat_char: csr_matrix = vec_char.fit_transform(documents)
    mat_word: csr_matrix = vec_word.fit_transform(documents)

    meta = []
    for _, row in df.iterrows():
        meta.append(
            {
                "cons_id_str": str(row["cons_id_str"]),
                "fullname": row.get("fullname", ""),
                "minjaar": float(row["minjaar"]) if pd.notna(row.get("minjaar")) else None,
                "maxjaar": float(row["maxjaar"]) if pd.notna(row.get("maxjaar")) else None,
            }
        )

    return {
        "vec_char": vec_char,
        "vec_word": vec_word,
        "mat_char": mat_char,
        "mat_word": mat_word,
        "meta": meta,
        "n": len(meta),
    }


def match_ner(
    store: dict[str, Any],
    ner_df: pd.DataFrame,
    top_k: int = DEFAULT_TOP_K,
    year_tolerance: int = DEFAULT_YEAR_TOLERANCE,
    min_score: float = DEFAULT_MIN_SCORE,
) -> pd.DataFrame:
    """Match NER spans to known delegates using dual TF-IDF scoring.

    Parameters
    ----------
    store:
        Dict returned by :func:`build_store`.
    ner_df:
        DataFrame with columns ``tag_text`` (already cleaned via
        ``preprocess.clean_span``) and ``year`` (int).
    top_k:
        Number of candidate columns to include.
    year_tolerance:
        Years added/subtracted from a delegate's [minjaar, maxjaar] window
        when testing temporal overlap.  Set to a large value to disable.
    min_score:
        Combined scores below this threshold are zeroed out.

    Returns
    -------
    DataFrame with columns (one row per input span):
        span_idx, tag_text, year,
        cand_1 … cand_<top_k>, score_1 … score_<top_k>
    """
    vec_char = store["vec_char"]
    vec_word = store["vec_word"]
    mat_char: csr_matrix = store["mat_char"]
    mat_word: csr_matrix = store["mat_word"]
    meta: list[dict] = store["meta"]
    n_delegates = store["n"]

    texts = ner_df["tag_text"].fillna("").tolist()
    years = ner_df["year"].tolist()

    q_char = vec_char.transform(texts)
    q_word = vec_word.transform(texts)

    sim_char = cosine_similarity(q_char, mat_char)  # (n_spans, n_delegates)
    sim_word = cosine_similarity(q_word, mat_word)

    combined = _CHAR_WEIGHT * sim_char + _WORD_WEIGHT * sim_word  # (n_spans, n_delegates)

    # Pre-compute delegate year bounds as arrays for vectorised temporal gating
    del_min = np.array(
        [m["minjaar"] if m["minjaar"] is not None else -np.inf for m in meta],
        dtype=float,
    )
    del_max = np.array(
        [m["maxjaar"] if m["maxjaar"] is not None else np.inf for m in meta],
        dtype=float,
    )

    rows = []
    for i, (span_year, scores_row) in enumerate(zip(years, combined)):
        # Temporal gate: zero delegates active outside [span_year ± tolerance]
        mask = (del_min - year_tolerance <= span_year) & (span_year <= del_max + year_tolerance)
        scores_row = scores_row * mask

        # Apply min_score threshold
        scores_row[scores_row < min_score] = 0.0

        top_idx = np.argsort(scores_row)[::-1][:top_k]

        row: dict[str, Any] = {
            "span_idx": ner_df.index[i] if hasattr(ner_df.index, "__getitem__") else i,
            "tag_text": texts[i],
            "year": span_year,
        }
        for rank, idx in enumerate(top_idx, 1):
            sc = float(scores_row[idx])
            row[f"cand_{rank}"] = meta[idx]["cons_id_str"] if sc > 0 else None
            row[f"score_{rank}"] = round(sc, 4) if sc > 0 else 0.0

        rows.append(row)

    return pd.DataFrame(rows)

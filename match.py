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

import re
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from preprocess import normalize_name_for_matching

# Weight of char n-gram similarity vs word n-gram similarity
_CHAR_WEIGHT = 0.6
_WORD_WEIGHT = 0.4

# Default matching parameters
DEFAULT_YEAR_TOLERANCE = 0
DEFAULT_MIN_SCORE = 0.1
DEFAULT_TOP_K = 5
DEFAULT_ATTENDANCE_BOOST = 0.1


def build_attendance_year_index(attendance_paths: list[str]) -> dict[str, set[int]]:
    """Build a delegate_id -> set(year) index from attendance parquet files.

    The attendance exports in this ecosystem are not schema-stable across
    periods. This loader supports both formats observed in 1610-1630 and
    1705-1795 releases.
    """
    year_re = re.compile(r"\b(1[5-8]\d{2})\b")
    index: dict[str, set[int]] = {}

    for raw_path in attendance_paths:
        path = str(raw_path)
        df = pd.read_parquet(path)

        id_col = next((c for c in ["cons_id_str", "delegate_id", "unified_id"] if c in df.columns), None)
        if id_col is None:
            continue

        work = df.copy()
        if "presence_value" in work.columns:
            work = work[work["presence_value"].fillna(0).astype(float) > 0]
        if "present" in work.columns:
            work = work[work["present"].fillna(False).astype(bool)]

        years: pd.Series
        if "year" in work.columns:
            years = pd.to_numeric(work["year"], errors="coerce")
        elif "date" in work.columns:
            years = pd.to_datetime(work["date"], errors="coerce").dt.year
        elif "session_date" in work.columns:
            years = pd.to_datetime(work["session_date"], errors="coerce").dt.year
        elif "pattern" in work.columns:
            pattern_text = work["pattern"].map(lambda v: "" if pd.isna(v) else str(v))
            years = pattern_text.map(
                lambda s: int(year_re.search(s).group(1)) if year_re.search(s) else np.nan
            )
        else:
            continue

        work = work.assign(_year=years)
        work = work[work["_year"].notna()]
        work["_year"] = work["_year"].astype(int)
        work[id_col] = work[id_col].astype(str)

        grouped = work.groupby(id_col)["_year"].agg(lambda s: set(int(v) for v in s.tolist()))
        for delegate_id, year_set in grouped.items():
            if delegate_id not in index:
                index[delegate_id] = set()
            index[delegate_id].update(year_set)

    return index


def _patterns_to_document(pattern_str: str | None) -> str:
    """Convert a semicolon-separated pattern string to a space-joined document.

    Interposition abbreviations (v.d., v., …) are normalised so the index
    uses the same canonical forms as the span text cleaned by clean_span().
    """
    if not pattern_str or not isinstance(pattern_str, str):
        return ""
    tokens = [normalize_name_for_matching(t.strip()) for t in pattern_str.split(";") if t.strip()]
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
    attendance_years_by_id: dict[str, set[int]] | None = None,
    attendance_boost: float = DEFAULT_ATTENDANCE_BOOST,
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
    attendance_years_by_id:
        Optional delegate_id -> years index from attendance records.
        If provided, candidates attested in the mention year receive a
        multiplicative score boost.
    attendance_boost:
        Additive boost factor for attendance hits. Effective multiplier is
        ``1 + attendance_boost``.

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

    # Pre-compute delegate year bounds as arrays for vectorised temporal weighting
    del_min = np.array(
        [m["minjaar"] if m["minjaar"] is not None else -np.inf for m in meta],
        dtype=float,
    )
    del_max = np.array(
        [m["maxjaar"] if m["maxjaar"] is not None else np.inf for m in meta],
        dtype=float,
    )
    del_att_years = [
        attendance_years_by_id.get(str(m["cons_id_str"]), set()) if attendance_years_by_id else set()
        for m in meta
    ]

    rows = []
    for i, (span_year, scores_row) in enumerate(zip(years, combined)):
        # Temporal weighting uses the delegate's [minjaar, maxjaar] as primary range.
        # Inside range -> full weight. Outside range -> decays to 0 within tolerance.
        if year_tolerance <= 0:
            temporal_weight = ((del_min <= span_year) & (span_year <= del_max)).astype(float)
        else:
            delta_before = np.maximum(del_min - span_year, 0.0)
            delta_after = np.maximum(span_year - del_max, 0.0)
            delta = np.maximum(delta_before, delta_after)
            temporal_weight = 1.0 - (delta / float(year_tolerance))
            temporal_weight = np.clip(temporal_weight, 0.0, 1.0)
        scores_row = scores_row * temporal_weight

        if attendance_years_by_id and attendance_boost > 0:
            attendance_hit = np.fromiter(
                ((span_year in years) if years else False for years in del_att_years),
                dtype=bool,
                count=n_delegates,
            )
            scores_row = scores_row * np.where(attendance_hit, 1.0 + attendance_boost, 1.0)

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


# ---------------------------------------------------------------------------
# Optional Ollama tiebreaker — second-pass LLM verification
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"

# Uncertainty band: rows with top-1 score in this range are sent to Ollama
TIEBREAK_LOW = 0.20
TIEBREAK_HIGH = 0.55


def _ollama_verify(span_text: str, span_year: int, candidate_name: str) -> bool | None:
    """Ask a local Ollama model whether *span_text* refers to *candidate_name*.

    Returns ``True`` (confirmed), ``False`` (rejected), or ``None`` if the
    request fails or Ollama is unavailable.  Never raises.
    """
    import json
    import urllib.request

    prompt = (
        f"Context: Dutch Republic historical records, 17th/18th century.\n"
        f"Task: Determine if a name mention refers to a known delegate.\n\n"
        f"Name mention: \"{span_text}\"\n"
        f"Year of mention: {span_year}\n"
        f"Candidate delegate: \"{candidate_name}\"\n\n"
        f"Rules:\n"
        f"1. The mention may use archaic or abbreviated spellings.\n"
        f"2. Dutch tussenvoegsels (van, de, van der) may be omitted or abbreviated.\n"
        f"3. A person may be referred to by title or lordship instead of surname.\n"
        f"4. If the year is clearly outside the delegate's active period, answer NO.\n\n"
        f"Is it highly probable that \"{span_text}\" refers to \"{candidate_name}\"?\n"
        f"Answer only YES or NO."
    )
    payload = json.dumps(
        {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0}}
    ).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
        answer = body.get("response", "").strip().upper()
        if answer.startswith("YES"):
            return True
        if answer.startswith("NO"):
            return False
        return None
    except Exception:
        return None


def apply_ollama_tiebreaker(
    results: pd.DataFrame,
    store: dict,
    low: float = TIEBREAK_LOW,
    high: float = TIEBREAK_HIGH,
    ollama_url: str = OLLAMA_URL,
    model: str = OLLAMA_MODEL,
) -> pd.DataFrame:
    """Run Ollama verification on uncertain rows in a ``match_ner`` result.

    Rows where ``score_1`` falls in ``(low, high)`` are sent to the local
    Ollama instance.  A new column ``ollama_verified`` is added:

    - ``True``  — Ollama confirmed the top candidate
    - ``False`` — Ollama rejected it (cand_1 / score_1 are set to None / 0)
    - ``None``  — Ollama unreachable or inconclusive (result left unchanged)

    Parameters
    ----------
    results:
        DataFrame returned by :func:`match_ner`.
    store:
        The same store dict, used to resolve cons_id_str → fullname.
    low, high:
        Uncertainty band for ``score_1``.

    Returns
    -------
    The results DataFrame with an added ``ollama_verified`` column.
    """
    # Build id→fullname lookup from store metadata
    id_to_name: dict[str, str] = {m["cons_id_str"]: m["fullname"] for m in store["meta"]}

    results = results.copy()
    results["ollama_verified"] = None

    uncertain = results["score_1"].between(low, high, inclusive="neither")
    n = uncertain.sum()
    if n == 0:
        return results

    print(f"Ollama tiebreaker: checking {n} uncertain matches …")
    for idx in results.index[uncertain]:
        row = results.loc[idx]
        cand_id = row.get("cand_1")
        if not cand_id:
            continue
        candidate_name = id_to_name.get(str(cand_id), str(cand_id))
        verdict = _ollama_verify(str(row["tag_text"]), int(row["year"]), candidate_name)
        results.at[idx, "ollama_verified"] = verdict
        if verdict is False:
            results.at[idx, "cand_1"] = None
            results.at[idx, "score_1"] = 0.0

    return results

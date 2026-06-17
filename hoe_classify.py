"""
hoe_classify.py — Offline classifier for the HOE (honorifics/attributes) layer.

Reads the raw annotations-layer_HOE.tsv, counts all distinct tag_text forms,
classifies each form into a semantic category, and writes data/hoe_vocab.parquet.

Classification uses two external reference files:

  data/kws_hoe.py      — regex keyword dicts from republic_latest (kw_edelen,
                         kw_ambt, kw_beroep, kw_id, kw_pol, …).  Each entry maps
                         a regex pattern to a canonical HOE label (e.g. "ambassadeur").

  data/perscatrep.tsv  — person-category-representative table; maps canonical
                         labels (norm_term) to perscatrep categories
                         (person_profession, person_title, person_family, …).

Classification pipeline
-----------------------
  1. Noise filter  — reject spans matching dellpat exclusion list in kws_hoe.py.
  2. Keyword pass  — apply kws_hoe regex rules in priority order; first match
                     yields canonical_form; look that up in perscatrep for category.
  3. Fuzzy fallback — token_set_ratio against all perscatrep norm_terms; used when
                     no regex fires.

token_set_ratio is used in the fuzzy pass because HOE spans show two systematic
problems that break phrase-model matching:
  1. Word order variation — "extraordinaris envoyé" vs "envoyé extraordinaris"
  2. Interjected function words — "haar hoogh mogende extraordinaris envoyé aan
     het hof van" vs "haar hoog mog. extraordinaris envoyé"
token_set_ratio sorts and deduplicates tokens before comparing, so both problems
are absorbed without an exhaustive skip-gram index.

Usage
-----
    python hoe_classify.py [--hoe PATH] [--out PATH] [--threshold INT]
                           [--kws PATH] [--perscatrep PATH]

Outputs
-------
    data/hoe_vocab.parquet
        Columns: normalized_text, canonical, category, method, count, token_set_score

    data/hoe_category_counts.json
        Summary: total occurrences and distinct forms per category.
"""

from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import json
import pathlib
import pickle
import platform
import re
import sys
from typing import Optional

import pandas as pd
from rapidfuzz.fuzz import token_set_ratio

# ---------------------------------------------------------------------------
# Default data paths (relative to this file)
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).parent
_KWS_HOE_DEFAULT = _HERE / "data" / "kws_hoe.py"
_PERSCATREP_DEFAULT = _HERE / "data" / "perscatrep.tsv"
_HOE_STORE_DEFAULT = _HERE / "data" / "hoe_store.pkl"

# Dict name → fallback category when canonical form is not in perscatrep
_DICT_FALLBACK: dict[str, str] = {
    "kws_qual":  "person_title",
    "kw_edelen": "person_title",
    "kw_zlast":  "person_title",
    "kw_kerk":   "person_profession",
    "kw_ambt":   "person_profession",
    "kw_beroep": "person_profession",
    "kw_rest":   "person_profession",
    "kw_new":    "person_profession",
    "kw_pol":    "person_citizen",
    "kw_id":     "person_family",
}

# Priority order for regex matching (most specific first; kw_zlast last)
_DICT_ORDER = [
    "kw_edelen",
    "kw_kerk",
    "kw_ambt",
    "kw_beroep",
    "kw_id",
    "kw_pol",
    "kw_rest",
    "kw_new",
    "kws_qual",
    "kw_zlast",
]

# ---------------------------------------------------------------------------
# Lazy-loaded globals (populated on first classify() call)
# ---------------------------------------------------------------------------
# list of (compiled_regex, canonical_form, fallback_category)
_RULES: Optional[list[tuple[re.Pattern, str, str]]] = None
# {norm_term_lower: categorie}
_PERSCATREP: Optional[dict[str, str]] = None
# compiled noise/exclusion patterns from dellpat
_NOISE_PATS: Optional[list[re.Pattern]] = None
# TF-IDF cosine store (optional; loaded by init_classifiers or load_hoe_store)
_HOE_STORE: Optional[dict] = None


def _store_meta_path(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(f"{path}.meta.json")


def _runtime_metadata(perscatrep_path: pathlib.Path | None = None) -> dict[str, str]:
    import sklearn  # lazy import

    meta = {
        "python_version": platform.python_version(),
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "sklearn_version": sklearn.__version__,
    }
    if perscatrep_path is not None:
        meta["perscatrep_path"] = str(pathlib.Path(perscatrep_path).resolve())
    return meta


def _load_store_metadata(path: pathlib.Path) -> dict[str, str] | None:
    meta_path = _store_meta_path(path)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _store_matches_runtime(path: pathlib.Path, perscatrep_path: pathlib.Path | None = None) -> bool:
    meta = _load_store_metadata(path)
    if meta is None:
        return False

    runtime = _runtime_metadata(perscatrep_path)
    if meta.get("python_major_minor") != runtime["python_major_minor"]:
        return False
    if meta.get("sklearn_version") != runtime["sklearn_version"]:
        return False
    if perscatrep_path is not None and meta.get("perscatrep_path") != runtime.get("perscatrep_path"):
        return False
    return True


def ensure_hoe_store(
    store_path: pathlib.Path,
    perscatrep_path: pathlib.Path,
) -> pathlib.Path:
    """Ensure the TF-IDF store is compatible with the current runtime.

    Rebuilds the store when metadata is missing or the Python/scikit-learn
    environment differs from the environment that produced the pickle.
    """
    store_path = pathlib.Path(store_path)
    perscatrep_path = pathlib.Path(perscatrep_path)

    if store_path.exists() and _store_matches_runtime(store_path, perscatrep_path):
        return store_path

    store = build_hoe_store(perscatrep_path)
    save_hoe_store(store, store_path, perscatrep_path=perscatrep_path)
    return store_path


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------

def _load_kws_hoe(
    path: pathlib.Path,
) -> tuple[list[tuple[re.Pattern, str, str]], list[re.Pattern]]:
    """Load kws_hoe.py via importlib; return (rules, noise_patterns).

    rules: ordered list of (compiled_re, canonical_form, fallback_category).
    noise_patterns: compiled list of dellpat exclusion regexes.
    """
    spec = importlib.util.spec_from_file_location("kws_hoe", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load kws_hoe module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rules: list[tuple[re.Pattern, str, str]] = []
    for dict_name in _DICT_ORDER:
        d = getattr(mod, dict_name, None)
        if not isinstance(d, dict):
            continue
        fallback = _DICT_FALLBACK.get(dict_name, "person_profession")
        for pattern, canonical in d.items():
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                rules.append((compiled, str(canonical).lower(), fallback))
            except re.error:
                pass  # skip malformed patterns

    noise_pats: list[re.Pattern] = []
    dellpat = getattr(mod, "dellpat", [])
    if isinstance(dellpat, list):
        for p in dellpat:
            try:
                noise_pats.append(re.compile(p, re.IGNORECASE))
            except re.error:
                pass

    return rules, noise_pats


def _load_perscatrep(path: pathlib.Path) -> dict[str, str]:
    """Load perscatrep.tsv; return {norm_term_lower: categorie}."""
    df = pd.read_csv(
        path, sep="\t", usecols=["categorie", "norm_term"], dtype=str
    )
    df = df.dropna(subset=["categorie", "norm_term"])
    return dict(zip(df["norm_term"].str.lower().str.strip(), df["categorie"]))


def _ensure_loaded(
    kws_path: Optional[pathlib.Path] = None,
    perscatrep_path: Optional[pathlib.Path] = None,
) -> None:
    global _RULES, _PERSCATREP, _NOISE_PATS
    if _RULES is None:
        p = pathlib.Path(kws_path) if kws_path else _KWS_HOE_DEFAULT
        _RULES, _NOISE_PATS = _load_kws_hoe(p)
    if _PERSCATREP is None:
        p = pathlib.Path(perscatrep_path) if perscatrep_path else _PERSCATREP_DEFAULT
        _PERSCATREP = _load_perscatrep(p)


def init_classifiers(
    kws_path: Optional[pathlib.Path | str] = None,
    perscatrep_path: Optional[pathlib.Path | str] = None,
    store_path: Optional[pathlib.Path | str] = None,
) -> None:
    """Explicitly (re-)initialize classifier data.

    Call this before ``classify()`` if you want non-default paths.
    If not called, defaults to data/kws_hoe.py and data/perscatrep.tsv.

    If *store_path* points to an existing hoe_store.pkl, the TF-IDF store is
    loaded and used as the primary classification layer (faster and more
    general than regex for seen forms).  Build a store with build_hoe_store().
    """
    global _RULES, _PERSCATREP, _NOISE_PATS, _HOE_STORE
    _RULES = _PERSCATREP = _NOISE_PATS = _HOE_STORE = None
    _ensure_loaded(
        pathlib.Path(kws_path) if kws_path else None,
        pathlib.Path(perscatrep_path) if perscatrep_path else None,
    )
    if store_path is not None:
        p = pathlib.Path(store_path)
        perscatrep_p = pathlib.Path(perscatrep_path) if perscatrep_path else _PERSCATREP_DEFAULT
        p = ensure_hoe_store(p, perscatrep_p)
        if p.exists():
            _HOE_STORE = load_hoe_store(p)


# ---------------------------------------------------------------------------
# TF-IDF cosine store  (ML replacement for the regex keyword pass)
# ---------------------------------------------------------------------------

def build_hoe_store(perscatrep_path: pathlib.Path) -> dict:
    """Build a TF-IDF cosine index over all attested HOE spans in perscatrep.tsv.

    Each row's ``hoedanigheid_in_tag`` is indexed; query text is matched via
    cosine similarity to return the closest norm_term and categorie.

    This generalises far better to OCR variants and archaic orthography than
    the regex approach, while being fully language-agnostic (character n-grams
    require no vocabulary or language model).

    Returns a dict with keys: ``vec``, ``mat``, ``norms``, ``cats``, ``texts``.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer  # lazy import

    df = pd.read_csv(perscatrep_path, sep="\t", dtype=str).dropna(
        subset=["categorie", "norm_term", "hoedanigheid_in_tag"]
    )
    texts = [normalise(t) for t in df["hoedanigheid_in_tag"]]
    norms = df["norm_term"].str.lower().str.strip().tolist()
    cats = df["categorie"].str.strip().tolist()

    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    mat = vec.fit_transform(texts)
    return {"vec": vec, "mat": mat, "norms": norms, "cats": cats, "texts": texts}


def save_hoe_store(
    store: dict,
    path: pathlib.Path,
    perscatrep_path: pathlib.Path | None = None,
) -> None:
    """Persist a store dict and runtime metadata for compatibility checks."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(store, f, protocol=5)

    meta = _runtime_metadata(perscatrep_path)
    _store_meta_path(path).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_hoe_store(path: pathlib.Path) -> dict:
    """Load a store dict previously saved with save_hoe_store()."""
    with open(path, "rb") as f:
        return pickle.load(f)


def match_hoe_store(
    store: dict,
    text: str,
    top_k: int = 1,
) -> list[tuple[str, str, float]]:
    """Return top-k (canonical, category, cosine_score) for *text*.

    Scores are in [0, 1]; higher is better.
    """
    norm = normalise(text)
    q = store["vec"].transform([norm])
    scores = (store["mat"] @ q.T).toarray().ravel()
    top_idx = scores.argsort()[::-1][:top_k]
    return [
        (store["norms"][i], store["cats"][i], float(scores[i]))
        for i in top_idx
    ]

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[.,;:!?\-\(\)\[\]{}'\"/\\]")


def normalise(text: str) -> str:
    """Lowercase, strip leading/trailing whitespace, collapse internal spaces."""
    text = text.lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Two-pass classification
# ---------------------------------------------------------------------------

def _is_noise(text: str) -> bool:
    # dellpat patterns were designed to filter NLP parsing artifacts, not
    # attested HOE annotation spans.  Several patterns (e.g. r'^ *\bhaa?re?n?\b')
    # have no trailing $ anchor and would wrongly reject valid compound spans
    # like "haar hoogh mogende extraordinaris envoyé".  Since hoe_classify.py
    # operates on already-attested tag_text forms, we skip dellpat filtering.
    return False


def classify_keyword(text: str) -> tuple[str, str] | None:
    """Apply kws_hoe regex rules in priority order.

    Returns ``(canonical_form, category)`` on first match, else ``None``.
    category is resolved via perscatrep lookup; falls back to dict-level default.
    """
    _ensure_loaded()
    assert _RULES is not None and _PERSCATREP is not None
    for compiled, canonical, fallback in _RULES:
        if compiled.search(text):
            cat = _PERSCATREP.get(canonical, fallback)
            return canonical, cat
    return None


def classify_fuzzy(text: str, threshold: int = 70) -> tuple[str, str, int]:
    """token_set_ratio against all perscatrep norm_terms.

    Returns ``(canonical_form, category, best_score)``.
    Falls back to ``('other', 'other', score)`` when nothing exceeds *threshold*.
    """
    _ensure_loaded()
    assert _PERSCATREP is not None
    best_score = 0
    best_canonical = "other"
    best_cat = "other"
    for norm_term, cat in _PERSCATREP.items():
        score = int(round(token_set_ratio(text, norm_term)))
        if score > best_score:
            best_score = score
            best_canonical = norm_term
            best_cat = cat
    if best_score < threshold:
        return "other", "other", best_score
    return best_canonical, best_cat, best_score


def classify(
    text: str,
    threshold: int = 70,
    store_min_score: float = 0.15,
) -> tuple[str, str, str, int]:
    """Classify a raw HOE span.

    Returns ``(canonical_form, category, method, score)``.

    * method ``'tfidf'``   — matched via TF-IDF cosine store (primary ML path)
    * method ``'keyword'`` — matched a kws_hoe regex rule; score 100
    * method ``'fuzzy'``   — matched via token_set_ratio against perscatrep
    * method ``'other'``   — no match above threshold

    The TF-IDF store is used when one has been loaded via init_classifiers(
    store_path=...) or load_hoe_store().  It generalises better to unseen
    orthographic variants than the regex layer.
    """
    _ensure_loaded()
    norm = normalise(text)

    # 1. TF-IDF cosine store (primary ML layer; language-agnostic char n-grams)
    if _HOE_STORE is not None:
        hits = match_hoe_store(_HOE_STORE, text, top_k=1)
        canonical, cat, score = hits[0]
        if score >= store_min_score:
            return canonical, cat, "tfidf", round(score * 100)

    # 2. Regex keyword rules (deterministic fallback)
    if _is_noise(norm):
        return "noise", "other", "noise", 0
    result = classify_keyword(norm)
    if result is not None:
        canonical, cat = result
        return canonical, cat, "keyword", 100

    # 3. Fuzzy token-set-ratio (last resort)
    canonical, cat, score = classify_fuzzy(norm, threshold)
    return canonical, cat, "fuzzy", score


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_vocab(hoe_path: pathlib.Path) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    with open(hoe_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            counts[row["tag_text"].strip().lower()] += 1
    return counts


def classify_all(
    counts: collections.Counter,
    threshold: int = 70,
) -> pd.DataFrame:
    rows = []
    for text, count in counts.items():
        canonical, cat, method, score = classify(text, threshold)
        rows.append({
            "normalized_text": text,
            "canonical": canonical,
            "category": cat,
            "method": method,
            "token_set_score": score,
            "count": count,
        })
    df = pd.DataFrame(rows)
    df = df.sort_values(["category", "count"], ascending=[True, False])
    df = df.reset_index(drop=True)
    return df


def summarise(df: pd.DataFrame) -> dict:
    summary = {}
    for cat, grp in df.groupby("category"):
        summary[cat] = {
            "total_occurrences": int(grp["count"].sum()),
            "distinct_forms": len(grp),
            "top_forms": grp.nlargest(10, "count")["normalized_text"].tolist(),
        }
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hoe",
        default=(
            pathlib.Path.home()
            / "Downloads/annotations-unaggregated/annotations-layer_HOE.tsv"
        ),
        type=pathlib.Path,
        help="Path to annotations-layer_HOE.tsv",
    )
    parser.add_argument(
        "--out",
        default=pathlib.Path("data/hoe_vocab.parquet"),
        type=pathlib.Path,
        help="Output parquet path",
    )
    parser.add_argument(
        "--summary",
        default=pathlib.Path("data/hoe_category_counts.json"),
        type=pathlib.Path,
        help="Output summary JSON path",
    )
    parser.add_argument(
        "--threshold",
        default=70,
        type=int,
        help="Minimum token_set_ratio score for fuzzy fallback (default 70)",
    )
    parser.add_argument(
        "--kws",
        default=None,
        type=pathlib.Path,
        help="Path to kws_hoe.py keyword dict (default: data/kws_hoe.py)",
    )
    parser.add_argument(
        "--perscatrep",
        default=None,
        type=pathlib.Path,
        help="Path to perscatrep.tsv category table (default: data/perscatrep.tsv)",
    )
    parser.add_argument(
        "--store",
        default=None,
        type=pathlib.Path,
        help="Path to hoe_store.pkl TF-IDF store (optional; use as primary classifier)",
    )
    parser.add_argument(
        "--build-store",
        action="store_true",
        help="Build and save a TF-IDF store from --perscatrep before classifying",
    )
    args = parser.parse_args(argv)

    # Optionally build+save the TF-IDF store
    if args.build_store:
        perscatrep_p = args.perscatrep or _PERSCATREP_DEFAULT
        store_p = args.store or _HOE_STORE_DEFAULT
        print(f"Building TF-IDF store from {perscatrep_p} …", file=sys.stderr)
        store = build_hoe_store(perscatrep_p)
        save_hoe_store(store, store_p, perscatrep_path=perscatrep_p)
        print(f"  Store saved → {store_p}", file=sys.stderr)

    init_classifiers(args.kws, args.perscatrep, args.store)

    print(f"Reading {args.hoe} …", file=sys.stderr)
    counts = build_vocab(args.hoe)
    print(f"  {len(counts):,} distinct forms, {sum(counts.values()):,} total", file=sys.stderr)

    print("Classifying …", file=sys.stderr)
    df = classify_all(counts, threshold=args.threshold)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)
    print(f"  Written → {args.out}", file=sys.stderr)

    summary = summarise(df)
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Summary → {args.summary}", file=sys.stderr)

    # quick report
    print("\nCategory summary (total occurrences):", file=sys.stderr)
    for cat, info in sorted(summary.items(), key=lambda x: -x[1]["total_occurrences"]):
        print(
            f"  {info['total_occurrences']:>9,}  {info['distinct_forms']:>7,} forms  {cat}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

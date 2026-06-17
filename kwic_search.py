"""
kwic_search.py — KWIC (keyword in context) index for HOE spans.

Parses the CoNLL BIO training data from the Republic NER project and builds a
searchable index of all tagged HOE spans with their surrounding sentence context.
Each span is classified with hoe_classify so you can filter and browse by
semantic category (person_profession, person_title, etc.).

Typical usage
-------------
Build the index once (saves to data/kwic_index.pkl):

    python kwic_search.py --build \
        --conll /path/to/flair_training_HOE \
        --out data/kwic_index.pkl

Then search interactively or from code:

    from kwic_search import KWICIndex
    idx = KWICIndex.load("data/kwic_index.pkl")

    # fuzzy span search
    for hit in idx.search("ambassadeur", top_k=10):
        print(hit.kwic_display())

    # filter by category
    for hit in idx.search("envoyé", top_k=20, category="person_profession"):
        print(hit.kwic_display())

    # context search — find spans where the surrounding sentence contains a word
    for hit in idx.context_search("Franckrijck", top_k=10):
        print(hit.kwic_display())

Measurement
-----------
idx.coverage_report() prints per-category counts and the fraction of spans
that classify as 'other' (= unknown / not in hoe_classify dictionaries).

This gives you a direct measure of hoe_classify's recall on real in-context
material, and a starting point for comparing isolated-span vs. KWIC
classification approaches.
"""

from __future__ import annotations

import pathlib
import pickle
import re
import sys
from dataclasses import dataclass, field
from typing import Iterator, Optional

import pandas as pd
from rapidfuzz import fuzz, process as rfprocess

import hoe_classify

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).parent
_DEFAULT_CONLL_DIR = pathlib.Path(
    "/Users/rikhoekstra/develop/republicgit/ground_truth/"
    "tag_de_besluiten/flair_training/flair_training_HOE"
)
_DEFAULT_INDEX = _HERE / "data" / "kwic_index.pkl"

# CoNLL files to include (all splits so we have maximum context variety)
_CONLL_FILES = ["train_1.0.txt", "validate.txt", "test.txt"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class KWICRecord:
    """One tagged HOE span with its sentence context.

    Attributes
    ----------
    span_text : str
        The raw concatenated span tokens (as they appear in the source).
    left_tokens : list[str]
        Tokens to the left of the span within the sentence.
    right_tokens : list[str]
        Tokens to the right of the span within the sentence.
    canonical : str
        Normalised canonical form returned by hoe_classify.
    category : str
        Semantic category (person_profession, person_title, …, other).
    method : str
        Classification method (tfidf / keyword / fuzzy / other).
    score : int
        Classifier confidence 0–100.
    source : str
        Source filename (train_1.0.txt / validate.txt / test.txt).
    """
    span_text: str
    left_tokens: list[str]
    right_tokens: list[str]
    canonical: str
    category: str
    method: str
    score: int
    source: str

    @property
    def sentence_text(self) -> str:
        """Full sentence as a single string."""
        return " ".join(self.left_tokens + [self.span_text] + self.right_tokens)

    def kwic_display(self, window: int = 8) -> str:
        """Return a fixed-width KWIC line.

        Shows up to *window* tokens on each side of the span.

            left context  |  **SPAN**  |  right context   [category]
        """
        left = " ".join(self.left_tokens[-window:])
        right = " ".join(self.right_tokens[:window])
        cat_label = f"[{self.category}]" if self.category != "other" else "[?]"
        return f"{left:>50}  |  {self.span_text}  |  {right:<50}  {cat_label}"


# ---------------------------------------------------------------------------
# CoNLL parsing
# ---------------------------------------------------------------------------

def _iter_sentences(path: pathlib.Path) -> Iterator[list[tuple[str, str]]]:
    """Yield one sentence at a time as list of (token, tag) pairs."""
    sentence: list[tuple[str, str]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                if sentence:
                    yield sentence
                    sentence = []
            else:
                parts = line.split()
                if len(parts) >= 2:
                    sentence.append((parts[0], parts[-1]))
    if sentence:
        yield sentence


def _extract_spans(
    sentences: Iterator[list[tuple[str, str]]], source: str
) -> Iterator[KWICRecord]:
    """For each sentence, yield one KWICRecord per HOE span found."""
    for sent in sentences:
        tokens = [t for t, _ in sent]
        tags = [g for _, g in sent]

        i = 0
        while i < len(tags):
            if tags[i] == "B-HOE":
                j = i + 1
                while j < len(tags) and tags[j] == "I-HOE":
                    j += 1
                span_tokens = tokens[i:j]
                span_text = " ".join(span_tokens)

                canonical, cat, method, score = hoe_classify.classify(span_text)
                record = KWICRecord(
                    span_text=span_text,
                    left_tokens=tokens[:i],
                    right_tokens=tokens[j:],
                    canonical=canonical,
                    category=cat,
                    method=method,
                    score=score,
                    source=source,
                )
                yield record
                i = j
            else:
                i += 1


def build_records(conll_dir: pathlib.Path) -> list[KWICRecord]:
    """Parse all CoNLL files in *conll_dir* and return a list of KWICRecords."""
    hoe_classify.init_classifiers()
    records: list[KWICRecord] = []
    for fname in _CONLL_FILES:
        p = conll_dir / fname
        if not p.exists():
            print(f"  Skipping missing file: {p}", file=sys.stderr)
            continue
        print(f"  Parsing {p.name} …", file=sys.stderr)
        for rec in _extract_spans(_iter_sentences(p), fname):
            records.append(rec)
    print(f"  Total spans: {len(records):,}", file=sys.stderr)
    return records


# ---------------------------------------------------------------------------
# Searchable index
# ---------------------------------------------------------------------------

class KWICIndex:
    """Searchable KWIC index over all HOE spans.

    Two search modes:
    - ``search(query)``         — fuzzy-match against span texts (rapidfuzz)
    - ``context_search(query)`` — substring search in the full sentence text

    Build with ``KWICIndex.build(conll_dir)`` and persist with ``.save()``.
    """

    def __init__(self, records: list[KWICRecord]) -> None:
        self.records = records
        # Pre-compute normalised span texts for fast fuzzy matching
        self._norm_spans: list[str] = [
            hoe_classify.normalise(r.span_text) for r in records
        ]
        # Pre-compute lower-case full sentences for context search
        self._sentences_lower: list[str] = [
            r.sentence_text.lower() for r in records
        ]

    # ------------------------------------------------------------------
    # Construction / persistence
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, conll_dir: pathlib.Path = _DEFAULT_CONLL_DIR) -> "KWICIndex":
        """Parse CoNLL files and build the index."""
        records = build_records(conll_dir)
        return cls(records)

    @classmethod
    def build_from_csv(
        cls,
        csv_path: pathlib.Path,
        text_col: str = "cleaned_text",
        source_col: str = "filename",
        window_tokens: int = 10,
        min_score: int = 75,
        max_rows: Optional[int] = None,
    ) -> "KWICIndex":
        """Build an index by scanning raw letter/document text in a CSV/TSV.

        Unlike ``build()``, no BIO annotations are required: kws_hoe regex
        rules are applied directly to the full text of each row.

        Parameters
        ----------
        csv_path : pathlib.Path
            Tab- or comma-separated file containing a text column.
        text_col : str
            Column with the full text to scan.
        source_col : str
            Column used as the ``source`` label on each record.
        window_tokens : int
            Context window passed to :func:`scan_text`.
        min_score : int
            Minimum classifier score to include a span.
        max_rows : int, optional
            Limit the number of rows processed (useful for development).
        """
        records = build_records_from_csv(
            csv_path,
            text_col=text_col,
            source_col=source_col,
            window_tokens=window_tokens,
            min_score=min_score,
            max_rows=max_rows,
        )
        return cls(records)

    def save(self, path: pathlib.Path = _DEFAULT_INDEX) -> None:
        """Persist the index to a pickle file."""
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=5)
        print(f"Index saved → {path}", file=sys.stderr)

    @classmethod
    def load(cls, path: pathlib.Path = _DEFAULT_INDEX) -> "KWICIndex":
        """Load a previously saved index.

        Handles pickles saved when kwic_search was run as ``__main__``
        (e.g. via the CLI) by remapping the module name on load.
        """
        import kwic_search as _self_mod  # may be __main__ when run as script

        class _Unpickler(pickle.Unpickler):
            def find_class(self, module: str, name: str):
                # Remap __main__ → kwic_search so CLI-built pickles load fine
                # in notebooks and other import contexts.
                if module == "__main__":
                    module = _self_mod.__name__
                return super().find_class(module, name)

        with open(pathlib.Path(path), "rb") as f:
            return _Unpickler(f).load()

    def save_jsonl(self, path: pathlib.Path) -> None:
        """Write every record to a JSONL file (one JSON object per line).

        The file can be loaded back with :meth:`load_jsonl`, inspected with any
        text editor, filtered with ``grep``, or read into pandas with::

            pd.read_json("kwic_index.jsonl", lines=True)

        ``left_tokens`` and ``right_tokens`` are stored as space-joined strings
        (not lists) so grep on context works without needing JSON parsing.
        """
        import json
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for r in self.records:
                obj = {
                    "span_text": r.span_text,
                    "left_context": " ".join(r.left_tokens),
                    "right_context": " ".join(r.right_tokens),
                    "canonical": r.canonical,
                    "category": r.category,
                    "method": r.method,
                    "score": r.score,
                    "source": r.source,
                }
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        print(f"JSONL saved  → {path}  ({len(self.records):,} records)", file=sys.stderr)

    @classmethod
    def load_jsonl(cls, path: pathlib.Path) -> "KWICIndex":
        """Reconstruct a KWICIndex from a JSONL file written by :meth:`save_jsonl`."""
        import json
        records: list[KWICRecord] = []
        with open(pathlib.Path(path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                records.append(KWICRecord(
                    span_text=obj["span_text"],
                    left_tokens=obj["left_context"].split(),
                    right_tokens=obj["right_context"].split(),
                    canonical=obj["canonical"],
                    category=obj["category"],
                    method=obj["method"],
                    score=obj["score"],
                    source=obj["source"],
                ))
        return cls(records)

    def to_dataframe(self) -> "pd.DataFrame":
        """Return all records as a DataFrame (one row per span)."""
        return pd.DataFrame([
            {
                "span_text": r.span_text,
                "left_context": " ".join(r.left_tokens),
                "right_context": " ".join(r.right_tokens),
                "canonical": r.canonical,
                "category": r.category,
                "method": r.method,
                "score": r.score,
                "source": r.source,
            }
            for r in self.records
        ])

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 20,
        category: Optional[str] = None,
        min_score: int = 60,
    ) -> list[KWICRecord]:
        """Fuzzy-search span texts for *query*.

        Parameters
        ----------
        query : str
            The span text to search for (e.g. "ambassadeur", "envoyé").
        top_k : int
            Maximum number of results.
        category : str, optional
            Restrict results to this category (e.g. "person_profession").
        min_score : int
            Minimum rapidfuzz token_set_ratio score (0–100).

        Returns
        -------
        list[KWICRecord]
            Hits sorted by descending match score.
        """
        norm_query = hoe_classify.normalise(query)

        # Filter by category first (cheap)
        if category:
            pool_idxs = [i for i, r in enumerate(self.records) if r.category == category]
        else:
            pool_idxs = list(range(len(self.records)))

        pool_norms = [self._norm_spans[i] for i in pool_idxs]

        # rapidfuzz extracting with token_set_ratio handles word-order variation
        matches = rfprocess.extract(
            norm_query,
            pool_norms,
            scorer=fuzz.token_set_ratio,
            limit=top_k * 3,  # over-fetch before score filter
            score_cutoff=min_score,
        )

        results: list[tuple[int, float]] = []
        seen_spans: set[str] = set()
        for match_str, score, local_idx in matches:
            global_idx = pool_idxs[local_idx]
            span_norm = self._norm_spans[global_idx]
            # De-duplicate identical spans, keeping highest score
            if span_norm not in seen_spans:
                seen_spans.add(span_norm)
                results.append((global_idx, score))

        results.sort(key=lambda x: -x[1])
        return [self.records[i] for i, _ in results[:top_k]]

    def context_search(
        self,
        query: str,
        top_k: int = 20,
        category: Optional[str] = None,
    ) -> list[KWICRecord]:
        """Return records whose sentence contains *query* (case-insensitive substring).

        Useful for finding all HOE spans that co-occur with a place name,
        a verb, or a formulaic phrase.

        Parameters
        ----------
        query : str
            Substring to search for in the full sentence text.
        top_k : int
            Maximum results.
        category : str, optional
            Restrict to this category.
        """
        q = query.lower()
        results = [
            r
            for r, sent in zip(self.records, self._sentences_lower)
            if q in sent and (category is None or r.category == category)
        ]
        return results[:top_k]

    def search_df(
        self,
        query: str,
        top_k: int = 20,
        category: Optional[str] = None,
        min_score: int = 60,
        mode: str = "span",
    ) -> pd.DataFrame:
        """Like ``search`` / ``context_search`` but returns a DataFrame.

        Parameters
        ----------
        mode : 'span' (default) or 'context'
        """
        if mode == "context":
            records = self.context_search(query, top_k=top_k, category=category)
        else:
            records = self.search(query, top_k=top_k, category=category, min_score=min_score)

        rows = []
        for r in records:
            rows.append({
                "span": r.span_text,
                "canonical": r.canonical,
                "category": r.category,
                "score": r.score,
                "method": r.method,
                "left": " ".join(r.left_tokens[-8:]),
                "right": " ".join(r.right_tokens[:8]),
                "source": r.source,
            })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Measurement / evaluation
    # ------------------------------------------------------------------

    def coverage_report(self) -> pd.DataFrame:
        """Per-category count and fraction of classified vs. 'other'.

        This measures hoe_classify's recall on real in-context material:
        how many attested HOE spans does the classifier actually recognise?
        """
        rows = []
        for r in self.records:
            rows.append({"category": r.category, "method": r.method, "source": r.source})
        df = pd.DataFrame(rows)

        total = len(df)
        classified = (df["category"] != "other").sum()

        cat_counts = df.groupby("category").size().rename("count").reset_index()
        cat_counts["fraction"] = cat_counts["count"] / total
        cat_counts = cat_counts.sort_values("count", ascending=False).reset_index(drop=True)

        print(f"\nTotal HOE spans: {total:,}", file=sys.stderr)
        print(f"Classified (non-other): {classified:,} ({classified/total:.1%})", file=sys.stderr)
        print(f"Other / unclassified:   {total-classified:,} ({(total-classified)/total:.1%})", file=sys.stderr)

        return cat_counts

    def method_report(self) -> pd.DataFrame:
        """Breakdown of which classification layer fired."""
        rows = [{"method": r.method, "category": r.category} for r in self.records]
        df = pd.DataFrame(rows)
        return df.groupby(["method", "category"]).size().rename("count").reset_index() \
                 .sort_values(["method", "count"], ascending=[True, False]) \
                 .reset_index(drop=True)

    def sample(
        self,
        category: str,
        n: int = 10,
        random_state: int = 42,
    ) -> list[KWICRecord]:
        """Return *n* random records from *category*."""
        import random
        rng = random.Random(random_state)
        pool = [r for r in self.records if r.category == category]
        return rng.sample(pool, min(n, len(pool)))

    def __len__(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        return f"KWICIndex({len(self.records):,} spans)"


# ---------------------------------------------------------------------------
# Raw-text scanner (no BIO annotation required)
# ---------------------------------------------------------------------------

def scan_text(
    text: str,
    source: str = "",
    window_tokens: int = 10,
    min_score: int = 75,
) -> list[KWICRecord]:
    """Find HOE spans in a raw (un-annotated) text.

    Uses the compiled kws_hoe regex rules from hoe_classify to locate candidate
    spans, then classifies each match.  Only matches with classifier score >=
    *min_score* are returned.

    Parameters
    ----------
    text : str
        Full text to scan (a letter, paragraph, etc.).
    source : str
        Label stored in each KWICRecord.source (e.g. the letter filename).
    window_tokens : int
        Number of whitespace-delimited tokens to include on each side of the
        span in the KWIC record.
    min_score : int
        Minimum hoe_classify score to keep a hit (0–100).

    Returns
    -------
    list[KWICRecord]
        One record per identified HOE span, with surrounding context.
    """
    hoe_classify._ensure_loaded()  # type: ignore[attr-defined]

    records: list[KWICRecord] = []
    seen_spans: set[tuple[int, int]] = set()

    for pat, canonical, fallback_cat in hoe_classify._RULES:  # type: ignore[union-attr]
        for m in pat.finditer(text):
            start, end = m.start(), m.end()
            # Skip if already covered by a higher-priority rule
            if any(s <= start and end <= e for s, e in seen_spans):
                continue
            span_text = text[start:end].strip()
            if not span_text:
                continue
            # Classify the span
            can, cat, method, score = hoe_classify.classify(span_text)
            if score < min_score:
                continue
            seen_spans.add((start, end))
            # Build token-level context from the full text
            # Split on whitespace, locate the approximate position
            pre = text[:start]
            post = text[end:]
            left_toks = pre.split()[-window_tokens:]
            right_toks = post.split()[:window_tokens]
            records.append(KWICRecord(
                span_text=span_text,
                left_tokens=left_toks,
                right_tokens=right_toks,
                canonical=can,
                category=cat,
                method=method,
                score=score,
                source=source,
            ))

    # Sort by position in text (approximate: left context length)
    records.sort(key=lambda r: len(" ".join(r.left_tokens)))
    return records


def build_records_from_csv(
    csv_path: pathlib.Path,
    text_col: str = "cleaned_text",
    source_col: str = "filename",
    window_tokens: int = 10,
    min_score: int = 75,
    max_rows: Optional[int] = None,
) -> list[KWICRecord]:
    """Scan all rows of a CSV for HOE spans using scan_text().

    Parameters
    ----------
    csv_path : pathlib.Path
        Path to a CSV/TSV file with a text column.
    text_col : str
        Column containing the full text to scan.
    source_col : str
        Column to use as the KWICRecord.source label.
    window_tokens : int
        Passed to scan_text().
    min_score : int
        Minimum classifier score to include a hit.
    max_rows : int, optional
        Process only this many rows (useful for development).

    Returns
    -------
    list[KWICRecord]
    """
    hoe_classify.init_classifiers()
    sep = "\t" if str(csv_path).endswith((".tsv", ".csv")) else ","
    df = pd.read_csv(csv_path, sep=sep, dtype=str)

    # Auto-detect separator: if only one column read, retry with comma
    if df.shape[1] == 1:
        df = pd.read_csv(csv_path, sep=",", dtype=str)

    if text_col not in df.columns:
        raise ValueError(f"Column '{text_col}' not found. Available: {list(df.columns)}")

    if max_rows:
        df = df.head(max_rows)

    records: list[KWICRecord] = []
    for _, row in df.iterrows():
        text = str(row.get(text_col, "") or "")
        source = str(row.get(source_col, "") or "")
        if not text or text == "nan":
            continue
        recs = scan_text(text, source=source, window_tokens=window_tokens, min_score=min_score)
        records.extend(recs)

    print(f"  Scanned {len(df):,} rows → {len(records):,} HOE spans found", file=sys.stderr)
    return records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build or search the HOE KWIC index."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # build
    p_build = sub.add_parser("build", help="Parse CoNLL files and build the index.")
    p_build.add_argument("--conll", type=pathlib.Path, default=_DEFAULT_CONLL_DIR)
    p_build.add_argument("--out", type=pathlib.Path, default=_DEFAULT_INDEX)
    p_build.add_argument("--save-jsonl", action="store_true",
                         help="Also write a .jsonl alongside the pickle.")

    # search
    p_search = sub.add_parser("search", help="Search the index for a query.")
    p_search.add_argument("query")
    p_search.add_argument("--index", type=pathlib.Path, default=_DEFAULT_INDEX)
    p_search.add_argument("--top-k", type=int, default=20)
    p_search.add_argument("--category", default=None)
    p_search.add_argument("--mode", choices=["span", "context"], default="span")
    p_search.add_argument("--min-score", type=int, default=60)

    # report
    p_report = sub.add_parser("report", help="Print coverage report.")
    p_report.add_argument("--index", type=pathlib.Path, default=_DEFAULT_INDEX)

    # build-csv (scan raw text from a CSV/TSV)
    p_csv = sub.add_parser("build-csv", help="Build index by scanning raw text in a CSV/TSV.")
    p_csv.add_argument("csv", type=pathlib.Path, help="CSV/TSV file to scan.")
    p_csv.add_argument("--text-col", default="cleaned_text")
    p_csv.add_argument("--source-col", default="filename")
    p_csv.add_argument("--out", type=pathlib.Path, default=_DEFAULT_INDEX)
    p_csv.add_argument("--min-score", type=int, default=75)
    p_csv.add_argument("--max-rows", type=int, default=None)
    p_csv.add_argument("--save-jsonl", action="store_true",
                       help="Also write a .jsonl alongside the pickle.")

    # export — convert an existing pkl to JSONL (or vice versa)
    p_export = sub.add_parser(
        "export", help="Export a saved pkl index to JSONL (human-readable)."
    )
    p_export.add_argument("--index", type=pathlib.Path, default=_DEFAULT_INDEX)
    p_export.add_argument("--out", type=pathlib.Path, default=None,
                          help="Output path (default: same stem as index, .jsonl).")

    args = parser.parse_args(argv)

    if args.cmd == "build":
        print(f"Building index from {args.conll} …", file=sys.stderr)
        idx = KWICIndex.build(args.conll)
        idx.save(args.out)
        if args.save_jsonl:
            idx.save_jsonl(args.out.with_suffix(".jsonl"))
        idx.coverage_report()

    elif args.cmd == "search":
        idx = KWICIndex.load(args.index)
        hits = idx.search(args.query, args.top_k, args.category, args.min_score) \
            if args.mode == "span" \
            else idx.context_search(args.query, args.top_k, args.category)
        for h in hits:
            print(h.kwic_display())

    elif args.cmd == "report":
        idx = KWICIndex.load(args.index)
        df = idx.coverage_report()
        print(df.to_string(index=False))
        print()
        print(idx.method_report().to_string(index=False))

    elif args.cmd == "build-csv":
        print(f"Scanning {args.csv} …", file=sys.stderr)
        records = build_records_from_csv(
            args.csv,
            text_col=args.text_col,
            source_col=args.source_col,
            min_score=args.min_score,
            max_rows=args.max_rows,
        )
        idx = KWICIndex(records)
        idx.save(args.out)
        if args.save_jsonl:
            idx.save_jsonl(args.out.with_suffix(".jsonl"))
        idx.coverage_report()

    elif args.cmd == "export":
        idx = KWICIndex.load(args.index)
        out = args.out or pathlib.Path(args.index).with_suffix(".jsonl")
        idx.save_jsonl(out)


if __name__ == "__main__":
    main()

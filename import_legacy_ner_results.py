from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def iter_sentences(tag_file: Path):
    sentence_tokens: list[str] = []
    sentence_tags: list[str] = []

    with tag_file.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                if sentence_tokens:
                    yield sentence_tokens, sentence_tags
                    sentence_tokens, sentence_tags = [], []
                continue

            parts = line.split("\t")
            if len(parts) != 2:
                parts = line.split()
                if len(parts) < 2:
                    continue
                token = parts[0]
                tag = parts[-1]
            else:
                token, tag = parts

            sentence_tokens.append(token)
            sentence_tags.append(tag)

    if sentence_tokens:
        yield sentence_tokens, sentence_tags


def extract_per_spans(tokens: list[str], tags: list[str]):
    spans: list[tuple[int, int, str]] = []
    i = 0
    while i < len(tags):
        if tags[i] == "B-PER":
            j = i + 1
            while j < len(tags) and tags[j] == "I-PER":
                j += 1
            span_text = " ".join(tokens[i:j])
            spans.append((i, j - 1, span_text))
            i = j
        else:
            i += 1
    return spans


def build_legacy_ner_per_df(source_root: Path) -> pd.DataFrame:
    rows: list[dict] = []
    tag_files = sorted(source_root.glob("session-*/tag_PER.tsv"))

    for tag_file in tag_files:
        source_file = tag_file.parent.name
        for sentence_idx, (tokens, tags) in enumerate(iter_sentences(tag_file)):
            sentence_text = " ".join(tokens)
            spans = extract_per_spans(tokens, tags)
            for span_idx, (tok_start, tok_end, span_text) in enumerate(spans):
                rows.append(
                    {
                        "source_file": source_file,
                        "sentence_idx": sentence_idx,
                        "span_idx": span_idx,
                        "token_start": tok_start,
                        "token_end": tok_end,
                        "span_text": span_text,
                        "sentence_text": sentence_text,
                        "tag_file": str(tag_file),
                    }
                )

    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import legacy tag_PER.tsv outputs into a consolidated parquet.")
    p.add_argument(
        "--source-root",
        default="/Users/rikhoekstra/develop/republic_latest/ground_truth/tag_de_besluiten/tag_de_besluiten/tdb-data",
        help="Root directory containing session-*/tag_PER.tsv files.",
    )
    p.add_argument(
        "--out",
        default="data/eval/ner_legacy_per_spans.parquet",
        help="Output parquet path.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    source_root = Path(args.source_root)
    out_path = Path(args.out)

    if not source_root.exists():
        raise FileNotFoundError(f"Missing source root: {source_root}")

    df = build_legacy_ner_per_df(source_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)

    print(f"Imported legacy NER PER spans: {len(df):,}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()

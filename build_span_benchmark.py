from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).parent
GROUND_TRUTH_DIR = Path(
    "/Users/rikhoekstra/develop/republicgit/ground_truth/tag_de_besluiten/"
    "flair_training/flair_training_PER"
)
OUT_DIR = ROOT / "data" / "eval"
SPLITS = ("validate.txt", "test.txt")


def parse_bio_spans(path: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    tokens: list[str] = []
    tags: list[str] = []
    sentence_idx = 0
    span_idx = 0

    def flush_sentence() -> None:
        nonlocal sentence_idx, span_idx, tokens, tags
        if not tokens:
            return

        start: int | None = None
        current_label: str | None = None
        for idx, tag in enumerate(tags):
            if tag.startswith("B-"):
                if start is not None:
                    rows.append(
                        {
                            "split": path.stem,
                            "source_file": path.name,
                            "sentence_idx": sentence_idx,
                            "span_idx": span_idx,
                            "label": current_label,
                            "token_start": start,
                            "token_end": idx,
                            "span_text": " ".join(tokens[start:idx]),
                            "sentence_text": " ".join(tokens),
                        }
                    )
                    span_idx += 1
                start = idx
                current_label = tag[2:]
            elif tag.startswith("I-"):
                label = tag[2:]
                if start is None or current_label != label:
                    if start is not None:
                        rows.append(
                            {
                                "split": path.stem,
                                "source_file": path.name,
                                "sentence_idx": sentence_idx,
                                "span_idx": span_idx,
                                "label": current_label,
                                "token_start": start,
                                "token_end": idx,
                                "span_text": " ".join(tokens[start:idx]),
                                "sentence_text": " ".join(tokens),
                            }
                        )
                        span_idx += 1
                    start = idx
                    current_label = label
            else:
                if start is not None:
                    rows.append(
                        {
                            "split": path.stem,
                            "source_file": path.name,
                            "sentence_idx": sentence_idx,
                            "span_idx": span_idx,
                            "label": current_label,
                            "token_start": start,
                            "token_end": idx,
                            "span_text": " ".join(tokens[start:idx]),
                            "sentence_text": " ".join(tokens),
                        }
                    )
                    span_idx += 1
                    start = None
                    current_label = None

        if start is not None:
            rows.append(
                {
                    "split": path.stem,
                    "source_file": path.name,
                    "sentence_idx": sentence_idx,
                    "span_idx": span_idx,
                    "label": current_label,
                    "token_start": start,
                    "token_end": len(tokens),
                    "span_text": " ".join(tokens[start:]),
                    "sentence_text": " ".join(tokens),
                }
            )
            span_idx += 1

        sentence_idx += 1
        tokens = []
        tags = []

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if not line.strip():
                flush_sentence()
                continue
            token, tag = line.rsplit(maxsplit=1)
            tokens.append(token)
            tags.append(tag)

    flush_sentence()
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, object]] = []
    for split in SPLITS:
        path = GROUND_TRUTH_DIR / split
        if not path.exists():
            raise FileNotFoundError(f"Missing PER BIO file: {path}")

        spans = parse_bio_spans(path)
        out_path = OUT_DIR / f"per_span_gold_{path.stem}.parquet"
        spans.to_parquet(out_path, index=False)

        summaries.append(
            {
                "split": path.stem,
                "source_path": str(path),
                "rows": int(len(spans)),
                "sentences": int(spans["sentence_idx"].nunique()) if not spans.empty else 0,
                "labels": spans["label"].value_counts().to_dict(),
                "output_path": str(out_path),
            }
        )

    summary_path = OUT_DIR / "span_benchmark_summary.json"
    summary_path.write_text(json.dumps(summaries, indent=2, ensure_ascii=False))
    print(json.dumps(summaries, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
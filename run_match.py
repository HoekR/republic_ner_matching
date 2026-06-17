"""CLI entry point: match NER PER-layer annotations to known delegates.

Usage::

    python run_match.py \\
        --ner  ~/Downloads/annotations-unaggregated/annotations-layer_PER.tsv.gz \\
        --out  data/results.parquet \\
        --year-min 1705 \\
        --year-max 1795 \\
        --top-k 5 \\
        --chunk-size 50000

The script processes the NER file in chunks and writes all results to a
single parquet file via PyArrow (schema inferred from the first chunk).
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from match import build_attendance_year_index, build_store, match_ner
from preprocess import (
    clean_span,
    load_inventory_metadata,
    load_ner,
    normalize_interpositions,
    split_multi_person,
)

_DATA = pathlib.Path(__file__).parent / "data"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Match NER PER-layer spans to known delegates."
    )
    p.add_argument(
        "--ner",
        required=True,
        metavar="PATH",
        help="Path to annotations-layer_PER.tsv.gz (or uncompressed .tsv).",
    )
    p.add_argument(
        "--out",
        default=str(_DATA / "results.parquet"),
        metavar="PATH",
        help="Output parquet path (default: data/results.parquet).",
    )
    p.add_argument(
        "--delegates",
        default=str(_DATA / "delegates_reference.parquet"),
        metavar="PATH",
        help="delegates_reference.parquet (default: data/delegates_reference.parquet).",
    )
    p.add_argument(
        "--inv-meta",
        default=str(_DATA / "inventory_metadata.json"),
        metavar="PATH",
        help="inventory_metadata.json (default: data/inventory_metadata.json).",
    )
    p.add_argument("--year-min", type=int, default=1705, metavar="YEAR")
    p.add_argument("--year-max", type=int, default=1795, metavar="YEAR")
    p.add_argument("--top-k", type=int, default=5, metavar="K")
    p.add_argument("--chunk-size", type=int, default=50_000, metavar="N")
    p.add_argument(
        "--year-tolerance",
        type=int,
        default=0,
        metavar="N",
        help="Years ± around delegate active period for temporal gate (default 0).",
    )
    p.add_argument(
        "--min-score",
        type=float,
        default=0.1,
        metavar="F",
        help="Minimum combined score to keep a candidate (default 0.1).",
    )
    p.add_argument(
        "--attendance",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Optional attendance parquet path(s). Can be repeated. "
            "Used as a soft yearly prior for candidate ranking."
        ),
    )
    p.add_argument(
        "--attendance-boost",
        type=float,
        default=0.1,
        metavar="F",
        help="Multiplicative boost factor for attendance hits (default 0.1 = +10%).",
    )
    return p.parse_args()


def _expand_spans(ner_df: pd.DataFrame) -> pd.DataFrame:
    """Split multi-person spans and clean; return expanded DataFrame.

    Each row gets columns: orig_idx, tag_text (cleaned), year, raw_tag_text.
    """
    records = []
    for orig_idx, row in ner_df.iterrows():
        raw = row["tag_text"]
        year = row["year"]
        parts = split_multi_person(raw)
        if not parts:
            parts = [clean_span(raw)]
        for part in parts:
            if part:
                records.append(
                    {
                        "orig_idx": orig_idx,
                        "resolution_id": row.get("resolution_id", ""),
                        "paragraph_id": row.get("paragraph_id", ""),
                        "raw_tag_text": raw,
                        "tag_text": part,
                        "year": year,
                    }
                )
    return pd.DataFrame(records)


def main() -> None:
    args = _parse_args()

    ner_path = pathlib.Path(args.ner).expanduser()
    out_path = pathlib.Path(args.out).expanduser()
    delegates_path = pathlib.Path(args.delegates).expanduser()
    inv_meta_path = pathlib.Path(args.inv_meta).expanduser()

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Load reference data ---
    print("Loading delegates reference …")
    delegates = pd.read_parquet(delegates_path)
    print(f"  {len(delegates):,} delegates")

    print("Building TF-IDF store …")
    t0 = time.perf_counter()
    store = build_store(delegates)
    print(f"  Done in {time.perf_counter() - t0:.1f}s")

    print("Loading inventory metadata …")
    inv_lookup = load_inventory_metadata(inv_meta_path)
    print(f"  {len(inv_lookup):,} inventories")

    attendance_index: dict[str, set[int]] | None = None
    if args.attendance:
        print("Loading attendance prior …")
        attendance_index = build_attendance_year_index([str(pathlib.Path(p).expanduser()) for p in args.attendance])
        print(f"  {len(attendance_index):,} delegates with attendance-year entries")

    # --- Stream NER file, match, write ---
    print(f"Matching NER spans from {ner_path.name} …")
    writer: pq.ParquetWriter | None = None
    schema: pa.Schema | None = None

    total_spans = 0
    total_rows = 0
    chunk_idx = 0

    compression = "gzip" if str(ner_path).endswith(".gz") else "infer"
    reader = pd.read_csv(
        ner_path,
        sep="\t",
        compression=compression,
        chunksize=args.chunk_size,
        usecols=["inv", "resolution_id", "paragraph_id", "tag_text"],
        dtype={
            "inv": "Int64",
            "resolution_id": str,
            "paragraph_id": str,
            "tag_text": str,
        },
        low_memory=False,
    )

    t_start = time.perf_counter()

    for raw_chunk in reader:
        chunk_idx += 1
        # Derive year
        raw_chunk = raw_chunk.copy()
        raw_chunk["year"] = raw_chunk["inv"].map(
            lambda x: inv_lookup.get(int(x), {}).get("year") if pd.notna(x) else None
        )
        raw_chunk = raw_chunk[raw_chunk["year"].notna()]
        raw_chunk["year"] = raw_chunk["year"].astype(int)

        if args.year_min:
            raw_chunk = raw_chunk[raw_chunk["year"] >= args.year_min]
        if args.year_max:
            raw_chunk = raw_chunk[raw_chunk["year"] <= args.year_max]

        raw_chunk = raw_chunk[
            raw_chunk["tag_text"].notna() & (raw_chunk["tag_text"].str.strip() != "")
        ].reset_index(drop=True)

        if raw_chunk.empty:
            continue

        total_rows += len(raw_chunk)

        # Expand multi-person spans
        span_df = _expand_spans(raw_chunk)
        total_spans += len(span_df)

        if span_df.empty:
            continue

        # Match
        results = match_ner(
            store,
            span_df[["tag_text", "year"]].reset_index(drop=True),
            top_k=args.top_k,
            year_tolerance=args.year_tolerance,
            min_score=args.min_score,
            attendance_years_by_id=attendance_index,
            attendance_boost=args.attendance_boost,
        )

        # Attach provenance columns
        results["raw_tag_text"] = span_df["raw_tag_text"].values
        results["resolution_id"] = span_df["resolution_id"].values
        results["paragraph_id"] = span_df["paragraph_id"].values

        # Write to parquet
        table = pa.Table.from_pandas(results, preserve_index=False)
        if writer is None:
            schema = table.schema
            writer = pq.ParquetWriter(str(out_path), schema)
        writer.write_table(table)

        elapsed = time.perf_counter() - t_start
        print(
            f"  chunk {chunk_idx}: {total_rows:,} NER rows, {total_spans:,} spans "
            f"— {elapsed:.0f}s elapsed"
        )

    if writer is not None:
        writer.close()

    elapsed = time.perf_counter() - t_start
    print(f"\nDone. {total_spans:,} spans written to {out_path} in {elapsed:.1f}s")

    if not out_path.exists():
        print("WARNING: no spans matched (output file not created).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

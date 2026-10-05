#!/usr/bin/env python3
"""Attach archival provenance (inventory, page ids, scan ids) to each flat resolution.

Answers "which manuscript image carries this resolution?" -- the question
`resolutions_flat` cannot answer on its own, needed to point a reviewer (or an
adjudication of a contested date) at the actual scan.

Source is the REPUBLIC Elasticsearch `full_resolutions` index, which carries
`metadata.page_ids` on each resolution document. No text matching is involved:
an earlier investigation (docs/DECISIONS.md 2026-10-05) established that the
resolution text *is* present in ES under `paragraphs[].text`, but provenance
does not need it -- the page ids are on the document already.

Two deliberate omissions:
- ES `session_metadata.session_date` is NOT carried. It is uncorrected
  first-pass output; `resolutions_flat`'s own `date` is the corrected value.
- Resolution text is not pulled, per `formulation.republic_es`'s own rule of
  never requesting full text documents in bulk.

Scope defaults to inventories 3185-3189 (the annual series) plus 4562 (the
secret ledger). 4861 is nominally a secret inventory but has zero rows in
`resolutions_flat`, so it contributes nothing.

Not every flat id resolves in ES (~74% on a 400-id sample; ~90% for 4562).
Unresolved ids are written with `found = false` so the gap is visible in the
dataset rather than silently absent.

Usage:
    PYTHONPATH=.:/Users/rikhoekstra/develop/formulation \
        uv run python -m scripts.build_resolution_archival_provenance
    # optional: --inventories 4562 --limit 500
"""

from __future__ import annotations

import argparse
import re
from typing import Any

import pandas as pd

from data_io import load, save_semi_structured

from formulation.republic_es import ElasticsearchConfig, RepublicEsClient

FLAT_DATASET = "resolutions_flat"
OUTPUT_DATASET = "resolution_archival_provenance"
ES_HOST = "annotation.republic-caf.diginfra.org"
DEFAULT_INVENTORIES = (3185, 3186, 3187, 3188, 3189, 4562, 4861)
SOURCE_FIELDS = ["id", "metadata.inventory_num", "metadata.page_ids", "metadata.page_num"]
PAGE_SUFFIX = re.compile(r"-page-\d+$")
SESSION_FROM_ID = re.compile(r"^(session-\d+-num-\d+)-resolution-\d+$")


def scan_ids_from_pages(page_ids: list[str]) -> list[str]:
    """`NL-HaNA_1.01.02_3185_0131-page-260` -> `NL-HaNA_1.01.02_3185_0131`."""
    return list(dict.fromkeys(PAGE_SUFFIX.sub("", str(p)) for p in page_ids if p))


def in_scope(frame: pd.DataFrame, inventories: tuple[int, ...]) -> pd.DataFrame:
    inv = frame["id"].str.extract(r"^session-(\d+)-num-")[0]
    return frame.loc[inv.isin({str(i) for i in inventories})]


def build_rows(flat_ids: list[str], found: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for flat_id in flat_ids:
        session_match = SESSION_FROM_ID.match(flat_id)
        base = {
            "flat_id": flat_id,
            "session_id": session_match.group(1) if session_match else None,
        }
        source = found.get(flat_id)
        if source is None:
            rows.append({**base, "found": False, "inventory_num": None, "page_num": None, "page_ids": [], "scan_ids": []})
            continue
        meta = source.get("metadata") or {}
        page_ids = [str(p) for p in (meta.get("page_ids") or [])]
        rows.append(
            {
                **base,
                "found": True,
                "inventory_num": meta.get("inventory_num"),
                "page_num": meta.get("page_num"),
                "page_ids": page_ids,
                "scan_ids": scan_ids_from_pages(page_ids),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventories", type=int, nargs="*", default=list(DEFAULT_INVENTORIES))
    parser.add_argument("--limit", type=int, default=None, help="Cap ids, for a smoke run.")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    flat = load(FLAT_DATASET)
    if not isinstance(flat, pd.DataFrame):
        flat = pd.DataFrame(flat)
    scoped = in_scope(flat, tuple(args.inventories))
    flat_ids = scoped["id"].astype(str).tolist()
    if args.limit:
        flat_ids = flat_ids[: args.limit]
    print(f"in scope: {len(flat_ids)} resolutions across inventories {sorted(args.inventories)}")

    client = RepublicEsClient(config=ElasticsearchConfig(host=ES_HOST))
    found = client.mget(client.config.resolutions_index, flat_ids, SOURCE_FIELDS, batch_size=args.batch_size)
    print(f"resolved in ES: {len(found)} / {len(flat_ids)} ({len(found) / max(len(flat_ids), 1):.1%})")

    rows = build_rows(flat_ids, found)
    frame = pd.DataFrame(rows)
    frame["inv"] = frame["flat_id"].str.extract(r"^session-(\d+)-num-")[0]
    print("\nfound-rate by inventory:")
    print(frame.groupby("inv")["found"].agg(["size", "sum"]).assign(rate=lambda d: (d["sum"] / d["size"]).map("{:.1%}".format)).to_string())
    with_pages = int(frame.loc[frame["found"], "page_ids"].map(bool).sum())
    print(f"\nof resolved rows, carrying page_ids: {with_pages} / {int(frame['found'].sum())}")

    meta_record = {
        "record_type": "meta",
        "n_requested": len(flat_ids),
        "n_found": len(found),
        "inventories": sorted(args.inventories),
        "es_index": client.config.resolutions_index,
        "source_fields": SOURCE_FIELDS,
        "note": "ES session_date deliberately not carried; resolutions_flat date is the corrected value.",
    }
    out = save_semi_structured(
        [meta_record] + rows,
        logical_name=OUTPUT_DATASET,
        parent_sources=[FLAT_DATASET],
        description="Per-resolution archival provenance (inventory, page_ids, scan_ids) from the ES full_resolutions index.",
        script=__file__,
    )
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

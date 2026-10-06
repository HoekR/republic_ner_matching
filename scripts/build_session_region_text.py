#!/usr/bin/env python3
"""Ingest the session text regions this corpus never imported: `date` and `attendance`.

Why. `paragraph_axis_1626_1630` descends from `resolutions_flat`, which carries **resolution**
text. ES classes every text region, and a session's own date heading lives in a `date`-class
region -- so the headings were simply absent here, and a channel that depends on them could
not work however well it was written. Measured on `session-3185-num-98`: the axis opens
`De Heeren Rantwijck, De Bije, Hend: ... wedergekeert uyt Noorthollant`, mid-attendance-list
straight into resolution text, while ES holds for that same session
`Heeren Grave, Rantwijck, De Bie, Halewijn, Mercurij den xxen. Maij 1626`. Running the
weekday arbitration against the axis returned 23 of 24 "no signal"; against ES `date`
regions it returned 16 H1, 1 H0 and 0 H2 (docs/DECISIONS.md 2026-10-06).

`attendance` regions come along because they are the other half of the same omission and the
delegate-matching work needs them -- REPUBLIC's own attendance model exists for exactly this
text. `marginalia` is *not* ingested by default although it is the largest class by count
(77 of 170 regions on `session-3185-num-23`): it is side-notes rather than session content,
and `--classes` takes whatever list is wanted rather than forcing a rebuild to change it.

Two conventions, both deliberate:

* Regions are ordered by `(scan_id, reading_order)`, which is reading order, so the **first**
  `date` region of a session is its opening heading. That distinction matters: a date further
  into a session is ordinary text -- `session-3185-num-56` carries a 28 March heading inside
  a 27 March session -- and a first version of the arbitration took the best-scoring heading
  anywhere and picked up the wrong one.
* Regions whose text holds no letters at all are kept, not dropped, with `has_letters: false`.
  They are OCR rubble (`4153 114 1550.`, `161101 4 1orp 2501`), and a consumer filtering them
  is making a visible choice rather than inheriting a silent one.
* **`metadata.session_id` is multi-valued** for a region straddling a session boundary, and
  such a region belongs to both sessions. A first version stringified the list, so 140 of
  3,763 rows carried `"['session-3185-num-10', 'session-3185-num-9']"` as their session id
  and joined to nothing -- losing exactly the most informative rows, since a straddling
  region carries two days' headings at once:
  `Nil Actum Dominica den xiijen. Junij 1626. Luna den xven. Junij 1626.` -- nihil actum
  written on the page rather than inferred from the ledger, followed by the next sitting.
  Now one row is emitted **per session id**, each carrying `session_ids` with all of them and
  `straddles_sessions`, so a join on `session_id` reaches both sessions while the duplication
  stays visible and is de-dupable on `text_region_id`.

Usage:
    uv run python scripts/build_session_region_text.py
    uv run python scripts/build_session_region_text.py --classes date attendance marginalia
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FORMULATION = Path("/Users/rikhoekstra/develop/formulation")
if FORMULATION.exists() and str(FORMULATION) not in sys.path:
    sys.path.insert(0, str(FORMULATION))

from data_io import save_semi_structured
from running_axis.stream import build_streams

OUTPUT_DATASET = "session_region_text_1626_1630"
ES_HOST = "annotation.republic-caf.diginfra.org"
DEFAULT_CLASSES = ("date", "attendance")
SOURCE_FIELDS = [
    "id",
    "metadata.session_id",
    "metadata.scan_id",
    "metadata.page_id",
    "metadata.reading_order",
    "metadata.text_region_class",
    "metadata.inventory_num",
    "lines.text",
    "stats",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classes", nargs="+", default=list(DEFAULT_CLASSES))
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()

    from formulation.republic_es import ElasticsearchConfig, RepublicEsClient

    # Scope: the sessions this corpus actually has, read off flat ids rather than taken from
    # any candidate-inventory column (see running_axis.axis.DateState).
    sessions = sorted(
        {ref.session_id for stream in build_streams().values() for ref in stream}
    )
    in_scope = set(sessions)
    print(f"sessions in this corpus: {len(sessions):,}")
    print(f"ingesting region classes: {', '.join(args.classes)}")

    client = RepublicEsClient(config=ElasticsearchConfig(host=ES_HOST))
    index = client.config.session_text_regions_index

    rows: list[dict[str, Any]] = []
    for start in range(0, len(sessions), args.batch_size):
        chunk = sessions[start : start + args.batch_size]
        body = {
            "size": 1000,
            "query": {
                "bool": {
                    "must": [
                        {"terms": {"metadata.session_id.keyword": chunk}},
                        {"terms": {"metadata.text_region_class.keyword": list(args.classes)}},
                    ]
                }
            },
            "_source": SOURCE_FIELDS,
        }
        response = client._request_json("POST", f"{index}/_search", body=body)
        hits = response.get("hits", {}).get("hits") or []
        total = (response.get("hits", {}).get("total") or {}).get("value")
        if total is not None and total > len(hits):
            raise RuntimeError(
                f"batch at {start} returned {len(hits)} of {total} regions -- raise `size` "
                "rather than silently ingesting a truncated batch"
            )
        for hit in hits:
            source = hit.get("_source") or {}
            meta = source.get("metadata") or {}
            lines = [str(line.get("text") or "") for line in (source.get("lines") or [])]
            text = " ".join(part for part in lines if part)
            raw = meta.get("session_id")
            session_ids = [str(v) for v in raw] if isinstance(raw, list) else [str(raw or "")]
            session_ids = [v for v in session_ids if v] or [""]
            for session_id in session_ids:
                rows.append(
                    {
                        "record_type": "region",
                        "session_id": session_id,
                        # All sessions this region belongs to. A straddling region is emitted
                        # once per session so joins reach each of them; de-dupe on
                        # text_region_id when counting regions rather than attributions.
                        "session_ids": session_ids,
                        "straddles_sessions": len(session_ids) > 1,
                        "inventory": str(meta.get("inventory_num") or ""),
                        "region_class": str(meta.get("text_region_class") or ""),
                        # The document's own id. metadata.text_region_id is null
                        # throughout this index, which made a first version report
                        # "1 distinct regions" -- every row keyed on None.
                        "text_region_id": source.get("id") or hit.get("_id"),
                        "scan_id": meta.get("scan_id"),
                        "page_id": meta.get("page_id"),
                        "reading_order": meta.get("reading_order"),
                        "n_lines": len(lines),
                        "text": text,
                        # Kept rather than dropped: OCR rubble is a visible row, so a consumer
                        # filtering it makes that choice itself.
                        "has_letters": any(ch.isalpha() for ch in text),
                    }
                )
        if start and start % (args.batch_size * 20) == 0:
            print(f"  {start:,}/{len(sessions):,} sessions, {len(rows):,} regions")

    rows.sort(key=lambda r: (r["session_id"], str(r["scan_id"]), r["reading_order"] or 0))
    by_class = Counter(r["region_class"] for r in rows)
    with_class: dict[str, set[str]] = {}
    for row in rows:
        # A straddling region can name a session this corpus does not hold, so reach is
        # counted over in-scope sessions only -- otherwise it exceeds the scope itself.
        if row["has_letters"] and row["session_id"] in in_scope:
            with_class.setdefault(row["region_class"], set()).add(row["session_id"])

    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Session text regions of the classes this corpus never ingested, from the ES "
            "session_text_regions index. Ordered by (scan_id, reading_order), so a session's "
            "first `date` region is its opening heading."
        ),
        "parent_datasets": ["paragraph_axis_1626_1630"],
        "es_index": index,
        "classes": list(args.classes),
        "sessions_in_scope": len(sessions),
        "attributions": len(rows),
        "regions": len({r["text_region_id"] for r in rows}),
        "straddling_attributions": sum(1 for r in rows if r["straddles_sessions"]),
        "attributions_out_of_scope": sum(1 for r in rows if r["session_id"] not in in_scope),
        "regions_by_class": dict(by_class),
        "sessions_with_region_by_class": {k: len(v) for k, v in sorted(with_class.items())},
        "regions_without_letters": sum(1 for r in rows if not r["has_letters"]),
        "characters": sum(len(r["text"]) for r in rows),
    }
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"\nWrote {path}")
    print(f"  {meta['regions']:,} distinct regions, {meta['attributions']:,} attributions "
          f"({meta['straddling_attributions']:,} from boundary-straddling regions), "
          f"{meta['characters']:,} characters")
    print(f"  by class: {meta['regions_by_class']}")
    print(f"  sessions reached: {meta['sessions_with_region_by_class']} of {len(sessions):,}")
    print(f"  regions with no letters (OCR rubble, kept): {meta['regions_without_letters']:,}")


if __name__ == "__main__":
    main()

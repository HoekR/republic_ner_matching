#!/usr/bin/env python3
"""Diagnose how often HTR session text contains an undetected internal session start.

Deliberately lenient prevalence measurement, not a cut boundary: flags a
"president" stem followed within a short window by a "present(ibus)" stem,
occurring past a session's own leading text. Real examples in this corpus
("President de Heer Brouchoven, Present de Veneris den xiijen. Februarij
1626.") confirmed both the pattern and that it can appear mid-resolution
(``session-3185-num-28-resolution-12``), evidence that two or more real
sessions were merged into one HTR-parsed block during the original parsing.
Measurement only -- does not cut, relabel, or write any session or dataset.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load
from scripts.build_session_date_ledger import _session_parts

FLAT_DATASET = "resolutions_flat"
LEDGER_DATASET = "session_date_status_1626_1630"

# Lenient on purpose (recall over precision -- this is a "how often does this
# happen" measurement, not a segmentation decision). Early-modern Dutch/Latin
# HTR spelling varies (president/preside/praeside/presideerde,
# present/presentibus/praesentibus), so prefix-match the stem rather than
# requiring an exact word.
PRESIDENT_PATTERN = re.compile(r"\bpr[ae]{1,2}sid\w*", re.IGNORECASE)
PRESENT_PATTERN = re.compile(r"\bpr[ae]{1,2}sent\w*", re.IGNORECASE)
LEADING_BUFFER_CHARS = 80  # ignore hits inside a session's own opening
PRESENT_WINDOW_CHARS = 60  # how far after "president" to look for "present(ibus)"
SNIPPET_CHARS = 160


@dataclass
class Hit:
    session_id: str
    offset: int
    snippet: str


def session_texts(flat: pd.DataFrame, inventory_ids: set[int]) -> dict[str, str]:
    """Concatenate each in-scope session's flat resolution text in resolution order."""
    flat = flat.copy()
    parts = _session_parts(flat["id"])
    flat["session_id"] = parts[0]
    flat["inventory_id"] = parts["inventory_id"].astype(int)
    flat["resolution_index"] = flat["id"].str.extract(r"-resolution-(\d+)$")[0].astype(int)
    flat = flat.loc[flat["inventory_id"].isin(inventory_ids)].sort_values(["session_id", "resolution_index"])
    grouped = flat.groupby("session_id")["resolutions_text"]
    return grouped.apply(lambda values: " ".join(str(v) for v in values if v)).to_dict()


def find_internal_starts(session_id: str, text: str) -> list[Hit]:
    """Return candidate mid-text 'president ... present' matches past the leading buffer."""
    hits = []
    for president_match in PRESIDENT_PATTERN.finditer(text):
        start = president_match.start()
        if start < LEADING_BUFFER_CHARS:
            continue
        window = text[start : start + PRESENT_WINDOW_CHARS]
        if PRESENT_PATTERN.search(window):
            hits.append(Hit(session_id=session_id, offset=start, snippet=text[start : start + SNIPPET_CHARS]))
    return hits


def main() -> None:
    ledger = load(LEDGER_DATASET)
    inventory_ids = set(ledger["inventory_id"].astype(int))
    texts = session_texts(load(FLAT_DATASET), inventory_ids)

    all_hits: list[Hit] = [hit for session_id, text in texts.items() for hit in find_internal_starts(session_id, text)]
    sessions_with_hits = {hit.session_id for hit in all_hits}

    print(f"Scanned {len(texts)} sessions across {len(inventory_ids)} inventories (1626-1630 ledger scope)")
    print(
        f"{len(sessions_with_hits)} / {len(texts)} sessions "
        f"({len(sessions_with_hits) / len(texts):.1%}) have >=1 possible undetected internal session start"
    )
    print(f"{len(all_hits)} candidate internal-start matches total")
    print("\nSample hits (first 15):")
    for hit in all_hits[:15]:
        print(f"  {hit.session_id} @ char {hit.offset}: {hit.snippet!r}")


if __name__ == "__main__":
    main()

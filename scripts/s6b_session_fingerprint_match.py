#!/usr/bin/env python3
"""Content-fingerprint correspondence between resolutions_flat's session ids and
the raw sessions_json_source sessions they actually contain.

Reproduces, as a registered pipeline output, a finding from the 2026-09-21 S4f
review session (docs/DECISIONS.md, "S4f review surfaced resolutions_flat
session-numbering drift"): resolutions_flat's own session numbering has
drifted from the current archive -- e.g. resolutions_flat's
session-3185-num-25-resolution-1 text matches raw session-3185-num-26's
content verbatim, not raw session-3185-num-25's. That match was previously
only in scratch (/tmp/scope_results.json, unregistered, not reproducible from
code in this repo); this script rebuilds it as a proper data_io dataset.

Method: for each resolutions_flat session, concatenate its ordered
resolutions_text into a normalized (lowercased, whitespace-collapsed) 150-char
fingerprint. For each raw session in s4_session_date_region_scan, concatenate
only its "para"-classified text_regions (excluding "date"/"attendance"/
"marginalia", which resolutions_text never carries) into one normalized text.
A flat session's fingerprint is matched by **substring containment** against
same-inventory raw sessions' concatenated text, not exact-prefix equality:
resolutions_flat's own paragraph splitting does not align 1:1 with raw para
region boundaries (e.g. session-3185-num-1's flat resolution-1 skips a
"President de Heer..." attendance-like line that the upstream classifier
mistagged "para", splicing across it) so the flat session's real content can
start partway into the raw concatenation. Exact-prefix matching found 838/1511
(55.5%); substring containment finds 1059/1511 (70.1%) with zero new
ambiguity, confirming most of the gap was alignment slack, not genuine
non-correspondence. Matches are content-verified, not id-based, so they are
independent of whatever number resolutions_flat currently assigns.

This is the session_date_verified anchor channel's prerequisite data
(STEP_S6_anchor_chain_alignment.md section 2.2, group D) -- it answers what
content resolutions_flat's (possibly mislabeled) session id actually is, so a
later anchor channel can key off archival provenance instead of the drifted
label. Building the channel itself is deferred to a follow-up session.

Usage: uv run python -m scripts.s6b_session_fingerprint_match
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from scripts.build_session_date_ledger import _session_parts

FLAT_DATASET = "resolutions_flat"
LEDGER_DATASET = "session_date_status_1626_1630"
REGION_SCAN_DATASET = "s4_session_date_region_scan"
OUTPUT_DATASET = "s6b_session_fingerprint_match"

FINGERPRINT_CHARS = 150
MIN_FINGERPRINT_CHARS = 30  # below this, a substring match would be unreliably common
WHITESPACE_PATTERN = re.compile(r"\s+")
NUM_SUFFIX_PATTERN = r"-num-(\d+)$"


def normalize(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip().lower()


def flat_fingerprints(flat: pd.DataFrame, inventory_ids: set[int]) -> pd.DataFrame:
    """One row per resolutions_flat session: inventory_id, flat_num, flat_session_id, date, fingerprint."""
    flat = flat.copy()
    parts = _session_parts(flat["id"])
    flat["session_id"] = parts[0]
    flat["inventory_id"] = parts["inventory_id"].astype(int)
    flat = flat.loc[flat["inventory_id"].isin(inventory_ids)].copy()
    flat["flat_num"] = flat["session_id"].str.extract(NUM_SUFFIX_PATTERN)[0].astype(int)
    flat["resolution_index"] = flat["id"].str.extract(r"-resolution-(\d+)$")[0].astype(int)
    flat = flat.sort_values(["session_id", "resolution_index"])

    grouped = flat.groupby(["inventory_id", "flat_num", "session_id"], as_index=False).agg(
        date=("date", "first"),
        text=("resolutions_text", lambda values: " ".join(str(v) for v in values if v)),
    )
    grouped["fingerprint"] = grouped["text"].map(normalize).str.slice(0, FINGERPRINT_CHARS)
    return grouped.drop(columns="text").rename(columns={"session_id": "flat_session_id"})


def raw_texts(regions: pd.DataFrame) -> pd.DataFrame:
    """One row per raw session: inventory_id, raw_num, raw_session_id, text, from 'para' regions only."""
    para = regions.loc[regions["text_region_class"] == "para"].copy()
    parts = _session_parts(para["session_id"])
    para["inventory_id"] = parts["inventory_id"].astype(int)
    para["raw_num"] = para["session_id"].str.extract(NUM_SUFFIX_PATTERN)[0].astype(int)

    grouped = para.groupby(["inventory_id", "raw_num", "session_id"], as_index=False).agg(
        text=("text", lambda values: " ".join(str(v) for v in values if v))
    )
    grouped["text"] = grouped["text"].map(normalize)
    return grouped.rename(columns={"session_id": "raw_session_id"})


def _find_raw_matches(fingerprint: str, raw_group: pd.DataFrame) -> list[str]:
    if len(fingerprint) < MIN_FINGERPRINT_CHARS:
        return []
    hits = raw_group.loc[raw_group["text"].str.contains(re.escape(fingerprint), regex=True)]
    return sorted(hits["raw_session_id"].tolist())


def match_fingerprints(flat_fp: pd.DataFrame, raw_fp: pd.DataFrame) -> pd.DataFrame:
    """Match each flat session's fingerprint by substring containment within same-inventory raw session text.

    resolutions_flat's paragraph splitting does not align 1:1 with raw para region
    boundaries, so the flat fingerprint can start partway into a raw session's
    concatenated text -- substring containment tolerates that, exact-prefix equality
    does not (see module docstring). A fingerprint too short to be reliable, found in
    zero raw sessions, or found in more than one raw session in the same inventory is
    left unmatched/ambiguous rather than guessed at.
    """
    records = []
    for inventory_id, flat_group in flat_fp.groupby("inventory_id"):
        raw_group = raw_fp.loc[raw_fp["inventory_id"] == inventory_id]
        for row in flat_group.itertuples(index=False):
            matches = _find_raw_matches(row.fingerprint, raw_group)
            records.append({**row._asdict(), "raw_matches": matches})

    matches_df = pd.DataFrame(records)
    raw_num_by_id = dict(zip(raw_fp["raw_session_id"], raw_fp["raw_num"]))
    # dtype=object keeps unmatched rows as Python None rather than upcasting to NaN,
    # which json.dumps cannot serialize (pd.NA) or writes as invalid bareword `NaN`.
    matches_df["raw_num"] = pd.Series(
        [int(raw_num_by_id[m[0]]) if len(m) == 1 else None for m in matches_df["raw_matches"]],
        dtype=object,
    )
    matches_df["offset"] = pd.Series(
        [
            (raw_num - flat_num) if raw_num is not None else None
            for raw_num, flat_num in zip(matches_df["raw_num"], matches_df["flat_num"])
        ],
        dtype=object,
    )
    return matches_df.sort_values(["inventory_id", "flat_num"])


def main() -> None:
    ledger = load(LEDGER_DATASET)
    inventory_ids = set(ledger["inventory_id"].astype(int))

    flat_fp = flat_fingerprints(load(FLAT_DATASET), inventory_ids)
    regions = pd.DataFrame(load(REGION_SCAN_DATASET))
    raw_fp = raw_texts(regions)

    matches = match_fingerprints(flat_fp, raw_fp)
    records = matches.to_dict("records")
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)

    total = len(matches)
    is_matched = matches["raw_num"].map(lambda v: v is not None)
    unique_matched = is_matched.sum()
    ambiguous = ((~is_matched) & (matches["raw_matches"].map(len) > 1)).sum()
    unmatched = total - unique_matched - ambiguous
    offsets = matches.loc[is_matched, "offset"]
    drifted = (offsets != 0).sum()

    print(f"Wrote {total} flat-session fingerprint records to {output}")
    print(f"{unique_matched} uniquely matched to a raw session ({unique_matched / total:.1%})")
    print(f"{ambiguous} ambiguous (fingerprint shared by >1 raw session)")
    print(f"{unmatched} unmatched (no raw session shares the fingerprint)")
    print(f"{drifted} / {unique_matched} matched sessions have a non-zero offset (drift)")
    print("\nPer-inventory:")
    print(
        matches.groupby("inventory_id").apply(
            lambda g: pd.Series(
                {
                    "sessions": len(g),
                    "matched": g["raw_num"].map(lambda v: v is not None).sum(),
                    "drifted": (g["offset"].map(lambda v: v is not None and v != 0)).sum(),
                }
            ),
            include_groups=False,
        )
    )


if __name__ == "__main__":
    main()

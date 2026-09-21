#!/usr/bin/env python3
"""One-time extraction of raw session text_regions for the 1626-1630 ledger scope.

sessions_json_source is a 10 GB tar.gz with no random access (gzip is a single
sequential stream), so this streams it once for just the sessions in the
1626-1630 session_date_status_1626_1630 ledger's inventories -- the same
1,511-session scope as scripts/s4_session_start_scan.py -- rather than the
whole multi-century archive, and stops as soon as every target tar member has
been found (same early-exit pattern as
scripts/s4_line_ground_truth_overlap_check.py).

For each session, keeps every text_region's scan_id/page_id/line_id, its
upstream text_region_class (the nlc_classifier's own "is this a date phrase"
call), and whether the region's line text matches the lenient
president/present regex from s4_session_start_scan.py. Investigating
session-3185-num-25 by hand (2026-09-21 review session) found the classifier
both false-positives ("Amsterdam 12 schepen2 Jachten" tagged "date") and
false-negatives (missed "President de Heer Rantwijck, Present de Dominica den
viijen. Februarij 1626." mid-session) -- so this keeps both signals rather
than trusting either alone, as raw material for a later manual sanity check
against the actual scans.

Written to warm tier (s4_session_date_region_scan, 1.4 GB+ uncompressed JSON
across ~1,500 sessions) rather than hot/local, per instruction -- this is
cache for reruns of the archive scan, not a small review artifact.

Usage: uv run python -m scripts.s4_session_date_region_scan
"""

from __future__ import annotations

import gzip
import json
import re
import tarfile

from data_io import TierUnavailableError, load, resolve, save_semi_structured

LEDGER_DATASET = "session_date_status_1626_1630"
SESSION_INDEX_DATASET = "session_index_all"
ARCHIVE_DATASET = "sessions_json_source"
OUTPUT_DATASET = "s4_session_date_region_scan"

# Same lenient stems as s4_session_start_scan.py -- see that module's
# docstring for the corpus evidence behind them.
PRESIDENT_PATTERN = re.compile(r"\bpr[ae]{1,2}sid\w*", re.IGNORECASE)
PRESENT_PATTERN = re.compile(r"\bpr[ae]{1,2}sent\w*", re.IGNORECASE)


def target_members() -> dict[str, str]:
    """Return {tar_member: session_id} for every session in the 1626-1630 ledger's inventories."""
    ledger = load(LEDGER_DATASET)
    inventory_ids = set(ledger["inventory_id"].astype(int))
    sessions = load(SESSION_INDEX_DATASET)
    sessions = sessions.loc[sessions["inventory_num"].isin(inventory_ids)]
    return dict(zip(sessions["tar_member"], sessions["session_id"]))


def region_records(session_id: str, session_json: dict) -> list[dict]:
    """Flatten one session's text_regions to one record per region with line text."""
    records = []
    for region in session_json.get("text_regions", []):
        text = " ".join(line.get("text", "") for line in region.get("lines", []) if line.get("text"))
        president_hit = bool(PRESIDENT_PATTERN.search(text))
        present_hit = bool(PRESENT_PATTERN.search(text))
        records.append(
            {
                "session_id": session_id,
                "text_region_id": region.get("id"),
                "scan_id": region.get("metadata", {}).get("scan_id"),
                "page_id": region.get("metadata", {}).get("page_id"),
                "text_region_class": region.get("metadata", {}).get("text_region_class"),
                "text": text,
                "president_hit": president_hit,
                "present_hit": present_hit,
                "president_and_present_hit": president_hit and present_hit,
            }
        )
    return records


def scan_archive(wanted: dict[str, str]) -> list[dict]:
    archive_path = resolve(ARCHIVE_DATASET)
    remaining = set(wanted)
    records: list[dict] = []
    with tarfile.open(archive_path, mode="r:gz") as tar:
        for member in tar:
            if not remaining:
                break
            if member.name not in remaining:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            session_json = json.loads(gzip.decompress(handle.read()))
            records.extend(region_records(wanted[member.name], session_json))
            remaining.discard(member.name)
    if remaining:
        print(f"WARNING: {len(remaining)} target tar members never found in archive: {sorted(remaining)[:10]}")
    return records


def main() -> None:
    try:
        wanted = target_members()
    except TierUnavailableError as exc:
        raise SystemExit(f"warm-tier drive not mounted: {exc}") from exc

    print(f"Scanning sessions_json_source for {len(wanted)} tar members (1626-1630 ledger scope, single sequential pass)...")
    records = scan_archive(wanted)
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)

    date_class_count = sum(1 for r in records if r["text_region_class"] == "date")
    regex_hit_count = sum(1 for r in records if r["president_and_present_hit"])
    both_count = sum(1 for r in records if r["text_region_class"] == "date" and r["president_and_present_hit"])
    print(f"Wrote {len(records)} text_region records from {len(wanted)} sessions to {output}")
    print(f"{date_class_count} regions classified 'date' by the upstream nlc_classifier")
    print(f"{regex_hit_count} regions match the lenient president/present regex")
    print(f"{both_count} regions have both signals; the rest disagree -- see this module's docstring")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check htr_classified_lines_marijn.csv coverage of the 12 S4 gold days.

Per docs/DECISIONS.md (2026-09-18, "Correct line-level-segmentation blocker..."):
no dataset in data_manifest.toml maps (inventory, scan/page) to date for
inventories 3185-3189. session_index_all gives (inventory, session_num) -> date;
the marijn-variant line-classification ground truth gives page_id -> checked
line labels, keyed by (inventory, scan). This script bridges the two by pulling
each target session's raw JSON out of the (unextracted, 10 GB) sessions_json
archive and harvesting page-id-like strings from it, so it can be joined against
the marijn CSV's page_ids for the 12 gold days.

Requires the "warm" tier drive mounted for the whole run (session_index_all and
sessions_json_source both live there). Streams the entire tar.gz sequentially
until it has found every target member -- gzip does not support random access,
so this is a real, possibly long, single pass; that's why it's meant to be
kicked off and left running rather than run interactively.

Usage:
    uv run python -m scripts.s4_line_ground_truth_overlap_check
"""

from __future__ import annotations

import re
import tarfile
from collections import defaultdict

import pandas as pd

from data_io import TierUnavailableError, load, resolve, save_semi_structured

TARGET_INVENTORIES = {3185, 3186, 3187, 3188, 3189}
GOLD_DATES = [
    "1626-01-08",
    "1626-04-04",
    "1627-08-19",
    "1627-10-05",
    "1628-04-04",
    "1628-10-26",
    "1628-11-24",
    "1629-10-15",
    "1630-01-22",
    "1630-02-16",
    "1630-02-27",
    "1630-03-20",
]
PAGE_ID_RE = re.compile(r"NL-HaNA_[\w.]+_\d{3,5}_\d{3,5}-page-\d+")


def load_marijn_page_ids() -> dict[int, set[str]]:
    path = resolve("htr_classified_lines_marijn")
    df = pd.read_csv(path, sep="\t")
    df.columns = [column.strip().strip('"') for column in df.columns]
    checked = df[df["checked"] == 1].copy()
    checked["inventory"] = checked["page_id"].str.extract(r"NL-HaNA_[\w.]+_(\d{3,5})_")[0].astype(int)
    by_inventory: dict[int, set[str]] = defaultdict(set)
    for inventory, group in checked.groupby("inventory"):
        by_inventory[int(inventory)] = set(group["page_id"])
    return by_inventory


def target_sessions() -> pd.DataFrame:
    sessions = load("session_index_all")
    sessions = sessions[sessions["inventory_num"].isin(TARGET_INVENTORIES)]
    sessions = sessions[sessions["session_date"].astype(str).isin(GOLD_DATES)]
    return sessions[["session_id", "session_date", "inventory_num", "tar_member"]].copy()


def harvest_page_ids(raw_bytes: bytes) -> set[str]:
    text = raw_bytes.decode("utf-8", errors="ignore")
    return set(PAGE_ID_RE.findall(text))


def scan_archive(wanted_members: set[str]) -> dict[str, set[str]]:
    archive_path = resolve("sessions_json_source")
    found: dict[str, set[str]] = {}
    remaining = set(wanted_members)
    with tarfile.open(archive_path, mode="r:gz") as tar:
        for member in tar:
            if not remaining:
                break
            if member.name not in remaining:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            found[member.name] = harvest_page_ids(handle.read())
            remaining.discard(member.name)
    if remaining:
        print(f"WARNING: {len(remaining)} target tar members never found in archive: {sorted(remaining)}")
    return found


def main() -> None:
    try:
        marijn_by_inventory = load_marijn_page_ids()
        sessions = target_sessions()
    except TierUnavailableError as exc:
        raise SystemExit(f"warm-tier drive not mounted: {exc}") from exc

    print(f"{len(sessions)} sessions in inventories {sorted(TARGET_INVENTORIES)} match the 12 gold dates")
    if sessions.empty:
        raise SystemExit(
            "No matching sessions found -- check GOLD_DATES against session_index_all "
            "coverage before scanning the archive."
        )

    wanted_members = set(sessions["tar_member"])
    print(f"Scanning sessions_json_source for {len(wanted_members)} tar members (single sequential pass)...")
    harvested = scan_archive(wanted_members)

    records = []
    for row in sessions.itertuples(index=False):
        page_ids = harvested.get(row.tar_member, set())
        marijn_ids = marijn_by_inventory.get(int(row.inventory_num), set())
        overlap = page_ids & marijn_ids
        records.append(
            {
                "date": row.session_date,
                "inventory_num": int(row.inventory_num),
                "session_id": row.session_id,
                "tar_member": row.tar_member,
                "harvested_page_id_count": len(page_ids),
                "harvested_page_ids": sorted(page_ids),
                "marijn_checked_page_id_count_in_inventory": len(marijn_ids),
                "overlap_page_ids": sorted(overlap),
                "has_marijn_coverage": bool(overlap),
            }
        )
        if not page_ids:
            print(
                f"NOTE: 0 page-id-like strings harvested for {row.session_date} ({row.tar_member}) -- "
                "session JSON schema may not embed the expected "
                "'NL-HaNA_..._..._...-page-N' pattern; inspect this session's raw JSON "
                "manually if this happens for every row."
            )

    covered = sum(record["has_marijn_coverage"] for record in records)
    print(f"{covered}/{len(records)} gold days have at least one overlapping checked page_id in htr_classified_lines_marijn.csv")

    output = save_semi_structured(
        records,
        logical_name="s4_line_ground_truth_overlap_check",
        script=__file__,
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()

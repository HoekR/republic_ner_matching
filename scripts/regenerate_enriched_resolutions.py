#!/usr/bin/env python3
"""Regenerate enriched_resolutions_1626_1630, dropping stray .xml.bak duplicate records.

Found during resolution_concordance_1626_1630 verification (docs/CANDIDATE_SCORING_AND_CONCORDANCE.md
Step F, 17 Sep 2026): enriched_resolutions_1626_1630_complete.json contains both
162915nov.xml and a stray 162915nov.xml.bak as separate records for the same
(date, resolution_index), duplicating all 13 resolutions of 1629-11-15. The
.bak record is the pre-edit version (diffs only in trivial date-abbreviation
edits, e.g. "31 okt." -> "31 oktober"), so the .xml record is authoritative.

No other duplicate (date, resolution_index) pairs or .bak files exist in the
source. Backs up the original file before overwriting.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from data_io import resolve
from data_io.provenance import ProvenanceRecord, git_commit_hash, write_sidecar

LOGICAL_NAME = "enriched_resolutions_1626_1630"


def main() -> None:
    path = resolve(LOGICAL_NAME)
    with path.open("r", encoding="utf-8") as handle:
        records = json.load(handle)

    kept = [r for r in records if not str(r.get("file", "")).endswith(".bak")]
    dropped = len(records) - len(kept)
    if dropped == 0:
        print("No .bak records found; nothing to do.")
        return

    backup_path = path.with_suffix(path.suffix + ".pre_bak_dedup.orig")
    shutil.copy2(path, backup_path)
    print(f"Backed up original ({len(records)} records) to {backup_path}")

    with path.open("w", encoding="utf-8") as handle:
        json.dump(kept, handle, indent=2, ensure_ascii=False)

    record = ProvenanceRecord(
        logical_name=LOGICAL_NAME,
        phase="frozen",
        parent_sources=[],
        description=(
            "Normative enriched resolutions for 1626-1630. Regenerated "
            f"{Path(__file__).name}: dropped {dropped} stray .xml.bak duplicate "
            "record(s) (162915nov.xml.bak, date 1629-11-15) that duplicated "
            "162915nov.xml under the same resolution_index."
        ),
        created_by_script=str(Path(__file__).resolve()),
        record_count=len(kept),
        git_commit=git_commit_hash(path.parent),
    )
    write_sidecar(path, record)

    print(f"Wrote {len(kept)} records ({dropped} dropped) to {path}")


if __name__ == "__main__":
    main()

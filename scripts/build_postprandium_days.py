#!/usr/bin/env python3
"""The 109 days the enriched edition records as having two sittings. A lookup, not a track.

`Stgen.dtd` in `enriched_resolutions_xml_source` declares

    <!ELEMENT zittingsdag ((presentielijst|postprandium?), resolutie*, noot*)+ >

so `postprandium` -- the afternoon sitting -- is a first-class element alternating with the
attendance list, and the trailing `+` lets the whole group repeat: several sittings in one day
are explicitly modelled. `enriched_resolutions_1626_1630` keeps no sitting field, so the
boundary is lost in the flattening.

**Recovering the boundary is deliberately not attempted** (user, 2026-10-06: "it may be very
difficult to retrieve the postprandiums, so i wouldn't try to. Just keep it as a recording in
case of confusion"). This dataset is that recording, in the form that makes it usable: when a
day's structure looks confused -- two axis sessions, a session dated to a neighbouring day, a
resolution count that will not fit one sitting -- check whether it is one of these 109 dates
before reaching for a more elaborate explanation.

What is already known about how they behave, measured 2026-10-06: of the 109, only **3** carry
more than one session on the HTR axis, **67** carry exactly one, and **39** carry none, 32 of
those sitting in the `no_session` population. So the usual outcome is two sittings collapsed
into one session or one sitting transcribed. Conversely only 3 of the 73 dates with several
axis sessions are postprandium days, so afternoon sittings are *not* the main source of that
multiplicity -- which is the main reason not to chase them.

Usage:
    uv run python scripts/build_postprandium_days.py
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve, save_semi_structured

OUTPUT_DATASET = "postprandium_days"
SOURCE_DATASET = "enriched_resolutions_xml_source"


def main() -> None:
    archive = Path(resolve(SOURCE_DATASET))
    with zipfile.ZipFile(archive) as bundle:
        day_files = [
            name for name in bundle.namelist()
            if name.endswith(".xml") and "__MACOSX" not in name and "svn" not in name
        ]
        found: list[dict[str, Any]] = []
        for name in day_files:
            raw = bundle.read(name).decode("utf-8", "replace")
            n_pp = len(re.findall(r"<postprandium", raw, re.IGNORECASE))
            if not n_pp:
                continue
            found.append({
                "file": name.split("/")[-1],
                "n_postprandium": n_pp,
                "n_presentielijst": len(re.findall(r"<presentielijst", raw, re.IGNORECASE)),
                "n_resolutie": len(re.findall(r"<resolutie[ >]", raw, re.IGNORECASE)),
            })

    # Dates via the enriched records' own `file` field, so no filename parsing is invented.
    file_to_date: dict[str, str] = {}
    for record in load("enriched_resolutions_1626_1630"):
        name = str(record.get("file") or "").split("/")[-1]
        if name:
            file_to_date.setdefault(name, str(record.get("date"))[:10])

    rows = []
    for entry in sorted(found, key=lambda e: file_to_date.get(e["file"], e["file"])):
        rows.append({
            "record_type": "postprandium_day",
            "date": file_to_date.get(entry["file"]),
            **entry,
            "sitting_groups": entry["n_presentielijst"] + entry["n_postprandium"],
        })

    unresolved = [r for r in rows if not r["date"]]
    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": "Days the enriched edition's XML records as having two sittings "
                       "(<postprandium>). A lookup to consult when a day's structure looks "
                       "confused; recovering the boundary is deliberately not attempted.",
        "parent_datasets": [SOURCE_DATASET, "enriched_resolutions_1626_1630"],
        "day_files_scanned": len(day_files),
        "postprandium_days": len(rows),
        "dates_unresolved": len(unresolved),
        "not_attempted": "carrying the sitting boundary into enriched_resolutions_1626_1630",
    }
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(rows)} postprandium days (of {len(day_files):,} day files) to {path}")
    print(f"  dates unresolved: {len(unresolved)}")
    print(f"  first few: {[r['date'] for r in rows[:6]]}")


if __name__ == "__main__":
    main()

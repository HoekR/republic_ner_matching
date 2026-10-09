#!/usr/bin/env python3
"""The edition's own person identifiers, with every surface form it writes them under.

User, 2026-10-08: "the edition also uses his assigned id" -- and that closes a real gap. The
enriched resolutions carry `persons` as **ID lists** (`["727016"]`), not names, while the XML
writes each mention as `<persoon idnr="727016">Languerack</persoon>`. So the edition already
disambiguates people, and the only thing missing was the id -> surface mapping.

Why it matters concretely: matching the edition against HTR on raw surface strings silently
fails on spelling. Searching the edition for `Langerack` returned nothing for January 1627
although the resolution was right there, because that entry spells it `Languerack`; id 727016
is written **Langerack, Languerack, Langeracq, Langueracq, Langherack** across the edition, plus
role descriptions (`ambassadeur bij de koning van Frankrijk`). 2,246 of 6,430 ids (35%) carry more
than one surface form -- `De Bije`/`De Bye`/`De Bie`, `Huijgens`/`Huygens`/`Hugens`/`Huigens`.

This is the project's standing rule applied to the edition side: known entities get dictionary
lookup over their recorded variants, not NER.

`kind` separates the two sorts of surface form, and **both are kept** -- role descriptions are
archival content, not noise, and dropping them would violate the no-discarding rule. They are
simply the wrong thing to match a surname against:

* `name`        -- a name-like form, <=3 tokens, no role vocabulary. Use these for matching.
* `description` -- a role or office (`ambassadeur`, `Franse koning`, `heer van Languerack`).

Diagnostic/reference only: reads the frozen XML, writes one dataset, changes no placement.

Usage:
    uv run python scripts/build_enriched_person_variants.py
"""

from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, resolve, save_semi_structured

SOURCE_DATASET = "enriched_resolutions_xml_source"
OUTPUT_DATASET = "enriched_person_name_variants"

PERSON_RE = re.compile(r'<persoon\s+idnr="(\d+)"[^>]*>(.*?)</persoon>', re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
ROLE_RE = re.compile(
    r"ambassad|gezant|resident|agent\b|koning|keurvorst|hertog|graaf van|heer van|"
    r"president|secretaris|griffier|raad van|residerend|commissaris|kapitein|colonel|"
    r"admirael|admiraal|burgemeester|pensionaris|thesaurier|rentmeester",
    re.IGNORECASE,
)


def classify(surface: str) -> str:
    if ROLE_RE.search(surface) or len(surface.split()) > 3:
        return "description"
    return "name"


def main() -> None:
    archive = Path(resolve(SOURCE_DATASET))
    variants: dict[str, Counter] = defaultdict(Counter)
    files = 0
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not name.endswith(".xml") or "__MACOSX" in name or "NihilActum" in name:
                continue
            files += 1
            raw = bundle.read(name).decode("utf-8", "replace")
            for idnr, inner in PERSON_RE.findall(raw):
                surface = " ".join(TAG_RE.sub(" ", inner).split())
                if surface:
                    variants[idnr][surface] += 1

    # Which ids the flattened edition actually uses, so coverage is visible rather than assumed.
    used: Counter = Counter()
    for record in load("enriched_resolutions_1626_1630"):
        for field in ("persons", "president_ids", "deputy_ids"):
            for value in record.get(field) or []:
                used[str(value)] += 1

    rows: list[dict[str, Any]] = []
    for idnr, counter in sorted(variants.items(), key=lambda kv: -sum(kv[1].values())):
        forms = [
            {"surface": s, "count": c, "kind": classify(s)}
            for s, c in counter.most_common()
        ]
        names = [f["surface"] for f in forms if f["kind"] == "name"]
        rows.append({
            "record_type": "person",
            "person_id": idnr,
            "mentions": sum(counter.values()),
            "n_surface_forms": len(forms),
            "n_name_forms": len(names),
            "preferred_name": names[0] if names else forms[0]["surface"],
            "name_variants": names,
            "surface_forms": forms,
            "used_in_flat_edition": used.get(idnr, 0),
        })

    multi = sum(1 for r in rows if r["n_name_forms"] > 1)
    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Person ids from the enriched edition's XML with every surface form it writes them "
            "under. The edition's `persons`/`president_ids`/`deputy_ids` fields are ID lists, so "
            "this is the missing id->name mapping; use `name_variants` for dictionary matching "
            "against HTR and never a single surface form."
        ),
        "parent_datasets": [SOURCE_DATASET, "enriched_resolutions_1626_1630"],
        "day_files_scanned": files,
        "person_ids": len(rows),
        "ids_with_multiple_name_forms": multi,
        "kinds": {
            "name": "name-like, <=3 tokens, no role vocabulary -- match on these",
            "description": "a role or office; archival content, kept deliberately, but never a surname",
        },
        "worked_example": (
            "727016 = Langerack/Languerack/Langeracq/Langueracq/Langherack, plus role "
            "descriptions. A surface search for `Langerack` misses the 1627-01-01 resolution "
            "entirely, which spells it `Languerack`."
        ),
    }
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(rows):,} person ids ({files:,} day files) to {path}")
    print(f"  ids with more than one NAME form: {multi:,} ({multi/len(rows):.0%})")
    print(f"  ids actually used by the flat edition: {sum(1 for r in rows if r['used_in_flat_edition']):,}")
    for r in rows[:5]:
        print(f"    {r['person_id']:>8} {r['mentions']:>6} mentions  {r['name_variants'][:5]}")


if __name__ == "__main__":
    main()

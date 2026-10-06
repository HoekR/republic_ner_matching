#!/usr/bin/env python3
"""Review worklist for enriched dates that found no HTR session.

What this is NOT. The 4,482 resolutions on `no_session` dates decompose (docs/DECISIONS.md
2026-10-06) into 634 on XML-flagged secret dates and 3,848 non-secret, and for 26 of the
non-secret dates the ES `full_resolutions` index holds resolutions. That looked like a
recoverable slice of ~313 resolutions. **It is not, and the reason is that `resolutions_flat`
was itself built from the ES resolutions dump** (user, 2026-10-06), so ES is upstream of this
corpus rather than an independent witness to it. It holds no text this corpus lacks -- the
measured ES/axis character ratio is 0.99 median over 1,316 sessions, which said the same
thing. What differs is only the *date* on sessions already present here: ES carries the
uncorrected first-pass `session_date` (the manifest entry for
`resolution_archival_provenance` declines to carry it for that reason) while this corpus
carries the corrected value.

So the question these rows pose is a date-attribution one, not a missing-text one: for 24
dates the enriched edition records business, and the session ES dates to that day sits in
this corpus under a *later* date -- 23 of 24 later, by 1, 2, 3, 4, 5, 6, 10, 11, 15, 16 or 21
days. Either the enriched date or the corrected session date is wrong for each.

A note on the 10-day cases, as a hypothesis and not a finding: 10 days is the
Julian-Gregorian gap in this period, the Republic used both styles by province, and Old Style
is present in this very HTR (`in dato 13e. lestleden ouden styls`, from Gelderland). But
docs/DECISIONS.md 2026-10-05 checked two dates against their weekdays and found no Julian
correction needed, only 3 of 24 offsets here are 10 days, and 15/16/21 do not fit. The
decisive cheap test is the weekday: `weekday_before` in
`scripts/s6_duplicate_session_date_headings.py` reads the weekday the page states, and
`pd.Period` gives the Gregorian one.

The session's own date heading would arbitrate, and that channel exists
(`scripts/s6_duplicate_session_date_headings.find_headings`: fuzzy to locate, exact day
lookup to verify, weekday as an independent cross-check). Measured on this population it is
mute: of 14 cases checked, 2 matched only the ES date, 0 matched only our label, 10 carried
no findable heading and 2 matched both -- the fuzzy collision that defeated an earlier
design. So the signal is not there, and the honest next step is the one
`resolution_archival_provenance` was built for: point each contested case at its manuscript
image so a human can read the date.

Diagnostic only: produces a review table, changes no placement.

Usage:
    uv run python scripts/build_unplaced_date_review.py
    uv run python scripts/build_unplaced_date_review.py --include-absent
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FORMULATION = Path("/Users/rikhoekstra/develop/formulation")
if FORMULATION.exists() and str(FORMULATION) not in sys.path:
    sys.path.insert(0, str(FORMULATION))

from data_io import load, save_semi_structured
from running_axis.axis import RunningAxis

OUTPUT_DATASET = "unplaced_date_review"
ES_HOST = "annotation.republic-caf.diginfra.org"
IIIF = "https://images.diginfra.net/iiif/NL-HaNA_1.01.02/{inv}/NL-HaNA_1.01.02_{inv}_{scan:04d}.jpg/full/full/0/default.jpg"


def iiif_url(scan_id: str) -> str | None:
    """Manuscript image for a scan id like `NL-HaNA_1.01.02_3185_0023`."""
    parts = str(scan_id).split("_")
    if len(parts) < 2 or not parts[-1].isdigit():
        return None
    return IIIF.format(inv=parts[-2], scan=int(parts[-1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-absent",
        action="store_true",
        help="also list the dates ES has nothing for (nothing to review, but they are the bulk)",
    )
    args = parser.parse_args()

    from formulation.republic_es import ElasticsearchConfig, RepublicEsClient

    axis = RunningAxis.load()
    flags = load("enriched_resolution_secret_flags")
    secret_dates = {str(r["date"])[:10] for r in flags if isinstance(r, dict) and r.get("date")}

    unplaced = {
        state.date: state
        for state in axis.dates.values()
        if state.addressability == "no_session"
    }
    non_secret = sorted(d for d in unplaced if d not in secret_dates)

    client = RepublicEsClient(config=ElasticsearchConfig(host=ES_HOST))
    index = client.config.resolutions_index

    # One pass: which sessions and pages ES attaches to each contested date.
    es_hits: dict[str, dict[str, Any]] = {}
    for start in range(0, len(non_secret), 50):
        chunk = non_secret[start : start + 50]
        body = {
            "size": 400,
            "query": {"terms": {"metadata.session_date": chunk}},
            "_source": ["id", "metadata.session_id", "metadata.session_date",
                        "metadata.inventory_num", "metadata.page_ids"],
        }
        response = client._request_json("POST", f"{index}/_search", body=body)
        for hit in response.get("hits", {}).get("hits") or []:
            source = hit.get("_source") or {}
            meta = source.get("metadata") or {}
            date = str(meta.get("session_date") or "")[:10]
            entry = es_hits.setdefault(
                date,
                {"resolutions": [], "sessions": collections.Counter(), "scans": set()},
            )
            entry["resolutions"].append(str(source.get("id")))
            if meta.get("session_id"):
                entry["sessions"][str(meta["session_id"])] += 1
            for page_id in meta.get("page_ids") or []:
                entry["scans"].add(str(page_id).split("-page-")[0])

    rows: list[dict[str, Any]] = []
    for date in non_secret:
        hit = es_hits.get(date)
        if hit is None and not args.include_absent:
            continue
        state = unplaced[date]
        row: dict[str, Any] = {
            "record_type": "review",
            "enriched_date": date,
            "k_e": state.k_e,
            "status": state.status,
            # Never the authoritative inventory: an unplaced date has no session to read one
            # off, so this is the concordance's candidate pick (see DateState).
            "candidate_inventory": state.candidate_inventory,
            "es_has_resolutions": hit is not None,
        }
        if hit is None:
            row["verdict_needed"] = "none -- ES holds nothing for this date either"
            rows.append(row)
            continue

        session_id, count = hit["sessions"].most_common(1)[0]
        span = axis.sessions.get(session_id)
        scans = sorted(hit["scans"])
        row.update(
            {
                "es_resolution_count": len(hit["resolutions"]),
                "es_session_id": session_id,
                "es_session_resolutions": count,
                "our_axis_has_that_session": span is not None,
                "our_axis_label": list(span.label_dates) if span else [],
                "our_resolved_dates": list(span.resolved_dates) if span else [],
                "our_char_length": span.char_length if span else None,
                "scan_ids": scans,
                "images": [url for url in (iiif_url(s) for s in scans) if url],
                "verdict_needed": (
                    "read the date on the image: does this session belong to the enriched "
                    "date (ES) or to the date our axis labels it with?"
                ),
            }
        )
        rows.append(row)

    reviewable = [r for r in rows if r["es_has_resolutions"]]
    meta = {
        "record_type": "meta",
        "track": OUTPUT_DATASET,
        "description": (
            "Enriched dates with no resolved HTR session, paired with what ES holds for them "
            "and manuscript image links so a human can arbitrate. Neither date source is "
            "trusted: ES session_date is uncorrected first-pass output, resolutions_flat's "
            "session numbering has drifted."
        ),
        "parent_datasets": ["resolution_concordance_1626_1630", "paragraph_axis_1626_1630"],
        "no_session_dates_total": len(unplaced),
        "no_session_resolutions_total": sum(s.k_e for s in unplaced.values()),
        "secret_flagged_dates_excluded": len(unplaced) - len(non_secret),
        "non_secret_dates": len(non_secret),
        "reviewable_dates": len(reviewable),
        "reviewable_resolutions": sum(r["k_e"] for r in reviewable),
        "es_index": index,
    }
    path = save_semi_structured([meta, *rows], logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote review worklist to {path}")
    print(
        f"  {meta['no_session_dates_total']} no_session dates "
        f"({meta['no_session_resolutions_total']:,} resolutions); "
        f"{meta['secret_flagged_dates_excluded']} XML-flagged secret excluded"
    )
    print(
        f"  reviewable: {meta['reviewable_dates']} dates, "
        f"{meta['reviewable_resolutions']:,} resolutions"
    )
    for row in reviewable[:5]:
        print(
            f"    {row['enriched_date']}  k_e={row['k_e']:>3}  ES {row['es_session_id']}"
            f"  our label {','.join(row['our_axis_label']) or '-'}"
            f"  {len(row['images'])} image(s)"
        )
        if row["images"]:
            print(f"      {row['images'][0]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Resolution-level concordance (Step 4C/E of docs/CANDIDATE_SCORING_AND_CONCORDANCE.md).

Expands the day-level ``s4_day_status_resolution`` table to one row per
enriched resolution -- ``enriched_resolutions_1626_1630`` ordered by
``(date, resolution_index)`` is the row-identity anchor, per the doc's
"Long-term target" section. Pure assembly over existing artifacts, no new
matching or alignment logic.

Two wrinkles not covered by the doc, resolved here:

1. **Multiple candidate inventories per date.** Every enriched date matches
   2-3 ``inventory_id`` ledger rows (overlapping ``inventory_metadata``
   periods), so a resolution's date alone does not determine which
   ``s4_day_status_resolution`` row applies. Resolved by ranking the
   candidate rows for that date with ``DAY_STATUS_RANK`` (human-approved >
   automatic > nihil actum > missing HTR > uncertain, matching Step B's own
   precedence) and taking the best; ``inventory_ambiguous`` flags dates where
   more than one candidate ties at the best rank (56 of 1,594 dates in the
   17 Sep 2026 run).
2. **Cross-day shift detection.** The doc requires a resolution whose
   resolved HTR session actually falls on an adjacent day to keep
   ``enriched_date`` as its identity but carry an explicit
   ``cross_day_shift`` status (never a rewritten date). Detected by looking
   up the resolved session's real date in ``resolutions_flat`` and comparing
   it to the resolution's own ``enriched_date``.

Paragraph attribution (which flat paragraph range a resolution maps to
within its resolved session) is attached only when the day resolved to a
specific same-day session and ``s4_corpus_paragraph_predictions`` predicted
cut points for that date with the same resolution count (``k_e``); it is a
best-effort enrichment column per the doc and never affects ``status``.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pandas as pd

from data_io import load, save_parquet

ENRICHED_DATASET = "enriched_resolutions_1626_1630"
DAY_STATUS_DATASET = "s4_day_status_resolution"
FLAT_DATASET = "resolutions_flat"
PARAGRAPH_PREDICTIONS_DATASET = "s4_corpus_paragraph_predictions"
OUTPUT_DATASET = "resolution_concordance_1626_1630"

SESSION_ID_PATTERN = re.compile(r"^(session-\d+-num-\d+)(?:-resolution-\d+)?$")

# Lower rank = more confident. Mirrors s4_day_status_resolution.py's own precedence.
DAY_STATUS_RANK = {
    "resolved_manual": 0,
    "resolved_auto": 1,
    "nihil_actum": 2,
    "missing_htr": 3,
    "uncertain": 4,
}
RESOLVED_STATUSES = {"resolved_auto", "resolved_manual"}


def _normalize_date(value: str) -> str:
    return str(pd.Period(str(value)[:10], freq="D"))


def load_enriched_resolutions() -> list[dict[str, Any]]:
    """Return enriched resolutions with a real date, ordered by (date, resolution_index)."""
    records = load(ENRICHED_DATASET)
    dated = [dict(record) for record in records if record.get("date")]
    skipped = len(records) - len(dated)
    if skipped:
        print(f"Skipping {skipped} enriched record(s) with no date (e.g. the NihilActum.xml template row)")
    for record in dated:
        record["enriched_date"] = _normalize_date(record["date"])
    dated.sort(key=lambda r: (r["enriched_date"], r["resolution_index"]))
    return dated


def group_day_status_by_date(day_status_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in day_status_rows:
        grouped.setdefault(str(row["enriched_date"]), []).append(row)
    return grouped


def select_day_status(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the most confident s4_day_status_resolution row among a date's candidate inventories."""
    ranked = sorted(candidates, key=lambda row: (DAY_STATUS_RANK[row["day_status"]], row["inventory_id"]))
    best_rank = DAY_STATUS_RANK[ranked[0]["day_status"]]
    tied = [row for row in ranked if DAY_STATUS_RANK[row["day_status"]] == best_rank]
    chosen = dict(ranked[0])
    chosen["inventory_ambiguous"] = len(tied) > 1
    chosen["inventory_candidate_count"] = len(candidates)
    return chosen


def build_session_date_lookup(flat: pd.DataFrame) -> dict[str, str]:
    """Map a bare HTR session id (no -resolution-N suffix) to its real date."""
    ids = flat["id"].astype(str).str.extract(SESSION_ID_PATTERN)[0]
    pairs = pd.DataFrame({"session_id": ids, "date": flat["date"].astype(str)}).dropna(subset=["session_id"])
    lookup = pairs.drop_duplicates("session_id").set_index("session_id")["date"]
    return {session_id: _normalize_date(date) for session_id, date in lookup.items()}


def resolution_paragraph_range(
    resolution_index: int, cuts: list[int], paragraph_count: int
) -> tuple[int, int]:
    start = 0 if resolution_index == 0 else cuts[resolution_index - 1]
    end = cuts[resolution_index] if resolution_index < len(cuts) else paragraph_count
    return start, end


def attach_paragraph_attribution(
    resolution_index: int, k_e_local: int, prediction: dict[str, Any] | None
) -> dict[str, Any]:
    empty = {"paragraph_start_index": None, "paragraph_end_index": None, "paragraph_prediction_status": None}
    if prediction is None:
        return empty
    status = prediction.get("status")
    empty["paragraph_prediction_status"] = status
    if status != "predicted" or prediction.get("k_e") != k_e_local:
        return empty
    cuts = sorted(b["paragraph_stream_index"] for b in prediction["boundaries"])
    if len(cuts) != k_e_local - 1 or resolution_index >= k_e_local:
        return empty
    start, end = resolution_paragraph_range(resolution_index, cuts, prediction["paragraph_count"])
    return {"paragraph_start_index": start, "paragraph_end_index": end, "paragraph_prediction_status": status}


def build_row(
    resolution: dict[str, Any],
    k_e_local: int,
    day_status: dict[str, Any],
    session_dates: dict[str, str],
    paragraph_prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved_session_id = day_status.get("resolved_session_id")
    resolved_session_date = session_dates.get(resolved_session_id) if resolved_session_id else None

    status = day_status["day_status"]
    cross_day_shift = bool(resolved_session_date and resolved_session_date != resolution["enriched_date"])
    if cross_day_shift:
        status = "cross_day_shift"

    paragraph_fields = (
        attach_paragraph_attribution(resolution["resolution_index"], k_e_local, paragraph_prediction)
        if status in RESOLVED_STATUSES and not cross_day_shift
        else {"paragraph_start_index": None, "paragraph_end_index": None, "paragraph_prediction_status": None}
    )

    return {
        "enriched_date": resolution["enriched_date"],
        "resolution_index": resolution["resolution_index"],
        "enriched_id": f"{resolution['enriched_date']}_{resolution['resolution_index']}",
        "session_date_key": day_status["session_date_key"],
        "inventory_id": day_status["inventory_id"],
        "inventory_ambiguous": day_status["inventory_ambiguous"],
        "inventory_candidate_count": day_status["inventory_candidate_count"],
        "status": status,
        "day_status": day_status["day_status"],
        "resolution_source": day_status["resolution_source"],
        "resolved_session_id": resolved_session_id,
        "resolved_session_date": resolved_session_date,
        **paragraph_fields,
        "file": resolution.get("file"),
        "text": resolution.get("text"),
        "institutions": resolution.get("institutions"),
        "persons": resolution.get("persons"),
        "places": resolution.get("places"),
        "ships": resolution.get("ships"),
        "secret": resolution.get("secret"),
        "president_ids": resolution.get("president_ids"),
        "deputy_ids": resolution.get("deputy_ids"),
    }


def main() -> None:
    resolutions = load_enriched_resolutions()
    day_status_by_date = group_day_status_by_date(load(DAY_STATUS_DATASET))
    session_dates = build_session_date_lookup(load(FLAT_DATASET))
    paragraph_predictions = {record["date"]: record for record in load(PARAGRAPH_PREDICTIONS_DATASET)}

    k_e_local_by_date = Counter(r["enriched_date"] for r in resolutions)

    records = []
    for resolution in resolutions:
        date = resolution["enriched_date"]
        candidates = day_status_by_date.get(date)
        if not candidates:
            raise ValueError(f"No s4_day_status_resolution row for enriched_date={date!r}")
        day_status = select_day_status(candidates)
        records.append(
            build_row(
                resolution,
                k_e_local_by_date[date],
                day_status,
                session_dates,
                paragraph_predictions.get(date),
            )
        )

    df = pd.DataFrame.from_records(records)
    output = save_parquet(
        df,
        logical_name=OUTPUT_DATASET,
        parent_sources=[ENRICHED_DATASET, DAY_STATUS_DATASET, FLAT_DATASET, PARAGRAPH_PREDICTIONS_DATASET],
        script=__file__,
    )

    assert len(df) == len(resolutions), "Row count must equal enriched_resolutions_1626_1630 (minus undated rows)"

    print(f"Wrote {len(df)} resolution-level concordance rows to {output}")
    print(f"Status distribution: {dict(Counter(df['status']))}")
    print(f"Ambiguous-inventory dates affecting rows: {int(df['inventory_ambiguous'].sum())}")
    print(f"Rows with paragraph attribution: {int(df['paragraph_start_index'].notna().sum())}")


if __name__ == "__main__":
    main()

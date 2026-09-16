"""Build the inventory-aware 1626-1630 session-date evidence ledger.

The canonical row identity is ``(inventory_id, enriched_date)``. Use
``session-<inventory_id>|<enriched_date>`` only as a stable serialized value
in frozen tables and review exports. Calendar dates are represented as
``pd.Period`` values with ``freq="D"`` while the ledger is assembled.

Inputs are loaded by logical name:

* ``enriched_resolutions_1626_1630``
* ``resolutions_flat``
* ``alignment_1626_1630``
* ``paragraph_axis_1626_1630``
* ``inventory_metadata``

The frozen ``session_date_status_1626_1630`` output has these columns:

``session_date_key, inventory_id, enriched_date, enriched_count, enriched_ids,
trusted_session_ids, trusted_anchor_count, trusted_enriched_count,
exact_date_session_ids, exact_date_resolution_count,
exact_date_paragraph_count, previous_day_session_ids, next_day_session_ids,
fallback_distance, nearby_ambiguous, status_code, status_detail``.

Status codes are evidence classifications: ``T`` and ``A`` for unique and
ambiguous trusted candidates; ``E``, ``X``, and ``N`` for unique, ambiguous,
and absent same-day HTR candidates; ``-1``, ``+1``, and ``?`` are reserved for
the review-only nearby-candidate step. No status automatically assigns a
nearby candidate or changes boundary gold.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import pandas as pd

from data_io import load, save_parquet


ENRICHED_DATASET = "enriched_resolutions_1626_1630"
FLAT_DATASET = "resolutions_flat"
ALIGNMENT_DATASET = "alignment_1626_1630"
PARAGRAPH_AXIS_DATASET = "paragraph_axis_1626_1630"
INVENTORY_METADATA_DATASET = "inventory_metadata"
OUTPUT_DATASET = "session_date_status_1626_1630"
DAY_PERIOD = "D"
SESSION_PATTERN = r"^(session-(?P<inventory_id>\d+)-num-\d+)(?:-resolution-|$)"

LEDGER_COLUMNS = (
    "session_date_key",
    "inventory_id",
    "enriched_date",
    "enriched_count",
    "enriched_ids",
    "trusted_session_ids",
    "trusted_anchor_count",
    "trusted_enriched_count",
    "exact_date_session_ids",
    "exact_date_resolution_count",
    "exact_date_paragraph_count",
    "previous_day_session_ids",
    "next_day_session_ids",
    "fallback_distance",
    "nearby_ambiguous",
    "status_code",
    "status_detail",
)


def _as_frame(records: pd.DataFrame | Iterable[dict[str, Any]]) -> pd.DataFrame:
    return records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)


def _dates_in_scope(values: pd.Series) -> pd.Series:
    periods = pd.PeriodIndex(values.astype(str).str[:10], freq=DAY_PERIOD)
    return pd.Series(periods.astype(str), index=values.index)


def _session_parts(values: pd.Series) -> pd.DataFrame:
    parts = values.astype(str).str.extract(SESSION_PATTERN)
    if parts.isna().any(axis=None):
        bad = values.loc[parts.isna().any(axis=1)].head(3).tolist()
        raise ValueError(f"Could not parse HTR session ID(s): {bad}")
    return parts


def _ordered_unique(values: pd.Series) -> list[str]:
    return sorted({str(value) for value in values.dropna()})


def _inventory_dates(enriched: pd.DataFrame, inventory_metadata: Iterable[dict[str, Any]]) -> pd.DataFrame:
    metadata = pd.DataFrame(inventory_metadata)
    metadata = metadata.loc[:, ["inventory_num", "period_start", "period_end"]].dropna().copy()
    metadata["inventory_id"] = metadata["inventory_num"].astype(int)
    metadata["period_start"] = pd.PeriodIndex(metadata["period_start"].astype(str), freq=DAY_PERIOD)
    metadata["period_end"] = pd.PeriodIndex(metadata["period_end"].astype(str), freq=DAY_PERIOD)
    dates = enriched.loc[:, ["enriched_date"]].drop_duplicates().copy()
    dates["enriched_period"] = pd.PeriodIndex(dates["enriched_date"], freq=DAY_PERIOD)
    dates = dates.merge(metadata[["inventory_id", "period_start", "period_end"]], how="cross")
    dates = dates.loc[
        dates["enriched_period"].ge(dates["period_start"])
        & dates["enriched_period"].le(dates["period_end"])
    ]
    if dates.empty:
        raise ValueError("No inventory metadata periods overlap enriched dates")
    return dates.loc[:, ["inventory_id", "enriched_date"]]


def add_nearby_candidates(ledger: pd.DataFrame, direct_sessions: pd.DataFrame) -> pd.DataFrame:
    """Add review-only +/-1-day evidence to unresolved same-day ledger rows."""
    result = ledger.copy()
    result["previous_day_session_ids"] = [[] for _ in range(len(result))]
    result["next_day_session_ids"] = [[] for _ in range(len(result))]
    result["fallback_distance"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["nearby_ambiguous"] = False

    unresolved = result.loc[result["status_code"].eq("N"), ["inventory_id", "enriched_date"]].copy()
    if unresolved.empty:
        return result
    unresolved["enriched_period"] = pd.PeriodIndex(unresolved["enriched_date"], freq=DAY_PERIOD)
    candidates = direct_sessions.loc[:, ["inventory_id", "date", "session_id"]].drop_duplicates().copy()
    candidates["date_period"] = pd.PeriodIndex(candidates["date"], freq=DAY_PERIOD)
    for distance, column in ((-1, "previous_day_session_ids"), (1, "next_day_session_ids")):
        lookup = unresolved.copy()
        lookup["date_period"] = lookup["enriched_period"] + distance
        matches = lookup.merge(candidates, on=["inventory_id", "date_period"], how="left")
        grouped = matches.groupby(["inventory_id", "enriched_date"], as_index=False).agg(
            **{column: ("session_id", _ordered_unique)}
        )
        result = result.merge(grouped, on=["inventory_id", "enriched_date"], how="left", suffixes=("", "_new"))
        result[column] = result[f"{column}_new"].apply(lambda value: value if isinstance(value, list) else [])
        result = result.drop(columns=f"{column}_new")

    previous_count = result["previous_day_session_ids"].str.len()
    next_count = result["next_day_session_ids"].str.len()
    unresolved = result["status_code"].eq("N")
    unique_previous = unresolved & previous_count.eq(1) & next_count.eq(0)
    unique_next = unresolved & previous_count.eq(0) & next_count.eq(1)
    ambiguous = unresolved & ~unique_previous & ~unique_next & (previous_count.gt(0) | next_count.gt(0))
    result.loc[unique_previous, ["status_code", "status_detail", "fallback_distance"]] = [
        "-1", "one previous-day HTR session candidate pending review", -1
    ]
    result.loc[unique_next, ["status_code", "status_detail", "fallback_distance"]] = [
        "+1", "one next-day HTR session candidate pending review", 1
    ]
    result.loc[ambiguous, ["status_code", "status_detail", "nearby_ambiguous"]] = [
        "?", "multiple nearby HTR session candidates pending review", True
    ]
    return result


def build_session_date_ledger(
    enriched_records: pd.DataFrame | Iterable[dict[str, Any]],
    flat_resolutions: pd.DataFrame,
    alignment: pd.DataFrame,
    paragraph_axis: pd.DataFrame | Iterable[dict[str, Any]],
    inventory_metadata: Iterable[dict[str, Any]],
) -> pd.DataFrame:
    """Return one evidence-classified row for each enriched inventory-date.

    The function retains all trusted and exact-date session candidates as
    ordered lists. It never assigns a candidate from an ambiguous row.
    """
    enriched = _as_frame(enriched_records)
    axis = _as_frame(paragraph_axis)
    flat = flat_resolutions.copy()
    anchors = alignment.copy()

    enriched = enriched.loc[enriched["date"].notna(), ["date", "resolution_index"]].copy()
    enriched["enriched_date"] = _dates_in_scope(enriched["date"])
    enriched["year"] = enriched["enriched_date"].str[:4].astype(int)
    enriched["enriched_id"] = enriched["enriched_date"] + "_" + enriched["resolution_index"].astype(str)

    flat["date"] = _dates_in_scope(flat["date"])
    flat_parts = _session_parts(flat["id"])
    flat["session_id"] = flat_parts[0]
    flat["inventory_id"] = flat_parts["inventory_id"].astype(int)
    flat["year"] = flat["date"].str[:4].astype(int)
    enriched = enriched.merge(_inventory_dates(enriched, inventory_metadata), on="enriched_date", how="inner")

    base = (
        enriched.groupby(["inventory_id", "enriched_date"], as_index=False)
        .agg(enriched_count=("enriched_id", "size"), enriched_ids=("enriched_id", _ordered_unique))
    )

    anchor_parts = _session_parts(anchors["session_id"])
    anchors["inventory_id"] = anchor_parts["inventory_id"].astype(int)
    anchors["enriched_date"] = _dates_in_scope(anchors["date"])
    trusted = anchors.loc[anchors["confidence_tier"].eq("tier1_anchor")].copy()
    trusted_summary = (
        trusted.groupby(["inventory_id", "enriched_date"], as_index=False)
        .agg(
            trusted_session_ids=("session_id", _ordered_unique),
            trusted_anchor_count=("enriched_id", "size"),
            trusted_enriched_count=("enriched_id", "nunique"),
        )
    )

    axis["date"] = _dates_in_scope(axis["date"])
    axis_parts = _session_parts(axis["flat_id"])
    axis["session_id"] = axis_parts[0]
    paragraph_counts = axis.groupby("session_id", as_index=False).agg(exact_date_paragraph_count=("axis_id", "size"))
    direct = (
        flat.groupby(["inventory_id", "date", "session_id"], as_index=False)
        .agg(exact_date_resolution_count=("id", "size"))
        .merge(paragraph_counts, on="session_id", how="left", validate="one_to_one")
    )
    direct["exact_date_paragraph_count"] = direct["exact_date_paragraph_count"].fillna(0).astype(int)
    direct_summary = (
        direct.groupby(["inventory_id", "date"], as_index=False)
        .agg(
            exact_date_session_ids=("session_id", _ordered_unique),
            exact_date_resolution_count=("exact_date_resolution_count", "sum"),
            exact_date_paragraph_count=("exact_date_paragraph_count", "sum"),
        )
        .rename(columns={"date": "enriched_date"})
    )

    ledger = base.merge(trusted_summary, on=["inventory_id", "enriched_date"], how="left")
    ledger = ledger.merge(direct_summary, on=["inventory_id", "enriched_date"], how="left")
    for column in ("trusted_session_ids", "exact_date_session_ids"):
        ledger[column] = ledger[column].apply(lambda value: value if isinstance(value, list) else [])
    for column in ("trusted_anchor_count", "trusted_enriched_count", "exact_date_resolution_count", "exact_date_paragraph_count"):
        ledger[column] = ledger[column].fillna(0).astype(int)

    trusted_candidates = ledger["trusted_session_ids"].str.len()
    exact_candidates = ledger["exact_date_session_ids"].str.len()
    ledger["status_code"] = "N"
    ledger.loc[exact_candidates.eq(1), "status_code"] = "E"
    ledger.loc[exact_candidates.gt(1), "status_code"] = "X"
    ledger.loc[trusted_candidates.eq(1), "status_code"] = "T"
    ledger.loc[trusted_candidates.gt(1), "status_code"] = "A"
    ledger["status_detail"] = ledger["status_code"].map(
        {"T": "one trusted Tier-1 session candidate", "A": "multiple trusted Tier-1 session candidates", "E": "one direct exact-date HTR session candidate", "X": "multiple direct exact-date HTR session candidates", "N": "no same-day HTR session candidate"}
    )
    ledger["session_date_key"] = "session-" + ledger["inventory_id"].astype(str) + "|" + ledger["enriched_date"]
    ledger = add_nearby_candidates(ledger, direct)
    return ledger.loc[:, LEDGER_COLUMNS].sort_values(["inventory_id", "enriched_date"]).reset_index(drop=True)


def main() -> None:
    ledger = build_session_date_ledger(
        load(ENRICHED_DATASET),
        load(FLAT_DATASET),
        load(ALIGNMENT_DATASET),
        load(PARAGRAPH_AXIS_DATASET),
        load(INVENTORY_METADATA_DATASET),
    )
    output = save_parquet(ledger, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(ledger)} inventory-date rows to {output}")


if __name__ == "__main__":
    main()
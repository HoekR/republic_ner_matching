#!/usr/bin/env python3
"""Export session-date review rows and run S4 only on supported ledger mappings.

Only same-day, unique trusted (``T``) and direct (``E``) mappings are selected.
Unique ``-1`` and ``+1`` candidates remain abstentions until a selection policy
is explicitly approved. All candidate lists are retained in every output row.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from build_alignment_new import calculate_idf_weights
from data_io import load, resolve, save_semi_structured
from scripts.s4_corpus_paragraph_predictions import OVERLAP_DATASETS, predict
from scripts.s4_paragraph_axis_baseline import build_axis_overlap


AXIS_DATASET = "paragraph_axis_1626_1630"
LEDGER_DATASET = "session_date_status_1626_1630"
OUTPUT_DATASET = "s4_session_date_mapping_predictions"
REVIEW_DATASET = "session_date_status_1626_1630_review"
AUTO_SELECT_STATUSES = {"T": "trusted_session_ids", "E": "exact_date_session_ids"}


def _as_list(value: Any) -> list[str]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if value is None or (not isinstance(value, (list, tuple)) and pd.isna(value)):
        return []
    return [str(item) for item in value]


def selected_session(row: pd.Series) -> tuple[str | None, str | None]:
    """Return an approved automatic mapping, otherwise its abstention reason."""
    source_column = AUTO_SELECT_STATUSES.get(str(row["status_code"]))
    if source_column:
        candidates = _as_list(row[source_column])
        if len(candidates) == 1:
            return candidates[0], None
        return None, "invalid_unique_evidence"
    if str(row["status_code"]) in {"-1", "+1"}:
        return None, "nearby_policy_pending"
    if str(row["status_code"]) in {"A", "X", "?"} or bool(row["nearby_ambiguous"]):
        return None, "ambiguous_session_candidates"
    return None, "no_supported_session_candidate"


def review_frame(ledger: pd.DataFrame) -> pd.DataFrame:
    """Return the human review export with stable key and unmodified evidence."""
    columns = [
        "session_date_key", "inventory_id", "enriched_date", "status_code", "status_detail",
        "trusted_anchor_count", "trusted_session_ids", "exact_date_session_ids",
        "previous_day_session_ids", "next_day_session_ids", "fallback_distance",
        "nearby_ambiguous", "exact_date_paragraph_count",
    ]
    review = ledger.loc[:, columns].copy()
    for column in ("trusted_session_ids", "exact_date_session_ids", "previous_day_session_ids", "next_day_session_ids"):
        review[column] = review[column].apply(lambda value: "; ".join(_as_list(value)))
    review["review_note"] = ""
    return review


def mapping_records(
    ledger: pd.DataFrame,
    axis_by_session: dict[str, list[dict[str, Any]]],
    lookup: dict[tuple[str, str], set[str]],
    idf_weights: dict[str, float],
) -> list[dict[str, Any]]:
    """Predict approved mappings and preserve evidence on all abstentions."""
    records: list[dict[str, Any]] = []
    for _, row in ledger.sort_values(["inventory_id", "enriched_date"]).iterrows():
        selected, abstention_reason = selected_session(row)
        evidence = {
            "session_date_key": row["session_date_key"],
            "inventory_id": int(row["inventory_id"]),
            "enriched_date": row["enriched_date"],
            "ledger_status": row["status_code"],
            "selected_session_id": selected,
            "trusted_session_ids": _as_list(row["trusted_session_ids"]),
            "exact_date_session_ids": _as_list(row["exact_date_session_ids"]),
            "previous_day_session_ids": _as_list(row["previous_day_session_ids"]),
            "next_day_session_ids": _as_list(row["next_day_session_ids"]),
            "fallback_distance": None if pd.isna(row["fallback_distance"]) else int(row["fallback_distance"]),
            "nearby_ambiguous": bool(row["nearby_ambiguous"]),
        }
        if selected is None:
            records.append({**evidence, "status": "abstained", "reason": abstention_reason, "boundaries": []})
            continue
        prediction = predict(
            str(row["enriched_date"]),
            _as_list(row["enriched_ids"]),
            axis_by_session.get(selected, []),
            lookup,
            idf_weights,
        )
        records.append({**evidence, **prediction})
    return records


def main() -> None:
    ledger = load(LEDGER_DATASET)
    review_output = Path(resolve(REVIEW_DATASET))
    review_output.parent.mkdir(parents=True, exist_ok=True)
    review_frame(ledger).to_csv(review_output, index=False)

    axis = load(AXIS_DATASET)
    axis_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in axis:
        axis_by_session[str(record["flat_id"]).split("-resolution-", 1)[0]].append(record)
    overlaps = [pd.read_excel(resolve(dataset)) for dataset in OVERLAP_DATASETS]
    overlaps = [frame.rename(columns={"naam": "name"}) if "name" not in frame and "naam" in frame else frame for frame in overlaps]
    combined = pd.concat(overlaps, ignore_index=True)
    records = mapping_records(ledger, axis_by_session, build_axis_overlap(axis, combined), calculate_idf_weights(combined))
    output = save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
    print(f"Wrote {len(records)} mapping-aware rows to {output}")
    print(f"Wrote {len(ledger)} review rows to {review_output}")
    print(f"Coverage by ledger status: {dict(Counter(item['ledger_status'] for item in records))}")
    print(f"Prediction outcomes: {dict(Counter(item['status'] for item in records))}")


if __name__ == "__main__":
    main()
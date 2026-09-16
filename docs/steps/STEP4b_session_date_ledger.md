# S4b: Session-Date Ledger

## Goal

Build one canonical row for every `(inventory_id, enriched_date)` in 1626-1630, recording only evidence already known from trusted anchors and direct HTR dates.

## Depends On

S4a.

## Required Columns

```text
session_date_key,inventory_id,enriched_date,enriched_count,enriched_ids,
trusted_session_ids,trusted_anchor_count,trusted_enriched_count,
exact_date_session_ids,exact_date_resolution_count,exact_date_paragraph_count,
status_code,status_detail
```

## Rules

1. Aggregate Tier-1 rows from `alignment_1626_1630` by inventory and enriched date.
2. Build direct HTR candidates from `resolutions_flat`, grouped by parsed inventory ID, assigned date, and full `session-<inventory>-num-<n>` session ID.
3. Prefer evidence classification, not selection: emit T/A when trusted candidates exist; otherwise E/X/N from direct HTR candidates.
4. Retain all candidates as ordered lists. Never select an arbitrary candidate from an ambiguous set.

## Done When

The frozen ledger contains one row per enriched inventory-date and each candidate session belongs to the row's inventory.

## Verification

Run unit tests for trusted unique/ambiguous and exact-date unique/ambiguous classification, then:

```bash
uv run python -m scripts.build_session_date_ledger
```
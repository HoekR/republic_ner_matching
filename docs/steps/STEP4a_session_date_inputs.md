# S4a: Session-Date Inputs
<!-- doc-status: active -->

## Goal

Define the inventory-aware key and register all datasets required for session-date status mapping.

## Key

The canonical key is `(inventory_id, enriched_date)`. Use `session-3186|1627-09-02` only as a stable serialized value for tables and review exports.

## Inputs

- `enriched_resolutions_1626_1630`: normative enriched resolutions.
- `resolutions_flat`: HTR resolution records and their assigned dates.
- `alignment_1626_1630`: trusted Tier-1 resolution anchors.
- `paragraph_axis_1626_1630`: HTR paragraph counts per session-date.

## Outputs

- `session_date_status_1626_1630` as canonical frozen Parquet.
- `session_date_status_1626_1630_review` as a derived, date-indexed CSV or XLSX.

## Status Codes

| Code | Meaning |
|---|---|
| T | One trusted Tier-1-supported session candidate. |
| A | Multiple trusted candidates. |
| E | One direct exact-date HTR candidate. |
| X | Multiple direct exact-date HTR candidates. |
| N | No same-day HTR candidate. |
| -1 | One previous-day candidate, pending review. |
| +1 | One next-day candidate, pending review. |
| ? | No nearby candidate or unresolved ambiguity. |

## Constraints

- Register manifest keys before code references them.
- Use `pd.Period(freq="D")` ordinal arithmetic for any date offsets.
- Never treat `N` as absent source text; it means no same-day HTR assignment.
- Do not alter gold boundaries or automatically assign nearby candidates.

## Done When

The manifest resolves all inputs and both outputs, and the ledger schema is documented in its builder module.

## Verification

```bash
uv run python -m data_io.check
```
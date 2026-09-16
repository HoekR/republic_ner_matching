# S4c: Nearby Session Candidates

## Goal

For ledger rows with no same-day HTR candidate, enumerate inventory-local candidates exactly one calendar day before and after the enriched date.

## Depends On

S4b.

## Rules

1. Restrict to status `N` only.
2. Construct dates with `pd.Period(enriched_date, freq="D")`.
3. Store `previous_day_session_ids` and `next_day_session_ids` separately.
4. Set `fallback_distance` to `-1`, `+1`, or `null`; retain `nearby_ambiguous` if multiple candidate sessions remain.
5. Do not modify `selected_session_id` in this step.

## Done When

Every `N` row has explicit previous/next candidate fields and an auditable nearby status.

## Verification

Unit-test unique previous-day, unique next-day, ambiguous nearby, and no-nearby cases. Confirm no candidate crosses inventory boundaries.
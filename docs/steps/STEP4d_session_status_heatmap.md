# S4d: Session Status Heatmap
<!-- doc-status: active -->

## Goal

Render a per-inventory-year calendar heatmap from the session-date ledger, making known and unresolved date assignments visible at a glance.

## Depends On

S4c.

## Display

- One calendar panel per inventory-year.
- One colored cell per enriched date.
- Colors correspond to T, A, E, X, N, -1, +1, and ?.
- Hover text includes the composite key, anchor count, candidate sessions, fallback distance, and HTR paragraph count.
- Include a legend and counts by status.

## Constraints

- The heatmap is diagnostic only. It must not assign sessions or change the ledger.
- Use a manifest-registered HTML output.
- Preserve readable cell sizes and visible status labels at desktop and mobile widths.

## Done When

The heatmap renders all ledger rows, has a non-empty panel for every inventory-year, and displays the status legend/counts.

## Verification

Open the generated HTML and check that `N` and nearby-candidate statuses are visually distinct.
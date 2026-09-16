# Session-Date Evidence Review UI

**Status:** tooling implemented (1 Sep 2026); human review pending

## Goal

Build a self-contained review UI for non-automatic session-date mappings. It
will show enriched text beside all inventory-local HTR candidate text, export
human decisions, and merge them into a separate approved artifact. The frozen
ledger and the existing S4 mapping output remain unchanged.

## Scope

The UI queues only ledger statuses `A`, `X`, `?`, `-1`, `+1`, and `N`.
Automatic `T` and `E` rows are excluded.

Each queued row must display:

- Original ledger evidence and status detail.
- All four original candidate lists: trusted, exact-date, previous-day, and
  next-day.
- Enriched resolutions for the ledger date, in order.
- A de-duplicated candidate union with its source-list labels.
- Complete ordered HTR resolution and paragraph text for every candidate.

Reviewers may choose a candidate, mark no match, or defer. A note is mandatory
when choosing a `-1` or `+1` candidate. Confidence is not recorded. The UI
records a client timestamp; the merge command supplies reviewer identity.

## Implementation steps

1. Register three outputs in `data_manifest.toml` before scripts reference
   them: the review HTML (`explore`), exported decision JSON (`semi`), and
   `s4_session_date_mapping_predictions_approved` (`semi`). Add the same
   logical names to the `PLAN.md` data-path table.
2. Add `scripts/build_session_date_mapping_review_ui.py`, reusing the
   self-contained HTML, bounded pagination, versioned localStorage migration,
   and Blob download pattern from `build_boundary_annotation_ui.py`.
3. Load `session_date_status_1626_1630`,
   `enriched_resolutions_1626_1630`, `resolutions_flat`, and
   `paragraph_axis_1626_1630` through `data_io`. Sort rows by inventory and
   enriched date. Normalize parquet arrays with the existing `_as_list`
   convention; retain `pd.Period` discipline for early-modern dates.
4. Create testable payload helpers that preserve all ledger evidence and build
   the inventory-local candidate union from `trusted_session_ids`,
   `exact_date_session_ids`, `previous_day_session_ids`, and
   `next_day_session_ids`.
5. Persist one decision per `session_date_key` in localStorage. Enforce action,
   selected-candidate membership, and the nearby-approval note rule before
   saving or exporting. Report queue progress and validation errors in the UI.
6. Export versioned JSON keyed by `session_date_key`, including format marker,
   export timestamp, queue/status counts, original evidence, action, selected
   candidate or null, note, and client timestamp.
7. Add `scripts/merge_session_date_mapping_decisions.py` with required
   `--reviewer NAME`. Load the frozen ledger and exported decisions through
   `data_io`. For duplicate decision keys, use the final occurrence in file
   order.
8. Validate decision format, known key, non-automatic ledger status, action,
   original ledger-status agreement, and selected membership in the row's
   four-list candidate union. Reject nearby approvals without notes.
9. Emit one sorted record per ledger row without mutating the ledger. Retain
   all original evidence; label reviewed selections `approved`, no-match rows
   `abstained`, deferrals `deferred`, and untouched rows `unreviewed`. Record
   reviewer, merge timestamp, decision client timestamp, note, and decision
   source where applicable.
10. Write the output with `save_semi_structured` using logical name
    `s4_session_date_mapping_predictions_approved`, producing its provenance
    sidecar. Do not run segmentation or evaluate approved cross-day mappings
    against within-day gold.
11. Add focused tests for queue filtering, evidence assembly and ordering,
    candidate de-duplication, nearby-note enforcement, candidate validation,
    last-file-order-wins behavior, merge idempotency, and unreviewed-row
    preservation.

## Data contract

`session_date_key` is the stable identity. An approved candidate must belong to
the union of that row's trusted, exact-date, previous-day, and next-day session
IDs. The merged JSONL is ledger-derived and contains every ledger row; it is
not a replacement for either `session_date_status_1626_1630` or
`s4_session_date_mapping_predictions`.

## Verification

1. Run focused tests:

   ```bash
   uv run pytest tests/test_build_session_date_mapping_review_ui.py \
     tests/test_merge_session_date_mapping_decisions.py
   ```

2. After manifest edits, run:

   ```bash
   uv run python -m data_io.check
   ```

3. Build the HTML and manually verify enriched and HTR evidence, pagination,
   localStorage restoration, JSON export, and required nearby-approval notes.
4. Merge a representative decision export with `--reviewer NAME`; inspect the
   JSONL and provenance sidecar. Confirm that candidate selections are
   inventory-local and that the frozen ledger and current S4 prediction output
   remain untouched.
5. Re-run the merge with identical inputs to check idempotent content. Include
   duplicate keys in a controlled export and verify that the final file-order
   occurrence wins.
6. Report coverage by ledger status and review status alongside S4e's
   `244 / 1,594` baseline. Do not include human-approved cross-day decisions in
   within-day gold evaluation.
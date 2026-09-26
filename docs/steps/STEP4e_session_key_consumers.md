# S4e: Session-Key Consumers
<!-- doc-status: active -->

## Goal

Use only uniquely supported ledger mappings in downstream corpus segmentation, while preserving unresolved and ambiguous cases as abstentions.

## Depends On

S4c. May proceed in parallel with S4d.

## Work

1. Write a review CSV/XLSX derived from the frozen ledger, keyed by `session_date_key`, with short status codes and a free-text note column.
2. Create a new mapping-aware corpus S4 prediction artifact. Do not overwrite `s4_corpus_paragraph_predictions`.
3. Select sessions automatically only for `T`, `E`, and uniquely supported `-1`/`+1` outcomes after their selection policy is explicitly approved.
4. Retain `A`, `X`, nearby ambiguity, and `?` as abstentions with their full candidate lists.

## Done When

The mapping-aware output reports coverage by ledger status and preserves candidate evidence for every abstention.

## Verification

Compare mapping-aware coverage with the baseline `244 / 1,594` corpus predictions. Do not evaluate cross-day mappings against within-day gold boundaries.
# Candidate Scoring Prototype and Resolution-Level Concordance

**Status:** planned (2 Sep 2026)

## Background

Manual review of the S4f queue (3,807 rows) surfaced two problems:

1. Reviewing every row by hand does not scale, and 3,197 of those rows
   (status `N`) have no candidate at all within the ledger's checked
   `+/-1`-day window, so there is nothing to hand-review there in the first
   place.
2. The day-level ledger and S4f decisions only resolve *which HTR session*
   maps to a calendar day. They do not resolve *which specific resolution*
   within that session matches a specific enriched resolution, and they
   cannot express a resolution that is filed under one day but whose real
   HTR content sits on an adjacent day.

This document plans the next two steps, in order, plus the longer-term
target they both feed into.

## Step 1 — `N`-status gap diagnostic (pending)

Goal: determine whether `N`-status rows are true gaps or an artifact of the
`+/-1`-day search window, and whether they concentrate on particular
weekdays.

- Script: `analyze_n_status_gaps.py` (root-level, matching the existing
  `analyze_*.py` convention). Not yet created — file creation was blocked by
  a disabled tool in a prior session; still pending.
- Logic: for every `N` row in `session_date_status_1626_1630`, compute its
  calendar weekday via `pd.PeriodIndex(..., freq="D").dayofweek` (never
  `pd.to_datetime`/`Timestamp` for these pre-1678 dates), and search the same
  inventory's HTR sessions at offsets `+/-2` through `+/-14` days (beyond the
  `+/-1` window `add_nearby_candidates` already checks in
  `scripts/build_session_date_ledger.py`).
- Output: a weekday distribution, a recovered-vs-unrecovered split, and an
  offset histogram for recovered rows. This is diagnostic only — it does not
  change the ledger or any prior artifact.
- Explicit non-goal: do not fabricate a Dutch Republic/States-General
  holiday or recess calendar. Weekday concentration is suggestive only and
  needs a verified historical source before being treated as fact.

## Step 2 — Candidate scoring prototype for `A`/`X` rows

Goal: replace manual "search a term, check context" review with an automatic
score per candidate, starting on the lowest-risk rows: `A` (multiple trusted
same-day candidates) and `X` (multiple exact-date same-day candidates) — 7
rows total, no cross-day ambiguity.

### Design

- Reuse existing machinery; do not build new matching logic:
  - Entity-IDF overlap: `calculate_idf_weights` and the per-pair overlap
    lookups already loaded in
    `scripts/s4_session_date_mapping_predictions.py` (place/org/person
    overlap datasets).
  - Dense text similarity: `AlignmentEmbedder` in `alignment_embeddings.py`
    (`tfidf` backend is sufficient for a first pass; no GPU dependency).
- For each `A`/`X` row, score every candidate in its relevant list
  (`trusted_session_ids` for `A`, `exact_date_session_ids` for `X`) against
  the row's enriched resolution text for that date, using concatenated flat
  resolution text per candidate session (reusing `_candidate_text`-style
  extraction already written for the S4f review UI).
- Rank candidates by combined score; do not auto-select — this prototype
  produces a ranked suggestion for a human to confirm, it does not bypass
  review.

### Steps

1. Add `notebooks/candidate_scoring_prototype.ipynb`: load the ledger, filter
   to `status_code` in `{"A", "X"}`, score each row's candidates, and display
   enriched text next to each candidate's text and score for manual eyeball
   comparison against the existing 7 rows.
2. Add `tests/test_candidate_scoring.py` with a small synthetic fixture
   (a handful of made-up enriched/candidate text pairs with a known best
   match) so the scoring function's core property — highest score for the
   candidate sharing the most distinctive terms — is checked without loading
   the full corpus.
3. Extract the scoring function itself into a plain module (not notebook-only
   code) so it can later be reused by `scripts/s4_session_date_mapping_predictions.py`
   or the S4f review UI as a ranked suggestion, once validated.

### Verification

1. Run the notebook top-to-bottom against the real 7 `A`/`X` rows; manually
   confirm the top-ranked candidate looks correct for each.
2. Run `uv run pytest tests/test_candidate_scoring.py`.
3. Report the score distribution and whether ranking agrees with manual
   judgment, before considering extending scoring to `?`/`-1`/`+1` rows.

## Long-term target — resolution-level concordance

The day-level ledger and S4f decisions, plus within-session paragraph
prediction (`s4_corpus_paragraph_predictions`), are inputs to a single
ordered concordance spanning enriched resolution 1 of 1626 through the last
resolution of 1630 (ordered by `(date, resolution_index)` — no inventory
grouping needed for this ordering), not separate end products.

Constraints agreed so far:

- Every row carries a closed status, extending the existing
  `REVIEW_ABSTENTION_REASONS` vocabulary (`missing_htr`, `cross_day_shift`,
  `nihil_actum`, `uncertain`) with resolved states (`resolved_auto`,
  `resolved_manual`) rather than leaving gaps implicit.
- A resolution filed under day X whose real HTR content is on day X-1/X+1
  must be modeled as a separate resolution-level attribution layer. Do not
  mutate the `(inventory_id, enriched_date)` ledger row identity to represent
  this.
- Never insert synthetic "nihil actum" placeholder text into any merged
  artifact — it is a status flag only, per the existing `nihil_actum`
  convention in `scripts/s4_paragraph_axis_baseline.py` /
  `scripts/s4_resolution_baseline.py`.
- This concordance is an assembly/join over existing artifacts; it is not a
  new alignment algorithm.

This section will be expanded into its own implementation plan once Steps 1
and 2 above report results.

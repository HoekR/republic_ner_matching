# Candidate Scoring Prototype and Resolution-Level Concordance

**Status:** Steps 1-3 done (17 Sep 2026); Step 4 (concordance implementation
plan) drafted 17 Sep 2026, sub-step A built 17 Sep 2026, B-F not yet built.

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

## Step 1 — `N`-status gap diagnostic (done, 17 Sep 2026)

Goal: determine whether `N`-status rows are true gaps or an artifact of the
`+/-1`-day search window, and whether they concentrate on particular
weekdays.

- Script: `analyze_n_status_gaps.py` (root-level, matching the existing
  `analyze_*.py` convention). Was already written as of 2 Sep 2026 (the
  "not yet created" note above was stale); had never been run. Two bugs
  fixed to get it running: `.dt.dayofweek` (a `Series` of `Period` objects
  needs the `.dt` accessor), an `int()` cast before `:+d` formatting (the
  offset column becomes `float64` once it holds `None`s), and a real
  correctness bug — `EXTRA_OFFSETS` iterated `-14 .. -2, 2 .. 14` in ascending
  order, so `nearest_recovery_offset` returned the first *far* match before
  checking anything closer; fixed to search by `(abs(offset), offset)`.
- Logic: for every `N` row in `session_date_status_1626_1630`, compute its
  calendar weekday via `pd.PeriodIndex(..., freq="D")` (never
  `pd.to_datetime`/`Timestamp` for these pre-1678 dates), and search the same
  inventory's HTR sessions at offsets `+/-2` through `+/-14` days (beyond the
  `+/-1` window `add_nearby_candidates` already checks in
  `scripts/build_session_date_ledger.py`).
- **Results** (3,197 `N`-status rows, 65% of the 4,916-row ledger):
  - Weekday distribution is flat (14.1-14.8% every day, both overall and
    among still-unrecovered rows) — no weekly-recess signal at all; the
    non-goal below is moot, there's nothing to fabricate a calendar from.
  - 753/3,197 (23.6%) recover within +/-14 days, front-loaded: +/-2 days
    alone recovers 174 rows (5.4%), cumulative through +/-7 days is 523 rows
    (16.4%), steep diminishing returns past that.
  - **2,444/3,197 (76.4%) stay unrecovered even at +/-14 days** — no HTR
    session exists for that inventory anywhere within a full month of the
    calendar date. This is 2,444/4,916 = 49.7% of the *entire ledger*: a
    structural coverage ceiling, not a matching-quality gap. No amount of
    better entity/text matching closes it, since there is nothing on the
    HTR side to match to.
  - Implication for the concordance: realistic full-corpus coverage is
    well under 100% regardless of matching quality; expect roughly half the
    ledger to close as `missing_htr`. A modest window widen (say +/-3 to
    +/-7 days, not the full +/-14 tested here) could reclaim ~10-16% of the
    `N` population and is a candidate follow-up, but was not implemented in
    this diagnostic run — this step is read-only per its own constraint.
- Explicit non-goal (confirmed moot by the flat weekday distribution): do
  not fabricate a Dutch Republic/States-General holiday or recess calendar.

## Step 2 — Candidate scoring prototype for `A`/`X` rows (done, 17 Sep 2026)

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

### Results (done, 17 Sep 2026)

Ran the notebook against all 7 `A`/`X` rows and manually checked each
top-ranked candidate:

| row | top `entity_overlap_score` | verdict |
|---|---|---|
| `session-3185\|1626-09-21` | 54.05 | correct |
| `session-3187\|1628-11-04` | 30.67 | correct |
| `session-3188\|1629-02-17` | 54.93 | correct |
| `session-3188\|1629-06-12` | 107.08 | correct |
| `session-3187\|1628-10-01` | 0.00 | nihil actum, expected to be skipped |
| `session-3187\|1628-11-26` | 0.00 | nihil actum, expected to be skipped |
| `session-4562\|1629-05-12` | 0.00 | wrong -- likely missing HTR content |

6/7 correct (counting the two nihil actum rows as correctly-not-a-real-match,
per user confirmation these are parsing artifacts that should just be
skipped, not treated as scoring failures). The one wrong pick
(`session-4562|1629-05-12`) was investigated directly: the enriched text
names Crèvecoeur, but a literal regex search, a substring search, and a
rapidfuzz fuzzy search across all 368 flat resolutions in inventory 4562
found zero matches for any spelling variant -- the name is not registered
in the place/org/person overlap dictionary either. This is the resolution-level
analogue of the Step 1 structural coverage gap (HTR under-segmentation):
the correct content is very likely simply absent from this inventory's HTR
text, not a scorer defect. `resolutions_text`/`paragraph_texts` were checked
and are not the cause (near-identical lengths).

**Clean separator found**: every correct top candidate had
`entity_overlap_score` in `[30.7, 107.1]`; every problem case (both nihil
actum rows and the wrong one) had exactly `0.0`, with no borderline values.
Dense similarity alone did not separate the cases (`0.20-0.28` for correct
rows, but also `0.20` for the wrong one) -- entity overlap is the real
signal, confirming Track A/B's IDF-overlap approach elsewhere in the pipeline.

**Threshold added**: `score_candidates`/`score_ledger_row` in
`scripts/s4_candidate_scoring.py` now mark a candidate `low_confidence` when
`entity_overlap_score <= MIN_CONFIDENT_ENTITY_OVERLAP` (`0.0`). This does not
distinguish nihil actum from genuinely missing HTR content -- both get zero
overlap the same way -- but since this tool only ever produces a suggestion
for human review, that's acceptable: the reviewer sees the flag plus the
(usually short) candidate text and can tell which is which. Caveat: this
floor is derived from only 7 rows and should be re-checked once `?`/`-1`/`+1`
rows are scored.

## Step 3 — Extend candidate scoring to `?`/`-1`/`+1` rows (done, 17 Sep 2026)

Goal: wire the `A`/`X` scoring module from Step 2 to the three
nearby-candidate statuses without building new matching logic, per the
"extend this scoring to `?`/`-1`/`+1` rows using the same module" follow-up
named in Step 2's results.

### Ledger shape for these statuses

Confirmed against the live `session_date_status_1626_1630` ledger
(4,916 rows): `-1` (184 rows, unique previous-day candidate),
`+1` (181 rows, unique next-day candidate), `?` (238 rows, ambiguous --
`previous_day_session_ids` and/or `next_day_session_ids` together hold 2-4
candidates, median 2). Unlike `A`/`X`, a `?` row's candidates span *two*
ledger columns rather than one.

### Design

- `scripts/s4_candidate_scoring.py`: extended `STATUS_CANDIDATE_COLUMNS`
  with `"-1": "previous_day_session_ids"` and `"+1": "next_day_session_ids"`.
  Added `candidate_session_ids(row)`, which unions and deduplicates both
  nearby-day columns for `?` rows (sorted) and falls back to the existing
  single-column lookup for every other status; `score_ledger_row` now calls
  this helper instead of reading one column directly. `score_candidates`
  itself (the entity-overlap + dense-similarity core) is unchanged.
- `MIN_CONFIDENT_ENTITY_OVERLAP` (`0.0`) is applied as-is, not re-derived --
  per Step 2's caveat, it should be re-checked once these rows are actually
  eyeballed (see Verification below), not before.
- `notebooks/candidate_scoring_prototype.ipynb` updated to filter to all
  five statuses (`A`, `X`, `-1`, `+1`, `?`) and to use
  `candidate_session_ids(row)` instead of the old direct
  `STATUS_CANDIDATE_COLUMNS[row['status_code']]` lookup (which only handled
  one column and would have raised on `?` rows). Cell outputs were cleared,
  not re-run here -- 603 rows is far more than the 7-row `A`/`X` set and
  eyeballing all of them was intentionally left for a follow-up session
  (see `docs/steps` workflow: no heavy compute run by default).

### Verification

1. `uv run pytest tests/test_candidate_scoring.py` -- 12/12 passing,
   including tests for `candidate_session_ids` covering `-1`, `+1`,
   `?` (union + dedup across both columns), an unsupported status
   returning `[]`, and (added below) `is_nihil_actum` / the
   `score_ledger_row` nihil actum abstention.
2. Ran the notebook against the real 603 rows and eyeballed the output
   (17 Sep 2026). Two findings:

   - **Nihil actum days should abstain, not be scored.** A day's enriched
     text is sometimes the formulaic Latin entry `"Nihil Actum"` (optionally
     `"Nihil Actum: <reason>."`, e.g. a feast day) -- there was no sitting,
     so there is no real content to match. Confirmed corpus-wide: 162/1595
     enriched dates in `enriched_resolutions_1626_1630` are *purely* nihil
     actum text (no date mixes nihil actum with real content), covering
     146/610 (23.9%) of the `?`/`-1`/`+1`/`A`/`X` candidate rows, concentrated
     in `?` (80/238) and `+1` (49/181). Scoring these anyway produced a
     spurious top pick from real HTR content filed under that date in nearly
     every case -- the matched HTR session was itself flagged nihil actum
     only once across the sample. This sharpens Step 2's caveat ("does not
     distinguish nihil actum from missing HTR content, both score zero") into
     a real defect: zero entity overlap was not a reliable nihil-actum
     signal at this scale, since the HTR side is not itself empty. Fixed by
     adding `is_nihil_actum()` to `scripts/s4_candidate_scoring.py` (regex on
     the literal formula) and short-circuiting `score_ledger_row` to return
     `[]` before scoring when it matches -- consistent with the existing
     `REVIEW_ABSTENTION_REASONS["N"] == "nihil_actum"` vocabulary in
     `scripts/s4_resolution_baseline.py`/`s4_paragraph_axis_baseline.py`,
     though that vocabulary is populated from human-reviewed codes elsewhere,
     not text detection -- no prior text-based detector existed to reuse.
     Notebook sections 3-4 updated to report `NIHIL_ACTUM` explicitly instead
     of a bare "no candidates" or a misleading low-confidence top pick.
   - **Remaining (non-nihil-actum) rows are mostly missing HTR, as expected
     from Step 1's structural ceiling**: roughly 1 in 7 has a genuine HTR
     match, found and ranked correctly; the rest have no matching HTR content
     to find, consistent with Step 1's finding that ~half the ledger has no
     HTR session for its inventory within a wide date window. Not yet backed
     by a full stratified count per status (`?`/`-1`/`+1`) -- the current
     figure is from a first eyeball pass, not a systematic sample.
3. Re-ran the notebook with nihil actum rows abstaining automatically and
   eyeballed a stratified sample of the remaining `?`/`-1`/`+1` rows per
   status (17 Sep 2026): top picks with `entity_overlap_score` under 5 were
   consistently not good matches -- the `0.0` floor from the 7-row `A`/`X`
   set was too permissive at this larger scale. Raised
   `MIN_CONFIDENT_ENTITY_OVERLAP` from `0.0` to `5.0` in
   `scripts/s4_candidate_scoring.py` on this basis; `tests/test_candidate_scoring.py`
   updated to match (12/12 passing).

   Tallied the effect across all 610 `A`/`X`/`-1`/`+1`/`?` rows: 146 abstain
   as nihil actum, 464 produce a top pick. Of those 464, entity_overlap_score
   is exactly `0.0` for 460 and `> 5.0` for the remaining 4 -- **zero rows
   have a score strictly between 0 and 5**, so raising the floor to `5.0`
   reclassifies nothing on the current corpus; it only tightens the
   definition against future/different data. This confirms the gap the
   eyeball pass found is real and clean, not an artefact of a small sample
   straddling a fuzzy boundary.

4. **Window-widen follow-up, run against the live corpus (17 Sep 2026)**:
   `scripts/s4_candidate_scoring_batch.py` now also scores every `N`-status
   row recoverable within +/-7 days (`analyze_n_status_gaps.WIDE_WINDOW_OFFSETS`).
   523 of the 753 recoverable `N` rows fell in that band; 48 are nihil actum
   (correctly abstained, moving them out of `missing_htr`/`uncertain` into
   `nihil_actum`), and the remaining 475 scored a top pick with
   `entity_overlap_score` **exactly `0.0` for all 475** -- the same
   0-or-`>5` bimodality as the `A`/`X`/`-1`/`+1`/`?` set above (460/464
   there), just with a 0% confident rate here instead of ~0.9%. Verified
   this isn't a lookup bug: candidate session ids are present in
   `paragraph_axis_1626_1630` (480/480 checked), and the `volgnr`
   convention in the overlap workbooks already matches `enriched_id`
   format directly (`overlap_enriched_id`'s transform is a no-op for
   corpus-scale ids). Read as a genuine result: HTR content misfiled 2-7
   days from its enriched date essentially never shares a distinctive
   named entity with the correct resolution at this scale, i.e. the
   entity-overlap signal that works for +/-1-day candidates does not
   extend usefully to the wider band. Day-level effect: `resolved_auto`
   **unchanged** at 1,113 (no wide-window row cleared the confidence floor);
   `nihil_actum` 146 -> 194 (+48); `uncertain` 1,213 -> 1,165 (net -48,
   since the 48 newly-nihil rows leave `uncertain` while the other 475
   stay `uncertain`, now correctly tagged `resolution_source:
   "candidate_scoring_low_confidence"` instead of implying they were
   never scored). `missing_htr` unchanged at 2,444, as expected --
   window-widen only touches the recoverable subset. Fixed one real bug
   found while verifying this: `resolve_row`'s `N`-status fallback
   previously labelled every recoverable-but-unresolved row
   `ledger_n_status_recoverable_wider_window` regardless of whether it had
   actually been scored; now distinguishes `candidate_scoring_low_confidence`
   (scored, didn't clear the floor) from the original label (never scored,
   e.g. recoverable only past +/-7 days). Resolution-level concordance
   effect: `resolved_auto` unchanged at 13,528; `missing_htr` 5,481 -> 5,465
   and `nihil_actum` 124 -> 127, both explained by `select_day_status`
   picking a better-ranked (`nihil_actum` outranks `missing_htr`) candidate
   among a date's overlapping inventories now that more `N` rows resolve to
   `nihil_actum`; `cross_day_shift` is still 0, since no wide-window row
   produced a confident `resolved_auto`. **Conclusion**: the window-widen
   improves status-classification accuracy (fewer misleading
   `missing_htr`/generic-`uncertain` labels) but does not, on this corpus,
   unlock any new resolved HTR sessions -- the confidence floor is doing its
   job; there is no lower-hanging fruit at +/-2..+/-7 days without a
   different signal than entity overlap.

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

## Step 4 — Concordance implementation plan (A-F built and run 17 Sep 2026)

Pure assembly over artifacts that already exist (session-date ledger, S4f
human decisions, Step 2/3 candidate scoring, S4/S5 paragraph-axis
predictions). No new matching or alignment logic. Scope note up front:
paragraph-level attribution (which flat paragraph a specific enriched
resolution maps to *within* a confirmed HTR session) is the least mature
input -- the corpus-scale S4/S5 paragraph-axis run covers only 21 eligible
gold days with 0.238 coverage (16/21 abstain for insufficient entity
anchors) and F1 0.576 exact / 0.727 within-2-paragraphs on those it does
predict. Treating it as required for every row would make almost the whole
concordance `uncertain`. **v1 decision: paragraph attribution is a
best-effort enrichment column, not a status input.** Row status is decided
at day/session granularity (does a specific HTR session exist for this
enriched resolution's date, and is it confidently identified); the
paragraph-axis prediction is attached where available and left null
otherwise, without downgrading the row's status.

### A — Persist candidate scoring as a dataset (done, 17 Sep 2026)

`scripts/s4_candidate_scoring_batch.py` runs `score_ledger_row` over every
`A`/`X`/`-1`/`+1`/`?` row in `session_date_status_1626_1630` (same loading
machinery as the notebook and `s4_session_date_mapping_predictions.py`) and
writes one row per ledger key via `save_semi_structured`: `session_date_key`,
`inventory_id`, `enriched_date`, `status_code`, `candidate_session_ids`,
`nihil_actum`, `ranked_candidates` (full list, for audit),
`top_candidate_session_id`, `entity_overlap_score`, `dense_similarity_score`,
`combined_score`, `low_confidence`. `s4_candidate_scoring_predictions` is
registered in `data_manifest.toml` (parent: `session_date_status_1626_1630`)
and resolves via `uv run python -m data_io.check`. Run against the live
610-row batch:

```bash
uv run python -m scripts.s4_candidate_scoring_batch
```

Result: 4 rows (all ledger status `A`) clear `low_confidence=False`; 146
`nihil_actum`; the remaining 460 are `low_confidence=True`.

### B — Day-level status resolution (one row per ledger key) (done, 17 Sep 2026)

Join, per `(inventory_id, enriched_date)`:

1. `session_date_status_1626_1630` (base status code + candidate columns).
2. `s4_session_date_mapping_predictions_approved` / the merged
   `s4_session_date_mapping_decisions` output -- authoritative wherever a
   human has approved a nearby-day mapping via the S4f review UI; overrides
   the automatic pick below when present.
3. `s4_candidate_scoring_predictions` from Step A -- automatic pick for
   `A`/`X`/`-1`/`+1`/`?` rows lacking a human decision.

Resolve one `day_status` + optional `resolved_session_id` per row using this
precedence: human-approved mapping > confident automatic candidate
(`not low_confidence and not nihil_actum`) > `nihil_actum` flag > ledger `N`
with no recovered candidate (`missing_htr`, per Step 1's 76.4%-of-`N`
finding) > everything else (`uncertain`). `T`/`E` ledger rows (single
trusted/exact candidate already) pass through as `resolved_auto` directly,
no scoring needed. This day-level table is the one place cross-day
attribution lives, per the standing constraint below -- it must **not**
mutate the enriched-resolution row identity in Step C.

Built as `scripts/s4_day_status_resolution.py`, registered as
`s4_day_status_resolution` in `data_manifest.toml` (parent:
`session_date_status_1626_1630`). `s4_session_date_mapping_predictions_approved`
is read defensively (`Path.exists()` check, not `data_io.load`) since S4f
human review has not produced it yet -- `resolved_manual` is currently
always 0.

**Bug found and fixed same session**: the first version mapped every ledger
`N` row straight to `missing_htr` using only S4c's +/-1-day candidate
columns -- 3,197 rows, 65% of the ledger. But Step 1's own diagnostic
(`analyze_n_status_gaps.py`) had already shown 753 of those 3,197 (23.6%)
have a same-inventory HTR session at a wider +/-2..+/-14-day offset that no
downstream step had ever looked up; only 2,444 (49.7% of the ledger) are
actually structurally missing. The first version conflated "unscored" with
"missing," overstating the gap by 753 rows. Fixed by reusing
`analyze_n_status_gaps.py`'s `direct_sessions`/`nearest_recovery_offset`
helpers (`n_row_recovery_offsets`) to split `N` rows correctly: only rows
with no recovery at any offset become `missing_htr`; the
recoverable-but-unscored remainder falls to `uncertain` (no automatic
candidate was actually scored for them -- the window-widen itself, i.e.
running candidate scoring against the wider-offset session, is not yet
implemented). `resolve_row`'s `n_recovery_offsets` argument was made
required (no silent default) so this can't silently regress. Run against
the live 4,916-row ledger:

```bash
uv run python -m scripts.s4_day_status_resolution
```

Result: `resolved_auto=1,113` (1,012 `T` + 97 `E` + 4 confident `A`
candidates from Step A), `missing_htr=2,444` (exactly Step 1's headline
49.7%-of-ledger structural ceiling), `nihil_actum=146`, `uncertain=1,213`
(460 low-confidence-scored `A`/`X`/`-1`/`+1`/`?` rows + 753
recoverable-but-unscored `N` rows). These sum to 4,916 and reconcile exactly
against the ledger's status-code counts, Step A's `low_confidence`/`nihil_actum`
breakdown, and Step 1's own recovery count -- cross-tabulated directly, not
just totalled. 10/10 tests in `tests/test_day_status_resolution.py` passing.

### C — Expand to resolution granularity (built 17 Sep 2026, not yet run)

`enriched_resolutions_1626_1630`, ordered by `(date, resolution_index)`, is
the row-identity anchor -- one row per enriched resolution, 1626-01-01
resolution 1 through the last resolution of 1630. Left-join each resolution
to its day's Step B status/`resolved_session_id`. Where a day resolved to a
specific session, attempt a best-effort join against
`s4_corpus_paragraph_predictions` (or `s4_paragraph_axis_predictions` for
gold days) to attach a candidate flat-paragraph/resolution span; leave the
attribution columns null when absent (expected for most rows given current
paragraph-axis coverage) without touching `day_status`.

A resolution filed under day X whose real content the day-level join places
on X-1/X+1 keeps `enriched_date = X` for its identity but carries the
resolved day's session id and an explicit `cross_day_shift: true` flag --
never a rewritten date, per the standing modeling constraint from this
doc's "Long-term target" section above.

**Two wrinkles not covered above, hit during implementation
(`scripts/s4_resolution_concordance.py`):**

- **Multiple candidate inventories per date.** `enriched_resolutions_1626_1630`
  carries no `inventory_id`, and every enriched date turns out to match 2-3
  `s4_day_status_resolution` rows (one per overlapping `inventory_metadata`
  period, same mechanism Step B's ledger already has -- 1,594 of 1,594
  unique enriched dates have more than one candidate inventory). Resolved by
  ranking a date's candidate rows with `DAY_STATUS_RANK`, the same precedence
  order Step B already applies (`resolved_manual` > `resolved_auto` >
  `nihil_actum` > `missing_htr` > `uncertain`), taking the best-ranked row,
  and setting `inventory_ambiguous: true` when more than one candidate ties
  at that best rank (56 of 1,594 dates, 3.5%, in a check against the live
  `s4_day_status_resolution` output).
- **`s4_paragraph_axis_predictions` is a strict subset.** All 50 gold dates
  in `s4_paragraph_axis_predictions` are already present with identical
  records in `s4_corpus_paragraph_predictions` (1,594 dates), so only the
  corpus predictions are loaded; the gold dataset adds nothing this join
  needs.

Cut-point boundaries decode to a resolution's paragraph range as
`start = 0 if i == 0 else cuts[i-1]`, `end = cuts[i] if i < len(cuts) else
paragraph_count`, gated on the prediction's `k_e` matching the date's actual
enriched-resolution count (defensive -- skip attribution on any mismatch
rather than attach a misaligned range).

### D — Status vocabulary

Extend `REVIEW_ABSTENTION_REASONS` (`cross_day_shift`, `missing_htr`,
`nihil_actum`, `uncertain`) with `resolved_auto` and `resolved_manual` as
the two closed, non-abstaining states, so every concordance row has exactly
one status and no implicit gaps:

| final `status`     | source                                                            |
|---------------------|--------------------------------------------------------------------|
| `resolved_auto`    | ledger `T`/`E`, or confident automatic candidate (Step B rule 2)   |
| `resolved_manual`  | human-approved via S4f decisions (Step B rule 1)                  |
| `missing_htr`      | ledger `N` with no recovered candidate at any checked offset       |
| `nihil_actum`      | day's enriched text is the formulaic Latin entry (Step 3 detector) |
| `cross_day_shift`  | resolved session is on an adjacent day, not the filed date         |
| `uncertain`        | low-confidence/no-candidate scoring result, no human decision yet  |

### E — Output dataset (built 17 Sep 2026, not yet run)

`resolution_concordance_1626_1630` (frozen `parquet`, `save_parquet`).
Registered in `data_manifest.toml` (parent `s4_day_status_resolution`); its
provenance chain is `enriched_resolutions_1626_1630`,
`s4_day_status_resolution`, `resolutions_flat`,
`s4_corpus_paragraph_predictions` -- Step C reads Step B's already-joined
output directly rather than re-joining the ledger/approved-mappings/
candidate-scoring sources Step B already combined, per this doc's own C
description ("Left-join each resolution to its day's Step B
status/`resolved_session_id`"). One row per enriched resolution with a real
date (19,133 of 19,134 -- the single `NihilActum.xml` template row at
`resolution_index=0` has `date=None` and is skipped, not part of the
1626-1630 calendar), ordered by `(date, resolution_index)`; never a
synthetic placeholder row for `nihil_actum` days, per the standing
constraint. Run with:

```bash
uv run python -m scripts.s4_resolution_concordance
```

**Run 17 Sep 2026**: 19,133 rows written to
`resolution_concordance_1626_1630`. Status distribution: `resolved_auto`
13,528 (70.7%), `missing_htr` 5,481 (28.6%), `nihil_actum` 124 (0.6%). Zero
`uncertain` and zero `cross_day_shift` rows -- both explained below, not
bugs.

**Re-run 17 Sep 2026** (after `scripts/regenerate_enriched_resolutions.py`
removed the 13 `.bak`-sourced duplicate `enriched_id` rows from the upstream
JSON -- see PLAN.md): 19,120 rows written (19,133 - 13, confirming the row
count invariant tracks the corrected source exactly). Status distribution:
`resolved_auto` 13,528 (unchanged), `missing_htr` 5,465 (down 16),
`nihil_actum` 127 (up 3) -- sums reconcile (13,528 + 5,465 + 127 = 19,120).
These exact figures (5,465/127) also appear in PLAN.md's Step 3b writeup as
the predicted resolution-level effect of the window-widen change to
`s4_day_status_resolution`; see the Step F note below for the arithmetic
breakdown of how much of the 16/3 shift is dedup vs. reclassification --
not fully disentangled from the window-widen effect here. Two new
figures reported this run, not previously tracked here: 3,266 rows fall on a
date with an ambiguous best-ranked inventory (`inventory_ambiguous`), and
2,217 rows carry paragraph-axis attribution (`paragraph_start_index`/
`paragraph_end_index` populated).

### F — Verification (done 17 Sep 2026, no heavy compute)

Stratified spot-check by `status` (small sample, hand review):

- **Row-count/identity invariant**: 19,133 output rows == 19,133 dated
  source rows. But equal counts alone hid a real issue -- 13 duplicate
  `enriched_id` values (`1629-11-15_0` .. `_12`), traced to the *upstream*
  `enriched_resolutions_1626_1630_complete.json` containing both
  `162915nov.xml` and a stray `162915nov.xml.bak` as separate records for
  the same date/resolution_index. This is a pre-existing data-quality bug
  in the frozen source JSON, not introduced by this join -- both the source
  and the output carry the same 13 duplicates, which is why the plain count
  check passed. **Not fixed here** (regenerating that upstream JSON is out
  of scope for a verification-only step); flagged as a follow-up: exclude
  `.bak`-suffixed files when `enriched_resolutions_1626_1630_complete.json`
  is next rebuilt.
- **Coverage vs. the ~50% `missing_htr` ceiling**: resolution-level coverage
  (28.6% `missing_htr`) is notably better than Step 1's day-level
  49.7%-of-ledger ceiling. Explained, not a discrepancy: (a)
  `select_day_status` picks the best-ranked candidate among a date's 2-3
  overlapping-inventory `s4_day_status_resolution` rows, so a date resolves
  as soon as *any* overlapping inventory has a confident match; (b) the
  HTR-covered inventories (3185-3189) carry more resolutions per day than
  the largely-uncovered ones, so resolution-weighted coverage skews above
  the flat day-level ledger rate. Confirmed structurally: inventory 4861 is
  100% `missing_htr` (2,953/2,953 rows), inventory 4562 is 84.3% `missing_htr`
  (2,528/3,002), and inventories 3185-3189 are >97% `resolved_auto` --
  matches the project's known HTR coverage window.
- **Zero `uncertain` rows**: confirmed by direct check that no enriched date
  has *all* of its overlapping-inventory candidates at `uncertain` -- every
  date has at least one better-ranked candidate, so `uncertain` never
  survives `select_day_status`. Real structural consequence of the
  multi-inventory overlap, not a bug.
- **Zero `cross_day_shift` rows**: confirmed by checking `resolution_source`
  on all `resolved_auto` day-status rows -- 1,109 are `ledger_direct` (`T`/`E`,
  same-day by construction) and 4 are `candidate_scoring` (the Step A `A`/`X`
  picks, also same-date). No `-1`/`+1`/`?` row has yet produced a confident
  automatic candidate (the window-widen follow-up below), so there is
  currently no resolved row whose session could plausibly land on an
  adjacent day. Expected to activate once that follow-up is implemented.
- Hand-reviewed 3 sampled rows per status (`resolved_auto`, `missing_htr`,
  `nihil_actum`): all plausible (real Dutch resolution text with matching
  session ids for `resolved_auto`; `nihil_actum` rows literally read "Nihil
  Actum").

### Open questions for the next session

- **Decided 17 Sep 2026**: `resolved_manual` should stay the umbrella
  `day_status`/`status` value for *any* human-approved mapping, but a future
  resolution-level correction feedback loop must not be conflated with the
  existing S4f day-level decisions under the same `resolution_source`
  string. `s4_day_status_resolution.py`'s `resolve_row` already
  distinguishes sources this way (`ledger_direct` vs `s4f_human_decision`
  vs `candidate_scoring`, all folded under `resolved_auto`/`resolved_manual`
  `day_status` values) -- when a resolution-level correction dataset exists,
  it should get its own `resolution_source` value (e.g.
  `s4h_resolution_correction`) read in Step C/`s4_resolution_concordance.py`
  and given the same top precedence rank as `resolved_manual`, not a new
  `status`. No dataset or code exists yet for this; still out of scope until
  a concrete correction UI/workflow is built.
- **Decided 17 Sep 2026, confirmed by re-reading the code**: paragraph-axis
  coverage improving later only needs `scripts/s4_resolution_concordance.py`
  rerun, not the full pipeline. Verified `scripts/s4_day_status_resolution.py`
  (Step B) has zero references to paragraph data, and
  `s4_resolution_concordance.py` (Step C) reads `s4_corpus_paragraph_predictions`
  fresh via `load(PARAGRAPH_PREDICTIONS_DATASET)` on every run and re-derives
  `paragraph_start_index`/`paragraph_end_index` from it -- Step B's frozen
  `day_status`/`resolved_session_id` output is consumed as-is, never
  recomputed from paragraph data. So a better paragraph-axis model only
  requires `uv run python -m scripts.s4_resolution_concordance` afterward.
- **Redone 17 Sep 2026** against the corrected 19,120-row output. Stratified
  re-sample (3 rows per status, `random_state=42`): all plausible --
  `resolved_auto` rows carry real Dutch resolution text with a matching
  `session-*` id and `resolution_source="ledger_direct"`; `missing_htr` rows
  have `resolved_session_id=None` and `resolution_source="ledger_n_status_no_recovery"`;
  `nihil_actum` rows literally read "Nihil Actum" with
  `resolution_source="candidate_scoring"`.
- **The `1629-11-15` hypothesis above was checked directly and is wrong**:
  all 13 surviving `1629-11-15` rows are `missing_htr` (`resolution_source=
  "ledger_n_status_no_recovery"`, `resolved_session_id=None`) -- none became
  `nihil_actum`. The `-13 missing_htr` from dedup is fully explained by row
  *removal* (13 duplicate rows dropped outright, all `missing_htr`), not
  reclassification. The separate `-3 missing_htr` / `+3 nihil_actum` shift
  among *surviving* rows remains unexplained and is now a genuine open
  question: `nihil_actum` status is assigned per `session_date_key` by
  `s4_day_status_resolution` (unchanged input, not rerun between builds) and
  `select_day_status` is a deterministic sort with no dependency on the
  enriched-resolutions JSON that was deduplicated -- so nothing in the
  pipeline as documented should have moved these 3 rows. Not yet located;
  needs a real diff against a saved copy of the stale 19,133-row build (none
  was retained) or a rerun with row-level tracing to identify which 3 dates
  moved and why.

## Step 5 — Window-widen non-entity-signal follow-up (done, 17 Sep 2026)

PLAN.md's open follow-up: score the 523 wide-window `N` rows (Step 3b) with
something other than the axis-based entity overlap, since every one of them
scored `entity_overlap_score == 0.0` there.

**Dense TF-IDF similarity tested and rejected.** `score_candidates` already
computed `dense_similarity_score` for every wide-window row (Step 3b ran
before this session; no rescoring needed to check it). Spot-checking the
4 highest- and 4 lowest-scoring zero-entity-overlap rows found the signal is
not just unhelpful but **backwards**: the two lowest-scoring pairs checked
were genuine matches (`1628-05-23` enriched "ambassadeur Carlille" ↔
candidate text "De heer Carleton nomende sijn affscheijt"; `1627-01-01`
enriched "Van Languerack" ↔ candidate "de heer van Langerack"), while the two
highest-scoring pairs shared no real content, just generic resolution
boilerplate ("Is goetgevonden...", "versocht..."). Using dense similarity as
a confidence signal would rank wrong candidates above right ones -- not
attempted further.

**Root cause of the 0.0 entity overlap.** Both name variants above
(`Langerack`/`Languerak, van`, `Charleton`/`Carlisle`) are already in the
912-name IDF vocabulary -- the entities are known, just not detected for
these pairs. Two independent gaps compound:

1. The axis-based `overlap_lookup` (built from `place_overlap_1626_1630.xlsx`
   etc., see the "Entity Resolution Fix" section of PLAN.md) is a
   literal-substring match done once at Excel-build time, so it silently
   misses spelling variants -- `matched_entity_names`'s own docstring in
   `build_alignment_new.py` documents this as unfixed for the main pipeline.
2. Independently, `build_alignment_new.py` never runs *any* text match for
   `persons` at all -- `resolve_enriched_entities`'s `persons_canonical` and
   `persons_surface` fields are computed but never passed to
   `matched_entity_names` anywhere in the file (only `places` and `orgs`
   are). Both spot-checked genuine matches above were person names, which is
   consistent with, not incidental to, this gap.

**Fix implemented**: `scripts/s4_candidate_scoring.py` gained
`text_confirmed_names(names, text)` -- the same exact-substring-then-
`rapidfuzz.fuzz.partial_ratio`-fallback method and threshold (85) as
`build_entity_surface_matches.py`'s `confirm_candidates`, applied directly to
a caller-supplied name list rather than an annotation-derived shortlist.
`score_ledger_row` gained an `enriched_entity_names` parameter that, when
given, replaces the axis-based `shared_entities` lookup with a direct
`text_confirmed_names` check against each candidate's text.
`scripts/s4_candidate_scoring_batch.py`'s `load_lookups` now also resolves
each enriched date's real place/person/org names via the already-fixed
`resolve_enriched_entities` (with `persons_info`/`institution_names`, so
persons get their best canonical form, not just `PER-entities.json`'s raw
name) and passes that list for the wide-window scoring path only -- the
`A`/`X`/`-1`/`+1`/`?` path is unchanged. 4 new tests in
`tests/test_candidate_scoring.py` (18/18 passing); full suite 210
passed/10 skipped.

**Real-corpus result** (`uv run python -m scripts.s4_candidate_scoring_batch`,
~44s): of the same 475 zero-axis-entity-overlap wide-window rows, **125
(26.3%) now clear the `MIN_CONFIDENT_ENTITY_OVERLAP` floor** via
text-confirmed names (was 0). Score-distribution spot-check across bins
`[5,10)` through `[60,200)` (18 rows) found shared-entity sets dominated by
distinctive place/person names (e.g. `Amboina`, `Glückstadt`, `Otten, Jan`,
`Jorck, ?`) in every bin, not just generic terms -- consistent with real
matches. **Caveat, not fixed**: exactly 3 of the 125 (`1626-01-27_offset-6`,
`1627-01-14_offset-3`, `1628-12-20_offset-5`, all in `session-4562`) have
*only* generic province/country names as shared evidence (`Holland`+
`Engeland`, `Overijssel` alone, `Engeland`+`Utrecht`) -- low-IDF-weight terms
that appear in nearly every Staten-Generaal resolution regardless of
content, so these 3 are likely false positives inherited from the same
"IDF discounts but doesn't zero out ubiquitous terms" property already
present in the un-modified `score_candidates` scoring formula. Left as a
documented residual (2.4% of the newly-confident set) rather than adding a
stoplist, since the general `score_candidates` function is shared with the
already-calibrated `A`/`X`/`-1`/`+1`/`?` path and a fix there needs
validation against that path's existing baseline, not just this one.

**Downstream re-run** (Steps B/C, same scripts as before, no logic changes
needed -- the wide-window confident candidates flow through the existing
precedence): `s4_day_status_resolution`: `resolved_auto` 1,113 → 1,238 (+125,
exactly the new confident count), `uncertain` 1,213 → 1,040, `missing_htr`
unchanged at 2,444 (structural ceiling, correctly untouched), `nihil_actum`
unchanged at 194. `s4_resolution_concordance`: **`cross_day_shift` moved
from 0 to 1,380** -- the first time this status has ever been populated,
since no row had produced a confident cross-day candidate before this
session. `missing_htr` 5,465 → 4,259 and `resolved_auto` 13,528 → 13,354 (a
day's status change cascades to all its resolutions, and some previously
same-day `resolved_auto` picks were outranked by a higher-scoring wide-window
candidate under the existing ambiguous-inventory precedence, correctly
producing `cross_day_shift` for those too, not just former `missing_htr`
days). Spot-checked 3 `cross_day_shift` rows against their `shared_entities`
in `s4_candidate_scoring_predictions`: 2 of 3 have multiple distinctive
names (`Amboina`/`Bergen op Zoom`/`Rees`/... at 54.9; `Brussel`/`Emden`/
`Rotterdam`/`Schelde` at 22.75), 1 is the `Overijssel`-only false positive
already flagged above.

**Open question for the next session**: whether the 3-row (125-row / 2.4%)
generic-name false-positive residual is worth a targeted fix (e.g. excluding
a short list of near-universal province/country names from counting toward
`MIN_CONFIDENT_ENTITY_OVERLAP` specifically for the text-confirmed path) once
it can be validated against the original 610-row baseline without
regressing it, or is small enough to leave as a documented limitation.

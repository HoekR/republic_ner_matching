# republic_ner_matching — implementation plan
<!-- doc-status: active -->
<!-- canonical-goal -->

> **Separate the resolutions.** For most of the ~19,120 enriched resolutions (1626-1630 editorial
> summaries), determine where that resolution begins and ends in the HTR transcription, expressed
> in session-relative archival terms — a verified archival address, not a possibly-drifted session
> number. Publish it as a reviewable table where every placement carries a confidence tier and its
> evidence, and where the *unplaced* parts are characterised rather than merely absent.
>
> Framing: patchy alignment, after ancient DNA. Damaged, fragmented aDNA matched against a known
> reference yields patchy alignment — that is the expected shape of a good result, not a failure.
> A confidently placed resolution is an aligned read; several resolutions sharing one paragraph is
> a multi-mapping read (filter, don't count as progress); an unplaced resolution is an uncovered
> region, and uncovered regions are informative — they must be classified, not merely omitted.
>
> **Acceptance criteria** (`docs/DECISIONS.md`, 2026-09-22 "Backfill acceptance-criteria
> decision"): a resolution is **separated** iff its start paragraph is shared with no other
> resolution on its date and its extent is ≤ 3 paragraphs. The paragraph-level ceiling is
> **11,644 / 19,120 = 60.9%** (pigeonhole: a day with *n* paragraphs can separate at most *n*
> resolutions; 535 days have no HTR at all), not physics — part of it is recoverable by
> correcting date/session drift rather than better segmentation. Targets are stated against that
> ceiling, never against a notional 100%. Full metric-tier breakdown (which channel each
> diagnostic feeds, and what's proposed but not yet computed): `docs/METRICS.md`.
>
> | | criterion | baseline (2026-09-23) |
> |---|---|---|
> | Global, primary | ≥ 50% of ceiling separated (≥ 5,822) | **MET** — 8,015 = 68.8% of ceiling (41.9% of all 19,120; 53.9% of 14,861 HTR-reachable) |
> | Global, stretch | ≥ 75% of ceiling (≥ 8,733) | not met — gap 718 resolutions |
> | Global, spans | ≥ 6 qualifying spans totalling ≥ 180 days | not met — gap=2: 4 spans / 177 days (closest); gap=1: 1 span / 43 days; gap=0: 0 spans (longest 12/43/60 calendar days) |
> | Local | any inventory-year reaching ≥ 50% of its own ceiling is banked as done and used as the worked example to extend from | — |
>
> **2026-09-23 jump (1,961 → 8,015) was a data-hygiene fix, not new modeling.**
> `resolution_concordance_1626_1630` — the dataset every separation metric reads — was frozen
> 2026-09-17, three `s4_corpus_paragraph_predictions` rebuilds behind (S6c's DP eliminating 777
> `insufficient_entity_anchors` abstentions, the concordance-fallback wiring, and the
> `axis_for_date` fix, all 2026-09-21/23). Re-running the "pure assembly" concordance script
> (26s, no new alignment logic) against current predictions is what moved the number. See
> `docs/DECISIONS.md` 2026-09-23 "`resolution_concordance_1626_1630` was stale, gating the entire
> Tier O separation baseline".
>
> A **span** is a run of consecutive solid session-days (≥ 50% of that day's resolutions separated)
> tolerating ≤ 1 non-solid day; it qualifies at ≥ 30 calendar days. Report spans at gap ∈ {0,1,2}
> always — the tolerance parameter dominates the result. Report separation as a share of all 19,120,
> of the 13,530 HTR-reachable, and of the 11,644 ceiling, every time — never a single number that a
> favorable denominator could flatter.
>
> This supersedes the original GysBERT NER fine-tuning goal (see "Overview"/"Phases" below,
> retired): that track would train on spans from the same ~50-55%-recall tagger its own training
> data comes from and so cannot close its own recall gap (session note, 2026-09-18), and its output
> is unrelated to this goal's segmentation-transfer work (`docs/DECISIONS.md`, 2026-09-21). Also
> supersedes "session attribution" (77.1%) and "paragraph attribution" (11.6%) as headline numbers,
> both measured this session and rejected: session attribution restates which calendar day a
> resolution falls on (all 1,138 dated sessions assign every resolution on a date the *same* session
> id — 14,734 row-level "attributions" encode only 1,053 distinct sessions), and paragraph
> attribution counts a resolution claiming a 99-paragraph span as a hit.
>
> Every other document's goal-bearing text should point here rather than restate it — see
> `docs/APPROACH_OVERVIEW.md` and `README.md`. Every document and top-level section here carries a
> `<!-- doc-status: active|future|sidelined|retired -->` marker; `uv run python scripts/svz.py doctor`
> checks that no non-active section asserts a conflicting goal and that this marker is unique.

**Multiple tracks below compete for the same session budget.** Before picking one up, run
`uv run python scripts/svz.py review` (or read [docs/STATE.md](docs/STATE.md)) and follow
[docs/ITERATION_POLICY.md](docs/ITERATION_POLICY.md) to decide what to continue, switch to, or
close out. Durable stop/continue decisions are logged in [docs/DECISIONS.md](docs/DECISIONS.md).

---

## Workspace Standard Alignment & Organization (Completed)
<!-- doc-status: active -->

Aligned with `dighum_template` guidelines via sync tool:

- **Portable Wisdom**: Installed 13 portable topic guides in [docs/wisdom/](docs/wisdom/).
- **Editor Standards**: Synchronized [.github/copilot-instructions.md](.github/copilot-instructions.md) and `.cursor/rules/project-standards.mdc`.
- **Data I/O Package**: Synchronized [data_io/](data_io/) with upstream `dighum_template`.
- **MCP Add-ons**: Applied `data-io-mcp` and `workflow-mcp` (recorded in [docs/addons/APPLIED.md](docs/addons/APPLIED.md)).
- **Notebook Reorganization**: Consolidated all Jupyter notebooks into [notebooks/](notebooks/).
- **Artifact Cleanup**: Cleaned `template/dh_project/` and temporary zip files; ignored `data.bak/` and credentials in [.gitignore](.gitignore).

---

## CURRENT Approach: Segmentation transfer (29 Aug 2026)
<!-- doc-status: active -->

> **Canonical document: [docs/SEGMENTATION_TRANSFER.md](docs/SEGMENTATION_TRANSFER.md).**
> This reframes the alignment problem and supersedes the entity-discrimination framing of tier-3
> below. The sections after it remain valid as the record of what was built.

### Session-Date Ledger Steps

| Step         | Guide                                                                                | Done when                                                         | Status |
| ------------ | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------- | ------ |
| **4a** | [STEP4a_session_date_inputs.md](docs/steps/STEP4a_session_date_inputs.md)             | Define the inventory-aware session-date key and register outputs. | [x]    |
| **4b** | [STEP4b_session_date_ledger.md](docs/steps/STEP4b_session_date_ledger.md)             | Build the date-indexed known/unknown session ledger.              | [x]    |
| **4c** | [STEP4c_nearby_session_candidates.md](docs/steps/STEP4c_nearby_session_candidates.md) | Add auditable`+/-1` day candidates without auto-assignment.     | [x]    |
| **4d** | [STEP4d_session_status_heatmap.md](docs/steps/STEP4d_session_status_heatmap.md)       | Render per-inventory-year calendar heatmaps.                      | [x]    |
| **4e** | [STEP4e_session_key_consumers.md](docs/steps/STEP4e_session_key_consumers.md)         | Produce review exports and a separate mapping-aware S4 consumer.  | [x]    |

**Hypothesis.** The enriched edition is normative — resolution count and order per sitting are
hand-edited and checked — so `K_e` is ground truth for how many resolutions a sitting contains. The
HTR side disagrees (sample day `session-3186` / 1627-09-02: 5 enriched, 3 flat, 6 paragraphs). The
aligner is being asked to map 5 onto 3, so a large share of the 52% FP rate is not a scoring failure:
**the correct answer is not in the candidate set.** Corroborating: `nw_matches_gt_rate` is 0.957 for
correct pairs and 0.962 for false positives — identical, which is what structural unavailability
predicts.

**Reframe.** Not matching but **count-constrained segmentation transfer**: given `K_e` and an ordered
stream of HTR units, place the `K_e − 1` cut points. Implemented by aligning **entity sequences**
(not resolutions) with Needleman–Wunsch; enriched resolution boundaries project through the alignment
onto HTR positions, then snap to the nearest opening formula / `para_start`.

**Sequence:**

- [X] **S0** — evaluation harness: boundary P/R/F1 at tolerance `t`, WindowDiff/P_k, exact-count
  satisfaction. Demote pair-level precision to a continuity metric. *Blocking.*
- [X] **S1** — four zero-annotation diagnostics (parallel):

  - [X] **D1** `K_e` / `K_f` / `K_p` and entity-set containment per session-day → segmentation-vs-evidence 2×2
  - [X] **D1c** Kendall τ on entity order in trusted tier-1 pairs → transposition band width
  - [X] **D2** existing LLM judge accuracy vs the 50 labelled pairs → signal or noise?
  - [X] **D2b** opening/closing formula hit rate at anchored tier-1 resolution starts

  Verified findings from the run:

  - 81.1% of session-days are HTR under-segmented (`K_f < K_e`), and only 3.8% hit exact counts.
  - Mean entity containment is 0.295; 68.1% of days fall in the `[K_f < K_e, Low Containment]` bucket, i.e. pure segmentation failure rather than combined NER collapse.
  - Tier-1 Kendall τ is 0.638 with 64.3% of pairs at τ ≥ 0.8, supporting a 2–3 token/entity transposition band.
  - LLM judge precision is 60.0% against a 53.7% baseline and therefore near-noise for this task.
  - Opening formula hit rate is 80.1%; the remaining ~19.9% miss expected formulaic openings, confirming need for S2 anchor harvesting.
- [X] **S2** — harvested openings/closings from the ~5,725 anchors → 1626–1630 phrase inventory *(D2b)*

  - Output: [output/s2_anchor_phrase_inventory.json](output/s2_anchor_phrase_inventory.json)
- [X] **S3 (tooling)** — [build_boundary_gold_sample.py](build_boundary_gold_sample.py) draws a stratified
  ~50-day sample by `|K_e − K_f|` and writes an annotation scaffold to
  [output/boundary_gold_sample.json](output/boundary_gold_sample.json).
  Upstream `res_start` (245 records, 42 inventories) has **zero overlap** with target
  inventories 3186–3189 — no records to merge; boundary annotation for this window must be
  created from scratch.
- [X] **S3 (annotation)** — hand-labeled `boundaries` for the 50 sampled session-days using
  [build_boundary_annotation_ui.py](build_boundary_annotation_ui.py) → open
  `output/boundary_annotation_ui.html`, type the `|||CUT|||` marker inline into the flat-text
  editor at each of the `K_e - 1` resolution boundaries per day (anywhere, including
  mid-paragraph). Sessions don't always split cleanly at the day boundary, so also: type
  `|||END|||` where the last resolution truly ends if it's before the end of the visible text
  (trailing spillover into another session), and tick the "not the start of a new resolution"
  checkbox if the first fragment continues a resolution from a previous day. Export, then run
  [merge_boundary_annotations.py](merge_boundary_annotations.py) to fold results into
  `output/boundary_gold_sample.json`. Review classified the exception days as segmentable (S),
  cross-day shift (C), or missing HTR material (M); regenerated review currently has 32
  exceptions after annotation correction. *(D1)*
- [ ] **S4** — assemble: entity-sequence NW → cut points → snap → exact-count interpolation between
  anchors → abstain below threshold. The first flat-resolution-axis entity-NW baseline ran on all
  50 gold days and abstained on all of them (22 missing HTR, 14 insufficient resolution
  granularity, 7 insufficient entity anchors, 7 cross-day shifts). A complete annotated-stream
  paragraph axis now contains 611 paragraphs: 480 have uniquely resolved entity annotations and
  131 do not; 87 annotation references remain explicitly unresolved. Entity-NW with monotone
  interpolation with place, organisation, and person overlap predicts 5 / 21 eligible days
  (16 anchor abstentions); exact paragraph-index micro F1 is 0.576 and F1 within 2 paragraphs
  is 0.727. At 360 manual gold cuts, the existing opening regex hits 63.1% and S2's top-20
  phrases hit 62.5%; recurring uncovered starts include `oederom gedelibereert synde`,
  `deses opte missive`, `is ter vergaderinge`, and `in deliberatie geleyt`. Derive an expanded
  phrase inventory from these gold-conditioned observations before character-level snapping.
  `fuzzy_search` spelling-variant matching at 0.85 similarity adds no hits beyond the 62.5%
  exact top-20 baseline, so missing phrase families rather than orthographic variation are the
  immediate coverage gap. A held-out tier-1 inventory (excluding all 50 gold dates) now has
  271 recurring candidates from 3,817 unique flat records, independently confirming `opde requeste`, `is ter vergaderinge`, and `in deliberatie geleyt`; integrate these as positional
  priors in the next S4 iteration.
  *(S1, S2)*

  **Session 2026-09-18.** Correction to the note above: the 271-candidate held-out
  inventory was already wired into `s4_paragraph_axis_baseline.py`'s phrase-snapping
  step at the same commit that produced the "5/21 eligible days" result -- the
  "integrate as positional priors" framing was chronologically backwards (the cut-rate
  diagnostics in `s4_opening_phrase_cut_evaluation[_full].jsonl` ran *after* the
  baseline, measuring hit rate directly at true gold cuts, never through the actual
  interpolate-snap-revert pipeline; see docs/SEGMENTATION_TRANSFER.md section 4.1 for the
  general lesson this forced). Root-caused all 16 `insufficient_entity_anchors`
  abstentions: **12/16 (75%) are structural** -- the paragraph axis has fewer
  paragraphs than `K_e` requires, either globally (`axis_count < k_e`) or locally
  between two entity anchors (`gap_violation`) -- confirming
  docs/SEGMENTATION_TRANSFER.md section 9's predicted line-level fallback trigger; **2/16
  were a code bug** (`interpolate_positions` required >=1 entity anchor even for
  `k_e == 1` days that need zero cut points); **2/16 were a data gap**
  (`boundary_gold_paragraph_axis` has no records for those 2 gold dates at all).
  Separately traced why phrase-snapping only reached 1 of the 5 predicted days
  (6/32 boundaries snapped): `predict_day`'s revert was **all-or-nothing per day**
  -- any single collision (two interpolated positions snapping to the same nearby
  paragraph, e.g. `1627-12-07` raw `[1,2,3,4,5,6]` -> snapped `[1,2,3,4,4,4]`)
  discarded every snap for that day, including the valid ones; widening the snap
  radius/threshold was tested and made no difference (every raw position already
  finds a phrase hit within radius 2).

  Fixed both in `scripts/s4_paragraph_axis_baseline.py`: `interpolate_positions`
  now short-circuits to `[]` for `k_e <= 1` (no anchors needed when no cuts are
  needed), and a new `snap_boundaries` replaces the all-or-nothing revert with a
  per-boundary, order-preserving greedy assignment (4 new tests in
  `tests/test_s4_paragraph_axis_baseline.py`, 9/9 passing). Re-run: predicted days
  5->9/21 (coverage 0.238->0.429) and phrase-snapped boundaries 6/32->26/32.
  **Caveat -- read the coverage gain correctly:** all 4 newly-predicted days are
  `k_e == 1` trivial zero-boundary days (2 of them have zero paragraph-axis records
  at all), so they add no real segmentation signal, only correctly avoid a spurious
  abstention. On the 5 original multi-boundary days, boundary-level F1 is
  **unchanged** (micro F1 0.576 exact / 0.727 within-2 tolerance, matching the
  pre-fix run to 3 decimal places) despite most boundaries switching from raw
  interpolation to phrase-snapped positions -- flagged as an open question, not yet
  explained (needs a per-boundary gold-vs-predicted comparison, not attempted this
  session). Neither the 12 structural `K_p < K_e` abstentions nor the 2
  missing-axis-record dates were addressed; both are candidates for the next S4
  session (line-level cut points per S9, and a `boundary_gold_paragraph_axis`
  data-completeness check, respectively). Full session narrative:
  [docs/S4_ITERATION_REVIEW.md](docs/S4_ITERATION_REVIEW.md).

  **Session 2026-09-18 (continued).** Explained the flagged open question above
  by decomposing TP/FP/FN per boundary on the 5 multi-boundary predicted days
  (reused existing `s4_paragraph_axis_predictions.jsonl` +
  `boundary_gold_paragraph_axis`, no rerun needed): gold's own `boundaries`
  annotations repeat the identical `paragraph_stream_index` for multiple
  distinct cut points whenever the paragraph axis is coarser than `K_e` --
  e.g. `1626-02-28` has 6 boundary slots but only 1 distinct axis position
  (`axis_count=8` for `k_e=7`). 16/17 eligible gold days with any boundary
  have at least one such collision; 41/179 boundary slots (22.9%)
  corpus-wide share a position with another slot the same day.
  `compute_boundary_prf` can award at most one hyp match per distinct ref
  value, and predicted positions are always strictly increasing (never
  repeat), so duplicate-valued gold slots impose a hard recall ceiling
  independent of predictor quality: max reachable TP = count of distinct ref
  values, not `len(ref)`. On the 5-day subset this ceiling is 24 distinct
  values out of 34 ref slots; tol0 TP (19) already reaches 79% of it and
  tol2 TP (24) reaches **exactly 100%** -- the snap-collision fix improved
  individual boundary position accuracy, but the metric was already
  saturated against the axis-granularity ceiling both before and after,
  which is why F1 didn't move. Recorded as a structural-ceiling decision in
  `docs/DECISIONS.md` (2026-09-18): `boundary_f1_tolerance0`/`tolerance2`
  are closed to further interpolation/snapping work; any further F1 gain
  needs finer-than-paragraph granularity, i.e. the already-scoped but
  `blocked` line-level-segmentation track. S4's other metrics (predicted-day
  coverage, corpus baseline coverage) are unaffected and remain open.

  **Session 2026-09-18 (entity-density diagnostic).** Explored a way around
  the paragraph-granularity ceiling above that doesn't depend on the blocked
  line-level track: does a paragraph's entity density (LOC+PER+ORG mention
  count) signal that it bundles multiple resolutions? Two prerequisite
  concerns were checked first and resolved: (1) entity offsets are not as
  unreliable as repo lore claimed -- the "~50% wrong" figure traces to no
  actual measurement; reproducing it gives ~18-22% character-level noise,
  always within the correct paragraph, largely a fixable reference-frame bug,
  and irrelevant here since the count used doesn't touch offsets. (2)
  `LOC-/PER-/ORG-annotations.json` come from an upstream GysBERT/Flair tagger
  with ~50-55% corpus-wide recall (never measured for 1626-1630
  specifically); this project's planned GysBERT fine-tuning would train on
  spans from that same layer and so cannot close its recall gap -- a
  dictionary/fuzzy surface-form lookup against known reference lists,
  scoped to flagged paragraphs, is the viable route instead (deferred, see
  below).

  Built `scripts/s4_entity_density_split_diagnostic.py` (+
  `tests/test_s4_entity_density_split_diagnostic.py`, 7/7 passing) to test the
  hypothesis directly against gold: paragraphs gold marks as "bundled" (2+
  boundary slots collapse onto one `paragraph_stream_index`, excluding gold's
  `out_of_range` fallback marker, which reflects missing HTR content, not
  entity density) vs. paragraphs gold marks as a single clean resolution
  boundary. Real-corpus result (16 eligible gold days, registered as
  `s4_entity_density_split_diagnostic`, parent `boundary_gold_paragraph_axis`):
  **bundled paragraphs (n=22) have median entity_annotation_count 4 vs. 1 for
  clean paragraphs (n=112); common-language effect size 0.77** (a random
  bundled paragraph beats a random clean paragraph's count 77% of the time),
  77% of bundled paragraphs at/above the clean group's 75th percentile.
  Recorded via `svz.py metric S4 entity_density_bundled_clean_effect_size
  0.770`. Verdict: the signal separates well enough to be worth pursuing
  further.

  **Next candidates (not started):** (1) fuzzy-surface-form-lookup
  augmentation of entity counts, scoped to paragraphs this diagnostic flags,
  against `LOC-entities.json`/`PER-entities.json`/`delegates_reference.parquet`/
  `abbrd_minimal.parquet` -- to recover entities the upstream tagger missed
  (avoids the previously-benchmarked `FuzzyTokenSearcher` full-dictionary
  scaling wall by staying scoped, not corpus-wide); (2) actual split-point
  placement within a flagged bundled paragraph, using freshly `.find()`-computed
  in-text character positions (not the stored annotation `offset` field) to
  locate entities and infer where to cut -- 2/22 bundled paragraphs have zero
  entities and would need a different signal or fall back to abstention.

  **Session 2026-09-18 (split-point POC).** Built
  [scripts/s4_bundled_split_poc.py](scripts/s4_bundled_split_poc.py) (+
  `tests/test_s4_bundled_split_poc.py`, 14/14 passing) to test candidate (2)
  directly, using candidate (1) as the lever to measure its own marginal
  value on the same batch, per this session's plan. Gold `mid_paragraph`
  boundary annotations carry an exact in-text `char_offset` -- all 22 bundled
  positions have real character-level ground truth (27 interior cuts total),
  not just paragraph-index-only labels. Method: locate entity spans via
  freshly `.find()`-computed positions (whitespace-flexible fallback), split
  them into `k+1` contiguous groups, predict a cut at each group gap's
  midpoint; abstain if fewer than `k+1` spans are found.

  Real-corpus result (registered as `S4`
  `bundled_split_poc_stage{1,2}_recall_tol{50,150}`): stage 1 (existing
  LOC-/ORG-/PER-annotations only) attempts 17/22 positions, recovers **0/27
  (0%) at tol=50 chars** and **9/27 (33.3%) at tol=150 chars**. Stage 2 (stage
  1 spans plus a scoped dictionary lookup against
  `entity_surface_matches_1626_1630` canonical LOC/PER names, restricted to
  these flagged paragraphs) attempts 18/22, recovers **3/27 (11.1%) at
  tol=50** and **11/27 (40.7%) at tol=150**.

  **Reading the result:** the even-split-of-entity-spans heuristic itself is
  the dominant limitation, not entity recall -- it is essentially unusable at
  a tight tolerance (0% at 50 chars) and only moderately useful at a loose
  one (33%). Dictionary augmentation gives a real but modest lift (+1
  abstention resolved, +2 hits at tol150, +3 at tol50), consistent with the
  entity-density diagnostic's hypothesis, but confirms it is not sufficient
  on its own to make split-point placement viable -- the placement heuristic
  needs a smarter signal than "midpoint of the gap between evenly-sized
  entity groups" (e.g. phrase-boundary snapping near the predicted gap,
  similar to S4's existing opening-phrase snap step, or per-entity role/type
  weighting) before this is worth wiring into the main baseline. Not yet
  attempted this session; next candidate action if this track continues.

  **Session 2026-09-18 (phrase-boundary snap).** Attempted the phrase-snap
  candidate above: added `phrase_offsets`/`snap_cut_to_phrase`/
  `snap_predicted_cuts` to `scripts/s4_bundled_split_poc.py`, reusing the same
  `s4_opening_phrase_candidates` inventory and per-cut order-preserving snap
  logic as `s4_paragraph_axis_baseline.snap_boundaries`, applied to raw char
  offsets instead of paragraph indices (4 new tests, 18/18 passing). Snaps
  each stage's midpoint cut to the nearest opening-phrase match within 150
  chars, independently per cut, falling back to the raw midpoint on collision
  or when no phrase is nearby.

  Real-corpus result (registered as `S4`
  `bundled_split_poc_stage{1,2}_phrase_snapped_recall_tol{50,150}`), same
  17/22 and 18/22 attempted (snapping doesn't change abstentions): stage 1
  moves **0/27 -> 2/27 (7.4%) at tol=50** and is unchanged at **9/27 (33.3%)
  at tol=150**; stage 2 moves **3/27 -> 4/27 (14.8%) at tol=50** and is
  unchanged at **11/27 (40.7%) at tol=150**. Reading the result: snapping
  gives a small but real lift at the tight tolerance in both stages (the
  cuts it moves were already within 150 chars of gold and land closer, not
  pulled in from outside that window) but zero lift at the loose tolerance
  -- it sharpens already-close cuts rather than rescuing wrong ones. Confirms
  the even-split heuristic itself, not phrase availability, remains the
  dominant limitation; per-entity role/type weighting (the other candidate
  named alongside phrase-snapping) is the next thing to try if this track
  continues, otherwise S4 split-point placement is likely near its ceiling
  without the blocked line-level track.

  **Session 2026-09-18 (open-items closeout).** Worked the two remaining open
  items from [docs/S4_ITERATION_REVIEW.md](docs/S4_ITERATION_REVIEW.md), both
  resolved with data already on disk (no rerun, no heavy compute):
  (1) the 2 `boundary_gold_paragraph_axis` missing-record dates (1626-05-17,
  1627-04-11) are not a pipeline bug -- `boundary_gold_sample.json` shows both
  are `k_e=1, k_f=0, flat_ids=[]`, i.e. the same `missing_htr` structural
  ceiling already closed for `resolution_concordance_1626_1630`, surfacing
  here as an empty paragraph axis instead; both are trivial zero-boundary
  days so no segmentation signal is lost. (2) Re-checked the line-level-
  segmentation blocker's stated next action ("map marijn-variant page_ids to
  dates, a cheap join") and found it isn't cheap: no dataset in
  `data_manifest.toml` maps (inventory, scan/page) to date --
  `session_index_all.parquet` and `session_date_status_1626_1630` are both
  session-level only -- so the join needs a new extraction step over the
  unextracted 10 GB `sessions_json-2026-02-27.tar.gz`. Corrected the "cheap"
  claim in `docs/SEGMENTATION_TRANSFER.md` §9 and the task note in
  `docs/state.json`; track stays `blocked`, now on a properly-scoped
  extraction step rather than a quick lookup. Both findings recorded in
  `docs/DECISIONS.md` (2026-09-18). With these closed, S4 has no more cheap
  already-scoped diagnostic work on hand -- next session should either scope
  the sessions_json page-range extraction as its own step, or switch tracks
  per `svz.py review`.

  **Session 2026-09-19 (batch candidates: corrected fuzzy-scaling claim +
  LLM split POC).** User asked for weekend-scale batch work. First corrected
  a wrong recommendation (GysBERT fine-tuning) using an already-documented
  finding a few lines above: `LOC-/PER-/ORG-annotations.json` come from the
  same noisy upstream tagger fine-tuning would train on, so it can't close
  its own recall gap (docs/DECISIONS.md 2026-09-18 already said this).
  Re-benchmarked the "`FuzzyTokenSearcher` full-dictionary scaling wall"
  claim (`build_entity_surface_matches.py` docstring, >4.5min/3.7GB without
  finishing on the full ~10,876-name dict): that number was measured at the
  default `index_vocabulary_pairs=True`. With it set `False`, full LOC
  (2,459 names) drops from 60s/3.7GB to 12s/1.2GB, full PER (8,076 names)
  completes in 185s/6.3GB (though a later end-to-end run saw PER indexing
  take 1,015s under system load -- real variance, not a fixed number). Also
  found the default `levenshtein_threshold=0.6` produces mostly garbage
  (common words like "ende"/"heeren" matching short place/person names at
  0.6-0.8 similarity); raised to 0.85 + a 4-char minimum match length
  (matching this codebase's existing `FuzzyPhraseSearcher` convention). Built
  [scripts/s4_fuzzy_surface_form_scan.py](scripts/s4_fuzzy_surface_form_scan.py)
  (+ 6/6 tests) -- full-dictionary LOC/PER/ORG scan over every 1626-1630
  paragraph (not just annotation-linked candidates, unlike
  `entity_surface_matches_1626_1630`), flagging `already_known` vs
  `newly_recovered`. Checkpointed (resumable), estimated 7-9h total
  (LOC ~1.8h, PER ~5.3h at clean-system rates). Smoke-tested end to end (8
  real matches written); LOC matches are clean (Amsterdam, Engelant->
  Engeland), PER matches are noisier (common words again: "Staten"/
  "Nederlanden"/"heer" collide with actual PER-dictionary surnames) --
  treat PER output as needing heavier review than LOC.

  Separately, explored few-shot local-LLM split-point prediction as an
  alternative to GysBERT fine-tuning for the still-open "next candidate (2)"
  above (actual split-point placement): reuses `s4_bundled_split_poc.py`'s
  exact 22-position gold set and tol50/150 scoring harness unchanged, swaps
  in a new stage that few-shot prompts a local Ollama model (`qwen32b:latest`,
  already pulled locally) with other gold positions' (text -> interior cut
  offsets) as in-context examples, no fine-tuning involved. Built
  [scripts/s4_llm_split_poc.py](scripts/s4_llm_split_poc.py) (+ 10/10 tests
  on the parseable logic; the Ollama call itself is untested by design).
  Checkpointed/resumable given 22 sequential local-LLM calls. Registered
  `s4_fuzzy_surface_form_scan`, `s4_llm_split_poc`, `loc_entities`,
  `per_entities`, `org_entities` in `data_manifest.toml` (the entity
  dictionaries as local `data.bak/` copies -- not confirmed against a
  canonical warm-tier path, see manifest description). Both scripts handed
  off for the user to run; results not yet in hand.
- [X] **S5** — evaluation adapter completed: [scripts/evaluate_s4_paragraph_axis.py](scripts/evaluate_s4_paragraph_axis.py)
  excludes C/M days from quality denominators, reports coverage separately, and writes
  `output/s5_paragraph_axis_evaluation.jsonl` (verified via
  [tests/test_evaluate_s4_paragraph_axis.py](tests/test_evaluate_s4_paragraph_axis.py); current
  run: 21 eligible days, 5 predicted, coverage 0.238, 16 `insufficient_entity_anchors`
  abstentions). Routing those abstentions to
  [sequence_review_ui.py](sequence_review_ui.py) is deferred — it depends on the next S4
  iteration (expanded phrase inventory) changing the abstention set, so wiring the UI now would
  be rework. *(S0, S3, S4)*
- [ ] **S6** — **multi-channel anchor chaining at character coordinates.** Guide:
  [docs/steps/STEP_S6_anchor_chain_alignment.md](docs/steps/STEP_S6_anchor_chain_alignment.md).
  Corrects a coordinate drift, not the alignment idea: §6.3 of
  [docs/SEGMENTATION_TRANSFER.md](docs/SEGMENTATION_TRANSFER.md) already specified that cut points
  land at **character** positions, but
  [scripts/s4_paragraph_axis_baseline.py](scripts/s4_paragraph_axis_baseline.py) emits
  `paragraph_stream_index`, with `char_offset` only as a phrase-snap byproduct. Measured on all 50
  gold days: 109/352 cut slots (31.0%, 25 days) share a paragraph index, and the hard recall bound
  **at tolerance 0** rises **79.5% → 90.9%** (280 → 320 distinct reachable positions) under
  `(paragraph_stream_index, char_offset)`; the 32 residual slots have `char_offset: null`, an
  annotation gap rather than a coordinate limit. (That bound is rigorous at tolerance 0 only — see
  the 2026-09-20 correction in [docs/DECISIONS.md](docs/DECISIONS.md).) Three changes: character coordinates on one
  per-inventory axis; **all** anchor inventories scoring into one chaining comparison, weighted per
  provenance group (tagger entity layer / dictionary+fuzzy surface / formulaic text /
  structural+temporal) so the shared tagger is not counted three times; and **session starts as
  anchors rather than partitions**, which turns the 7 cross-day-shift days and some of the 535
  no-same-day-HTR days from exclusions into scoreable regions. Algorithm is colinear anchor chaining
  (seed–chain–extend, banded by D1c's transposition width), not global NW over a dense alphabet and
  not an off-the-shelf bioinformatics library. **S6a (the character-coordinate harness) must come
  first** — until scoring runs on that axis, every S6 result is invisible to the tracked metrics.
  Reopens `boundary_f1_tolerance0/2`, closed 2026-09-18, on a new axis. *(S0, S3, S4, S5)*

  **Session 2026-09-20 (S6a done).** Built
  [scripts/s6a_char_axis_evaluation.py](scripts/s6a_char_axis_evaluation.py)
  (+ `tests/test_s6a_char_axis_evaluation.py`, 14/14 passing; output registered as
  `s6a_char_axis_evaluation`). This also closes the separately-registered
  `interior-cut-evaluation-harness` track — they were the same piece of work.
  Composition is **pure concatenation, no separator**: gold `paragraph_boundary`
  cuts carry `char_offset == len(paragraph_text)` (verified on 1626-01-08, where
  paragraph 0 has length 424 and its boundary cut sits at 424), so a paragraph-final
  cut composes to exactly the next paragraph's start and the two descriptions of that
  point share one coordinate. `compute_boundary_prf` is unit-agnostic and needed no
  change — only this adapter.

  **Re-scored baseline, predictions unchanged** (the 2026-09-18
  `s4_paragraph_axis_predictions` composed onto the new axis): micro F1 **0.467**
  (tol 0 chars) / **0.500** (tol 50) / **0.567** (tol 150); coverage 7 / 19 scoreable
  days. These are *not* comparable to the 0.576 / 0.727 paragraph figures — different
  unit, and tol 0 characters is a far harder target than tol 0 paragraphs. The point
  is the headroom: 0.467 against a 0.889 ceiling, where the paragraph metric was
  saturated against its own.

  **Ceiling corrected: 313/352 = 0.889, not 320/352 = 0.909** (recorded in
  `docs/DECISIONS.md`, and the step guide's table amended). 39 cut slots carry
  `char_offset: null` and fall into 7 distinct `(date, paragraph_index)` groups; the
  320 figure added those 7 groups to the 313 genuinely distinct character positions.
  A slot with no offset has no character coordinate. Strict composition confirms all
  313 offset-bearing cuts land on 313 distinct positions, with 0 off-axis cuts and 0
  cuts on axis-less days — no residual collisions at all. The character axis still
  wins by a real margin; the gain is +9.4 points rather than +11.4.

  **Folded-anchor structure** is emitted per day as requested: 24 folded groups
  across 16 days, of which 22 (91.7%) gain distinct character coordinates under
  composition. The 2 that stay folded contain only `char_offset: null` slots.

  **Scoring denominator clarified.** Only 35 of the 50 gold days have any
  `boundary_gold_paragraph_axis` records; the other 15 all have `k_f == 0` and
  `flat_ids == []` — the accepted `missing_htr` ceiling (13 carry review code `M`;
  1626-05-17 and 1627-04-11 are the two uncoded `k_e == 1` days already noted). A day
  with no text has no character axis, so 19 of the 21 eligible days are scoreable.

  **Session 2026-09-20 (S6 Step 1: which constraint binds?).** Before building S6c's
  chaining DP, measured whether anchor *selection* is the bottleneck at all. Chaining
  changes which anchors are trusted; it does not change what happens between chosen
  anchors, nor the coordinate emitted. So an oracle-anchor run is an **upper bound on
  what any anchor-selection improvement, chaining included, can reach**. Built
  [scripts/s6_oracle_anchor_diagnostic.py](scripts/s6_oracle_anchor_diagnostic.py)
  (+ 18 tests; output `s6_oracle_anchor_diagnostic`), handing the *unmodified*
  `interpolate_positions` + `snap_boundaries` a perfect gold-derived anchor set and
  scoring on the S6a character axis.

  | anchors | days predicted | tol 0 | tol 50 | tol 150 |
  | --- | --- | --- | --- | --- |
  | real (S6a baseline) | 7 / 19 | 0.467 | 0.500 | 0.567 |
  | oracle, all | 5 / 19 | 0.727 | 0.788 | 0.788 |
  | oracle, endpoints only | 11 / 19 | 0.546 | 0.579 | 0.645 |

  **The decisive number is coverage, not F1.** With a perfect anchor set the model
  predicts only **5 of 19** days (0.263): 9 abstain `folded_anchors_non_monotone`,
  5 `axis_shorter_than_k_e`. Chaining cannot help a model that discards perfect
  anchors on three days out of four. Oracle F1 also caps at 0.788 rather than near
  1.0 because the model emits `(paragraph index, snap offset)`, leaving 33 of 177
  gold cuts (18.6%, `mid_paragraph`) largely unreachable at tight tolerance.
  Recorded in `docs/DECISIONS.md` (2026-09-20).

  *Caveat:* the `all` (5 days) and `endpoints` (11 days) rows cover **different day
  sets** — thinning to two anchors dodges the non-monotone check — so 0.788 vs 0.645
  is not a density effect.

  **Lumped baseline (added on request).** To get one baseline population rather than a
  reachable/unreachable split, `s6a_char_axis_evaluation.py` now also scores with gold
  cuts collapsed onto the paragraph they open (interior cuts credited at their paragraph
  start, de-duplicated) and model output collapsed the same way:

  | scoring | tol 0 | tol 50 | tol 150 |
  | --- | --- | --- | --- |
  | strict (character precision) | 0.467 | 0.500 | 0.567 |
  | lumped (paragraph granularity) | 0.828 | 0.828 | 0.828 |

  Lumped is flat across tolerances because once both sides sit on paragraph starts the
  candidates are far apart, so slack changes nothing. Read together: **the model picks
  the right paragraph ~83% of the time, and essentially all of the drop to 0.467 is
  sub-paragraph precision** — which is the error a character-granular segmentation DP
  would target. Recorded as `char_axis_boundary_f1_lumped`; the strict metrics keep
  their own history and are unchanged.

  **Next: S6b** — anchor harvest into one `(inventory, char position, channel, group,
  weight, payload)` table across provenance groups A–D (useful under any algorithm),
  then a **count-constrained segmentation DP** at character granularity in place of
  S6c's chaining DP.

  **Session 2026-09-20/21 (S6b constraint baseline, partial).** Built
  [scripts/s6b_known_point_ledger.py](scripts/s6b_known_point_ledger.py) +
  [scripts/s6b_constraint_baseline_report.py](scripts/s6b_constraint_baseline_report.py)
  (registered `s6b_known_point_ledger`) to test SEGMENTATION_TRANSFER.md §7's claim that
  unanchored gaps are short and locally constrained. Chains typed known points (session
  start/end sentinels, tier-1 entity anchors, hand-annotated gold boundaries — groups A and
  D only, not the full B/C anchor set S6b's guide calls for) at character coordinates and
  counts how many resolutions must fall in each gap.

  Run on a contiguous window (1626 H1) first: of 495 gaps, 81.2% are determined-or-nearly by
  *count* but hold only 24.8% of unplaced resolutions — the 93 open gaps (>2 unplaced) hold
  75.2% of the work (recorded in `docs/DECISIONS.md`, 2026-09-20). Then run on the full
  1626–1630 period ([docs/S6B_CONSTRAINT_BASELINE.md](docs/S6B_CONSTRAINT_BASELINE.md)): 5,111
  of 13,530 enriched resolutions (37.8%) are pinned by a known point; 947 open gaps (15.7% of
  gaps by count) hold 5,302 of 7,504 unplaced resolutions (70.7%), spanning 3.13M characters,
  up to 25 resolutions long. Inventory 4562 is anchor-starved (7.6% pinned vs 18.9% corpus
  average) and should not be pooled when fitting weights.

  **This is not yet S6b's exit criterion.** The guide asks for all four provenance groups and
  a measurement of how far the anchor set closes the 815 corpus-wide
  `insufficient_entity_anchors` abstentions; what's built only uses groups A (tier-1) and D
  (session sentinels) plus gold boundaries, with no group B (`entity_surface_matches_1626_1630`,
  `s4_fuzzy_surface_form_scan`) or group C (`s2_anchor_phrase_inventory`,
  `s4_opening_phrase_candidates`) anchors, and no per-channel weight/payload columns. It's a
  valid standalone finding (the open-work is concentrated in 947 long gaps, not diffuse — a
  much better-specified target than corpus-wide boundary F1), not yet the harvest table itself.
  **Next S6b action:** add groups B and C to the ledger and re-measure whether the 70.7%
  open-gap share falls.

  **Session 2026-09-21 (anchor harvest table).** Built
  [scripts/s6b_anchor_harvest.py](scripts/s6b_anchor_harvest.py) (+
  `tests/test_s6b_anchor_harvest.py`, 9/9 passing) — the literal `(date, inventory,
  char_position, channel, group, weight, payload)` table §2.2 asks for, across all four groups:
  **A** `tier1_entity_nw` (reused from the existing alignment table); **B**
  `entity_surface_matches_1626_1630` (flat-id/paragraph-start granularity) and
  `s4_fuzzy_surface_form_scan` (true char-offset granularity — its full corpus run had actually
  completed: 189,764 rows on disk, not just the smoke test the earlier note above described);
  **C** `s2_anchor_phrase_inventory` (top-20) and `s4_opening_phrase_candidates` (271 phrases),
  both scanned per paragraph with one `FuzzyPhraseSearcher` built once and reused across the
  whole window; **D** session start/end sentinels only — DAT date hooks and `para_start` are
  still not wired in, no dataset maps them onto this axis yet. Registered `s6b_anchor_harvest`
  in `data_manifest.toml`; `data_io.check` passes.

  Smoke-tested on 1626-01-01..03-01 (36 days, 6,857 rows, ~106s) to validate correctness before
  committing to the full run: group A 149 anchors/32 days; group B 617 + 5,007 anchors/36 days;
  group C 465 + 547 anchors/36 days. Of 26 `insufficient_entity_anchors` abstentions in this
  window, 3 had zero group-A anchors at all, and all 3 gain a non-A anchor once B/C are
  harvested — an anchor-**supply** signal only, not a placement guarantee (the S6 Step 1 oracle
  diagnostic already showed the placement model, not anchor supply, is often what binds).

  **Not run corpus-wide this session.** Extrapolating the smoke window's ~3s/day gives an
  estimated 80–90 minutes for the full 1626–1630 period — heavy enough to hand to the user
  rather than run inline. **Next S6b action:** run
  `uv run python -m scripts.s6b_anchor_harvest` (full period, no args needed) and read
  `density_by_channel` / `insufficient_entity_anchors_supply_gain` off the output summary row
  for the real corpus-wide numbers, then decide whether S6c (a chaining DP that resolves a raw
  B/C position to an enriched index) is worth building from those.

  **Session 2026-09-21 (full-corpus run — decisive finding, closes S6b).** User ran the harvest
  corpus-wide: 247,871 anchor rows over 1,240 days-with-axis. Of the 815 corpus-wide
  `insufficient_entity_anchors` abstentions, only **59 (7.2%) had zero group-A anchors at all**
  — the other 756 (92.8%) already had ≥1 group-A anchor and abstained anyway, because
  `interpolate_positions`'s monotonicity/axis-length requirements reject them, not because
  anchors were scarce. Of the 59 zero-anchor days, 57 (96.6%) gain a non-A anchor from groups
  B/C — but that's only 57/815 = **7.0% of all abstentions**, despite group B/C anchor volume
  being enormous (`fuzzy_surface_scan` alone touches 162,307 distinct character positions
  across 1,238 of 1,240 days). Recorded in `docs/DECISIONS.md` (2026-09-21).

  **This confirms the S6 Step 1 oracle diagnostic at full corpus scale, from the supply side
  this time.** The oracle diagnostic (perfect anchors, still only 5/19 gold days placeable)
  showed the placement model binds; this harvest (real B/C anchors, only ~7% of abstentions
  affected) shows the same thing from the other direction. Two independent measurements now
  agree: **do not build S6c as a chaining step that resolves more anchors for the existing
  rigid `interpolate_positions`.** S6b's exit criterion (anchor density + abstention-closing
  measurement) is answered, and the answer is "anchor supply isn't it" — but see the caveat
  immediately below before treating that as settled.

  **CAVEAT (2026-09-21, RESOLVED same day) — this 815/59/57 result was measured on stale
  inputs.** `alignment_1626_1630.parquet` (every group-A anchor's source) was last built
  2026-08-28 and `s4_corpus_paragraph_predictions.jsonl` (the 815-abstention list's source)
  2026-08-31 — both **before** the place/org overlap rebuild (2026-09-19) and the PER overlap
  rebuild (2026-09-21). Neither had been regenerated against the now-fully-swapped overlap
  tables. Recorded in `docs/DECISIONS.md` (2026-09-21, "Caveat on the S6b anchor-supply
  finding"). The placement-model ceiling is an algorithmic property and likely survives a
  refresh, but that's an expectation, not a measurement.

  **Session 2026-09-21 (re-run on refreshed inputs — caveat resolved).** Re-ran
  `build_alignment_new.py` (11:43) then `scripts.s4_corpus_paragraph_predictions` (11:44)
  against the swapped overlap tables, closing `adopt-windowed-overlap-rebuild`'s own pending
  downstream-re-run action. Before re-running the anchor harvest, parallelized and
  checkpointed [scripts/s6b_anchor_harvest.py](../../scripts/s6b_anchor_harvest.py) (fork-based
  `ProcessPoolExecutor`, one task per day, shared read-only lookups/searchers inherited via
  copy-on-write; `.checkpoint.jsonl` scratch file + `--resume` following the same pattern as
  `s4_fuzzy_surface_form_scan.py`; 4 new tests in `tests/test_s6b_anchor_harvest.py`, 13/13
  passing) — smoke-tested at 13/36/75-day windows first (steady-state ~1.3s/day at 12 workers
  vs. the prior single-process ~3s/day), then ran the full 1626-1630 corpus in the background:
  1240 days, 247,914 anchor rows in ~32 minutes (vs. the ~85-90 min serial estimate — a real
  but sub-linear ~3x speedup, capped by fixed data-loading overhead and per-day load
  imbalance, not the ~12x core count).

  **The split survives the refresh, and is now more lopsided in the same direction.**
  Corpus-wide `insufficient_entity_anchors` abstentions dropped 815 → **777**; of those, only
  **19 (2.4%, was 59/7.2%)** have zero group-A anchors, and only **18 (2.3% of all
  abstentions, was 57/7.0%)** gain a non-A anchor from groups B/C. **758/777 = 97.6%** of
  abstentions (was 92.8%) already had a group-A anchor and abstained anyway. Recorded in
  `docs/DECISIONS.md` (2026-09-21, "S6b anchor-supply finding re-confirmed on refreshed
  inputs").

  **Decision, now on measured (not stale) data: do not build S6c as a chaining step that
  resolves more anchors for the existing rigid `interpolate_positions`.** S6c should instead
  be a count-constrained segmentation DP working directly inside each gap from
  `s6b_known_point_ledger.py`'s chain (947 open corpus-wide gaps hold 70.7% of unplaced
  resolutions), using B/C raw positions as soft in-gap evidence rather than pre-resolved,
  index-pinned anchors.

  **Session 2026-09-21 (S6c target metric rescoped — paragraph-level, not char-exact).**
  Before building S6c, checked whether any downstream consumer actually needs
  character-exact cut points. It does not: `s4_resolution_concordance.py` (the one real
  downstream assembly step) treats paragraph attribution as explicitly optional best-effort,
  not required per row; `build_alignment_new.py` (the live entity-matching pipeline) works
  entirely on `paragraph_id → resolution_id` and never reads character offsets; NER training
  pairs get their offsets from the separate `LOC-/PER-annotations.json` layer, unrelated to
  this track's output; `resolution_concordance_1626_1630` has zero downstream readers today.
  The char-axis push (S6/S6a/S6b) was motivated by defeating a self-imposed plateau on
  `boundary_f1_tolerance0` (`docs/DECISIONS.md` 2026-09-20), not a named consumer's need.
  Recorded in `docs/DECISIONS.md` (2026-09-21, "S6c target metric rescoped").

  **Consequence: S6c should target coverage and paragraph-level (`lumped`) accuracy, not
  tol0/tol50 character precision.** This also sidesteps a real risk — S6c's originally-scoped
  in-gap character placement (B/C anchors as soft evidence for an exact cut) would likely
  have inherited `s4_bundled_split_poc.py`'s already-measured weak precision (0-15% recall at
  tol50). Scoped to paragraph granularity instead, S6c's job narrows to fixing
  `interpolate_positions`'s over-eager abstention (only 5/19 days predicted even with
  oracle-perfect anchors, S6 Step 1 diagnostic) while keeping today's paragraph-level
  placement quality (0.828 lumped) — a smaller, better-evidenced target than the original
  scope. **Next S6c action:** build the in-gap DP against the `lumped` paragraph-level score
  and predicted-day coverage as the primary metrics; treat any tol0/tol50 gain as a bonus,
  not the target. If lumped/coverage still doesn't move, the next escalation is the
  already-scoped-but-`blocked` line-level-segmentation track (needs a `sessions_json`
  page-to-date extraction, `docs/DECISIONS.md` 2026-09-18), not a fresh approach.

  **Session 2026-09-21 (closed `adopt-windowed-overlap-rebuild`; step guide corrected).**
  `svz.py review` kept resurfacing `adopt-windowed-overlap-rebuild` as unjudgeable even
  though the downstream re-run had already happened (as part of the S6b caveat-resolution
  session above) — its own goal ("check whether headline tier/confidence stats move") had
  never actually been checked against `build_alignment_new.py`'s own output. Loaded
  `alignment_1626_1630.parquet` (13,342 rows, unchanged total) and compared
  `confidence_tier` counts to the pre-swap figures already documented above: `tier1_anchor`
  5,725→5,730, `tier2_*` 4,734→4,708, `tier3_*` 2,883→2,904 — largest single-tier delta 26
  rows (0.19pp). Headline tier composition barely moved; the swap's real effect surfaced in
  S6b's anchor-supply numbers instead (815→777 abstentions), not here. Recorded via
  `svz.py metric`/`svz.py decision` and closed the track `done` (`docs/DECISIONS.md`
  2026-09-21). Also found `docs/state.json`'s `s6-anchor-chain-alignment` entry and
  [docs/steps/STEP_S6_anchor_chain_alignment.md](docs/steps/STEP_S6_anchor_chain_alignment.md)'s
  S6c row still described the pre-rescope plan (re-run as a pending action; S6c as a
  chaining DP scored at char tol 50/150) — both now updated to match the rescoped S6c
  target above, so `svz.py review`'s recommendation and the step guide agree.
  **Next: S6c** — build the count-constrained segmentation DP inside
  `s6b_known_point_ledger.py`'s gaps, per the rescoped target two paragraphs up. Not
  started this session (design/implementation work, out of scope for a bookkeeping pass).

  **Session 2026-09-21 (S6c built and validated on the 50 gold days).** Built
  [scripts/s6c_gap_segmentation.py](../../scripts/s6c_gap_segmentation.py)
  (`segment_gap` / `segment_day`, 11/11 tests) and swapped it in for
  `interpolate_positions` inside `predict_day`
  ([scripts/s4_paragraph_axis_baseline.py](../../scripts/s4_paragraph_axis_baseline.py))
  and `predict` ([scripts/s4_corpus_paragraph_predictions.py](../../scripts/s4_corpus_paragraph_predictions.py)).
  `interpolate_positions` itself is untouched — `s6_oracle_anchor_diagnostic.py`
  deliberately keeps pinning to the unmodified model.

  The DP never abstains: a non-decreasing anchor backbone is always bounded by the
  structural session start/end sentinels `(0, 0)` / `(k_e, axis_count)` (STEP_S6 §2.2
  group D, matching `s6b_known_point_ledger.py`'s chain convention rather than letting a
  stray NW match at enriched index 0 shift the origin); an anchor that would go backwards
  is clipped forward instead of aborting the day; and a gap narrower than the resolutions
  it must hold gets repeated paragraph assignments instead of `None` — exactly what lumped
  paragraph-level scoring already tolerates. Inside each gap it chooses `count`
  non-decreasing positions maximizing an even-split-vs-phrase-hit tradeoff (group-C
  evidence, reusing the existing gold-day `phrase_hits`), falling back to plain
  interpolation with no evidence.

  **Real gold-day result** (re-ran `s4_paragraph_axis_baseline.py` →
  `evaluate_s4_paragraph_axis.py` / `s6a_char_axis_evaluation.py`, no other inputs
  changed): predicted-day coverage **9/21 → 19/21** eligible (**7/19 → 19/19** scoreable —
  every day with an axis now gets a prediction). Lumped paragraph-level F1 held flat:
  **0.828 → 0.826** at tol50/150 (0.806 at tol0). Strict character F1 was roughly flat at
  tol50 (**0.500 → 0.503**) and dipped slightly at tol0/150 (0.467→0.432, 0.567→0.538)
  despite predicting on **nearly 3× as many days**, including the harder ones the old
  model used to refuse outright. Recorded via `svz.py metric`
  (`s6c_gold_day_coverage=0.905`, `char_axis_boundary_f1_lumped_tol150=0.826`,
  `char_axis_boundary_f1_tol50=0.503`) and `svz.py decision` (2026-09-21). This is exactly
  the coverage win the rescoped S6c target asked for — obtained without a corpus-wide run.

  **Deferred, not overlooked:** group B (`entity_surface_matches_1626_1630`,
  `s4_fuzzy_surface_form_scan`) is not wired into `position_scores` yet, and the corpus
  predictor (`s4_corpus_paragraph_predictions.py`) currently gets no phrase-hit evidence
  at all — adding either means a per-day `FuzzyPhraseSearcher`/lookup pass over the full
  1626-1630 corpus, the kind of run `s6b_anchor_harvest.py` needed ~32 minutes
  (parallelized) for, which this session did not run. **Next S6c action:** hand
  `uv run python -m scripts.s4_corpus_paragraph_predictions` to the user for a corpus-wide
  re-run (cheap — no phrase search, same cost as before) and read the new
  `insufficient_entity_anchors` count off it (expected to collapse from 777 toward ~0);
  if the coverage/lumped gain holds at corpus scale, decide whether group-B/C evidence at
  corpus scale is worth its runtime before declaring S6c done.

  **Session 2026-09-21 (corpus-wide re-run — insufficient_entity_anchors eliminated).**
  User ran `uv run python -m scripts.s4_corpus_paragraph_predictions` (no code changes
  since the note above). Result: **1,059 predicted / 535 abstained**, and the abstained
  set is now `missing_htr` only — **`insufficient_entity_anchors` is exactly 0** (was
  777). 1,059 = 282 (pre-existing predictions) + 777 (every previously-abstained day now
  predicts) — an exact match confirming the mechanism, not a coincidence. **100% of days
  with any paragraph axis now receive a prediction.**

  **Quality caveat, quantified directly from the output** (no gold labels exist
  corpus-wide, so this substitutes for an F1 check): of the 1,059 predicted days, 48 are
  trivial (`k_e <= 1`, no cuts needed), 302 are clean (no repeated paragraph index), 516
  have a minor 2–3-way collapse, 114 have 4–6, and **79 (7.5%) have 7+ resolutions
  collapsed onto one paragraph** (max 24) — these are low-localization coverage wins, not
  real segmentation, an expected and disclosed consequence of allowing repeats rather than
  a bug. Recorded via `svz.py metric`
  (`corpus_insufficient_entity_anchors_abstentions=0`,
  `corpus_coverage_of_days_with_axis=1.0`, `corpus_severe_collapse_share=0.075`) and
  `svz.py decision` (2026-09-21).

  **S6c's rescoped exit criterion (coverage + gold-day lumped F1, not char precision) is
  met.** Group-B evidence and corpus-scale phrase-hit wiring remain deferred, scoped as
  the next increment only if the severe-collapse share needs improving — not required to
  call S6c done.

  **Session 2026-09-21 (S6d pivoted: wire the corpus predictor to
  `resolution_concordance_1626_1630` instead of building session-as-anchor chaining).**
  Before implementing STEP_S6's original S6d design (drop the per-day partition, run per
  inventory with session starts as group-D anchors), a sizing check on the 79 severe-
  collapse S6c days led to a bigger discovery: a separate, already-"accepted final" track
  (S4a-g: `session_date_status_1626_1630` → `s4_day_status_resolution` →
  `resolution_concordance_1626_1630`, [docs/CANDIDATE_SCORING_AND_CONCORDANCE.md](docs/CANDIDATE_SCORING_AND_CONCORDANCE.md))
  already resolves session/day mapping per enriched resolution — including confident
  entity-overlap candidate scoring over ambiguous ledger `-1`/`+1`/`?` rows — and
  `s4_corpus_paragraph_predictions.py` never consulted it, grouping paragraphs by raw
  calendar date only. Exactly the orphan pattern STEP_S6 section 1(b) warned about.

  Considered and rejected auto-selecting ledger `-1`/`+1` candidates directly as a
  cheaper alternative: [docs/SESSION_DATE_MAPPING_REVIEW.md](docs/SESSION_DATE_MAPPING_REVIEW.md)
  already decided those need human review with a mandatory note, and a quick check showed
  why — 348/365 (95%) of unique `-1`/`+1` candidates are *also* their true neighbor day's
  own trusted/exact match, so whether that's genuine shared-session content or a dating
  mismatch needs a human reading the actual text, not a blanket policy.

  Instead wired `scripts/s4_corpus_paragraph_predictions.py` to fall back to
  `resolution_concordance_1626_1630`'s `resolved_session_id` (`day_status ==
  "resolved_auto"`) when a date has no same-calendar-day axis, via two new pure functions
  (`session_of`, `axis_for_date`, 4 new tests) — a data-source wiring fix, not new
  alignment logic, per the "replace, don't accrete" guardrail. Re-ran the corpus
  predictor (no other changes, ~2.5s): predicted 1,059 → **1,140**, `missing_htr`
  abstentions 535 → **454** — 81 days recovered for free from work already done and
  accepted by a separate track. Full test suite (354 passed) and `data_io.check` clean.
  Recorded via `svz.py metric` (`corpus_missing_htr_after_concordance_wiring=454`) and
  `svz.py decision` (2026-09-21).

  **Remaining gaps, explicitly out of scope this session:** the 365 `-1`/`+1` ledger rows
  still need the pending human-review workflow before they can resolve further; the 7
  gold cross-day-shift days (trailing contaminated text on a day that *does* have its own
  axis) are a different failure mode this wiring does not touch, and neither does
  STEP_S6's original session-as-anchor design fully solve them without the same
  representational problem noted above (a boundary that legitimately belongs to a
  neighboring day has no slot in the current per-day scoring schema). **Next:** either (a)
  run the S4f human-review UI (`build_session_date_mapping_review_ui.py` /
  `merge_session_date_mapping_decisions.py`) to close out the long-pending `-1`/`+1`
  queue — a review task, not a coding one — or (b) pick a different track per `svz.py
  review`. STEP_S6's S6d (session-as-anchor chaining) is superseded by this wiring for
  its stated success criterion and is not planned to be built as originally scoped.

  **Session 2026-09-21 (S4f review started; found `resolutions_flat` session-numbering
  drift instead — bigger than the queue itself).** Took option (a): scoped
  `build_session_date_mapping_review_ui.py` to just the `-1`/`+1` rows via a new
  `--status` filter (365 rows), then added `drop_nihil_actum_rows`/`enriched_text_by_date`
  to exclude the 64 rows whose enriched date is a pure "Nihil Actum" entry (already
  auto-resolved ahead of human review by `s4_day_status_resolution.py`'s precedence) —
  301 rows left, 5/5 new tests passing. User hand-reviewed ~10 and exported decisions
  (`data/import/s4_session_date_mapping_decisions.json`): 4/9 approvals confirmed a
  real signal (a "President de Heer X, Present de \<weekday\> den \<date\>" session-start
  formula appearing *mid-session*, i.e. two real sessions merged into one HTR-parsed
  block), which a new lenient diagnostic (`scripts/s4_session_start_scan.py`, prefix-stem
  regex on `presid`/`presen` stems, deliberately recall-favoring) reproduced at scale:
  210 candidate mid-text starts across 167/1,511 sessions (11.1%) in ~2s.

  But 3/9 no-match decisions cited true dates 2-3 days outside the ledger's ±1-day
  candidate window (found via `app.goetgevonden.nl`'s per-resolution-URN dates) —
  investigating those revealed those "external" dates are just `resolutions_flat`'s own
  per-session date restated, not independent ground truth. Chasing why led to pulling
  raw `sessions_json_source` JSON directly (new warm-tier cache
  `s4_session_date_region_scan`, 51,677 text_regions across all 1,690 sessions in the
  ledger's 6 covered inventories — 179 more sessions than `resolutions_flat` sees at all,
  since it holds zero rows for nihil-actum/empty sessions). That surfaced the real,
  bigger finding: **`resolutions_flat`'s session numbering has drifted from the current
  archive**. Confirmed by matching a 150-char content fingerprint from each
  `resolutions_flat` session against its own inventory's raw sessions: 1,128/1,511
  (75%) matched a unique raw session, 0 ambiguous, 383 unmatched. Per-inventory drift
  shape varies: `3185`/`3186`/`3189` accumulate a monotonic +1-at-a-time staircase
  (reaching +9/+13/+8), `3187` is mild (0 for ~240 sessions, then +1, +2), `3188` is
  bidirectional (starts at −2, ends at +8), and `4562` oscillates between 0/+1/+2
  dozens of times rather than accumulating — likely a structurally different case
  (interleaved series?) worth checking before assuming it behaves like the others.
  Every step changes by exactly ±1, consistent with one session being inserted/removed
  at a time as the archive was re-segmented since `resolutions_flat` was built, not
  wholesale renumbering.

  Practical upshot: a real chunk of `-1`/`+1` (and likely `A`/`X`/`N`) rows reflect
  numbering drift, not genuine nearby-day ambiguity — the candidate session id is
  simply mislabeled relative to its actual content. Fixing the *ledger* is a bigger job
  (per-inventory realignment against `sessions_json_source`) than reviewing the queue as
  currently framed. **Next:** add two new Group-D channels to `s6b_anchor_harvest.py`
  (`CHANNEL_GROUP`/`harvest_row`, alongside the existing `session_boundary` sentinel),
  per STEP_S6 section 2.2 ("structural/temporal", chained with the other groups, not
  summed): (1) `session_day_find` — direct date-phrase hits from raw `text_regions`
  (the `President de Heer X, Present de <weekday> den <date>` / `Praeside et
  Praesentibus` formula; catches what the upstream `nlc_classifier`'s "date"
  `text_region_class` tag misses — confirmed both false-negative, e.g. it missed the
  real Feb-8 header in `session-3185-num-26`, and false-positive, e.g. it tagged an
  unrelated "Amsterdam 12 schepen2 Jachten" line as "date"). Self-sufficient: works on
  all 1,690 raw sessions, not just the 75% with a `resolutions_flat` match. (2)
  `session_date_verified` — the content-fingerprint correspondence between
  `resolutions_flat`'s (possibly mislabeled) session id and the raw session it actually
  matches; needed specifically because a date alone doesn't say what `resolutions_flat`
  currently calls that content. Open design question before either is quick to build:
  `s6b`'s `char_position` axis is built from `resolutions_flat`'s own (possibly
  drifted) text, so anchoring must key off content or archival provenance
  (`scan_id`/`page_id`/`line_id`), not the session-number label. Reusable state:
  `s4_session_date_region_scan` (warm tier, registered) has the raw text_region data;
  the 1,128 confirmed offset matches are only in `/tmp/scope_results.json` (scratch,
  not persisted) and would need regenerating or saving properly before the channel
  work starts.

  **Session 2026-09-21 (fingerprint-match prerequisite persisted).** Took the S4f
  handoff's flagged prerequisite before either new Group-D channel
  (`session_day_find`, `session_date_verified`) can be built: the content-fingerprint
  correspondence between `resolutions_flat` session ids and raw `sessions_json_source`
  sessions existed only in unregistered scratch (`/tmp/scope_results.json`, 1128/1511
  matched via an undocumented method). Built
  [scripts/s6b_session_fingerprint_match.py](../../scripts/s6b_session_fingerprint_match.py)
  (9 tests) and registered `s6b_session_fingerprint_match` in `data_manifest.toml`.
  150-char normalized fingerprint of each flat session's resolution text, matched by
  **substring containment** (not exact-prefix equality) against same-inventory raw
  sessions' concatenated `para`-class region text — exact-prefix only found 838/1511
  (55.5%; `resolutions_flat`'s paragraph splitting doesn't align 1:1 with raw para
  region boundaries, e.g. an attendance line mistagged `para` gets spliced out of the
  flat text, so real content can start partway into the raw concatenation); substring
  containment finds **1059/1511 (70.1%), 0 ambiguous**. `data_io.check` and the full
  suite (363 passed) are clean. Recorded via `svz.py metric`/`svz.py decision`
  (2026-09-21). This closes only the persistence prerequisite, not the anchor channels
  themselves — the open design question from the S4f note (key on content/provenance,
  not the drifted session-number label) is what `s6b_session_fingerprint_match`'s
  `raw_session_id`/`raw_num`/`offset` columns now answer. **Next:** build
  `session_day_find` and `session_date_verified` as new Group-D channels in
  `scripts/s6b_anchor_harvest.py` per STEP_S6 section 2.2, using this dataset for the
  latter.

  **Session 2026-09-21 (`session_day_find` built, fuzzy-vs-regex validated before
  wiring in).** Built the first of the two Group-D channels:
  `phrase_hits`/`session_day_find_rows` in
  [scripts/s6b_anchor_harvest.py](../../scripts/s6b_anchor_harvest.py), pairing a
  "president"-family phrase hit with a nearby "present"-family hit past a day's own
  opening — the same internal-merge signal `s4_session_start_scan.py` targets, but
  using `FuzzyPhraseSearcher` (already the tool for every other phrase channel here)
  instead of porting that script's stem regex, so HTR character noise inside a
  correctly-spelled stem is tolerated, not just morphological variation.

  Two bugs surfaced and fixed before trusting any count. `FuzzyPhraseSearcher`'s
  `ignorecase` defaults to `False`; against real text ("Preside et Presentibus...",
  sentence-initial) that undercounted the regex baseline (210 hits/167 sessions,
  measured on the same session-text universe) by 4x (54/45) until set `True` — the
  existing `s2_anchor_phrases`/`s4_opening_phrase_candidates` channels share
  `PHRASE_SEARCH_CONFIG` without this fix, left unchanged since their metrics predate
  the finding (separate follow-up, not folded in silently). Second, at the existing
  0.85 threshold the ignorecase-fixed count jumped to 576/365 — sampled snippets
  showed most were false positives (short words like "present" fuzzy-matching
  unrelated nearby substrings, pairing a generic "de heer President heeft
  geproponeerde..." mention with noise). Raising the threshold to 0.95 dropped the
  count to **154/130** with 25/25 sampled hits genuine (checked twice, different
  random samples) — lower recall than the regex baseline (which was never itself
  checked for precision) but real. Present-family phrase list also narrowed from a
  corpus-frequency guess to one grounded in what actually co-occurs with "presid*" in
  a 60-char window (237/830 occurrences do; 94.5% of those are
  present/presentibus/praesentibus/presentie/presente — `presentatie`/
  `presenterende`/`presenteren`/`presenteert`, common corpus-wide, occur there zero
  times).

  **Scope note:** unlike STEP_S6's original wording ("self-sufficient: works on all
  1,690 raw sessions"), this channel runs over `paragraph_axis_1626_1630` like the
  rest of the harvest — still `resolutions_flat`-derived, not raw
  `sessions_json_source` text_regions — so it does not yet reach the 179 sessions
  with zero `resolutions_flat` rows. 4 new tests (17/17 total in the file), full
  suite (367 passed) and `data_io.check` clean. Recorded via `svz.py decision`
  (2026-09-21). Not yet run corpus-wide (`main()`'s ~32-minute parallelized pass) —
  only validated against the same session-text universe
  `s4_session_start_scan.py` used. **Next:** hand the corpus-wide
  `uv run python -m scripts.s6b_anchor_harvest` re-run to the user, then decide
  whether to build `session_date_verified` (needs the open design question on
  provenance-keyed anchors, not session-number labels) or move to weight fitting
  (S6e) with what Group D has now.

  **Session 2026-09-21 (corpus-wide harvest re-run).** User ran
  `uv run python -m scripts.s6b_anchor_harvest` (no code changes). `session_day_find`:
  **203 anchors / 162 of 1,240 days-with-axis (13.1%)**, 203 distinct positions —
  smallest of all six non-sentinel channels (group A `tier1_entity_nw` alone: 5,375
  anchors/995 days; group B `fuzzy_surface_scan`: 189,764). The
  `insufficient_entity_anchors` supply-gain proxy printed 0/0/0 — degenerate, not a
  finding: S6c already eliminated that abstention category corpus-wide (777 → 0), so
  there's no abstained-day set left to check gains against. `session_day_find`'s real
  signal is low density plus validated precision (154/130 on the session-text universe,
  25/25 sampled genuine), consistent with internal session-merge formulas being rare
  (11.1% of raw sessions) rather than a per-day-typical anchor. Recorded via
  `svz.py metric`/`svz.py decision` (2026-09-21). **Next:** decide `session_date_verified`
  vs S6e (weight fitting) with what Group D has now — `session_day_find`'s sparsity
  argues it won't move coverage much either way, so this is a precision/robustness
  addition to the anchor set, not a new lever on the open coverage questions.

  **Session 2026-09-21 (corpus-scale group-C phrase wiring tested, measured negative).**
  Scoped and tested the deferred increment `s6c_gap_segmentation.py`'s own docstring
  names: feeding `s4_opening_phrase_candidates` evidence into
  `s4_corpus_paragraph_predictions.py`'s `segment_day` call via `position_scores`
  (currently gold-day-only, corpus predictor gets none). Refactored
  [scripts/s4_paragraph_axis_baseline.py](../../scripts/s4_paragraph_axis_baseline.py)'s
  `phrase_hits(axis, phrases)` to `phrase_hits(axis, searcher)` so a `FuzzyPhraseSearcher`
  can be built once and reused — necessary before this is corpus-scale-tractable at all
  — verified behavior-preserving by diffing `s4_paragraph_axis_predictions.jsonl`
  byte-for-byte before/after (identical).

  Before running the full corpus pass (~32 minutes per `s6b_anchor_harvest.py`'s
  precedent), scored the change cheaply: ran the corpus predictor's own
  `predict()`/`grouped_enriched()`/`axis_for_date()` codepath (not the separate gold-day
  pipeline) restricted to the 19/21 scoreable gold days, with and without the phrase
  evidence, scored via `evaluate_s4_paragraph_axis.py`'s own harness. **Result: net
  negative.** tol0 F1 **0.644 → 0.622**, mean Pk/WindowDiff **0.285 → 0.292** (worse);
  tol1/tol2 only marginally better (+0.006 each). Also tried adding `snap_boundaries`
  (the gold pipeline's second phrase-evidence stage, which the corpus predictor never
  had) on top — produced **identical** numbers, confirming this is a real result, not an
  artifact of porting only half the mechanism. Reverted the `predict()`/`main()` wiring
  in `scripts/s4_corpus_paragraph_predictions.py` back to the unmodified
  `segment_day(...)` call; kept only the `phrase_hits` refactor (independently useful,
  verified identical). Recorded via `svz.py metric`/`svz.py decision` (2026-09-21). No
  corpus-wide run was needed to reach this answer — the ~32-minute job was avoided for a
  result that would not have justified it. **Next:** decide `session_date_verified` vs a
  fresh look at what else could close the 79/1,059 severe-collapse days, since
  group-C phrase evidence is now a tested dead end for that specific problem.

  **Session 2026-09-22 (`session_date_verified` built).** Picked `session_date_verified`
  over the severe-collapse diagnostic (user direction — the latter was the recommended
  option given anchor supply's already-established non-bindingness, but not the chosen
  one). Built the third Group-D channel in
  [scripts/s6b_anchor_harvest.py](../../scripts/s6b_anchor_harvest.py)
  (`session_id_char_starts`/`session_date_verified_rows`, 4 new tests, 20/20 passing):
  one anchor per flat session on a day's axis whose content-fingerprint match
  (`s6b_session_fingerprint_match`) uniquely identifies which raw archival session it
  actually is, positioned at that session's first char offset within the day's axis and
  keyed by `flat_session_id` rather than `resolutions_flat`'s own possibly-drifted
  session-number label — the open design question the 2026-09-21 S4f session flagged
  before this could be built. Weighted 4.0 (group D, on par with the validated-but-derived
  `session_day_find`, below the trivially-true `session_boundary` sentinel at 5.0).

  9-day smoke window (1626-01-01..01-10, `--start`/`--end`): **7 anchors / 7 of 9 days**,
  matching the fingerprint match dataset's ~70% overall match rate. `data_io.check` and
  the full test suite clean. **Not run corpus-wide this session** — the smoke run
  overwrote the local (gitignored, regenerable) `output/s6b_anchor_harvest.jsonl` that
  previously held the 2026-09-21 corpus-wide result (247,914 rows); that file now only
  covers the 9-day smoke window until the next full run. **Next:** hand
  `uv run python -m scripts.s6b_anchor_harvest` (full period, no args needed, ~32 min
  parallelized) to the user, read `session_date_verified`'s corpus-wide density off the
  output summary, then decide whether it's worth folding into weight fitting (S6e) or
  whether — per the earlier `session_day_find` precedent and the standing S6 Step 1 /
  anchor-supply findings — it's confirmed low-yield and the severe-collapse angle should
  be picked up instead.

  **Session 2026-09-22/23 (severe-collapse autopsy + `axis_for_date` fix).** Outside this
  conversation, the severe-collapse angle above was picked up instead of `session_date_verified`:
  `scripts/s6c_severe_collapse_autopsy.py` was built and run (92/1,140 predicted days with 7+
  resolutions on one paragraph start; cause mix `pigeonhole_forced` 32, `axis_requires_repeats` 50,
  `room_on_axis` 10 — see `docs/DECISIONS.md` 2026-09-22 "S6c severe-collapse autopsy"), then a
  spot-check of the worst days found `axis_for_date` (`scripts/s4_corpus_paragraph_predictions.py`)
  preferring a thin same-calendar-day stub over a richer concordance-resolved session on a
  neighboring date for 9/92 of them — a real selector bug, not missing HTR (`docs/DECISIONS.md`
  2026-09-22 "axis_for_date must not treat non-empty same_day as a day cutoff").

  This session implemented that fix: `axis_for_date` now prefers the concordance
  `resolved_auto` session over a non-empty same-day stub, falling back to the same-day axis only
  when no resolved session is recorded or its axis is empty (6 tests updated/added,
  `tests/test_s4_corpus_paragraph_predictions.py`, 8/8 passing). Re-ran the full chain —
  `s4_corpus_paragraph_predictions` → `metrics_span_gap_map` → `s6c_severe_collapse_autopsy` —
  and confirmed the spot-check exactly: severe-collapse days **92 → 83** (max pile-up 25 → 16),
  breaking gaps containing a collapse day **43 → 40** (25.15% → 23.39%, `severe_collapse_implicated`
  **True → False** against the 0.25 threshold, reversing the 2026-09-22 reopen call on refreshed
  data). Coverage itself is unchanged (1,140 predicted / 454 `missing_htr`) — of the 1,057 days now
  routed through the resolved-session path, only **77** actually change axis content; the other 980
  resolve to the same underlying session either way, so the headline "days affected" number is 77,
  not 1,057. Global-spans bridge-ceiling reasoning is unaffected (still 0 spans@30, longest 12
  calendar days after bridging `weak_separation`). Recorded via `svz.py metric`/`svz.py decision`/
  `svz.py update`/`svz.py focus` (2026-09-23; see `docs/DECISIONS.md` "axis_for_date fixed and
  remeasured").

  **Along the way:** found and restored an unrelated accidental revert of
  `plans/SHORT_RESOLUTION_SIDE_PLAN.md` (its working-tree copy had lost the entire Step 1–4
  execution record and the Step 7 `CLOSE` decision — restored from HEAD, no content change beyond
  that).

  **Next:** `severe_collapse_implicated` is now `False` on refreshed data, so the autopsy's own
  reopening rationale no longer holds — re-run `svz.py review` to pick the next track rather than
  continuing the severe-collapse thread by default. Densifying `weak_separation` (917 days) toward
  solid remains the only lever shown to move Global spans; nothing in this session changed that.

  **Session 2026-09-23 (scoping the `weak_separation` lever — no code run).** Traced what
  "densify `weak_separation`" actually touches before committing a session to it.
  `s4_corpus_paragraph_predictions.py`'s `predict()` calls `s6c_gap_segmentation.segment_day(...)`
  with **no `position_scores`** for the corpus run — when a gap has more resolutions than
  paragraphs, the DP splits evenly with zero tie-breaking evidence, which is what produces
  non-separated (shared-start or >3-paragraph-extent) resolutions. Of the two deferred
  `position_scores` channels, Group C (`s4_opening_phrase_candidates` phrase hits) was already
  wired in and killed on gold days (2026-09-21, tol0 F1 0.644 → 0.622: do not retry). **Group B**
  (`entity_surface_matches_1626_1630` — already a computed dataset, no search needed) has never
  been wired in at all; `s6c_gap_segmentation.py`'s own docstring still calls it "deferred, not
  overlooked." `s4_fuzzy_surface_form_scan.py` (the separate no-metric track `svz.py review`
  flags) is a different, much heavier 7-9h full-dictionary recovery job and is not a prerequisite
  for this — don't conflate the two.

  **Next:** before any corpus-wide re-run, repeat the 2026-09-21 Group-C methodology on Group B:
  wire `entity_surface_matches_1626_1630` into `segment_day`'s `position_scores` and score it
  cheaply through the corpus predictor's own codepath restricted to the 19/21 scoreable gold days
  (`evaluate_s4_paragraph_axis.py`'s harness). Only if that shows a real gain does a full
  `s4_corpus_paragraph_predictions` re-run (cheap, no search) become worth running, followed by a
  fresh `metrics_span_gap_map` / `weak_separation` count to see whether it actually moved.

  **Session 2026-09-23 (concordance staleness found — Global, primary criterion now met).**
  Before scoping the Group-B `position_scores` wiring above, built a cheap diagnostic
  (`scripts/metrics_weak_separation_headroom_diagnostic.py`, 5/5 tests) to check whether
  `weak_separation` days are even reachable given axis coarseness: per day,
  `structural_ceiling_share = min(1, paragraph_count / k_e_signal)` is a strict upper bound on
  `separated_share`. First run: 91.4% of the 917 `weak_separation` days were `headroom_available`
  (ceiling ≥ 0.5) — but median `separated_share` on those days was exactly **0.0**, even on days
  with `paragraph_count == k_e_signal` (ceiling 1.0). Too implausible to be a placement-quality
  gap, so traced it to source instead of scoping S6e on it: `resolution_concordance_1626_1630`
  (every Tier O metric's input) was built **2026-09-17**, three `s4_corpus_paragraph_predictions`
  rebuilds behind (S6c's DP eliminating 777 `insufficient_entity_anchors` abstentions and the
  `axis_for_date` fix, both 2026-09-21/23). A sampled date showed the live prediction record was
  `status=predicted` while concordance still carried `paragraph_prediction_status=abstained` for
  every resolution that date.

  Re-ran `scripts/s4_resolution_concordance.py` (its own docstring: pure assembly, no new
  matching/alignment logic; 26s) then the full Tier O chain (`metrics_nihil_actum_invariant` →
  `metrics_separation_span_table` → `metrics_span_gap_map` → `s6c_severe_collapse_autopsy` →
  the new headroom diagnostic). **No algorithm or modeling work — a stale-cache fix alone moved
  the PLAN.md headline from 1,961/11,644 = 16.8% to 8,015/11,644 = 68.8% of ceiling**, clearing
  the **Global, primary criterion (≥50%)** outright (stretch ≥75% not yet met, gap 718). Solid
  days 221 → 693/1,594. Global spans@30: gap=2 now has 4 spans / 177 days (was 0/0) — short of
  the ≥6-spans/≥180-days criterion but close; gap=0/1 still 0/≤1 spans. `severe_collapse_implicated`
  stays `False`. Recorded via `svz.py metric`/`svz.py decision` (2026-09-23 "`resolution_concordance_1626_1630`
  was stale, gating the entire Tier O separation baseline"). Full test suite and `data_io.check`
  clean; registered `metrics_weak_separation_headroom_diagnostic` in `data_manifest.toml`.

  Re-run on fresh data: `weak_separation` days dropped 917 → 445, of which 82.2% are still
  `headroom_available` (mean headroom 0.65, down from the spurious 0.90) — the Group-B
  `position_scores` wiring planned above is still a live, real lever on the *smaller* remaining
  population, not obsoleted by this fix. **Next:** either push for the 75%-stretch / 180-day-span
  criteria via the already-scoped Group-B wiring, or bank this session's result — clear chat and
  re-run `svz.py review` before picking.

**Key shift in ground truth.** Pair verdicts are algorithm-dependent artefacts that expire whenever
the candidate generator changes — the structural reason the labelling loop never accumulated.
Boundary annotations are algorithm-independent facts, yield `K_e − 1` labels per day instead of one,
and merge with the 245 upstream `res_start` records. **Boundaries, not verdicts, from here on.**

**Deferred:** role-typed entity overlap; structured LLM judge redesign (measure it first via D2);
TRIFECTA layering (reduced to its evaluation discipline only); entity-noise simulation.

---

## NEW Approach: Semantic & LLM-Assisted Resolution Alignment
<!-- doc-status: retired -->

Enriched resolutions represent concise editorial **summaries** (abstracts of decisions, attendees, petitions) while flat resolutions are **full early-modern Dutch transcriptions**. To leverage LLMs and dense semantics effectively without incurring prohibitive cloud costs or hallucination risks, a two-tier hybrid architecture is implemented:

### Option A — Bi-Encoder Dense Semantic Scoring (`alignment_embeddings.py`)

- **Concept**: Compute cosine similarity between enriched summaries and flat resolution full texts.
- **Integration**: In [build_alignment_new.py](build_alignment_new.py), dense semantic similarity is integrated directly into the Needleman-Wunsch sequence alignment cost matrix:
  $$
  \text{MatchScore} = (\text{IDF}_{\text{entity\_overlap}}) + (w_{\text{semantic}} \cdot \text{CosineSimilarity})
  $$
- **Unanchored Gap Bridging**: If a resolution lacks prominent named entities but shares high semantic similarity ($\ge 0.35$), the diagonal transition is permitted, allowing topical alignment across gap resolutions.
- **Backends**: Supports local HuggingFace transformers (`emanjavacas/GysBERT`), Ollama embeddings (`nomic-embed-text`), and sublinear word/character n-gram TF-IDF fallbacks.

### Option B — Targeted Local LLM Verification Judge (`alignment_llm_judge.py`)

- **Concept**: Use local Ollama (`qwen2.5-coder` or `llama3`) as a selective verifier and tiebreaker only on ambiguous or unanchored candidate pairs (~5–15% of the corpus).
- **Output**: Generates structured JSON verdicts (`match` / `no_match` / `uncertain`), confidence scores, and brief explanatory reasons.
- **Artifacts**: Populates `llm_decision`, `llm_confidence`, and `llm_reason` fields in `output/ground_truth_stratified_matches.parquet` and [output/verify_ground_truth.html](output/verify_ground_truth.html).

### Tiered Milestone Alignment & Continuation Stitching (`build_alignment_new.py`)

- **Milestone Anchoring**: Discovered that entity overlap ($\ge 2.0$ IDF weight) forms immovable sequence milestones (~99% precision). Bounded resolutions between two milestones in the same daily meeting session are interpolated with monotonic order preservation.
- **Three-Tier Confidence Classification**:
  - `Tier 1 (tier1_anchor)`: 5,725 pairs (42.9%) — Verified entity overlap milestones.
  - `Tier 2 (tier2_merged_page, tier2_interpolated, tier2_adjacent)`: 4,734 pairs (35.5%) — Multi-item page merges and bounded sequence interpolations.
  - `Tier 3 (tier3_head_template, tier3_tail)`: 2,883 pairs (21.6%) — Opening attendance formulas and tail resolutions for targeted review.
- **Page-Break Continuation Stitching**: Solved the folio-turnover splitting problem where a single resolution was split across two flat records (`resolution_k` + `resolution_{k+1}`) due to HTR page breaks. Automatically detects and stitches 610 split continuation fragments per meeting session.
- **Clean Ground Truth Benchmark**: Corrected mislabeled merged-page matches in [output/ground_truth_audited.json](output/ground_truth_audited.json), achieving **100.0% precision** on retained judged pairs in the backtest.
- **Fast Parquet Cache**: `prebuild_paragraph_resolution_map.py` pre-indexes paragraph-to-resolution IDs into `data/derived/paragraph_to_resolution.parquet`, eliminating 4.3 GB JSON re-parsing on startup.

### Performance & Memory Optimization: Enriched Date Window Confinement

- **Upfront Corpus Pruning**: When loading flat resolutions (`resolutions_flat.parquet`, 692K rows), alignment scripts ([build_alignment_new.py](build_alignment_new.py), [generate_alignment/build_alignment_artifacts.py](generate_alignment/build_alignment_artifacts.py), [align_resolutions.py](align_resolutions.py)) now automatically extract the bounding date range of the enriched dataset and confine flat resolutions upfront to $[ \text{min\_date} - 30\text{d}, \text{max\_date} + 30\text{d} ]$.
- **Impact**: Reduces in-memory flat resolutions from 692,156 rows to 11,754 rows ($\sim$98.3% reduction in memory and scanning overhead) while strictly observing pre-1678 calendar constraints via `pd.Period(..., freq="D")`.

### Interactive Alignment Exploration Notebook

- **Interactive Sandbox** ([notebooks/alignment_inspection.ipynb](notebooks/alignment_inspection.ipynb)):
  - Fast, zero-cost ($0.00) CPU evaluation using `AlignmentEmbedder(backend='tfidf')` and `build_alignment_new` sequence alignment.
  - Follows `data_io` standards for data resolution and window-pruned data loading.
  - Visualizes $N \times M$ cosine similarity heatmaps with overlaid Needleman-Wunsch alignment traces.
  - Generates side-by-side rich HTML comparison cards with entity and TF-IDF score breakdowns across random and target session dates.
  - Includes an opt-in, locally cached Ollama experiment on at most eight existing labeled pairs. It extracts structured event fingerprints from flat texts and compares those fingerprints with enriched summaries using TF-IDF.

### Execution Commands

```bash
# Option A only (Embeddings in Needleman-Wunsch alignment)
python build_alignment_new.py --use-embeddings --semantic-weight 2.0

# Small sample testing (e.g. first 5 dates or specific dates)
python build_alignment_new.py --max-dates 5 --use-embeddings --embedding-backend tfidf
python build_alignment_new.py --date 1626-01-02 --date 1626-01-03 --use-embeddings

# Option A + Option B (Embeddings + Local Ollama LLM Judge)
python build_alignment_new.py --use-embeddings --use-llm-judge --llm-model llama3
```

---

## Overview
<!-- doc-status: retired -->

**Inputs:**

- `data/LOC-annotations.json` — 1.3M location spans with character offsets & entity IDs
- `data/PER-annotations.json` — 2M person spans with character offsets & entity IDs
- `data/LOC-entities.json` — 2,459 place canonical names
- `data/PER-entities (1).json` — 8,076 person canonical names
- `data/resolutions_flat.parquet` — 692K resolutions with paragraph text

**Target period:** 1626-1630

**Outputs:**

- `data/training_pairs_loc_1626_1630_dedup.parquet` — 21K PLACE training records
- `data/training_pairs_per_1626_1630_dedup.parquet` — 13K NAME training records
- `models/gysberg_delegate_ner_loc/` — fine-tuned PLACE-only model
- `models/gysberg_delegate_ner_combined/` — fine-tuned PLACE+NAME model

---

## Phases
<!-- doc-status: retired -->

### Phase 1 — Data preparation ✅

**LOC training pairs** (`build_loc_training_pairs.py`):

```bash
uv run python build_loc_training_pairs.py
```

- Loads 1.3M LOC-annotations.json with character offsets
- Maps entity IDs to canonical names via LOC-entities.json
- Filters to 1626-1630 period (8,412 resolutions overlap)
- Creates 21K PLACE training records
- Output: `data/training_pairs_loc_1626_1630_dedup.parquet`

**PER training pairs** (`build_per_training_pairs.py`):

```bash
uv run python build_per_training_pairs.py
```

- Loads 2M PER-annotations.json with character offsets
- Maps entity IDs to canonical names via PER-entities.json
- Filters to 1626-1630 period (6,127 resolutions overlap)
- Creates 13K NAME (delegate) training records
- Output: `data/training_pairs_per_1626_1630_dedup.parquet`

### Phase 2 — Model training

**PLACE-only fine-tuning** (`finetune_gysberg_loc.py`):

```bash
uv run python finetune_gysberg_loc.py
```

- Fine-tunes emanjavacas/GysBERT on 21K place spans
- Uses 100-word truncation (conservative for 512 token BERT limit)
- Exact word-boundary matching only (no substrings)
- 70% train / 15% val / 15% test split by date
- Output: `models/gysberg_delegate_ner_loc/best-model.pt`
- Training: 10 epochs, batch size 16, learning rate 0.1, MPS acceleration

**Combined PLACE+NAME fine-tuning** (`finetune_gysberg_combined.py`):

```bash
uv run python finetune_gysberg_combined.py
```

- Fine-tunes GysBERT on 34K spans (21K PLACE + 13K NAME)
- Multi-class NER: labels are O, PLACE, NAME
- Same truncation, tokenization, and split strategy
- Output: `models/gysberg_delegate_ner_combined/best-model.pt`
- Training: 10 epochs, batch size 16, learning rate 0.1, MPS acceleration
- Corpus: 7,501 train + 1,384 dev + 1,214 test sentences

### Phase 3 — Evaluation

After training completes:

```python
from flair.models import SequenceTagger

# Load model
model = SequenceTagger.load("models/gysberg_delegate_ner_combined/best-model.pt")

# Test on sample
from flair.data import Sentence
sent = Sentence("Heinsius woonde in Amsterdam")
model.predict(sent)
for token in sent.tokens:
    print(f"{token.text} → {token.get_label('ner')}")
```

Expected output: `Heinsius` → NAME, `Amsterdam` → PLACE

### Phase 4 — Inference pipeline

For new resolutions (future work):

- Tokenize resolution paragraphs with 100-word truncation
- Run model predictions to extract PLACE and NAME spans
- Post-process: normalize whitespace, validate token boundaries
- Map canonical names back to entity IDs if needed

**Key implementation notes:**

- **Memory optimization**: Load only ~12K resolutions referenced in training pairs (98.2% reduction from full 692K)
- **BERT token management**: 100-word truncation ≈ 250-300 BERT tokens (safe margin below 512 limit)
- **Label matching**: Exact word boundaries only; no substring matching (prevents false positives like "dam" in "Amsterdam")
- **MPS acceleration**: Metal Performance Shaders on macOS; falls back to CPU for CRF layer
- **Date stratification**: Train/val/test split by calendar date ensures temporal coverage

Smoke test:

```bash
uv run python run_match.py \
  --ner ~/Downloads/annotations-unaggregated/annotations-layer_PER.tsv.gz \
  --out data/test_results.parquet \
  --year-min 1708 --year-max 1712 \
  --top-k 5
# Expected: ~20 000 spans, runtime < 30 s
```

Final checks:

1. `results.parquet` has column `cand_1` with no 100 % null column
2. Match rate (score_1 > 0.2) ≥ 30 % of spans within year range
3. Temporal gate works: no span with year 1780 matched to delegate active only 1620–1650
4. Multi-person: "Slicher ende Hop" → two rows in output

### Phase 6 — Notebook (`explore.ipynb`) ✅

- Load results, show score distribution histogram
- Match rate by year (line chart)
- Top unmatched spans (score_1 < 0.1) — candidates for new delegates
- Sample table: span + top-3 candidates with scores

---

## Pilot plan — session/date reconciliation
<!-- doc-status: retired -->

The current export/reconciliation work should be treated as a pilot, not a full rewrite. The goal is to test whether the available source material is sufficient to align enriched resolutions, flat resolutions, and session text well enough for manual comparison.

### Inputs to use in the pilot

- `republic_corpus` source archive: `sessions_json-2026-02-27.tar.gz`
- session index: `index/session_index_all.parquet`
- flat resolutions: `resolutions/resolutions_flat.parquet`
- enriched resolutions: `derived/enriched_resolutions_1626_1630_complete.json`
- annotation layers: `annotations/LOC-annotations.json`, `annotations/PER-annotations.json`, `annotations/ORG-annotations.json`
- existing overlap / matching outputs in `derived/` and `output/`

### Pilot scope

- Run only a few dates first, not the full period.
- Prefer one sparse date, one normal date, and one dense/messy date.
- Keep alignment recall-first: accept loose matches if they help review, but surface confidence and ambiguity.
- Use the session text as the reading context and the `reconciled` sheet as the comparison view.

### Working hypothesis

- Session IDs and resolution IDs are close enough that a relaxed local window such as `session-xxxx-num-##` to enriched resolution `##..##+2` is useful as a starting alignment.
- Offsets and paragraph-level entity spans are the strongest clues for reconciliation.
- Entity order is only a weak signal and should not be used as a hard requirement.

### Pilot checks

1. Verify that each sampled date has a populated `sessions` row with readable session text.
2. Verify that `enriched` and `flat` both contain all resolutions for that date.
3. Inspect `reconciled` rows for the same date and check whether the relaxed window produces plausible pairs.
4. Confirm that `org_names` are resolved before treating organization comparisons as reliable.
5. Record where offsets, tag text, or recurring entities actually explain the reconciliation.

### Exit criteria

- If the pilot shows that session text, offsets, and a loose local window are enough to explain most pairs, proceed with the same approach for more dates.
- If the pilot shows repeated mismatches, tighten the pairing logic or switch to a different grouping key before scaling.
- Do not broaden the scope until the pilot produces a stable comparison pattern on the sampled dates.

---

## Track B — Approaches from `huygens_name_index/names`
<!-- doc-status: future -->

**Source**: `/Users/rikhoekstra/develop/huygens_name_index/names`

This is a mature, production-tested package originally built for the *Namenindex*
disambiguation task: matching free-text person names in archival sources to a
person authority register. The problem is structurally identical to ours, but at
different scale and with a different retrieval model (pairwise scoring rather than
vector search). The codebase embodies many years of practical experience with Dutch
historical naming conventions and should be treated as a knowledge source rather
than a drop-in replacement.

### Package components

#### `soundex.py` — Dutch phonetic normalization

`soundex_nl(s, length=-1, group=1|2)` reduces a name token to a phonetic key by
applying an ordered sequence of regex substitutions that encode Dutch spelling
conventions:

- Prefix stripping: `'s-`, `'t `, `d'`, `l'` etc.
- Spelling normalization at token level:
  - `ij`/`y`/`eij`/`ey` → `i` (all treated identically)
  - `ouw`/`auw`/`au`/`ou` → `o`
  - `ck`/`cks`/`kk`/`c` → `k`
  - `sch` (medial) → `s`
  - `ph`/`v`/`w`/`ff` → `f`
  - `ch` → `g` (in clusters like `ngh`, `gg`, `gh`, `ng`)
  - Historical suffixes: `-en` after consonant, final `-e` after consonant → dropped
  - `szoon` → `sz`, `-naar` → `-na`
  - French endings: `-ecque` → `-ek`, `-eille` → `-elle`
- Vowel folding at digit level: `ah/ae/a → 1`, `ee/eh/e → 2`, `eij/ey/ij/ie/y → 3`,
  `oh/oo/oe → 4`, `uu/uh → 5`, `ouw/au → 6`, `uy/uij/ui → 7`
- Two strictness levels: `group=2` is close to actual phonetics; `group=1` is more
  aggressive (collapses all vowels to `.`, strips leading `h`, merges `b/p`, `d/t`).

`soundexes_nl(s, filter_stop_words=True)` tokenises a full name string and returns
a list of phonetic keys, optionally filtering out stopwords (tussenvoegsels etc.)
before encoding.

**Relevance**: The current `char_wb` n-gram TF-IDF conflates e.g. "Wassenaer" and
"Wassenaar" only by shared bigrams, losing weight to suffix variation. `soundex_nl`
collapses both to the same key outright. It could serve as (a) an additional index
dimension alongside the TF-IDF vectors, (b) a pre-filter to narrow candidates before
scoring, or (c) a component in a reranker.

#### `common.py` — Name vocabularies and stopwords

The package maintains curated Dutch-name vocabularies:

- `TUSSENVOEGSELS`: `van`, `de`, `den`, `der`, `des`, `di`, `la`, `le`, `ten`,
  `thoe`, `tot`, `in 't`, `of`, `en`, `het` — these are also valid tussenvoegsels in
  Republic resolutions.
- `VOORVOEGSELS` (title prefixes): `dr`, `mr`, `prof`, `jhr` etc.
- `POSTFIXES` (patronymic): `azn.`, `cz.`, `Hz.`, `Wzn.`, `jr.`, `sr.`
- `TERRITORIALE_TITELS`: `graaf`, `baron`, `heer`, `prins`, `jonkheer` etc.
- `ROMANS`: Roman numerals (dynastic/numeral suffixes) treated as opaque tokens.
- `STOP_WORDS` = union of all the above + `PREFIXES`.
- `remove_stopwords(s)` strips all of the above from a string in one pass.

`to_ascii(s)` handles Unicode normalisation, accented characters, and HTML entities
(relevant for OCR output).

**Relevance**: The current `preprocess.py` strips some titles but does not have an
exhaustive tussenvoegsel list. Adding `remove_stopwords` before TF-IDF indexing
would prevent "van", "de", "den" etc. from inflating IDF weights or causing false
positives when a query has a different tussenvoegsel than the indexed pattern.
The `POSTFIXES` list handles patronymic suffixes (azn., Cz.) common in 18th-century
notarial/resolution text that the current preprocessor does not handle.

#### `similarity.py` — Composite weighted similarity

`average_distance(l1, l2, distance_function)` computes a bipartite best-match
average over two lists of word tokens (e.g. the words in a surname), with a penalty
of 0.8 per unmatched word in the longer list. This gracefully handles:

- Compound surnames split at a hyphen: `["Coehoorn"]` vs `["Coehoorn", "Goslinga"]`
- Spelling variants where one form has one token and the other has two
- Missing tussenvoegsels

`Similarity.ratio(n1, n2)` (requires two `Name` instances) combines five components
with learned weights:

| Component                              | Weight | What it measures                  |
| -------------------------------------- | ------ | --------------------------------- |
| Normal-form Levenshtein                | 5.0    | Character similarity of full name |
| Soundex of normal form                 | 8.0    | Phonetic similarity of full name  |
| Soundex of*geslachtsnaam*            | 10.0   | Phonetic similarity of surname    |
| Levenshtein of*geslachtsnaam* tokens | 10.0   | Direct surname character distance |
| Initials Levenshtein                   | 2.0    | Initial string similarity         |

When one name is in initials form, the weights shift: soundex and initials become
dominant, direct character distance shrinks. This is directly applicable since many
NER spans have the form "J. van Wassenaer" or "A.H. de Vrij".

**Relevance**: The current TF-IDF scorer has no concept of surname vs. initial vs.
tussenvoegsel — "J. de Vrij" and "Jan de Vrij" are not obviously closer to each
other than to "J. de With". `Similarity.ratio` encodes exactly this structural
awareness. It is most useful as a **reranker** on the top-k TF-IDF shortlist, since
computing it pairwise over the full delegate set would be too slow.

#### `name.py` — Structured name parsing

The `Name` object stores a name as an XML element tree with typed constituents:
`preposition`, `voornaam`, `intrapositie`, `geslachtsnaam`, `postpositie`,
`territoriale_titel`. It exposes methods: `geslachtsnaam()`, `initials()`,
`guess_normal_form()`, `geslachtsnaam_soundex()`, `contains_initials()`.

**Relevance**: Full `Name` parsing would allow truly structural comparison. However:

- It depends on `lxml` and an XML-based internal representation — heavy for bulk
  NER processing.
- `guess_normal_form()` requires some structure to be present; on raw NER spans
  (which are unstructured strings) it would need to fall back to the free-text
  constructor, which relies on heuristic guessing.
- The `from_args` path (where constituents are known) is reliable; the
  `from_string` path (parsing a raw span) is not.
- In practice it is more maintainable to extract just the surname component by
  stripping known tussenvoegsels/titles from the span, rather than instantiating
  `Name` objects.

### Proposed Track B design

Three graduated improvements, in increasing complexity:

**B1 — Preprocessing improvements** (low risk, low effort)

- Apply `remove_stopwords` from `common.py` to both the query span and the indexed
  patterns before TF-IDF scoring. This removes tussenvoegsels from the comparison
  surface.
- Apply `to_ascii` for accent/OCR normalisation (already partially done in
  `preprocess.py` but not exhaustively).
- Add `POSTFIXES` stripping (azn., Cz., Hz.) to `clean_span`.

**B2 — Soundex as secondary index dimension** (medium effort)

- Add a third TF-IDF vector per delegate based on `soundexes_nl(pattern, group=2)`.
- Combine: `score = 0.5 × sim_char + 0.3 × sim_word + 0.2 × sim_soundex`.
- The soundex index catches spelling variants (ij/y, ck/k, ae/a) that the char
  n-gram index underweights when the variant differs in length.

**B3 — Structural reranker on top-k** (medium effort, highest expected gain)

- After TF-IDF retrieves top-20 candidates, re-score each candidate against the
  query using `average_distance` on the *geslachtsnaam* component:
  1. Strip tussenvoegsels and initials from both query and candidate to isolate the
     surname tokens.
  2. Compute `average_distance(query_surname_tokens, cand_surname_tokens, levenshtein_ratio)`.
  3. If either contains initials, apply the soundex normal-form score as a tiebreaker.
  4. Re-rank and return top-k by reranked score.
- This avoids instantiating `Name` objects; it uses only the free functions
  `average_distance`, `levenshtein_ratio`, `soundexes_nl`, and `remove_stopwords`.

### Caveats and open questions

- **Dependency**: `similarity.py` imports the `Levenshtein` package (not
  `python-Levenshtein`; the API may differ). `rapidfuzz.distance.Levenshtein.normalized_similarity`
  is a drop-in replacement that is already in the project dependencies.
- **lxml**: `name.py` requires `lxml`. Not worth adding as a dependency if we only
  use the free functions from `similarity.py`, `soundex.py`, and `common.py`.
- **Weight calibration**: The weights in `Similarity.ratio` (5/8/10/10/2) were
  tuned on a different corpus and index. They should be treated as a starting point
  and re-evaluated against the benchmark once B3 is implemented.
- **`soundex_nl` group 1 vs 2**: Group 1 collapses too aggressively for a precision
  task (many false positives). Group 2 is the right default for Track B.
- **Stopword collision**: Stripping *all* stopwords from both query and index risks
  losing distinguishing tussenvoegsels for delegates whose surnames are themselves
  stopword-like (e.g. "Van" as a surname element). Apply stopword removal only for
  scoring, not for display or identification.

---

## Track C — Structured span matching built on `fuzzy-search`
<!-- doc-status: future -->

### Motivation

The `fuzzy-search` package (Marijn Koolen, PyPI v2.7.1) was designed specifically
for Dutch Republic resolutions with OCR/HTR errors and historical spelling
variation. Its own documentation uses the exact texts and context phrases
(PRAESIDE, PRAESENTIBUS, "Den Heere Bentinck", "De Heeren ...") that we work
with. Building Track C on top of it avoids re-implementing character skip-gram
indexing, Levenshtein scoring, and phrase-variant logic from scratch.

Key capabilities that map to our problem:

| `fuzzy-search` feature   | Track C use                                                                                                               |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `FuzzyTokenSearcher`     | Token-level matching with character skip-grams inside tokens — exactly the two-level model                               |
| Phrase`variants`         | All historical spellings of a context phrase as a single logical entry                                                    |
| Phrase`distractors`      | Phrases that look like a context word but are actually part of a name (e.g. "de Heer" as title vs "De Heer" as a surname) |
| Phrase`label`            | Tag context type:`quantifier`, `honorific`, `role`, `title`, `postfix`                                          |
| Phrase`metadata`         | Store quantifier arity (singular/plural), role category, year range                                                       |
| `PhraseMatch.offset`     | Locate the context phrase within the span; the name tokens are what remains                                               |
| `levenshtein_similarity` | First-pass similarity score for the context match                                                                         |

### What the context component does

A NER span like "capitein Van Aerssen" or "zijne excellentie monsigneur Heinsius"
is a **name expression** with two separable parts:

1. **Context component**: honorifics, roles, titles, quantifiers that surround the
   name — "heere", "heeren", "ambassador", "capitein", "majoor", "monsigneur",
   "zijne excellentie", "jonkheer", "grave", etc.
2. **Name component**: the person name proper — voornaam (possibly abbreviated or
   absent), tussenvoegsel, geslachtsnaam, possibly a compound surname.

The context component serves four distinct functions:

| Function                        | Example                                                        | Implication for matching                                            |
| ------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------- |
| **Quantification**        | "heere" → 1 name; "heeren" → multiple names                  | Pre-split: extract one name vs. multi-person split                  |
| **Role disambiguation**   | "ambassador Van Aerssen" vs "delegate Van Aerssen" (same year) | Use role to break ties between contemporaries with the same surname |
| **Role discovery**        | "zijne excellentie monsigneur X" (not in index)                | Record (X, role, year) as new attribute; enrich delegate record     |
| **Career reconstruction** | "capitein Y" (1710) → "majoor Y" (1720)                       | Infer promotion; longitudinal enrichment                            |

### The two-level matching model

`FuzzyTokenSearcher` already implements this hierarchy:

- **Level 1 — character**: within each word token, character skip-grams absorb
  spelling variation (OCR errors, historical orthography, abbreviations).
  This is the same level as `soundex_nl` + Levenshtein in Track B.
- **Level 2 — token sequence**: phrases are matched as sequences of word tokens;
  a fuzzy token match requires enough tokens to match at the character level,
  allowing for missing tokens (gap), token insertions, and transpositions.
  This is the element-level sequence edit distance described in the user request.

The substitution cost at level 2 is derived from the character-level similarity
at level 1 — not from exact token equality — which is precisely the generalised
edit distance model we need.

### Proposed pipeline

```
Raw NER span  (or raw resolution text for full-text mode)
    │
    ▼
[Step 1] Context detection via FuzzyTokenSearcher
    Build a phrase model of context expressions with labels:
      - quantifiers: "heere", "den heer", "de heer", "heeren", "de heeren"
      - honorifics:  "monsigneur", "zijne excellentie", "haar hoogmogende"
      - titles:      "jonkheer", "grave", "graaf", "baron", "hertog"
      - roles:       "ambassador", "ambassadeur", "resident", "capitein",
                     "majoor", "kolonel", "admiraal", "raadpensionaris",
                     "pensionaris", "secretaris", "griffier", "ontvanger"
      - academic:    "mr.", "meester", "doctor"
      - postfixes:   "azn.", "cz.", "hz.", "jr.", "sr."
    Register known ambiguous strings as distractors (e.g. "de Heer" when it
    is used as a surname rather than a title).
    Run FuzzyTokenSearcher over the span; collect PhraseMatch objects.
    │
    ▼
[Step 2] Name extraction
    Remove context token offsets from the span string; what remains is the
    name component.  Normalise: to_ascii, lowercase, detect tussenvoegsels,
    identify initials.
    If quantifier label == plural → run multi-person split before Step 3.
    │
    ▼
[Step 3] Candidate retrieval (unchanged)
    Existing TF-IDF shortlist (top-20) + temporal gate.
    │
    ▼
[Step 4] Hierarchical reranking via FuzzyTokenSearcher (reverse mode)
    Build a second FuzzyTokenSearcher whose phrase model is the top-20
    candidate name strings.  Run it against the extracted name component.
    This gives a token-sequence + character-level similarity score for each
    candidate.  Combine with Track B soundex / Levenshtein reranker if active.
    │
    ▼
[Step 5] Context-assisted tie-breaking
    If ≥ 2 candidates remain close in score and a role context was detected:
      - Filter candidates whose known roles are incompatible with the role.
    If no role context: fall through to top-1 by score.
    │
    ▼
[Step 6] Attribute enrichment (optional)
    For matched spans that carry a role/title context token, emit a
    (cons_id_str, delegate_id, role_label, year) record into a side table.
    For unmatched spans with a role context, emit a discovery record for
    manual review.
```

### Phrase model structure

```python
context_phrases = [
    # quantifiers — singular signals one name follows
    {"phrase": "den heere",  "variants": ["de heer", "den heer", "den hr"],
     "label": "quantifier", "metadata": {"arity": "singular"}},
    {"phrase": "de heeren",  "variants": ["de heeren", "de hren"],
     "label": "quantifier", "metadata": {"arity": "plural"}},
    # honorifics
    {"phrase": "zijne excellentie", "variants": ["sijne excellentie", "s.e."],
     "label": "honorific", "metadata": {}},
    {"phrase": "monsigneur",
     "variants": ["monseigneur", "monsr.", "mons."],
     "label": "honorific", "metadata": {}},
    # roles — note: "raadpensionaris" is also a function in the canonical name
    {"phrase": "ambassadeur",
     "variants": ["ambassador", "ambassdr."],
     "label": "role",
     "distractors": ["ambassade"],  # avoid matching place names
     "metadata": {"role_category": "diplomatic"}},
    {"phrase": "capitein",
     "variants": ["capiteyn", "captn.", "cap."],
     "label": "role", "metadata": {"role_category": "military"}},
    # … extend from corpus frequency analysis
]
```

### Relationship to existing components

| Component                                                       | Role in Track C                                        |
| --------------------------------------------------------------- | ------------------------------------------------------ |
| `preprocess.clean_span`                                       | Upstream normalisation; extend to preserve offset info |
| TF-IDF matcher (`match.py`)                                   | Step 3 retrieval; unchanged                            |
| Track B (`soundex_nl`, `levenshtein_ratio`)                 | Optional scoring layer inside Step 4 token similarity  |
| `TUSSENVOEGSELS`, `TERRITORIALE_TITELS` (common.py)         | Seed vocabulary for context phrase model               |
| `fuzzy_search.FuzzyTokenSearcher`                             | Steps 1 and 4 — core matching engine                  |
| `PhraseMatch.offset`, `.label`, `.levenshtein_similarity` | Context classification and name boundary detection     |

### Implementation order

1. **Install**: `uv add fuzzy-search` (already a project dependency candidate).
2. **Build context phrase model**: start from TUSSENVOEGSELS / TERRITORIALE_TITELS
   in `common.py`; add roles and quantifiers from the frequency table of NER
   span prefixes.
3. **`split_span(text, searcher) → (context_matches, name_string)`**: thin wrapper
   around `FuzzyTokenSearcher.find_matches`; returns `PhraseMatch` list + residual
   name string.
4. **Wire into `match.py`**: call `split_span` before TF-IDF query; pass name
   component to TF-IDF; pass context matches to Step 5 tie-breaker.
5. **Benchmark**: run against Track A benchmark (divergence bands); compare top-1
   accuracy with and without Track C active.
6. **Attribute table**: once matching is stable, enable Step 6 enrichment.

### Open questions

1. **Context vocabulary completeness**: what fraction of NER spans contain a
   detectable context prefix? Requires a frequency scan of span-initial tokens.
2. **Distractor coverage**: "de Heer" is both title and surname. How many surname
   tokens also appear in the context vocabulary? Need a collision analysis.
3. **Quantifier → multi-person split interaction**: plural quantifier handling
   ("heeren A, B en C") is already partially in `preprocess.split_multi_person`.
   Confirm it fires before Step 3 so each name gets a separate TF-IDF query.
4. **`FuzzyTokenSearcher` config for name matching (Step 4)**: the default
   `ngram_size=2, skip_size=2` is very exhaustive; for short name tokens (2–8
   chars) `ngram_size=2, skip_size=1` may be sufficient and faster.
5. **Role-based disambiguation threshold**: when does the role confidently break a
   tie vs. when is the role token itself an OCR artifact? A minimum
   `levenshtein_similarity` threshold on the context match (e.g. 0.75) should gate
   its use for disambiguation.
6. **Career inference scope**: whether role-change records feed back into the
   delegate index (active learning) or stay as a read-only enrichment table is an
   architectural decision deferred to after Step 5 benchmark.

---

## Entity Resolution Fix (persons/orgs/places, `build_alignment_new.py`) ✅
<!-- doc-status: active -->

Partial implementation of Track B/C's "candidate shortlist, then verify" design,
scoped to the 1626-1630 window. Plan: `/Users/rikhoekstra/.claude/plans/short-resolutions-is-fine-calm-iverson.md`.

**Findings that changed scope mid-implementation**: `align_resolutions.py`
(the file originally targeted for an orthography fix) turned out to be
orphaned -- its output is consumed by nothing except itself. The live
pipeline is `build_alignment_new.py`, which had two bugs *upstream* of
orthography, both the same pattern -- an id-reference silently used as if it
were already a name string:

- **Persons**: enriched `persons`/`president_ids`/`deputy_ids` are `Id_persoon`
  ids, not names. `resolve_enriched_entities` already had the correct-resolution
  code path (via a `persons_info` lookup) but it was never actually invoked at
  either live call site -- raw ids passed straight through.
- **Institutions**: enriched `institutions` holds `ID_instelling` ids (a
  register at `~/GNB_artikel/data/processed/instituten_lookup_cleaned.csv`,
  now copied to the warm tier and registered as `instituten_lookup_cleaned`),
  but the code resolved them against `ORG-entities.json` (`O0000002`-style
  ids) -- a disjoint id space that never matched, silently falling back to the
  raw integer.

Both fixed by wiring in the correct lookup (`load_persons_info_lookup`,
new `load_institution_names`) at both call sites. Verified directly:
`institutions=['14']` now resolves to `'Hof van Holland en Zeeland'` (was
`'14'`); `persons=['791967']` now resolves to `'Huygen, Rutger heer van Clarenbeek'` (was `'791967'`).

**Orthography fix** (the original ask): `matched_entity_names` did a literal
substring check against the full canonical dictionary. `fuzzy_search.FuzzyTokenSearcher`
over the full ~10,876-name LOC+PER+ORG dictionary does not scale (benchmarked:
2,459 LOC names alone did not finish indexing in 60s). Built
`build_entity_surface_matches.py` instead: candidate shortlist per flat
resolution from `LOC-/PER-annotations.json`'s `resolution_id -> entity_id`
links (offsets ignored -- documented ~50% wrong elsewhere in this repo, so
used only as *which entities to check*, never *where*), confirmed against
each resolution's real text via exact substring first, `rapidfuzz.fuzz.partial_ratio`
fallback (threshold 85) only for misses. Cached as the
`entity_surface_matches_1626_1630` dataset (18,698 rows: 11,330 exact + 7,368
fuzzy, built in 79s) and wired into `matched_entity_names` as an additive
lookup (falls back to literal substring for anything outside the cache).
11/11 spot-checked fuzzy matches against full resolution text were correct
historical spelling variants (e.g. "Vlaenderen"/Vlaanderen, "Carleton"/Charleton,
"Maseick"/Maaseik, "Sevenbergen"/Zevenbergen, "groeninge"/Groningen).

**Known limitation, not fixed here**: the pipeline's headline tier/confidence
stats are driven mainly by pre-built Excel overlap tables
(`place_overlap_1626_1630.xlsx` etc., built by `build_per_overlap.py` and
similar), checked *before* the text-fallback this step improves -- confirmed
`build_per_overlap.py` has the same literal-substring limitation. A 100-date
smoke test's aggregate stats were unchanged before/after for this reason; the
fix is verified correct at the function level (see above) but a full
pipeline-level confidence-distribution shift would need those Excel builders
audited too -- a natural next step, not attempted here.

**Explicitly deferred**: PER-entities.json (`P0xxxxxx`) id-space unification
with `Id_persoon` (not needed -- `Id_persoon` is already the id the enriched
pipeline and `persoon_functie_sanitized.csv` use); the `raa_nw` MySQL database
(mentioned once in this file, never otherwise documented -- flagged as a gap,
not accessed).

---

## Step 1 — N-status gap diagnostic (`analyze_n_status_gaps.py`) ✅
<!-- doc-status: active -->

Full detail in `docs/CANDIDATE_SCORING_AND_CONCORDANCE.md`. The doc's own
stated order gates the resolution-level concordance assembly on this step
(and Step 2, candidate scoring for `A`/`X` rows) reporting results first, so
this ran before any concordance-assembly work.

Headline finding, at real scale (3,197 of the 4,916-row `session_date_status_1626_1630`
ledger, 65%, are `N`-status -- no HTR candidate within the current +/-1-day
window): **2,444 rows (49.7% of the entire ledger) have no HTR session for
their inventory anywhere within +/-14 days.** This is a structural coverage
ceiling, not a matching-quality gap -- concretely answers "100% may not be
attainable": realistic full-corpus concordance coverage is well under 100%
regardless of how good the matching gets, and roughly half the ledger should
be expected to close as `missing_htr` rather than resolved. The remaining
753 rows (23.6% of `N`-rows) recover within +/-14 days, front-loaded toward
close offsets (+/-2 days alone: 174 rows) -- a modest window widen (+/-3 to
+/-7, not the full +/-14 tested) is a plausible, bounded-payoff follow-up,
not yet implemented. No weekday concentration (flat 14.1-14.8% every day),
so no recess-calendar story to chase.

Two latent bugs fixed in the (previously unrun) script: `.dt.dayofweek`
accessor on a `Period`-dtype `Series`, and an offset-search order bug
(`EXTRA_OFFSETS` iterated far-to-near, so "nearest recovery offset" wasn't
actually nearest -- fixed to sort by `(abs(offset), offset)`).

## Step 2 — Candidate scoring prototype for `A`/`X`-status rows (7 rows) ✅
<!-- doc-status: active -->

Full detail in `docs/CANDIDATE_SCORING_AND_CONCORDANCE.md`. Built
`scripts/s4_candidate_scoring.py` (`score_candidates`/`score_ledger_row`,
reusing `calculate_idf_weights`, existing overlap lookups, and
`AlignmentEmbedder` tfidf backend), `notebooks/candidate_scoring_prototype.ipynb`,
and `tests/test_candidate_scoring.py`. Produces ranked suggestions for human
review, never auto-selects.

Verified against the real 7 rows: 6/7 top candidates correct (2 of those
were nihil actum rows correctly surfaced as non-matches, per user
confirmation those are parsing artifacts to skip, not scoring failures).
The 1 wrong pick (`session-4562|1629-05-12`) was traced to content that is
genuinely absent from that inventory's HTR text (confirmed via regex,
substring, and fuzzy search for the enriched text's key name) -- the
resolution-level analogue of Step 1's structural coverage gap, not a
scorer defect.

Found a clean, data-driven separator: every correct top candidate had
`entity_overlap_score` in `[30.7, 107.1]`; every problem case (nihil actum
or missing content) had exactly `0.0`, no borderline values. Added a
`low_confidence` flag (`entity_overlap_score <= 0.0`) to both scoring
functions on that basis -- caveated in the doc as an n=7 floor to revisit
once `?`/`-1`/`+1` rows are scored.

**Step 3** (done, 17 Sep 2026): extended candidate scoring to `?`/`-1`/`+1`
rows using the same module -- `scripts/s4_candidate_scoring.py` now unions
`previous_day_session_ids`/`next_day_session_ids` for ambiguous `?` rows via
a new `candidate_session_ids` helper, and looks up the single relevant
column for `-1`/`+1`. `low_confidence` floor applied as-is (not re-derived).
First eyeball pass against the real 603 rows (17 Sep 2026) found 146/610
(23.9%) candidate rows have a formulaic `"Nihil Actum"` enriched date with no
real content to match -- scoring them anyway produced spurious top picks
from real HTR content on that date. Fixed: `is_nihil_actum()` added to
`scripts/s4_candidate_scoring.py`, `score_ledger_row` now abstains (`[]`)
before scoring these; 12/12 tests passing. Of the remaining rows, roughly
1 in 7 has a genuine, correctly-ranked HTR match; the rest are structurally
missing HTR, consistent with Step 1. Re-checked the `entity_overlap_score`
floor against a stratified eyeball of the `?`/`-1`/`+1` rows (17 Sep 2026):
scores under 5 had no good candidates, so `MIN_CONFIDENT_ENTITY_OVERLAP` was
raised from `0.0` to `5.0` in `scripts/s4_candidate_scoring.py` (tests
updated, 12/12 passing). Full detail in `docs/CANDIDATE_SCORING_AND_CONCORDANCE.md`.

**Step 3b -- window-widen follow-up (built and run 17 Sep 2026)**: implements
Step 1's "modest window widen (+/-3 to +/-7 days)" suggestion.
`analyze_n_status_gaps.py` gained `direct_session_ids` (offset -> actual HTR
session ids, not just a recovery flag), `nearest_recovery_candidates`, and a
`WIDE_WINDOW_OFFSETS` constant capped at +/-7 days (the front-loaded
523/753-row band, not the full +/-14 the diagnostic tested).
`scripts/s4_candidate_scoring.py`'s `score_ledger_row` gained a `candidate_ids`
override; `scripts/s4_candidate_scoring_batch.py` now also scores every
`N`-status row recoverable within that window into the same
`s4_candidate_scoring_predictions` dataset.

**Real-corpus result**: 523 recoverable `N` rows fell in the +/-7 band; 48
are nihil actum (correctly reclassified out of `missing_htr`/`uncertain`);
the other 475 all scored `entity_overlap_score == 0.0` -- **zero** cleared
the `5.0` confidence floor. Verified this is the same 0-or->5 bimodality
Step 3 already found for the `A`/`X`/`-1`/`+1`/`?` set (460/464 there were
also exactly `0.0`), not a lookup bug (candidate session ids checked present
in `paragraph_axis_1626_1630`, `volgnr`/`enriched_id` key formats checked to
already match). **Conclusion: the window-widen improves status-classification
accuracy but unlocks zero new resolved HTR sessions on this corpus** --
entity overlap is not a useful signal at +/-2..+/-7 days, only at +/-1.
Day-level effect: `resolved_auto` unchanged at 1,113; `nihil_actum` 146 ->
194; `uncertain` 1,213 -> 1,165 (still `uncertain`, but 475 of those rows are
now correctly tagged `resolution_source: "candidate_scoring_low_confidence"`
instead of implying they were never scored -- a real mislabeling bug found
and fixed in `resolve_row` while verifying this run). Resolution-level
concordance: `resolved_auto` unchanged at 13,528; `missing_htr` 5,481 ->
5,465 and `nihil_actum` 124 -> 127 (better-ranked candidate now available
for some multi-inventory dates); `cross_day_shift` still 0, as expected given
zero confident wide-window matches. Full writeup:
`docs/CANDIDATE_SCORING_AND_CONCORDANCE.md`. Tests: `tests/test_n_status_gaps.py`
(new) + additions to `tests/test_candidate_scoring.py` and
`tests/test_day_status_resolution.py` (206 total, all passing).

Follow-up candidates from this diagnostic: (1) done 17 Sep 2026 -- see
"Window-widen non-entity-signal follow-up" below (dense TF-IDF tested and
rejected; the actual fix was closing an entity-matching gap, not adding a
non-entity signal); (2) whether the 16-row resolution-level `missing_htr`
shift and 3-row `nihil_actum` shift should be spot-checked by hand before
trusting `select_day_status`'s rank-based pick across overlapping
inventories at this larger scale -- still not started.

---

## HOE Classifier (`hoe_classify.py`) ✅
<!-- doc-status: sidelined -->

### Motivation

The HOE annotation layer (4.2 M rows, 1.2 M distinct forms) carries the
**context component** of NER spans: honorifics, roles, titles, and quantifiers
that immediately precede or surround delegate names. Understanding this layer
serves two purposes:

1. **Quantifier detection** — "heere" → singular name follows; "heeren" → multi-
   person split before matching.
2. **Role disambiguation** — "ambassadeur Heinsius" vs "raadpensionaris Heinsius"
   (same surname, different contemporaries) — the role breaks the tie.

### Architecture

Two-pass offline classifier:

**Pass 1 — keyword match** (`classify_keyword`): exact substring match against
seed strings per category. O(n seeds) per form, runs once over the ~1.2 M
distinct forms during pre-classification.

**Pass 2 — fuzzy fallback** (`classify_fuzzy`): `rapidfuzz.fuzz.token_set_ratio`
against category centroids. Chosen because it sorts+deduplicates tokens before
scoring → word-order invariant and handles interjected stopwords (e.g.
"extraordinaris envoyé aan het hof van" ≡ "envoyé extraordinaris") without
exhaustive skip-gram indexing.

At match time: dict lookup on `data/hoe_vocab.parquet` → O(1).

### 16 categories

| Category                   | Occurrences | Distinct forms | Purpose                                    |
| -------------------------- | ----------- | -------------- | ------------------------------------------ |
| `other`                  | 1 317 577   | 574 490        | unclassified; needs further seed expansion |
| `administrative`         | 675 807     | 122 599        | griffier, secretaris, pensionaris, etc.    |
| `diplomatic`             | 364 987     | 61 698         | ambassadeur, resident, consul, envoyé     |
| `sovereign`              | 355 684     | 85 082         | coninck, keyser, prins, grave, lord, duke  |
| `military`               | 344 683     | 81 478         | capitein, colonnel, generael, admirael     |
| `territorial_title`      | 180 484     | 29 188         | heere van, heer van                        |
| `collective_social`      | 155 227     | 45 711         | ingesetenen, crediteuren, gedeputeerden    |
| `quantifier_singular`    | 143 564     | 42 425         | den heere, de heer, den hr                 |
| `quantifier_plural`      | 143 026     | 33 421         | de heeren, de heren                        |
| `maritime_military`      | 139 095     | 38 901         | schipper, officieren, matroosen            |
| `honorific_majesteit`    | 127 783     | 19 848         | sijne majesteyt, haar mat                  |
| `personal_status`        | 109 986     | 35 902         | weduwe, wijlen, coopman, erffgenamen       |
| `states_general_formula` | 76 304      | 9 597          | haar hoogh mogende extraordinaris envoyé  |
| `ecclesiastical`         | 53 045      | 17 280         | predicant, bisschop, abt                   |
| `honorific_excellentie`  | 46 220      | 2 711          | syn excie, zijne excellentie               |
| `honorific_hoogheid`     | 14 817      | 1 468          | zijne hoogheid, hare hoogheid              |

### Outputs

| File                              | Rows       | Columns                                                                       |
| --------------------------------- | ---------- | ----------------------------------------------------------------------------- |
| `data/hoe_vocab.parquet`        | 1 201 799  | `normalized_text`, `category`, `method`, `token_set_score`, `count` |
| `data/hoe_category_counts.json` | 16 entries | `{category: {total, distinct}}`                                             |

### Re-run

```bash
uv run python hoe_classify.py [--hoe PATH] [--threshold INT] [--out PATH] [--summary PATH]
```

Default input: `~/Downloads/annotations-unaggregated/annotations-layer_HOE.tsv.gz`

### Known limitation

`other` bucket is ~1.32 M rows (31 % of total) — the largest single category.
Priorities for reduction:

- Run frequency analysis on top-100 `other` forms and add seeds
- Merge with `abbrd.functienaam` values (see next section) to auto-generate
  administrative seeds from the authoritative register

---

## Additional data sources
<!-- doc-status: active -->

### `abbrd` — Authoritative delegate biographical index

**Location**: `/Users/rikhoekstra/develop/streamlit_worksheet/abbrd_minimal.parquet`

**Schema** (9 698 rows):

| Column              | Type  | Notes                                                        |
| ------------------- | ----- | ------------------------------------------------------------ |
| `fullname`        | str   | Canonical surname, given name (e.g.`"Aa, Willem van der"`) |
| `geboortejaar`    | float | Birth year (many nulls)                                      |
| `overlijdensjaar` | float | Death year (many nulls)                                      |
| `beginjaar`       | float | First year active                                            |
| `eindjaar`        | float | Last year active (nulls = still active)                      |
| `functienaam`     | str   | Semicolon-separated roles, e.g.`"lid;gecommitteerde"`      |
| `college`         | str   | Institution(s), e.g.`"Vroedschap van Rotterdam;VOC"`       |
| `provincie`       | str   | Province (mostly null in this minimal export)                |
| `gedeputeerde`    | bool  | `True` = actual delegate to Staten-Generaal                |

**What it adds beyond `delegates_reference.parquet`**:

- `beginjaar`/`eindjaar` are more complete than `minjaar`/`maxjaar` for some
  delegates (different source; cross-check useful)
- `functienaam` values → seed vocabulary for HOE `administrative` and `diplomatic`
  categories
- `gedeputeerde` flag enables filtering to just SG delegates (True = 1 027 rows
  roughly, matching current reference)
- `college` → institution context; useful for disambiguation when two delegates
  share a surname and year range

**Integration path**:

1. Join on `cons_id_str` ↔ `abbrd.fullname` (after normalisation) to enrich
   `delegates_reference.parquet` with `functienaam` and `beginjaar`/`eindjaar`.
2. Extract unique `functienaam` tokens → add to HOE classifier seeds.
3. Use `college` as a secondary disambiguation field in Track C Step 5.

### `schutte-bewerkingen` — Diplomatic representatives index

**Location**: `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/`

Three parquets:

| File                                 | Rows | Key columns                                                                                          | What it is                                               |
| ------------------------------------ | ---- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `schutte_buitenland_in_nl.parquet` | 686  | `name`, `givenname`, `schutte_functie`, `category` (country), `derived_beginjaar/eindjaar` | Foreign diplomatic representatives to the Dutch Republic |
| `schutte_nl_in_buitenland.parquet` | 342  | same schema                                                                                          | Dutch representatives abroad                             |
| `schutte_df.parquet`               | 342  | `name`, `givenname`, `pagenr`, `schutte_nr`, `nr`, `category`                            | Flat index (both directions combined)                    |

`schutte_functie` values include: `ambassadeur`, `extraordinaris ambassadeur`,
`gedeputeerde`, `chargé d'affaires`, `secretaris van ambassade`, `commissaris`.

**What it adds**:

- Foreign delegates who appear in resolutions as addressees or counterparties
  (currently absent from `delegates_reference.parquet` which covers only SG members)
- `schutte_functie` → additional seed vocabulary for HOE `diplomatic` category
- `category` (country) → context for `states_general_formula` HOE spans

**Integration path**:

1. Create `data/schutte_reference.parquet` combining both direction files, with
   columns: `name`, `givenname`, `derived_beginjaar`, `derived_eindjaar`,
   `schutte_functie`, `category`.
2. Run NER matching separately against Schutte reference for spans whose HOE
   context is `diplomatic` or `states_general_formula`.
3. Store matches in `data/schutte_results.parquet` alongside main `results.parquet`.

### `fuzzy_search_poc.ipynb` — Compound-name filter, FuzzyPhraseSearcher, and MySQL supplement

**Location**: `/Users/rikhoekstra/develop/streamlit_worksheet/fuzzy_search_poc.ipynb`

The notebook has two distinct parts:

**Part 1 — FuzzyPhraseSearcher + compound-name filter (cells 1–19)**:

1. **`FuzzyPhraseSearcher` integration** (cells 1–3): tests whether
   `fuzzy-search` recovers the same split-half → neighbor matches as the manual
   Levenshtein loop in `pattern_merge.py`. Config tuned for short proper names:
   `ngram_size=2, skip_size=1, levenshtein_threshold=0.6`.
2. **Compound-name pre-check** (cells 5–6): before flagging a pattern as a concat
   candidate, check whether the **whole pattern** scores well against any single
   anchor. If `min_lev_dist(pattern, anchor) ≤ t_compound`, skip it — it is a
   compound name, not a concat error. Current default `t_compound ≈ 0.25`.
3. **Distractor mechanism** (cell 4): register the full compound name as a
   `distractor` for each split-half phrase → `FuzzyPhraseSearcher` suppresses
   matches when the input is closer to the distractor than to the phrase.
4. **Ground-truth validation loop** (cells 7–10): sweep `t_compound` over
   labeled CSV (`ground_truth_concat_candidates.csv`); optimise precision/recall
   for compound suppression without dropping genuine concat candidates.

**Part 2 — MySQL supplement for delegate export (cell 28)**:

Cell 28 connects to a **local MySQL database** (`raa_nw`) via `pymysql` to produce
the authoritative `uq_delegates_baked_<date>.parquet`. The database is the
underlying source that the parquet exports are derived from.

Connection: `host='localhost', user='rik', db='raa_nw'`

Two queries:

- `persoon WHERE id IN (active_ids)` — fetches `geslachtsnaam`, `voornaam`,
  `tussenvoegsel`, `geboortejaar`, `overlijdensjaar`, `heerlijkheid` to fill
  null columns in the parquet
- `aanstelling JOIN provincie` (two passes: SG-only appointments first, then all)
  — populates `provincie` for delegates where the parquet has nulls

The MySQL database is the **ground truth** for biographical and appointment data;
the parquets are snapshots. Any delegate absent from the parquet but present in
the corrections list is fetched directly from MySQL.

**Relevance for this project**:

- The `raa_nw.persoon` table is the authoritative source for `fullname`,
  `geslachtsnaam`, `geboortejaar`, `overlijdensjaar` — richer than what is in
  `abbrd_minimal.parquet` (which is a pre-filtered export).
- If this project needs to expand the delegate reference (e.g. for 1610–1630
  period), querying `raa_nw` directly would give the most complete data.
- The `aanstelling JOIN provincie` pattern shows how to derive province assignments
  from the relational schema — useful for period-aware disambiguation.
- The distractor pattern from Part 1 is directly applicable to Track C Step 5
  tie-breaking: register the longer compound name as a distractor for the shorter
  anchor (e.g. "van der Capellen tot den Pol" as distractor for "van der Capellen").

---

## Data paths (defaults)
<!-- doc-status: active -->

| Logical name                                     | Path                                                          | Phase   |
| ------------------------------------------------ | ------------------------------------------------------------- | ------- |
| `session_date_status_1626_1630`                | `data/derived/session_date_status_1626_1630.parquet`        | frozen  |
| `session_date_status_1626_1630_review`         | `output/session_date_status_1626_1630_review.csv`           | explore |
| `session_date_status_1626_1630_heatmap`        | `output/session_date_status_1626_1630_heatmap.html`         | explore |
| `s4_session_date_mapping_predictions`          | `output/s4_session_date_mapping_predictions.jsonl`          | semi    |
| `s4_session_date_mapping_review_ui`            | `output/s4_session_date_mapping_review_ui.html`             | explore |
| `s4_session_date_mapping_decisions`            | `output/s4_session_date_mapping_decisions.json`             | semi    |
| `s4_session_date_mapping_predictions_approved` | `output/s4_session_date_mapping_predictions_approved.jsonl` | semi    |
| `short_resolution_llm_sample_manifest`         | `output/short_resolution_llm_sample_manifest.jsonl`         | semi    |
| `metrics_nihil_actum_invariant`                | `output/metrics_nihil_actum_invariant.jsonl`                | semi    |
| `metrics_ke_drift_diagnostic`                  | `output/metrics_ke_drift_diagnostic.jsonl`                  | semi    |
| `metrics_separation_span_table`                | `output/metrics_separation_span_table.jsonl`                | semi    |
| `metrics_span_gap_map`                         | `output/metrics_span_gap_map.jsonl`                         | semi    |
| `s6c_severe_collapse_autopsy`                  | `output/s6c_severe_collapse_autopsy.jsonl`                  | semi    |
| `metrics_bottleneck_diagnostic`                | `output/metrics_bottleneck_diagnostic.jsonl`                | semi    |

S4a completed 2026-09-01: registered both outputs in `data_manifest.toml` and
documented the canonical key, ledger schema, and status semantics in
`scripts/build_session_date_ledger.py`. `uv run python -m data_io.check` resolves
all S4 inputs and outputs; the two S4 outputs remain absent until S4b writes them.

S4b completed 2026-09-01: `scripts/build_session_date_ledger.py` wrote 4,916
inventory-date rows to `session_date_status_1626_1630`. Statuses: T=1,012, A=4,
E=97, X=3, N=3,800. The candidate-inventory invariant passed for every trusted
and exact-date session ID; overlapping metadata inventories remain separate rows.

S4c completed 2026-09-01: added review-only, inventory-local `previous_day_session_ids`
and `next_day_session_ids` for unresolved rows. The rebuilt ledger contains 184
unique `-1`, 181 unique `+1`, 238 ambiguous `?`, and 3,197 no-nearby `N` rows;
no candidate is automatically assigned.

S4d completed 2026-09-01: `scripts/render_session_date_heatmap.py` wrote
`output/session_date_status_1626_1630_heatmap.html` with 4,916 ledger rows across
8 inventory panels. The responsive calendar includes distinct status colors, a
legend, per-panel status counts, and hover evidence for every recorded date.

S4e completed 2026-09-01: `scripts/s4_session_date_mapping_predictions.py` wrote
4,916 stable-key review rows and 4,916 mapping-aware prediction/abstention rows.
Only 1,012 T and 97 E mappings are selected; unique nearby candidates remain 365
`nearby_policy_pending` abstentions pending explicit approval. The new consumer
predicts 180 rows, compared with 244 / 1,594 in the date-keyed baseline.

S4f tooling completed 2026-09-01: [session-date evidence review UI](docs/SESSION_DATE_MAPPING_REVIEW.md)
now builds `output/s4_session_date_mapping_review_ui.html` for 3,807 `A`, `X`,
`?`, `-1`, `+1`, and `N` rows. Its localStorage-backed export is validated and
merged with `scripts/merge_session_date_mapping_decisions.py --reviewer NAME`
into a separate provenance-backed approved mapping artifact; human review is
pending. S4e remains unchanged, and within-day evaluation of approved cross-day
mappings remains deferred.

S4g steps 1-3 completed 2026-09-17: manual review of the S4f queue found it
dominated by `N` rows with no candidate evidence at all, and missed the fact
that day-level mapping cannot resolve resolution-level or cross-day
placement. [Candidate scoring prototype and resolution-level
concordance](docs/CANDIDATE_SCORING_AND_CONCORDANCE.md) ran the planned
`N`-status gap diagnostic (`analyze_n_status_gaps.py`: 76.4% of `N` rows have
no HTR session within +/-14 days — a structural coverage ceiling, not a
matching-quality gap) and built the entity-IDF/embedding candidate-scoring
module (`scripts/s4_candidate_scoring.py`), validated on the 7 `A`/`X` rows
(6/7 correct) then extended to all 610 `A`/`X`/`-1`/`+1`/`?` rows, adding a
nihil-actum abstention and an entity-overlap confidence floor
(`MIN_CONFIDENT_ENTITY_OVERLAP = 5.0`). The longer-term resolution-level
concordance spanning 1626-1630 that both steps feed into remains planned.

S4g step 4 (implementation plan) drafted 2026-09-17 in
[docs/CANDIDATE_SCORING_AND_CONCORDANCE.md](docs/CANDIDATE_SCORING_AND_CONCORDANCE.md#step-4--concordance-implementation-plan-drafted-17-sep-2026-not-built):
assembly-only plan (A) persist `s4_candidate_scoring.py` as a registered
`s4_candidate_scoring_predictions` dataset, (B) resolve one day-level status
per ledger key by joining the ledger, S4f human decisions, and candidate
scoring with a fixed precedence, (C) expand to one row per enriched
resolution ordered by `(date, resolution_index)` with paragraph-axis
attribution as a best-effort, non-status-affecting enrichment column given
its current 0.238 coverage, (D) extend the abstention vocabulary with
`resolved_auto`/`resolved_manual`, (E) freeze as `resolution_concordance_1626_1630`,
(F) stratified spot-check, no heavy compute.

**Step A built and run 2026-09-17**: `scripts/s4_candidate_scoring_batch.py` runs
`score_ledger_row` over every `A`/`X`/`-1`/`+1`/`?` ledger row (same loading
machinery as the notebook prototype and `s4_session_date_mapping_predictions.py`)
and writes one row per ledger key via `save_semi_structured`.
`s4_candidate_scoring_predictions` registered in `data_manifest.toml`
(parent: `session_date_status_1626_1630`); `uv run python -m data_io.check`
resolves it. Executed against the live ledger: 610 rows written (4 confident
`low_confidence=False` picks, all status `A`; 146 `nihil_actum`; 460
`low_confidence=True`).

**Step B built and run 2026-09-17**: `scripts/s4_day_status_resolution.py`
joins the ledger, `s4_session_date_mapping_predictions_approved` (read
defensively — absent until S4f human review completes, so `resolved_manual`
is currently unused), and `s4_candidate_scoring_predictions` into one row per
`session_date_key` with a single `day_status` +
optional `resolved_session_id`, per the doc's precedence (human-approved >
confident automatic candidate > `nihil_actum` > ledger `N` with no HTR
anywhere within +/-14 days → `missing_htr` > `uncertain`); `T`/`E` rows pass
through as `resolved_auto` directly. `s4_day_status_resolution` registered in
`data_manifest.toml` (parent: `session_date_status_1626_1630`); 10/10 tests
in `tests/test_day_status_resolution.py` passing.

**Bug caught and fixed same session**: the first version labeled every
ledger `N` row as `missing_htr` (3,197 rows, 65% of the ledger) using only
S4c's +/-1-day candidate columns. `analyze_n_status_gaps.py` had already
shown 753 of those 3,197 (23.6%) *do* have a same-inventory HTR session at a
wider +/-2..+/-14-day offset that nothing downstream had looked up — so the
first version conflated "structurally missing" with "merely unscored,"
overstating the gap by 753 rows. Fixed by reusing
`analyze_n_status_gaps.py`'s `direct_sessions`/`nearest_recovery_offset`
helpers inside `s4_day_status_resolution.py` (`n_row_recovery_offsets`) to
split `N` rows correctly, and made `n_recovery_offsets` a required
`resolve_row` argument (no silent default) so this can't regress unnoticed.
Corrected run against the live 4,916-row ledger: `resolved_auto=1,113`
(1,012 `T` + 97 `E` + 4 confident `A` candidates), `missing_htr=2,444`
(exactly Step 1's documented 49.7%-of-ledger structural ceiling),
`nihil_actum=146`, `uncertain=1,213` (460 low-confidence-scored + 753
recoverable-but-unscored `N` rows) — sums reconcile exactly against the
ledger's status-code breakdown, Step A's output, and Step 1's diagnostic.
`resolved_manual` is 0 until S4f decisions exist.

**Steps C/D/E built 2026-09-17** (not yet run): `scripts/s4_resolution_concordance.py`
expands `s4_day_status_resolution` to one row per `enriched_resolutions_1626_1630`
record (19,133 of 19,134 have a real date; the `NihilActum.xml` template row at
`resolution_index=0`/`date=None` is skipped, it is not tied to any calendar
date), ordered by `(date, resolution_index)`, and freezes the result as
`resolution_concordance_1626_1630` via `save_parquet` (registered in
`data_manifest.toml`, parent `s4_day_status_resolution`). Two wrinkles the doc's
plan didn't cover, resolved in the implementation (see the script's module
docstring):

- Every enriched date matches 2-3 candidate `inventory_id` ledger rows
  (overlapping `inventory_metadata` periods), so a resolution's date alone
  doesn't pick a `s4_day_status_resolution` row. Resolved by ranking
  same-date candidates with the same precedence Step B already uses
  (human-approved > automatic > nihil actum > missing HTR > uncertain) and
  flagging `inventory_ambiguous` when more than one candidate ties at the
  best rank.
- `status` is `cross_day_shift` (overriding the day-level `day_status`,
  which is kept in its own column) whenever the resolved session's real date
  -- looked up in `resolutions_flat` -- differs from the resolution's own
  `enriched_date`, per the standing "never rewrite the enriched date"
  constraint.

Paragraph attribution (`paragraph_start_index`/`paragraph_end_index`, decoded
from `s4_corpus_paragraph_predictions`' cut points) is attached only for
same-day resolved rows where the prediction's `k_e` matches the date's actual
resolution count; it stays null otherwise and never affects `status`, per the
doc's "best-effort enrichment, not a status input" decision. 10/10 new tests
in `tests/test_resolution_concordance.py` passing; not yet run against the
live data (needs `uv run python -m scripts.s4_resolution_concordance`) or
spot-checked (Step F).

**Steps E/F run and verified 2026-09-17**: `uv run python -m scripts.s4_resolution_concordance`
wrote 19,133 rows to `resolution_concordance_1626_1630` (row-count invariant
holds: matches dated `enriched_resolutions_1626_1630`). Status distribution:
`resolved_auto` 13,528 (70.7%), `missing_htr` 5,481 (28.6%), `nihil_actum`
124 (0.6%); zero `uncertain`/`cross_day_shift` rows, both explained (not
bugs) in `docs/CANDIDATE_SCORING_AND_CONCORDANCE.md`'s Step F section.
Coverage is notably better than Step 1's ~50% day-level ceiling because
`select_day_status` takes the best of 2-3 overlapping-inventory candidates
per date and HTR-covered inventories (3185-3189, >97% resolved) carry more
resolutions/day than uncovered ones (4861 100% `missing_htr`, 4562 84.3%).

**Data-quality fix applied 2026-09-17** (`scripts/regenerate_enriched_resolutions.py`):
the 13 duplicate `enriched_id`s (`1629-11-15_0`..`_12`) were traced to a
stray `162915nov.xml.bak` record alongside `162915nov.xml` in
`enriched_resolutions_1626_1630_complete.json`; diffed field-by-field first
(only `file` differs for 11/13, plus a trivial date-abbreviation edit --
"31 okt." vs "31 oktober" -- for the other 2, confirming `.xml` is the
later, authoritative version). Original backed up to
`enriched_resolutions_1626_1630_complete.json.pre_bak_dedup.orig`; the live
file now has 19,121 records (0 `.bak`, 0 duplicate `(date, resolution_index)`
keys), verified via `data_io.check` (`enriched_resolutions_1626_1630: ok`).
**`resolution_concordance_1626_1630` (built above) is now stale by 13 rows**
relative to this corrected source -- re-running
`uv run python -m scripts.s4_resolution_concordance` is the natural next
step before treating the concordance as final.

**Re-run completed 2026-09-17**: `uv run python -m scripts.s4_resolution_concordance`
wrote 19,120 rows (19,133 - 13, confirming the dedup source is now fully
reflected). Status distribution: `resolved_auto` 13,528 (unchanged),
`missing_htr` 5,465 (was 5,481), `nihil_actum` 127 (was 124) -- sums
reconcile exactly. New metrics printed this run: 3,266 rows fall on a date
with an ambiguous best-ranked inventory, and 2,217 rows carry paragraph-axis
attribution. Full arithmetic breakdown of the 16/3 shift (mostly dedup, ~3
rows independently reclassified) in
[docs/CANDIDATE_SCORING_AND_CONCORDANCE.md](docs/CANDIDATE_SCORING_AND_CONCORDANCE.md#e--output-dataset-built-17-sep-2026-not-yet-run).
**Step F hand-review redone 2026-09-17** against the corrected 19,120-row
output: a fresh stratified sample (3 rows/status) is plausible across all
three statuses (real text + session id for `resolved_auto`, no session id
for `missing_htr`, literal "Nihil Actum" text for `nihil_actum`). It also
**falsified** the earlier arithmetic hypothesis: none of the 13 surviving
`1629-11-15` rows became `nihil_actum` (all still `missing_htr`) -- the
`-13 missing_htr` is fully explained by outright row removal, not
reclassification. A separate `-3 missing_htr`/`+3 nihil_actum` shift among
*surviving* rows is real but still unexplained (day-level status doesn't
depend on the deduplicated JSON, so nothing documented should have moved
them) -- flagged as an open question in
[docs/CANDIDATE_SCORING_AND_CONCORDANCE.md](docs/CANDIDATE_SCORING_AND_CONCORDANCE.md#open-questions-for-the-next-session),
not resolved here.

**Window-widen non-entity-signal follow-up done (17 Sep 2026)**: dense
TF-IDF similarity was tested and rejected (spot-check found it ranked
non-matches above genuine matches). Root cause of the 523 wide-window rows'
`entity_overlap_score == 0.0` traced to two compounding gaps -- the
axis-based overlap lookup does literal-substring matching at Excel-build
time (misses spelling variants), and person names were never text-matched
against flat text anywhere in the pipeline (only places/orgs were). Fixed
via `text_confirmed_names` (same exact+fuzzy method as
`build_entity_surface_matches.py`) wired into the wide-window path only.
Real-corpus result: 125/475 (26.3%) now clear the confidence floor (was 0);
`s4_day_status_resolution`'s `resolved_auto` 1,113 → 1,238; `uncertain`
1,213 → 1,040; `s4_resolution_concordance`'s `cross_day_shift` populated for
the first time, 0 → 1,380. A small residual (3/125 rows, only generic
province-name overlap) is flagged as a likely false-positive caveat, not
fixed. Full detail: [docs/CANDIDATE_SCORING_AND_CONCORDANCE.md](docs/CANDIDATE_SCORING_AND_CONCORDANCE.md#step-5--window-widen-non-entity-signal-follow-up-done-17-sep-2026).

**Open-questions decided 2026-09-17** (no code changes -- design/scoping
decisions only, recorded in
[docs/CANDIDATE_SCORING_AND_CONCORDANCE.md](docs/CANDIDATE_SCORING_AND_CONCORDANCE.md#open-questions-for-the-next-session)):
`resolved_manual` stays the umbrella status for any human-approved mapping,
but a future resolution-level correction feedback loop gets its own
`resolution_source` value rather than being folded into the existing S4f
day-level `s4f_human_decision` source (no such correction dataset exists
yet, so nothing to build). Paragraph-axis coverage improving later confirmed
to need only `uv run python -m scripts.s4_resolution_concordance` rerun --
`s4_day_status_resolution.py` has no paragraph-data dependency, verified by
re-reading both scripts. The remaining open item (the unexplained -3/+3
`missing_htr`/`nihil_actum` shift, and the 3-row generic-name
false-positive residual) are still open for a future session.

**Track accepted as final, closed (2026-09-18)**: `resolution_concordance_1626_1630`
(70.7% `resolved_auto`, 28.6% `missing_htr`, 0.6% `nihil_actum`) is accepted
as the final output of Steps 1-5. The dominant remaining gap (the 49.7%
structural coverage ceiling documented in Step 1) is diagnosed, not a scoring
defect, and the wide-window follow-up already showed near-zero further
returns (0/475 entity-overlap signal before the Step 5 fix, 125/475 after --
the addressable part of that gap is closed). Full completeness on the
remaining `missing_htr` rows is explicitly not pursued further. See
[docs/DECISIONS.md.new](docs/DECISIONS.md.new) for the recorded decision. A
planned bounded pagexml spot-check (inventory 4861; inventory 4562's
`1629-05-12` "Crèvecoeur" row) turned out to be non-trivial: `docs/DATA.md`'s
pagexml location (`/Volumes/2tb disk/data/`) is stale -- the real archive is
an unextracted, unregistered 88.5 GB tarball
(`/Volumes/2tb disk/datasets/republic/source/1.01.02-pagexml.tgz`), so
verifying against it is deferred as its own scoped step, not a quick check.
Next candidate tracks: **S4 Segmentation Transfer**
(above, still `[ ]` -- addresses HTR under-segmentation, a distinct problem
from `missing_htr`) or the **NER training track** (GysBERT fine-tuning).

Logical names are defined in [`data_manifest.toml`](data_manifest.toml). Resolve at runtime:

```bash
uv run python -m data_io.check
```

| Logical name          | Relative path (via`data/` symlink)                                |
| --------------------- | ------------------------------------------------------------------- |
| resolutions_flat      | `resolutions/resolutions_flat.parquet`                            |
| per_annotations       | `annotations/PER-annotations.json`                                |
| loc_annotations       | `annotations/LOC-annotations.json`                                |
| delegates_reference   | `reference/delegates_reference.parquet`                           |
| patterns_reference    | `reference/patterns_reference.parquet`                            |
| inventory_metadata    | `reference/inventory_metadata.json`                               |
| ner_per_annotations   | `~/develop/.../downloads/annotations-layer_PER.tsv.gz` (hot tier) |
| gnb_passport_sessions | `/Volumes/Extreme SSD/scratch/gnb_passport_sessions.jsonl`        |

See [docs/DATA.md](docs/DATA.md) for tier layout. Legacy table:

| File                           | Path                                                                                                                 |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| NER PER annotations (download) | `~/Downloads/annotations-unaggregated/annotations-layer_PER.tsv.gz`                                                |
| HOE annotations                | `~/Downloads/annotations-unaggregated/annotations-layer_HOE.tsv.gz`                                                |
| results                        | `data/results.parquet`                                                                                             |
| hoe_vocab                      | `data/hoe_vocab.parquet`                                                                                           |
| hoe_category_counts            | `data/hoe_category_counts.json`                                                                                    |
| abbrd (external)               | `/Users/rikhoekstra/develop/streamlit_worksheet/abbrd_minimal.parquet`                                             |
| schutte buitenland→NL         | `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/schutte_buitenland_in_nl.parquet` |
| schutte NL→buitenland         | `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/schutte_nl_in_buitenland.parquet` |

## Dashboard
<!-- doc-status: active -->

- Project dashboard: docs/dashboard.md

find "$(python -c "import data_io; print(data_io.resolve('gnb_raw_resolutions'))")" -iname "*4861*" | head -20
find "$(python -c "import data_io; print(data_io.resolve('gnb_raw_resolutions'))")" -iname "*4562*" -iname "*pagexml*" | head -20

# then grep the matched pagexml file(s) for the name, e.g.:

grep -il "crevecoeur\|crèvecoeur" <matched-file></matched>

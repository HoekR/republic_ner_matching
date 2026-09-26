# Metrics tiers

<!-- doc-status: active -->

Before this doc, `docs/STATE.md`'s "Key Intermediate Results & Metrics" section was a flat list
of ~59 lines from unrelated tracks (S1 diagnostics, S4 boundary F1, HOE classifier, S6 anchor
work, resolution-concordance completeness), each with an ad hoc "higher/lower is better" note
baked into the label text. This doc groups them.

The grouping follows the anchor-signal-channel taxonomy the project already uses for HTR
alignment (`PLAN.md:538-561`), rather than an abstract "distance from the acceptance criteria"
scheme — most diagnostic work in this repo *is* about one of these channels' supply or quality,
so tiering by channel keeps the metric next to the thing that would move it.

## Tier definitions

- **Tier O — Outcome.** The acceptance-criteria table itself: `PLAN.md:17-35`'s canonical-goal
  block (separated definition, 60.9% paragraph ceiling, Global primary/stretch/spans, Local).
  Not duplicated here in prose — read it there. Also holds the consecutive-day separation span
  table (`scripts/metrics_separation_span_table.py`).
- **Tier P — Placement/model.** Cross-channel metrics measuring how well the placement algorithm
  (`interpolate_positions` / `segment_day` DP in `scripts/s4_paragraph_axis_baseline.py` and
  `scripts/s4_corpus_paragraph_predictions.py`) uses anchors *together*, independent of any one
  channel's supply: boundary F1 at various tolerances, oracle ceilings, segmentation-DP results,
  predicted-day coverage, confidence-tier distribution stability. Also holds the bottleneck
  diagnostic (`scripts/metrics_bottleneck_diagnostic.py`) that decides whether Tier A-D or Tier P
  itself is the next thing worth improving.
- **Tier A — Group A: entity anchors (Needleman-Wunsch).** Backed by `tier1_entity_nw` /
  `alignment_1626_1630.parquet` (`scripts/build_alignment_new.py`). Supply, density, and
  insufficiency counts for this channel.
- **Tier B — Group B: fuzzy/dictionary entity matches.** Backed by
  `entity_surface_matches_1626_1630` and `s4_fuzzy_surface_form_scan` output, plus the
  place/org/PER overlap builders (`build_windowed_overlap.py`, `build_per_overlap.py`).
- **Tier C — Group C: phrase anchors.** Backed by `s2_anchor_phrase_inventory` and
  `s4_opening_phrase_candidates`, scanned via `FuzzyPhraseSearcher`.
- **Tier D — Group D: session boundaries + concordance.** Session start/end sentinels,
  `session_day_find`, and — since concordance ties a resolution to its session —
  `resolution_concordance_1626_1630` completeness shares and the session-date ledger (S4a-e).
  Also holds the per-day K_e drift-comparison diagnostic
  (`scripts/metrics_ke_drift_diagnostic.py`, parented on Tier V's day series).
- **Tier E — Group E: short-resolution anchors.** `align_short_resolutions.py`'s formulaic
  open/close phrase anchors on short "no decision" resolutions. **Retired 2026-09-22** with the
  LLM side-plan close (`plans/SHORT_RESOLUTION_SIDE_PLAN.md` Step 7; `docs/DECISIONS.md`): built
  once, never measured, never wired into `scripts/s6b_anchor_harvest.py`. Not an active channel;
  do not re-open without a fresh measured case against current A–D baselines.
  **Reopen condition met 2026-09-25, not yet acted on.** Step 1 of
  `plans/COLLISION_AVOIDANCE_TRACK.md` reused this channel's `OPENING_PHRASES` unchanged as its
  `formulaic_opening` landmark class and measured it against the current stream: openings detected
  in 500 / 1,316 flat sessions (38.0%), of which **115 are reached by no other channel** (neither
  the content-verified fingerprint channel nor the in-axis president/present stems). That is the
  "fresh measured case" this retirement asked for — measured as a *landmark* channel, note, not as
  the short-resolution aligner it was retired as. The track doc's revaluation note says re-examine,
  do not auto-reopen; recorded here so the gate is not re-litigated from scratch. Dataset:
  `landmark_density_eval`.
- **Tier V — Validation/consistency invariants.** Categorically different from every other
  tier: pass/fail correctness gates, not "higher/lower is better" coverage numbers. Holds the
  nihil-actum invariant (`scripts/metrics_nihil_actum_invariant.py`) and emits the shared
  per-day `K_e` series that Tier D and Tier O consume.
- **Tier X — Exploratory/historical.** One-off readings that justified a past decision but are
  not ongoing tracked signals: the S1-D1/D2 diagnostics that justified the segmentation-transfer
  pivot, the superseded flat-resolution entity-NW baseline, the HOE classifier's `other` bucket
  (a real open task, but not an alignment-anchor channel), and S4's boundary-micro-F1-at-tolerance
  pair (demoted `docs/DECISIONS.md` 2026-09-21 in favor of paragraph-level concordance and
  collapse counts — kept for record, no longer a primary driver).

## Computed this track (V → D → O; P)

- **Tier V — nihil-actum invariant** (`scripts/metrics_nihil_actum_invariant.py`, dataset
  `metrics_nihil_actum_invariant`). A day whose concordance `day_status` is `nihil_actum` is
  authoritative: its attributed-resolution count (rows with non-null `resolved_session_id`)
  must be exactly 0. Any nonzero count is a proven date/session attribution error and blocks
  trusting that day's Tier O/D numbers. The same script emits one `day` record per enriched
  calendar date (`k_e`, `k_e_signal`, `attributed_count`, `is_nihil_actum`, `invariant_ok`);
  `k_e_signal` is 0 on nihil days so downstream drift/span work treats them as structural
  zeros rather than 1-row formula entries. Also checks ledger-level
  `s4_day_status_resolution` rows for the same rule.
- **Tier D — per-day K_e drift comparison** (`scripts/metrics_ke_drift_diagnostic.py`, dataset
  `metrics_ke_drift_diagnostic`). Parent: Tier V's day series. Scores
  `|k_e_signal - median(±3 calendar-day neighbors)|` with threshold 10; ranks spike/dip
  candidates. Nihil days are never candidates; dates failing the Tier V invariant are listed
  under `blocked_dates` and excluded. The scored day series is also written out so Tier O can
  reuse the same `K_e` parent (`K_e` is `separated_share`'s denominator).
- **Tier O — consecutive-day separation spans** (`scripts/metrics_separation_span_table.py`,
  dataset `metrics_separation_span_table`). Parent: Tier V day series + concordance paragraph
  attribution. A resolution is separated iff its start paragraph is unique on its date and
  extent (`end - start + 1`) ≤ 3 (reproduces the 1,961 baseline). Solid day:
  `separated_share = separated / k_e_signal >= 0.5`. Maximal solid runs at gap ∈ {0,1,2};
  reports qualifying spans at 7/14/30/60 calendar-day thresholds (Global, spans uses ≥30).
- **Tier O — span-gap geography** (`scripts/metrics_span_gap_map.py`, dataset
  `metrics_span_gap_map`). Parent: Tier O day solid flags. Classifies every non-solid
  session-day (`missing_htr` / `nihil_actum` / `weak_separation` / …), enumerates gaps
  between consecutive solid days, reports bridge counterfactuals (longest run if each
  class were transparent), and sets `severe_collapse_implicated` when the deferred S6c
  79-day autopsy should be reopened.
- **Tier P — bottleneck diagnostic** (`scripts/metrics_bottleneck_diagnostic.py`, dataset
  `metrics_bottleneck_diagnostic`). Repeatable oracle-vs-real rerun on eligible gold days under
  unmodified `interpolate_positions` + `snap_boundaries`: `oracle_ceiling` (perfect gold
  anchors) vs `real_performance` (NW entity anchors). Emits a `recommended_focus` decision aid
  for `svz.py review` (evidence vs placement vs redesign) — not an automatic switch.

## Proposed, not yet computed

**Placement margin (a MAPQ analogue) — Tier P, proposed 2026-09-25.** Every placement currently
carries a *provenance* tier (`tier1_anchor` / `tier2_*` / `tier3_*`): what kind of evidence produced
it. Nothing records how *uniquely* it fits — whether the chosen paragraph beat its runner-up
clearly or tied with four others. In read alignment that second quantity is MAPQ
(`-10·log10 Pr{position is wrong}`, Li/Ruan/Durbin 2008), computed from the score distribution over
competing placements, and its defining property is that a *perfect* match in a repetitive region
scores MAPQ 0: high identity, no confidence.

Why it is worth computing here:

- It is the quantity the canonical goal already asks for in prose. `PLAN.md`'s framing says
  "several resolutions sharing one paragraph is a multi-mapping read (filter, don't count as
  progress)"; a margin score turns that sentence into a per-placement number with a threshold,
  instead of the current post-hoc demotion when `n_share > 1`.
- It targets the dominant loss channel. Collisions cost 4,722 of 14,472 slots (32.6%) against
  extent's 9.9% (`plans/COLLISION_AVOIDANCE_TRACK.md` finding A), and a collision *is* a
  multi-mapping event — a flat score surface across candidates.
- It is orthogonal to what has already measured flat. `nw_matches_gt_rate` is 0.957 for correct
  pairs and 0.962 for false positives: evidence-*kind* demonstrably does not separate them.
  Ambiguity is a different axis and is untested.
- It fits the abstention-free DP without undoing it. `segment_day` always emits `K_e − 1` cuts (the
  design choice that took coverage to 100% of days with an axis), so an anchored cut and a
  uniform-interpolation guess are emitted with identical standing, and 79 days (7.5%) carry 7+
  resolutions on one paragraph. A margin separates them while keeping the coverage.

Two limits to state wherever it is reported:

- **Not a probability.** MAPQ is one because its score is a log-likelihood under a sequencing error
  model. `s6c_gap_segmentation`'s cost is a heuristic even-split-vs-phrase-hit tradeoff, so a margin
  derived from it is an *ordinal ambiguity statistic* until calibrated — bin placements by margin,
  measure actual correctness per bin on the 50 gold days, and report the calibration curve.
- **It measures ambiguity, not correctness.** A systematically wrong model is confidently wrong:
  shift every placement one paragraph and the margins do not move. So it is a filter and a reporting
  axis, never the score a placement change is judged by — the trap Step 2 of the collision-avoidance
  track already documented when a trivial even spread beat gold's own annotations on `separated`.

Span-gap geography computed 2026-09-22; nothing else outstanding.

## How this relates to the DNA analogy

`PLAN.md:11-15`'s framing ("patchy alignment, after ancient DNA") gives every tier a direct
counterpart, and it is why the bottleneck diagnostic above is scoped as an oracle rerun rather
than a general solver:

- **Tiers A-D are anchor/seed classes**, same as a genome aligner's evidence types: Group A
  (exact entity matches) is the unique-seed class — sparse, high specificity; Group B
  (fuzzy/dictionary matches) is the degenerate-match class — higher volume, lower specificity;
  Group C (phrase anchors) is a motif/marker class; Group D (session boundaries) is the
  scaffold/contig-boundary class — a structural constraint on where anything can go, independent
  of content matching.
- **Tier P is the aligner itself**, and its own resolving-power limit is a distinct failure mode
  from input quality — exactly the point of testing a repeat region with a *simulated perfect
  read*: if coverage still caps out with perfect input, the ceiling is the algorithm
  (multi-mapping / non-unique placement), not sequencing depth. The S6 Step-1 oracle diagnostic
  already ran this test once for this project (5/19 gold days placeable even with perfect
  anchors) and reached exactly that conclusion.
- **Tier O's spans metric is a coverage-breadth statistic** — a run of consecutive solid days is
  the resolutions-corpus equivalent of reporting the longest covered contig / breadth of
  coverage at depth X in an aDNA paper, matching the canonical goal's "uncovered regions are
  informative, must be classified, not merely omitted."
- **Tier V's nihil-actum invariant is a negative-control check** — a region (day) that should
  show zero coverage; nonzero coverage there is contamination (mis-mapped date/session), never
  counted as signal.
- **The bottleneck diagnostic is the standard QC move, not a new invention**: real aDNA/NGS
  pipelines decide "sequence more" vs. "fix the aligner" by rerunning the perfect-read oracle
  test whenever the evidence base changes, then applying domain judgment to the result — they do
  not solve it with a dynamic program. That is why this stays a decision aid feeding
  `svz.py review`, consistent with `docs/ITERATION_POLICY.md`'s existing "advisors and editors,
  not operators" convention, rather than a new orchestrator engine.

## Full mapping of current `docs/STATE.md` metrics

Every line in `docs/STATE.md`'s "Key Intermediate Results & Metrics" section, by tier:

| Tier | Metric (as recorded in `docs/STATE.md`) |
|---|---|
| X | S1-D1 — HTR under-segmented session-days: 81.1% |
| X | S1-D1 — Exact K_f == K_e session-days: 3.8% |
| X | S1-D1 — Mean entity containment: 0.295 |
| A | S1-D1c — Tier-1 Kendall tau: 0.638; 64.3% of pairs at tau >= 0.8 |
| X | S1-D2 — LLM judge precision: 60.0% against 53.7% baseline |
| C | S1-D2b — Opening formula hit rate: 80.1% |
| X | S4 — Flat-resolution entity-NW baseline coverage: 0/50 predicted (superseded by paragraph-axis approach) |
| A | S4 — Paragraph-axis resolved entity coverage: 480/611 paragraphs; 87 unresolved |
| X | S4 — Boundary micro F1 (tolerance 0): 0.576 (demoted, `docs/DECISIONS.md` 2026-09-21: paragraph-level concordance and collapse counts are now the primary drivers) |
| X | S4 — Boundary micro F1 (within 2 paragraphs): 0.727 (demoted, same 2026-09-21 entry) |
| P | S4 — Predicted-day coverage (of 21 eligible gold days): 0.429 |
| C | S4 — Opening signal at manual cuts: 227/360 regex; 225/360 S2 top-20 phrases |
| C | S4 — fuzzy_search opening coverage: 225/360 |
| C | S4 — Held-out opening phrase inventory: 271 candidates |
| A | S4 — Corpus paragraph axis: 21,519 paragraphs; 16,104 entity-bearing; 41,156 resolved attachments |
| P | S4 — Corpus entity-NW baseline: 244/1,594 predicted; 815 insufficient anchors; 535 no same-day HTR |
| D | resolution-concordance-completeness — Resolved-auto share: 70.7% |
| D | resolution-concordance-completeness — Missing-HTR share: 28.6% |
| X | hoe-classifier-other-bucket — 'other' bucket share: 31% |
| P | S4 — Common-language effect size, bundled vs clean-boundary: 0.770 |
| P | S4 — NER-only entity spans, even-split, tol150: 0.333 |
| P | S4 — NER + dictionary lookup, tol150: 0.407 |
| P | S4 — NER-only entity spans, even-split, tol50: 0.0 |
| P | S4 — NER + dictionary lookup, tol50: 0.111 |
| P | S4 — NER-only + phrase-boundary snap, tol50: 0.074 |
| P | S4 — NER-only + phrase-boundary snap, tol150: 0.333 |
| P | S4 — NER + dictionary + phrase-boundary snap, tol50: 0.148 |
| P | S4 — NER + dictionary + phrase-boundary snap, tol150: 0.407 |
| B | excel-overlap-builder-audit — place rebuild delta: 0.1342 |
| B | excel-overlap-builder-audit — org rebuild delta: 0.0404 |
| B | excel-overlap-builder-audit — PER fuzzy-confirmed cross-check: 1.0 |
| P | s6-anchor-chain-alignment — Hard recall bound tol0 (paragraph, char_offset) axis: 0.909 |
| P | s6-anchor-chain-alignment — S6a STRICT ceiling: 0.889 |
| P | s6-anchor-chain-alignment — S6a re-scored baseline, tol0 chars: 0.467 |
| P | s6-anchor-chain-alignment — S6a re-scored baseline, tol150 chars: 0.567 |
| P | interior-cut-evaluation-harness — 22/24 folded gold groups gain distinct coords: 0.917 |
| P | s6-anchor-chain-alignment — S6 Step 1 oracle diagnostic coverage: 0.263 |
| P | s6-anchor-chain-alignment — S6 Step 1 oracle diagnostic F1 tol50: 0.788 |
| P | s6-anchor-chain-alignment — S6a LUMPED baseline: 0.828 |
| A | s6-anchor-chain-alignment — S6b constraint baseline, contiguous Jan-Jun, pinned share: 0.319 |
| P | s6-anchor-chain-alignment — S6b constraint baseline, gaps>2 share of unplaced work: 0.752 (problem-structure baseline, not a model output) |
| A | s6-anchor-chain-alignment — S6b constraint baseline, FULL period, pinned share: 0.378 |
| P | s6-anchor-chain-alignment — S6b constraint baseline, FULL period, gaps>2 share: 0.707 |
| B | adopt-windowed-overlap-rebuild — PER variant rebuild delta: 415 |
| A | s6-anchor-chain-alignment — S6b anchor harvest, 36-day smoke, supply-gain: 0.0 |
| A | s6-anchor-chain-alignment — S6b anchor harvest, FULL CORPUS, supply-gain: 0.072 |
| A | s6-anchor-chain-alignment — S6b anchor harvest, FULL CORPUS, per-channel density: 6.99 (cross-channel summary; recorded value is Group-A scale, full breakdown also covers B/C/D) |
| P | adopt-windowed-overlap-rebuild — post-rebuild confidence_tier distribution delta: 0.0195 |
| P | s6-anchor-chain-alignment — 19/21 eligible gold days predicted: 0.905 |
| P | s6-anchor-chain-alignment — S6c segmentation DP, baseline check: 0.826 |
| P | s6-anchor-chain-alignment — S6c segmentation DP, ~3x predicted days: 0.503 |
| A | s6-anchor-chain-alignment — insufficient_entity_anchors eliminated: 0 |
| P | s6-anchor-chain-alignment — 1059/1059 days with axis now predict: 1.0 |
| P | s6-anchor-chain-alignment — 79/1059 low-localization days: 0.075 |
| D | s6-anchor-chain-alignment — 535->454 missing_htr recovered via resolved_session_id: 454 |
| D | s6-anchor-chain-alignment — session-content fingerprint match rate: 0.701 |
| D | s6-anchor-chain-alignment — session_day_find, 25/25 sampled genuine: 1.0 |
| D | s6-anchor-chain-alignment — session_day_find corpus-wide density: 0.131 |
| P | s6-anchor-chain-alignment — phrase-evidence (Group C) regression on corpus predictor: 0.622 |
| V | metrics-nihil-actum-invariant — invariant_passed (1=pass): 1 |
| V | metrics-nihil-actum-invariant — nihil_share_of_days (127/1594): 0.0797 |
| D | metrics-ke-drift-diagnostic — n_drift_candidates (|dev|>=10 vs ±3d neighbor median): 203 |
| O | metrics-separation-span-table — separated_count (post 2026-09-23 concordance refresh, was 1961): 8015 |
| O | metrics-separation-span-table — separated_share_of_ceiling (Global-primary >=0.5 now MET, was 0.1684): 0.6883 |
| O | metrics-separation-span-table — n_solid_days (share>=0.5 on k_e_signal, was 221): 693 |
| O | metrics-separation-span-table — Global spans@30 gap=0 (n_spans / days_covered, unchanged): 0/0 |
| O | metrics-separation-span-table — Global spans@30 gap=1 (was 0/0): 1/43 |
| O | metrics-separation-span-table — Global spans@30 gap=2 (was 0/0; criterion needs >=6/>=180): 4/177 |
| O | metrics-weak-separation-headroom-diagnostic — headroom_available_share of remaining 445 weak_separation days (post-refresh): 0.822 |
| P | metrics-bottleneck-diagnostic — oracle_ceiling coverage (interpolate_positions): 0.263 |
| P | metrics-bottleneck-diagnostic — real_performance coverage (NW + same model): 0.368 |
| P | metrics-bottleneck-diagnostic — recommended_focus (1=algorithm_redesign): algorithm_redesign |

## Known gaps

- ~~Tier O's pigeonhole ceiling (11,644) is still unreproducible as a scripted
  computation.~~ **Closed 2026-09-24.** `scripts/metrics_local_inventory_ceiling.py`
  reproduces it exactly: `sum(min(k_e, same-calendar-day raw paragraph_count))` over
  all 1,594 enriched-dates, with 535 no-HTR dates also matching. Same script answers
  PLAN.md's Local criterion (any inventory ≥ 50% of its own ceiling): **MET** — all 5
  main annual inventories clear it (63.9%–72.3%); the 2 non-annual "secret resolution"
  inventories (4562, 4861) do not (10.5%, 0.0%), structurally near-zero same-day HTR.
  See `docs/DECISIONS.md`, 2026-09-24.
- **Global, spans is measured and currently unmet** at every gap ∈ {0,1,2}: zero
  qualifying ≥30-day spans (longest run 6/9/9 calendar days). Solid days exist
  (221/1,594) but do not form long contiguous runs under current paragraph attribution.
- **Span-gap geography (2026-09-22, `metrics_span_gap_map`):** 171 breaking gaps
  among 221 solids; dominant interrupter `weak_separation` (125/171). Severe-collapse
  days appear in 43/171 = 25.15% of breaking gaps → `severe_collapse_implicated=True`
  (reopens the deferred autopsy). Bridge counterfactuals: no single interrupter class
  unlocks Global spans — bridging all 917 `weak_separation` days only raises longest
  to 12 calendar days. Converting weak_separation days *into* solids (higher
  `separated_share`), not merely bridging them, remains necessary for ≥30d runs.
- **S6c severe-collapse autopsy (2026-09-22, `s6c_severe_collapse_autopsy`):** 92/1,140
  predicted days (8.1%). Cause mix: `pigeonhole_forced` 32, `axis_requires_repeats` 50,
  `room_on_axis` 10. All 92 are Tier O `weak_separation` nonsolids (0 solid). Mean excess
  over pigeonhole floor 4.3; max pile-up 25. Closed as diagnostic — densify
  `weak_separation` rather than retune S6c for the collapse tail.
- **Severe-collapse spot-check (2026-09-22):** of 92 days, **9** ignore a richer
  concordance-resolved session (neighbor date) in favor of a thin same-calendar
  stub (`axis_for_date` order); **15** are genuinely thin on both calendar and
  resolved session (often inventory 4562 single-paragraph blobs); **56** have a
  short axis with no richer session. Missing-text is real for the thin strata;
  the 9 are a selector bug, not absent HTR.
- **`axis_for_date` fixed and remeasured (2026-09-23):** prefers the concordance
  `resolved_auto` session over a non-empty same-calendar-day stub (falls back to the
  stub only when no resolved session exists or its axis is empty). Coverage unchanged
  (1,140 predicted / 454 `missing_htr`); of those, 1,057 now route through the
  resolved-session path but only **77** actually change axis content (the rest resolve
  to the same session either way). Re-running the full chain (predictions → span-gap
  map → severe-collapse autopsy) confirms the spot-check exactly: severe-collapse days
  **92 → 83** (max pile-up 25 → 16), breaking gaps containing a collapse day **43 → 40**
  (25.15% → 23.39%, `severe_collapse_implicated` **True → False** against the 0.25
  threshold). Bridge-ceiling reasoning is unchanged — still 0 spans@30 under every
  interrupter class, longest 12 calendar days after bridging `weak_separation`.
- **`resolution_concordance_1626_1630` was stale, gating the whole Tier O baseline
  (2026-09-23).** A new headroom diagnostic (`scripts/metrics_weak_separation_headroom_diagnostic.py`
  — per-day `structural_ceiling_share = min(1, paragraph_count/k_e_signal)`, a strict upper
  bound on `separated_share`) found 91% of `weak_separation` days had ample axis room but
  `separated_share ≈ 0` regardless — implausible as a placement-quality signal. Root cause:
  `resolution_concordance_1626_1630` (every Tier O metric's input) was built 2026-09-17, three
  `s4_corpus_paragraph_predictions` rebuilds behind (S6c's DP, the concordance-fallback wiring,
  and the `axis_for_date` fix above). Re-ran `scripts/s4_resolution_concordance.py` (pure
  assembly, no new alignment logic, 26s) and the full Tier O chain: **separated_count 1,961 →
  8,015 (16.8% → 68.8% of ceiling, Global-primary criterion now MET)**, solid days 221 → 693,
  spans@30 gap=2 0/0 → 4 spans/177 days (still short of the 6-spans/180-days criterion).
  `severe_collapse_implicated` stays `False`. See `docs/DECISIONS.md` 2026-09-23. Re-run headroom
  diagnostic on fresh data: `weak_separation` days 917 → 445, of which 82.2% remain
  `headroom_available` (mean headroom 0.65) — the Group-B `position_scores` wiring already
  scoped in `PLAN.md` is still a live lever on the smaller remaining population.

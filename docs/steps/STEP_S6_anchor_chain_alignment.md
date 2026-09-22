# STEP S6 — Multi-channel anchor chaining at character coordinates
<!-- doc-status: active -->

Successor to S4's paragraph-axis baseline. Supersedes the paragraph-index coordinate, not the
Needleman–Wunsch idea: [docs/SEGMENTATION_TRANSFER.md](../SEGMENTATION_TRANSFER.md) §6 already
specified entity-sequence alignment — this step corrects where the implementation diverged from it
and generalises the anchor set.

---

## 1. Why this step exists

Three changes, in order of how much they move:

**(a) The coordinate is wrong, and that alone caps recall.**
§6.3 of the design says cut points land at **character positions** and that the paragraph-vs-line
granularity question "dissolves." The implementation instead emits `paragraph_stream_index` as the
real output coordinate ([s4_paragraph_axis_baseline.py:155-156](../../scripts/s4_paragraph_axis_baseline.py#L155-L156));
`char_offset` is only a byproduct of a phrase-snap hit and is `0` when no phrase matched.

`compute_boundary_prf` ([evaluation_harness.py:104-120](../../evaluation_harness.py#L104-L120))
consumes each reference boundary at most once, and predicted positions are strictly increasing.
HTR under-segments on 81.1% of days, so distinct gold cuts frequently land inside one paragraph and
collapse to the same integer — e.g. 1626-01-08 has cuts at `(index 2, char 409, mid_paragraph)` and
`(index 2, char 746, paragraph_boundary)`, 337 characters apart in the source, indistinguishable in
paragraph space.

Measured on all 50 gold days (`output/boundary_gold_sample.json`, `kind == "cut"`):

| | paragraph coords | character coords |
| --- | --- | --- |
| distinct reachable positions | 280 / 352 | **313 / 352** |
| hard recall bound **at tolerance 0** | 79.5% | **88.9%** |

109 of 352 cut slots (31.0%, across 25 days) share a paragraph index with another slot. Moving to
`(paragraph_stream_index, char_offset)` separates 40 of them. The 32 that remain unseparated all
have `char_offset: null` — an annotation gap, not a coordinate limit.

> **Corrected 2026-09-20 by S6a** (was 320 / 352 and 90.9%; see
> [DECISIONS.md](../DECISIONS.md)). 39 cut slots carry `char_offset: null` and fall into 7 distinct
> `(date, paragraph_index)` groups. The original count added those 7 groups to the 313 genuinely
> distinct character positions. A slot with no offset has no character coordinate, so it is not
> reachable on this axis. Measured by strict composition in
> [scripts/s6a_char_axis_evaluation.py](../../scripts/s6a_char_axis_evaluation.py): all 313
> offset-bearing cuts compose to 313 distinct positions, with no residual collisions. The character
> axis still wins by a real margin — the gain is +9.4 points, not +11.4.

**Precision about the bound (corrects the 2026-09-18 framing).** "Max TP = distinct reference values"
is rigorous **only at tolerance 0**, where a hypothesis must equal a reference exactly and strictly
increasing predictions can therefore claim at most one slot per distinct value. At tolerance > 0 it is
*not* a property of the metric: against `ref = [7,7,7]`, a clustered hypothesis `[5,6,7]` scores
TP = 3 at tolerance 2, while the spread `[3,7,11]` scores 1. The bound binds at tolerance 2 only
because the current predictor emits one cut per paragraph by construction, so it cannot cluster.
Consequence: the 2026-09-18 reading of "tol2 TP = 24 = exactly the ceiling" as *saturation* was wrong
— there was headroom that the ceiling framing hid. Both framings still point at character
coordinates, since placing several cuts inside one paragraph is precisely what they enable.

**So the ceiling is an implementation artifact.** Unlike the line-level track, lifting it needs no
new ground truth and does not touch the blocked 10 GB `sessions_json` extraction.

**(b) One anchor channel is too sparse.** The current alphabet is resolved entity IDs, capped by an
upstream tagger at ~50-55% recall. That sparsity is the direct cause of 815 corpus-wide
`insufficient_entity_anchors` abstentions. The repo has since built several further anchor
inventories that are used in isolation or not at all — the orphan pattern
[docs/APPROACH_OVERVIEW.md](../APPROACH_OVERVIEW.md) diagnosed. They should all score into one
comparison.

**(c) The session/day boundary should be an anchor, not a partition.** Everything downstream of S4a-e
partitions by session-day and aligns within each day, so material that crosses a day boundary is an
exception class rather than a case: 7 gold days abstain as "cross-day shifts," S5 *excludes* C/M days
from quality denominators, and 535 corpus days have no same-day HTR assignment at all. The gold
schema already records the phenomenon (`starts_mid_resolution`, `has_trailing_spillover`). Treating
a session start as a strong-but-soft anchor inside one continuous per-inventory stream turns all of
those from exclusions into ordinary alignment regions.

---

## 2. Design

### 2.1 Coordinate

One monotone character axis per **inventory** (not per day). A position is
`(paragraph_stream_index, char_offset)` composed to a single cumulative integer. Keep the composed
integer as the alignment's coordinate and the pair as its human-readable form; the gold data already
carries both.

`compute_boundary_prf` ([evaluation_harness.py:55](../../evaluation_harness.py#L55)) is unit-agnostic —
it takes two integer sequences and a tolerance — so **it does not need rewriting**. What it needs is a
gold adapter that emits composed character coordinates and tolerances on a character scale
(50 / 150 chars, matching the split-POC harness) instead of 0 / 2 paragraphs.

### 2.2 Anchors, grouped by provenance

Every channel contributes a scored anchor at a character position. Weights are fitted **per group,
not per inventory** — several channels are derived from the same underlying evidence and summing them
flat would triple-count one tagger.

| Group | Channels | Independent of the NER tagger? |
| --- | --- | --- |
| **A — tagger entity layer** | `LOC-/ORG-/PER-annotations`, `place_overlap_1626_1630`, `org_overlap_1626_1630` (both variant-aware as of 2026-09-19) | no — shared provenance, one shared weight |
| **B — dictionary / fuzzy surface** | `entity_surface_matches_1626_1630`, `s4_fuzzy_surface_form_scan` | partly — recovers what the tagger missed |
| **C — formulaic text** | `s2_anchor_phrase_inventory`, `s4_opening_phrase_candidates` (271 held-out) | yes — text-derived |
| **D — structural / temporal** | DAT date hooks (`dat_paragraph_dates_1626_1630`), session index, `para_start` | yes |

Apply the existing `calculate_idf_weights` ([build_alignment_new.py:767](../../build_alignment_new.py#L767))
inside group A and B so that a "Holland"↔"Holland" hit earns almost nothing, per §6.5.

Group D is where **(c)** lands: a session start is an anchor with a high but finite weight. It can be
crossed when the other channels agree, which is exactly the cross-day spillover case.

### 2.3 Algorithm — chaining, not global NW

Use **colinear anchor chaining** (the seed-chain-extend structure of long-read genome aligners),
not a full NW pass over a dense symbol stream:

1. **Seed** — collect all anchors from all four groups over the inventory stream.
2. **Chain** — find the maximum-score colinear (monotone) chain by DP, with a gap penalty. Band the
   DP by the transposition width implied by D1c (Kendall τ 0.638; 64.3% of tier-1 pairs at τ ≥ 0.8).
3. **Interpolate** — between consecutive chained anchors the enriched resolution count is known, so
   place the remaining cuts by exact-count interpolation (§7).
4. **Snap** — move each cut to the nearest group-C phrase hit within a radius, using the existing
   per-boundary order-preserving `snap_boundaries` logic rather than an all-or-nothing revert.
5. **Abstain** below a score threshold; route abstentions to review.

Chaining is the right primitive because the anchor set is **sparse, heterogeneous and weighted** —
which is what the user's "all anchors contribute to one comparison" implies. A substitution-matrix
aligner wants a dense symbol-by-symbol comparison over a small fixed alphabet and cannot express
"this match is worth 3.2 because it is a rare place name that also carries a DAT hook."

### 2.4 On bioinformatics libraries

Take the algorithms, not the dependency.

- `Bio.Align.PairwiseAligner`, `parasail`, `edlib`, `minimap2` all assume a small fixed alphabet with
  a symbol-pair substitution matrix. Our score is *position-specific* and multi-channel; encoding it
  as a symbol matrix would discard the per-position weighting that makes the approach work.
- Profile HMMs (HMMER) are the closest conceptual fit — position-specific scoring is exactly what §2.2
  describes — but adapting them to this data is a research project, not reuse.
- What *is* worth lifting is the chaining DP, affine (Gotoh) gap costs, and banded DP. Each is on the
  order of tens of lines, and the repo already has NW machinery to host them.
- Character-level fuzzy matching is already covered by `rapidfuzz` and `fuzzy-search`, both in-project.

---

## 3. Sequence

Do **S6a before anything else** — until scoring runs at character coordinates, a win here is invisible
to every tracked metric, and this branch would repeat the interior-cut branch's fate.

| Step | Done when |
| --- | --- |
| **S6a** — character-coordinate evaluation adapter (the registered `interior-cut-evaluation-harness` track) | **DONE 2026-09-20** — [scripts/s6a_char_axis_evaluation.py](../../scripts/s6a_char_axis_evaluation.py), 14/14 tests, output `s6a_char_axis_evaluation`. Composition is pure concatenation, no separator: gold `paragraph_boundary` cuts carry `char_offset == len(paragraph)`, so a paragraph-final cut composes to exactly the next paragraph's start. `compute_boundary_prf` needed no change. Re-scored baseline (predictions unchanged): micro F1 **0.467** / **0.500** / **0.567** at tol 0 / 50 / 150 chars, coverage 7 / 19 scoreable days. Ceiling recorded as 280→**313** (0.795→0.889), correcting the 320 above. |
| **S6b** — anchor harvest | One table of `(inventory, char position, channel, group, weight, payload)` over the 1626-1630 stream, built from all four groups. Report per-group anchor density and how far it closes the 815 `insufficient_entity_anchors` abstentions. Corpus-wide harvest across A/B/C plus the `session_boundary` sentinel: **DONE 2026-09-21** (`docs/DECISIONS.md`). The second Group-D channel, `session_day_find`: **DONE 2026-09-21** — [scripts/s6b_anchor_harvest.py](../../scripts/s6b_anchor_harvest.py) (`phrase_hits`/`session_day_find_rows`), `FuzzyPhraseSearcher` at `ignorecase: True`/threshold 0.95, not the stem regex this step originally implied; validated against `s4_session_start_scan.py`'s baseline (210/167) with 25/25 sampled hits genuine at 154/130 — see `docs/DECISIONS.md` for the two bugs (case-sensitivity, threshold-driven false positives) found before trusting the count. Scope caveat: still `paragraph_axis_1626_1630`/`resolutions_flat`-derived, not raw `sessions_json_source`, so it does not reach the 179 sessions with zero `resolutions_flat` rows. Corpus-wide run: **203 anchors / 162 of 1,240 days-with-axis (13.1%)**, smallest of all six non-sentinel channels — a sparse, high-confidence anchor (merged-session formulas are rare events), not a coverage lever. The third Group-D channel, `session_date_verified`: **built 2026-09-22** — one anchor per flat session on a day's axis whose content-fingerprint match (`s6b_session_fingerprint_match`) uniquely identifies its true raw archival session, keyed off `flat_session_id` rather than the drifted session-number label. 9-day smoke window (1626-01-01..01-10): 7 anchors / 7 of 9 days (~70%, matching the fingerprint match rate). Not yet run corpus-wide. |
| **S6c** — count-constrained segmentation DP (RESCOPED 2026-09-21, `docs/DECISIONS.md`) | **DONE 2026-09-21** — [scripts/s6c_gap_segmentation.py](../../scripts/s6c_gap_segmentation.py) (`segment_gap`/`segment_day`, 11/11 tests), swapped in for `interpolate_positions` in both `s4_paragraph_axis_baseline.py` and `s4_corpus_paragraph_predictions.py`; `interpolate_positions` itself is untouched (`s6_oracle_anchor_diagnostic.py` still needs the unmodified model). Never abstains: a non-decreasing anchor backbone bounded by session start/end sentinels, with repeats allowed when a gap is narrower than its resolution count, and group-C phrase hits as soft in-gap evidence at gold-day scale. Gold-day result: predicted-day coverage 9/21 → 19/21 eligible (7/19 → 19/19 scoreable), lumped F1 flat (0.828 → 0.826). Corpus-wide result: `insufficient_entity_anchors` 777 → **0**, 100% of days with an axis now predict; quality caveat — 79/1059 (7.5%) predicted days collapse 7+ resolutions onto one paragraph (low-localization coverage, not real segmentation). Group-B evidence remains deferred, not a blocker. Corpus-scale group-C phrase-hit wiring was **tried and measured negative 2026-09-21** (`docs/DECISIONS.md`): tol0 F1 0.644 → 0.622 on the gold-day sample scored through the corpus predictor's own codepath, mean Pk/WindowDiff also worse; not wired in. Not a candidate for the severe-collapse problem going forward without new evidence. |
| **S6d** — session-as-anchor | **SUPERSEDED 2026-09-21 (`docs/DECISIONS.md`)** — before building this, found `resolution_concordance_1626_1630` (a separate, already-"accepted final" track: `session_date_status_1626_1630` → `s4_day_status_resolution` → concordance, [docs/CANDIDATE_SCORING_AND_CONCORDANCE.md](../CANDIDATE_SCORING_AND_CONCORDANCE.md)) already resolves session/day mapping per enriched resolution, including confident candidate scoring over ambiguous `-1`/`+1`/`?` ledger rows — exactly the orphan pattern section 1(b) warned about. Wired `scripts/s4_corpus_paragraph_predictions.py` to fall back to its `resolved_session_id` instead of building new session-as-anchor chaining: `missing_htr` abstentions 535 → **454** (81 days recovered), a data-source fix not new alignment logic. Auto-selecting ledger `-1`/`+1` candidates directly was considered and rejected — [docs/SESSION_DATE_MAPPING_REVIEW.md](../SESSION_DATE_MAPPING_REVIEW.md) already requires human review with a note, and 95% of unique `-1`/`+1` candidates are also their true neighbor day's own match, confirming that needs a human reading the text. The 7 gold cross-day-shift days remain unresolved (different failure mode: a day with its *own* axis but contaminated trailing text — the per-day scoring schema still has no slot for a boundary that belongs to a neighboring day). Not planned to be built as originally scoped. |
| **S6e** — weight fitting | Fit the four group weights on held-out days (never per-inventory weights — 50 gold days / 332 offset-bearing boundaries is too little for that). |

---

## 4. Guardrails

Each of these is a mistake this project has already made once.

- **Measure through the real pipeline, not a shortcut of it** (§4.1). The 2026-09-18 session
  measured phrase hit rate directly at gold cuts while the pipeline used interpolate-snap-revert, and
  the two disagreed. Every S6 number must come from the predictor's own output.
- **Do not sum correlated channels.** Group A's three channels share one tagger; a flat sum would
  silently weight it 3×.
- **Replace, don't accrete.** This is the third scoring function in the repo after
  `build_alignment_new.py` (IDF + semantic cosine) and the S4 baseline (entity NW + phrase snap). S6c
  must *replace* the baseline's scoring step, or it becomes the next orphan.
- **Record a metric every session.** A track with no metric cannot be judged by `svz.py review`.

---

## 5. What this reopens, and what it does not

`docs/DECISIONS.md` (2026-09-18) closed `boundary_f1_tolerance0` / `tolerance2` on the grounds that
further gain "needs finer-than-paragraph granularity, i.e. the already-scoped but `blocked`
line-level-segmentation track." Character coordinates are finer-than-paragraph granularity **and do
not require that track** — the offsets are already in the gold file. S6 therefore reopens those two
metrics legitimately, on a new axis, and S6a must record the new ceiling so the reopening is explicit
rather than a silent re-litigation.

Still closed and untouched by this step: `resolution_concordance_1626_1630` (accepted final), the
`missing_htr` structural ceiling, and line-level segmentation (still blocked on the `sessions_json`
page-range extraction).

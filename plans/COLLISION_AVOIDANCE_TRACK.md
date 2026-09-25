# Inventory-stream reframing and collision avoidance

<!-- doc-status: active -->

## Goal

Test whether treating each **inventory as one continuous resolution stream** — with session
openings as interior landmarks rather than the calendar day as a hard partition — recovers
separations that the current per-day framing declares structurally impossible.

Opened 2026-09-25 out of the post-mortem code check (`plans/POST_MORTEM_CODE_CHECK.md`). This is a
**separate track from `s6-anchor-chain-alignment`**, which is closed and stays closed: S6 tested
*what evidence feeds `position_scores`* and exhausted that lever. This track tests *what unit the
problem is posed on*, and *what constraint governs placement when evidence is absent or tied*.
S6c's closure verdict is not reopened or reinterpreted.

## Guardrails

- Read-only diagnostics first. No change to production concordance, S6c segmentation, or frozen
  datasets until a gate below comes back positive.
- **The success metric is not `separated`-share alone.** Under a stream framing the denominator
  itself changes, and `separated` is gameable by scattering resolutions onto arbitrary unused
  paragraphs (uniqueness satisfied, placement wrong). Any step that proposes a placement change
  must report avoidable-collisions-recovered **plus** a correctness check against boundary gold.
  Per `docs/SEGMENTATION_RESULTS.md` §5 "define the metric before the method".
- No tolerance-family metrics as targets (`feedback_no_tolerance_metrics`); collision, coverage,
  and gold-correctness only.

## Findings already in hand (free gates, 2026-09-25)

Computed from artifacts already on disk, no replay:

**A. Collisions are the dominant loss channel, 4:1 over extent.** Corpus-wide over the 1,121
predicted days (14,472 resolution slots): separated 8,315 (57.5%), lost to collision *only* 4,722
(32.6%), lost to extent *only* 1,426 (9.9%). 773/1,121 days (69.0%) carry at least one collision.

**B. Most "pigeonhole-forced" collisions are day-partition artifact, not physics.** Of the 4,722
collision losses, 3,244 sit on days where `k_e > paragraph_count` and 1,478 on days where it is
not — of which 1,334 are on days that still have *unused* paragraphs. Reference: the Global-stretch
gap is 718.

**C. The ceiling itself encodes the day partition.** Recomputing the pigeonhole bound per
inventory stream (`min(Σk_e, Σparagraphs)`) instead of per day (`Σ min(k_e, paragraphs)`):

| inv | k_e | paragraphs | day ceiling | stream ceiling | gain |
|---|---|---|---|---|---|
| 3185 | 2655 | 4516 | 2051 | 2655 | 604 |
| 3186 | 2704 | 4660 | 2257 | 2704 | 447 |
| 3187 | 3521 | 4665 | 3163 | 3521 | 358 |
| 3188 | 3736 | 3723 | 2805 | 3723 | 918 |
| 3189 | 1624 | 1579 | 1311 | 1579 | 268 |
| 4562 | 2493 | 76 | 57 | 76 | 19 |
| 4861 | 2387 | 0 | 0 | 0 | 0 |

**11,644 (day) vs 14,258 (stream) — 2,614 resolutions, 22.5% of the current ceiling, are
unreachable because of the partition, not the archive.** 3185 is the clearest case: 70% more
paragraphs than resolutions across the inventory, yet 604 declared impossible. For 3185/3186/3187
the stream ceiling equals `k_e` exactly — no pigeonhole constraint at all.

Honesty notes: 14,258 is a *loose upper* bound (it assumes paragraphs are freely reallocatable
along the stream; really a resolution can only move as far as evidence allows), just as 11,644 is
a bound conditional on the day partition being correct. The true bound is between them. And note
the reframing makes the headline look **worse**, not better: 8,015 separated is 68.8% of the day
ceiling but 56.2% of the stream ceiling. It reveals headroom, it does not flatter.

**D. The anchor-correction channel's data exists and was never wired up.**
`scripts/s6b_session_fingerprint_match.py` content-verifies flat-session identity by text
fingerprint, independent of the drifted session label: 1,059/1,511 (70.1%). Its docstring ends
"Building the channel itself is deferred to a follow-up session." That follow-up never happened.

## Working hypothesis (user, 2026-09-25)

1. If resolutions were recognized correctly, applying `k_e` sequentially along an inventory would
   partition it mechanically. The mechanism is sound; the granularity mismatch (paragraphs are not
   resolutions — 81.1% of days under-segmented, S1-D1) is what breaks it.
2. Since it breaks, day separation should act as a **local calibration anchor** for sequence
   alignment, not as a partition.
3. Misplaced day anchors can then be **corrected by the resolutions that do align confidently** —
   a feedback loop the pipeline currently lacks entirely (everything flows date → session → axis →
   placement; nothing flows back).
4. Additional landmark class: short formulaic session-opening resolutions, e.g. *"ontfangen een
   missive van resident/ambassador X houdende advertentie waarop geen resolutie is genomen"*.
5. **Entity order is informative for all entities, not just rare ones.** Because this is a
   sequence, a common entity still constrains the alignment path. Current scoring weights by IDF
   (`calculate_idf_weights`), which is right for identity matching and throws away order.
6. Long and short resolutions are reflected as such in *both* streams, so relative length is a
   usable proportional-placement prior.

## Stepped plan

### Step 1 — Landmark density in the HTR stream itself
<!-- status: done 2026-09-25 — GATE PASSED, with one claim quarantined -->

**Purpose:** the stream framing trades a tight-but-wrong local constraint (`k_e` per day) for a
loose one (`k_e` per inventory). Session landmarks must re-impose locality or the trade is a net
loss. This is the gate for the whole track.

Separate two things the project currently conflates: the session-date *ledger* status (T=1,012 of
4,916 rows, mostly N) is about enriched→HTR date *mapping* — the unreliable thing being escaped.
Whether a session *opening is detectable in the HTR text* is a different and probably better
question. Finding D gives a first answer (70.1%); extend it with the hypothesis-4 formulaic
opening class and the presentielijst/attendance-list marker class.

**Gate:** if landmark coverage is thin or unreliable, stop — the reframing is not usable even if
finding C is true.

**Result.** `scripts/landmark_density_eval.py` (+ `tests/test_landmark_density_eval.py`, 14/14
passing) → dataset `landmark_density_eval`. Thresholds were fixed in the script docstring before
the run; the day-partition arm reproduces the cited 11,644 ceiling and 535 no-HTR dates exactly,
and the one-segment-per-inventory arm reproduces finding C's 14,258, so the accounting between the
two bounds is validated rather than asserted.

**1. Session openings are near-universal in the archive.** Of 1,690 raw sessions in
`s4_session_date_region_scan`: 1,690 (100%) carry a `date` region, 1,687 (99.8%) as the session's
*very first* region; 1,211 (71.7%) carry an `attendance` region; 1,514 (89.6%) have an opening
region before their first `para`. The presentielijst class asked for in the step exists and is
already extracted. Availability is not the constraint.

**2. Localizability on the stream the segmenter actually reads is the constraint.** Landmarks must
land on `paragraph_axis_1626_1630` (1,316 flat sessions, 21,519 paragraphs), which is built from
`resolutions_flat` and therefore *excludes* the date/attendance regions:

| channel | flat sessions | share | needs date mapping? |
|---|---|---|---|
| `fingerprint_verified` (finding D, content-matched) | 939 | 71.4% | no — content, not label |
| `verified_with_attendance` (+ raw session has a presentielijst) | 808 | 61.4% | no |
| `formulaic_opening` (hypothesis 4, head 2 paragraphs) | 500 | 38.0% | no |
| `in_axis_president_or_present` (leaked attendance text) | 237 | 18.0% | no |
| `in_axis_president_and_present` (both stems) | 42 | 3.2% | no |
| union of all three classes | 1,132 | **86.0%** | no |

The classes are complementary, not redundant: `formulaic_opening` contributes 115 sessions the
fingerprint channel misses and the in-axis channel 100, which is why the union reaches 86%. The
in-axis channels are thin for a structural reason, not a tuning one — attendance material is
classified out of `resolutions_flat` upstream, so only leakage is visible (consistent with
`s6b_anchor_harvest.py`'s independently measured 130–167 sessions for the same stems).

**3. Verified landmarks are order-preserving — the decisive reliability result.** Across all five
annual inventories (3185–3189), **zero** non-monotone steps: every content-verified opening sits in
the same relative order in the flat stream and in the archive. Drift is large but *piecewise*:
80–99% of matched sessions carry a non-zero `raw_num − flat_num` offset, in only 5–11 runs per
inventory (mean run length 11–42 sessions). So the session *label* is wrong nearly everywhere while
the session *order* is intact everywhere — exactly the separation the step asked for, and the
property a sequence alignment needs. Only 4562 violates it (15 non-monotone steps, 40 offset runs,
mean run 4.97); it is already excluded from pooling by finding C's anchor-starvation note.

**4/5. Locality and headroom (read together — a coarser partition always raises the bound).**

| channel | segments | dates/segment | median segment `k_e` | vs day | segment ceiling | gain | gain, no-HTR dates isolated |
|---|---|---|---|---|---|---|---|
| day partition (baseline) | 1,594 | 1.00 | 12 | 1.00× | 11,644 | — | — |
| flat-session boundary | 1,060 | 1.50 | 14 | 1.17× | 12,591 | +947 | **+0** |
| `fingerprint_verified` | 749 | 2.13 | 16 | 1.33× | 12,973 | +1,329 | **+342** |
| `verified_with_attendance` | 642 | 2.48 | 17 | 1.42× | 13,197 | +1,553 | **+503** |
| `union_all_channels` | 910 | 1.75 | 15 | 1.25× | 12,777 | +1,133 | **+169** |
| one segment per inventory (finding C) | 7 | 227.7 | 2,655 | 189× | 14,258 | +2,614 | +1,667 |

**Gate: PASS.** `fingerprint_verified` keeps median segment `k_e` at 1.33× the day median (threshold
2×) and 2.13 dates per segment (threshold 3), is order-preserving, and opens real headroom. The
price is explicit: locality loosens ~2×, buying 1,329 of finding C's 2,614.

**The claim to quarantine.** Most of that raw gain is not "two real HTR days share a segment" — it
is **the 535 dates with no same-day HTR at all being absorbed into a neighbour**. The
`flat-session boundary` row proves it: +947 raw, **+0** once no-HTR dates are barred from borrowing
paragraphs. Absorbing them *is* the reframing's own hypothesis (a no-HTR date is a mislabelled
neighbour, not an empty one), but it is a much stronger claim than day-merging and it is not
evidence Step 1 produced. The gain that survives without it is **+342** (`fingerprint_verified`) to
**+503** (`verified_with_attendance`) — real, but *below* the Global-stretch gap of 718. So: the
reframing is usable, and it does not on its own close Global-stretch at honest locality.

Also note `deficit_absorbed_vs_day` and `ceiling_gain_vs_day` are the same number by construction
(`segment_ceiling == 19,120 − segment_deficit`), reported twice for readability — one finding, not
two. The independent quantity is the no-HTR-isolated column.

**Consequences for the rest of the track.** Step 1's mechanism is *not* "detect more openings" —
availability is already 100% on the raw side and 86% on the stream. It is **keying placement to
content-verified session order instead of the date label**, which finding 3 shows is safe to do.
Step 1 also supplies Step 4's missing prerequisite: the order-preserving verified chain is the
held-out-checkable scaffold Step 4 said it needed, and it already exists on disk. Step 5's honest
bound is now bracketed: 11,644 (day) < 11,986–12,147 (verified landmarks, no-HTR dates isolated) <
12,973–13,197 (verified landmarks, no-HTR absorbed) < 14,258 (free reallocation).

**Correction, same day: this note first ranked Step 4 ahead of Step 3, and that was wrong.** The
stated reason was that Step 3 "owes a gap/scoring design" — a readiness argument presented as a
value one. On value the ranking inverts: Step 3 attacks finding A's dominant loss channel
(collisions, 4:1 over extent) and finding B's 1,478 directly, while Step 1's order-preservation
result arguably *narrows* Step 4's target, since order is already intact among the 71.4% verified
and the correction loop's remaining work is mostly the unverified 28.6%. Step 3's design question
is now settled and parameter-free (see Step 3), so it is not blocked either. **Take Step 3 first**;
Step 4 stays queued with its prerequisite satisfied.

### Step 2 — Length-proportional placement prior
<!-- status: done 2026-09-25 — NEGATIVE, do not adopt -->

**Result.** `scripts/length_prior_eval.py` → dataset `length_prior_eval`. 37/50 gold days scored
(13 have no axis); 289 extent pairs. Extents are only defined where two *consecutive* resolutions
are both located, because gold is sparser than assumed: 41 of 373 boundary markers are unlocated
placeholders (no `flat_id`, null `char_offset`) parked at the day's last paragraph index.

| | all 37 days (289 pairs) | review-code S only, 19 days (146 pairs) |
|---|---|---|
| Spearman, enriched chars vs HTR chars | 0.219 | 0.271 |
| Spearman, within-day share | 0.172 | 0.345 |
| per-day Spearman mean / median | 0.119 / 0.091 | 0.204 / 0.103 |
| days with positive per-day Spearman | 18/30 | 11/15 |
| mean \|displacement\|, **uniform** | **3.439** | **1.491** |
| mean \|displacement\|, proportional | 3.939 | 2.418 |

**Hypothesis 6 is directionally true but too weak to use.** The correlation is positive, consistent
in sign (11/15 clean days), and — as a good internal check — *stronger* on clean days than on all
days (0.271 vs 0.219; share 0.345 vs 0.172), exactly as expected if day-quality noise attenuates
it. But at ρ≈0.3 a *deterministic proportional allocation* is worse than uniform on both cohorts,
and worse by more on the clean days (1.491 → 2.418). Uniform spacing is the minimum-variance choice
under uncertainty; allocating proportionally on a weak predictor moves cuts far off-centre on a
signal that is only slightly better than chance. **Do not change `segment_gap`'s uniform `ideal`.**

Likely reason the signal is weak: the enriched text is an editorial *summary*, so its length
encodes editorial verbosity as much as original extent. A different length proxy is a different
hypothesis, not a rescue of this one.

**What this result does *not* rule out** (limits of the test, stated so a later session doesn't
over-read the verdict):

- **Only a hard, fully-deterministic allocation was tested.** Cuts were placed at exact cumulative
  enriched-length shares. A *shrunk* prior — `λ·proportional + (1−λ)·uniform` with small λ — was
  not tested and is the standard remedy for a real-but-weak predictor; at ρ≈0.3 it would be
  expected to land between the two, i.e. no worse than uniform rather than better. Worth one cheap
  sweep if anyone revisits, not worth a track of its own.
- **The A/B is anchor-free by construction.** It places cuts across a whole day from its structural
  bounds alone, whereas in production this prior only fires *inside* anchor-bracketed gaps, which
  are much shorter. Absolute displacements would therefore be smaller in production; what carries
  over is the *ranking* (uniform beats proportional), which is consistent across both cohorts.
- **Modest sample.** 289 extent pairs over 37 days, 146 over the 19 clean days, and gold's located
  markers are not a random subset of resolutions — annotators located the ones they could.

**Side finding — `separated` cannot discriminate placement rules on gold.** Uniform spacing scores
170 separated on the clean days against gold's own 111 (of 197); all-days, 293 vs 228 (of 477). A
trivial even spread beats the ground truth on the project's own criterion, because the criterion
rewards spreading irrespective of correctness and gold carries duplicate/unlocated slots. This
confirms the guardrail above empirically: any future placement A/B on this track must be scored by
displacement (or another correctness-sensitive measure), never by `separated` alone.

Cheapest concrete item on the list, independent of Steps 1/3. `segment_gap`'s `ideal` is *uniform*
spacing (`s6c_gap_segmentation.py:76`) — it assumes every resolution in a gap is the same length.
Hypothesis 6 says enriched text length predicts HTR extent. Measure that correlation first on gold
days; if it holds, make `ideal` proportional to enriched length instead of uniform.

This touches only the default that fires when evidence is absent — i.e. exactly the path
responsible for finding A — and does not involve the entity-density mechanism that sank Group B.

### Step 3 — Order-constrained alignment over all entities
<!-- status: designed 2026-09-25 — ready to build, gate defined -->

Hypothesis 5. Note this is **not** a rerun of the closed Group-B experiments: those fed entity
*density* into `position_scores` and failed because density clusters multiple resolutions onto the
same evidence-rich paragraph (measured: collisions rose in 11/11 affected gold days). An *order*
constraint is monotone by construction and is therefore inherently collision-resistant — it
attacks finding B's 1,478 directly rather than aggravating it.

~~Design question to settle before building: dropping IDF weighting makes the alignment alphabet
much denser, so local ambiguity and cost both rise. Needs a real gap/scoring design, not just
removing the weight.~~ **Settled 2026-09-25 (user).** The open question was self-inflicted: it
assumed the experiment needs a scoring scheme, so a *parameter-free* formulation dissolves it. It
was also being used as a reason to rank Step 4 first — a readiness argument, not a value one; see
the corrected note under Step 1.

#### Diagnosis — read this before touching the aligner

Three facts from the live code and already-measured numbers, not from this plan's prose:

1. **No entity sequence is aligned anywhere today.** `align_session`
   (`build_alignment_new.py:900`) runs Needleman-Wunsch over the **resolution** sequence
   (`enriched_ids` × `flat_ids`). Entities enter only as a bag inside each cell —
   `sum(idf_weights.get(e, 1.0) for e in shared_entities)` (`:931`), a `set`. Order of mentions
   *within* a resolution is discarded and an entity is never a sequence position. So hypothesis 5
   is not merely untested in this repo, it is **untestable in this code**: the unit of the sequence
   is the resolution.
2. **The anchor gate is why order buys nothing at present.** `anchor_only_diagonal=True` sends any
   cell with zero shared entities to `NO_ANCHOR_DIAG_SCORE` (`:938-941`) — a resolution pair with
   no entity overlap cannot be matched at all. With mean entity containment at 0.295 (S1-D1) that
   gate is shut most of the time, and an order constraint cannot rescue a cell that is already
   closed. Any Step 3 build that keeps the gate will measure the gate, not the hypothesis.
3. **Entity identity is binary end to end, and the binary signal is measurably non-discriminating.**
   The overlap tables keep a 4-way provenance category (`match_kind` ∈ `canonical` / `variant` /
   `tag_text` / `surname_token`) and **no similarity column** — the graded distance is computed at
   build time and thrown away, so `Frankrijk` ↔ `Vranckryck` is stored indistinguishably from an
   exact hit. Downstream, `nw_matches_gt_rate` is 0.957 for correct pairs and 0.962 for false
   positives (PLAN.md, "Hypothesis"): the existing per-cell entity evidence separates correct from
   incorrect pairs essentially not at all. Step 3 is therefore attacking a measured null, not a hunch.

#### The change

Move the sequence's unit from **resolution** to **entity mention**: one symbol per mention, in
reading order, on both sides. A dense stream of many low-value symbols carries positional constraint
that a sparse stream of set-intersections cannot — which is the whole of hypothesis 5, and the
reason it needs the entity as the unit.

**Run it inside `s6b_known_point_ledger.py`'s open gaps** (947 gaps holding 5,302 of 7,504 unplaced
resolutions, 70.7%), not across an inventory and not across Step 1's landmark segments. Rescoped
2026-09-25 on the global→local argument: the global chain already localises the uncertainty, each
gap arrives with its count constraint attached, and the gap is exactly where today's model is
weakest — `segment_gap` fills it by *uniform interpolation with a phrase-hit nudge*
(`s6c_gap_segmentation.py:76`), which is not an alignment at all.

That reframes this track's negative results as a single finding: **both terms of the in-gap cost
have been tuned to exhaustion and neither is an alignment.** Five `position_scores` variants (Group
B/C, relocated, grounded, candidate-grounded) tuned the *bonus* term — all net negative. Step 2's
length prior tuned the *ideal* term — negative, uniform won. Nobody has replaced the interpolation
itself. The failures are evidence that tuning a non-alignment does not pay, not that local work does
not.

#### First experiment — unit-cost edit alignment, deliberately parameter-free

Levenshtein distance **is** this DP with degenerate parameters: unit substitution, unit symmetric
gap, minimise instead of maximise. That makes it the wrong choice on the *resolution* sequence (it
would delete IDF and the gap structure) and the right first instrument on the *entity* sequence: no
IDF, no gap tuning, no anchor gate, so it tests order in isolation with nothing to tune first.

- **Keep the traceback, not just the scalar.** Cut points must project *through* the alignment onto
  HTR positions, exactly as the S4 entity-NW design intends; the path is the deliverable and the
  distance is only its score.
- **Fix before running: gap asymmetry.** The enriched side is an editorial *summary* and carries far
  fewer mentions than the HTR, so unit symmetric costs (`gap_penalty=0.1` on both `up` and `left`,
  `build_alignment_new.py:944-945`) let gap cost dominate and the result becomes uninterpretable.
  Minimum viable fix: cheap HTR-side skips, or normalise by the longer sequence. This is the one
  default that must not be inherited.
- **Accept as-is: transposition over-penalisation.** Levenshtein charges 2 edits for a swap, while
  D1c measured a 2–3 position transposition band (Kendall τ 0.638, 64.3% of tier-1 pairs at τ ≥ 0.8).
  So the metric systematically over-penalises reordering the corpus says is routine. This biases
  **against** hypothesis 5, which makes a positive result trustworthy and a negative one only
  suggestive. Damerau buys adjacent swaps at cost 1, still not the measured 2–3; a banded,
  transposition-tolerant cost is the eventual design, not the first test.

#### Prior art to borrow from — only *after* the first experiment reports

**Guard: none of this changes the first experiment.** It stays unit-cost, parameter-free, with the
single gap-asymmetry fix named above. This subsection is a menu to be opened only if that run beats
the null, and then one item at a time — reading it as a build list would rebuild the "design a
scoring scheme before testing the hypothesis" blocker that the parameter-free formulation just
removed.

Read 2026-09-25 (Prousalis et al., "A Survey on Sequence Alignment Algorithms and State-of-the-Art
Aligners", ACM CSUR 2025) as a map to primary references. Its MSA half does not apply — this problem
is pairwise, one enriched stream against one HTR stream — but four items in its pairwise section
replace pieces left open above. **None of this is evidence about this corpus; it changes design
options, not findings.** Borrow the scoring *models*, not the tooling: STEP_S6's decision not to
adopt an off-the-shelf bioinformatics library stands, because the alphabet is not nucleotides.

- **Adaptive seeds (LAST, Kiełbasa et al. 2011)** answer the dense-alphabet objection directly:
  seeds are chosen *by rareness*, extending until rare enough, which is designed for "sequences with
  arbitrarily nonuniform composition". That is the IDF-vs-order tension in hypothesis 5, and it is a
  better mechanism than down-weighting or discarding common symbols. Preferred over the
  band-plus-masking sketch if the first experiment justifies building further.
- **Concave gap cost (minimap2, Li 2018)** is the published answer to the gap-asymmetry fix named
  above. Concave rather than merely affine (Gotoh 1982) is the shape that fits long indels, i.e.
  this corpus's many-enriched-to-one-HTR structure under 81.1% under-segmentation. Note minimap2's
  seed–chain–extend with the Suzuki-Kasahara formulation is the reference implementation of what
  STEP_S6 arrived at independently — corroboration of that design, not a reason to switch tools.
- **Semi-global alignment (free end gaps)** is the standard formalism for terminals that need not
  match, "when one sequence is a subsequence of another or when the sequences share significant
  regions of similarity with differing lengths at the ends". That is exactly the cross-day spillover
  case this project handles ad hoc — the 7 cross-day-shift days and S3's `|||END|||` /
  "continues from a previous day" annotations.
- **MUM + LIS (MUMmer/NUCmer, Delcher et al. 1999)** — maximal unique matches ordered by Longest
  Increasing Subsequence, then gaps closed between them — is architecturally identical to
  `s6b_known_point_ledger.py`'s chain-then-fill-gaps structure. LIS is the off-the-shelf way to
  extract a maximal colinear subset from noisy anchors, so it is the standard treatment for 4562's
  15 non-monotone verified landmarks (Step 1 finding 3).

One corroboration, no action: the survey's "seeding is the bottleneck for short sequences while
banded D.P. is the bottleneck for long sequences" matches what this project measured twice
independently (the S6 Step-1 oracle diagnostic and the S6b anchor-supply harvest both found
placement binds, not supply).

A fifth item, **MAPQ-style placement confidence**, is logged separately under
`docs/METRICS.md` "Proposed, not yet computed" rather than here — it applies to every placement the
pipeline emits, not only to Step 3's.

#### Second, and only conditionally

A **graded substitution cost** between non-identical entity symbols — the information finding 3
shows is currently discarded — but only if the parameter-free run beats the 0.957-vs-0.962 null.
Both surfaces are already on disk in the ~19k overlap rows, so the distance can be recomputed
without rebuilding anything. Requirements learned the hard way here: length normalisation, a
minimum match length, and ideally HTR-confusion-weighted operations (u/v, i/j/y, c/t, long-s,
abbreviation marks) rather than unit edits — `Frankrijk`/`Vranckryck` is 5+ raw edits but roughly
one systematic orthographic transform, and plain Levenshtein at `levenshtein_threshold=0.6`
produced garbage ("ende"/"heeren" matching short place and person names, 2026-09-19 session). Note
`track-b-name-matching` (soundex/Levenshtein name reranker) was closed 2026-09-23 **unmeasured, on
a prior** — this is not a repeat of a negative result, and soundex is a sound complement because HTR
errors are often phonetically neutral.

#### Gate

Fold into Step 3's own run rather than adding a step: **re-run D1c stratified by IDF band**. If
common-entity order consistency is comparable to rare-entity, hypothesis 5 holds and the entity-stream
alignment is worth building out; if it is near-random, Step 3 closes for the price of one diagnostic.
The same run tests the competing explanation — at containment 0.295 the binding scarcity may be
*recall on the matched side* rather than alphabet density, in which case a denser alphabet is a
non-problem and the whole objection above was moot.

#### Constraints

- **Do not re-weight `calculate_idf_weights` in place.** It is defined at
  `build_alignment_new.py:767` and consumed by six further call sites including the production
  alignment path (`build_alignment_new.py:1305`, `session_chain_alignment.py:1436`,
  `analyze_sequence_entity_overlap.py:784`, `sequence_review_ui.py:402-403`,
  `build_pin_coverage_report.py:72`, `discover_session_tri_anchors.py:1270`). Add a scoring path
  alongside it, or the experiment silently shifts tier composition across the whole pipeline.
- **Bounded upside regardless.** ~70% of enriched entities have no HTR counterpart (containment
  0.295) and no metric creates one. The nearest measured analogue is discouraging: for *phrases*,
  fuzzy matching at 0.85 added zero hits beyond the exact top-20, i.e. missing families rather than
  orthographic variation were the coverage gap. Phrases are not entities, so this is a caution, not
  a verdict.
- **Score by correctness, never by `separated`.** Step 2's side finding stands: a trivial even
  spread beats gold's own annotations on the `separated` criterion, so it cannot discriminate
  placement rules.

### Step 4 — Close the anchor-correction loop
<!-- status: pending -->

Hypothesis 3, building on finding D's existing content-verified data. Risk to control: bootstrapping
from confident alignments can amplify bias if the confident set is skewed (tier-1 anchors
concentrate on entity-rich resolutions). Needs a held-out check, not just convergence.

### Step 5 — Restate the state in alignment terms, then re-derive the bound
<!-- status: pending — rescoped 2026-09-25 (user), was "re-derive the ceiling honestly" -->

Originally scoped as re-deriving the pigeonhole bound alone. Widened on the observation that the
alignment is now good enough over most of the corpus to be treated as a **scaffold** rather than as
the object of work: freeze it, call what remains gaps, and attack the gaps. Re-deriving a bound is
then only one part of describing where we are.

**Guardrail, unchanged and now load-bearing: this does not restate PLAN.md's acceptance table.**
Tier O is the criteria; this is a Tier P diagnostic vocabulary reported *alongside* them. Finding C
is still a reason to investigate, not a licence to change the denominator.

#### 5a. The re-expression (no new compute — all figures are already on disk)

| current term | alignment equivalent | current value |
|---|---|---|
| days predicted | breadth of coverage | 100% of days with an axis; 1,059 / 1,594 dates |
| `separated` | uniquely-placed, bounded-length | 8,015 — 41.9% of all / 68.8% of bound |
| collision | multi-mapping pile-up | 4,722 slots (32.6%) |
| severe collapse | extreme pile-up | 79 days with 7+ on one paragraph, max 24 |
| extent > 3 | over-long / spurious alignment | 1,426 slots (9.9%) |
| ceiling 11,644 | positions mappable under the current reference partition | a length bound, not an accuracy |
| 535 no-HTR dates | no template — uncovered, not misaligned | keep as its own class |
| 947 open gaps | unassembled regions between anchors | hold 70.7% of unplaced work |
| tier1/2/3 | anchor *evidence class* | explicitly **not** mapping quality |
| — | placement margin (MAPQ analogue) | not computed — `docs/METRICS.md` |
| — | accuracy vs gold, corpus-wide | not computed |

#### 5b. Why the baseline cannot simply be frozen at 68.8%

**`separated` is a coverage criterion, not an accuracy criterion.** It tests uniqueness of the start
paragraph plus extent ≤ 3; it never tests whether the placement is right. Step 2 measured the
consequence directly: a trivial uniform spread scored **170 separated on the clean gold days against
gold's own 111**. Ground truth loses to an even spread. In the alignment vocabulary above, 8,015 is
"mapped somewhere unique" — MAPQ > 0 — and says nothing about correctness.

The figure that *does* support calling the alignment good is a different one:
`char_axis_boundary_f1_lumped` = **0.826** — the model picks the right paragraph ~83% of the time,
with nearly all of the residual being sub-paragraph precision. That is an accuracy measure, on 19
scoreable gold days, not corpus-wide.

#### 5c. Three conditions before the scaffold framing is adopted

1. **Verify before freezing.** Gap-filling around unverified anchors propagates error both ways — a
   wrong anchor corrupts the gap on each side of it. Gold exists; measuring accuracy on the
   separated set is cheap and is the precondition for treating 68.8% as scaffold rather than claim.
2. **Keep the two gap classes apart.** The 947 anchor-to-anchor gaps are a *filling* problem; the
   535 no-HTR dates are a *no template at all* problem. Conflating them is exactly what inflated the
   Step 1 ceiling by 947 (see Step 1's quarantined claim).
3. **Score gap-filling by correctness, never by `separated`** — the standing track guardrail, and
   doubly so for the metric that lost to an even spread.

#### 5d. Sequencing

5a (re-expression, free) → 5c.1 (verify the baseline on gold, cheap) → gap-filling, which **is**
Step 3's local alignment scoped to the 947 gaps rather than a separate step. The bound re-derivation
that was this step's original whole scope becomes its last item, and Step 1 already brackets it:
11,644 (day) < ~11,986–12,147 (verified landmarks, no-HTR isolated) < 12,973–13,197 (no-HTR
absorbed) < 14,258 (free reallocation).

## Revaluation note

Several closed items were closed on a value judgment made *under the day framing*, where a
session-opening detector mostly restates what the date already tells you. Under a stream framing
such a detector becomes the primary scaffold. If Step 1 passes, re-examine (do not auto-reopen):
`short-resolution-alignment` (retired 2026-09-22, formulaic `align_short_resolutions.py` — exactly
hypothesis 4's class), and the presentielijst/attendance-list marker machinery in the sibling
`republic` repo (`republic/analyser/attendance_lists/`), which is a session-opening detector built
around explicitly enumerated HTR corruption forms.

**Triggered 2026-09-25 by Step 1's PASS, with the two items now pointing opposite ways:**

- `short-resolution-alignment` — **re-examine.** Its `OPENING_PHRASES`, reused unchanged as Step 1's
  `formulaic_opening` channel, detect an opening in 500/1,316 stream sessions (38.0%) and contribute
  **115 sessions no other channel reaches**. That is standalone landmark value the retirement
  judgment could not have seen, because under the day framing it duplicated the date.
- presentielijst machinery in the sibling `republic` repo — **probably unnecessary.** Step 1 finding
  1 shows the attendance class is already extracted and near-complete on the raw side (1,211/1,690
  sessions, and `date` regions at 100%) in `s4_session_date_region_scan`. The bottleneck is not
  detecting presentielijsten in HTR; it is that `resolutions_flat` classifies them *out* of the
  stream the segmenter reads (only 18.0% leakage visible in-axis). A better detector upstream does
  not fix a stream that excludes the region by construction — projecting the regions already in hand
  onto the axis would.

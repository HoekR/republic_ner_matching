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
- **The enriched edition ends 1630-05-14; do not extend beyond it** (user, 2026-09-25). The HTR axis
  runs to 1630-12-31, so 184 sessions / 2,284 paragraphs (10.6%) are out of scope. The day partition
  excluded them for free by keying on enriched dates; **a stream framing does not**, so any step that
  pools paragraphs along an inventory must bar them explicitly. Measured and enforced under Step 6
  finding 5.

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
<!-- status: blocked 2026-09-25 — gate no_data; control has only 26 common-band pairs -->

**Gate checkpoint (2026-09-25).** The IDF-band D1c tests pass, and the real common-band tau is
0.809 versus 0.103 for the deliberately mismatched control. The control has only 26 common-band
pairs, below the fixed minimum of 50, so the verdict is **`no_data`**, not a pass or fail. Do not
build the entity-stream aligner or weaken the threshold; obtain a defensible control with at least
50 common-band pairs before reopening this step.

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
  default that must not be inherited. **Direction is level-specific — do not carry one level's
  asymmetry to the other:** at the *entity-mention* level HTR-side skips are cheap (the summary
  drops detail the HTR keeps); at the *resolution* level the asymmetry inverts, see the next bullet.
- **Resolution level: deletion is the norm, insertion is not a modelled event** (user, 2026-09-25;
  "this is where it differs from aDNA procedures" — aDNA reads carry genuine insertions, editorial
  summaries of a fixed archive do not). An *enriched* resolution with no distinct HTR unit is
  routine: that is 81.1% under-segmentation (S1-D1), the deletion case. The converse — an HTR
  resolution whose content appears in no enriched resolution — has never been observed.

  Checked against gold rather than accepted on assertion (2026-09-25, artifacts on disk, no replay):
  `boundary_gold_sample`'s instructions are *"place K_e − 1 boundary cut points over the ordered
  flat_ids/paragraph stream"*, and its slot vocabulary is `kind ∈ {cut, start, end_of_last_resolution}`
  with `has_trailing_spillover` (13 slots) and `starts_mid_resolution` (3 days). **There is no
  annotation category for an HTR span belonging to no enriched resolution.** The ground truth's own
  design is a surjection of the stream onto exactly `K_e` contiguous spans, with cross-day spillover
  as the only escape — so the no-insertion prior is not merely consistent with gold, it is gold's
  construction.

  **The trap: a penalty alone is the wrong encoding, because `K_f > K_e` is common.** On 10 of the
  50 gold days the flat stream has *more* records than the day has resolutions (1626-11-16: 47 flat
  vs 14 enriched; 1626-10-27: 26 vs 11). Under a strict one-to-one NW those surplus flat records
  *must* take enriched-side gaps, so raising the insertion penalty does not suppress them — it buys
  them off by forcing surplus records into **wrong substitutions** with enriched resolutions they do
  not belong to. The surplus is HTR **over**-segmentation (one resolution split across several flat
  records), the mirror of the 81.1% under-segmentation, and neither is an insertion.

  **Therefore encode it as a structural constraint, not a cost.** The model must be able to express
  *many-to-one in both directions* — a run of consecutive HTR units attaching to one enriched
  resolution at low cost, and a run of consecutive enriched resolutions attaching to one HTR unit —
  while an HTR unit attaching to *nothing* is disallowed outright rather than made expensive. That
  is a monotone many-to-many (stepwise) alignment, not Levenshtein with reweighted gaps. Concretely
  for the first experiment: keep unit costs, but forbid the enriched-side gap move and give the
  HTR-side "stay on the same enriched resolution" move zero or near-zero cost. **Consequence for the
  prior-art menu below: `concave gap cost` is promoted from optional to the natural fit** — a
  concave penalty is exactly "one long run of unmatched-but-attached HTR material costs little more
  than a short one", which is this corpus's shape. Semi-global (free end gaps) stays the right
  treatment for the cross-day spillover that gold does mark.
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
<!-- status: 5a + 5c.1 done 2026-09-25; bound re-derivation still pending — rescoped 2026-09-25 (user), was "re-derive the ceiling honestly" -->

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

   <!-- status: done 2026-09-25 — CONDITION MET, scaffold framing cleared -->

   **Result.** `scripts/separated_accuracy_eval.py` (+ `tests/test_separated_accuracy_eval.py`,
   20/20 passing) → dataset `separated_accuracy_eval`. 35 of the 50 gold days scored (13 have no
   axis at all, 2 have no paragraph attribution); 421 scoreable rows, 312 of them with a
   gold-located start. Scored by exact start-paragraph agreement and absolute paragraph
   displacement — no tolerance-family metric. Resolution index 0 is held out of every cohort
   (35 rows): both the concordance and gold put it at paragraph 0 by construction, so scoring it
   would hand each cohort a free hit.

   | cohort | n | exact | within 1 | mean displacement | uniform-null exact | uniform-null displacement |
   |---|---|---|---|---|---|---|
   | all attributed | 312 | 0.503 | 0.772 | 2.32 | 0.189 | 3.58 |
   | **separated** | 191 | **0.628** | **0.869** | **1.86** | 0.267 | 2.86 |
   | not separated | 121 | 0.306 | 0.620 | 3.03 | 0.066 | 4.72 |

   **1. `separated` does carry an accuracy signal — it is not only a coverage criterion.** A
   separated placement is right **twice as often** as a non-separated one (0.628 vs 0.306 exact)
   and its errors are much tighter (0.869 vs 0.620 within one paragraph; mean displacement 1.86 vs
   3.03, median 0 vs 1). The loss-reason split behaves the same way in both directions: collision
   losses score 0.299 exact and extent losses 0.357, against the separated set's 0.628. So
   selecting on `separated` genuinely selects better placements, which is what the scaffold
   framing needs. This does **not** retract §5b — `separated` still cannot *rank* placement rules
   (see finding 3), but it can *select* placements, and those are different jobs.

   **2. Production beats the uniform null decisively, on correctness.** This is the answer §5b left
   open: Step 2 had only shown uniform winning on `separated`, a metric it games. Scored by
   correctness instead, `segment_gap`'s own output beats an even spread by **2.4×** on the
   separated cohort (0.628 vs 0.267) and **2.7×** overall (0.503 vs 0.189). The placement carries
   real alignment signal; the earlier result was an artifact of the metric, not a statement about
   the model.

   **3. Step 2's side finding survives the gold-convention correction, but narrowed.** Recomputed
   on the 15 gold days where every resolution is located (144 resolutions): gold's own annotations
   score **103** separated, production **104**, uniform **115**. Uniform still out-scores ground
   truth, so the guardrail stands unchanged — but production lands *on top of* gold rather than
   above it, i.e. it is not gaming the criterion. (Step 2 reported 170 vs 111 on a differently
   defined day subset; the numbers are not directly comparable. See the convention note below.)

   **4. The corpus splits sharply by gold's own review code, and the split is the expected one.**

   | review code | rows | exact | within 1 | mean displacement | uniform-null exact |
   |---|---|---|---|---|---|
   | S (segmentable) | 158 | 0.639 | 0.911 | **0.72** | 0.335 |
   | C (cross-day shift) | 58 | 0.517 | 0.845 | 0.79 | 0.069 |
   | M (missing HTR) | 96 | 0.271 | 0.500 | **5.87** | 0.021 |

   On the days gold calls segmentable, the model puts the resolution in **the right paragraph 64%
   of the time and within one paragraph 91% of the time, median displacement 0**. Essentially all
   of the corpus-wide degradation is the M cohort, whose mean displacement is 8× the S cohort's.
   Note these M rows *do* receive placements: `axis_for_date` falls back to a resolved neighbouring
   session when the calendar day has no HTR, so a day PLAN.md counts under the accepted
   `missing_htr` ceiling can still be handed an axis and placed on it — badly. **That is a concrete,
   newly-localised defect**, and it is the same class of thing as Step 1's quarantined claim
   (no-HTR dates borrowing a neighbour's paragraphs). Worth its own item; see the note under §5d.

   **Sample caveat, stated so the numbers are not over-read.** The gold sample is stratified by
   `|K_e − K_f|` and deliberately over-weights hard days: 25 of the 35 scored days are `diff_3plus`,
   against 2 at `diff_0`. These figures are therefore pessimistic relative to the corpus, not
   optimistic. Reassuringly the separated share of scoreable gold rows (59.4%) tracks the
   corpus-wide separated share of attributed slots (57.5%, finding A), so the cohort split itself
   is not unrepresentative.

   **Convention correction found while building this** (recorded because it affects an existing
   result, not to reopen it). `scripts/length_prior_eval.py`'s `gold_starts` — Step 2's gold
   adapter — reads `boundaries[j]` as resolution *j*'s start. The canonical convention, already
   implemented in `scripts/s6a_char_axis_evaluation.py` and used here, is that cut *c* opens
   resolution *c+1*, that a `paragraph_boundary` slot sits at the *end* of its paragraph and so
   opens `index + 1`, and that `end_of_last_resolution` (13 slots) and leading `start` slots (8
   days) are not cuts at all. Step 2's A/B therefore scored both arms against a shifted reference.
   Its *ranking* conclusion (uniform beats proportional) is likely robust — both arms were shifted
   identically — but its absolute displacements are inflated and its `gold_separated_ceiling` is
   distorted. **Do not re-open Step 2 on this alone; do re-derive its numbers if anything is ever
   built on them.**

   **Verdict: condition 1 is met. The separated set is accurate enough to act as a scaffold**, with
   the qualification that the scaffold is trustworthy on S/C days and not on M days.
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

**5a and 5c.1 are both done (2026-09-25).** 5a is the table in §5a, written from figures already on
disk; 5c.1 is the measurement recorded under condition 1 above. The scaffold framing is cleared,
with one carve-out and one new item:

- **Carve-out: exclude review-code-M days from the scaffold.** 5c.1 finding 4 measured mean
  displacement 5.87 paragraphs on days with no same-day HTR, against 0.72 on segmentable days.
  Freezing those as anchors is precisely the "wrong anchor corrupts the gap on each side" failure
  condition 1 exists to prevent. Condition 2 (keep the two gap classes apart) already says to hold
  the 535 no-HTR dates as their own class; 5c.1 turns that from hygiene into a measured requirement.
- **New item, not yet scoped: `axis_for_date`'s neighbour fallback places resolutions on days that
  have no HTR of their own.** The fallback is deliberate and correct for the case it was written
  for (`docs/DECISIONS.md` 2026-09-22, a thin same-calendar stub coexisting with a richer resolved
  session), but its output on M days is measurably poor, and those placements flow into the
  concordance and therefore into the separated count. Whether to suppress them, or to keep them and
  mark them low-confidence, is a real decision with a headline-number consequence — not a bug to
  fix silently. Size it before acting: 96 of 421 scoreable gold rows are M, but the corpus-wide
  share is unmeasured.

Next: **Step 3**, the entity-stream edit alignment scoped to `s6b_known_point_ledger.py`'s 947 open
gaps, built under the no-insertion structural constraint recorded in Step 3's bullets — and scored
against 5c.1's numbers as the baseline to beat (exact 0.639 / within-1 0.911 on S days), never
against `separated`.

### Step 6 — Session-level sequence alignment between the two streams
<!-- status: done 2026-09-25 — GATE DID NOT PASS; do not build the aligner. Premise overturned below. -->

**Result (2026-09-25).** `scripts/session_offset_eval.py` (+ `tests/test_session_offset_eval.py`,
13/13 passing) → dataset `session_offset_eval`. Thresholds were fixed in the script docstring before
the run. Verdict **INCONCLUSIVE** on those thresholds, and the reason matters more than the verdict:
**Step 6's factual premise does not hold for the main corpus.**

Sessions dated after the enriched edition ends are barred from the stream (see finding 5), so
these are in-scope counts:

| inventory | sittings | resolved | axis sessions (in scope) | unresolved | unclaimed sessions |
|---|---|---|---|---|---|
| 3185 | 216 | **216** | 184 | 0 | 0 |
| 3186 | 218 | **218** | 200 | 0 | 2 |
| 3187 | 276 | **276** | 275 | 0 | 4 |
| 3188 | 271 | **271** | 266 | 0 | 5 |
| 3189 | 108 | **108** | 109 | 0 | 1 |
| 4562 | 187 | 34 | 98 | 153 | 67 |
| 4861 | 191 | 0 | 0 | 191 | — |

**1. In the five annual inventories every enriched sitting already resolves to an HTR session**
(1,089/1,089), and the concordance carries **zero `missing_htr` rows** there. All 344 unresolved
sittings — all 4,482 resolutions — are in 4562 (2,095) and 4861 (2,387): the two non-annual "secret
resolution" series PLAN.md's Local criterion already excludes as structurally HTR-poor. 4861 has no
axis sessions at all, so no aligner can reach it; 4562 has 102 sessions for 187 sittings and is the
outlier finding C excluded from pooling and Step 1 found carrying the only 15 non-monotone landmarks.

**2. The motivating "29.4% of the corpus" decomposes into two things that are not alike.** Of the
cited 5,619, the 4,482 `missing_htr` are the mass in 1 above; the 1,137 `cross_day_shift` on 74 dates
are **not unmapped at all** — every one carries a `resolved_session_id`, to a session whose date label
differs. 69 of those 74 dates are in the annual inventories. Whether those pins are *correct* is a
different question this diagnostic does not answer (see the caveat below).

**3. The mechanism is confirmed, on a population too small to carry the step.** Three sittings
(40 resolutions, all 4562) sit in *determined* brackets, where equal counts of unresolved sittings and
unclaimed sessions between two pins force the pairing by monotonicity alone. All **3 of 3** are beyond
the ±1-day window — at **20, 22 and 36 days**. So order does reach correspondences the date label
provably cannot, exactly as hypothesised. It reaches 40 of 19,120 resolutions, against a
Global-stretch gap of 718.

**4. The no-insertion claim, verified at session level as the design notes required rather than
carried over on faith: nearly true, not exactly.** 51 of the 1,132 in-scope axis sessions (4.5%) are
bracketed by claimed sessions on both sides with no enriched sitting available to claim them —
3186:2, 3187:4, 3188:5, 3189:1, **4562:39**. Outside 4562 that is 12 sessions (1.2%). So the
constraint is safe to encode in the annual inventories and is broken by 4562, the same inventory that
breaks order preservation. Do not assume it; it is now measured.

**5. Scope constraint, confirmed by the user 2026-09-25 and now enforced: the enriched edition ends
1630-05-14, and the alignment does not extend beyond it.** The HTR axis runs to 1630-12-31 and carries
**2,284 paragraphs (10.6% of 21,519) over 184 sessions** past that date — 180 in 3189, 4 in 4562.
That is why 3189 shows 289 axis sessions against 108 sittings.

`session_offset_eval.py` now drops those sessions from the stream before bracketing (cut-off read
from the data, not hardcoded) and **asserts that no sitting resolves into them**. Today that count is
**0**, so the bar costs nothing and exists to catch a widened `axis_for_date` fallback later. Two
checks behind the enforcement:

- *It changes no gate quantity* — 3 forced pairings, 100% beyond window, 51 no-insertion sessions,
  same verdict. The Step 6 finding is robust to it. What it does change are denominators: axis
  sessions 1,316 → 1,132 and unclaimed sessions 263 → **79**.
- *Upstream is already safe.* `metrics_local_inventory_ceiling` and `landmark_density_eval` both key
  paragraph counts on enriched dates (`date_sequence` joins `paragraph_count` on `enriched_date`), so
  the 11,644 day ceiling, finding C's 14,258 and Step 1's segment ceilings never included this
  material. 3189's 1,579 paragraphs in finding C's table is exactly its in-scope count.

**The trap this guards, and why it is not hypothetical.** 3189's 180 post-edition sessions are
*trailing*, so bracket geometry isolated them anyway. 4562's 4 are **not** — they sit inside ordinary
brackets, where without the bar they could be offered to an unresolved sitting dated years earlier
(the regression test forces exactly such a pairing at >900 days). Any future work that pools an
inventory's paragraphs along the stream — finding C's framing, and Step 5's pending bound
re-derivation — must apply this bar explicitly, because the day partition applied it for free and a
stream framing does not. A naive "sum all axis paragraphs per inventory" would hand 3189 3,858
paragraphs instead of 1,579.

*Method note:* a first pass counted the trailing sessions as no-insertion violations, inflating that
figure from 51 to 232. Read the span before counting the surplus.

**Read the ordinal offset with its conflation, not as drift.** The per-sitting
`htr_ordinal − enriched_ordinal` runs to −32 (3185) with 94% beyond ±1, but the two sequences have
genuinely different lengths, so the offset absorbs multiply-claimed sessions as well as any drift.
It is reported as context. The decisive quantities are 1–4. (The 67 sessions claimed by 2+ sittings
are consistent with the 68 already recorded under the 2026-09-23 cross-date uniqueness policy — not
a new finding.)

**Caveat, stated so the verdict is not over-read.** That a sitting is *pinned* does not mean it is
pinned *correctly*. This closes "the session mapping is **absent**" as a motivation for Step 6; it
does not settle "the session mapping is **wrong**". A cheap follow-up exists and is not done: for
pinned sittings, compare the enriched date against the date of the *content-verified raw* session
(`s6b_session_fingerprint_match`) rather than against the flat label the concordance already used.
70 pinned sittings already resolve to a session whose label is more than a day away, so the
population to check is identifiable.

**Consequence: Step 3 is next**, which is where the track's own gate said it would go if Step 6
closed — reached by a different route than the gate anticipated.

<!-- Original proposal below, kept as the record of what was tested. -->
<!-- status: proposed 2026-09-25 (user) — checked as genuinely missing, not already built -->

**Hypothesis 7 (user, 2026-09-25).** Align the *enriched sitting sequence* against the *HTR session
sequence* as sequences, and use the matched session openings as anchors in the resolution stream.
Posed as "if we do not already have it" — so the first thing done was checking. **We do not.**

#### What exists, and why none of it is this

| artifact | what it aligns | why it is not Step 6 |
|---|---|---|
| `scripts/s6b_session_fingerprint_match.py` | `resolutions_flat` sessions ↔ raw `sessions_json` sessions | Both sides are **HTR**. Content-verified and order-preserving, but it never touches the enriched edition. |
| `session_date_status_1626_1630` (S4a–S4e ledger) | enriched date → HTR session | A **date-keyed lookup**, not a sequence alignment. Candidates come from the same calendar day plus a **±1-day** window (`-1`/`+1`/`?`), and those 603 nearby rows are review-only and were never auto-assigned. |
| `session_chain_alignment.py` | enriched resolutions ↔ flat paragraphs, **within one calendar day** | Resolution-level inside a day, chained across days for border hints. The session correspondence is an input to it, not its output. |
| `s6b_known_point_ledger.py` group D | session start/end sentinels | Uses session boundaries as anchors *once the session is known*. Assumes the answer Step 6 would produce. |

So the enriched→HTR session correspondence is currently established by **date label plus a ±1-day
window**, and everything downstream inherits whatever that produces.

#### Why this is likely the binding constraint, not a refinement

1. **Session numbering demonstrably drifts far beyond ±1.** From
   `s6b_session_fingerprint_match`'s 1,059 content-verified flat sessions: 400 (37.8%) sit at
   offset 0, but **659 (62.2%) carry a non-zero `raw_num − flat_num` offset and 494 (46.6%) are
   more than one position away** — the distribution runs out to 13, with clusters at 5 (120
   sessions), 8 (51) and 13 (42). A ±1-day candidate window cannot reach an offset of 5, let alone
   13. *Scope note: this offset is measured flat↔raw, both HTR-side, so it evidences the
   **mechanism** rather than the enriched↔HTR gap directly — quantifying that gap is Step 6's own
   first deliverable.*
2. **The mass affected is large and is exactly the unplaced mass.** In
   `resolution_concordance_1626_1630`: 4,482 resolutions on 344 `missing_htr` dates and 1,137 on 74
   `cross_day_shift` dates — **5,619 resolutions, 29.4% of all 19,120**, sit on dates whose session
   mapping is absent or already known to be wrong. The Global-stretch gap is 718.
3. **Step 1 already proved the precondition.** Verified landmarks are order-preserving: **zero**
   non-monotone steps across inventories 3185–3189, with drift piecewise-constant over runs of
   11–42 sessions. Labels are wrong nearly everywhere; order is intact everywhere. That is exactly
   and only what a monotone sequence alignment needs, and it is already measured.
4. **It is the principled fix for 5c.1's worst cohort.** `axis_for_date` currently answers "this
   date has no HTR" by borrowing a neighbouring session's axis, which 5c.1 measured at mean
   displacement 5.87 paragraphs. Step 6 replaces the borrow with an actual answer to *which session
   this sitting is*.

#### Relation to Step 3 — these are at different levels and Step 6 is upstream

Step 3 improves placement **within** a session that has already been identified. If the session
identification is wrong, Step 3 fills the wrong gap more precisely. On the numbers above, Step 6
governs 29.4% of the corpus that Step 3 cannot reach at all, and it makes Step 3's own inputs
trustworthy. **Recommendation: Step 6 before Step 3.** Both remain in scope; this is an ordering
call, not a substitution, and Step 3's design work (the no-insertion constraint) is already banked.

#### Design notes carried over

- **Same no-insertion structure, same check needed at this level.** An enriched sitting with no HTR
  session is routine (lost or unscanned material → deletion). An HTR session that is no sitting of
  this body should not exist. Verify before encoding, exactly as the resolution-level claim was
  verified against gold — do not assume it transfers.
- **Use content, not labels** — the lesson `s6b_session_fingerprint_match` already established
  HTR-side, and the one Step 1 turned into this track's mechanism.
- **LIS over noisy anchors** (MUMmer/NUCmer, Step 3's prior-art menu) is the standard treatment for
  extracting a maximal colinear subset, and inventory 4562's 15 non-monotone verified landmarks are
  the case that needs it.

**First deliverable, before any aligner is built:** measure the enriched↔HTR session offset
distribution the way finding 1 measures the flat↔raw one, so the ±1-window claim is evidenced
across the streams rather than argued by analogy. Cheap, and it is also the gate — if enriched↔HTR
offsets are overwhelmingly within ±1, Step 6 closes for the price of one diagnostic.

#### Nihil-actum as an alignment signal (user, 2026-09-25) — checked, and it redirects

Proposed as a two-sided anchor class. The signal **does** exist on both sides, but they are **not
the same class**, so it should not be wired in as an anchor. Measured directly from artifacts on
disk, no replay:

- **Enriched side: 127 dates**, `status == "nihil_actum"` in `resolution_concordance_1626_1630`,
  literal text `Nihil Actum`, exactly one row each (`k_e_signal = 0` per Tier V,
  `scripts/metrics_nihil_actum_invariant.py`).
- **These are a calendar artifact, not a content event: 112 of the 127 (88%) are Sundays.** The
  remaining 15 are scattered, presumably feast days. For contrast, all seven weekdays are otherwise
  evenly represented across the enriched date series (227–228 each). The body did not sit on
  Sundays and the edition records the non-sitting.
- **Only 2 of the 127 appear in `paragraph_axis_1626_1630` at all.** A day with no sitting produced
  no text, so there is nothing on the HTR side to anchor *to*.
- **HTR side: 32 dates, not the 138 first reported — that figure was wrong and must not be reused.**
  A first pass counted any axis paragraph containing `nihil` / `vacat` / `niet gedaen`. Inspecting
  the matched text shows **119 of the 138 are false positives**: every `vacat` hit (103 paragraphs)
  is `vacatien` — per-diem **fees**, from Latin *vacatio*, in travel-expense declarations ("over
  reiscosten ende vacatien by hem gedaen") — and every `niet gedaen` hit (16) is ordinary prose
  ("te niet gedaen", "daerop tot desen niet gedaen"). Of the 46 `nihil` paragraphs, **32 are
  standalone markers** (≤ 20 chars, literally `Nihil Actum`) and 14 are embedded in prose (e.g. a
  quoted Raad van State endorsement, "geteeckent Nihil Actum"). Same-date overlap with the enriched
  127 is still zero.

**The collapse is mostly implicit** (user, 2026-09-25). A nihil sitting is normally absorbed into a
neighbouring session with **no marker at all** — the day simply does not appear as a session and
the surrounding text runs on. An explicit `Nihil Actum` paragraph is the minority case: **32 of 127
(25%) leave any textual trace; 95 (75%) leave none.** Two measurements on the 32 that do:

- **Position within the session:** 16 are the **last** paragraph of their flat session and 12 the
  second-to-last — 28 of 32 within two of the end. They sit at the tail of a session's text rather
  than opening one.
- **Date relative to the enriched nihil day:** the nearest enriched nihil date is exactly **one day
  earlier in 17 of 32** cases, with a wide tail (−7 ×3, then −28, −38, −60, −137, −164, −184,
  −231). Weekdays agree: the enriched set is 88% Sunday, the HTR markers 59% **Monday**.

Whether that reads as "collapsed into the previous day" or "into the next" cannot be settled from
this alone, because the flat session's *own* date label is the drifted quantity under investigation
(finding 1: 46.6% of sessions sit more than one position from their label). The direction is left
open deliberately; Step 6's gate is what would resolve it.

**What survives, and what is withdrawn:**

1. **Keep: a hard skip constraint on the enriched stream — and the implicit-collapse finding makes
   it essential rather than merely useful.** The 127 nihil sittings must consume **zero** HTR
   sessions. Because 75% collapse with no marker, **the gap cannot be detected from the HTR side at
   all** — an aligner has no local evidence that a sitting is missing there. It has to be told, a
   priori, from the enriched side. Feeding these in stops the aligner spending an HTR session on an
   empty sitting and shifting everything downstream by one, which matters precisely because 46.6%
   of sessions are already mis-keyed by more than one position. This is the deletion-not-insertion
   asymmetry recorded for Step 3, in its sharpest and most certain instance.
2. **Withdrawn: "the HTR marker class is an independent landmark inventory."** That rested on the
   138 figure, 86% of which was `vacatien` and prose. The 32 real markers are corroboration of the
   collapse mechanism, not anchors. Possible small diagnostic use — the −1 / Sunday→Monday
   concentration is a directly observable instance of the label drift Step 6's gate is sizing — but
   they do not constrain placement, and 32 events is too thin to key an alignment on.

**Method note for whoever picks this up:** the 138 figure was produced by case-folded substring
matching and reported before the matched text was read. Read the matches before counting them —
`vacatien` and `nihil actum` are unrelated words that share no meaning, and the error inflated the
set 4×.

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

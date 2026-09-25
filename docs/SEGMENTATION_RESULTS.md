# Segmentation transfer — results, method, and what actually worked
<!-- doc-status: active -->

**Purpose of this document:** a single readable account of the segmentation-transfer effort
(29 Aug – 24 Sep 2026) — what it produced, how it works, and which parts of the method are worth
reusing versus which were specific to this corpus. It is a *summary*, not a new source of truth:
`PLAN.md` remains canonical for the goal and acceptance criteria, `docs/DECISIONS.md` for the
session-by-session record, `docs/METRICS.md` for the metric taxonomy. This document exists so a
reader (including a future session extending the method to a different period) doesn't have to
reconstruct the shape of the work from ~30 dated session notes.

---

## 1. The problem in one paragraph

Two independent descriptions of the same historical resolutions exist and don't line up. The
**enriched edition** (1626–1630 editorial summaries, ~19,120 resolutions) is trustworthy about
*how many* resolutions a sitting contains and *what* each one says, but carries no link to the
original manuscript. The **HTR transcription** (handwritten-text-recognition output of the
original session record) is a continuous stream of text with no resolution boundaries marked at
all. The goal: for each enriched resolution, find where it starts and ends in the HTR stream —
expressed as a verified archival address (paragraph, character offset), not a guess.

The framing that made this tractable: this is not *matching* two lists of similar-length items,
it is **count-constrained segmentation** — the enriched edition tells you exactly how many pieces
(`K_e`) a day's HTR text should be cut into; the algorithm's job is to place the `K_e − 1` cuts,
not to decide whether a match is "correct."

---

## 2. Headline results

**The result dataset:** `resolution_concordance_1626_1630` — one row per enriched resolution
(19,120 rows), carrying `day_status`, the resolved HTR session, and `paragraph_start_index`/
`paragraph_end_index` (null where no placement was possible). Load with
`data_io.load('resolution_concordance_1626_1630')`; see
[notebooks/resolution_concordance_exploration.ipynb](../notebooks/resolution_concordance_exploration.ipynb)
for an interactive walkthrough, including the "separated" flag computation below.

| Criterion | Target | Result |
|---|---|---|
| **Global, primary** | ≥50% of the paragraph-pigeonhole ceiling | **MET** — 68.8% (8,015 / 11,644) |
| **Global, stretch** | ≥75% of ceiling | not met — 718 resolutions short |
| **Global, spans** | ≥6 runs of ≥30 consecutive solid calendar-days, totalling ≥180 days | not met — best case 4 runs / 177 days |
| **Local** | any single inventory ≥50% of its own ceiling | **MET** — all 5 annual inventories (63.9–72.3%); the 2 non-annual "secret resolutions" inventories don't (structurally near-zero same-day HTR) |

Two formulas carry all of the above and are worth understanding precisely, because they're the
part most likely to transfer to a new period unchanged:

**The ceiling (a pigeonhole bound, not a model output).** On a calendar day with only *n* HTR
paragraphs, no algorithm — however good — can give more than *n* resolutions their own distinct
starting paragraph. So each day's maximum possible contribution to "separated" resolutions is
`min(k_e, paragraph_count)`, summed over all days: **11,644** out of 19,120 enriched resolutions
(60.9%). The remaining 39% is not a modeling failure; it's mostly days with no matching HTR at
all (535 of 1,594 enriched-dates have zero same-day HTR paragraphs).

**"Separated" (the per-resolution success criterion).** A resolution counts as separated iff (a)
its predicted start paragraph is shared with no other resolution on that date, and (b) its
predicted extent (`end − start + 1` paragraphs) is ≤3. (a) rules out two resolutions the model
just lumped together at the same spot; (b) rules out a technically-unique start that actually
covers a huge, clearly-wrong blob of text.

A **solid day** has ≥50% of its resolutions separated; a **span** is a run of solid days
tolerating at most `gap` non-solid days in a row (reported at gap∈{0,1,2} because the tolerance
parameter changes the answer a lot). "Global, spans" asks for long *unbroken* stretches, which
turned out to be a much harder bar than the per-resolution share — see §5.

---

## 3. The method

The working analogy throughout: **patchy alignment, as in ancient-DNA sequencing.** Damaged,
fragmentary source material aligned against a trusted reference yields incomplete coverage with
gaps — that's the expected shape of a good result, not a failure. A confidently-placed resolution
is an aligned read; several resolutions crammed into one paragraph is a multi-mapping read
(filtered out, not counted as progress); an unplaced resolution is an uncovered region, worth
classifying (why is it uncovered?) rather than silently dropping.

### 3.1 Anchors: four evidence channels, never treated as equally trustworthy

| Group | Channel | Character | What it's built from |
|---|---|---|---|
| **A** | Entity Needleman–Wunsch | sparse, high-precision "unique seeds" | Sequence-align each day's enriched-side entities against its HTR-side entities (`build_alignment_new.py`); ~43% of enriched rows land a tier-1 anchor this way |
| **B** | Fuzzy/dictionary entity matches | high-volume, low-specificity | Orthographic-variant and fuzzy lookup against name/place/org dictionaries |
| **C** | Phrase anchors | motif/marker class | Formulaic session-opening phrases (e.g. *"is ter vergaderinge"*), harvested from the corpus itself rather than hand-written |
| **D** | Session boundaries | structural scaffold | Session start/end sentinels — a hard constraint independent of any content match |

This is explicitly modeled on a genome aligner's seed classes (unique vs. degenerate vs. motif vs.
scaffold), because the failure modes turned out to match too — see §5.

### 3.2 Placement: a count-constrained DP, not a classifier

Given a day's ordered anchor positions and `K_e`, a dynamic-programming step (`segment_gap` /
`segment_day`) chooses `K_e − 1` non-decreasing cut points between the day's structural start/end
sentinels. It **never abstains** — a day with too little evidence still gets a best-effort
placement (repeated paragraph indices, which downstream "separated" scoring already treats as a
miss, not a crash) — because for this project's actual consumer, a low-confidence placement that
is visibly low-confidence is more useful than a silent gap. Evaluation and consumption are always
told the confidence tier alongside the placement.

### 3.3 Evaluation harness

Boundary placement is scored at multiple deliberately different granularities — this mattered
more than any single number:

- **Exact-count satisfaction** — does the day get exactly `K_e − 1` cuts.
- **Boundary P/R/F1 at tolerance `t`** — a placement within `t` characters/paragraphs of gold
  counts as correct, rather than requiring an exact hit; **WindowDiff**/**P_k** are standard
  text-segmentation metrics with the same tolerance-aware spirit, used to avoid the false alarms
  that pure exact-match produces.
- **"Lumped" (paragraph-granularity) scoring** — collapse both gold and predicted cuts onto the
  paragraph they open. This turned out to be the metric that actually tracked what the project's
  real consumer needs (§5) — sub-paragraph, character-exact precision was a self-imposed target,
  not a requirement of anything downstream.

---

## 4. What each layer actually contributed

Condensed from `docs/APPROACH_OVERVIEW.md` (which has the full dependency graph):

| Layer | Contribution | Verdict |
|---|---|---|
| Overlap builders (place/org/per) | Anchor input quality — fixed a literal-substring bug affecting all three | Real, modest gain (+13.4% place rows, +4.0% org, PER rebuilt from scratch) |
| Group-A entity NW alignment | The backbone anchor channel | Carries most of the signal; ~1 anchor per 2.3 enriched rows |
| Session-date ledger | Maps enriched dates to HTR sessions, including cross-day drift | Closed a 49.7%-of-ledger structural `missing_htr` ceiling |
| Paragraph-axis baseline → S6 anchor chaining → S6c segmentation DP | The placement algorithm itself | Took predicted-day coverage from 5/19 gold days (with an *oracle* anchor set!) to 19/19; corpus-wide from 244/1,594 days predicted to 1,059/1,059 days-with-any-axis |
| Concordance refresh | Re-ran a stale 3-rebuilds-behind assembly script | Moved the headline Global-primary number from 16.8% to 68.8% *with zero new modeling* — see §5, this is the single biggest lesson |
| Group-B/C evidence (fuzzy matches, phrases) fed into placement scoring | Tested as position-scoring evidence, 5+ variants | **Consistently net negative** — see §5 |
| Track B/C (soundex reranker, fuzzy-search context matching) | Never started | Closed on the strength of the Group-B/C finding above — same class of lever, already measured to not help |
| Line-level segmentation | Finer-than-paragraph cut points | Blocked — no dataset maps page→date for the needed inventories; would need a new extraction step |

---

## 5. Successes and pitfalls (the generalizable lessons)

These are the findings most worth carrying into a different corpus or period — they're about the
*shape* of the problem, not this specific dataset.

**Worked:**

1. **Reframing "matching" as "count-constrained segmentation"** was the single highest-leverage
   idea in the whole effort. It converts an open-ended similarity-scoring problem (is this HTR
   span *the* match for this enriched resolution?) into a much easier one (given that there are
   exactly `K_e` resolutions, where do the `K_e − 1` cuts go?). If a normative per-day count is
   available for a new period the way it is here, re-derive this reframing first before building
   any matcher.
2. **A DP that never abstains, paired with a confidence tier, beats a DP that abstains.** The
   original design abstained below a confidence threshold; replacing that with "always place,
   always flag confidence" moved coverage from 24% to 100% of days-with-any-axis without
   requiring better evidence — the abstention threshold itself was the bottleneck, not evidence
   quality (confirmed independently by an oracle-anchor test: even *perfect* anchors only unlocked
   5/19 gold days under the old abstain-happy DP).
3. **Session start/end sentinels as hard structural bounds** (Group D) were cheap and reliable —
   worth building early in any re-application, because they bound every gap the DP has to fill
   regardless of how good other evidence is.
4. **Deriving phrase/anchor inventories from the corpus's own high-confidence anchors**, rather
   than hand-writing or inheriting them from a different period's phrase list, worked better than
   expected and is self-reinforcing (better anchors → better harvested phrases → more anchors).
   Directly relevant to a new period: don't assume an existing phrase inventory (built for a later
   period) transfers — harvest fresh from whatever high-confidence anchors the new period yields.
5. **Scripting cited constants.** Several headline numbers (the 11,644 ceiling, a 1,961 baseline)
   were manually derived at some point and then cited as fixed constants for weeks without a
   script reproducing them. Once finally scripted, both reproduced exactly — so they weren't
   *wrong*, but they were unverified, and that's a needless risk for numbers a whole target table
   depends on. Script every cited number as soon as it's going to be reused, not after.

**Pitfalls — worth avoiding on a re-application:**

1. **Presence-of-entity is not position-of-boundary.** The single most-repeated negative result:
   feeding "this entity appears near here" evidence (Groups B and C — fuzzy/dictionary matches,
   phrase hits) into the placement scorer, in five independently-designed variants (blanket,
   day-grounded, gap-candidate-grounded, exact-relocated, fuzzy-relocated), **always made
   placement worse**, never better, even when the evidence was tightly grounded to confirm a
   specific enriched resolution actually claims that entity. The mechanism: these signals mark
   *where content is discussed*, not *where a resolution begins*, and a scorer that rewards
   entity-density pulls cuts toward entity-dense paragraphs regardless of whether those paragraphs
   open a resolution. Don't assume more evidence sources are better without measuring the specific
   placement effect, not just raw recall.
2. **A signal's isolated hit-rate is not its effect through the real pipeline.** An opening-phrase
   inventory hit 73.6% of gold cut points when checked directly — and then influenced only 1 of 5
   predicted days once run through the actual snap-and-revert logic, because a single collision
   discarded an entire day's snaps. Always re-check a promising signal *after* it passes through
   whatever downstream logic will actually consume it.
3. **Stale downstream artifacts silently cap headline numbers.** The concordance table that every
   separation metric reads had been frozen three predictor-rebuilds behind its own inputs for
   about a week; the fix was a 26-second re-run of a "pure assembly, no new logic" script, and it
   more than quadrupled the headline result (16.8% → 68.8%). No modeling change was involved —
   just noticing the input was stale. Any pipeline with more than one stage feeding a tracked
   metric needs a cheap way to check "is my input current," or this recurs.
4. **Paragraph-index-level "boundary F1" saturates against gold's own granularity**, independent
   of model quality — gold annotations that collapse multiple true cut points onto one coarse
   paragraph index impose a hard recall ceiling no placement improvement can cross. Moving to
   character-level scoring (S6a) fixed the ceiling but revealed the real headroom was in
   sub-paragraph precision, which turned out not to matter to any actual downstream consumer
   (next point) — so this was real, but not worth chasing further once that was established.
5. **Check what "boundary precision" is actually for before optimizing it.** A late finding: none
   of this project's real downstream consumers (the concordance table, the entity-matching
   pipeline, NER training-pair generation) needs character-exact cut points — paragraph-level
   attribution is treated as optional best-effort everywhere it's consumed. The push for
   character-precision was motivated by a self-imposed metric plateau, not a named requirement.
   Establish what precision the actual consumer needs *before* investing in a finer-grained
   harness.

---

## 6. What's period-specific vs. what's portable

**Superseded 2026-09-24** — this section originally claimed "the count-constrained-segmentation
reframing itself" was likely portable to earlier volumes. Scoping the actual extension work showed
that's not the right question: portability depends on **where the count-bearing evidence physically
sits**, not on whether a count exists at all. 1626–1630's own resolutions are numbered too
(`resolution_index`, and the web edition shows the numbers) — but that numbering lives on the
enriched side only, never inside the HTR being segmented, so it's an *ordering*, not a *locator*,
and cutting still had to be inferred. Whether the reframing/DP transfers to a given new period turns
on whether its count-bearing evidence is a locator (inside the stream) or an ordering (outside it).

Scoping surfaced (at least) three periods with different evidence shapes, each needing a different
method:

| Period | Evidence | Which method fits |
|---|---|---|
| 1626–1630 (this doc) | Normative `K_e`, an *ordering* on the enriched side only | Count-constrained DP — solved here |
| ~1610–1625 | Resolution numbers *printed in the OCR stream* — *locators* | Detection + sequence validation, not the DP — cheaper problem |
| ~1576–1590 | A short chronological list, thin *ordering*, against notably harder HTR | Closer analog to *this* period's own anchor-chaining/ceiling approach, but at a much lower expected ceiling |

Full reasoning, and the concrete build plan for both newer periods, is in the sibling-repo plan
referenced in §7 — this section now only carries the corrected headline distinction, not the detail.

**Portable regardless of period** (method/discipline, not data):
- The evaluation harness (boundary P/R/F1 at tolerance, WindowDiff/P_k, exact-count satisfaction) —
  corpus-agnostic by construction, verified by zero project-internal imports.
- Gold-annotation tooling, and the discipline of defining the metric before the method.
- The pigeonhole-ceiling framing — report progress against a computed ceiling, never against 100%.
- All five pitfalls in §5 — none of them are specific to having an enriched edition.

**Confirmed not portable as-is:** the place/org/PER overlap dictionaries, `abbrd`/`schutte`
reference registers, and any inherited phrase inventory — all built for this period's known
delegates and phrase distribution; per §5 pitfall 1, none should be assumed to help a new period
without a fresh measurement.

---

## 7. Where to look for more detail

- `PLAN.md` — canonical goal, acceptance criteria, full dated session log.
- `docs/DECISIONS.md` — every durable stop/continue/scope decision, dated.
- `docs/METRICS.md` — the full metric-tier taxonomy (Tiers V/D/O/P/A–E/X) and the DNA-alignment
  mapping in more depth.
- `docs/APPROACH_OVERVIEW.md` — the complete dependency graph between every approach that was
  built, including orphaned/unwired work.
- `docs/SEGMENTATION_TRANSFER.md` — the original method proposal this document reports the outcome
  of.

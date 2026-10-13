# TF-IDF embeddings wiring

<!-- doc-status: active -->

## Goal

Wire TF-IDF semantic similarity scoring into the segmentation pipeline as a placement candidate scoring signal, supplementing or replacing the existing entity-overlap mechanisms. Test whether semantic similarity improves placement on the 445 `weak_separation` days that block the Global-stretch criterion (≥75% of 11,644-resolution ceiling).

## Rationale

Five independent `position_scores` variants (blanket Group-B entity evidence, day-grounded, relocated, exact-relocated, gap-candidate-grounded, plus Group-C phrase-hit evidence) have all regressed below the 0.644 paragraph-tol0 no-evidence baseline when wired into `segment_gap`'s in-gap DP. The collision-avoidance track's Step 3 (order-constrained entity-mention alignment) also measured NEGATIVE. Semantic similarity offers a qualitatively different angle: rather than evidence presence (a binary signal), score the likelihood that an enriched resolution's editorial summary matches a given HTR gap's content.

**Known baseline:**
- `tfidf_similarity_auc_paragraph_granularity` = 0.893 (computed 2026-09-26)
- Measured on same-day placement discrimination (pool of paragraphs on the same calendar date)
- AUC does not directly transfer to the in-gap scenario (different pool size, different semantic distribution)

## Design questions (not yet scoped)

1. **How to integrate similarity into the gap-filling DP?**
   - Replace the uniform `ideal` default with similarity-weighted positions?
   - Add as a bonus term like Group B/C (likely to have same regression pattern)?
   - Use similarity as a gate (only attempt gap-filling if threshold met)?

2. **What is the effective AUC on weak-separation days?**
   - The 0.893 AUC is measured on a much smaller pool (same-calendar-day paragraphs)
   - `weak_separation` days are underbounded by paragraph count; real pools are much larger
   - Need a second measurement on realistic pool sizes before designing the integration

3. **How does similarity interact with the two collision-recovery modes?**
   - If an enriched resolution's summary genuinely matches multiple HTR gaps (high similarity to several), similarity alone cannot resolve collisions
   - Does semantic scoring help break ties on ambiguous same-day placements, or does it amplify false positives?

## Current state (2026-09-29)

Two wirings of the same TF-IDF matrix have now been measured, both on `separated_count`.

### Wiring 1 -- collapsed `position_scores` (NEGATIVE, mechanism understood)

`similarity_position_scores` takes the per-paragraph max over the (k_e x k_p) matrix, so it
answers "does *some* resolution like this paragraph?" and structurally cannot say which
resolution goes where. Measured on the 19-day gold subset
(`s6c_similarity_position_scores_eval`, commit 8f90e4b): scales 0.5 and 1.0 left the DP's argmax
untouched (bit-identical output), scale 3.0 moved placements the wrong way (-18 separated). The
bonus varies with the absolute similarity level (mean 0.1314), not with the correct-vs-best-wrong
margin (0.0201).

### Wiring 2 -- per-rank `rank_scores`

<!-- Recorded in the three-part form of docs/ITERATION_POLICY.md ("Retired step"), because the bare
     verdict below ("NEGATIVE globally, POSITIVE gated") was measured against `separated_count` and
     later reversed when the same condition was scored for correctness. Read all three parts.
     (1) Does not pass on `separated_count`: -25 globally at best, +315 only when gated to
         weak_separation days.
     (2) Establishes: per-row normalisation moves placements at all, where the absolute-level form
         provably could not (the DP's argmax was bit-identical at scales 0.5/1.0); and, on gold,
         *improves correctness* — exact start agreement 0.5032 -> 0.5865 applied everywhere,
         better than the gated variant's 0.5321.
     (3) Re-evaluate if: correctness replaces coverage as the gating metric, which is the open
         decision this track now hangs on. Under that metric this wiring is positive and ungated. -->

`segment_gap` now accepts `rank_scores`: slot `rank` of a gap is enriched resolution
`left_anchor + rank`, so it is scored by *its own* similarity row. `similarity_rank_scores`
supplies those rows as `raw` (the level; the already-failed form, kept as the null), `rownorm`
(similarity / row max, level cancels) or `zscore` (only paragraphs above that resolution's own
row mean, in units of its own dispersion).

Measured corpus-wide with no gold dependency (`s6c_similarity_rank_scores_eval`, 1,121 scoreable
days, 14,472 attributed resolutions, baseline 8,315 separated / 0.5746):

| condition | global | delta | weak_separation days | gated to weak days | delta |
|-----------|--------|-------|----------------------|--------------------|-------|
| baseline | 8,315 | -- | 1,536 / 5,462 (0.2812) | -- | -- |
| `raw` @0.5 | 8,315 | +0 | 1,536 | -- | -- |
| `raw` @2 | 8,129 | -186 | 1,533 | -- | -- |
| `rownorm` @3 | 8,049 | -266 | 1,615 (0.2957) | 8,394 | +79 |
| `zscore` @1 | 8,202 | -113 | 1,731 (0.3169) | 8,510 | +195 |
| `zscore` @2 | 8,277 | -38 | 1,827 (0.3345) | 8,606 | +291 |
| `zscore` @3 | 8,290 | -25 | 1,851 (0.3389) | **8,630** | **+315** |

Saturates above scale 3 (scale 6 and 10: global -42/-43, weak 1,856). `raw` confirms the level
form fails at per-rank granularity too, so the normalisation, not the plumbing, is what made the
difference.

**Reading.** Applied everywhere the signal is negative; applied only on the days the pipeline has
already self-diagnosed as `weak_separation` it is clearly positive, and the two facets say the
same thing from both sides -- it helps where placement was ambiguous and hurts where the entity
anchors were already right. The gated figure is exact, not an estimate: `separated` is defined
within one date, so swapping one day's placements cannot change another day's separation.

### Correctness scoring of the gated condition (2026-09-29) -- POSITIVE, and the gate is wrong

`s6c_gated_correctness_eval` scores the same `zscore`@3 condition against the hand-annotated
`boundary_gold_sample` days with `separated_accuracy_eval`'s own `accuracy()` /
`gold_start_paragraphs()` (exact start-paragraph agreement and paragraph displacement; no
tolerance-family metric), reporting `separated_count` on the *same rows* so coverage and
correctness can be read against each other. 37 of 50 gold days scored (13 have no axis), 12 of
them `weak_separation`. Resolution 0 held out throughout.

**1. The gated gain is correctness, not spread.** On the 12 weak gold days the gate's `+7`
separated comes with better placement, and the paired before/after on the rows it actually
relocated is one-sided:

| weak gold days (169 rows) | baseline | gated |
|---|---|---|
| separated | 50 (0.2959) | 57 (0.3373) |
| exact start agreement (n=87) | 0.3218 | **0.4253** |
| within 1 paragraph | 0.5862 | 0.6667 |
| mean abs displacement | 5.471 | 5.540 |

46 rows moved on 10 days; 24 sit where gold locates nothing, leaving **22 adjudicable: 18 moved
toward gold, 4 away, 0 tied**, turning 0 exact hits into 9.

The rising mean displacement is **a single outlier**, not a tail. Every move on these days travels
1-2 paragraphs except one, which travels 21 the wrong way; excluding it alone turns net
displacement from +6 to **-15**. With 22 adjudicable rows, one row carries the whole
"displacement got worse" reading, so it should not be described as a distribution effect.

**2. `weak_separation` is the wrong gate -- ungated scores better on correctness.** Applied to
every gold day the same condition reaches **exact 0.5865** against the baseline's 0.5032, where
the gated version only reaches 0.5321, and net displacement falls 25 paragraphs. On the *non-weak*
days alone -- the days the gate was built to protect -- 33 rows move, 28 adjudicable: **25 toward
gold, 3 away**, mean displacement 2.929 -> 1.821, 17 new exact hits.

So the corpus-wide `-25 separated` that motivated gating is a **coverage** loss that, everywhere
gold can see it, is a **correctness gain**. The two metrics disagree in sign on solid days: the
condition merges or crowds starts that `separated` then refuses to count, while putting them
closer to where the annotator put them. `separated` was chosen as a gold-free proxy; this is the
first direct measurement of where it misleads.

## Open questions

1. ~~**Is the gated gain real or just spread?**~~ ANSWERED above: real. 18 vs 4 toward gold on the
   adjudicable moved rows, exact agreement +10.3 points on the weak days.
2. **Is `weak_separation` the right gate?** ANSWERED, negatively -- ungated beats gated on
   correctness (0.5865 vs 0.5321 exact). The live question is now whether to keep a gate at all,
   and that is a question about the *metric*, not the gate: adopting ungated means accepting a
   corpus-wide `separated` loss (-25) that PLAN.md's acceptance criteria score as a regression.
   Needs a decision in `docs/DECISIONS.md` before any placement change.
3. **Why does it hurt the solid days?** It does not hurt them on gold. It costs `separated` there
   while improving placement. The shape question is now the opposite one: which `separated` losses
   are correctness gains, and can that be recognised without gold?
4. **NEW -- how far does the 37-day gold subset carry?** The decisive cohorts are small (22 and 28
   adjudicable moved rows). The direction is consistent across every cut, but the size of the
   ungated gain is not well determined, and 13 gold days could not be scored at all.

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

- `tfidf_similarity_auc_paragraph_granularity` exists in `docs/state.json`
- No integration into `s6c_gap_segmentation.py` or `s4_corpus_paragraph_predictions.py` yet
- No evaluation on the 445 `weak_separation` days
- No corpus-wide measurement of pool size / effective AUC on realistic gaps

## Next actions (decision required before scoping)

**Before proceeding, clarify:**
1. Is the goal to close the Global-stretch gap (718 resolutions), or to improve weak-separation days as an experiment?
2. Should this track prioritize understanding whether similarity helps at all (cheap diagnostic), or proceed directly to implementation?
3. Are there existing semantic-scoring integration patterns in `build_alignment_new.py` or elsewhere that should be reused?

**If proceeding to diagnostic:**
- Compute effective AUC on weak-separation day pools (realistic size, `segment_gap` DP context)
- Score a gold-day sample with similarity as a tie-breaker inside the DP
- Compare to existing no-evidence baseline (0.644 paragraph-tol0 F1)

**If proceeding to integration:**
- Choose one integration mode (above)
- Wire into `s6c_gap_segmentation.py` or as a separate `s6d_*` variant
- Measure on 19/21 scoreable gold days before corpus-wide run

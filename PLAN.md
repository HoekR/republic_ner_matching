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
> **Acceptance criteria** (`docs/DECISIONS.md`): a resolution is **separated** iff its start
> paragraph is shared with no other resolution on its date and its extent is ≤ 3 paragraphs.
> The paragraph-level ceiling is **11,644 / 19,120 = 60.9%** (pigeonhole: 535 days have no HTR),
> not physics. Targets stated against that ceiling, never 100%.
>
> | criterion | baseline (2026-09-29) | status |
> |-----------|----------------------|--------|
> | Global primary: ≥ 50% of ceiling | 8,015 = 68.8% | **MET** |
> | Global stretch: ≥ 75% of ceiling | 8,015 = 68.8% | not met; gap 718 |
> | Global spans: ≥ 6 spans / ≥ 180 days | 4 spans / 177 days | not met; tracked, non-blocking |
> | Local: ≥ 50% of inventory ceiling | 3185–3189 all clear | **MET** |

## Status summary

**Closed (complete):**
- Segmentation-transfer S0–S6: S6c counts-constrained gap DP, `position_scores` tuning exhausted
- S4a–e: Session-date ledger (4,916 inventory-date mappings)
- Metrics tiers O/P/D/V: Separation, bottleneck, drift, nihil-actum diagnostics

**Active tracks (use `svz.py review` for decisions):**
1. **`inventory-stream-collision-avoidance`** ([plans/COLLISION_AVOIDANCE_TRACK.md](plans/COLLISION_AVOIDANCE_TRACK.md))
   - Step 1 PASS: Session landmarks 86% localizable, order-preserving
   - Step 2 NEGATIVE: Length prior doesn't help
   - Step 3 NEGATIVE: Entity-mention order aligner underperforms interpolation
   - Step 6 GATE: Main corpus already fully mapped; unplaced mass in secret series (4562/4861)

2. **`tfidf-embeddings-wiring`** ([plans/TFIDF_EMBEDDINGS_TRACK.md](plans/TFIDF_EMBEDDINGS_TRACK.md))
   - TF-IDF similarity AUC 0.893 (paragraph granularity)
   - Not yet wired into segmentation pipeline

3. **`resolution-loss-census`** (newly completed 2026-09-29)
   - 621 of 1,137 cross_day_shift sit on verified sessions; 552 (93%) collision-locked
   - 27 are true date-label conflicts; 516 lack fingerprint verification
   - Diagnostic: identifies which unplaced mass is recoverable (relabelling) vs structural (collisions)

**Future / parked:**
- **Synthetic boundary encoder** ([docs/steps/STEP_SYNTHETIC_BOUNDARY_ENCODER.md](docs/steps/STEP_SYNTHETIC_BOUNDARY_ENCODER.md))
  - Completed eval 2026-09-28; GloBERTise F1@50=0.407; hard-openings retrain worse
- **Secret resolutions (4562/4861)** — Cherry-picking retrieval design, separate track; user parked 2026-09-29
- **Workspace alignment** — Completed via `dighum_template` sync

## How to navigate

1. **For work planning:** `uv run python scripts/svz.py review` shows active tracks and metrics
2. **For decisions:** See [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/ITERATION_POLICY.md](docs/ITERATION_POLICY.md)
3. **For the method:** [docs/SEGMENTATION_TRANSFER.md](docs/SEGMENTATION_TRANSFER.md) frames the problem
4. **For results:** [docs/SEGMENTATION_RESULTS.md](docs/SEGMENTATION_RESULTS.md) summarizes findings
5. **For active track details:** Each track in `plans/*.md`

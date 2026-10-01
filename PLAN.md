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
   - Collapsed `position_scores` wiring NEGATIVE; mechanism diagnosed (bonus tracks the absolute similarity level, not the margin)
   - Per-rank `rank_scores` wiring measured corpus-wide, no gold: NEGATIVE everywhere (best −25), **POSITIVE gated to weak_separation days (+315, 8,315 → 8,630)**
   - Gated gain scored for correctness on gold (2026-09-29): **real** — exact start agreement 0.3218 → 0.4253 on weak days, 18 of 22 adjudicable moved rows go toward gold
   - **But the gate is wrong**: ungated scores *better* on correctness (exact 0.5865 vs gated 0.5321), so the corpus-wide −25 `separated` is a coverage loss that is a correctness gain
   - Next: decide whether `separated` or gold correctness rules when they disagree (`docs/DECISIONS.md`) — blocks any placement change

3. **`staged-anchor-consolidation`** ([plans/STAGED_ANCHOR_CONSOLIDATION.md](plans/STAGED_ANCHOR_CONSOLIDATION.md), opened 2026-09-30)
   - Execution design for `COLLISION_AVOIDANCE_TRACK`'s working hypothesis (2026-09-25), not a new framing
   - A clump is an **unresolved gap**, not a result — so no schema change, and gap-minimisation is not gameable
   - Objective: shrink gap mass via staged propagation (objective anchors → reconcile → subdivide → repeat); measure already exists (`s6b_known_point_ledger` gap-size distribution, baseline 947 gaps / 70.7% of unplaced work)
   - Measured: the DP consumes only ~4–7% of available anchors; groups B/C/D are **structurally invisible** to `align_session`'s `anchor_only_diagonal` gate, not merely down-weighted
   - One code change with reach: **partial abstention** in `segment_day` (today it never abstains, so it fabricates precision — `1630-02-22` emits 28 placements where 7 + 2 gaps is honest)
   - Step 1 DONE (2026-10-01, `docs/DECISIONS.md`): pinned-but-wrong population sized at 0.7% (8/1,123) confirmed — not a blocker for `session_boundary`/D; `1630-02-22` itself is `date_label_agrees`, so its crowding is a Step 3/4 problem, not this one
   - Step 2 harvest-join fix implemented (2026-10-01): `s6b_anchor_harvest.py` now enumerates dates via `axis_for_date` instead of raw same-day grouping, closing 93% of a 137-date raw/resolved axis mismatch — not yet re-run (user to run `uv run python -m scripts.s6b_anchor_harvest`)
   - Next: Step 3, partial abstention in `segment_day`

4. **`resolution-loss-census`** (newly completed 2026-09-29)
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

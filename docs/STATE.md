# Current Project State (SvZ)

Last updated: 2026-09-23 14:41

```mermaid
flowchart TD
    classDef done fill:#2e7d32,stroke:#1b5e20,color:#fff,stroke-width:2px;
    classDef inprogress fill:#f57c00,stroke:#e65100,color:#fff,stroke-width:2px;
    classDef todo fill:#424242,stroke:#212121,color:#ddd,stroke-width:1px,stroke-dasharray: 5 5;
    classDef blocked fill:#c62828,stroke:#b71c1c,color:#fff,stroke-width:2px;

    S0["S0: Boundary evaluation harness"] :::done
    S1["S1: Zero-annotation diagnostics"] :::done
    S2["S2: Anchor phrase inventory"] :::done
    S3_tooling["S3-tooling: Boundary gold tooling"] :::done
    S3_annotation["S3-annotation: Manual boundary annotation"] :::done
    S4["S4: Segmentation assembly (paragraph-axis baseline)"] :::inprogress
    S4a["S4a: Session-date inputs"] :::done
    S4b["S4b: Session-date ledger"] :::done
    S4c["S4c: Nearby session candidates"] :::done
    S4d["S4d: Session status heatmap"] :::done
    S4e["S4e: Session-key consumers"] :::done
    S5["S5: Evaluation and review routing"] :::done
    line_level_segmentation["line-level-segmentation: Line-level cut points for the 12 structurally-abstaining gold days"] :::blocked
    track_b_name_matching["track-b-name-matching: Track B -- soundex/Levenshtein reranker for person-name matching"] :::todo
    track_c_fuzzy_search_context["track-c-fuzzy-search-context: Track C -- FuzzyTokenSearcher context/role matching"] :::todo
    entity_resolution_fix["entity-resolution-fix: Entity resolution fix (persons/orgs/places id->name bugs, build_alignment_new.py)"] :::done
    excel_overlap_builder_audit["excel-overlap-builder-audit: Audit place/org/per_overlap_1626_1630.xlsx builders for the same literal-substring bug"] :::done
    resolution_concordance_completeness["resolution-concordance-completeness: Resolution concordance completeness (N-status gaps, candidate scoring, window-widen)"] :::done
    hoe_classifier_other_bucket["hoe-classifier-other-bucket: HOE classifier -- reduce the 'other' bucket (31% unclassified)"] :::todo
    ner_finetuning_original_goal["ner-finetuning-original-goal: GysBERT multi-class NER fine-tuning (original project goal, Phase 2+)"] :::blocked
    short_resolution_alignment["short-resolution-alignment: Short-resolution alignment (align_short_resolutions.py) -- decide: wire into concordance or retire"] :::done
    fuzzy_surface_form_scan["fuzzy-surface-form-scan: Corpus-wide fuzzy surface-form scan (s4_fuzzy_surface_form_scan.py) -- recover entities the tagger missed"] :::inprogress
    interior_cut_evaluation_harness["interior-cut-evaluation-harness: Extend the boundary evaluation harness to credit sub-paragraph (interior) cuts"] :::done
    adopt_windowed_overlap_rebuild["adopt-windowed-overlap-rebuild: Adopt build_windowed_overlap.py's variant-aware rebuild as canonical place/org overlap; build the equivalent fuzzy pass for PER"] :::done
    s6_anchor_chain_alignment["s6-anchor-chain-alignment: S6 -- multi-channel anchor chaining at character coordinates"] :::inprogress
    metrics_nihil_actum_invariant["metrics-nihil-actum-invariant: Tier V: nihil-actum invariant check"] :::done
    metrics_separation_span_table["metrics-separation-span-table: Tier O: consecutive-day separation span table"] :::done
    metrics_ke_drift_diagnostic["metrics-ke-drift-diagnostic: Tier D: per-day K_e drift-comparison diagnostic"] :::done
    metrics_bottleneck_diagnostic["metrics-bottleneck-diagnostic: Tier P: bottleneck diagnostic (evidence vs. algorithm)"] :::done
    metrics_consolidation_overhaul["metrics-consolidation-overhaul: Register the metrics-tier overhaul itself in state.json"] :::done
    S0 --> S5
    S1 --> S4
    S2 --> S4
    S4a --> S4b
    S4b --> S4c
    S4c --> S4d
    S4c --> S4e
    S3_tooling --> S3_annotation
    S3_annotation --> S5
    S4 --> S5
    S4 --> line_level_segmentation
    entity_resolution_fix --> excel_overlap_builder_audit
```

## Overall Progress

- [x] S0: Boundary evaluation harness — Implemented boundary P/R/F1 at tolerance t, WindowDiff/P_k, and exact-count satisfaction; gold-data adapter remains part of S4 evaluation.
- [x] S1: Zero-annotation diagnostics — D1, D1c, D2, and D2b completed; findings support segmentation-transfer framing.
- [x] S2: Anchor phrase inventory — Harvested 1626-1630 opening/closing phrases to output/s2_anchor_phrase_inventory.json.
- [x] S3-tooling: Boundary gold tooling — Built sample generator, annotation UI, and merge script. Upstream res_start has zero target-inventory overlap.
- [x] S3-annotation: Manual boundary annotation — All 50 days annotated and merged. Exception review distinguishes segmentable, cross-day-shift, and missing-HTR cases.
- [/] S4: Segmentation assembly (paragraph-axis baseline) — 2026-09-18: fixed k_e<=1 short-circuit and per-boundary snap collision revert. Predicted days 5/21 -> 9/21 (4 are trivial k_e==1); boundary micro F1 unchanged 0.576 exact / 0.727 within-2 -- open question, not yet explained. 12/21 remaining abstentions are structural (paragraph axis coarser than K_e) -> see line-level-segmentation.
- [x] S4a: Session-date inputs — Composite inventory-date key defined and registered; data_io.check passes for all S4 inputs.
- [x] S4b: Session-date ledger — 4,916 inventory-date rows: T=1,012, A=4, E=97, X=3, N=3,800.
- [x] S4c: Nearby session candidates — +/-1-day candidates recorded without auto-assignment.
- [x] S4d: Session status heatmap — Per-inventory-year calendar heatmap rendered.
- [x] S4e: Session-key consumers — Review export and mapping-aware corpus segmentation consumer both produced.
- [x] S5: Evaluation and review routing — scripts/evaluate_s4_paragraph_axis.py excludes C/M days, reports coverage separately. Routing abstentions to sequence_review_ui.py still deferred pending the next real S4 iteration.
- [!] line-level-segmentation: Line-level cut points for the 12 structurally-abstaining gold days — Per SEGMENTATION_TRANSFER.md section 9's fallback trigger. BLOCKED 2026-09-18, corrected 2026-09-18: canonical htr_classified_lines.csv has zero rows in inventories 3185-3189; the marijn-variant file has 1,294 checked rows in the right inventories but at spot-check density (2-9 pages/inventory), unmapped to dates. The page-to-date join is NOT a cheap check (see docs/DECISIONS.md 2026-09-18 'Correct line-level-segmentation blocker'): no manifest dataset maps (inventory, scan/page) to date -- session_index_all.parquet and session_date_status_1626_1630 are both session-level only. Doing the join needs a new extraction step over the unextracted 10 GB sessions_json-2026-02-27.tar.gz. Next action: scope and register a targeted page-range extraction from that archive before attempting the overlap check, or drop this track -- do not treat it as a quick lookup.
- [ ] track-b-name-matching: Track B -- soundex/Levenshtein reranker for person-name matching — Design-only in PLAN.md (B1 preprocessing, B2 soundex index, B3 structural reranker on TF-IDF top-k). Not started.
- [ ] track-c-fuzzy-search-context: Track C -- FuzzyTokenSearcher context/role matching — Design-only in PLAN.md (context-phrase model, two-level fuzzy match pipeline, role tie-breaking). Not started.
- [x] entity-resolution-fix: Entity resolution fix (persons/orgs/places id->name bugs, build_alignment_new.py) — Fixed silent id-as-name bugs for persons and institutions; built entity_surface_matches_1626_1630 cache (18,698 rows) for orthography fallback. Known limitation not fixed here -> excel-overlap-builder-audit.
- [x] excel-overlap-builder-audit: Audit place/org/per_overlap_1626_1630.xlsx builders for the same literal-substring bug — Confirmed the literal-substring bug for all three builders (see docs/DECISIONS.md 2026-09-19). Place +13.4% (1265/9428), org +4.0% (55/1363) rows recoverable via build_windowed_overlap.py's existing --compare-legacy rebuild, both zero-regression (legacy_only=0). Per confirmed by code inspection (no fuzzy pass in build_per_overlap.py); no rebuild script exists yet for it.
- [x] resolution-concordance-completeness: Resolution concordance completeness (N-status gaps, candidate scoring, window-widen) — Accepted as final 2026-09-18 (docs/DECISIONS.md): 70.7% resolved_auto, 28.6% missing_htr (structural ceiling, 49.7% of ledger has no HTR within +/-14d), 0.6% nihil_actum. Window-widen to +/-7d unlocked zero new confident matches. Closed track, not open for further work.
- [ ] hoe-classifier-other-bucket: HOE classifier -- reduce the 'other' bucket (31% unclassified) — hoe_classify.py pipeline is done end-to-end; 'other' is still ~1.32M rows / 31% of the 4.2M-row HOE layer. Priorities: frequency analysis on top-100 other forms; merge abbrd.functienaam seeds.
- [!] ner-finetuning-original-goal: GysBERT multi-class NER fine-tuning (original project goal, Phase 2+) — Phase 1 data prep done (21K LOC + 13K PER training pairs). Phase 2 (model training) not run this cycle -- deprioritized while the alignment/segmentation pivot (CURRENT/NEW Approach) is active.
- [x] short-resolution-alignment: Short-resolution alignment (align_short_resolutions.py) -- decide: wire into concordance or retire — RETIRED 2026-09-22 with the LLM side-plan close (plans/SHORT_RESOLUTION_SIDE_PLAN.md Step 7). Formulaic align_short_resolutions.py stays an orphan: never measured, never wired into s6b_anchor_harvest A-D, never consumed by concordance. Closing the LLM ranking track removes the only active reason to keep Tier E on the board; do not wire-in without a new measured case. Script may remain in-repo as historical reference.
- [/] fuzzy-surface-form-scan: Corpus-wide fuzzy surface-form scan (s4_fuzzy_surface_form_scan.py) -- recover entities the tagger missed — Registered 2026-09-19 (docs/APPROACH_OVERVIEW.md layer 0c). Built and launched same day as weekend batch work; was not in state.json at all until now. Full-dictionary FuzzyTokenSearcher scan (LOC/PER/ORG, index_vocabulary_pairs=False, levenshtein_threshold 0.85, 4-char min match) over all 21,519 paragraph_axis_1626_1630 paragraphs, flagging already_known vs newly_recovered against entity_surface_matches_1626_1630. Est 7-9h, checkpointed/resumable. LEVERAGE IS UNPROVEN and was questioned the same session: the cheaper scoped version (entity_surface_matches, layer 0b) already tested this lever in s4_bundled_split_poc and gave only a modest lift (0/27 -> 3/27 tol50). Output currently feeds nothing. Next action when it finishes: record newly_recovered count as a metric, then decide whether any downstream consumer justifies it -- do not assume it is progress.
- [x] interior-cut-evaluation-harness: Extend the boundary evaluation harness to credit sub-paragraph (interior) cuts — DONE 2026-09-20 via S6a (scripts/s6a_char_axis_evaluation.py, 14/14 tests). The harness now scores at character coordinates: gold (paragraph_stream_index, char_offset) composes to one integer axis per day by pure concatenation (no separator -- gold paragraph_boundary cuts carry char_offset == len(paragraph), so a paragraph-final cut composes to exactly the next paragraph's start). compute_boundary_prf needed no change, only this adapter. Interior/sub-paragraph cuts are therefore no longer structurally invisible: s4_bundled_split_poc.py and s4_llm_split_poc.py results can now be scored on the same axis as the main baseline at tol 50/150 chars. Registered output: s6a_char_axis_evaluation.
- [x] adopt-windowed-overlap-rebuild: Adopt build_windowed_overlap.py's variant-aware rebuild as canonical place/org overlap; build the equivalent fuzzy pass for PER — 2026-09-19: place/org canonical overlap swapped to variant-aware rebuild. 2026-09-21: PER canonical overlap swapped (build_per_overlap.py extended, +415 rows). 2026-09-21: downstream re-run done (build_alignment_new.py 11:43, s4_corpus_paragraph_predictions.py 11:44) against all three swapped tables. 2026-09-21: checked build_alignment_new.py's own headline confidence_tier distribution pre- vs post-swap -- tier1_anchor 5725->5730, tier2_* 4734->4708, tier3_* 2883->2904 out of 13342 unchanged total; largest single-tier delta 26 rows (0.19pp). Headline tier stats barely moved; the swap's real effect showed up in S6b's anchor-supply measurement (insufficient_entity_anchors abstentions 815->777) instead. Accepted as final -- see docs/DECISIONS.md 2026-09-21.
- [/] s6-anchor-chain-alignment: S6 -- multi-channel anchor chaining at character coordinates — 2026-09-23: axis_for_date fixed (prefers concordance resolved_auto session over a non-empty same-day stub). Re-ran predictions -> span-gap map -> severe-collapse autopsy in sequence: severe-collapse 92->83 days, breaking-gap share 25.15%->23.39% (below 0.25, severe_collapse_implicated now False), coverage unchanged (1140 predicted/454 missing_htr).
- [x] metrics-nihil-actum-invariant: Tier V: nihil-actum invariant check — Built scripts/metrics_nihil_actum_invariant.py. Concordance+ledger check: invariant_passed=True, 127 nihil days, 0 violations. Emits shared per-day K_e series (k_e_signal=0 on nihil) for Tier D/O.
- [x] metrics-separation-span-table: Tier O: consecutive-day separation span table — Built scripts/metrics_separation_span_table.py. Separated=1961 (16.8% of ceiling); solid_days=221/1594; Global spans@30 unmet at gap 0/1/2 (longest 6/9/9 calendar days).
- [x] metrics-ke-drift-diagnostic: Tier D: per-day K_e drift-comparison diagnostic — Built scripts/metrics_ke_drift_diagnostic.py on Tier V day series. 203 drift candidates at |dev|>=10 vs ±3d neighbor median; 0 blocked by V. Candidates are suspects, not proven errors.
- [x] metrics-bottleneck-diagnostic: Tier P: bottleneck diagnostic (evidence vs. algorithm) — Built scripts/metrics_bottleneck_diagnostic.py. oracle_coverage=0.263 (5/19), real_coverage=0.368 (7/19), recommended_focus=algorithm_redesign. Real>oracle is thin-anchor monotone dodge (same as endpoints density), not evidence that NW anchors beat perfect gold.
- [x] metrics-consolidation-overhaul: Register the metrics-tier overhaul itself in state.json — Closed 2026-09-22: docs/METRICS.md channel tiers O/P/A-E/V/X in place; V/D/O/P implemented (E retired). Overhaul complete.

## Active Focus

Discovered + fixed: resolution_concordance_1626_1630 was stale (2026-09-17, 3 predictor rebuilds behind). Re-ran it + full Tier O chain: separated_share_of_ceiling 16.8% -> 68.8% (Global-primary criterion now met), solid_days 221 -> 693/1594, spans@30 gap=2 4 spans/177d (was 0). Next: decide whether to push for the 75% stretch / 180-day span criterion (headroom diagnostic says 82.2% of remaining weak_separation days are headroom_available, not axis-capped -- a placement-quality fix e.g. S6e still has room) or bank this as the session's result. Clear chat.

## Key Intermediate Results & Metrics

- **S1-D1 — HTR under-segmented session-days:** 81.1%
- **S1-D1 — Exact K_f == K_e session-days:** 3.8%
- **S1-D1 — Mean entity containment:** 0.295
- **S1-D1c — Tier-1 Kendall tau:** 0.638; 64.3% of pairs at tau >= 0.8
- **S1-D2 — LLM judge precision:** 60.0% against 53.7% baseline
- **S1-D2b — Opening formula hit rate:** 80.1%
- **S4 — Flat-resolution entity-NW baseline coverage:** 0 / 50 predicted
- **S4 — Paragraph-axis resolved entity coverage:** 480 / 611 paragraphs; 87 unresolved annotation references
- **S4 — Boundary micro F1 (tolerance 0):** 0.576 (stagnant, Δ+0.000)
- **S4 — Boundary micro F1 (within 2 paragraphs):** 0.727 (stagnant, Δ+0.000)
- **S4 — Predicted-day coverage (of 21 eligible gold days):** 0.429 (improving, Δ+0.191)
- **S4 — Opening signal at manual cuts:** 227/360 regex (63.1%); 225/360 S2 top-20 phrases (62.5%)
- **S4 — fuzzy_search opening coverage:** 225/360 (62.5%), unchanged from exact top-20 phrase matching
- **S4 — Held-out opening phrase inventory:** 271 candidates from 3,817 tier-1 flat records; excludes 50 gold dates
- **S4 — Corpus paragraph axis:** 21,519 paragraphs; 16,104 entity-bearing; 41,156 resolved attachments
- **S4 — Corpus entity-NW baseline:** 244/1,594 predicted; 815 insufficient anchors; 535 no same-day HTR assignment
- **resolution-concordance-completeness — Resolved-auto share of resolution-level concordance:** 70.7%
- **resolution-concordance-completeness — Missing-HTR share (accepted structural ceiling):** 28.6%
- **hoe-classifier-other-bucket — 'other' bucket share of the HOE layer:** 31%
- **S4 — Common-language effect size, bundled vs clean-boundary paragraph entity_annotation_count (gold, n=22/112):** 0.770
- **S4 — NER-only entity spans, even-split heuristic, tol=150 chars:** 0.333
- **S4 — NER + entity_surface_matches dictionary lookup, tol=150 chars:** 0.407
- **S4 — NER-only entity spans, even-split heuristic, tol=50 chars:** 0.0
- **S4 — NER + dictionary lookup, tol=50 chars:** 0.111
- **S4 — NER-only spans + phrase-boundary snap, tol=50 chars:** 0.074
- **S4 — NER-only spans + phrase-boundary snap, tol=150 chars:** 0.333
- **S4 — NER + dictionary + phrase-boundary snap, tol=50 chars:** 0.148
- **S4 — NER + dictionary + phrase-boundary snap, tol=150 chars:** 0.407
- **excel-overlap-builder-audit — 1265/9428 additional rows found by build_windowed_overlap.py's variant+tag_text passes vs legacy canonical-only place_overlap_1626_1630.xlsx (window_days=0, --compare-legacy: legacy_only=0, rebuilt_only=1265):** 0.1342
- **excel-overlap-builder-audit — 55/1363 additional rows found by build_windowed_overlap.py's variant pass vs legacy canonical-only org_overlap_1626_1630.xlsx (window_days=0, --compare-legacy: legacy_only=0, rebuilt_only=55):** 0.0404
- **excel-overlap-builder-audit — Confirmed by code inspection: build_per_overlap.py has no fuzzy/variant pass at all (exact tag_text substring, then exact-word surname_token fallback only). Directional cross-check against entity_surface_matches_1626_1630 (different candidate universe, so not a clean rate): 1123 fuzzy-confirmed PER entity/resolution pairs across 991 resolutions are absent from per_overlap_1626_1630.xlsx entirely.:** 1.0
- **s6-anchor-chain-alignment — Hard recall bound AT TOLERANCE 0 on the 50-day gold set under (paragraph_stream_index, char_offset): 320/352 distinct cut positions, vs 280/352 (0.795) under paragraph indices alone. Higher is better. Rigorous at tol0 only -- at tol>0 a clustering predictor can exceed the distinct-value count (see DECISIONS.md 2026-09-20 correction). Residual 32 slots have char_offset=null.:** 0.909
- **s6-anchor-chain-alignment — S6a STRICT ceiling: 313/352 distinct character positions reachable at tolerance 0 on the 50-day gold set, vs 280/352 (0.795) under paragraph indices. Higher is better. CORRECTS the step guide's 320/352 (0.909), which counted 7 paragraph-index groups whose slots have char_offset=null as reachable; they are annotation gaps. 39 cut slots carry no offset and are unreachable on a character axis.:** 0.889
- **s6-anchor-chain-alignment — S6a re-scored baseline: micro F1 at tolerance 0 CHARACTERS for the unchanged 2026-09-18 s4_paragraph_axis_predictions, composed onto the character axis. Higher is better. Not comparable to the 0.576 paragraph-coordinate figure (different unit); the point is that 0.467 sits well below the 0.889 ceiling, so the metric is no longer saturated.:** 0.467
- **s6-anchor-chain-alignment — S6a re-scored baseline: micro F1 at tolerance 150 characters (matching the split-POC harness scale). Higher is better.:** 0.567
- **interior-cut-evaluation-harness — 22 of 24 folded gold groups (16 days) gain distinct character coordinates under (paragraph_stream_index, char_offset) composition. Higher is better. The 2 that stay folded hold only char_offset=null slots.:** 0.917
- **s6-anchor-chain-alignment — S6 Step 1 oracle diagnostic: with a PERFECT gold-derived anchor set, the current placement model (interpolate_positions + snap_boundaries, unmodified) can predict only 5 of 19 scoreable gold days. Higher is better. 9 days abstain folded_anchors_non_monotone, 5 axis_shorter_than_k_e. This is an upper bound on what ANY anchor-selection improvement, chaining included, can cover.:** 0.263
- **s6-anchor-chain-alignment — S6 Step 1 oracle diagnostic: micro F1 at tol 50 chars on the 5 days perfect anchors can predict (tol0 0.727, tol150 0.788). Higher is better. Caps below 1.0 because the model emits (paragraph index, snap offset), so the 33 mid_paragraph gold cuts are largely unreachable.:** 0.788
- **s6-anchor-chain-alignment — S6a LUMPED baseline: gold cuts collapsed onto the paragraph they open (interior cuts credited at their paragraph start, de-duplicated) and model output collapsed the same way. Higher is better. Flat 0.828 across tol 0/50/150 because paragraph starts are far apart, so tolerance is irrelevant once both sides are at paragraph granularity. Separate metric name on purpose: the STRICT character-precision figures (char_axis_boundary_f1_tol0 = 0.467) are unchanged and must keep their own history.:** 0.828
- **s6-anchor-chain-alignment — S6b constraint baseline, contiguous 1626-01-01..06-30: 389 of 1218 enriched resolutions are pinned by a typed known point (366 tier-1 anchors, 41 gold boundaries; session start/end are sentinels). Higher is better. Measures the problem's constraint structure, not any model.:** 0.319
- **s6-anchor-chain-alignment — S6b constraint baseline: 544 of 723 unplaced resolutions sit in the 93 gaps holding more than 2 resolutions. LOWER is better. Counting GAPS flatters this badly -- 81.2% of gaps are determined or nearly so, but those hold only 24.8% of unplaced resolutions; 18.8% of gaps hold 75.2% of the work.:** 0.752
- **s6-anchor-chain-alignment — S6b constraint baseline, FULL period 1626-1630: 5111 of 13530 enriched resolutions pinned by a typed known point (4761 tier-1 anchors, 350 gold boundaries). Higher is better. Report: docs/S6B_CONSTRAINT_BASELINE.md.:** 0.378
- **s6-anchor-chain-alignment — S6b constraint baseline, FULL period: 5302 of 7504 unplaced resolutions sit in the 947 gaps holding more than 2 resolutions, spanning 3.13M characters. LOWER is better. Gap-count view says 84.3% settled; resolution-weighted view says 70.7% of the work is open. Quote both.:** 0.707
- **adopt-windowed-overlap-rebuild — PER variant-aware rebuild vs legacy literal-substring build: legacy_only=0 (strict superset), shared=7544, rebuilt_only=415. Higher is better.:** 415
- **s6-anchor-chain-alignment — S6b anchor harvest, 36-day smoke window (1626-01-01..03-01, preliminary, not corpus-wide): group A (tier1_entity_nw) 149 anchors/32 days; group B (entity_surface_matches 617, fuzzy_surface_scan 5007)/36 days; group C (s2_anchor_phrases 465, s4_opening_phrase_candidates 547)/36 days. Of 26 insufficient_entity_anchors abstentions in this window, 3 had zero group-A anchors at all, and all 3 gain a non-A anchor once B/C are harvested (anchor SUPPLY only -- not a placement guarantee, see docs/DECISIONS.md 2026-09-20 on the placement model binding). No trend direction; this is a first reading, full-corpus run not yet done.:** 0.0
- **s6-anchor-chain-alignment — S6b anchor harvest, FULL CORPUS 1626-1630: 247,871 anchor rows over 1,240 days-with-axis. Of the 815 corpus-wide insufficient_entity_anchors abstentions, only 59 (7.2%) had ZERO group-A (tier1_entity_nw) anchors at all -- the other 756 (92.8%) already had >=1 group-A anchor and abstained for a different reason (interpolate_positions' monotonicity/axis-length requirements, per the S6 Step 1 oracle diagnostic). Of the 59 zero-anchor days, 57 (96.6%) gain a non-A anchor once groups B/C are harvested -- but that is only 57/815 = 7.0% of all abstentions. LOWER is better (less of the problem is anchor-supply-shaped). Report: this response.:** 0.072
- **s6-anchor-chain-alignment — S6b anchor harvest, FULL CORPUS: per-channel density (anchors / distinct positions / days-touched of 1,240 days-with-axis). A tier1_entity_nw: 5,332/3,718/993. B entity_surface_matches: 18,406/8,075/1,068; fuzzy_surface_scan: 189,764/162,307/1,238 (touches nearly every day and vastly outnumbers group A, but char-offset granularity means many hits cluster within single paragraphs). C s2_anchor_phrases: 14,890/14,890/1,231; s4_opening_phrase_candidates: 16,999/16,999/1,233 (one best hit per paragraph by construction, so anchors==distinct positions). D session_boundary: 2,480/2,480/1,240 (2 per day, as designed). Value recorded is total group-A anchors in thousands (5.332k) as a scale reference; read the full breakdown in the label, not the number. Higher is better for coverage completeness, not for correctness of any given anchor.:** 6.99
- **adopt-windowed-overlap-rebuild — Post-rebuild build_alignment_new.py re-run (2026-09-21, refreshed place/org/per overlap tables), alignment_1626_1630.parquet, n=13342 (unchanged): tier1_anchor 5725->5730 (42.9%->42.9%), tier2_* 4734->4708 (35.5%->35.3%), tier3_* 2883->2904 (21.6%->21.8%). Value = largest single-tier count delta (26) / total (13342). LOWER is better (less headline movement from the overlap swap alone).:** 0.0195
- **s6-anchor-chain-alignment — 19/21 eligible gold days predicted (was 9/21 pre-S6c):** 0.905
- **s6-anchor-chain-alignment — S6c segmentation DP, was 0.828 pre-S6c (baseline unchanged within noise):** 0.826
- **s6-anchor-chain-alignment — S6c segmentation DP on nearly 3x the predicted days (19 vs 7), was 0.500 pre-S6c:** 0.503
- **s6-anchor-chain-alignment — was 777 pre-S6c; eliminated entirely (1059 = 282 pre-existing + all 777 recovered):** 0
- **s6-anchor-chain-alignment — 1059/1059 days with an axis now predict (535 missing_htr, structural, untouched):** 1.0
- **s6-anchor-chain-alignment — Predicted days with 7+ resolutions collapsed onto one paragraph (83/1140) after the axis_for_date fix; was 92/1140=0.0807 pre-fix, 79/1059=0.075 before the concordance-fallback wiring:** 0.0728 (stagnant, Δ-0.002)
- **s6-anchor-chain-alignment — was 535 pre-wiring; 81 days recovered via resolution_concordance_1626_1630's resolved_session_id:** 454
- **s6-anchor-chain-alignment — S6b prerequisite: resolutions_flat session -> raw session content-fingerprint match rate (substring containment on 'para'-class text), registered as s6b_session_fingerprint_match, replacing unregistered scratch. 1059/1511 matched, 0 ambiguous, 659/1059 drifted (non-zero offset). Higher is better.:** 0.701
- **s6-anchor-chain-alignment — session_day_find (S6b Group-D channel): 25/25 sampled hits genuine at FuzzyPhraseSearcher threshold 0.95+ignorecase, 154 hits/130 sessions vs regex baseline's unvalidated 210/167 on the same session-text universe. Higher is better (this is a precision spot-check, not corpus coverage).:** 1.0
- **s6-anchor-chain-alignment — session_day_find corpus-wide: 203 anchors / 162 of 1240 days-with-axis (13.1%), 203 distinct positions -- smallest of all six non-sentinel channels (vs group A tier1_entity_nw 5375 anchors/995 days). insufficient_entity_anchors supply-gain proxy is degenerate at 0/0/0: S6c already eliminated that abstention category entirely, so the proxy has nothing left to measure -- not evidence this channel closed a gap.:** 0.131
- **s6-anchor-chain-alignment — s4_corpus_paragraph_predictions.py's predict(), with s4_opening_phrase_candidates fed into segment_day's position_scores, scored on the 19/21 scoreable gold days: tol0 F1 0.622 vs 0.644 WITHOUT phrase evidence -- a regression, not a gain. tol1/tol2 marginally better (0.796/0.812 vs 0.790/0.807), mean Pk/WindowDiff worse (0.292 vs 0.285). Adding snap_boundaries (the gold pipeline's second phrase-evidence stage) on top produced IDENTICAL numbers -- not a partial-implementation artifact. NOT wired into the corpus predictor. Higher is better (but this is the WITH-evidence reading; compare against the 0.644 without-evidence baseline, not a target).:** 0.622
- **metrics-nihil-actum-invariant — Tier V nihil-actum invariant_passed (1=pass, 0=fail):** 1
- **metrics-nihil-actum-invariant — Tier V nihil_share_of_days (127/1594):** 0.0797
- **metrics-ke-drift-diagnostic — Tier D K_e drift candidates (|dev|>=10 vs ±3d neighbor median); lower after genuine fixes is better:** 203
- **metrics-separation-span-table — separated resolutions (unique start + extent<=3):** 1961
- **metrics-separation-span-table — solid days (separated_share>=0.5 on k_e_signal):** 221
- **metrics-separation-span-table — Global spans @30d gap=1 (n_spans; criterion >=6):** 0
- **metrics-separation-span-table — Global spans @30d gap=1 (days covered; criterion >=180):** 0
- **metrics-bottleneck-diagnostic — oracle_ceiling coverage (perfect anchors + interpolate_positions):** 0.263
- **metrics-bottleneck-diagnostic — real_performance coverage (NW anchors + interpolate_positions):** 0.368
- **metrics-bottleneck-diagnostic — bottleneck recommended_focus (decision aid):** algorithm_redesign
- **s6-anchor-chain-alignment — session_date_verified corpus-wide: 939 anchors / 891 of 1240 days (71.9%):** 0.719
- **s6-anchor-chain-alignment — Tier O span-gap map: inter-solid breaking gaps (171) among 221 solid days; 49 adjacent solid pairs. Dominant interrupter weak_separation (125/171), then missing_htr (38), nihil_actum (8).:** 171
- **s6-anchor-chain-alignment — Share of breaking gaps that contain an S6c severe-collapse day (40/171) after axis_for_date fix; was 0.2515 (43/171) -- drops below the 0.25 implication threshold:** 0.2339 (regressing, Δ-0.018)
- **s6-anchor-chain-alignment — Bridge counterfactual: drop all 917 weak_separation days from the series; longest gap=0 solid run is only 12 calendar days (still 0 spans@30). No single-class bridge reaches Global spans.:** 12
- **s6-anchor-chain-alignment — S6c severe-collapse autopsy: days with max>=7 resolutions on one paragraph start (83/1140, after the 2026-09-23 axis_for_date fix; was 92/1140):** 83 (regressing, Δ-9.000)
- **s6-anchor-chain-alignment — Share of severe-collapse days where ceil(k_e/P)>=7 (25/83) after axis_for_date fix -- structural even under optimal assignment; was 0.3478 (32/92):** 0.3012 (regressing, Δ-0.047)
- **s6-anchor-chain-alignment — Share of severe-collapse days with paragraph_count>=k_e (10/83) after axis_for_date fix; was 0.1087 (10/92):** 0.1205 (improving, Δ+0.012)
- **s6-anchor-chain-alignment — All 92 severe-collapse days are Tier O weak_separation nonsolids (0 solid):** 1.0
- **s6-anchor-chain-alignment — Of 92 severe-collapse days, 9 prefer a thin same-calendar-date axis over a richer concordance-resolved session on a neighboring date (axis_for_date bug):** 9
- **s6-anchor-chain-alignment — Of 92 severe-collapse days, 15 have P<=1 on both calendar axis and resolved session (real short/blob HTR, often inventory 4562):** 15
- **s6-anchor-chain-alignment — PLAN.md Global-primary metric after re-running resolution_concordance_1626_1630 (stale since 2026-09-17) against the current S6c predictor: 8015/11644 separated (was 1961/11644=16.8%). Higher is better. Global-primary criterion (>=50%) now met; stretch (>=75%) not yet (gap ~718).:** 0.688
- **s6-anchor-chain-alignment — Tier O solid days out of 1594 after concordance refresh (was 221/1594). Higher is better.:** 693
- **s6-anchor-chain-alignment — Global spans@30 gap=2 days_covered after concordance refresh (was 0; n_spans=4, criterion is >=6 spans AND >=180 days). Higher is better -- 177 is just short of the 180-day stretch.:** 177
- **s6-anchor-chain-alignment — Share of remaining 445 weak_separation days (was 917) that are headroom_available (ceiling>=0.5, not axis-capped) per metrics_weak_separation_headroom_diagnostic, after the concordance refresh. Higher is better (means placement-quality work, not axis granularity, is still the live lever).:** 0.822
- **s6-anchor-chain-alignment — Group-B (entity_surface_matches) position_scores wired into segment_day, corpus predictor codepath, 19/21 scoreable gold days, PARAGRAPH tol0 F1 (not char tolerance per 2026-09-21 rescope). Baseline (no evidence) tol0=0.644/tol1=0.790/tol2=0.807; Group-B tol0=0.555/tol1=0.790/tol2=0.840. Lower is worse at tol0 -- net negative at the primary granularity, same failure mode as Group-C phrase hits (2026-09-21): entity mentions signal presence, not resolution-opening position, so the phrase_weight/dispersion tradeoff pulls cuts toward entity-dense paragraphs regardless of whether they open a resolution.:** 0.555
- **s6-anchor-chain-alignment — Sum of (with-evidence TP - baseline TP) across days whose predicted cuts actually changed, 19-21 scoreable gold days, paragraph tol0. Group B: -21 across 11 divergent days (all worse). Group C (re-measured same way this session): -2 across 8 divergent days (6 same, 2 worse, 0 better). Lower magnitude is better/more neutral. Confirms Group B's regression is ~10x larger than Group C's, traced to flat_id-level (not paragraph-level) evidence granularity -- see docs/DECISIONS.md correction.:** -21
- **s6-anchor-chain-alignment — Two-sided check, 40-day random sample (seed=42): of 243 entity_surface_matches rows flagged 'new' (not already in the rebuilt place/org/per_overlap tables for that flat resolution), only 4 (1.6%) match a SPECIFIC enriched resolution's own resolved entity set (places+orgs+persons via resolve_enriched_entities) anywhere in that day's candidate pool; 239 (98.4%) are floating -- no enriched resolution that day claims the name at all. Higher is better (more grounded, fewer false anchors). Sanity-checked against a raw example (1626-01-19): genuinely-grounded enriched entities are small specific place names (Oudenbosch, Kempenland, Zevenbergen); the floating flagged names are large common geographic terms (Holland, Zeeland, Engeland, Amsterdam, Groningen) that read as incidental context mentions, not resolution subjects.:** 0.016

## Blockers / Open Questions

- [ ] line-level-segmentation: htr_classified_lines_marijn.csv page_id->calendar-date mapping not yet built, so overlap with the 12 structurally-abstaining gold days is unverified.

## Next Actions

- Run `uv run python scripts/svz.py review` at the start of the next session before picking up work; see docs/ITERATION_POLICY.md.
- line-level-segmentation: map marijn-variant page_ids to calendar dates (session/page index join) and check overlap with the 12 gold days before writing any DP/classifier code.
- S4: explain why boundary F1 stayed at 0.576/0.727 despite the collision fix relocating most boundaries from raw interpolation to phrase-snapped positions -- needs a per-boundary gold-vs-predicted diff, not attempted yet.
- S4: investigate the 2 gold dates (1626-05-17, 1627-04-11) with zero boundary_gold_paragraph_axis records -- data-completeness gap, not yet root-caused.

<!-- Manual notes below this line are preserved by scripts/svz.py render. -->
## Notes


## MCP

- mcp_enabled: true
- mcp_server_path: /Users/rikhoekstra/develop/dighum_template/packages/workflow_mcp
- last_mcp_check: 2026-09-01T00:00:00Z
- current_step: 4a

## Dashboard
- docs/dashboard.md

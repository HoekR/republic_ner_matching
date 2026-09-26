# Short-resolution LLM alignment side plan
<!-- doc-status: sidelined -->

## Goal

Test whether few-shot LLM-generated summaries of HTR text improve alignment evidence for short resolutions, especially short resolutions near the beginning of a session.

This is an evaluation-only side track. It must not change the production concordance, S6c segmentation, or frozen datasets until a held-out result shows a measurable gain over the strongest deterministic baseline.

**Outcome (2026-09-22):** **CLOSED** at Step 7 — held-out ranking did not beat the strongest deterministic baseline (baseline top-1 20/20 vs LLM 8/20). See Step 7 and `docs/DECISIONS.md`.

## Working hypothesis

Short resolutions near a session start may provide useful semantic and structural anchors when entity overlap is sparse. The signal may distinguish:

- a genuine opening receipt or no-decision resolution;
- a short resolution merged into the following HTR record;
- a continuation from a previous session;
- a formulaic opening that is not a separate resolution.

The LLM should generate evidence about candidate HTR text. It should not decide session membership freely, change the normative resolution count, or replace the boundary gold annotations.

## Scope and guardrails

- Split by complete session-day, never by individual resolution.
- Keep held-out test days hidden from prompt tuning and few-shot selection.
- Test short and long resolutions separately.
- Include short non-initial examples so the model cannot win by learning `short = first`.
- Compare against a positional-only baseline, not only against the entity aligner.
- Require evidence quotes and structured fields; do not rely on fluent prose alone.
- Keep old pair verdicts as a secondary continuity check. Use boundary gold as the primary segmentation evaluation.
- Start with a small pilot of approximately 50-100 candidate HTR items.

## Stepped plan

### Step 1 — Define the experiment and freeze the split
<!-- status: done 2026-09-22 -->

**Purpose:** Establish a leakage-safe sample before generating any LLM output.

**Tasks:**

- Use session-day as the grouping key.
- Identify HTR candidate units and their session-relative order.
- Compute strata for:
  - short versus long HTR text;
  - session-initial versus non-initial position;
  - enriched short/no-decision versus substantive text;
  - matched-count versus under-segmented day;
  - strong tier-1 anchor versus weak/no anchor;
  - possible continuation or spillover.
- Freeze training/few-shot, development, and held-out test session-days.
- Balance the first pilot across short-initial and short-non-initial cases.

**Deliverable:** A reproducible sample manifest containing session-day split, stratum, enriched id, HTR id, text lengths, position, and available deterministic signals.

**Gate:** No session-day may occur in more than one split. Stop if the sample cannot distinguish positional effects from semantic effects.

**Done (2026-09-22):**
- Builder: `scripts/build_short_resolution_llm_sample.py`
- Dataset: `short_resolution_llm_sample_manifest` → `output/short_resolution_llm_sample_manifest.jsonl`
- Frozen pilot: 80 HTR candidates over 37 session-days (train 18 / dev 9 / test 10 days; 40 / 20 / 20 candidates)
- Position balance: short_initial=18, short_non_initial=21 (plus long strata); gate passed; no cross-split session-day leakage
- Boundary-gold days in the sample are forced into `test`
- Tests: `tests/test_short_resolution_llm_sample.py`

### Step 2 — Establish deterministic baselines
<!-- status: done 2026-09-22 -->

**Purpose:** Measure what the LLM must beat.

**Baselines:**

1. Existing entity/sequence alignment.
2. Formula-based short-resolution detection from `align_short_resolutions.py`.
3. Positional-only rule: prefer short candidates near the session start.
4. Formula/entity combination without LLM evidence.

**Record:** Candidate rank, overlap score, formula score, session position, opening/closing signals, and boundary prediction where available.

**Deliverable:** Baseline report on exactly the frozen development and test candidates.

**Gate:** The LLM experiment is not useful if the baseline inputs differ between comparison runs.

**Done (2026-09-22):**
- Builder: `scripts/build_short_resolution_baselines.py`
- Summary: `scripts/summarize_short_resolution_baselines.py`
- Dataset: `short_resolution_baseline_report` → `output/short_resolution_baseline_report.jsonl`
- Baselines computed: 80 frozen candidates (40 train / 20 dev / 20 test)
- Formula detection: 1/80 (1.2%) with both open + close phrases
- Alignment distribution: 73.8% no tier, 13.8% tier-3, 10.0% tier-1
- Positional effect: short_initial baseline mean 1.001, short_non_initial 2.006 (scale favors initial)
- Tests: `tests/test_short_resolution_baselines.py` (7 tests, all passing)
- Gate: ✓ Deterministic scoring verified (formula scores recomputed from HTR texts match manifest)

### Step 3 — Add an experiment-only structured summarizer
<!-- status: done 2026-09-22 -->

**Purpose:** Generate inspectable semantic evidence for each HTR candidate.

Reuse local model availability and JSON extraction from `alignment_llm_judge.py`, but keep summarization separate from the existing pairwise judge contract.

Schema delivered:

```json
{
  "kind": "receipt|petition|decision|appointment|continuation|no_decision|other|uncertain",
  "actor": "",
  "subject": "",
  "action_or_decision": "",
  "is_receipt_or_no_decision": false,
  "is_session_opening": false,
  "is_continuation": false,
  "evidence_quote": "",
  "uncertainty": []
}
```

**Requirements:** ✓ Implemented

- ✓ Versioned prompt (v1) and deterministic temperature (0.0)
- ✓ Preserve raw response, parsed response, model name, prompt version, input limits, and parse failures
- ✓ Few-shot examples sourced from training split only
- ✓ Long/merged HTR records marked uncertain when ambiguous; full texts stored for analysis

**Deliverable:** Experiment-only JSONL output with provenance and structured summaries

**Gate:** ✓ Implemented — reject outputs with no usable evidence quote or invalid structure from primary analysis; retain them for parse-failure reporting

**Done (2026-09-22):**
- Builder: `scripts/build_short_resolution_summaries.py`
- Dataset: `short_resolution_structured_summaries` → `output/short_resolution_structured_summaries.jsonl`
- Prompt version: v1 (few-shot context from training examples)
- Temperature: 0.0 (deterministic)
- Input char limit: 1500 chars (truncated for long texts, marked in uncertainty)
- All 80 candidates processed (dry-run validates: 5/5 parse success, gate pass)
- Tests: `tests/test_short_resolution_summaries.py` (9 tests, all passing; integrated with baseline and sample tests → 21 total passing)
- Gate logic: evidence_quote (>3 chars) + valid schema structure required for gate_passed=true
- Parse failures and gate failures both retained for analysis with parse_error and gate_notes fields
- Usage: `uv run python scripts/build_short_resolution_summaries.py [--dry-run] [--sample-mode]`
  - Default: process all 80 candidates with live LLM (requires mlx-lm + local model available)
  - `--dry-run`: mock responses for CI/testing
  - `--sample-mode`: process only first 5 records (quick validation)

### Step 3b — Freeze the authoritative summary set before ranking
<!-- status: almost complete -->

**Purpose:** Lock the summary artifact and quality gate before any ranking or boundary experiments depend on it.

**Tasks:**

- Run the final quality check on the saved summary output.
- Confirm `gate_passed` coverage on the target sample; retain only the authoritative set for the next step.
- Re-run the recovery path (`--retry-failed`) only when the saved output falls below the threshold.
- Write the summary quality report into the dataset provenance and note parse failures separately from valid summaries.
- Freeze the exact sample IDs used in the ranking step so dev/test arguments remain stable across runs.

**Deliverable:** A persisted, quality-checked summary set plus a minimal report listing:

- total records;
- pass / fail / irrecoverable counts;
- parse error count;
- mean evidence length;
- strata coverage across short vs long and opening vs non-opening cases.

**Gate:** Proceed to Step 4 only when the saved summary set is authoritative (`gate_pass_rate >= 0.90` on the intended sample), or when the run is explicitly marked diagnostic and not used for promotion.

**Notes:**
- This is the final guardrail before candidate ranking.
- It prevents ranking from running on stale or partially recovered summary output.
- It keeps the side track on the evaluation-only path and avoids silently contaminating the deterministic baselines.

### Step 3a — Recover and retry failed summaries (authoritative gate)
<!-- status: closed 2026-09-25 — stale marker; side-plan closed at Step 7 on 2026-09-22 -->

**Purpose:** Do not treat ranking, opening diagnostics, or a corpus receipt/no-decision index as authoritative while structured summaries remain below quality threshold.

**Process (mandatory after any live Step 3 run):**

1. Check coverage:
   ```bash
   uv run python scripts/build_short_resolution_summaries.py --quality-check
   ```
2. If below threshold (≥ 90% `gate_passed`):
   ```bash
   uv run python scripts/build_short_resolution_summaries.py --retry-failed
   ```
   This recovers salvageable JSON from saved `raw_response` first, then re-calls the LLM only for remaining failures and merges into `short_resolution_structured_summaries`.
3. Re-run `--quality-check` until authoritative (or inspect irreducible failures and document them).

**Downstream enforcement:**

- Step 4 ranking refuses a live run when summaries are below threshold unless `--allow-incomplete-summaries` (diagnostic only).
- A night corpus receipt/no-decision index must not start until this gate passes on the intended sample/corpus summaries.

**Deliverable:** Same dataset with improved gate-pass rate; quality report printed by the builder.

**Gate:** Authoritative iff `gate_pass_rate >= 0.90` on the saved summary set.

### Step 4 — Test semantic candidate ranking
<!-- status: done 2026-09-22 -->

**Purpose:** Determine whether generated summaries improve local alignment decisions.

For each enriched resolution, present the LLM with two or three deterministic, chronology-valid candidate HTR spans. Include the enriched summary and generated candidate summaries or candidate text, but do not reveal the gold label.

Evaluate:

- top-1 candidate accuracy;
- top-2 recall;
- abstention/uncertain rate;
- accuracy by stratum;
- whether the LLM adds value when entity/formula scores are weak;
- agreement between structured fields and the enriched summary.

Do not allow this step to alter session membership or resolution count.

**Deliverable:** Candidate-ranking report with baseline rank, LLM rank, combined rank, confidence, evidence quote, and gold outcome.

**Gate:** Continue only if the LLM improves held-out ranking over the strongest deterministic baseline, not merely over the positional-only baseline.

**Done (2026-09-22):**
- Builder: `scripts/build_short_resolution_ranking.py`
- Summarizer: `scripts/summarize_short_resolution_ranking.py`
- Dataset: `short_resolution_ranking_report` → `output/short_resolution_ranking_report.jsonl`
- Test coverage: `tests/test_short_resolution_ranking.py` (6 tests, all passing)
- Implementation: For each enriched resolution in dev+test split, builds 2-3 chronology-valid candidates from baseline, asks LLM to rank without revealing gold, computes top-1/top-2/abstention metrics
- Gate status: **GATE_FAIL** (held-out test, n=20, live 2026-09-22): baseline top-1 **20/20**, LLM top-1 **8/20**, LLM top-2 **8/20**, abstained **7/20**. No headroom — strongest deterministic baseline already saturates; LLM cannot improve. Do not advance to Step 5/6 on ranking grounds; Step 7 likely revise/close unless a different stratum or task (opening signal) is scoped separately.
- Dry-run validation: ✓ Sample execution verified (2 records, no LLM calls, output schema valid)
- Upstream dependency: live ranking exits unless summary gate-pass ≥ 90% (override: `--allow-incomplete-summaries`, non-authoritative)

### Step 5 — Test the session-opening signal
<!-- status: skipped 2026-09-22 — Step 4 GATE_FAIL; not entered -->

**Purpose:** Test the specific hypothesis that short early resolutions are useful anchors.

Compare these groups separately:

- short and session-initial;
- short and non-initial;
- long and session-initial;
- long and non-initial;
- short item merged with following material;
- continuation or spillover cases.

Measure whether the LLM correctly identifies `is_session_opening`, `is_continuation`, and `is_receipt_or_no_decision`.

Compare against:

- position alone;
- formula signals alone;
- position plus formula signals;
- position plus formula/entity signals plus LLM.

**Deliverable:** Stratified confusion matrix and error catalogue.

**Gate:** A gain only counts if it remains after comparison with the positional-only rule.

### Step 6 — Evaluate impact on boundary placement
<!-- status: skipped 2026-09-22 — Step 4 GATE_FAIL; not entered -->

**Purpose:** Test whether the semantic signal improves the actual alignment task rather than only producing plausible summaries.

On boundary-gold session-days, compare:

1. deterministic segmentation;
2. deterministic segmentation plus formula/entity signals;
3. deterministic segmentation plus the LLM opening/candidate signal.

Use the existing evaluation harness and report:

- boundary precision, recall, and F1 at existing tolerances;
- WindowDiff and/or $P_k$;
- exact-count satisfaction;
- coverage and abstention rate;
- first-resolution/session-opening accuracy;
- results by short-initial and short-non-initial strata.

The LLM may rerank or validate deterministic, count-valid alternatives. It may not emit an arbitrary number of cuts.

**Deliverable:** Held-out boundary evaluation and five representative successes/failures.

**Gate:** Do not integrate if the semantic score improves pairwise plausibility but does not improve boundary or opening-placement metrics.

### Step 7 — Decide whether to promote or close the side track
<!-- status: done 2026-09-22 — CLOSED -->

**Promote only if:**

- held-out session-day performance improves over the strongest deterministic baseline;
- the gain survives the positional-only comparison;
- false positives and false negatives do not worsen materially;
- parse failures and runtime are acceptable;
- the gain is visible in at least one meaningful low-anchor or merged-text stratum.

**Possible promotion:**

- specialized short-opening anchor channel;
- candidate reranker for weak/no-anchor cases;
- review prioritization signal;
- index of received letters / missives that required no resolution (`is_receipt_or_no_decision`), built first from formula open+close detection and only extended with LLM after Step 3a authoritative summaries and Step 5 field validation.

**Not justified by a positive result:**

- free-form corpus-wide LLM alignment;
- replacing count-constrained segmentation;
- treating generated summaries as ground truth;
- changing the session concordance without a separate validation step;
- a night corpus receipt index while Step 3a summaries remain below the authoritative threshold.

Record the outcome and next decision in `docs/DECISIONS.md` before modifying production consumers.

**Decision (2026-09-22): CLOSE — do not promote.**

| Promote criterion | Result |
|---|---|
| Held-out beats strongest deterministic baseline | **Fail** — baseline top-1 20/20; LLM 8/20 |
| Gain survives positional-only comparison | **N/A** — no gain to test |
| FP/FN do not worsen | **Fail** — LLM regresses vs baseline (−60 pp on weak-anchor stratum) |
| Parse/runtime acceptable | Not decisive (gate already failed on accuracy) |
| Gain in low-anchor / merged stratum | **Fail** — weak-anchor n=20 baseline 100%, LLM 40%; merged n=4 baseline 100%, LLM 50% |

Steps 5–6 were not entered (Step 4 gate). Experiment artifacts remain registered for audit (`short_resolution_*` datasets); no production consumer is changed. Tier E / `short-resolution-alignment` (`align_short_resolutions.py`) is **also retired** with this close (`docs/DECISIONS.md`, 2026-09-22) — formula orphan, never measured or wired.

**If this track is ever reopened:** only with a sample where the strongest deterministic baseline fails on held-out ranking (hard negatives). Re-prompting against a saturated baseline cannot clear the gate.

## Existing implementation surfaces

- `align_short_resolutions.py`: formula-based short/no-decision baseline.
- `alignment_llm_judge.py`: local LLM loading, generation, and JSON extraction.
- `benchmark_llm_judge.py`: existing benchmark accounting pattern.
- `analyze_sequence_entity_overlap.py`: overlap matrices, sequence alignment, and gold-pair diagnostics.
- `evaluation_harness.py`: boundary F1, WindowDiff, $P_k$, and exact-count metrics.
- `output/boundary_gold_sample.json`: algorithm-independent boundary gold.
- `output/ground_truth_labeled.json`: secondary pair-level labels.
- `docs/SEGMENTATION_TRANSFER.md`: count-constrained framing and evaluation rules.
- `data_manifest.toml`: register persistent experiment outputs before pipeline code references them.

## Expected outputs

The experiment should produce, at minimum:

- a frozen sample manifest (`short_resolution_llm_sample_manifest`, Step 1 done 2026-09-22);
- deterministic baseline results;
- raw and parsed LLM summaries with prompt/model provenance;
- candidate-ranking results;
- stratified opening-resolution diagnostics;
- held-out boundary evaluation;
- a short decision note stating promote, revise, or close → **CLOSE** (Step 7, 2026-09-22).

No production dataset is replaced by this plan.

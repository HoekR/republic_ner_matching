# Step 4 Execution Guide — Test Semantic Candidate Ranking

**Status:** Implementation complete, ready for user evaluation run.

## What was implemented

### Files created

1. **Builder script:** `scripts/build_short_resolution_ranking.py`
   - Loads frozen sample manifest, baseline report, and structured summaries
   - For each enriched resolution, builds 2-3 chronology-valid candidates from baseline
   - Asks LLM to rank candidates without revealing gold labels
   - Computes metrics: top-1, top-2, abstention rate, confidence
   - Writes `short_resolution_ranking_report.jsonl` with provenance

2. **Metrics summarizer:** `scripts/summarize_short_resolution_ranking.py`
   - Analyzes ranking report
   - Computes gate status: does LLM improve over deterministic baseline?
   - Reports by position stratum (short_initial, short_non_initial, long_initial, long_non_initial)
   - Reports on weak-anchor and merged-text subsets
   - Recommends gate pass/fail

3. **Test suite:** `tests/test_short_resolution_ranking.py`
   - 6 unit tests, all passing
   - Schema validation for ranking record
   - Prompt construction and dry-run validation
   - Metrics computation

4. **Dataset registered:** `data_manifest.toml`
   - `short_resolution_ranking_report` → `output/short_resolution_ranking_report.jsonl`

## How to run

### Option 1: Quick test (dry-run, 2 records)
```bash
uv run python scripts/build_short_resolution_ranking.py --dry-run --sample-mode
uv run python scripts/summarize_short_resolution_ranking.py
```

Expected output: Schema validation, sample ranking records, gate status with insufficient data warning.

### Option 2: Full evaluation (dev + test splits, requires local LLM)
```bash
# This will use mlx-lm to call local model (must be available)
uv run python scripts/build_short_resolution_ranking.py
uv run python scripts/summarize_short_resolution_ranking.py
```

Expected runtime: ~5-10 minutes depending on LLM and hardware.

Output will include:
- Baseline vs LLM top-1 accuracy
- Top-2 recall
- Abstention rate
- Metrics by stratum
- Gate status: GATE_PASS if LLM improves over baseline, GATE_FAIL otherwise

### Option 3: Test split only
```bash
uv run python scripts/build_short_resolution_ranking.py --test-only
uv run python scripts/summarize_short_resolution_ranking.py
```

## Gate status

The gate requires:
- LLM top-1 accuracy > baseline top-1 accuracy, OR
- LLM improves at least one meaningful stratum (weak-anchor, merged, short-initial), AND
- Abstention rate < 50%

Current implementation is ready. Run the above commands to compute gate status.

## Deliverable structure

Each ranking record contains:
- **Input:** enriched_id, position_stratum, anchor_class, day_segmentation
- **Candidates:** 2-3 HTR candidates (text, summary, baseline scores)
- **LLM output:** model, prompt version, raw response, parsed choice, confidence
- **Metrics:** baseline_top1_correct, llm_top1_correct, top2_recall, abstention_rate
- **Gold outcome:** gold_htr_id, gold_rank_baseline for gate computation

## What's next

If **gate passes:**
→ Proceed to Step 5: Test the session-opening signal (is_session_opening, is_continuation accuracy by stratum)

If **gate fails:**
→ Record decision in docs/DECISIONS.md and close side track (do not promote LLM ranking to production)

## Constraints honored

✓ No hardcoded paths (all via data_io.resolve/load/save_*)\
✓ No production datasets altered\
✓ No changes to session membership or resolution count\
✓ Manifest registered before use\
✓ Provenance sidecar written automatically\
✓ Vectorized pandas (no row loops)\
✓ --dry-run mode for CI/testing\
✓ Unit tests all passing\

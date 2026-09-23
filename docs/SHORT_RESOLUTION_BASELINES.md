# Short-resolution LLM alignment baselines (Step 2)
<!-- doc-status: sidelined -->

## Overview

Step 2 of `plans/SHORT_RESOLUTION_SIDE_PLAN.md` establishes deterministic baselines for the frozen 80-candidate sample from Step 1.

The baselines measure what the LLM must beat on the held-out test set. All scoring is deterministic and reproducible: the gate is that baseline inputs remain identical across comparison runs.

## Baseline Signals

For each of the 80 frozen HTR candidates, we compute four deterministic baseline scores:

### 1. **Alignment confidence score** (tier + overlap)
- Ranks by alignment confidence tier (tier1 < tier2 < tier3 < none)
- Within tier, prefers higher entity/sequence overlap
- Input: `alignment_confidence_tier`, `alignment_overlap_score` from Step 1 manifest

### 2. **Positional-only score**
- Prefers HTR items at session start (`is_session_initial=True`)
- Secondary preference for earlier session order
- Tests hypothesis: does position alone (without semantic evidence) predict alignment?

### 3. **Formula-based detection**
- Boolean: both opening *and* closing phrase match from `align_short_resolutions.py`
  - Opening phrases: "ontfangen een missive", "ontfangen een requeste", etc.
  - Closing phrases: "geen resolutie is gevallen", "sonder resolutie", etc.
- Using FuzzyPhraseSearcher with Levenshtein similarity ≥ 0.8
- Empirical phrase inventory from S2 anchor harvesting over 5,725 tier-1 anchors

### 4. **Combined formula+entity score**
- Weights formula signals (prefer both open + close) and alignment tier/overlap
- Bonus if both formula signals detected; penalty if neither
- Reflects that formula-detected candidates should rank high *despite* weak alignment tier

## Results Summary

**Frozen sample:** 80 candidates (40 train / 20 dev / 20 test)

| Metric | Train | Dev | Test | Overall |
|--------|-------|-----|------|---------|
| Candidates | 40 | 20 | 20 | 80 |
| Formula detection rate | 2.5% | 0.0% | 0.0% | 1.2% |
| Tier 1 anchor | 5 | 3 | 0 | 8 (10.0%) |
| No tier | 27 | 14 | 20 | 59 (73.8%) |
| Alignment score mean | 5.0 | 4.7 | 5.7 | 5.1 |
| Positional score mean | 1.50 | 1.55 | 1.50 | 1.51 |

**Position stratum analysis:**

- **short_initial** (n=18): alignment score mean 4.22, positional mean 1.00
- **short_non_initial** (n=21): alignment score mean 5.91, positional mean 2.01
- **long_initial** (n=21): alignment score mean 4.29, positional mean 1.00
- **long_non_initial** (n=20): alignment score mean 5.90, positional mean 2.01

**Key observations:**
- Position is a **strong signal**: session_initial candidates score ~1.0, non_initial ~2.0 (difference of 1.0 unit)
- Alignment coverage is **sparse**: 73.8% have no confidence tier; 10.0% have tier-1 anchor
- Formula detection is **rare**: only 1 candidate (1.2%) shows both open + close phrase match
  - This low rate is expected: short receipts-without-decision are uncommon in a sample balancing strata
  - The pilot was designed to include mixed short and long, initial and non-initial to separate positional effects from semantic effects

## Data Paths

| Dataset | Path | Records |
|---------|------|---------|
| **Input (Step 1)** | `output/short_resolution_llm_sample_manifest.jsonl` | 81 (1 meta + 80 candidates) |
| **Input (support)** | `resolutions_flat.parquet` (HTR text lookup) | ~4000 |
| **Output (Step 2)** | `output/short_resolution_baseline_report.jsonl` | 81 (1 meta + 80 baselines) |

## Usage

**Build baselines:**
```bash
uv run python scripts/build_short_resolution_baselines.py
```

**Summarize baselines:**
```bash
uv run python scripts/summarize_short_resolution_baselines.py
```

**Test baseline scoring logic:**
```bash
uv run pytest tests/test_short_resolution_baselines.py -v
```

## Scoring Normalization

All baseline scores are normalized to a comparable scale (lower = more preferred):

- **Alignment score:** 0-6 range (tier ranking 0-5, overlap penalty -0.1 to 0.0)
- **Positional score:** 1.0-3.0+ range (initial=1.0, non_initial=2.0, ±session_order penalty)
- **Combined score:** alignment score ± formula bonus/penalty (±0.3 to ±1.0)

Scores are deterministic and reproducible from manifest data (formula signals verified by recomputation from HTR texts).

## Next Step (Step 3)

Step 3 will:
1. Add an LLM-based structured summarizer (using local Ollama or similar)
2. Generate semantic evidence for each candidate (kind, actor, subject, is_session_opening, etc.)
3. Keep raw/parsed responses with provenance
4. Use few-shot examples from training split only

Step 3 output will be scored against these baselines to measure whether LLM summaries add value over deterministic signals.

## References

- `plans/SHORT_RESOLUTION_SIDE_PLAN.md` — full side-track plan
- `align_short_resolutions.py` — formula searcher configuration and phrase inventory
- `build_short_resolution_llm_sample.py` — Step 1: frozen sample builder
- `build_short_resolution_baselines.py` — Step 2: baseline builder (this step)

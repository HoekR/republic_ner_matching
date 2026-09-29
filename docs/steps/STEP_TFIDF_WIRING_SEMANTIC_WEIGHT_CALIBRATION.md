# Step 1: Semantic-Weight Calibration for TF-IDF Similarity Wiring

**Status**: Ready to start (Step 0 gate passed 2026-09-29, AUC 0.9555)  
**Goal**: Wire TF-IDF semantic similarity into the corpus predictor and calibrate its weight to improve placement accuracy.  
**Success criteria**: Measure paragraph-level F1 on the 50 gold days with semantic similarity wired in; if it improves the lumped baseline (0.828 at tol150), accept the improvement and proceed to corpus-scale testing.

## Background

- **Step 0 (completed)**: Measured that TF-IDF semantic similarity separates correct from incorrect enriched<->flat resolution pairings with AUC 0.9555 (discrimination: positive-pair mean 0.180 vs. negative 0.069). This is independent evidence, on a stratified sample, that the signal is real and separable.
- **Current state**: The semantic similarity backend exists (`alignment_embeddings.py`, TF-IDF backend), and `align_session` (the NW aligner) accepts `similarity_matrix` and `semantic_weight` parameters, but both default to off (similarity_matrix=None, semantic_weight=0.0).
- **Gap**: The corpus predictor (`s4_corpus_paragraph_predictions.py` line 114) calls `align_session` with default parameters, so semantic similarity is never computed or used in placement.

## Mechanism

**TF-IDF Similarity Matrix computation** (from `alignment_embeddings.py`):
- Input: two lists of resolution texts (enriched summaries and HTR paragraphs)
- Output: N × M matrix of cosine similarities (0 to 1)
- Method: combined word (0.4 weight) and character n-gram (0.6 weight) TF-IDF vectors
- Cost: ~100–300ms per day (depends on text length and vocabulary size)

**Integration into alignment** (from `build_alignment_new.py:933–935`):
```python
sem_sim = float(similarity_matrix[i-1, j-1]) if similarity_matrix is not None else 0.0
sem_score = sem_sim * semantic_weight
total_match_score = entity_match_score + sem_score
```

The semantic score is **additive**: it's multiplied by a weight and summed with the entity overlap score. The weight controls the contribution relative to entity overlap.

**Anchor gate** (from `build_alignment_new.py:938`):
```python
has_anchor = entity_match_score > 0 or (similarity_matrix is not None and sem_sim >= min_semantic_threshold)
```

A match is allowed (passes `anchor_only_diagonal` gate) if **either**:
- Entity overlap score > 0, **OR**
- Semantic similarity ≥ min_semantic_threshold (currently 0.35, from Step 0 calibration)

## Step 1 Phases

### Phase 1a: Adapt corpus predictor to accept semantic similarity

**File**: `scripts/s4_corpus_paragraph_predictions.py`  
**Change**: 
1. Import `AlignmentEmbedder` from `alignment_embeddings.py`
2. Accept new command-line arguments:
   - `--semantic_backend` (default "tfidf"; options: "tfidf", "ollama", "transformers")
   - `--semantic_weight` (default 0.0, off; range to test: 0.5–5.0)
3. For each calendar day:
   - Extract enriched summary texts (one text per resolution, or concatenate text)
   - Extract HTR axis texts (one per paragraph, or one per resolution)
   - Compute similarity matrix via `AlignmentEmbedder.compute_similarity_matrix()`
   - Pass to `align_session(similarity_matrix=matrix, semantic_weight=weight, min_semantic_threshold=0.35)`

**Inputs**:
- Enriched resolutions: `enriched_resolutions_1626_1630` (per date, ordered by resolution_index)
- HTR axis: `paragraph_axis_1626_1630` (per date, already ordered)

**Output**:
- Modified `s4_corpus_paragraph_predictions.jsonl` with semantic similarity active

**Effort**: ~200 lines; should be straightforward since `align_session` already handles it.

### Phase 1b: Test on gold days (50-day sample)

**File**: `scripts/s4_paragraph_axis_baseline.py`  
**Change**: Adapt the existing gold-day test harness to accept `--semantic_weight` and pass it through to `align_session`.

**Measurement**:
1. Run the existing `evaluate_s4_paragraph_axis.py` gold-evaluation harness on the 50 gold days with semantic_weight OFF (baseline).
2. Sweep semantic_weight over [0.5, 1.0, 1.5, 2.0, 3.0, 5.0].
3. For each weight, measure:
   - **Primary**: paragraph-level lumped F1 at tol0/50/150 (same as the baseline)
   - **Secondary**: coverage (days predicted / eligible days), strict (character-coordinate) F1 at tol0/50/150
4. Report results per day and corpus-wide.

**Success criterion**: At least one weight improves lumped F1@tol150 above the 0.828 baseline.

**Cost**: ~10–15 runs × ~2 minutes per run = 20–30 minutes total (parallelizable if desired).

### Phase 1c: Calibrate weight on gold; decide corpus-scale test

**Decision logic**:
1. If lumped F1 improves ≥0.01 (e.g., 0.828 → 0.838+): accept the best weight and proceed to Phase 2.
2. If lumped F1 stays flat or regresses: investigate why (analogue to the Group-B/C position_scores analysis).
   - Check per-day F1 changes (which days moved, by how much?)
   - Check whether the semantic matches are helping or hurting (scatter plot of sem_sim vs. correctness)
   - Decide: retry with a different weight range, or close this step as "discriminates in isolation but doesn't help in context."
3. Secondary criterion: prefer the smallest weight that achieves the improvement (Occam's razor).

**Output**: Recommended semantic_weight for corpus testing (or decision to close the step).

## Expected Challenges

1. **Text representation**: Should each enriched resolution be a single concatenated text, or should they be processed as separate summaries? The writeup notes that the gate measurement used "enriched summary texts" and "flat resolution texts" without specifying granularity. Starting point: one text per enriched resolution (concatenate all paragraphs from its flat counter-parts where available) vs. one per paragraph.

2. **Cross-day contamination**: The similarity matrix for a given day is computed only from that day's texts (enriched + axis). If a flat resolution spans multiple calendar dates (a cross-day-shift day), the matrix won't capture semantic similarity with other dates' enriched resolutions. This is the same boundary condition `segment_day` already faces.

3. **Performance**: The writeup says this is cheap (~100–300ms/day), but the corpus has ~1,300 calendar days with an axis, so corpus-wide computation is ~2–6 minutes. Acceptable, but parallelizable if needed.

4. **Interaction with position_scores**: The existing `position_scores` mechanism (phrase hits, entity density) is orthogonal to semantic_weight (which affects the NW alignment phase, not the gap-filling phase). They can coexist, but their interaction isn't yet measured. Phase 1c can defer this to Phase 2.

## Phase 2 (not in scope for this step)

Once Phase 1c recommends a weight, Phase 2 would:
- Run corpus-wide with semantic similarity active at the recommended weight
- Measure corpus-wide separated accuracy, coverage, and span metrics
- Decide whether to make this the production default or keep it off

**Potential Phase 2 extension**: Backend comparison. `alignment_embeddings.py` supports TF-IDF (default, proven at Step 0), GysBERT (transformers), GloBERTise (alternative model for Dutch text), and Ollama (local LLM). Step 1 uses TF-IDF. If the TF-IDF weight recommendation is promising, Phase 2 could test whether a heavier-weight backbone (GysBERT, GloBERTise) improves further, though this would require re-training/downloading model weights.

## Reference Files

- `alignment_embeddings.py`: The `AlignmentEmbedder` class (already exists, TF-IDF backend ready)
- `build_alignment_new.py`: The `align_session` NW aligner (lines 900–971)
- `scripts/s4_corpus_paragraph_predictions.py`: Corpus predictor (where wiring needs to happen)
- `scripts/s4_paragraph_axis_baseline.py`: Gold-day baseline (where testing harness should adapt)
- `scripts/evaluate_s4_paragraph_axis.py`: Gold-day evaluation harness (already measures lumped F1)
- `scripts/tfidf_similarity_pair_discrimination_eval.py`: Step 0 gate measurement (reference implementation)
- `docs/writeup_mechanism_anchors.md`: Step 0 findings and context

## Deliverables

1. **Modified corpus predictor** (`s4_corpus_paragraph_predictions.py`): accepts `--semantic_backend` and `--semantic_weight` flags
2. **Gold-day test results** (20–30 minute runs, sweep over 6 weight values): per-day and corpus-wide lumped F1, coverage, strict F1
3. **Weight recommendation** (decision record in `docs/DECISIONS.md`): best weight for corpus testing, or decision to defer
4. **If proceeding to Phase 2**: corpus-wide run output and whether semantic similarity becomes a production default

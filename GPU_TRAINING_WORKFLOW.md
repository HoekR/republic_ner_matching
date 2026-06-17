# Two-Model NER Training Workflow

## Overview

You're training **two separate specialized NER models** on the Surf GPU machine:

1. **PLACE Model** (`gysberg_place_ner_gpu`) — Recognizes location mentions
2. **DELEGATE Model** (`gysberg_delegate_ner_gpu`) — Recognizes delegate/person names

## Why Separate Models?

| Model | Purpose | Training Data | Use Case |
|-------|---------|---------------|---------:|
| **PLACE** | Identify location mentions | 21K LOC annotations (1626-1630) | Align resolutions by geography |
| **DELEGATE** | Identify delegate names | 13K PER annotations (1626-1630) | Search resolutions by person |

Separate models allow:
- ✅ Each model optimized for its entity type (locations vs names)
- ✅ Reusable embeddings (GysBERT trained on Dutch text of 1626-1630)
- ✅ Independent evaluation per entity type
- ✅ Flexibility: use PLACE alone for alignment, DELEGATE alone for search, or both

## Training Timeline

```
macOS (local) → Transfer data → SURF GPU machine
                                    ↓
                          Train PLACE (20-30 min)
                                    ↓
                          Train DELEGATE (15-25 min)
                                    ↓
                          Transfer models back → macOS
```

## Technical Details

### PLACE Model (`finetune_gysberg_gpu.py`)

```python
Training data:    training_pairs_loc_1626_1630_dedup.parquet
Entity type:      PLACE
Dataset size:     21,310 records
Split:            70% train (7,501 sentences) / 15% dev / 15% test
Output:           models/gysberg_place_ner_gpu/best-model.pt
```

**Key training params:**
- Batch size: 16
- Epochs: 15
- Learning rate: 0.1
- CRF layer: Yes (for sequence modeling)
- RNN: Yes (bidirectional LSTM)

### DELEGATE Model (`finetune_gysberg_delegate.py`)

```python
Training data:    training_pairs_per_1626_1630_dedup.parquet
Entity type:      NAME (delegate mentions)
Dataset size:     13,274 records
Split:            70% train / 15% dev / 15% test
Output:           models/gysberg_delegate_ner_gpu/best-model.pt
```

**Same training params as PLACE model** (for consistency).

## Data Characteristics

### PLACE Data
- **Entities**: 21,310 place name mentions
- **Examples**: "Texel", "Amsterdam", "Batavia"
- **Length**: Short (typically 1-3 tokens)
- **Challenge**: Ambiguous names (could be places or people)

### DELEGATE Data
- **Entities**: 13,274 delegate name mentions
- **Examples**: "Nicolaes Brouwer", "Jan Jansz"
- **Length**: Often multi-word (2-4 tokens)
- **Challenge**: Name variants and abbreviations (see `hoe_classify.py` for mapping)

## Offset-Based Labeling

Both models use **character offset matching** (not word-boundary matching):

```python
# For each token, check if its character range overlaps with annotation spans:
if token.start_position < annotation_end and token.end_position > annotation_start:
    token.label = 'PLACE' or 'NAME'
else:
    token.label = 'O'
```

This ensures exact alignment with the ground-truth annotations.

## Evaluation Metrics

After training, each model produces:
- **Precision**: Of tokens predicted as PLACE/NAME, how many are correct?
- **Recall**: Of all actual PLACE/NAME tokens, how many did we find?
- **F1**: Harmonic mean of precision and recall

Expected performance:
- **PLACE F1**: 0.70-0.85 (places are fairly consistent)
- **DELEGATE F1**: 0.60-0.75 (names are noisier, variants/abbreviations)

## Next Steps After Training

### 1. Evaluate Test Set

```bash
# Load best-model.pt and run on test set
# Save precision/recall/F1 metrics per entity type
```

### 2. Error Analysis

Look at false positives / false negatives:
- **PLACE FPs**: What's being mislabeled as places?
- **DELEGATE FNs**: What delegate names are missed?

### 3. Inference on Full Dataset

Use both models on **all 1626-1630 resolutions** (not just training data):
- Extract all PLACE mentions → build location index
- Extract all DELEGATE mentions → build person index

### 4. Resolution Alignment

Match resolutions by:
- **PLACE overlap**: If two resolutions mention same location
- **DELEGATE overlap**: If they mention same delegates
- **Combined score**: Weight both signals

## File Outputs

### Training Logs
```
models/gysberg_place_ner_gpu/training.log
models/gysberg_delegate_ner_gpu/training.log
```

### Model Artifacts
```
models/gysberg_place_ner_gpu/best-model.pt      # Best on dev set
models/gysberg_place_ner_gpu/final-model.pt     # After all epochs
models/gysberg_delegate_ner_gpu/best-model.pt
models/gysberg_delegate_ner_gpu/final-model.pt
```

### Results
```
models/gysberg_place_ner_gpu/results.txt        # Eval metrics
models/gysberg_delegate_ner_gpu/results.txt
```

## Troubleshooting

**Q: PLACE model F1 < 0.5?**  
A: Check if training data was correctly parsed. Run `test_offset_labeling.ipynb` first.

**Q: DELEGATE model has high F1 but low recall?**  
A: Name variants may be missing. Check if `entity_id` mapping is one-to-one.

**Q: GPU memory error during training?**  
A: Reduce `BATCH_SIZE` in the script (e.g., 8 instead of 16).

**Q: Training is very slow?**  
A: Check `nvidia-smi` to confirm both GPUs are being used.

## References

- Model: `emanjavacas/GysBERT` (trained on 17th-18th century Dutch)
- Framework: `flair` 0.15.0 (state-of-the-art sequence labeling)
- Architecture: Transformer + BiLSTM + CRF
- Loss function: Negative log-likelihood (CRF loss)

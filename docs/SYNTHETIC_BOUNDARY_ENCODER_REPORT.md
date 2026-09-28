# Synthetic boundary encoder — run report
<!-- doc-status: active -->

Generated: 2026-09-27T09:01:50.542463+00:00

## Setup

- Device: `cpu`
- Synthetic test n: **304**
- Gold n: **55** (scaffold suggested_boundaries auto-accepted; not hand-reviewed)
- Models: `emanjavacas/GysBERT`, `globalise/GloBERTise`
- Tolerances: 0, 50, 150

Task: recover internal char cut points in concatenated HTR (no separator).
Baseline: even character split knowing `n_cuts`. Encoders: token-level boundary taggers fine-tuned with curriculum (2-res then 2+4-res).

## Results

### synthetic_test

| predictor | F1@0 | F1@50 | F1@150 | exact-count |
|---|---:|---:|---:|---:|
| `even_split_baseline` | 0.002 | 0.073 | 0.345 | 1.000 |
| `emanjavacas/GysBERT` | 0.336 | 0.377 | 0.507 | 1.000 |
| `globalise/GloBERTise` | 0.975 | 0.980 | 0.991 | 1.000 |

### gold

| predictor | F1@0 | F1@50 | F1@150 | exact-count |
|---|---:|---:|---:|---:|
| `even_split_baseline` | 0.000 | 0.095 | 0.242 | 1.000 |
| `emanjavacas/GysBERT` | 0.179 | 0.232 | 0.274 | 1.000 |
| `globalise/GloBERTise` | 0.747 | 0.758 | 0.768 | 1.000 |

## Comparison

- Best on gold @tol50: **`globalise/GloBERTise`** (F1=0.758) vs even-split (F1=0.095).
- Synthetic-test @tol50 best: **`globalise/GloBERTise`**.

## Caveats

- Gold boundaries equal machine `suggested_boundaries` (cumulative segment lengths), not hand review.
- Examples truncated at encoder `max_length=512`; fold builder also capped concat at 2500 chars.
- Train caps: 1200 pairs + 600 quads (see `synthetic_boundary_folds` meta).
- MPS/CPU run; not a full hyperparameter sweep.

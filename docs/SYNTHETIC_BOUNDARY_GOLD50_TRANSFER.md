# Synthetic boundary encoder — transfer on 50-day gold bundled paragraphs
<!-- doc-status: active -->

Transfer test: fine-tuned merge-boundary encoders (trained on synthetic separated-slice concatenations) scored on real gold **bundled** paragraphs from `boundary_gold_sample` (same units as `s4_bundled_split_poc`: mid_paragraph char offsets inside paragraphs that carry 2+ gold cut slots).

## Setup

- Device: `mps`
- Model tag: `hard`
- Bundled paragraphs with mid_paragraph gold: **22**
- Gold interior cuts: **27**
- Tolerances: 0, 50, 150
- Predictors: even-split (knows `n_cuts`) · encoders · encoder+phrase_snap (snap distance 150)

## Results (micro P/R/F1 via `compute_boundary_prf`)

| predictor | F1@0 | F1@50 | F1@150 | P@50 | R@50 | exact-count |
|---|---:|---:|---:|---:|---:|---:|
| `even_split_baseline` | 0.000 | 0.222 | 0.630 | 0.222 | 0.222 | 1.000 |
| `globalise/GloBERTise` | 0.037 | 0.259 | 0.630 | 0.259 | 0.259 | 1.000 |
| `globalise/GloBERTise+phrase_snap` | 0.148 | 0.222 | 0.556 | 0.222 | 0.222 | 1.000 |

## Verdict

- Best @tol50: **`globalise/GloBERTise`** (F1=0.259) vs even-split (F1=0.222).
- Compare against `s4_bundled_split_poc` NER/dictionary heuristics (previously ~0–15% recall @tol50 on the same 22-position family).

## Caveats

- This is **transfer / OOD**: train distribution was concat of separated resolution slices; test is a single HTR paragraph that gold says contains multiple resolutions.
- `n_cuts` is taken from gold (oracle count), same privilege the even-split baseline and the earlier POC had.
- Encoder `max_length=512` may truncate long paragraphs.

# Synthetic boundary encoder track (GysBERT / GloBERTise)
<!-- doc-status: active -->

**Separate from** session-day `boundary_gold_sample` (S3 segmentation transfer). Goal: fine-tune historical Dutch encoders on an artificial **merge → recover boundaries** task, then evaluate on hand-verified gold.

## Pipeline order

1. **Gold scaffold** — `uv run python scripts/build_synthetic_boundary_gold_scaffold.py`
2. **Label** — export `synthetic_boundary_gold_annotations.json` (hand review *or* accept `suggested_boundaries`; see merge script docstring)
3. **Merge gold** — `uv run python scripts/merge_synthetic_boundary_gold_annotations.py` *(done 2026-09-27: 55 auto-accepted suggested boundaries)*
4. **Folds** — `uv run python scripts/build_synthetic_boundary_folds.py`
5. **Train** — `uv run python scripts/train_synthetic_boundary_encoder.py --model emanjavacas/GysBERT` (and `globalise/GloBERTise`)
6. **Eval + report** — `uv run python scripts/eval_synthetic_boundary_encoder.py --models …` then `docs/SYNTHETIC_BOUNDARY_ENCODER_REPORT.md` via `run_synthetic_boundary_pipeline.py`

Or one shot: `uv run python scripts/run_synthetic_boundary_pipeline.py`

## Conventions

- HTR segments concatenated with **no separator** (S6a char axis).
- Internal gold = cumulative segment character lengths.
- Candidates: consecutive **separated** resolutions on the same date (concordance paragraph attribution + `paragraph_axis_1626_1630`).
- Dates present in `boundary_gold_sample` are excluded from the scaffold pool.

## Manifest datasets

| Logical name | Role |
|--------------|------|
| `synthetic_boundary_gold_scaffold` | Machine scaffold for expert review |
| `synthetic_boundary_gold_annotations` | Raw export from annotation |
| `synthetic_boundary_gold` | Benchmark (never train); 2026-09-27 auto-accepted suggested boundaries |
| `synthetic_boundary_folds` | Train/val/test synthetic merges excluding gold ids |
| `synthetic_boundary_eval_report` | P/R/F1 comparison (baseline + encoders) |

Report: [docs/SYNTHETIC_BOUNDARY_ENCODER_REPORT.md](../SYNTHETIC_BOUNDARY_ENCODER_REPORT.md)

## Transfer on 50-day gold (bundled paragraphs)

```bash
uv run python scripts/eval_synthetic_boundary_on_gold50.py
```

Uses the same 22 bundled mid_paragraph positions as `s4_bundled_split_poc`. Write-up:
[docs/SYNTHETIC_BOUNDARY_GOLD50_TRANSFER.md](../SYNTHETIC_BOUNDARY_GOLD50_TRANSFER.md).

## More lumped-paragraph gold (human)

Expand mid_paragraph GT beyond the 50-day sample (notes / uncertain / clutter supported).
Flask UI mirrors `trifecta-annotation/gold_labeller` (Jinja + `POST /api/save/<id>` → disk JSON).

```bash
uv run python scripts/build_lumped_paragraph_gold_scaffold.py   # ~80 candidates (once)
uv run lumped-paragraph-gold-ui                                 # http://127.0.0.1:5055
# annotate: |||CUT||| + notes; each Save writes output/lumped_paragraph_gold_annotations.json
uv run python scripts/merge_lumped_paragraph_annotations.py --annotator YOUR_NAME
```

Datasets: `lumped_paragraph_gold_scaffold`, `lumped_paragraph_gold_annotations`, `lumped_paragraph_boundary_gold`.

## Encoders (Hugging Face)

- `emanjavacas/GysBERT`
- `globalise/GloBERTise`

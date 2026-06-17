# Alignment generation

This folder contains the reproducible generation pipeline extracted from the notebook.

Run it with:

```bash
uv run python generate_alignment/build_alignment_artifacts.py
```

It produces:

- `output/matched_resolutions_sample.html`
- `output/ground_truth_stratified_matches.json`
- `output/ground_truth_stratified_matches.jsonl`
- `output/ground_truth_stratified_matches.parquet`
- `output/ground_truth_matches.json`
- `output/verify_ground_truth.html`

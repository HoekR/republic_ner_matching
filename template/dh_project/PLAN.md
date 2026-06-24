# Project plan

## Goal

<!-- One paragraph: what this project produces -->

## Data paths

Logical names live in [`data_manifest.toml`](data_manifest.toml). Verify with `uv run python -m data_io.check`.

| Logical name | Phase | Notes |
|--------------|-------|-------|
| | explore / semi / frozen | |

## Phases

### Phase 1 — Explore

- [ ] Register inputs in manifest
- [ ] `data_io.check` passes

### Phase 2 — Semi-structured

- [ ] Outputs via `save_semi_structured`

### Phase 3 — Frozen

- [ ] Promote stable tables to `save_parquet`

## Outputs

| Artifact | Logical name | Path (via manifest) |
|----------|--------------|---------------------|

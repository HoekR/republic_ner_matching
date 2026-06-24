# Agent instructions — DH data project

Read this file, `docs/DATA.md`, and `PLAN.md` before writing pipeline code.

## Data paths (strict)

- **Never** hardcode absolute paths (`/Users/...`, `/Volumes/...`) in Python scripts.
- **Always** register datasets in `data_manifest.toml` first, then use:
  ```python
  from data_io import resolve, load, save_semi_structured, save_parquet
  ```
- **Always** run after manifest or tier changes:
  ```bash
  uv run python -m data_io.check
  ```

## Output writes (strict)

- Phase 1–2 (explore / semi): `save_semi_structured(..., logical_name="...", script=__file__)`
- Phase 3 (frozen): `save_parquet(df, logical_name="...", script=__file__)`
- Never write pipeline outputs without sidecar provenance (`data_io` does this automatically).

## Legacy / orphan files — `llm_archivist`

For **existing** files without `data_io` sidecars (inbox dumps, old exports):

```bash
# Fast — no Ollama (columns, coverage, row counts)
uv run archive-inventory /path/to/folder

# LLM — rich description (requires Ollama at localhost:11434)
uv run archive-scan /path/to/folder --model qwen2.5-coder:latest
```

- Profiles `.parquet`, `.csv`, `.xlsx`, `.ipynb` → `filename.meta.toml`
- Use on `scratch/_inbox/` or migrated legacy data — **not** on `data_io` outputs
- After inventory, read **`INVENTORY.md`** at the scan root; add canonical files to `data_manifest.toml`

| Tool | When | Sidecar | LLM? |
|------|------|---------|------|
| `data_io.save_*` | New pipeline outputs | `.meta.toml` / `.parquet.meta.json` | No |
| `archive-inventory` | Fast orphan triage | `.meta.toml` (`inventory_mode = "fast"`) | No |
| `archive-scan` | Rich archival context | `.meta.toml` | Yes |

## Before adding a dataset

1. Add `[datasets.<logical_name>]` to `data_manifest.toml` (tier, path, phase, description, parent).
2. Run `data_io.check`.
3. Only then reference `logical_name` in code.

## Archival integrity

- Do not drop metadata fields from domain records when transforming.
- Do not mutate canonical reference files in place; write versioned outputs.
- Promote JSONL → Parquet only when schema is stable for one review cycle.

## Session workflow

1. Read `PLAN.md` for current phase and outputs.
2. Update `PLAN.md` data-path table when manifest datasets change.
3. Smoke test: `uv run python -c "from data_io import resolve; print(resolve('...'))"`

## Common mistakes (avoid)

| Wrong | Right |
|-------|-------|
| `pd.read_parquet("/Volumes/...")` | `load("resolutions_flat")` |
| `open("data/out.jsonl", "w")` | `save_semi_structured(rows, logical_name="...")` |
| `archive-scan` on `data_io` outputs | Only scan legacy/orphan folders |
| New path in code only | New `[datasets.*]` entry + `data_io.check` |

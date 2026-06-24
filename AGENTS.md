# Agent instructions — republic_ner_matching

Read **`docs/DATA.md`** and **`data_manifest.toml`** before pipeline work.

## Data paths

- Use `from data_io import resolve, load, save_parquet, save_semi_structured` — no absolute paths in scripts.
- Register new datasets in `data_manifest.toml` before referencing them in code.
- After manifest edits: `uv run python -m data_io.check`
- Keep `PLAN.md` `## Data paths` in sync with `[datasets.*]` keys.

## Outputs

- Semi-structured: `save_semi_structured(..., logical_name=..., script=__file__)`
- Frozen: `save_parquet(df, logical_name=..., script=__file__)`

## Archival integrity

See root `.cursorrules` — never drop provenance fields; version reference data instead of in-place mutation.

## Bootstrap a sibling project

```bash
./scripts/bootstrap_dh_project.sh ~/develop/NewProject new-project
```

Requires `~/develop/llm-archivist` (copied into new project). See [docs/SKELETON.md](docs/SKELETON.md).

## Legacy file documentation (`llm_archivist`)

```bash
# Fast inventory (no Ollama) — start here
./scripts/inventory_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"

# LLM enrichment (Ollama required)
./scripts/archive_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"
```

Do **not** run on files written by `save_semi_structured` / `save_parquet`.

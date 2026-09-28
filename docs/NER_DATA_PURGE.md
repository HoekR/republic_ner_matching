# NER data / scratch purge plan (`republic_ner_matching`)

*Status: policy written 2026-09-28. Destructive moves are staged; run the commands below when ready.*

## Size drivers (measured)

| Path | ~Size | Policy |
|------|-------|--------|
| `output/` | **18G** | Scratch. Already gitignored. Prefer `data_manifest` scratch tier (`/Volumes/Extreme SSD/scratch`) for new model checkpoints |
| `data.bak/` | **11G** | Cold backup of pre-symlink `data/`. **Safe to delete after confirming warm symlink is complete** |
| `.git/` | 1.9G | Normal; shrinks after `git gc` once large blobs are gone from history |
| `.venv/` | 1.3G | Local only (gitignored) |
| `mlx_llm/` | 315M | Nested tool + venv; keep code, ignore nested `.venv` |
| `data` → symlink | — | **Correct:** `/Volumes/2tb disk/datasets/republic` |

Symlink already in place; warm data must not return into the git tree.

## Immediate gitignore hardening

Ensure these stay untracked:

- `data.bak/`
- `output/` (all model checkpoints, `*.safetensors`, `optimizer.pt`)
- `*.zip`, `*.tar.gz`
- nested `mlx_llm/.venv/`

## Recommended purge order (human-run)

```bash
# 1. Confirm warm mount and symlink
ls -la data
uv run python -m data_io.check

# 2. Spot-check that critical files exist on warm tier (not only in data.bak)
test -f data/resolutions/resolutions_flat.parquet || test -f "/Volumes/2tb disk/datasets/republic/resolutions/resolutions_flat.parquet"

# 3. Move data.bak to scratch archive (recoverable) then delete when satisfied
mkdir -p "/Volumes/Extreme SSD/scratch/_archive/ner_data_bak_20260928"
# rsync -a --info=progress2 data.bak/ "/Volumes/Extreme SSD/scratch/_archive/ner_data_bak_20260928/"
# rm -rf data.bak

# 4. Relocate heavy model checkpoints to scratch (keep final only in repo output if needed)
# mv output/synthetic_boundary_models "/Volumes/Extreme SSD/scratch/republic_ner/synthetic_boundary_models"

# 5. Optional: git gc after history cleanup (separate task; does not remove working-tree bulk)
```

## Manifest policy

- Inputs: `data_manifest.toml` → warm/hot tiers only
- Pipeline writes: `save_semi_structured` / `save_parquet` → scratch logical names
- Never re-copy `Food_terms`-style reference or resolutions into the git root

## Done in this inventory pass

- Documented size drivers and purge commands
- Hardened `.gitignore` for archive/backup and ML artifacts
- Inventory cross-link: [REPUBLIC_REPO_INVENTORY.md](REPUBLIC_REPO_INVENTORY.md)

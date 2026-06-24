# Data layout and manifest

Decouple code from disk layout using `data_manifest.toml` and `data_io`.

## Tiers (edit in `data_manifest.toml`)

| Tier | Typical role |
|------|----------------|
| **hot** | Code repos, tiny local inputs |
| **warm** | Canonical parsed datasets (parquet, annotation JSON) |
| **scratch** | Ephemeral exports, semi-structured JSONL |
| **cold** | Raw archives (zip, XML dumps) |
| **collab** | SurfDrive / Nextcloud shared data |

## Day-zero checklist

1. `cp data_manifest.toml.example data_manifest.toml` — fill tier roots for this machine.
2. Optional: `data_manifest.local.toml` (gitignored) for laptop vs SURF paths.
3. `uv run sync` or `uv pip install -e .`
4. `uv run python -m data_io.check`
5. Add `[datasets.*]` entries before writing scripts that read/write data.

## Three-phase pipeline

| Phase | Format | Save via |
|-------|--------|----------|
| explore | jsonl, pkl, xlsx | `save_jsonl(..., phase="explore")` |
| semi | jsonl + `.meta.toml` | `save_semi_structured(...)` |
| frozen | parquet + `.meta.json` | `save_parquet(...)` |

Promote to Parquet only after schema review.

## API

```python
from data_io import resolve, load, save_semi_structured, save_parquet

path = resolve("my_dataset")
rows = load("my_dataset")

save_semi_structured(records, logical_name="my_output", script=__file__)
```

## GNB-style example

```toml
[datasets.gnb_passport_sessions]
tier = "scratch"
path = "gnb_passport_sessions.jsonl"
phase = "semi"
parent = "gnb_raw_resolutions"
description = "Sessions with passport agenda items"
```

```python
save_semi_structured(
    sessions,
    logical_name="gnb_passport_sessions",
    parent_sources=["gnb_raw_resolutions"],
    description="Ready for entity extraction.",
    script=__file__,
)
```

## Legacy files — `llm_archivist`

For files **not** created by `data_io` (inbox dumps, old exports):

```bash
# Fast — no Ollama (columns, coverage, row counts)
uv run archive-inventory /path/to/scratch/_inbox
# → INVENTORY.md + inventory_report.toml at scan root

# LLM — rich description (Ollama on localhost:11434)
uv run archive-scan /path/to/scratch/_inbox --model qwen2.5-coder:latest
```

**Do not** run on `data_io` outputs — they already have provenance sidecars.

| Tool | Use case | LLM? |
|------|----------|------|
| `data_io.save_*` | New pipeline writes | No |
| `archive-inventory` | Fast orphan triage | No |
| `archive-scan` | Inferred research context | Yes |

Shortcuts: `./scripts/inventory_inbox.sh` (fast), `./scripts/archive_inbox.sh` (LLM)


# Data layout and manifest

This project decouples code from physical storage using `data_manifest.toml` and the `data_io` package. Scripts request datasets by **logical name**; paths resolve at runtime with tier mount checks.

## Storage tiers (this machine)

| Tier | Location | Role |
|------|----------|------|
| **hot** | `~/develop` | Code repos, small local inputs |
| **warm** | `/Volumes/2tb disk` | Canonical Republic datasets (`datasets/republic/`) |
| **scratch** | `/Volumes/Extreme SSD/scratch` | Ephemeral exports, GNB explore JSONL |
| **collab** | `~/Nextcloud2/Republic` | Shared / synced resources |

`republic_ner_matching/data` symlinks to `/Volumes/2tb disk/datasets/republic`.

Legacy warm archives remain at `/Volumes/2tb disk/data/` (pagexml, sessions_json).

## Day-zero checklist

1. Copy `data_manifest.toml.example` → `data_manifest.toml` (or use the project file as-is).
2. Optional: `data_manifest.local.toml` for SURF/laptop overrides (see `.example`).
3. Run `uv run python -m data_io.check` — tiers mounted, paths resolve.
4. Use `resolve("resolutions_flat")`, `load(...)`, `save_parquet(...)` in scripts — no hardcoded absolute paths.
5. Keep [PLAN.md](../PLAN.md) `## Data paths` in sync with `[datasets.*]` keys.

## Three-phase pipeline

| Phase | Formats | When to use |
|-------|---------|-------------|
| **explore** | `.jsonl`, `.pkl`, `.xlsx` | Pattern discovery, KWIC, ad-hoc |
| **semi** | `.jsonl` + `.meta.toml` | Human-reviewed structures (GNB sessions) |
| **frozen** | `.parquet` + `.meta.json` | Stable schema; DuckDB in-place queries |

**Promotion rule:** call `save_parquet` only after one review cycle with a stable schema. Until then, stay in JSONL.

## `data_io` API

```python
from data_io import resolve, load, save_semi_structured, save_parquet

path = resolve("delegates_reference")
df = load("delegates_reference")

save_parquet(df, logical_name="delegates_reference", script=__file__)
```

### Provenance

Every `save_*` writes a **sidecar**:

- JSONL (explore/semi): `filename.meta.toml`
- Parquet (frozen): `filename.parquet.meta.json`

Parquet files also embed the same fields in the Arrow schema metadata (`dh.*` keys).

## GNB passport sessions example

Manifest entries (see `data_manifest.toml`):

```toml
[datasets.gnb_passport_sessions]
tier = "scratch"
path = "gnb_passport_sessions.jsonl"
phase = "semi"
parent = "gnb_raw_resolutions"
```

Extraction script:

```python
from data_io import save_semi_structured

extracted_sessions = [
    {"date": "1654-03-12", "president": "Fagel", "raw_text": "Resolutien... paspoort voor..."},
    {"date": "1654-03-14", "president": "De Witt", "raw_text": "Aengaende de paspoorten..."},
]

save_semi_structured(
    extracted_sessions,
    logical_name="gnb_passport_sessions",
    parent_sources=["gnb_raw_resolutions"],
    description="Filtered GNB sessions where passports were on the agenda.",
    script=__file__,
)
# → /Volumes/Extreme SSD/scratch/gnb_passport_sessions.jsonl
# → /Volumes/Extreme SSD/scratch/gnb_passport_sessions.meta.toml
```

## CLI

```bash
uv run python -m data_io.check
```

Prints tier mount status and resolved dataset paths. Exit code 1 if any tier is unavailable or dataset file is missing.

## Local overrides

Merge order: `data_manifest.toml` → `data_manifest.local.toml` → `DATA_MANIFEST_OVERRIDE` (path to a TOML file).

Environment variable `DATA_MANIFEST` points to the base manifest file if not in the project root.

## Legacy files — `llm_archivist`

For orphan files without `data_io` sidecars:

```bash
./scripts/inventory_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"   # fast, no Ollama
# → INVENTORY.md + inventory_report.toml at scan root
./scripts/archive_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"     # LLM enrichment
```

| Tool | When | LLM? |
|------|------|------|
| `data_io.save_*` | New writes | No |
| `archive-inventory` | Fast inbox triage | No |
| `archive-scan` | Rich descriptions | Yes (Ollama) |

See [docs/SKELETON.md](SKELETON.md).

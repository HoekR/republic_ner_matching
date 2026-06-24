# DH project (data manifest template)

Bootstrap from the [republic_ner_matching](https://github.com/...) `template/dh_project` skeleton.

## Setup

```bash
uv sync
cp data_manifest.toml.example data_manifest.toml
# edit tier roots and datasets
uv run python -m data_io.check
```

## For LLM / Cursor agents

Read **`AGENTS.md`** first — it defines path rules, provenance writes, and the manifest workflow.

## Layout

```
├── AGENTS.md                 # LLM coding rules (Cursor, Copilot)
├── data_manifest.toml        # logical datasets (create from .example)
├── data_io/                  # manifest + provenance I/O
├── llm_archivist/            # archive-scan: LLM sidecars for legacy files
├── docs/DATA.md              # human-readable tier + phase docs
├── PLAN.md                   # project status + data-path table
└── scripts/                  # pipeline entrypoints + archive_inbox.sh
```

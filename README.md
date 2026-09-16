# Republic NER Matching

Named-entity matching and sequence alignment pipeline for Dutch Republic resolutions (1626–1630 and beyond), aligned with Digital Humanities Project Standards (`dighum_template`).

## Repository Structure

- `data_io/` — Unified storage manifest and data access layer
- `docs/` — Architecture documentation, data tiers, add-ons, and portable wisdom:
  - `docs/DATA.md` — Manifest layout, storage tiers, and dataset life-cycle
  - `docs/wisdom/` — Portable methodology topics (e.g. pre-1678 dates, vectorized pandas, manifest discipline)
  - `docs/addons/` — Applied MCP servers and add-on documentation (`data-io-mcp`, `workflow-mcp`)
- `notebooks/` — Exploratory, analysis, and verification Jupyter notebooks
- `scripts/` — Utility scripts, inbox archival tools, and project automation
- Root scripts (`match.py`, `build_*.py`, `finetune_*.py`) — NER training and alignment pipeline executables

## Setup

```bash
cd /path/to/republic_ner_matching
uv sync
```

Check data manifest tiers and datasets:

```bash
uv run python -m data_io.check
```

Open `republic_automated.code-workspace` in VS Code to use the configured profile.

## Syncing with dighum_template

This repository synchronizes standard editor rules, portable wisdom topics, add-ons, and `data_io` package updates from `dighum_template`:

```bash
cd ~/develop/dighum_template
./scripts/sync_project.sh ~/develop/republic_ner_matching --all
```

## Legacy files — `llm_archivist`

Retroactively document orphan datasets in `scratch/_inbox/`:

```bash
./scripts/archive_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"
```

Requires Ollama (`localhost:11434`). See [docs/SKELETON.md](docs/SKELETON.md).

## Bootstrap a new DH project

Use the dedicated template repo:

```bash
cd ~/develop/dighum_template
./scripts/bootstrap.sh ~/develop/MyNewProject my-new-project
```

Or forward from this repo (deprecated):

```bash
./scripts/bootstrap_dh_project.sh ~/develop/MyNewProject my-new-project
```

See **[dighum_template/docs/NEW_REPO.md](../dighum_template/docs/NEW_REPO.md)** and **`AGENTS.md`** for agent coding rules.

## Project Dashboard
- See the running project dashboard: docs/dashboard.md

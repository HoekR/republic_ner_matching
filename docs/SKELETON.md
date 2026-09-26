# Project skeleton for new DH repos
<!-- doc-status: sidelined -->

Use this repo as the **source of truth** for `data_io`. New projects get `data_io` + `llm_archivist` via the bootstrap script.

**Start here:** [dighum_template/docs/NEW_REPO.md](../../dighum_template/docs/NEW_REPO.md) — step-by-step guide (canonical template repo).

This file describes the skeleton model. Bootstrap commands now live in **dighum_template**.

**Prerequisite:** clone [llm-archivist](../llm-archivist) and [dighum_template](../dighum_template) as sibling repos under `~/develop/`.

## Quick start

```bash
cd dighum_template
./scripts/bootstrap.sh ~/develop/GNBanalysis gnb-analysis
cd ~/develop/GNBanalysis
uv sync
# Edit data_manifest.toml — tier roots + [datasets.*]
uv run python -m data_io.check
git init && git add . && git commit -m "Bootstrap DH data manifest project"
```

Override archivist source if needed:

```bash
LLM_ARCHIVIST_SRC=~/develop/llm-archivist/src/llm_archivist ./scripts/bootstrap_dh_project.sh ...
```

## What gets copied

| Source | Destination in new repo |
|--------|-------------------------|
| `dighum_template/template/*` | AGENTS.md, PLAN.md, docs, pyproject.toml, `.cursorrules`, `.cursor/rules/`, `.vscode/`, `<package>.code-workspace`, scripts |
| `dighum_template/packages/data_io/` | `data_io/` |
| `../llm-archivist/src/llm_archivist/` | `llm_archivist/` |
| `tests/test_data_io.py` | `tests/` |
| `../llm-archivist/tests/test_scanners.py` | `tests/test_llm_archivist.py` |
| `../llm-archivist/tests/test_inventory.py` | `tests/test_inventory.py` |

Both packages are copied at bootstrap time so each project is self-contained (SURF, offline).

## Two-tool provenance model

```mermaid
flowchart LR
    subgraph new [New pipeline outputs]
        save[data_io.save_*]
        sidecar1[sidecar auto]
    end
    subgraph legacy [Legacy / inbox files]
        scan[archive-scan]
        sidecar2[LLM .meta.toml]
    end
    manifest[data_manifest.toml]
    save --> sidecar1 --> manifest
    scan --> sidecar2 --> manifest
```

| Tool | When | LLM? |
|------|------|------|
| **`data_io`** | All new writes | No — deterministic provenance |
| **`llm_archivist`** | Orphan files in `_inbox/`, migrated legacy | Optional — `archive-inventory` (fast) or `archive-scan` (LLM) |

## LLM coding workflow

1. **`AGENTS.md`** — path rules, `data_io` writes, when to `archive-scan`
2. **`.cursor/rules/project-standards.mdc`** — uv, manifest, pandas conventions (always apply)
3. **`.cursorrules`** — short manifest discipline (legacy auto-load)
4. **`docs/DATA.md`** — tiers, phases, both tools
5. **`PLAN.md`** — status + data-path table
6. **`<package>.code-workspace`** — editor profile (interpreter, lint, test, excludes)

### Prompt pattern

```
Read AGENTS.md and PLAN.md.
Add [datasets.my_output] to data_manifest.toml.
Implement scripts/extract.py using save_semi_structured.
Run uv run python -m data_io.check when done.
```

### Document an inbox folder

```
Run archive-inventory on scratch/_inbox (no Ollama).
Read INVENTORY.md at the scan root; register canonical files in data_manifest.toml.
Optional: archive-scan for LLM-rich sidecars.
```

### Validation

```bash
uv run python -m data_io.check
uv run pytest tests/ -q
```

## Syncing updates

```bash
rsync -a data_io/ ~/develop/GNBanalysis/data_io/
rsync -a ../llm-archivist/src/llm_archivist/ ~/develop/GNBanalysis/llm_archivist/
```

## This repo (republic_ner_matching)

Use sibling archivist without vendoring:

```bash
./scripts/archive_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"
```

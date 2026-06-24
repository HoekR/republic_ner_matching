# Republic NER Matching Template

This repository is a starter template for a Python-based named-entity matching project with a VS Code profile.

## Included profile

- `.vscode/settings.json` — workspace Python settings, linting, testing, and useful file excludes
- `.vscode/extensions.json` — recommended extensions for Python, Jupyter, and Copilot
- `republic_automated.code-workspace` — workspace file that opens the repository with the profile
- `requirements-dev.txt` — editable install plus development tools
- `pyproject.toml` — package metadata and dependency declarations
- `.gitignore` — ignores virtual environments, local caches, output artifacts, and large data files

## Setup

```bash
cd /path/to/new/project
uv pip install -e .
uv pip install -r requirements-dev.txt
```

Open `republic_automated.code-workspace` in VS Code to use the included profile.

## Notes

- The workspace is configured to use `${workspaceFolder}/.venv/bin/python`.
- If you create a new project from this template, keep the `.vscode/` folder and `republic_automated.code-workspace` for the profile.
- Remove or replace any sample data files from `data/` if they are not part of your new project.

## Legacy files — `llm_archivist`

Retroactively document orphan datasets in `scratch/_inbox/`:

```bash
./scripts/archive_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"
```

Requires Ollama (`localhost:11434`). See [docs/SKELETON.md](docs/SKELETON.md).

## Bootstrap a new DH project (manifest + data_io + llm_archivist)

This repo contains a copyable skeleton for LLM-friendly historical-data projects:

```bash
./scripts/bootstrap_dh_project.sh ~/develop/MyNewProject my-new-project
```

See **[docs/SKELETON.md](docs/SKELETON.md)** and **`AGENTS.md`** for agent coding rules.

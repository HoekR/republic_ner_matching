<!-- Same body as .cursor/rules/project-standards.mdc.
     Source: dighum_template/template/shared/agent-standards.md -->

# Agent standards (Cursor + VS Code Copilot)

Read `AGENTS.md`, `docs/DATA.md`, and `PLAN.md` before pipeline work.

- Never hardcode absolute data paths; use `data_manifest.toml` + `data_io.resolve` / `load` / `save_*`
- Register datasets in the manifest before referencing them in code or notebooks
- After manifest edits: `uv run python -m data_io.check`
- Pipeline writes: `save_semi_structured` / `save_parquet` (automatic provenance, including `*.provenance.json`)
- Use `uv add`, `uv sync`, `uv run` — no bare `pip install`
- Prefer vectorized pandas; avoid row loops and `inplace=True`
- Never use `pd.to_datetime` / `Timestamp` for calendar dates before 1678 — use `pd.Period` with `freq="D"`
- Never discard archival metadata fields during transforms
- `archive-inventory` / `archive-scan` only for legacy orphan files (requires `--with-archivist`), never on `data_io` outputs

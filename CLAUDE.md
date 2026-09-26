<!-- Same body as .cursor/rules/project-standards.mdc / .github/copilot-instructions.md.
     Source: dighum_template/template/shared/agent-standards.md
     Canonical brief: AGENTS.md (read that file for full project context). -->

# Agent standards (Cursor + VS Code Copilot + Claude Code)

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

## Workflow

- One active step per session — never implement the whole `PLAN.md` at once
- Read `PLAN.md` first; if a guide exists under `plans/steps/STEP*.md`, follow it before editing files
- Prefer advising commands; do not run heavy compute (sampling, long builds) by default — user runs the terminal
- Do not scan or dump large parts of the repo unless asked
- Targeted edits only — no whole-file rewrites of unchanged content
- When a step is done: mark it in `PLAN.md`, give a short 3-bullet handoff, name the next step, and remind the user to clear the chat before the next step

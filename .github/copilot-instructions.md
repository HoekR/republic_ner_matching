<!-- Same body as .cursor/rules/project-standards.mdc.
     Source: dighum_template/template/shared/agent-standards.md -->

# Agent standards (Cursor + VS Code Copilot + Claude Code)

Read `AGENTS.md`, `docs/DATA.md`, and `PLAN.md` before pipeline work.

## Scope bar — the corpus ends 1630-05-14. FULL STOP

**The enriched XML edition ends `1630-05-14`** (user, 2026-09-25; restated as FULL STOP
2026-10-08 after it was broken anyway). Past that date:

- **Do not reconsider dates.** Do not take scans or HTR text into account. Not as a population,
  not as a denominator, not as a diagnostic, not as a side finding, not "kept visible" for
  completeness.
- The HTR axis runs to **1630-12-31**, so post-bar material *is present on disk* (2,284 axis
  paragraphs, 184 sessions) and must be dropped **explicitly, at the point data enters a script** —
  never filtered downstream, never left to fall out of some geometry.
- Use `scripts/corpus_scope.py`: `in_scope(date)`, `drop_out_of_scope(items, key)`,
  `split_by_scope(frame, col)`, `scope_meta()` for a dataset's `meta`. The bar is derived from the
  baseline, never hardcoded. Tests: `tests/test_corpus_scope.py`.
- A missing or unparseable date is **out** of scope, not in — fail closed.
- This has already caused two retracted findings (an "unaccounted room" class that was wholly
  post-bar pages, and a contaminated 80.9% disagreement rate). If a result involves dated HTR
  material, state that the bar was applied.
- Never hardcode absolute data paths; use `data_manifest.toml` + `data_io.resolve` / `load` / `save_*`
- Register datasets in the manifest before referencing them in code or notebooks
- After manifest edits: `uv run python -m data_io.check`
- Pipeline writes: `save_semi_structured` / `save_parquet` (automatic provenance, including `*.provenance.json`)
- Use `uv add`, `uv sync`, `uv run` — no bare `pip install`
- Prefer vectorized pandas; avoid row loops and `inplace=True`
- Never use `pd.to_datetime` / `Timestamp` for calendar dates before 1678 — use `pd.Period` with `freq="D"`
- Never discard archival metadata fields during transforms
- `archive-inventory` / `archive-scan` only for legacy orphan files (requires `--with-archivist`), never on `data_io` outputs

## The spine: three sequences, four edges

The project models three sequences (physical scans, HTR sessions, editorial dates) that must not be conflated. Four cross-sequence edges hold the evidence: **OBSERVED_ON** (archival), **DATED_AS** (heading), **PINNED_TO** (inferred session→date link), and **ALIGNED_TO** (derivable). Before reporting a new measurement, state which edge the question is about. If a result crosses PINNED_TO, it is inferred and must say so. This applies to the agent's own claims, not only to pipeline code: before asserting a conclusion, name which edge it rests on — if you cannot, the claim is not yet well-posed, no matter how confident it reads. See `docs/SEQUENCE_MODEL.md` and `plans/SEQUENCE_GRAPH_SPINE.md`; the graph package `sequence_graph/` is built through Stage 4 (the solver, unfitted/ungated) -- `sequence_graph.query` answers session/date/scan questions directly.

## Workflow

- One active step per session — never implement the whole `PLAN.md` at once
- Read `PLAN.md` first; if a guide exists under `plans/steps/STEP*.md`, follow it before editing files
- Prefer advising commands; do not run heavy compute (sampling, long builds) by default — user runs the terminal
- Do not scan or dump large parts of the repo unless asked
- Targeted edits only — no whole-file rewrites of unchanged content
- When a step is done: mark it in `PLAN.md`, give a short 3-bullet handoff, name the next step, and remind the user to clear the chat before the next step

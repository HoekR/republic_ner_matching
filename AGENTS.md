# Agent instructions — republic_ner_matching

Read **`docs/DATA.md`** and **`data_manifest.toml`** before pipeline work.

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

## The spine: three sequences, four edges

The project models three sequences (physical scans, HTR sessions, editorial dates) that must not be conflated. Four cross-sequence edges hold the evidence: **OBSERVED_ON** (archival), **DATED_AS** (heading), **PINNED_TO** (inferred session→date link), and **ALIGNED_TO** (derivable). Before reporting a new measurement, state which edge the question is about. If a result crosses PINNED_TO, it is inferred and must say so. This applies to the agent's own claims, not only to pipeline code: before asserting a conclusion, name which edge it rests on — if you cannot, the claim is not yet well-posed, no matter how confident it reads. See `docs/SEQUENCE_MODEL.md` and `plans/the-two-deep-hits-melodic-avalanche.md`; the graph package `sequence_graph/` is not yet built.

## Which track to work on

Several research tracks (S4 segmentation transfer, Track B/C name matching, HOE classifier, ...)
compete for the same session budget. Before starting work, run
`uv run python scripts/svz.py review` (or read `docs/STATE.md`) to see which track is improving,
stagnant, or blocked, and follow `docs/ITERATION_POLICY.md` to decide what to pick up. Record any
stop/continue/switch call via `svz.py decision ...` into `docs/DECISIONS.md`.

## Data paths

- Use `from data_io import resolve, load, save_parquet, save_semi_structured` — no absolute paths in scripts.
- Register new datasets in `data_manifest.toml` before referencing them in code.
- After manifest edits: `uv run python -m data_io.check`
- Keep `PLAN.md` `## Data paths` in sync with `[datasets.*]` keys.

## Outputs

- Semi-structured: `save_semi_structured(..., logical_name=..., script=__file__)`
- Frozen: `save_parquet(df, logical_name=..., script=__file__)`

## Archival integrity

See root `.cursorrules` — never drop provenance fields; version reference data instead of in-place mutation.

## Pandas and calendar dates (early modern corpus)

- Prefer **vectorized** pandas operations (`merge`, `groupby`, `explode`, `str` accessors, boolean masks) over `for row in df.itertuples()` / `iterrows()` when building or transforming DataFrames.
- JSON ingestion may require a single list pass to build a frame; all subsequent column work should be vectorized.
- **Never use `datetime` / `Timestamp` / `to_datetime()` for calendar dates before 1678**, this is a hard limitation of the pandas datatime epoch.
- Use **`pd.Period` / `pd.PeriodIndex` with `freq="D"`** for resolution dating, window checks, and joins on calendar day.
- Compare periods via ordinal arithmetic: `(period_index - anchor_period).astype(int).abs()`, not `datetime` subtraction.
- Filter malformed ISO strings with vectorized month/day checks before constructing `PeriodIndex` (invalid dates such as `1582-11-40` must not reach `to_datetime` fallbacks).

## Bootstrap a sibling project

```bash
./scripts/bootstrap_dh_project.sh ~/develop/NewProject new-project
```

Requires `~/develop/llm-archivist` (copied into new project). See [docs/SKELETON.md](docs/SKELETON.md).

## Legacy file documentation (`llm_archivist`)

```bash
# Fast inventory (no Ollama) — start here
./scripts/inventory_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"

# LLM enrichment (Ollama required)
./scripts/archive_inbox.sh "/Volumes/Extreme SSD/scratch/_inbox"
```

Do **not** run on files written by `save_semi_structured` / `save_parquet`.

## Add-ons

### data-io-mcp

Optional Cursor MCP server for manifest registry access. Prefer MCP tools over raw filesystem reads:

- `check_manifest()` — tier mounts + dataset availability
- `list_datasets(prefix?)` — filter logical names
- `resolve_dataset(name)` — path + exists
- `preview_dataset(name, limit=10)` — schema/sample only (never full wide tables)
- `get_provenance(name)` — sidecar + parent chain
- `suggest_manifest_entry(...)` — draft `[datasets.*]` TOML for human commit

Setup: see `docs/addons/data-io-mcp/README.md`. Requires an optional sibling clone of [dighum_template](https://github.com/HoekR/dighum_template) for the server package (not vendored — no code replication). Still run `uv run python -m data_io.check` in CI and before sessions.

### workflow-mcp

Optional Cursor MCP server for cost-sensitive step workflow. Prefer MCP over reading whole `PLAN.md` / all step files:

- `get_plan_status()` — parsed checklist from `PLAN.md`
- `get_current_step()` — first incomplete step
- `list_steps()` — `docs/steps/STEP*.md` index
- `get_step_guide(step_id)` — one step guide only (e.g. `3a`)
- `get_workflow_rules()` — `docs/wisdom/cost-sensitive-agent-workflow.md` if present

Setup: see `docs/addons/workflow-mcp/README.md`. Requires an optional sibling clone of [dighum_template](https://github.com/HoekR/dighum_template) for the server package (not vendored — no code replication). Still follow **one step per chat**; MCP does not replace human progress ticks in `PLAN.md`.
- minimal_agent: Minimal, human-in-the-loop assistant. See docs/agent-plan.md

## Repo inventory

See [docs/REPUBLIC_REPO_INVENTORY.md](docs/REPUBLIC_REPO_INVENTORY.md) for sibling Republic clones on `~/develop`.

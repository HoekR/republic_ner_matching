# Agent instructions — republic_ner_matching

Read **`docs/DATA.md`** and **`data_manifest.toml`** before pipeline work.

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

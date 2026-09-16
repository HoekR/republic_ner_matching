# workflow MCP server

Cursor MCP tools for **cost-sensitive step-by-step** projects (`PLAN.md` + `docs/steps/`).

## Optional dependency: dighum_template

MCP server code is **not** copied into derivative projects — intentionally, to avoid replicating identical tooling.

| Layer | Location |
|-------|----------|
| MCP server | Sibling clone of [dighum_template](https://github.com/HoekR/dighum_template) → `packages/workflow_mcp/` |
| Your project | Overlay only: `.cursor/mcp.json`, this README, `AGENTS.md` snippet; `PLAN.md` and `docs/steps/` stay here |

Clone dighum_template once (any path), run `uv sync` in the package directory, and point `.cursor/mcp.json` at it. Pipeline/runtime code (`data_io/`, etc.) is still vendored in the derivative at bootstrap — only Cursor MCP servers stay upstream.

**Optional:** skip this add-on if you do not use Cursor MCP; read step guides from files instead.

## Setup

1. Ensure this project has `PLAN.md`, `AGENTS.md`, and step guides under `docs/steps/`.
2. Install the MCP package once:

   ```bash
   cd ~/develop/dighum_template/packages/workflow_mcp && uv sync
   ```

3. Copy or merge MCP config:

   ```bash
   mkdir -p .cursor
   cp .cursor/mcp.json.example .cursor/mcp.json   # after applying add-on
   ```

   If you also use **data-io-mcp**, merge both entries under `"mcpServers"` in one file.

4. Edit `.cursor/mcp.json` if your dighum_template path differs from `/Users/rikhoekstra/develop/dighum_template`.

5. Reload Cursor MCP servers (Settings → MCP, or restart Cursor).

`${workspaceFolder}` resolves to this project root.

## Tools

| Tool | Use when |
|------|----------|
| `get_plan_status()` | Session start; see checklist without opening `PLAN.md` |
| `get_current_step()` | Find the next incomplete step |
| `list_steps()` | Discover available `STEP*.md` files |
| `get_step_guide(step_id)` | Read one step only (`0`, `2`, `3a`, …) |
| `get_workflow_rules()` | Portable rules from `docs/wisdom/` (bootstrap with `--with-wisdom`) |

## Rules

- MCP mirrors `AGENTS.md` — **one step per chat**; never "execute the whole plan".
- Agents advise and edit; **user runs terminal** by default.
- Tick `PLAN.md` yourself when **Done when** passes; MCP reads status but does not write.

## Prompt patterns

| You say | Agent does |
|---------|------------|
| **start step N** | `get_step_guide(N)` + that step only |
| **guide step N** | Spec/checklist; no later steps |
| **review my step N** | Read your diff against step N guide |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `PLAN.md not found` | Check `--project-root` / `${workspaceFolder}` |
| Empty checklist | Ensure `PLAN.md` has a markdown table with `\| **N** \| [STEP…](docs/steps/…)` rows |
| Step not found | Use `list_steps()`; step id is the number/letter after `STEP` (e.g. `3a`) |

## Related

- Wisdom: [cost-sensitive-agent-workflow](../../wisdom/cost-sensitive-agent-workflow.md)
- Package: `dighum_template/packages/workflow_mcp/README.md`
- Sync from dighum: `~/develop/dighum_template/scripts/sync_project.sh <project> --addon workflow-mcp --mcp` — [SYNC-PROJECT.md](https://github.com/HoekR/dighum_template/blob/main/docs/SYNC-PROJECT.md)

# workflow MCP server

**Status:** stable (v1)  
**Applies to:** multi-step DH projects with `PLAN.md` + `docs/steps/`  
**Portable:** yes (server in `dighum_template/packages/workflow_mcp`)

## Rule

Use the **workflow MCP** at session start and when the user says **start/guide step N** — read one step guide via MCP, not the whole repo plan.

## Tools

| Tool | Purpose |
|------|---------|
| `get_plan_status()` | Parsed `PLAN.md` checklist |
| `get_current_step()` | First incomplete step |
| `list_steps()` | Index of `docs/steps/STEP*.md` |
| `get_step_guide(step_id)` | Single step markdown |
| `get_workflow_rules()` | `docs/wisdom/cost-sensitive-agent-workflow.md` if present |

## Optional dependency: dighum_template

Derivatives reference — not vendor — the server in [dighum_template](https://github.com/HoekR/dighum_template) `packages/workflow_mcp/`. Clone once as a sibling; add-on overlay copies only `.cursor/mcp.json` stub and docs. Optional: skip if you do not use Cursor MCP.

## Setup

1. `cd ~/develop/dighum_template/packages/workflow_mcp && uv sync`
2. Apply add-on: `apply_addon.sh <project> workflow-mcp`
3. Merge `.cursor/mcp.json.example` → `.cursor/mcp.json` (combine with `data-io` if needed)
4. `${workspaceFolder}` must point at the DH project root

## Why

Agents load entire plans, skip step boundaries, and run multi-step shell loops. MCP exposes the same **one-step-at-a-time** contract as `AGENTS.md` at tool-call time.

## Not in v1

- Writing/ticking `PLAN.md` via MCP
- Running terminal commands
- Cross-project step templates (steps stay in each repo's `docs/steps/`)

## Related

- [cost-sensitive-agent-workflow](cost-sensitive-agent-workflow.md)
- [data-io-mcp](data-io-mcp.md)
- Package: `packages/workflow_mcp/README.md`

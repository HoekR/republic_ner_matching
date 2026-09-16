# data_io MCP server

**Status:** stable (v1)  
**Applies to:** DH projects with vendored `data_io` + `data_manifest.toml`  
**Portable:** yes (server in `dighum_template/packages/data_io_mcp`)

## Rule

Use the **data_io MCP** in Cursor for manifest discovery and capped previews — not raw filesystem reads or full parquet dumps.

## Tools

| Tool | CLI equivalent |
|------|----------------|
| `check_manifest()` | `uv run python -m data_io.check` (structured JSON) |
| `list_datasets(prefix?)` | Registry filter |
| `resolve_dataset(name)` | `resolve(name)` |
| `preview_dataset(name, limit=10)` | Partial inspect only |
| `get_provenance(name)` | Sidecar + parent chain |
| `suggest_manifest_entry(...)` | Draft TOML for human commit |

## Optional dependency: dighum_template

Derivatives reference — not vendor — the server in [dighum_template](https://github.com/HoekR/dighum_template) `packages/data_io_mcp/`. Clone once as a sibling; add-on overlay copies only `.cursor/mcp.json` stub and docs. Vendored `data_io/` in the project is runtime code (separate concern). Optional: skip if you do not use Cursor MCP.

## Setup

1. `cd ~/develop/dighum_template/packages/data_io_mcp && uv sync`
2. Apply add-on: `apply_addon.sh <project> data-io-mcp`
3. Copy `.cursor/mcp.json.example` → `.cursor/mcp.json`
4. `${workspaceFolder}` must point at the DH project root

## Why

Agents skip `data_io.check` and guess paths. MCP exposes the same governed API as `AGENTS.md` at tool-call time.

## Not in v1

- `save_*` writes via MCP
- Arbitrary path read/write
- Full wide-table loads (`rpp_18c` → use `rpp_summary` or pipelines)

## Related

- [manifest-discipline](manifest-discipline.md)
- [archivist-vs-data-io](archivist-vs-data-io.md)
- Package: `packages/data_io_mcp/README.md`

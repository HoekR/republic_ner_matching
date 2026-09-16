# data_io MCP server

Cursor MCP tools wrapping `data_io` — manifest registry, capped previews, provenance chains.

## Optional dependency: dighum_template

MCP server code is **not** copied into derivative projects — intentionally, to avoid replicating identical tooling.

| Layer | Location |
|-------|----------|
| MCP server | Sibling clone of [dighum_template](https://github.com/HoekR/dighum_template) → `packages/data_io_mcp/` |
| Your project | Vendored `data_io/` + manifest at bootstrap; add-on adds `.cursor/mcp.json`, docs, `AGENTS.md` snippet |

Clone dighum_template once (any path), run `uv sync` in the package directory, and point `.cursor/mcp.json` at it.

**Optional:** skip this add-on if you do not use Cursor MCP; use `uv run python -m data_io.check` and file reads instead.

## Setup

1. Ensure this project has `data_io/` and `data_manifest.toml` (from dighum_template bootstrap).
2. Install the MCP package once:

   ```bash
   cd ~/develop/dighum_template/packages/data_io_mcp && uv sync
   ```

3. Copy the MCP config:

   ```bash
   mkdir -p .cursor
   cp .cursor/mcp.json.example .cursor/mcp.json   # after applying add-on
   ```

4. Edit `.cursor/mcp.json` if your dighum_template path differs from `/Users/rikhoekstra/develop/dighum_template`.

5. Reload Cursor MCP servers (Settings → MCP, or restart Cursor).

`${workspaceFolder}` resolves to this project root — the server reads **this** project's manifest.

## Tools

| Tool | Use when |
|------|----------|
| `check_manifest()` | Session start; verify scratch/warm tiers mounted |
| `list_datasets(prefix?)` | Discover logical names (`president_`, `rpp_`, …) |
| `resolve_dataset(name)` | Path + exists without hardcoding |
| `preview_dataset(name, limit=10)` | Schema and sample rows (max 20 rows, 48KB) |
| `get_provenance(name)` | Sidecar metadata and parent chain |
| `suggest_manifest_entry(...)` | Draft manifest block before editing `data_manifest.toml` |

## Rules

- MCP mirrors `AGENTS.md` — use logical names, not `/Volumes/...` paths.
- `preview_dataset` never returns full wide parquets (e.g. `rpp_18c`); use `rpp_summary` or run pipelines.
- Writes (`save_*`) are **not** exposed via MCP in v1.

## Manual CLI equivalent

```bash
uv run python -m data_io.check
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `data_manifest.toml not found` | Check `--project-root` / `${workspaceFolder}` |
| Tier unavailable | Mount scratch drive or set `data_manifest.local.toml` |
| `No module named data_io` | Project must contain vendored `data_io/` at root |

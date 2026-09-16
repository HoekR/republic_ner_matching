# Local config files, not environment variables

**Status:** stable  
**Applies to:** all DH projects  
**Portable:** yes

## Rule

Put **machine-local configuration** (credentials, tier roots, connection strings, API keys) in **gitignored `*.local.toml` files** at the repo root — not in shell environment variables.

Typical pattern:

```bash
cp data_manifest.local.toml.example data_manifest.local.toml   # edit; never commit
```

Resolve config in code: **local file first**, then raise a clear error pointing at the example file.

## Why

| Problem with env vars | Local TOML |
|----------------------|------------|
| Invisible — not listed in repo layout | Documented via `.example` + README |
| Leak to shell history, `ps`, child processes | Stays in one ignored file |
| Every new terminal/session needs re-export | Persistent across sessions |
| Hard for agents to discover | `AGENTS.md` / manifest docs name the file |
| Duplicate config across projects | Each repo has one obvious place |

Environment variables are fine for **ephemeral runtime flags** (debug mode, log level) and for **CI secret injection** where no persistent local file exists — not for day-to-day laptop credentials.

## Example

**Wrong**

```bash
export VK_MYSQL_URL='mysql+pymysql://user:secret@127.0.0.1:3306/vk'
uv run python scripts/export_mysql.py
```

**Right**

```toml
# data_manifest.local.toml (gitignored)
[vk_mysql]
url = "mysql+pymysql://user:secret@127.0.0.1:3306/vk"
```

```bash
uv run python scripts/export_mysql.py
```

## Anti-patterns

| Wrong | Right |
|-------|-------|
| Document `export FOO=...` in README as primary setup | `cp foo.local.toml.example foo.local.toml` |
| Env var overrides local file (hides misconfiguration) | Local file is canonical; env only for CI if needed |
| Secrets in committed `.env` | Gitignored `*.local.toml` + committed `.example` |

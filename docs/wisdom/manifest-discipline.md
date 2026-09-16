# Manifest discipline

**Status:** stable  
**Applies to:** all DH projects  
**Portable:** yes

## Rule

1. Register every dataset in `data_manifest.toml` **before** referencing it in code.
2. Resolve paths only via `data_io.resolve()` / `load()` / `save_*()` — no `/Users/...` or `/Volumes/...` in scripts.
3. Run `uv run python -m data_io.check` after every manifest edit.
4. Keep `PLAN.md` dataset table in sync with `[datasets.*]` keys.

## Why

Hardcoded paths break across machines (laptop, SURF, external disks). The manifest is the contract between code, agents, and humans.

## Anti-patterns

| Wrong | Right |
|-------|-------|
| `pd.read_parquet("/Volumes/...")` | `load_parquet("my_dataset")` |
| New path in code only | New `[datasets.*]` + `data_io.check` |
| `open("output.jsonl", "w")` | `save_semi_structured(..., logical_name="...")` |

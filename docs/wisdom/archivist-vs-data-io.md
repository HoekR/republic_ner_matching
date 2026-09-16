# data_io vs llm_archivist

**Status:** stable  
**Applies to:** all DH projects  
**Portable:** yes

## Rule

| Tool | When | LLM? |
|------|------|------|
| **`data_io.save_*`** | All **new** pipeline outputs | No — deterministic sidecars |
| **`archive-inventory`** | Fast triage of orphan / legacy folders | No |
| **`archive-scan`** | Rich `.meta.toml` for unmigrated legacy files | Yes (Ollama) |
| **`archive-dedup`** | Reclaim space on archive snapshots vs live Nextcloud tree | No (rdfind) |

**Never** run archivist tools on files already written by `data_io` (sidecars already exist).

## Archive snapshot dedup

When a **live sync folder** (e.g. Nextcloud) and an older **backup snapshot** overlap, use `archive-dedup` in the [llm-archivist](https://github.com/HoekR/llm-archivist) repo — not `data_io`.

```bash
cd ~/develop/llm-archivist
uv run archive-dedup analyze --canonical ~/Nextcloud2 --archive "/Volumes/.../backup" -o ~/dupes.txt
uv run archive-dedup summary ~/dupes.txt --canonical ~/Nextcloud2 --archive "/Volumes/.../backup"
```

List `--canonical` first so the live tree is kept. Quarantine or delete only on the archive volume. When done, run `archive-dedup clean` to remove `~/dupes_*.txt` reports and quarantine folders (see llm-archivist README).

## Workflow for inbox dumps

1. `archive-inventory /path/to/_inbox` — columns, row counts, coverage
2. Read `INVENTORY.md` at scan root
3. Register canonical files in `data_manifest.toml`
4. Optional: `archive-scan` for LLM-rich descriptions

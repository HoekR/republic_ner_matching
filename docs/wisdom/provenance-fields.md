# Provenance and metadata fields

**Status:** stable  
**Applies to:** all DH projects  
**Portable:** yes

## Rule

- Do **not** drop metadata fields from domain records when transforming (IDs, offsets, corpus, source paths, correction flags).
- Do **not** mutate canonical reference files in place — write versioned outputs with sidecars.
- Promote JSONL → Parquet only when schema is stable for one review cycle.

## Why

DH pipelines are re-run, audited, and merged across years. Lost provenance makes corrections impossible to trace.

## Outputs

All new writes go through `save_semi_structured` or `save_parquet` so `.meta.toml` / sidecars are automatic.

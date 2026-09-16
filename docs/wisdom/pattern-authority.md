# Pattern authority (delegate / NER pipelines)

**Status:** stable  
**Applies to:** Republic attendance, NER matching, RPP  
**Portable:** yes

## Rule

Designate **one canonical pattern source** per era/pipeline. Never substitute convenience copies (baked exports, intermediate parquets, QA tool outputs).

When corrected identity has rows the pattern source lacks:

- **Flag** in validation output (e.g. `pattern_validation_*.jsonl`)
- **Do not invent** patterns or backfill from secondary sources

## Why

Multiple gedelegeerden / streamlit / rc7 exports diverge in row count and spelling. Mixing sources produces silent join errors (~130k unmatched rows in 18th-c. work).

## Example policy (18th c.)

| Role | Authority |
|------|-----------|
| Occurrence `lowerpattern` | `delegates_18thc_raw.xlsx` (warm tier) |
| Corrected identity | `final_release` attendance |
| QA / corrections | `streamlit_worksheet` — review only, not pattern authority |

See addon **`rpp`** for project scaffolding.

# republic_ner_matching — implementation plan

Match NER PER-layer spans from Dutch Republic resolution annotations to known
delegates in the 1705–1795 corpus.

---

## Overview

**Input** `annotations-layer_PER.tsv.gz` — 3.28 M rows, columns:
`layer, inv, resolution_id, paragraph_id, tag_text, offset, end, tag_length`

**Reference** two parquet exports from `streamlit_worksheet`:
- `data/delegates_reference.parquet` — one row per delegate (cons_id_str, fullname, …)
- `data/patterns_reference.parquet` — one row per (cons_id_str, pattern) pair

**Year lookup** `data/inventory_metadata.json` — from republic-project GitHub;
maps `inventory_num` → `year`, `period_start`, `period_end`

**Output** `data/results.parquet` — top-k candidates per span with scores

---

## Phases

### Phase 1 — Scaffold ✅
- `uv init`, dependencies: pandas, scikit-learn, pyarrow, rapidfuzz, requests
- `data/` dir gitignored except `inventory_metadata.json`

### Phase 2 — Reference data

**Step 1** Run `export_reference.py` in `streamlit_worksheet`:

```bash
cd ~/develop/streamlit_worksheet
uv run python export_reference.py ../republic_ner_matching/data/
```

Expected output:
```
data/delegates_reference.parquet   ~1 020 rows
data/patterns_reference.parquet    ~4 000 rows
```

Verification:
- `delegates_reference` must have column `cons_id_str` as unique key
- `patterns_reference` must have (`cons_id_str`, `pattern`, `year_min`, `year_max`)
- No null `cons_id_str`

**Step 2** Download `inventory_metadata.json`:

```bash
cd ~/develop/republic_ner_matching
uv run python -c "
import requests, json, pathlib
url = 'https://raw.githubusercontent.com/HuygensING/republic-project/main/data/inventories/inventory_metadata.json'
data = requests.get(url).json()
pathlib.Path('data/inventory_metadata.json').write_text(json.dumps(data, indent=2))
print(f'Downloaded {len(data)} inventory records')
"
```

Verification:
- Record count > 200
- Entry for inv 3782 present with year 1727
- Entry for inv 3763 present with year 1708

### Phase 3 — Preprocessing (`preprocess.py`)

Functions:
- `load_inventory_metadata(path) -> dict[int, dict]`
  - Returns `{inventory_num: {year, period_start, period_end}}`
  - Filters out entries where `inventory_num` is not int or `year` is a list
    (multi-year inventories get `year = year_start`)
- `load_ner(path, inv_lookup, year_min=None, year_max=None) -> DataFrame`
  - Reads tsv.gz in chunks (default 100 000 rows)
  - Joins `period_start`, `period_end` from `inv_lookup`
  - Filters to `year_min <= year <= year_max` if provided
  - Returns columns: `inv, resolution_id, paragraph_id, tag_text, year, period_start, period_end`
- `clean_span(text: str) -> str`
  - Strips Dutch titles: `mr.`, `meester`, `heere`, `hertog`, `grave`, `marquis`, `monsr.`, `vrouwe`, `de heer`, `jonkheer`, `de jonge`
  - Lowercases, strips leading/trailing whitespace
- `split_multi_person(text: str) -> list[str]`
  - Split on `\s+ende\s+`, `,\s*`, `;\s*`
  - Return list of non-empty cleaned tokens

Verification:
```python
from preprocess import load_inventory_metadata, clean_span, split_multi_person
meta = load_inventory_metadata('data/inventory_metadata.json')
assert 3782 in meta and meta[3782]['year'] == 1727
assert clean_span('mr. Heinsius') == 'heinsius'
assert split_multi_person('Slicher ende Hop') == ['slicher', 'hop']
```

### Phase 4 — Matching engine (`match.py`)

Adapted from `streamlit_worksheet/utils.py` `build_suggestion_store` /
`query_suggestions` — no Streamlit dependency.

```
build_store(delegates_df, patterns_df) -> dict
  - One TF-IDF document per delegate = all pattern strings joined
  - Dual vectorizer: char_wb ngram(2,4) + word ngram(1,2)
  - Returns {vec_char, vec_word, key_char, key_word, id_index, meta}

match_ner(store, ner_df, top_k=5, year_tolerance=15, min_score=0.1) -> DataFrame
  - Input: ner_df with columns [tag_text, year] (clean_span already applied)
  - Combined score: 0.6 × sim_char + 0.4 × sim_word
  - Temporal gate: zero delegates whose [minjaar-year_tolerance, maxjaar+year_tolerance]
    does not overlap span year
  - Returns: [span_idx, tag_text, year, cand_1…cand_k, score_1…score_k]
```

Key differences from streamlit_worksheet:
- No province constraint (NER has no province context)
- Uses `minjaar`/`maxjaar` from delegates_reference (not `j` column)
- `year_tolerance=15` (wider than QA tool's 10)

Verification:
```python
from match import build_store, match_ner
import pandas as pd
delegates = pd.read_parquet('data/delegates_reference.parquet')
patterns  = pd.read_parquet('data/patterns_reference.parquet')
store = build_store(delegates, patterns)
test = pd.DataFrame({'tag_text': ['heinsius'], 'year': [1710]})
res = match_ner(store, test, top_k=3)
assert res.iloc[0]['cand_1'].startswith('hein')   # Heinsius top-1
```

### Phase 5 — CLI (`run_match.py`)

```
python run_match.py \
  --ner     /path/to/annotations-layer_PER.tsv.gz \
  --out     data/results.parquet \
  --year-min 1705 \
  --year-max 1795 \
  --top-k   5 \
  --chunk-size 50000
```

Pipeline per chunk:
1. `load_ner(path, inv_lookup, year_min, year_max)` — filtered chunk
2. For each row: `split_multi_person(clean_span(tag_text))` → sub-spans
3. `match_ner(store, sub_span_df)`
4. Append to output parquet (via `pyarrow.parquet.ParquetWriter`)

Progress printed every chunk.

Smoke test:
```bash
uv run python run_match.py \
  --ner ~/Downloads/annotations-unaggregated/annotations-layer_PER.tsv.gz \
  --out data/test_results.parquet \
  --year-min 1708 --year-max 1712 \
  --top-k 5
# Expected: ~20 000 spans, runtime < 30 s
```

Final checks:
1. `results.parquet` has column `cand_1` with no 100 % null column
2. Match rate (score_1 > 0.2) ≥ 30 % of spans within year range
3. Temporal gate works: no span with year 1780 matched to delegate active only 1620–1650
4. Multi-person: "Slicher ende Hop" → two rows in output

### Phase 6 — Notebook (`explore.ipynb`)

- Load results, show score distribution histogram
- Match rate by year (line chart)
- Top unmatched spans (score_1 < 0.1) — candidates for new delegates
- Sample table: span + top-3 candidates with scores

---

## Data paths (defaults)

| File | Path |
|---|---|
| NER annotations | `~/Downloads/annotations-unaggregated/annotations-layer_PER.tsv.gz` |
| delegates_reference | `data/delegates_reference.parquet` |
| patterns_reference | `data/patterns_reference.parquet` |
| inventory_metadata | `data/inventory_metadata.json` |
| results | `data/results.parquet` |

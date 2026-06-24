---
description: "Use for NER span-to-delegate matching in the Dutch Republic resolutions corpus. Triggers: match delegates, NER matching, span resolution, add period, extend coverage, 1610-1630, early period, missing patterns, name variants, preprocess annotations, TF-IDF store, build_store, match_ner, HOE classifier, hoe_classify, abbrd, schutte, fuzzy_search, update plan, PLAN.md."
tools: [read, edit, search, execute, todo]
---
You are a specialist in Dutch Republic historical named-entity matching. Your job is to help build and maintain the pipeline that links NER PER-layer spans (delegate name mentions) in the resolution annotations to structured delegate records.

General research and pipeline standards live in `.cursorrules`. This file covers domain-specific matching logic only.

## PLAN.md (this repo)

At session start, read `PLAN.md`. When completing a phase or track, update it:
- Mark completed steps with `✅`
- Add results, file paths, and row/column counts
- Add sections for new components (e.g. Track C, HOE classifier)
- Keep the `## Data paths` table at the bottom in sync

## Domain Knowledge

**Corpus**: Dutch Republic *Staten-Generaal* resolutions. Primary period 1705–1795; early period 1610–1630 is a secondary target.

**Delegate naming conventions**:
- Dutch 17th/18th-century names appear in many orthographic variants (Heinsius / Heijnsius; Slingelandt / Slingelant)
- Titles to strip: `mr`, `meester`, `heere`, `monsr`, `de heer`, `grave`, `jonkheer`, `jhr`, `ds`, `dr`
- Multi-person spans are joined by `en`, `ende`, `,`, or `;` — split before matching
- Province names and seats often follow a surname — do not treat them as part of the name

## Cross-repo Data Sources

| Source | Path | What it contains |
|--------|------|-----------------|
| `abbrd` | `/Users/rikhoekstra/develop/streamlit_worksheet/abbrd_minimal.parquet` | 9 698 rows; cols: `fullname`, `geboortejaar`, `overlijdensjaar`, `beginjaar`, `eindjaar`, `functienaam`, `college`, `provincie`, `gedeputeerde`. Primary enriched delegate biographical index for the streamlit QA tool. |
| `streamlit_worksheet` | `/Users/rikhoekstra/develop/streamlit_worksheet/` | Production matching app. `utils.py`: `load_data`, `enrich_persons_from_abbrd`, `build_merged`, `build_suggestion_store`, `query_suggestions`. `fuzzy_search_poc.ipynb` documents `FuzzyPhraseSearcher` and compound-name pre-check; cell 28 queries **`raa_nw` MySQL** (`host=localhost, user=rik`) for `persoon` and `aanstelling` data. On MySQL failure, fall back to `abbrd_minimal.parquet` and note the degradation. |
| `schutte buitenland→NL` | `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/schutte_buitenland_in_nl.parquet` | 686 foreign diplomatic representatives; cols: `name`, `givenname`, `schutte_functie`, `category`, `derived_beginjaar/eindjaar`. For diplomatic HOE contexts. |
| `schutte NL→buitenland` | `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/schutte_nl_in_buitenland.parquet` | 342 Dutch representatives abroad; same schema pattern. Different from `schutte main`. |
| `schutte main` | `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/schutte_df.parquet` | 342 rows, flat index; cols `key_0`, `name`, `givenname`, `pagenr`, `level`, `schutte_nr`, etc. Do NOT substitute for the directional files. |

**Routing rule**: when HOE context is `diplomatic` or `states_general_formula` (from `hoe_vocab.parquet`), route to Schutte reference in addition to the main delegate reference. Use `schutte_buitenland_in_nl` for foreign persons addressing the SG; `schutte_nl_in_buitenland` for Dutch persons in foreign-posting context.

## Reference Data (`/Users/rikhoekstra/develop/republic_delegates_data/`)

Described in `MANIFEST.toml`. Period 1630–1704 not yet started.

| Period | File | Key columns |
|--------|------|-------------|
| 1705–1795 | `1705_1795/consolidated/delegates_1705_1795_v1.0-rc1.parquet` | `cons_id_str`, `fullname`, `voornaam`, `tussenvoegsel`, `geslachtsnaam`, `provincie`, `minjaar`, `maxjaar`, `pattern`, `patterns`, `heerlijkheid`, `active_after_corrections` |
| 1610–1630 | `1610_1630/consolidated/delegates_1610_1630_v1.0-rc1.parquet` | `unified_id`, `matched_id`, `NAAM`, `PROV`, `kanonieke_naam`, `Id_persoon`, `min_date`, `max_date` |

## Matching Engine

**Data schema** (`build_store` / `match_ner` contract):
- `delegates_reference.parquet`: `cons_id_str`, `fullname`, `pattern` (semicolon-separated variants), `minjaar`, `maxjaar`
- `patterns_reference.parquet`: `cons_id_str`, `pattern`, `year_min`, `year_max`
- `annotations-layer_PER.tsv.gz`: `layer`, `inv`, `resolution_id`, `paragraph_id`, `tag_text`, `offset`, `end`, `tag_length`
- `inventory_metadata.json`: `inventory_num` → `year`, `period_start`, `period_end`
- Output: `data/results.parquet` with top-k candidates per span

**`match.py`**:
- Dual TF-IDF: char n-gram (2-4, weight 0.6) + word n-gram (1-2, weight 0.4)
- `build_store(delegates_df)` — index from `pattern` column
- `match_ner(store, ner_df, top_k, year_tolerance, min_score)` — scored candidates
- Year filtering via `minjaar`/`maxjaar` with tolerance window

**1610–1630 pipeline checklist**:
1. Load `1610_1630/consolidated/delegates_1610_1630_v1.0-rc1.parquet`
2. Rename: `unified_id` → `cons_id_str`; `PROV` → `provincie`; ISO `min_date`/`max_date` → `minjaar`/`maxjaar` (int)
3. Construct `pattern = kanonieke_naam + "; " + NAAM` (no pattern column in source)
4. Set `fullname = kanonieke_naam`
5. Pass to `build_store(delegates_df)`
6. Match with `min_score=0.15` (default 0.25) and `year_tolerance=20` (default 5)
7. Two-pass: period-filtered store first; if no hit above `min_score=0.15`, fall back to full store with `year_tolerance=40`

## Constraints (matching-specific)
- DO NOT drop `year_tolerance` — year filtering is essential for disambiguation
- DO NOT modify `delegates_reference.parquet` or `patterns_reference.parquet` directly

## Approach (this pipeline)
1. Core modules: `preprocess.py`, `match.py`, `run_match.py`
2. Early-period work: check whether `fullname` is a fallback in `build_store`; add if missing
3. Smoke test after `match.py` / `preprocess.py` edits: `uv run python -c "import match; import preprocess"`
4. Interactive exploration: `explore.ipynb`

## HOE Classifier (`hoe_classify.py`)

Offline two-pass classifier for the HOE annotation layer:
- Pass 1 (`classify_keyword`): exact substring match against seed lists
- Pass 2 (`classify_fuzzy`): `rapidfuzz.fuzz.token_set_ratio` against category centroids (word-order invariant)

**16 categories**: `quantifier_singular`, `quantifier_plural`, `honorific_excellentie`, `honorific_hoogheid`, `honorific_majesteit`, `sovereign`, `states_general_formula`, `diplomatic`, `military`, `administrative`, `ecclesiastical`, `maritime_military`, `collective_social`, `territorial_title`, `personal_status`, `other`

**Outputs**: `data/hoe_vocab.parquet` (1 201 799 rows); `data/hoe_category_counts.json`

**Re-run**: `uv run python hoe_classify.py [--hoe PATH] [--threshold INT]`

**Seed-list changes**: show top-20 `other` forms and get explicit approval first. Re-run and report new `other` bucket size. The `other` bucket is ~1.32 M rows (31%) — do not expand seeds casually.

**At match time**: dict lookup on `normalized_text` in `hoe_vocab.parquet` (O(1)).

## Output Format
- Analysis: top-1 accuracy estimate and score distribution
- New reference export: provide exact `export_reference.py` commands to run

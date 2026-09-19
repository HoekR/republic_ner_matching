# NER matcher — cross-repo reference data

Reference tables for `.github/agents/republic-ner-matcher.agent.md`, split out so the
agent prompt doesn't re-send them on every invocation. Load this file only when a task
actually touches one of these sources.

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
|--------|------|-----------------|
| 1705–1795 | `1705_1795/consolidated/delegates_1705_1795_v1.0-rc1.parquet` | `cons_id_str`, `fullname`, `voornaam`, `tussenvoegsel`, `geslachtsnaam`, `provincie`, `minjaar`, `maxjaar`, `pattern`, `patterns`, `heerlijkheid`, `active_after_corrections` |
| 1610–1630 | `1610_1630/consolidated/delegates_1610_1630_v1.0-rc1.parquet` | `unified_id`, `matched_id`, `NAAM`, `PROV`, `kanonieke_naam`, `Id_persoon`, `min_date`, `max_date` |

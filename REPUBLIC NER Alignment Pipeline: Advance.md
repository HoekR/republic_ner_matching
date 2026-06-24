# REPUBLIC NER Alignment Pipeline: Advanced Session & Anchor Strategy

**Status:** active development  
**Authoritative script:** `build_alignment_new.py`  
**Last updated:** 2026-06-22

---

## 1. The Core Problem

Aligning structured early modern resolutions (Enriched JSON) with raw HTR/OCR text (Flat Parquet) presents three major challenges:

1. **Noisy HTR dates** — OCR/HTR frequently misreads dates (e.g. confusing a 3 for an 8). Strict date-to-date matching fails because resolutions land in the wrong daily buckets.
2. **Low NER recall** — The NER pipeline often misses entities. Punishing a match for missing entities creates false negatives.
3. **Ubiquitous entities** — Common entities (e.g. Holland) appear everywhere, creating false positives if we rely on simple entity counts.

---

## 2. Architectural Strategy

### 2.1 Target architecture (session-first)

The long-term design shifts from text similarity to **anchor-based sequence alignment** on pre-calculated overlap data:

| Pillar | Purpose |
|--------|---------|
| **Golden anchors** | Verified Excel overlap files (`place_overlap_1626_1630.xlsx`, `org_overlap_1626_1630.xlsx`) — definitive entity bridges, no raw-text scanning |
| **Session mapping** | Map enriched date → flat `session-*` block via anchors; align inside the session, ignoring noisy HTR session dates |
| **Needleman–Wunsch + IDF** | Snap verified anchors together; gap-fill resolutions between anchors scored by entity rarity (IDF), not raw frequency |

### 2.2 Implemented architecture (current)

`build_alignment_new.py` implements the anchor + NW core, with pragmatic fixes discovered during integration:

| Component | Implementation |
|-----------|----------------|
| Enriched key | `volgnr` = `{date}_{resolution_index}` (not `id`, which is absent in JSON) |
| Flat key | `resolution_id` from LOC/ORG annotations (`paragraph_id` → `resolution_id` map) |
| Overlap lookups | Separate **place-only** and **org-only** lookups + combined lookup for NW scoring |
| Flat candidate pool | **Session-first** by default (`--session-first`); falls back to same-day or `±N` day window (`--date-window-days`) |
| NW diagonal gate | **Anchor-only diagonal** (`--anchor-only-diagonal`, default on) — no gap-fill pair without Excel entity overlap |
| Export filter | `--min-overlap-score` (default 2.0) drops low-evidence pairs from stratified sample |
| Cross-day evidence | Excel anchors when same-day; text fallback for entity names when window > 0 and dates differ |
| Human review | `verify_ground_truth.html` (reuses `write_verification_html` from `generate_alignment/`) |
| Verdict import | `import_verification_summary.py` → `ground_truth_curated.json` / `_rejected.json` / `_uncertain.json` |

### 2.3 Strategy adjustment (2026-06-18)

The draft in §4 assumed `paragraph_id` could be used directly as a flat key and that `session-*` could be regex-extracted from it. **That was incorrect:**

- Flat parquet uses `session-*-num-*-resolution-*` ids.
- Excel overlap uses `session-*-num-*-para-*` paragraph ids.
- **Fix applied:** paragraph → resolution mapping via `LOC-annotations.json` / `ORG-annotations.json`.

**Revised rollout order:**

1. ✅ Same-day anchor alignment with correct keys (working baseline)
2. ✅ Date-window candidate expansion + manual verification loop
3. ✅ **Session-first block alignment** — pool flat resolutions by `session_id` derived from mapped resolution ids (default when `--date-window-days 0`)
4. ✅ **Anchor-only NW diagonal** + `min_overlap_score` export filter (post-verification hardening)
5. ⬜ **Windowed overlap rebuild** — scripted version of `manual_entitiy_alignment.ipynb` merge with `|enriched_date − flat_date| ≤ N`
6. ⬜ Curated ground truth → training-pair projection

The legacy script `generate_alignment/build_alignment_artifacts.py` remains for the ±3-day **entity-in-text** heuristic path; it is **not** replaced — `build_alignment_new.py` is the Excel-anchor path.

---

## 3. Implementation Checklist

### Data preparation
- [x] Enriched resolutions JSON (`enriched_resolutions_1626_1630_complete.json`)
- [x] Flat resolutions parquet (`resolutions_flat.parquet`)
- [x] Place overlap Excel (`place_overlap_1626_1630.xlsx`) — 11,848 rows
- [x] Org overlap Excel (`org_overlap_1626_1630.xlsx`) — 1,651 rows
- [x] Entity canonical name files (LOC / PER / ORG)

### Pipeline (`build_alignment_new.py`)
- [x] Excel overlap → `(volgnr, flat_resolution_id)` lookup
- [x] Paragraph → resolution id mapping (5,949 ids resolved)
- [x] IDF-weighted Needleman–Wunsch per enriched session day
- [x] `match_kind`: `places_only` | `orgs_only` | `both` | `none`
- [x] Enriched + flat text in preview and ground-truth exports
- [x] Stratified verification sample (by month + match kind)
- [x] `verify_ground_truth.html` — Correct / False positive / Uncertain + export
- [x] Pagination controls top and bottom of verification UI
- [x] `--date-window-days` for extended flat candidate pool
- [x] Session-id pooling (immunity to HTR date noise within session)
- [x] Anchor-only NW diagonal + `--min-overlap-score` filter
- [x] `import_verification_summary.py` — merge browser export into curated/rejected JSON
- [ ] Windowed overlap regeneration (cross-day Excel anchors)
- [ ] Person-entity anchors in overlap scoring
- [ ] Import verified labels back into parquet / training pipeline

### Outputs (generated under `output/`)
- [x] `matched_resolutions_sample.html`
- [x] `ground_truth_stratified_matches.json` (+ `.jsonl`, `.parquet`, `_summary.json`)
- [x] `verify_ground_truth.html`
- [x] `ground_truth_curated.json` / `ground_truth_rejected.json` (from manual verification import)
- [x] `ground_truth_verification_analysis.json`

---

## 4. Milestones

### ✅ M1 — Overlap tables (complete)
Manual notebook `manual_entitiy_alignment.ipynb` produced place/org overlap spreadsheets by joining enriched entities with LOC/ORG annotations on shared date + entity name.

### ✅ M2 — Anchor alignment script (complete)
`build_alignment_new.py` — NW alignment driven by Excel anchors and IDF weights.

### ✅ M3 — Key alignment fixes (complete)
- `volgnr` derivation
- Paragraph → flat `resolution_id` mapping
- Preview HTML populated (was empty when keys were wrong)

### ✅ M4 — Entity-type visibility (complete)
Separate place/org shared-entity reporting in preview, JSON exports, and verification samples.

### ✅ M5 — Manual ground-truth workflow (complete)
Browser-based verification UI with persistent labels and JSON export.

### ✅ M6 — Date-window matching (complete)
`--date-window-days N` expands flat candidate pool; cross-day text fallback for entity evidence.

### ✅ M7 — Session-first pooling (complete)
Use `session-*` extracted from mapped flat resolution ids to define alignment blocks, decoupling from HTR calendar dates within a sitting. Default in `build_alignment_new.py` when `--date-window-days 0`.

### ⬜ M8 — Windowed overlap rebuild (next)
Re-derive overlap tables allowing `|enriched_date − flat_date| ≤ N` at data-prep time (notebook logic → script).

### ✅ M9 — Human verification pass (complete — first round)
Researcher labeled 50 stratified `both`-anchor pairs in `verify_ground_truth.html`; export `ground_truth_verification_summary_20260622.json`. See result summary below.

### ⬜ M10 — Curated alignments → downstream NER
Project verified enriched↔flat pairs into annotation-offset / training-pair builders.

---

## 5. Result Summaries

> **RESULT SUMMARY — Same-day mode** (`--date-window-days 0`)  
> Run date: 2026-06-18

| Metric | Value |
|--------|------:|
| Enriched resolutions loaded | 19,134 |
| Flat resolutions loaded | 692,156 |
| Place overlap rows | 11,848 |
| Org overlap rows | 1,651 |
| Paragraph ids mapped → resolution | 5,949 |
| **Total aligned pairs** | **6,936** |
| **Anchored pairs** (entity overlap) | **3,096** (44.6%) |
| Places only | 2,863 |
| Orgs only | 147 |
| Places + orgs | 86 |

---

> **RESULT SUMMARY — Date-window mode** (`--date-window-days 3`)  
> Run date: 2026-06-18

| Metric | Value |
|--------|------:|
| **Total aligned pairs** | **16,271** |
| **Anchored pairs** | **3,326** (20.4%) |
| Places only | 3,065 |
| Orgs only | 175 |
| Places + orgs | 86 |

*Note:* Window mode increases positional pair count substantially; Excel anchors remain same-day dominated. Cross-day pairs rely on NW gap-fill and optional text fallback — prioritize manual review before treating as ground truth.

---

> **RESULT SUMMARY — Verification sample** (latest `ground_truth_stratified_matches_summary.json`)

| Metric | Value |
|--------|------:|
| Stratified samples | 100 |
| Same-day in sample | 100 |
| Summary anchors (both + same-day) | 29 |
| Places only | 37 |
| Orgs only | 34 |
| Places + orgs | 29 |
| Places found in flat (aggregate) | 197 / 422 enriched |
| Orgs found in flat (aggregate) | 65 / 136 enriched |
| Persons found in flat (aggregate) | 0 / 265 enriched |

*Person matching is not yet anchored via Excel overlap; expect low person recall until PER overlap is added.*

---

> **RESULT SUMMARY — Manual verification pass #1**  
> Export: `ground_truth_verification_summary_20260622.json` · Run date: 2026-06-22  
> Pipeline mode: session-first, anchor-only diagonal, `min_overlap_score=2`, `match_kind=both`

| Metric | Value |
|--------|------:|
| Samples reviewed | 50 |
| **Correct** | **23** (46.0%) |
| False positive | 26 (52.0%) |
| Uncertain | 1 (2.0%) |
| All samples | `both` (place + org Excel anchors), same-day |
| Mean confidence — correct | 11.61 |
| Mean confidence — false positive | 10.74 |
| Precision at score ≥ 10 | 55.6% (27 pairs) |

**Interpretation:** Session-first pooling and anchor-only diagonal eliminated gap-fill false positives, but **entity overlap alone is insufficient** — false positives share nearly identical anchor profiles (avg 1.5 place + 1.0 org matches vs 1.7 + 1.0 for correct). Confidence scores barely separate verdicts. The NW sequence step still pairs the wrong flat resolution when multiple candidates on the same day share ubiquitous entities.

**Curated outputs:** 23 verified pairs in `output/ground_truth_curated.json`.

---

### 2.4 Entity signals (places / orgs / persons)

**Design choice:** treat entity types as **separate signals** that complement and cross-check each other, not only as a merged overlap score.

| Signal | Role today | Target role |
|--------|------------|-------------|
| **Places** | `place_lookup`; merged into NW score | Own overlap band along paragraph axis; sequence coherence per type |
| **Organizations** | `org_lookup`; merged into NW score | Independent band; agreement with places strengthens a link |
| **Persons** | Not in Excel anchors; 0 recall in verification sample | Later phase; lower weight until pinpointing improves |

**Combined vs separate:** The pipeline already stores place-only and org-only lookups (`build_overlap_lookups`) but NW scoring still sums them into one `combined_lookup` IDF score. The next refinement is **dual-signal scoring**:

- `score_place(i,j)` and `score_org(i,j)` as separate heatmap rows or matrix layers
- **Agreement bonus** when both peaks align at the same paragraph index (or adjacent)
- **Disagreement flag** when place and org diagonals diverge — candidate for manual correction (R2)
- **Combined score** only as fallback when a resolution has places but no orgs (or vice versa)

Ubiquitous places (Holland, Brabant) remain in the place signal; org agreement acts as a check rather than blocking place hits.

**Persons (deferred):** PER overlap is harder — sparse NER, ambiguous names, deputy/president metadata already on enriched side but not bridged to flat paragraphs. Add `person_overlap_*.xlsx` only after place/org sequence alignment stabilises; use as a third signal layer with conservative weight.

---

## 6. Usage

```bash
# Current default (session-first + anchor-only + both-kind verification sample)
uv run python build_alignment_new.py \
  --preview-limit 12 \
  --stratified-size 50 \
  --date-window-days 0 \
  --verification-match-kind both

# Import browser verification export
uv run python import_verification_summary.py \
  --verification output/ground_truth_verification_summary_20260622.json

# Extended matching with manual review (disables session-first pooling)
uv run python build_alignment_new.py \
  --preview-limit 12 \
  --stratified-size 50 \
  --date-window-days 3 \
  --no-session-first \
  --verification-page-size 5
```

Open `output/verify_ground_truth.html` in a browser to label pairs and export verification summary.

Sequence review (current iteration):

```bash
uv run python session_chain_alignment.py
# Open output/verify_session_heatmap_comparison.html  — session diagnostics
# Open output/verify_sequence_alignment.html          — ranked candidate picker
# Open output/verify_day_sequences.html             — side-by-side day sequences
# Open output/verify_resolution_search.html           — manual term search + pinpoint
# Export sequence_correction_summary.json from browser, then:
uv run python import_sequence_correction.py --correction output/sequence_correction_summary.json
uv run python session_chain_alignment.py              # re-align with new pins
```

---

## 7. Open Questions

1. **Sequence disambiguation** — NW needs stronger positional constraints; session-chain propagation in progress.
2. **Dual-signal scoring** — Implement separate place/org heatmap layers + agreement bonus (see §2.4).
3. **Person anchors** — Deferred until place/org sequence alignment stabilises; expect lower precision initially.
4. **Verification target** — Expand corrective ground truth via R2 loop before M10 training-pair projection.

---

## 8. Reference: superseded draft code

The inline Python draft previously in this document (session regex on `paragraph_id`, `enriched.get("id")`) is **superseded** by `build_alignment_new.py`. Do not paste that block into `generate_alignment/build_alignment_artifacts.py` — it used incorrect keys and would produce empty anchors.

See `build_alignment_new.py` for the current implementation.

# republic_ner_matching — implementation plan

Fine-tune GysBERT for multi-class NER on 1626-1630 Dutch Republic resolutions.
Recognize both place names (LOC-annotations) and delegate names (PER-annotations).

---

## Overview

**Inputs:**
- `data/LOC-annotations.json` — 1.3M location spans with character offsets & entity IDs
- `data/PER-annotations.json` — 2M person spans with character offsets & entity IDs
- `data/LOC-entities.json` — 2,459 place canonical names
- `data/PER-entities (1).json` — 8,076 person canonical names
- `data/resolutions_flat.parquet` — 692K resolutions with paragraph text

**Target period:** 1626-1630

**Outputs:**
- `data/training_pairs_loc_1626_1630_dedup.parquet` — 21K PLACE training records
- `data/training_pairs_per_1626_1630_dedup.parquet` — 13K NAME training records
- `models/gysberg_delegate_ner_loc/` — fine-tuned PLACE-only model
- `models/gysberg_delegate_ner_combined/` — fine-tuned PLACE+NAME model

---

## Phases

### Phase 1 — Data preparation ✅

**LOC training pairs** (`build_loc_training_pairs.py`):
```bash
uv run python build_loc_training_pairs.py
```

- Loads 1.3M LOC-annotations.json with character offsets
- Maps entity IDs to canonical names via LOC-entities.json
- Filters to 1626-1630 period (8,412 resolutions overlap)
- Creates 21K PLACE training records
- Output: `data/training_pairs_loc_1626_1630_dedup.parquet`

**PER training pairs** (`build_per_training_pairs.py`):
```bash
uv run python build_per_training_pairs.py
```

- Loads 2M PER-annotations.json with character offsets
- Maps entity IDs to canonical names via PER-entities.json
- Filters to 1626-1630 period (6,127 resolutions overlap)
- Creates 13K NAME (delegate) training records
- Output: `data/training_pairs_per_1626_1630_dedup.parquet`

### Phase 2 — Model training

**PLACE-only fine-tuning** (`finetune_gysberg_loc.py`):
```bash
uv run python finetune_gysberg_loc.py
```

- Fine-tunes emanjavacas/GysBERT on 21K place spans
- Uses 100-word truncation (conservative for 512 token BERT limit)
- Exact word-boundary matching only (no substrings)
- 70% train / 15% val / 15% test split by date
- Output: `models/gysberg_delegate_ner_loc/best-model.pt`
- Training: 10 epochs, batch size 16, learning rate 0.1, MPS acceleration

**Combined PLACE+NAME fine-tuning** (`finetune_gysberg_combined.py`):
```bash
uv run python finetune_gysberg_combined.py
```

- Fine-tunes GysBERT on 34K spans (21K PLACE + 13K NAME)
- Multi-class NER: labels are O, PLACE, NAME
- Same truncation, tokenization, and split strategy
- Output: `models/gysberg_delegate_ner_combined/best-model.pt`
- Training: 10 epochs, batch size 16, learning rate 0.1, MPS acceleration
- Corpus: 7,501 train + 1,384 dev + 1,214 test sentences

### Phase 3 — Evaluation

After training completes:

```python
from flair.models import SequenceTagger

# Load model
model = SequenceTagger.load("models/gysberg_delegate_ner_combined/best-model.pt")

# Test on sample
from flair.data import Sentence
sent = Sentence("Heinsius woonde in Amsterdam")
model.predict(sent)
for token in sent.tokens:
    print(f"{token.text} → {token.get_label('ner')}")
```

Expected output: `Heinsius` → NAME, `Amsterdam` → PLACE

### Phase 4 — Inference pipeline

For new resolutions (future work):
- Tokenize resolution paragraphs with 100-word truncation
- Run model predictions to extract PLACE and NAME spans
- Post-process: normalize whitespace, validate token boundaries
- Map canonical names back to entity IDs if needed

**Key implementation notes:**
- **Memory optimization**: Load only ~12K resolutions referenced in training pairs (98.2% reduction from full 692K)
- **BERT token management**: 100-word truncation ≈ 250-300 BERT tokens (safe margin below 512 limit)
- **Label matching**: Exact word boundaries only; no substring matching (prevents false positives like "dam" in "Amsterdam")
- **MPS acceleration**: Metal Performance Shaders on macOS; falls back to CPU for CRF layer
- **Date stratification**: Train/val/test split by calendar date ensures temporal coverage

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

### Phase 6 — Notebook (`explore.ipynb`) ✅

- Load results, show score distribution histogram
- Match rate by year (line chart)
- Top unmatched spans (score_1 < 0.1) — candidates for new delegates
- Sample table: span + top-3 candidates with scores

---

## Track B — Approaches from `huygens_name_index/names`

**Source**: `/Users/rikhoekstra/develop/huygens_name_index/names`

This is a mature, production-tested package originally built for the *Namenindex*
disambiguation task: matching free-text person names in archival sources to a
person authority register. The problem is structurally identical to ours, but at
different scale and with a different retrieval model (pairwise scoring rather than
vector search). The codebase embodies many years of practical experience with Dutch
historical naming conventions and should be treated as a knowledge source rather
than a drop-in replacement.

### Package components

#### `soundex.py` — Dutch phonetic normalization

`soundex_nl(s, length=-1, group=1|2)` reduces a name token to a phonetic key by
applying an ordered sequence of regex substitutions that encode Dutch spelling
conventions:

- Prefix stripping: `'s-`, `'t `, `d'`, `l'` etc.
- Spelling normalization at token level:
  - `ij`/`y`/`eij`/`ey` → `i` (all treated identically)
  - `ouw`/`auw`/`au`/`ou` → `o`
  - `ck`/`cks`/`kk`/`c` → `k`
  - `sch` (medial) → `s`
  - `ph`/`v`/`w`/`ff` → `f`
  - `ch` → `g` (in clusters like `ngh`, `gg`, `gh`, `ng`)
  - Historical suffixes: `-en` after consonant, final `-e` after consonant → dropped
  - `szoon` → `sz`, `-naar` → `-na`
  - French endings: `-ecque` → `-ek`, `-eille` → `-elle`
- Vowel folding at digit level: `ah/ae/a → 1`, `ee/eh/e → 2`, `eij/ey/ij/ie/y → 3`,
  `oh/oo/oe → 4`, `uu/uh → 5`, `ouw/au → 6`, `uy/uij/ui → 7`
- Two strictness levels: `group=2` is close to actual phonetics; `group=1` is more
  aggressive (collapses all vowels to `.`, strips leading `h`, merges `b/p`, `d/t`).

`soundexes_nl(s, filter_stop_words=True)` tokenises a full name string and returns
a list of phonetic keys, optionally filtering out stopwords (tussenvoegsels etc.)
before encoding.

**Relevance**: The current `char_wb` n-gram TF-IDF conflates e.g. "Wassenaer" and
"Wassenaar" only by shared bigrams, losing weight to suffix variation. `soundex_nl`
collapses both to the same key outright. It could serve as (a) an additional index
dimension alongside the TF-IDF vectors, (b) a pre-filter to narrow candidates before
scoring, or (c) a component in a reranker.

#### `common.py` — Name vocabularies and stopwords

The package maintains curated Dutch-name vocabularies:
- `TUSSENVOEGSELS`: `van`, `de`, `den`, `der`, `des`, `di`, `la`, `le`, `ten`,
  `thoe`, `tot`, `in 't`, `of`, `en`, `het` — these are also valid tussenvoegsels in
  Republic resolutions.
- `VOORVOEGSELS` (title prefixes): `dr`, `mr`, `prof`, `jhr` etc.
- `POSTFIXES` (patronymic): `azn.`, `cz.`, `Hz.`, `Wzn.`, `jr.`, `sr.`
- `TERRITORIALE_TITELS`: `graaf`, `baron`, `heer`, `prins`, `jonkheer` etc.
- `ROMANS`: Roman numerals (dynastic/numeral suffixes) treated as opaque tokens.
- `STOP_WORDS` = union of all the above + `PREFIXES`.
- `remove_stopwords(s)` strips all of the above from a string in one pass.

`to_ascii(s)` handles Unicode normalisation, accented characters, and HTML entities
(relevant for OCR output).

**Relevance**: The current `preprocess.py` strips some titles but does not have an
exhaustive tussenvoegsel list. Adding `remove_stopwords` before TF-IDF indexing
would prevent "van", "de", "den" etc. from inflating IDF weights or causing false
positives when a query has a different tussenvoegsel than the indexed pattern.
The `POSTFIXES` list handles patronymic suffixes (azn., Cz.) common in 18th-century
notarial/resolution text that the current preprocessor does not handle.

#### `similarity.py` — Composite weighted similarity

`average_distance(l1, l2, distance_function)` computes a bipartite best-match
average over two lists of word tokens (e.g. the words in a surname), with a penalty
of 0.8 per unmatched word in the longer list. This gracefully handles:
- Compound surnames split at a hyphen: `["Coehoorn"]` vs `["Coehoorn", "Goslinga"]`
- Spelling variants where one form has one token and the other has two
- Missing tussenvoegsels

`Similarity.ratio(n1, n2)` (requires two `Name` instances) combines five components
with learned weights:

| Component | Weight | What it measures |
|---|---|---|
| Normal-form Levenshtein | 5.0 | Character similarity of full name |
| Soundex of normal form | 8.0 | Phonetic similarity of full name |
| Soundex of *geslachtsnaam* | 10.0 | Phonetic similarity of surname |
| Levenshtein of *geslachtsnaam* tokens | 10.0 | Direct surname character distance |
| Initials Levenshtein | 2.0 | Initial string similarity |

When one name is in initials form, the weights shift: soundex and initials become
dominant, direct character distance shrinks. This is directly applicable since many
NER spans have the form "J. van Wassenaer" or "A.H. de Vrij".

**Relevance**: The current TF-IDF scorer has no concept of surname vs. initial vs.
tussenvoegsel — "J. de Vrij" and "Jan de Vrij" are not obviously closer to each
other than to "J. de With". `Similarity.ratio` encodes exactly this structural
awareness. It is most useful as a **reranker** on the top-k TF-IDF shortlist, since
computing it pairwise over the full delegate set would be too slow.

#### `name.py` — Structured name parsing

The `Name` object stores a name as an XML element tree with typed constituents:
`preposition`, `voornaam`, `intrapositie`, `geslachtsnaam`, `postpositie`,
`territoriale_titel`. It exposes methods: `geslachtsnaam()`, `initials()`,
`guess_normal_form()`, `geslachtsnaam_soundex()`, `contains_initials()`.

**Relevance**: Full `Name` parsing would allow truly structural comparison. However:
- It depends on `lxml` and an XML-based internal representation — heavy for bulk
  NER processing.
- `guess_normal_form()` requires some structure to be present; on raw NER spans
  (which are unstructured strings) it would need to fall back to the free-text
  constructor, which relies on heuristic guessing.
- The `from_args` path (where constituents are known) is reliable; the
  `from_string` path (parsing a raw span) is not.
- In practice it is more maintainable to extract just the surname component by
  stripping known tussenvoegsels/titles from the span, rather than instantiating
  `Name` objects.

### Proposed Track B design

Three graduated improvements, in increasing complexity:

**B1 — Preprocessing improvements** (low risk, low effort)
- Apply `remove_stopwords` from `common.py` to both the query span and the indexed
  patterns before TF-IDF scoring. This removes tussenvoegsels from the comparison
  surface.
- Apply `to_ascii` for accent/OCR normalisation (already partially done in
  `preprocess.py` but not exhaustively).
- Add `POSTFIXES` stripping (azn., Cz., Hz.) to `clean_span`.

**B2 — Soundex as secondary index dimension** (medium effort)
- Add a third TF-IDF vector per delegate based on `soundexes_nl(pattern, group=2)`.
- Combine: `score = 0.5 × sim_char + 0.3 × sim_word + 0.2 × sim_soundex`.
- The soundex index catches spelling variants (ij/y, ck/k, ae/a) that the char
  n-gram index underweights when the variant differs in length.

**B3 — Structural reranker on top-k** (medium effort, highest expected gain)
- After TF-IDF retrieves top-20 candidates, re-score each candidate against the
  query using `average_distance` on the *geslachtsnaam* component:
  1. Strip tussenvoegsels and initials from both query and candidate to isolate the
     surname tokens.
  2. Compute `average_distance(query_surname_tokens, cand_surname_tokens, levenshtein_ratio)`.
  3. If either contains initials, apply the soundex normal-form score as a tiebreaker.
  4. Re-rank and return top-k by reranked score.
- This avoids instantiating `Name` objects; it uses only the free functions
  `average_distance`, `levenshtein_ratio`, `soundexes_nl`, and `remove_stopwords`.

### Caveats and open questions

- **Dependency**: `similarity.py` imports the `Levenshtein` package (not
  `python-Levenshtein`; the API may differ). `rapidfuzz.distance.Levenshtein.normalized_similarity`
  is a drop-in replacement that is already in the project dependencies.
- **lxml**: `name.py` requires `lxml`. Not worth adding as a dependency if we only
  use the free functions from `similarity.py`, `soundex.py`, and `common.py`.
- **Weight calibration**: The weights in `Similarity.ratio` (5/8/10/10/2) were
  tuned on a different corpus and index. They should be treated as a starting point
  and re-evaluated against the benchmark once B3 is implemented.
- **`soundex_nl` group 1 vs 2**: Group 1 collapses too aggressively for a precision
  task (many false positives). Group 2 is the right default for Track B.
- **Stopword collision**: Stripping *all* stopwords from both query and index risks
  losing distinguishing tussenvoegsels for delegates whose surnames are themselves
  stopword-like (e.g. "Van" as a surname element). Apply stopword removal only for
  scoring, not for display or identification.

---

## Track C — Structured span matching built on `fuzzy-search`

### Motivation

The `fuzzy-search` package (Marijn Koolen, PyPI v2.7.1) was designed specifically
for Dutch Republic resolutions with OCR/HTR errors and historical spelling
variation. Its own documentation uses the exact texts and context phrases
(PRAESIDE, PRAESENTIBUS, "Den Heere Bentinck", "De Heeren ...") that we work
with. Building Track C on top of it avoids re-implementing character skip-gram
indexing, Levenshtein scoring, and phrase-variant logic from scratch.

Key capabilities that map to our problem:

| `fuzzy-search` feature | Track C use |
|---|---|
| `FuzzyTokenSearcher` | Token-level matching with character skip-grams inside tokens — exactly the two-level model |
| Phrase `variants` | All historical spellings of a context phrase as a single logical entry |
| Phrase `distractors` | Phrases that look like a context word but are actually part of a name (e.g. "de Heer" as title vs "De Heer" as a surname) |
| Phrase `label` | Tag context type: `quantifier`, `honorific`, `role`, `title`, `postfix` |
| Phrase `metadata` | Store quantifier arity (singular/plural), role category, year range |
| `PhraseMatch.offset` | Locate the context phrase within the span; the name tokens are what remains |
| `levenshtein_similarity` | First-pass similarity score for the context match |

### What the context component does

A NER span like "capitein Van Aerssen" or "zijne excellentie monsigneur Heinsius"
is a **name expression** with two separable parts:

1. **Context component**: honorifics, roles, titles, quantifiers that surround the
   name — "heere", "heeren", "ambassador", "capitein", "majoor", "monsigneur",
   "zijne excellentie", "jonkheer", "grave", etc.

2. **Name component**: the person name proper — voornaam (possibly abbreviated or
   absent), tussenvoegsel, geslachtsnaam, possibly a compound surname.

The context component serves four distinct functions:

| Function | Example | Implication for matching |
|---|---|---|
| **Quantification** | "heere" → 1 name; "heeren" → multiple names | Pre-split: extract one name vs. multi-person split |
| **Role disambiguation** | "ambassador Van Aerssen" vs "delegate Van Aerssen" (same year) | Use role to break ties between contemporaries with the same surname |
| **Role discovery** | "zijne excellentie monsigneur X" (not in index) | Record (X, role, year) as new attribute; enrich delegate record |
| **Career reconstruction** | "capitein Y" (1710) → "majoor Y" (1720) | Infer promotion; longitudinal enrichment |

### The two-level matching model

`FuzzyTokenSearcher` already implements this hierarchy:

- **Level 1 — character**: within each word token, character skip-grams absorb
  spelling variation (OCR errors, historical orthography, abbreviations).
  This is the same level as `soundex_nl` + Levenshtein in Track B.

- **Level 2 — token sequence**: phrases are matched as sequences of word tokens;
  a fuzzy token match requires enough tokens to match at the character level,
  allowing for missing tokens (gap), token insertions, and transpositions.
  This is the element-level sequence edit distance described in the user request.

The substitution cost at level 2 is derived from the character-level similarity
at level 1 — not from exact token equality — which is precisely the generalised
edit distance model we need.

### Proposed pipeline

```
Raw NER span  (or raw resolution text for full-text mode)
    │
    ▼
[Step 1] Context detection via FuzzyTokenSearcher
    Build a phrase model of context expressions with labels:
      - quantifiers: "heere", "den heer", "de heer", "heeren", "de heeren"
      - honorifics:  "monsigneur", "zijne excellentie", "haar hoogmogende"
      - titles:      "jonkheer", "grave", "graaf", "baron", "hertog"
      - roles:       "ambassador", "ambassadeur", "resident", "capitein",
                     "majoor", "kolonel", "admiraal", "raadpensionaris",
                     "pensionaris", "secretaris", "griffier", "ontvanger"
      - academic:    "mr.", "meester", "doctor"
      - postfixes:   "azn.", "cz.", "hz.", "jr.", "sr."
    Register known ambiguous strings as distractors (e.g. "de Heer" when it
    is used as a surname rather than a title).
    Run FuzzyTokenSearcher over the span; collect PhraseMatch objects.
    │
    ▼
[Step 2] Name extraction
    Remove context token offsets from the span string; what remains is the
    name component.  Normalise: to_ascii, lowercase, detect tussenvoegsels,
    identify initials.
    If quantifier label == plural → run multi-person split before Step 3.
    │
    ▼
[Step 3] Candidate retrieval (unchanged)
    Existing TF-IDF shortlist (top-20) + temporal gate.
    │
    ▼
[Step 4] Hierarchical reranking via FuzzyTokenSearcher (reverse mode)
    Build a second FuzzyTokenSearcher whose phrase model is the top-20
    candidate name strings.  Run it against the extracted name component.
    This gives a token-sequence + character-level similarity score for each
    candidate.  Combine with Track B soundex / Levenshtein reranker if active.
    │
    ▼
[Step 5] Context-assisted tie-breaking
    If ≥ 2 candidates remain close in score and a role context was detected:
      - Filter candidates whose known roles are incompatible with the role.
    If no role context: fall through to top-1 by score.
    │
    ▼
[Step 6] Attribute enrichment (optional)
    For matched spans that carry a role/title context token, emit a
    (cons_id_str, delegate_id, role_label, year) record into a side table.
    For unmatched spans with a role context, emit a discovery record for
    manual review.
```

### Phrase model structure

```python
context_phrases = [
    # quantifiers — singular signals one name follows
    {"phrase": "den heere",  "variants": ["de heer", "den heer", "den hr"],
     "label": "quantifier", "metadata": {"arity": "singular"}},
    {"phrase": "de heeren",  "variants": ["de heeren", "de hren"],
     "label": "quantifier", "metadata": {"arity": "plural"}},
    # honorifics
    {"phrase": "zijne excellentie", "variants": ["sijne excellentie", "s.e."],
     "label": "honorific", "metadata": {}},
    {"phrase": "monsigneur",
     "variants": ["monseigneur", "monsr.", "mons."],
     "label": "honorific", "metadata": {}},
    # roles — note: "raadpensionaris" is also a function in the canonical name
    {"phrase": "ambassadeur",
     "variants": ["ambassador", "ambassdr."],
     "label": "role",
     "distractors": ["ambassade"],  # avoid matching place names
     "metadata": {"role_category": "diplomatic"}},
    {"phrase": "capitein",
     "variants": ["capiteyn", "captn.", "cap."],
     "label": "role", "metadata": {"role_category": "military"}},
    # … extend from corpus frequency analysis
]
```

### Relationship to existing components

| Component | Role in Track C |
|---|---|
| `preprocess.clean_span` | Upstream normalisation; extend to preserve offset info |
| TF-IDF matcher (`match.py`) | Step 3 retrieval; unchanged |
| Track B (`soundex_nl`, `levenshtein_ratio`) | Optional scoring layer inside Step 4 token similarity |
| `TUSSENVOEGSELS`, `TERRITORIALE_TITELS` (common.py) | Seed vocabulary for context phrase model |
| `fuzzy_search.FuzzyTokenSearcher` | Steps 1 and 4 — core matching engine |
| `PhraseMatch.offset`, `.label`, `.levenshtein_similarity` | Context classification and name boundary detection |

### Implementation order

1. **Install**: `uv add fuzzy-search` (already a project dependency candidate).
2. **Build context phrase model**: start from TUSSENVOEGSELS / TERRITORIALE_TITELS
   in `common.py`; add roles and quantifiers from the frequency table of NER
   span prefixes.
3. **`split_span(text, searcher) → (context_matches, name_string)`**: thin wrapper
   around `FuzzyTokenSearcher.find_matches`; returns `PhraseMatch` list + residual
   name string.
4. **Wire into `match.py`**: call `split_span` before TF-IDF query; pass name
   component to TF-IDF; pass context matches to Step 5 tie-breaker.
5. **Benchmark**: run against Track A benchmark (divergence bands); compare top-1
   accuracy with and without Track C active.
6. **Attribute table**: once matching is stable, enable Step 6 enrichment.

### Open questions

1. **Context vocabulary completeness**: what fraction of NER spans contain a
   detectable context prefix? Requires a frequency scan of span-initial tokens.

2. **Distractor coverage**: "de Heer" is both title and surname. How many surname
   tokens also appear in the context vocabulary? Need a collision analysis.

3. **Quantifier → multi-person split interaction**: plural quantifier handling
   ("heeren A, B en C") is already partially in `preprocess.split_multi_person`.
   Confirm it fires before Step 3 so each name gets a separate TF-IDF query.

4. **`FuzzyTokenSearcher` config for name matching (Step 4)**: the default
   `ngram_size=2, skip_size=2` is very exhaustive; for short name tokens (2–8
   chars) `ngram_size=2, skip_size=1` may be sufficient and faster.

5. **Role-based disambiguation threshold**: when does the role confidently break a
   tie vs. when is the role token itself an OCR artifact? A minimum
   `levenshtein_similarity` threshold on the context match (e.g. 0.75) should gate
   its use for disambiguation.

6. **Career inference scope**: whether role-change records feed back into the
   delegate index (active learning) or stay as a read-only enrichment table is an
   architectural decision deferred to after Step 5 benchmark.

---

## HOE Classifier (`hoe_classify.py`) ✅

### Motivation

The HOE annotation layer (4.2 M rows, 1.2 M distinct forms) carries the
**context component** of NER spans: honorifics, roles, titles, and quantifiers
that immediately precede or surround delegate names. Understanding this layer
serves two purposes:

1. **Quantifier detection** — "heere" → singular name follows; "heeren" → multi-
   person split before matching.
2. **Role disambiguation** — "ambassadeur Heinsius" vs "raadpensionaris Heinsius"
   (same surname, different contemporaries) — the role breaks the tie.

### Architecture

Two-pass offline classifier:

**Pass 1 — keyword match** (`classify_keyword`): exact substring match against
seed strings per category. O(n seeds) per form, runs once over the ~1.2 M
distinct forms during pre-classification.

**Pass 2 — fuzzy fallback** (`classify_fuzzy`): `rapidfuzz.fuzz.token_set_ratio`
against category centroids. Chosen because it sorts+deduplicates tokens before
scoring → word-order invariant and handles interjected stopwords (e.g.
"extraordinaris envoyé aan het hof van" ≡ "envoyé extraordinaris") without
exhaustive skip-gram indexing.

At match time: dict lookup on `data/hoe_vocab.parquet` → O(1).

### 16 categories

| Category | Occurrences | Distinct forms | Purpose |
|---|---|---|---|
| `other` | 1 317 577 | 574 490 | unclassified; needs further seed expansion |
| `administrative` | 675 807 | 122 599 | griffier, secretaris, pensionaris, etc. |
| `diplomatic` | 364 987 | 61 698 | ambassadeur, resident, consul, envoyé |
| `sovereign` | 355 684 | 85 082 | coninck, keyser, prins, grave, lord, duke |
| `military` | 344 683 | 81 478 | capitein, colonnel, generael, admirael |
| `territorial_title` | 180 484 | 29 188 | heere van, heer van |
| `collective_social` | 155 227 | 45 711 | ingesetenen, crediteuren, gedeputeerden |
| `quantifier_singular` | 143 564 | 42 425 | den heere, de heer, den hr |
| `quantifier_plural` | 143 026 | 33 421 | de heeren, de heren |
| `maritime_military` | 139 095 | 38 901 | schipper, officieren, matroosen |
| `honorific_majesteit` | 127 783 | 19 848 | sijne majesteyt, haar mat |
| `personal_status` | 109 986 | 35 902 | weduwe, wijlen, coopman, erffgenamen |
| `states_general_formula` | 76 304 | 9 597 | haar hoogh mogende extraordinaris envoyé |
| `ecclesiastical` | 53 045 | 17 280 | predicant, bisschop, abt |
| `honorific_excellentie` | 46 220 | 2 711 | syn excie, zijne excellentie |
| `honorific_hoogheid` | 14 817 | 1 468 | zijne hoogheid, hare hoogheid |

### Outputs

| File | Rows | Columns |
|---|---|---|
| `data/hoe_vocab.parquet` | 1 201 799 | `normalized_text`, `category`, `method`, `token_set_score`, `count` |
| `data/hoe_category_counts.json` | 16 entries | `{category: {total, distinct}}` |

### Re-run

```bash
uv run python hoe_classify.py [--hoe PATH] [--threshold INT] [--out PATH] [--summary PATH]
```

Default input: `~/Downloads/annotations-unaggregated/annotations-layer_HOE.tsv.gz`

### Known limitation

`other` bucket is ~1.32 M rows (31 % of total) — the largest single category.
Priorities for reduction:
- Run frequency analysis on top-100 `other` forms and add seeds
- Merge with `abbrd.functienaam` values (see next section) to auto-generate
  administrative seeds from the authoritative register

---

## Additional data sources

### `abbrd` — Authoritative delegate biographical index

**Location**: `/Users/rikhoekstra/develop/streamlit_worksheet/abbrd_minimal.parquet`

**Schema** (9 698 rows):

| Column | Type | Notes |
|---|---|---|
| `fullname` | str | Canonical surname, given name (e.g. `"Aa, Willem van der"`) |
| `geboortejaar` | float | Birth year (many nulls) |
| `overlijdensjaar` | float | Death year (many nulls) |
| `beginjaar` | float | First year active |
| `eindjaar` | float | Last year active (nulls = still active) |
| `functienaam` | str | Semicolon-separated roles, e.g. `"lid;gecommitteerde"` |
| `college` | str | Institution(s), e.g. `"Vroedschap van Rotterdam;VOC"` |
| `provincie` | str | Province (mostly null in this minimal export) |
| `gedeputeerde` | bool | `True` = actual delegate to Staten-Generaal |

**What it adds beyond `delegates_reference.parquet`**:
- `beginjaar`/`eindjaar` are more complete than `minjaar`/`maxjaar` for some
  delegates (different source; cross-check useful)
- `functienaam` values → seed vocabulary for HOE `administrative` and `diplomatic`
  categories
- `gedeputeerde` flag enables filtering to just SG delegates (True = 1 027 rows
  roughly, matching current reference)
- `college` → institution context; useful for disambiguation when two delegates
  share a surname and year range

**Integration path**:
1. Join on `cons_id_str` ↔ `abbrd.fullname` (after normalisation) to enrich
   `delegates_reference.parquet` with `functienaam` and `beginjaar`/`eindjaar`.
2. Extract unique `functienaam` tokens → add to HOE classifier seeds.
3. Use `college` as a secondary disambiguation field in Track C Step 5.

### `schutte-bewerkingen` — Diplomatic representatives index

**Location**: `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/`

Three parquets:

| File | Rows | Key columns | What it is |
|---|---|---|---|
| `schutte_buitenland_in_nl.parquet` | 686 | `name`, `givenname`, `schutte_functie`, `category` (country), `derived_beginjaar/eindjaar` | Foreign diplomatic representatives to the Dutch Republic |
| `schutte_nl_in_buitenland.parquet` | 342 | same schema | Dutch representatives abroad |
| `schutte_df.parquet` | 342 | `name`, `givenname`, `pagenr`, `schutte_nr`, `nr`, `category` | Flat index (both directions combined) |

`schutte_functie` values include: `ambassadeur`, `extraordinaris ambassadeur`,
`gedeputeerde`, `chargé d'affaires`, `secretaris van ambassade`, `commissaris`.

**What it adds**:
- Foreign delegates who appear in resolutions as addressees or counterparties
  (currently absent from `delegates_reference.parquet` which covers only SG members)
- `schutte_functie` → additional seed vocabulary for HOE `diplomatic` category
- `category` (country) → context for `states_general_formula` HOE spans

**Integration path**:
1. Create `data/schutte_reference.parquet` combining both direction files, with
   columns: `name`, `givenname`, `derived_beginjaar`, `derived_eindjaar`,
   `schutte_functie`, `category`.
2. Run NER matching separately against Schutte reference for spans whose HOE
   context is `diplomatic` or `states_general_formula`.
3. Store matches in `data/schutte_results.parquet` alongside main `results.parquet`.

### `fuzzy_search_poc.ipynb` — Compound-name filter, FuzzyPhraseSearcher, and MySQL supplement

**Location**: `/Users/rikhoekstra/develop/streamlit_worksheet/fuzzy_search_poc.ipynb`

The notebook has two distinct parts:

**Part 1 — FuzzyPhraseSearcher + compound-name filter (cells 1–19)**:

1. **`FuzzyPhraseSearcher` integration** (cells 1–3): tests whether
   `fuzzy-search` recovers the same split-half → neighbor matches as the manual
   Levenshtein loop in `pattern_merge.py`. Config tuned for short proper names:
   `ngram_size=2, skip_size=1, levenshtein_threshold=0.6`.

2. **Compound-name pre-check** (cells 5–6): before flagging a pattern as a concat
   candidate, check whether the **whole pattern** scores well against any single
   anchor. If `min_lev_dist(pattern, anchor) ≤ t_compound`, skip it — it is a
   compound name, not a concat error. Current default `t_compound ≈ 0.25`.

3. **Distractor mechanism** (cell 4): register the full compound name as a
   `distractor` for each split-half phrase → `FuzzyPhraseSearcher` suppresses
   matches when the input is closer to the distractor than to the phrase.

4. **Ground-truth validation loop** (cells 7–10): sweep `t_compound` over
   labeled CSV (`ground_truth_concat_candidates.csv`); optimise precision/recall
   for compound suppression without dropping genuine concat candidates.

**Part 2 — MySQL supplement for delegate export (cell 28)**:

Cell 28 connects to a **local MySQL database** (`raa_nw`) via `pymysql` to produce
the authoritative `uq_delegates_baked_<date>.parquet`. The database is the
underlying source that the parquet exports are derived from.

Connection: `host='localhost', user='rik', db='raa_nw'`

Two queries:
- `persoon WHERE id IN (active_ids)` — fetches `geslachtsnaam`, `voornaam`,
  `tussenvoegsel`, `geboortejaar`, `overlijdensjaar`, `heerlijkheid` to fill
  null columns in the parquet
- `aanstelling JOIN provincie` (two passes: SG-only appointments first, then all)
  — populates `provincie` for delegates where the parquet has nulls

The MySQL database is the **ground truth** for biographical and appointment data;
the parquets are snapshots. Any delegate absent from the parquet but present in
the corrections list is fetched directly from MySQL.

**Relevance for this project**:
- The `raa_nw.persoon` table is the authoritative source for `fullname`,
  `geslachtsnaam`, `geboortejaar`, `overlijdensjaar` — richer than what is in
  `abbrd_minimal.parquet` (which is a pre-filtered export).
- If this project needs to expand the delegate reference (e.g. for 1610–1630
  period), querying `raa_nw` directly would give the most complete data.
- The `aanstelling JOIN provincie` pattern shows how to derive province assignments
  from the relational schema — useful for period-aware disambiguation.
- The distractor pattern from Part 1 is directly applicable to Track C Step 5
  tie-breaking: register the longer compound name as a distractor for the shorter
  anchor (e.g. "van der Capellen tot den Pol" as distractor for "van der Capellen").

---

## Data paths (defaults)

Logical names are defined in [`data_manifest.toml`](data_manifest.toml). Resolve at runtime:

```bash
uv run python -m data_io.check
```

| Logical name | Relative path (via `data/` symlink) |
|---|---|
| resolutions_flat | `resolutions/resolutions_flat.parquet` |
| per_annotations | `annotations/PER-annotations.json` |
| loc_annotations | `annotations/LOC-annotations.json` |
| delegates_reference | `reference/delegates_reference.parquet` |
| patterns_reference | `reference/patterns_reference.parquet` |
| inventory_metadata | `reference/inventory_metadata.json` |
| ner_per_annotations | `~/develop/.../downloads/annotations-layer_PER.tsv.gz` (hot tier) |
| gnb_passport_sessions | `/Volumes/Extreme SSD/scratch/gnb_passport_sessions.jsonl` |

See [docs/DATA.md](docs/DATA.md) for tier layout. Legacy table:

| File | Path |
|---|---|
| NER PER annotations (download) | `~/Downloads/annotations-unaggregated/annotations-layer_PER.tsv.gz` |
| HOE annotations | `~/Downloads/annotations-unaggregated/annotations-layer_HOE.tsv.gz` |
| results | `data/results.parquet` |
| hoe_vocab | `data/hoe_vocab.parquet` |
| hoe_category_counts | `data/hoe_category_counts.json` |
| abbrd (external) | `/Users/rikhoekstra/develop/streamlit_worksheet/abbrd_minimal.parquet` |
| schutte buitenland→NL | `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/schutte_buitenland_in_nl.parquet` |
| schutte NL→buitenland | `/Users/rikhoekstra/Nextcloud2/Republic/gekoppelde_resources/schutte-bewerkingen/schutte_nl_in_buitenland.parquet` |

# Segmentation transfer — reframing enriched↔HTR alignment

**Status:** proposed (29 Aug 2026) · **Supersedes:** the entity-discrimination framing of tier-3 alignment
**Scope:** inventories 3186–3189 (1626–1630); extensible to further inventories, not the whole corpus

---

## 1. Working hypothesis

The enriched edition is **normative**: the number of resolutions per sitting and their order are
hand-edited and checked. Therefore `K_e` (enriched resolution count per session-day) is ground
truth for how many resolutions a sitting contains.

The HTR side does not agree. Sample day `session-3186` / 1627-09-02:
**5 enriched, 3 flat resolutions, 6 paragraphs.**

The aligner is being asked to map 5 things onto 3. **A large share of the measured 52% false-positive
rate is not a scoring failure — the correct answer is not in the candidate set.**

> **The task is not matching. It is count-constrained segmentation transfer:**
> given `K_e` normative resolutions and an ordered stream of HTR units for that day,
> place the `K_e − 1` cut points.

### 1.1 Evidence already in hand (previously misread as "discrimination")

| Signal | Correct reading |
|---|---|
| 5 enriched / 3 flat / 6 paragraphs on the sample day | count mismatch; HTR under-segmented |
| `nw_matches_gt_rate` 0.957 (correct) vs 0.962 (FP) | NW picks an index from a set lacking the right answer; identical rates are exactly what structural unavailability predicts |
| 610 folio-turnover fragments already auto-stitched | the pipeline already knew flat resolutions were mis-segmented |
| paragraph axis loses to resolution axis (gain −4.16) | measured for paragraphs as *match candidates*; as *cut-point units* the finding does not apply |
| tier-3 = `head_template` + `tail`, 2,883 pairs (21.6%) | "tails" are fragments by name |

Source: [output/sequence_overlap_summary.json](../output/sequence_overlap_summary.json),
[output/daily_tri_anchors.json](../output/daily_tri_anchors.json).

---

## 2. Framing: all components exist — what is missing is order and evaluation

No new capability is required. Already in hand:

- normative `K_e` (enriched edition)
- 5,725 tier-1 anchors at ~99% precision (~1 anchor per 2.3 rows of 13,342)
- entity sequences and `calculate_idf_weights`
- Needleman–Wunsch (`align_session`) in [build_alignment_new.py](../build_alignment_new.py)
- tri-anchors in [discover_session_tri_anchors.py](../discover_session_tri_anchors.py)
- a review UI in [sequence_review_ui.py](../sequence_review_ui.py)
- upstream (`~/develop/republicgit`): early-band phrase model, `NeuralLineClassifier` `para_start`,
  and 245 hand-validated `res_start` records

The work is **assembly plus a proper evaluation harness**.

---

## 3. Why the previous ground truth felt circular — it was the wrong kind

Pair verdicts (`correct` / `false_positive`) are **algorithm-dependent artefacts**: valid only for
the candidate set that produced them. Change the candidate generator and they expire. That is the
structural reason the labelling loop never accumulated, and why more of the same would not have
helped.

**Boundary annotations are algorithm-independent facts.**

| | pair verdicts (old) | boundary gold (new) |
|---|---|---|
| unit | one enriched–flat pair | one session-day, all `K_e − 1` boundaries at once |
| validity | expires when the aligner changes | permanent |
| task type | comparison (slow, fatiguing) | reading + marking (fast) |
| yield | 1 label per judgement | `K_e − 1` labels per day |
| cost | ~150–300 labels for weak power | ~50 days × 2–4 min ≈ **2–4 hours** |
| reuse | none | merges with upstream `ground_truth/resolutions/res_start/` (245 records, same schema); contributable back |

Stratify the annotated days by `|K_e − K_f|` (see D1) so the gold covers the failure modes rather
than the easy cases.

---

## 4. Evaluation harness — define this before any modelling

The absence of a fit-for-purpose metric is what allowed the circling.

**Primary — boundary accuracy over the HTR stream:**

- boundary precision / recall / F1 at tolerance `t` (characters or lines)
- **WindowDiff** and/or **P_k** — standard text-segmentation metrics, tolerance-aware by design.
  Use these rather than exact match: exact-match metrics already produced a false alarm in this
  project (PER 0.5% exact vs 82.7% case-insensitive, see D3).
- exact-count satisfaction rate: fraction of days where `K_f' == K_e`

**Secondary (continuity only, demoted):** pair-level precision on the 50 labelled pairs and the
42-pair audited backtest. Keep for comparability with past results; do not optimise against it.

**Always report:** coverage alongside precision, with explicit abstention.

### 4.1 Diagnostics must run through the real pipeline, not a shortcut of it

*(Added 2026-09-18, after a concrete miss — see PLAN.md S4 session log and
[docs/S4_ITERATION_REVIEW.md](S4_ITERATION_REVIEW.md).)* A hit-rate diagnostic that
measures a signal directly at true gold positions (e.g. "does this phrase list match
at the known cut point?") answers a different question than "does this signal survive
the actual prediction pipeline" — the pipeline's own combination/revert logic can
silently discard most of what the diagnostic found. Concretely: an opening-phrase
inventory scored 73.6% exact / 76.4% fuzzy hit rate when checked directly against 360
gold cut points, but only reached 1 of 5 predicted days once run through
`s4_paragraph_axis_baseline.py`'s snap-then-revert step, because that step discarded
an entire day's snaps on a single collision. The diagnostic wasn't wrong, but it
wasn't sufficient either — **always additionally check the signal's effect after it
passes through the full candidate pipeline** (e.g. inspect the `source` field on
actual predictions, not just the isolated hit-rate), not only the isolated hit rate.

---

## 5. Diagnostics — zero annotation, all data already on disk

### D1 — structure vs evidence (decisive; run first)

Per session-day across 1626–1630:

- *Structure:* `K_e`, `K_f` (flat resolutions), `K_p` (paragraphs); distribution of `K_e − K_f`
- *Evidence:* `E_e`, `E_f` entity sets pooled per session-day; report `|E_f|/|E_e|` and containment
  `|E_e ∩ E_f| / |E_e|` (containment survives name variants — use the existing abbrd/schutte/fuzzy
  normalisation)

**Entity budget is conserved under segmentation** — under-segmenting pools entities, it does not
destroy them. Hence:

| | `K_f ≈ K_e` | `K_f < K_e` |
|---|---|---|
| `E_f ≈ E_e` | discrimination problem (the old hypothesis) | **pure segmentation — expected result; highly fixable** |
| `E_f ≪ E_e` | NER recall problem | both broken; segmentation first |

**This escapes the n=50 power problem.** Verdict-based per-session precision is n=5–11 and
unreliable (binomial CIs on 8/11 and 0/5 overlap). Structure and evidence statistics are computed
over *every* resolution and entity in the session, so they are reliable. If they correlate with the
noisy verdict pattern (3185/3188/3189 low, 3186/3187 high), that is mutual corroboration, and
structure becomes a free corpus-wide proxy for expected precision.

**Run D1 before spending any expert time on gold.**

*Caveat:* `E_f` derives from NER of unknown recall, so `E_e` vs `E_f` conflates NER recall with HTR
quality. Restrict to trusted tier-1 days to partly decompose.

### D1c — how much to trust entity order

On trusted tier-1 pairs, compute Kendall τ between enriched and HTR entity order within the pair;
report separately for high-IDF and low-IDF entities. Sets the transposition band width empirically
instead of by guesswork.

### D2 — is the existing LLM judge signal or noise?

`llama3.2:latest` (~3B) judging 17th-century Dutch produced 58.3% confirmed / 30.1% non-match /
11.6% uncertain, with **no accuracy measurement against the 50 labelled pairs**. Cheap to fix. If it
is near chance, the schema was never the issue.
Files: [judge_tier3_candidates.py](../judge_tier3_candidates.py),
[alignment_llm_judge.py](../alignment_llm_judge.py).

### D2b — opening/closing formula hit rate

For each **anchored tier-1** HTR resolution start, does the current `OPENING_FORMULA` regex
([build_alignment_new.py](../build_alignment_new.py), ~L451) or the upstream early-period phrase set
fire? Report hit rate; same for resolution ends. A hit rate below ~60% confirms missed openings as
the segmentation cause.

### D3 — training-pair metric artefact (independent)

PER exact-match 0.5% vs case-insensitive 82.7% is a metric bug, not a data bug. Apply soft /
case-insensitive containment in the training-pair rebuild
([rebuild_training_pairs_from_annotations.py](../rebuild_training_pairs_from_annotations.py) and the
PER variant).

---

## 6. Entity order is the primary segmentation signal

Entity order matters when comparing HTR to enriched. Not absolute — editorial wording shifts order
locally — but resolutions shift topics, so entity sequences are distinctive except for the most
frequent entities.

**Reframe: align entity sequences, not resolutions.**

- HTR side: the day's entity mentions in reading order, each with a position (paragraph index,
  char offset).
- Enriched side: flatten the `K_e` normative resolutions into one ordered sequence of
  `(resolution_index, entity)` pairs.
- Align the two with **Needleman–Wunsch at the entity level**, with gaps for NER misses and for
  entities the editor did not record.
- **The enriched resolution boundaries project through the alignment onto HTR positions. The cut
  points fall out directly.**

Consequences:

1. **NW is the right tool — applied to entities within a day, not resolutions within a day.** Keep
   `align_session`; change what it aligns.
2. No candidate-segment scoring needed. `K_e − 1` cut points are guaranteed by construction.
3. **The paragraph-vs-line granularity question dissolves.** Cut points land at character positions;
   snap afterwards to the nearest `para_start` or opening-formula hit. The line classifier and phrase
   model become a **snapping prior**, not the primary signal.
4. **Two-level constraint:** *between* resolutions order is normative → hard monotonicity at block
   level; *within* a resolution editorial rewording applies → soft, with a transposition band (width
   from D1c).
5. **Frequent entities are the known confound** — apply the existing `calculate_idf_weights` to the
   NW substitution score so "Holland" matching "Holland" earns almost nothing.

---

## 7. Milestones as scaffolding — interpolation is exact-count

The ~78% coverage is not merely shippable output, it is **scaffolding**. 5,725 tier-1 anchors across
13,342 rows is roughly one anchor every 2.3 rows, so unanchored gaps are short (typically 1–2
resolutions).

Combined with normative `K_e`, interpolation between consecutive anchors becomes **exact-count**:
the number of resolutions between milestone *i* and *i+1* is known. A gap of known length 1 or 2
with fixed endpoints is nearly determined.

Consequence: the residual problem is small and locally constrained. The global LLM judge over 2,935
candidates treated as independent decisions was solving a problem mostly settled by local
constraints. **Apply the constraint first; judge only what survives.**

Threshold policy: interpolate automatically above a certainty threshold, **abstain** below, route
abstentions to human review.

---

## 8. Segmentation failure = missed formulaic openings

Segmentation fails largely because formulaic openings (and probably closings) are missed: the phrase
set diverges from the one built for other periods.

Corroborated upstream in `~/develop/republicgit`:

- `make_opening_searcher(year_start, year_end)` filters `proposition_opening_phrases` **by year
  range**; the early band is tagged **1576–1637**, the main set 1637–1796.
- **1626–1630 sits in the early, sparser band.**
- The same pattern appears elsewhere: upstream widens the date search window for `year_start < 1630`
  (`num_future_dates` 31 → 61). Early material is systematically underserved.
- Early examples in `resolution_phrase_model.py`: `Is geaduyseert`,
  `Nochmaels ter Vergaderinge voortgebracht` — short relative to the main set.

**Fix — harvest openings and closings from the anchors.** Take the HTR text at each of the ~5,725
anchored resolution starts, extract leading n-grams, normalise for HTR noise, cluster. This yields an
opening-phrase inventory derived from 1626–1630 itself rather than inherited. Repeat on trailing
n-grams for closing formulae (relevant to `tier3_tail`).

Properties:

- uses only ~99%-precision material, so the harvest is clean
- **self-reinforcing:** better openings → better segmentation → more anchors → better openings
- **derive the inventory, do not invent it** — this supersedes any hand-written discourse-regime taxonomy
- contributable upstream as an extension to `proposition_opening_phrases` for the early band

*Caveat:* upstream `NeuralLineClassifier` `para_start` labels may themselves be period-skewed
(labelled lines come largely from inventory 3156 and neighbours). Check `checked`-flag coverage per
inventory before relying on it as a snapping prior.

---

## 9. Segmentation design

**Unit choice.** Paragraphs first. If `K_p < K_e` on a meaningful share of days, paragraphs are also
too coarse and cut points must be sought at **line** level.

**Supervision upstream (`~/develop/republicgit`) — verified 2026-09-18, not as available as this
section previously claimed:**

- `republic/classification/line_classification.py` — `NeuralLineClassifier` (GysBERT) predicting
  `para_start` / `para_mid` / `para_end` / `date` / `attendance` / `marginalia`. No trained
  checkpoint confirmed present; would need training/fine-tuning, not just loading.
- `ground_truth/line_classification/htr_classified_lines.csv` (14,324 rows, the canonical/merged
  file) — **zero rows** fall in target inventories 3185–3189 (checked directly by inventory
  number extracted from `page_id`). Skewed to inventory 3156 and ~176 other inventories instead.
- `ground_truth/line_classification/htr_classified_lines_marijn.csv` (one of three per-annotator
  variants) — does have 1,294 `checked=1` rows across all five target inventories (121
  `para_start`, 123 `para_end`), but scattered across only 2–9 sampled scan pages per inventory
  out of hundreds — spot-check density, not comprehensive coverage. Unmapped to calendar dates;
  overlap with the 12 structurally-abstaining gold days (§ below) is unverified and, given the
  sparsity, unlikely to be complete.
- `ground_truth/resolutions/res_start/*.jsonl` — 245 hand-validated resolution openings; **zero
  overlap** with inventories 3186–3189 (already noted in PLAN.md).
- `republic/model/resolution_phrase_model.py` — period-scoped opening phrases.

**Implication:** treat line-level segmentation as needing new ground truth (targeted annotation of
the marijn-variant pages that *do* land on the 12 gold days, or fresh sampling) before any DP/
classifier work, not as a drop-in reuse of existing supervision. Before committing engineering
effort: map the 1,294 marijn-variant rows' `page_id`s to calendar dates and check how many of the
12 gold days they actually touch. **Correction, 2026-09-18: this join is not cheap.** No dataset in
`data_manifest.toml` maps (inventory, scan/page) to date for these inventories —
`session_index_all.parquet` and `session_date_status_1626_1630` are both session-level
(`inventory_id`/`session_num`), not scan/page-level. The join needs a new extraction step over the
unextracted 10 GB `sessions_json-2026-02-27.tar.gz` to read per-session page ranges first. Scope
that extraction as its own step (register it in `data_manifest.toml`) before attempting the
overlap check; see docs/DECISIONS.md 2026-09-18.

**Algorithm.** Monotone DP over cut points, `O(N²K)`; with N ≈ 10 units and K ≈ 5 this is trivial.
Score a candidate segment against enriched resolution *i* by typed entity overlap + IDF (existing
`score_typed_overlap`), an opening-formula prior at the cut point, and optionally a length prior.
Tri-anchors from [discover_session_tri_anchors.py](../discover_session_tri_anchors.py) pin cut
positions as hard constraints.

**Why count-constrained segmentation is much easier than free segmentation:** the classifier need not
be precise, only to *rank* candidate cut points. Take the top `K_e − 1` subject to monotonicity.
`K_e` removes the hardest part of the problem.

**Post-condition:** after re-segmentation `K_f' == K_e` by construction, so the residual task is a
genuine 1:1 ordered correspondence — at which point mutual exclusivity and monotonicity are sound
(they were not before).

---

## 10. Sequence

| Step | Work | Depends on |
|---|---|---|
| **S0** | Build the evaluation harness: boundary P/R/F1 at tolerance `t`, WindowDiff/P_k, exact-count satisfaction; wire the 42-pair backtest in as demoted secondary | — (**blocking**) |
| **S1** | Four zero-annotation diagnostics in parallel: D1, D1c, D2, D2b | — |
| **S2** | Harvest openings/closings from the ~5,725 anchors → 1626–1630 phrase inventory | D2b |
| **S3** | Boundary gold: ~50 session-days, stratified by `\|K_e − K_f\|`; merge with upstream `res_start` (~2–4 h expert time). **Tooling done** ([build_boundary_gold_sample.py](../build_boundary_gold_sample.py)); upstream `res_start` has zero overlap with inventories 3186–3189, so annotation is from scratch. Hand-labeling still pending. | D1 |
| **S4** | Assemble: entity-sequence NW → cut points → snap to harvested opening / `para_start` → exact-count interpolation between anchors → abstain below threshold | S1, S2 |
| **S5** | Evaluate with S0; route abstentions to `sequence_review_ui.py` | S0, S3, S4 |

---

## 11. Verification

1. D1 output: `K_e − K_f` distribution and entity containment per session-day, cross-tabbed against
   the 50-pair verdicts. Expect FP concentration where `|K_e − K_f|` is large.
2. Post-segmentation: `K_f' == K_e` for ~all days by construction; report the exceptions.
3. Re-run the 42-pair audited backtest — precision must hold at 100% with tier-3 volume falling.
4. Report per-session precision first, with explicit abstention and coverage.
5. `uv run python -m data_io.check` after manifest edits; register `session_day_index` and
   `resegmented_resolutions`. Use `pd.Period(freq="D")` only — never `to_datetime` for pre-1678 dates.

---

## 12. Deferred or dropped

- **Role-typed entity overlap** — deferred. Do not build until D1 shows evidence, not structure, is
  the binding constraint.
- **Structured LLM judge redesign** — deferred, and still unmeasured (D2 first).
- **TRIFECTA layering** (`~/develop/trifecta-annotation`) — reduced to its *evaluation discipline*
  only: precision-first, soft containment, quota gold, no auto-relabel. The pipeline architecture
  does not transfer; a classification task on single documents is not a matching task across two
  document sets.
- **Entity-noise simulation sweep** — dropped. Measure real entity recall via D1 instead.
- **"Drop the paragraph axis"** — retracted. The −4.16 gain was measured for paragraphs as *match
  candidates*; they are the natural *cut-point* unit.

---

## 13. Constraints and decisions

- ~78% coverage at ~99% precision is probably sufficient for the research question.
- The period will extend beyond 1626–1630, but not to the whole corpus.
- Expert review time is limited (tens of hours). Reserve it for **adjudication, not diagnosis** —
  the diagnostics are designed to spend compute instead.
- LLM budget: prefer a single structured call per decision unit.
- Enriched entity lists provide set-level gold ("what, not where") for the exact period at zero cost.
  Not usable for span-boundary evaluation.

## 14. Discipline going forward

- Never produce algorithm-dependent gold again — boundaries, not verdicts.
- Define the metric before the method.
- Precision first, with coverage reported; abstention is a valid output.
- Prefer deriving inventories from trusted anchors over hand-writing taxonomies.
- A signal's hit rate measured in isolation (directly at gold positions) is not
  its effect once it passes through the real pipeline — check both (§4.1).

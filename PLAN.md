# republic_ner_matching — implementation plan

<!-- doc-status: active -->
<!-- canonical-goal -->

> **Separate the resolutions.** For most of the ~19,120 enriched resolutions (1626-1630 editorial
> summaries), determine where that resolution begins and ends in the HTR transcription, expressed
> in session-relative archival terms — a verified archival address, not a possibly-drifted session
> number. Publish it as a reviewable table where every placement carries a confidence tier and its
> evidence, and where the *unplaced* parts are characterised rather than merely absent.
>
> Framing: patchy alignment, after ancient DNA. Damaged, fragmented aDNA matched against a known
> reference yields patchy alignment — that is the expected shape of a good result, not a failure.
> A confidently placed resolution is an aligned read; several resolutions sharing one paragraph is
> a multi-mapping read (filter, don't count as progress); an unplaced resolution is an uncovered
> region, and uncovered regions are informative — they must be classified, not merely omitted.
>
> **Acceptance criteria** (`docs/DECISIONS.md`): a resolution is **separated** iff its start
> paragraph is shared with no other resolution on its date and its extent is ≤ 3 paragraphs.
> The paragraph-level ceiling is **11,644 / 19,120 = 60.9%** (pigeonhole: 535 days have no HTR),
> not physics. Targets stated against that ceiling, never 100%.
>
> | criterion | baseline (2026-09-29) | status |
> |-----------|----------------------|--------|
> | Global primary: ≥ 50% of ceiling | 8,015 = 68.8% | **MET** |
> | Global stretch: ≥ 75% of ceiling | 8,015 = 68.8% | not met; gap 718 |
> | Global spans: ≥ 6 spans / ≥ 180 days | 4 spans / 177 days | not met; tracked, non-blocking |
> | Local: ≥ 50% of inventory ceiling | 3185–3189 all clear | **MET** |

## Status summary
<!-- doc-status: active -->

**Closed (complete):**
- Segmentation-transfer S0–S6: S6c counts-constrained gap DP, `position_scores` tuning exhausted
- S4a–e: Session-date ledger (4,916 inventory-date mappings)
- Metrics tiers O/P/D/V: Separation, bottleneck, drift, nihil-actum diagnostics

**Active tracks (use `svz.py review` for decisions):**
1. **`inventory-stream-collision-avoidance`** ([plans/COLLISION_AVOIDANCE_TRACK.md](plans/COLLISION_AVOIDANCE_TRACK.md))
   - Step 1 PASS: Session landmarks 86% localizable, order-preserving
   - Step 2 NEGATIVE: Length prior doesn't help
   - Step 3 NEGATIVE: Entity-mention order aligner underperforms interpolation
   - Step 6 GATE: Main corpus already fully mapped; unplaced mass in secret series (4562/4861)

2. **`tfidf-embeddings-wiring`** ([plans/TFIDF_EMBEDDINGS_TRACK.md](plans/TFIDF_EMBEDDINGS_TRACK.md))
   - TF-IDF similarity AUC 0.893 (paragraph granularity)
   - Collapsed `position_scores` wiring NEGATIVE; mechanism diagnosed (bonus tracks the absolute similarity level, not the margin)
   - Per-rank `rank_scores` wiring measured corpus-wide, no gold: NEGATIVE everywhere (best −25), **POSITIVE gated to weak_separation days (+315, 8,315 → 8,630)**
   - Gated gain scored for correctness on gold (2026-09-29): **real** — exact start agreement 0.3218 → 0.4253 on weak days, 18 of 22 adjudicable moved rows go toward gold
   - **But the gate is wrong**: ungated scores *better* on correctness (exact 0.5865 vs gated 0.5321), so the corpus-wide −25 `separated` is a coverage loss that is a correctness gain
   - **DECIDED (user, 2026-10-05): `separated` rules; the gold is too limited.** Where `label_separation` and gold start-paragraph correctness disagree, `separated` adjudicates. Gold stays a diagnostic — how mechanisms get understood and instruments calibrated — but does not decide corpus-wide placement questions. Demonstrated limit: the widened existence check across all 74 gold + hard-period days could score **12 paragraphs total**. **Applies here: keep the gated wiring (+315 `separated`)**, accepting the correctness loss (exact 0.5865 ungated vs 0.5321 gated). See `docs/DECISIONS.md` 2026-10-05.
   - **One standing guard:** `separated` is gameable — Step 2 found a trivial uniform spread beats gold's own annotations on it — so `separated` counts stay reported against the uniform null (`uniform_start_paragraphs`), never absolute. The ruling settles which metric adjudicates a disagreement; it does not turn an unbeaten-by-uniform gain into a win.
   - **Unblocked the three dependents, at very different costs (measured 2026-10-05):** track 2's gate (applies directly); the secret-hijack withdrawal (**≤6 of 8,084 separated, 0.07% — effectively free**); dedup (**428 separated exposed, 5.3% — constrained, not free**). Details under tracks 4 and 5.

3. **`staged-anchor-consolidation`** ([plans/STAGED_ANCHOR_CONSOLIDATION.md](plans/STAGED_ANCHOR_CONSOLIDATION.md), opened 2026-09-30)
   - Execution design for `COLLISION_AVOIDANCE_TRACK`'s working hypothesis (2026-09-25), not a new framing
   - A clump is an **unresolved gap**, not a result — so no schema change, and gap-minimisation is not gameable
   - Objective: shrink gap mass via staged propagation (objective anchors → reconcile → subdivide → repeat); measure already exists (`s6b_known_point_ledger` gap-size distribution, baseline 947 gaps / 70.7% of unplaced work)
   - Measured: the DP consumes only ~4–7% of available anchors; groups B/C/D are **structurally invisible** to `align_session`'s `anchor_only_diagonal` gate, not merely down-weighted
   - One code change with reach: **partial abstention** in `segment_day` (today it never abstains, so it fabricates precision — `1630-02-22` emits 28 placements where 7 + 2 gaps is honest)
   - Step 1 DONE (2026-10-01): pinned-but-wrong population sized at 0.7% (8/1,123) confirmed
   - Step 2 DONE (2026-10-01): harvest char→paragraph join verified on 3 seed days; 93% of axis mismatches traced to harvest-side grouping defect, fix implemented
   - Step 3 DONE (2026-10-01): partial abstention in `segment_day` implemented; gate PASS both metrics — gap-mass 2 abstained gaps on 1630-02-22 (expected); gold correctness (re-measured live, first attempt read a stale cache — see `docs/DECISIONS.md`) exact-agreement 0.5431→0.6486, abstained population only 13.9% correct beforehand vs 54.3% baseline
   - Step 4 pre-check DONE (2026-10-02): Group B (`entity_surface_matches`, `fuzzy_surface_scan`) measured, not wired — attributable to a specific enriched resolution only 9.6% of the time via the existing overlap data, and on the 24.6% of scored cells where Group A has no anchor (the only population wiring B would actually change), exact agreement is 28.2%, well below baseline. Deferred; see `docs/DECISIONS.md` 2026-10-02.
   - Step 4 redirect DONE (2026-10-02): Group C measured as a hard anchor via position-based attribution — net negative (30.9% vs 47.9% baseline on the only population it would change), same shape as Group B; stays soft-only. The already-shipped TF-IDF diagonal relaxation (`semantic_weight=0.5`, 2026-09-29) was isolated: touches only 6/50 gold days, zero breaks, one distinctive win a content-blind control can't replicate (`1627-08-19`) — always by resolving a local near-tie inside a gap Group A already narrowed, never by opening new territory. A real text-ID-lookup bug in `s4_paragraph_axis_baseline.py` was found and fixed along the way (gold-day semantic similarity had been computed against placeholder strings; corpus-wide production was unaffected). Confirms the locality principle: weak channels are separation-*resolvers*, not separation-*detectors*. Step 4a/4b's staged-vs-combined framing has no remaining channel to meaningfully stage beyond Group A; closed. See `docs/DECISIONS.md` 2026-10-02.
   - Group C boundary-existence reframing DONE (2026-10-02), result **inconclusive, not negative**: measured directly on `floor > 1` gaps, but only 2 of 20 in-scope gaps in `boundary_gold_sample` are scoreable (8 paragraphs total) — too small to judge. (Superseded 2026-10-05: the widened re-run below shows the window, not the sample size, is the blocker.) Surfaced a consequential side finding: 9 of 20 (45%) have the live Group-A backbone anchor itself positioned *before* where gold says the gap's own content ends — the `1630-02-22` crowding pathology, now measured at scale rather than one hand-checked day. See `docs/DECISIONS.md` 2026-10-02.
   - User decision (2026-10-02): widen via the existing `boundary_gold_hard_period_sample` scaffold (severe-collapse/high-`|K_e−K_f|` days, built 2026-09-28, exactly the right population) — by **user annotation** through the existing UI, not new tooling. Merge adapter DONE (user, 2026-10-05): `merge_boundary_annotations.py` now takes `--sample`/`--annotations`, and all 5 prioritized `floor > 1` candidate days are merged with located cuts.
   - **Widened re-run DONE (2026-10-05) — sub-step CLOSED, and not for lack of data: the metric is structurally degenerate in `floor > 1` gaps.** `scripts/s6c_group_c_boundary_existence_check.py` now reads both samples (per-sample + combined; first consumer anywhere of the hard-period `date_start`/`date_end` and `no_htr_text` conventions). The original 50 days reproduce 2026-10-02 to the digit (20 in scope, 2 scoreable, lift 1.00x) — a regression check on the extension. The hard sample delivers the density it promised (**21 in-scope gaps from 24 days vs 20 from 50**) but only 2 are scoreable, at a base rate of **exactly 100%** (4/4 paragraphs are real boundaries). `floor > 1` means `gap_count > room`, so pigeonhole forces a boundary in nearly every paragraph: the window admits almost no negatives, lift is capped at `1/base_rate` ≈ 1.0, and a detector answering "boundary" everywhere would score 100% precision. **Do not annotate further hard-period days for this question** — the remaining 14 would add ~11 gaps at the same pinned ceiling. Supersedes option (a) of the 2026-10-02 entry. See `docs/DECISIONS.md` 2026-10-05.
   - Next (candidate, needs user sign-off before any code): re-aim the same phrase-hit existence question at **`floor == 1` gaps**, where `room ≥ gap_count` leaves spare continuation paragraphs, the base rate drops well below 100%, and lift is measurable — also where the locality principle predicts a weak channel pays (resolver of a near-tie inside an already-narrowed gap, not detector of a split). Carry the caveat: `segment_gap` does not abstain there, so the signal must *beat* today's placement, making it a tie-break comparison. `s6c_group_c_attribution_check` already scored that population on the *identity* question (30.9% vs 47.9%); the existence question has not been asked there. The alternative is to close the Group C channel entirely and redirect.
   - **Day selection for annotation (2026-10-02), checked against the live Group-A backbone so effort isn't wasted on days this question can't use:** of the 20 unannotated hard-period days, 8 have zero yield — `1627-10-11`/`1627-11-28`/`1628-10-14`/`1629-11-14` have no `floor > 1` gap at all, `1627-06-21`/`1629-06-19`/`1629-06-30`/`1629-08-25` are missing HTR or enriched data entirely. Of the remaining 12, prioritize these 5 (2 `floor>1` gaps each, `max_floor` 4-8, **all inventory 3187/3188 — not 4562, confirmed clear of the pathology below**): `1628-05-15`, `1629-02-02`, `1629-09-08`, `1629-09-22`, `1629-10-13`.
   - **Secondary list downgraded further (2026-10-02):** of the original 7 fallback days, 4 are inventory **4562** (`1626-12-16`, `1627-01-14`, `1628-12-15`, `1629-05-04`) — given a 2-for-2 hit rate below on inventory 4562 producing "one secret resolution, rest unannotatable" rather than genuine crowding, these are now higher-risk, not just lower-yield. Only `1629-08-04`, `1629-11-17`, `1630-04-30` (inventory 3188/3189) remain solid fallbacks if the top 5 aren't enough.
   - **Annotation finding, `1628-05-15` (2026-10-05):** user annotated resolutions 1-9 (cuts inserted), text then continues at resolution 16 — **1-based 10-15 are missing**. Probed per the upstream-first rule and confirmed absent, not mis-filed: none of the distinctive names from those six (Sir Thomas Lucas, Mourmont, Wollebrantsz/Tol, Wiggeringe) appear in the local paragraph axis for `session-3187-num-121` (9 paragraphs), in ES's own `paragraphs[].text` for that session, or anywhere in a 23-session window (`3187-num-110..132`). Upstream (stage 1-2) fault, same class as `1626-03-28`'s `#2-6` — left, per the stopping rule. **This day is still partially usable gold:** resolutions 1-9 and 16-18 have real text and real boundaries, unlike the three 4562 days which yield nothing.
   - **New recurring pathology found while annotating (2026-10-02), separate from the `1626-03-28` case above:** `1626-04-24` (`k_e=15`/`k_f=1`, inventory 4562) is the same shape — one genuine secret resolution present and complete (archive-confirmed, scan `NL_HANA_1_01_02_4562_0140`), the other 14 enriched resolutions have no corresponding text, all degenerately collapsed in production (`paragraph_start≈paragraph_end≈0`). `1626-07-17` (`k_e=28`, inventory 4562) is a related third shape: `k_f=0`, no resolved session at all — nothing to annotate. 2 of the original 5 hard-period days hit the first shape, 1 hits the second; only 2 of 5 (`1626-05-01`, `1626-05-29`) annotated normally. **Action for days like this:** no checkbox fits, place no markers, record in notes which resolutions are present/complete vs. absent, and (if inventory 4562) whether the present one is archive-confirmed secret.

## Strategy (user, 2026-10-06) and the model it required

The user's stated working order, to which the tracks below are subordinate:

1. **Find the good sequence.** 2. **Identify the gaps in it.** 3. **Resolve the biggest gaps first**,
by (a) placing additional anchors and (b) shifting anchors — learning from successes and failures,
since only a limited number of things can be wrong. 4. **Iterate**, with an explicit way to say
*enough* or *methods exhausted*. Hand editing is reserved for genuinely unclear, unsolvable cases.

**`running_axis/` — DONE 2026-10-06** (new package, 95 tests, `pyproject.toml` registered; dataset
`running_axis_snapshot`; `docs/DECISIONS.md` 2026-10-06). Built because steps 3–4 are *mutations* that
must preserve monotonicity, and because recomputing the sequence from dispersed sources per script is
what let **three gap counts** circulate for one ledger (120 from the one-month run on disk, 947 cited
in this file from an earlier full run, and a third fabricated set, now withdrawn). One loaded object,
every window a *view* of it, so a month and a corpus figure cannot contradict.

- **The `no_axis` defect, and the free win inside it.** `s6b_known_point_ledger` groups the axis by
  each paragraph's `date` field and `continue`s past any date with none, filing them under a
  fabricated inventory named `no_axis` (`scripts/s6b_known_point_ledger.py:412`) — although
  `axis_for_date` exists to prefer the concordance-resolved session and is simply never called.
  Decomposed and machine-checked: **1,594 enriched dates = 1,059 labelled + 66
  dropped_by_label_grouping + 125 nihil_actum + 344 no_session**; **19,120 resolutions = 13,530 + 983
  + 125 + 4,482**. The **66 dates / 983 resolutions already carry a resolved session** and are lost
  only to the grouping rule — a defect in the ledger's *measurement*, since production does call
  `axis_for_date`. October 1628 decomposes 31 = 15 + 3 + 2 + 11 instead of "15 with an axis, 16
  without".
- **Ambiguous counts are now inexpressible, not merely discouraged.** `running_axis/tally.py` binds
  every count to a registered population and a window; cross-population subtraction, overlapping-window
  addition, cross-unit ratios and empty denominators all raise. The four date counts that read as a
  contradiction were each correct over a different population: **1,240** axis date labels, **1,594**
  enriched dates, **1,059** both, **535** enriched without a label, **181** axis labels that are not
  enriched dates (180 past the edition's 1630-05-14 end while the axis runs to 1630-12-31).
- **Gap accounting and brackets DONE 2026-10-06** (`running_axis/chain.py`, 19 tests). Both
  structures, kept distinct because they are easy to conflate: **gaps** are resolution-level within a
  day (`s6b_known_point_ledger`), **brackets** are session-level within an inventory
  (`session_offset_eval`). The model **reproduces the ledger field-for-field** from its own chains —
  120 gaps, determined 70 / nearly_determined 36 / open 14, resolutions 0 / 49 / 61, chars 168,197 /
  92,920 / 51,796, `settled_share_by_gap` 0.8833 and `open_share_by_resolution` 0.5545, all twelve
  fields — and reproduces `session_offset_eval` on sittings (344, k_e 4,482) and determined pairings
  (3 sittings, k_e 40). **One documented difference:** unclaimed sessions are 263 here against its 79,
  which is exactly its 79 + the 184 sessions beyond the enriched edition's 1630-05-14 end that it
  drops via `restrict_to_enriched_span` and this model deliberately keeps visible. Production anchors
  are *not* re-derived — the ledger computes those live through `align_session`, and a second
  implementation of the thing whose numbers we want to check would be worthless as a check.

### What `missing_htr` actually means (2026-10-06)

Definition (`scripts/s4_day_status_resolution.py`): a ledger `N` row with no same-inventory HTR session
within ±14 days. So it means *no session in what upstream delivered*, *not* "no text exists".

- **Our own manipulations are cleared.** The axis carries exactly what `resolutions_flat` holds
  in-window — session numbers match per inventory (184/184, 200/200, 275/275, 266/266, 289/289), the
  136 axis-absent numbers are absent upstream too, and 4562's 102-vs-297 gap is entirely its date range
  (upstream 1615–1924; of its 288 dates exactly 98 fall in 1626–1630 and **all 98 are on the axis**).
- **No surplus of parsed HTR:** 344 unresolved sittings against **79 unclaimed sessions**
  (`session_offset_eval`), so reassignment cannot absorb them.
- **An orphan-page hypothesis was raised and REFUTED.** 420 scans appeared to sit between consecutive
  resolved sessions, 86 of them in 37 gaps bracketing a `missing_htr` date. Queried against
  `session_text_regions-2026-03-25`: all 86 carry text (1,216 regions, 8,720 lines) and **all 86 belong
  to the left bracketing session**. `metadata.page_ids` names only the page a resolution *starts* on,
  so session extents derived from resolutions are systematically too narrow. The derived "~311
  recoverable resolutions" is withdrawn.
- **A second hypothesis — under-transcription in our snapshot — was also tested and REFUTED, same
  day.** `session-3185-num-23` showed ES `para` text at 43,770 characters against our axis's 13,122
  (3.3x, same content: 54.5% of our distinct 6+ letter tokens appear in it), which looked like a lead.
  Generalised over **all 1,316 sessions** by server-side aggregation on `stats.chars`: **median ratio
  0.99, total 1.07** (per inventory 0.95-1.16), so the two snapshots carry the same resolution text
  overall and that session was an outlier, not a pattern. Per-session spread is nonetheless wide (p10
  0.42, p75 1.13, p90 2.97; 379 sessions where ES has less, 522 where it has more) while totals match
  — a signature that would fit text moving between adjacent sessions, but **that was tested too and
  does not hold**: correlation of ratio(N) with ratio(N+1) is **+0.005**, where displacement into a
  neighbour would read negative, and pooling adjacent pairs narrows the spread about as much as
  averaging any two noisy measurements. The variance is real and unexplained; no mechanism is claimed.
- **A third hypothesis — that the unplaced mass is the secret series — was also raised and REFUTED,
  and it names a trap worth remembering.** Grouping the 344 `no_session` dates by the concordance's
  `inventory_id` returns 4861: 191 dates / 2,387 resolutions and 4562: 153 / 2,095, zero in
  3185–3189. That field descends from `session_date_status_1626_1630`, which holds **3 candidate
  inventories per date** (4,916 rows for 1,594 dates) — `s6b_known_point_ledger.inventory_of`
  already declines to use it for exactly this reason. The candidates are structurally *the year's
  main inventory plus 4562* (the main series is annual, 3185 = 1626 … 3189 = 1630, while 4562 spans
  the whole period), and for a `missing_htr` date the pick was never confirmed against HTR because
  there is no session to confirm it against. **It is a tautology: dates without HTR are attributed
  to the inventories without HTR.** `DateState.inventory` is now None unless a resolved session
  establishes it, and brackets carry `rests_on_candidate_inventory`.
- **Decomposed soundly via the XML secret flags and the ES resolutions index.** Of the 323
  XML-flagged secret dates, **264 are `labelled`** — placed, with HTR — so secrecy does not imply
  missing text. Setting them aside leaves 298 dates / 3,848 resolutions; queried against ES
  `full_resolutions` by `metadata.session_date`, 26 dates / 313 resolutions exist upstream and not
  here, 272 dates / 3,535 exist nowhere.

  | the 4,482 `missing_htr` resolutions | dates | resolutions | share |
  |---|---|---|---|
  | on XML-flagged secret dates | 46 | 634 | 14% |
  | in ES but absent here — **recoverable** | 26 | 313 | 7% |
  | absent from the HTR corpus altogether | 272 | 3,535 | 79% |

  **Then withdrawn too (user, 2026-10-06): `resolutions_flat` was built from the ES resolutions
  dump**, so ES is upstream of this corpus and holds no text it lacks — the 0.99 median character
  ratio had already said so. The 26 dates are a *date-attribution* question, not missing text.
- **Which turned out to be the live finding: the date headings were never ingested.** The axis
  descends from `resolutions_flat`, which carries resolution text; ES classes text regions and the
  headings live in `date`-class ones (`attendance` too). `session-3185-num-98` opens mid-attendance
  list on the axis, while ES holds `Heeren Grave, Rantwijck, De Bie, Halewijn, Mercurij den xxen.
  Maij 1626` for it. An earlier weekday test against the axis returned 23 of 24 "no signal" — read
  as a mute channel, actually un-imported evidence.
- **Re-run against ES `date` regions with predictions fixed first**
  (`scripts/h_weekday_date_attribution.py`): **H1 16, H0 1, H2 0**, 5 no signal, 1 undecidable.
  So for **16 of 24 contested dates — 207 resolutions — the enriched date is right and this
  corpus' corrected session date is wrong**; the text is here under another date. **H2
  (Julian/Gregorian) is refuted** — all three 10-day offsets came out H1, and the 10-day offset was
  the only reason to suspect it. Two method fixes, both from the user reading the manuscript: only
  a session's *first* heading dates it, and `Praeside et Praesentibus qui heri` names **yesterday**,
  so such headings shift one day forward — which is why `session-3185-num-16`, reading 20 January
  on the image, is correctly dated the 21st here.
- **Ingestion DONE 2026-10-06** (`session_region_text_1626_1630`): 3,763 `date`/`attendance`
  regions, 262k characters, **date regions for 1,275 of 1,316 sessions (96.9%)**.
- **But the corpus-wide check that ingestion enabled is CIRCULAR — do not cite its 610.**
  The heading's date equals ES's own uncorrected `session_date` 6 of 6 sampled, because **ES
  segmented the sessions using those headings**. Heading and ES are one witness. The same applies
  to the 16-of-24 H1 result above: those dates were *selected* by "ES dates a session here", so a
  readable heading had to agree. One witness counted sixteen times.
- **The arbiter is a human reading the page** — `manuscript_date_verdicts`, 7 readings over 6
  sessions. **The recorded date agrees with the page in 1 of 7; the enriched date in 3 of 6.**
  Offsets: 0, +3, +4, +10, +15, +20, −10. Four error sources all observed: our correction, HTR in
  both directions (a stroke added *and* dropped), the clerk (`martis den xiijen` where the 13th was
  a Monday — so **weekday beats numeral**), and a calendar-style reading that the user **withdrew**
  (this corpus' dates are always modern style, so the two 10-day cases are plain errors of opposite
  sign — suggestive of a mis-applied conversion, hypothesis only).
- **Two mechanisms confirmed on paper:** `qui heri` names *yesterday*, so such headings shift one
  day forward (41 sessions carry it); and `session-3185-num-72` holds 13, 14 **and** 15 April 1626
  — a multi-day block, i.e. **sessions as anchors, not containers, read off the manuscript**. 146
  sessions show several distinct day headings.
- **A non-circular rate does exist**, from the heading's *internal* coherence (weekday matching
  its own numeral is a property of the page, not of ES's date field): of **685** sessions with a
  readable, internally consistent heading, the recorded date **disagrees in 525 (76.6%)**, agrees
  in 160. Offsets cluster small and negative (−1: 49, −2: 43, −5: 55, −6: 35), tail to −18. The
  user's 7 image reads agreed in 1 of 7, same magnitude. **Gated question ANSWERED (user,
  2026-10-06): the date correction is REPUBLIC heuristics, not an external authority** — so the
  disagreement is a heuristic against the manuscript, and the heuristic is the suspect party.
  **And the calendar authority is the XML**: every day recorded, non-session days as `nihil
  actum`, the XML baseline normative for it. So **the enriched date is normative and the recorded
  HTR session date is heuristic** — which is the direction the 16-of-24 headings pointed, a result
  still circular as a *rate* but now independently supported in direction.
- **`postprandium` is in the DTD and we discard it** (user, 2026-10-06; XML now registered as
  `enriched_resolutions_xml_source`). `Stgen.dtd` declares
  `zittingsdag ((presentielijst|postprandium?), resolutie*, noot*)+` — the afternoon sitting is a
  first-class element and the group repeats, so **several sittings per day are explicitly
  modelled**. **109 of 1,595 day files carry it**, and `enriched_resolutions_1626_1630` keeps no
  sitting field at all, so those days were flattened. Of the 109: only 3 have >1 axis session, 67
  have exactly 1, 39 have none (32 in `no_session`). Independent corroboration of Track S from the
  normative source. Only 3 of the 73 multi-session dates are postprandium days, so afternoon
  sittings are not that multiplicity's main source.
  **Not to be chased** (user, 2026-10-06): retrieving the sitting boundaries is likely hard and
  afternoon sittings explain only 3 of the 73 multi-session dates, so it stays a *recording* —
  `postprandium_days`, a 109-date lookup to consult when a day looks structurally confused before
  reaching for a more elaborate explanation.
### Track P's editorial ceiling is ~98%, not a reframing (user, 2026-10-06)

The edition follows resolution order but, per its own `verantwoording`, **sometimes lumps
same-subject resolutions on one day, with no listing of which**. Track P asks where enriched
resolution *i* begins in the HTR, which presumes the editorial and scribal units are the same kind
of object; for a lumped resolution they are not, since it has no single scribal start point.

**Magnitude, from the editor: lumping was never observed in the resolutions he has read, so
"pretty seldom" — a ceiling around 98%, not 100%.** That is an informed estimate from cases seen,
not a measurement, and the lumping stays unidentifiable from the edition side. But at ~2% it is a
footnote rather than a reframing, and the important consequence runs the other way: **the 4,516
resolutions sharing a start paragraph are overwhelmingly placement failures, not editorial
composites, so Track P's premise holds.** Report future Track P results against ~98% rather than
100%, and do not treat the collision mass as substantially editorial.

### No resolution register is missing (2026-10-06)

REPUBLIC's `data/inventories/inventory_metadata.json`: exactly **8 inventories overlap
1626–1630** — the five annual `ordinaris` registers 3185–3189, the `secreet` register 4562
(1615-12-01..1634-12-31), and two `index` volumes. **All six resolution registers are in this
corpus.** So the 3,535 unplaced resolutions with nothing in ES are absent because the text is not
in the digitised registers, not because a register was overlooked — the last structural
explanation, now closed. Also: **4861 is an `index`, not resolutions** (`resolution_type:
speciaal`, 1626–1661), so it never held resolutions to extract, and the 2,387 the candidate column
attributed to it were attributed to a finding aid.

- **Next, not done:** applying any date verdict is a day-status ledger change nobody has designed;
  the 76.6% figure still has no reproducible artifact (`h_session_date_vs_heading.py` holds the
  circular version plus a year-override and month-fallback bug that fabricate dates); and the
  secret-flag extraction has no committed script (`created_by_script: ""`), so it is not
  reproducible.

## Main line (user, 2026-10-05): the two remaining problems are both anchor operations

The user named the two core problems and their answers: **(1) we do not know how to divide or join
paragraphs → place anchors**; **(2) the distribution of resolutions/paragraphs over sessions is
unresolved → shift anchors**. Both are changes to *what an anchor is allowed to be* — finer (inside a
paragraph) and freer (outside its date's own session). They are coupled: several shared-session splits
are themselves sub-paragraph, so **P before S**.

### Track P — "placing anchors": sub-paragraph division

Sizing (measured 2026-10-05): sub-paragraph collision is the project's **largest single loss class** —
**4,516 of 13,374 placed resolutions (34%)** share a start paragraph, against 774 lost to extent, and
it concentrates into just **1,597 paragraphs**. Nothing needs re-harvesting: all **249,056**
`s6b_anchor_harvest` anchors already carry `char_position` (verified on the day's concatenated char
axis, max-position/day-chars ratio 0.99) and the placement model discards the offsets. Group A, which
is all the DP really consumes, is 5,375 of those — about 2%.

- **Granularity rule (user, 2026-10-05), and it is what makes this tractable:** *within text*, anchor
  placement may be **character-wise**, because the paragraph no longer holds as a container — a
  resolution boundary inside a paragraph means that paragraph was never a real unit. For anchor
  **shifting** (track S) everything is **translated back to paragraphs**, over the *new* paragraphs that
  P's cuts create. So the char axis is an **intermediate** representation; the final address stays
  paragraph-based, which preserves the canonical goal's verified archival address and every downstream
  consumer.
- **P0 — GATE, still a canonical-goal decision, but a smaller one than first drafted.** Because a char
  cut **materialises as a new paragraph boundary**, `separated` does **not** need rekeying to
  `(paragraph, char_offset)` — `label_separation`'s definition is untouched and simply runs over a finer,
  corrected paragraph stream. (An earlier draft of this step proposed rekeying the metric; the user's
  re-paragraphing architecture is better and supersedes it, because it leaves the criterion the
  `separated` ruling adjudicates on exactly as it is.) What still needs explicit sign-off:
  - **The ceiling rises.** The **11,644 paragraph-level ceiling** is a pigeonhole over today's
    paragraphs; more paragraphs means more capacity, so today's 8,084 = 68.8% "MET" becomes a smaller
    fraction of a larger denominator. Real coverage rises while the headline number falls. That is the
    right trade but it must be chosen, not discovered.
  - **Re-paragraphing scale (measured):** 1,597 paragraphs split into 4,516 pieces — **+2,919
    paragraphs, +13.6% of the 21,519-paragraph axis**, touching 7.4% of it. Median 2 pieces per split
    paragraph, p90 5.
  - **It cuts both ways, and the cost is measured:** re-paragraphing unlocks up to 4,516
    collision-blocked resolutions, but **809 currently-separated resolutions (10%) overlap a
    to-be-split paragraph and 273 of them (3.4% of all separated) would then exceed `extent <= 3`** —
    a resolution spanning a paragraph that becomes 3 pieces grows by 2. Roughly 16:1 in favour, but not
    free, and `MAX_EXTENT_PARAGRAPHS = 3` was calibrated on *old* paragraphs, so the threshold's meaning
    shifts in exactly those 7.4% and may need revisiting as part of this gate.
  - **Migration:** every stored `paragraph_start_index` becomes stream-version dependent, so the axis
    needs a versioned successor with provenance rather than an in-place edit. One thing gets *simpler*:
    gold's `mid_paragraph` cuts become ordinary `paragraph_boundary` cuts in the new stream.
- **P1 — free pre-check, no annotation, do first.** Calibrate Group C interior candidates against the
  **81 gold `mid_paragraph` opening cuts across 33 days** already in `boundary_gold_sample` (65) and
  `boundary_gold_hard_period_sample` (9, plus 7 `start` slots) — a real sample, unlike the n=8/n=12
  that defeated this session's other measurements. Score against a **uniform-random-position null
  inside the same paragraph**; a candidate generator that does not beat that null is worthless however
  available it is. Availability is already measured: Group C gives ≥1 interior candidate on 78% of the
  1,597 colliding paragraphs and enough for every needed cut on **62%**, with the median case exactly
  one candidate for one needed cut. Group B reaches 98%/94% but at median 9 candidates per cut, so it
  is recall without precision. **Treat as channel calibration, not a track target metric — no
  tolerance-threshold F1, per the standing ban.** If P1 fails, placing anchors is available but not
  accurate, and the track stops here rather than proceeding on availability alone.
  - **DONE (2026-10-05) — PASS, and it hands back a calibration decision rather than just a verdict.**
    `scripts/s6c_group_c_interior_offset_calibration.py` (diagnostic only, no dataset write). Population
    as costed: 81 `mid_paragraph` opening slots / 33 days, of which **8 carry `char_offset == 0`** — a
    mid-paragraph marker on the paragraph's first character, i.e. a paragraph boundary in the other
    unit's terms with no interior position to find — leaving **73 interior cuts in 63 host paragraphs**
    (54 host one cut, 8 two, 1 three). The 7 `mid_paragraph`/`start` slots are in the *original* sample,
    not the hard-period one (65 cut + 7 start vs 9 cut); the 81/33 totals hold. Coordinate assumption
    verified, not assumed: the live `axis_for_date` stream is text-identical to
    `boundary_gold_paragraph_axis` on 30/30 days that have gold-axis records (the 3 hard-period days
    have none), which also regression-checks what `s6c_group_c_boundary_existence_check.py` assumes
    silently. Nulls are **exact, closed-form over the paragraph's interior positions** — no Monte Carlo,
    no seed — and **count-matched**, because nearest-of-9 beats nearest-of-1 for free and that is
    precisely the Group B pathology the null has to neutralise.
    - **The candidate *set* carries the cut.** Nearest-candidate displacement **120.4 chars vs a
      count-matched null of 246.7 (ratio 0.49)**, beating its own null on **47 of 57** cuts
      (sign test p < 0.0001), median 40 chars, **p25 = 1 char, exact on 13/57**. Monotone one-to-one
      assignment (so a multi-cut paragraph cannot score by snapping every cut to one candidate) agrees:
      **0.45**, 39/47, p < 0.0001.
    - **The channel's own ranking cannot find it, and this is the operative finding.** Picking the
      highest-similarity candidate — what production would do, with no gold to choose by — lands
      **351.7 vs 448.7 (ratio 0.78)**, median 209 chars off, exact on only 3/57. **Significance is
      marginal, not established:** per cut that is 38/57, p = 0.0082, but the 73 cuts come from 33 days
      (one day supplies 7, one paragraph hosts 3), and clustered by day it is **18/27 days, p = 0.061**,
      with a day-level bootstrap ratio CI of **[0.61, 0.96]** — direction holds, the conventional line
      does not. Quote the clustered figure. `nearest` is unaffected by clustering (21/27, p = 0.0030,
      CI [0.32, 0.68]), as is `assignment` (22/27, p = 0.0008). The whole nearest↔ranked gap is
      selection: the ranking picks its own closest-to-gold candidate just **33/57** times. **Locality
      principle again, now measured on offsets:** Group C is a cut *resolver* inside an
      already-narrowed window, never a cut *selector* on its own.
    - **First-pass calibration read (SUPERSEDED, kept because the numbers stand):** the channel as
      defined fails its usable facet outright (ranked ratio **1.01**, 39/69, p = 0.168 — indistinguishable
      from a random position) because `build_combined_c_searcher` takes `s2_anchor_phrase_inventory`'s
      top 20 unfiltered, so "is"/"synde"/"ontfangen"/"opt" are live members; a ≥3-word restriction makes
      it pass (0.78) at a cost of availability 94.5% → 78.1% and median 4 → 2 candidates per cut. **But
      ≥3 words is the wrong fix** — `de heeren van` is three words and sails through it. See below.
    - **ROOT CAUSE (user-led diagnosis, 2026-10-05): the Group C inventory was never a formula
      inventory, and it is fit to the wrong population.** It was built by n-gram frequency *over* known
      openings (`s2` top-20 n-grams, `s4`'s 271 count-ranked candidates) with **no background frequency
      ever consulted**, so it conflates three kinds of string: real formulas, truncated prefixes of real
      formulas, and free prefixes that formulas and ordinary prose share. Frequency cannot separate them —
      `in deliberatie geleyt synde,` (a genuine formula, gold-confirmed) has count 5 while `de heeren van`
      (never an opening formula — user, categorical) has count 10. Opening-rate against the 12,811
      `para_index == 0` openings flags the junk correctly (`de heeren van` 0.008, bottom of 229) but
      **cannot be used as a threshold**: it scores `in deliberatie geleyt synde,` at 0.059, because that
      formula mostly opens resolutions *mid-paragraph* and the `para_index == 0` corpus is built from the
      same under-segmented stream Track P exists to fix. The denominator is contaminated by the target.
    - **The decisive measurement — the inventory is fit to paragraph-initial openings, not to Track P's
      population.** Re-reading `s4_opening_phrase_cut_evaluation_full` (360 gold cuts, built earlier in
      this repo and never used this way): the fixed-phrase inventory covers **85.4% of
      `paragraph_boundary` cuts but only 61.2% of `mid_paragraph` cuts**. The uncovered mid-paragraph
      openings are overwhelmingly **one productive participial construction** — `Synde`/`Syn` + participle
      (+ `ter Vergaderinge`) + object: *Synde gecommuniceert seeckere missive…*, *Synde gerapporteert byden
      heer President…*, *Syn wederom ter Vergaderinge gecompareert…*, *Gelesen synde de requeste van…*,
      *Nochmael geresumeert synde t'versouck…*. A frame head covers **35.8% of mid_paragraph cuts vs
      16.6% of paragraph_boundary cuts**, and phrase-or-frame together reach 74.6% / 88.3%. This is why
      the bare stem `synde` (count 740) is in the inventory at all: the frequency list captured the
      *stem of a productive frame* instead of the frame. Openings HTR lumped into a paragraph are
      **linguistically different** from paragraph-initial ones, and the inventory was derived from
      tier-1 anchored resolutions, which are overwhelmingly paragraph-initial.
    - **Checked against baseline-identified resolutions, with the user's own caveat confirmed
      quantitatively (2026-10-05): the baseline under-scores exactly the formulas that matter, and the
      inversion is the signal.** Per-frame share of the 13,374 production-placed openings vs the 67 gold
      `mid_paragraph` openings: participial `Synde`/`Syn` + participle **12.5% → 28.4% (ratio 2.27)**,
      inverted `<participle> synde` **4.7% → 13.4% (2.88)**, `ter vergaderinge gecompareert` **2.4% →
      6.0% (2.46)**; against `ontfangen` (missive intake) **17.2% → 3.0% (0.17)**, `is/synde gelesen`
      **12.2% → 4.5% (0.37)**, `opt/opde versouck|requeste` **10.6% → 3.0% (0.28)**, `is goetgevonden`
      (decision) **4.4% → 1.5% (0.34)**. The three under-detected frames are **48% of gold mid-paragraph
      openings but 19.6% of baseline**; the four well-covered ones are **44% of baseline but 12% of gold
      mid-paragraph**. The pipeline finds precisely the formulas it holds phrases for. **Consequence for
      method: baseline coverage is never evidence of a formula's weight** — it measures what is already
      visible, so a formula scoring low there is a recovery target, not a weak candidate. Same selection
      bias as the `para_index == 0` contamination above, one level further downstream. Caveat on the
      frames themselves: **40.3% of gold mid-paragraph openings are still unclassified** by these 7
      patterns, so the early-period inventory is described, not complete.
    - **Division of labour between the two available sources (user, 2026-10-05).** REPUBLIC's
      `republic/model/resolution_phrase_model.py` (`republicgit` @ `25924b93`, 2026-06-08) supplies what
      ours lacks: a **structural typology** — `proposition_opening_phrases` (92 frames) vs
      `decision_phrases` vs `proposition_closing_phrases` vs `resolution_link_phrases` — plus a curated
      per-phrase `max_start_offset`, which *is* the "is this an opening" discriminator. The typology is
      structural enough to transfer across periods even where the surface forms do not. What it lacks is
      this period: **41 of the 92 are out-of-period** (printed era, 1637+) and the 51 nominally covering
      1626–1630 are in printed orthography (`Opde Requeste van`, `Is ter Vergaderinge gerepresenteert`)
      against our HTR's `opt versouck van` / `is gelesen de reqte.` / `ontfangen een missiue van`. It is
      weak on the actual early-17th-century openings, and carries few samples of them. Our empirical
      n-grams are the inverse: real surface forms, no notion of what is a formula. **So: REPUBLIC for
      structure and class, our own material for early-period realisation.** Independent validation that
      this works: `in deliberatie geleyt synde,` — the formula our statistics could not rescue — is
      sanctioned by REPUBLIC as `Wederom in deliberatie geleijt zijnde`, a 1576–1630 frame.
    - **Two structural rules stated by the user and confirmed corpus-wide:** intake-class formulas
      precede decision-class ones — **97.0%** (3,529 of 3,637 paragraphs containing both) — and a
      decision formula opens a resolution only when no intake formula is available — **96.7%** (1,097 of
      1,134 decision-initial openings have no intake formula anywhere in the paragraph). Inventory splits
      147 intake / 24 decision / 58 unclassified under a crude stem test; the 58 mixes genuine
      non-formulas to purge (`de heeren van`, `de heer president`, bare `is`/`synde`/`opt`) with real
      formulas the stems missed (`is ter vergaderinge gecompareert`, `opte requeste van`, `noch ontfangen
      een missive`), so the partition needs the user's vocabulary, not a statistic.
    - **The worked example resolves under typing + ordering with no tuning.** `1629-09-22` paragraph 4,
      gold cut at offset 1639, four candidates: `2888 "de heeren van"` purged (attaches to no sanctioned
      frame); `1200`/`1669 "is goetgevonden ende verstaen"` are decision-class and `1669` is suppressed
      because an intake formula at `1640` precedes it; `1640 "in deliberatie geleyt synde,"` is intake and
      wins — **1 character from gold**. The similarity ranking picked `2888` (sim 1.000, a short generic
      phrase matching exactly) and was **1,249 chars wrong**: similarity rewards exact matches on
      throwaway strings over approximate matches on real formulas. Separately measured and too weak to
      use: gold cuts preceded by a clause terminator 72.6% vs 54.9% for decoy candidates.
    - **Verdict:** P1's *measurement* stands and its verdict holds in direction — the candidate set
      carries the cut, the channel's ranking cannot find it. But the gap is **not** a scoring problem to
      be closed by calibration weights; it is a **vocabulary and typing** problem upstream of scoring.
      Do not wire Group C offsets as a standalone cut placer, and do not adopt the ≥3-word filter.
    - **Rebuild DONE (2026-10-05, user sign-off given) — PASS, and the goal it was built for is met.**
      `scripts/s6c_group_c_typed_formula_channel.py`; REPUBLIC vocabulary copied with commit
      provenance to `scripts/_republic_resolution_phrase_vocab.py` (`3b46b43b`, byte-identical at the
      cited `25924b93`; `uv add` still blocked by REPUBLIC's `python <3.12` and `fuzzy-search ^2.6.0`
      pins). `s6c_group_c_interior_offset_calibration.py` now takes `--channels` and nothing else about
      it moved — same 73 interior cuts over 33 days, same coordinate check (30/30), same exact
      count-matched nulls, same day-clustering. **The legacy arms reproduce the recorded numbers to the
      digit** (`legacy` ranked 1.01; `legacy:3` nearest 0.49 / ranked 0.78 / assignment 0.45, selector
      33/57, availability 94.5% → 78.1%), which is the built-in proof that the harness did not move.
      - **`ranked` — the only facet that decides anything — goes from marginal to established:
        day-clustered 18/27 days p=0.061 (CI [0.623, 0.958]) → **26/32 days p=0.0003, ratio 0.62,
        CI [0.403, 0.822]**, median 209 → 71 chars, exact 3/57 → 16/70. And availability *rises*,
        78.1% → 95.9%, instead of being traded for precision. `nearest` 0.49 → **0.40** (29/32 days,
        p<0.0001, median **1 char**, exact 21/70), `assignment` 0.45 → **0.32**, selector agreement
        33/57 → 46/70.
      - **Ablations attribute it, and one is negative.** The typed candidate *set* under the **old**
        similarity ranking already reaches ranked 0.70 (27/32, p=0.0001, CI [0.549, 0.826]); the typed
        ranking adds 0.70 → 0.62 and selector 34/70 → 46/70. So both halves of the diagnosis were real:
        vocabulary *and* selection. The participial pattern buys availability and precision but not
        ratio (off: 83.6% availability, nearest median 16 chars, ranked unchanged at 0.63).
        **The intake-before-decision ordering rule contributes nothing measurable on this population** —
        ranked 0.62 and essentially the same CI with it switched off. It suppresses 65 of 71
        decision-class candidates and it is what makes the worked example resolve, but it is typing
        hygiene here, not a measured accuracy mechanism. Report it that way.
      - **Two bugs found by validating against the worked example rather than by the aggregate**, both
        now regression-documented in the module: an offset's class must be settled class-blind by
        whichever match realises *most* of a sanctioned formula **before** the ordering rule runs (else
        REPUBLIC's 2-token `Is goetgevonden`, labelled `proposition_opening` in its own list, types the
        4-token decision formula at `1629-09-22`:1669 as intake and shields it from suppression); and a
        participial match whose span crosses a clause terminator is not one construction
        (`gedelibereert synde, is goetgevonden ende verstaen` matched forward as `synde … goetgevonden`).
      - **Worked example resolves as predicted:** 16 raw matches → 7 offsets → 3 interior candidates;
        `de heeren van` purged at admission as `prefix_phrases: de Heeren` — REPUBLIC's own
        `person_name_prefix`, so the purge is categorical rather than thresholded, which is what the
        user asserted about that string; 1200/1669 typed decision and suppressed; pick = offset 1640,
        **1 char from gold**.
      - Caveat on the figures: run at `--reps 300`. `nearest` and `ranked` are unaffected — their
        nulls are closed-form — but the `assignment` null and every bootstrap CI are Monte Carlo at
        300 draws. The authoritative run is the default `--reps 10000`; advise it, don't run it.
      - Free parameters, three, none fitted to gold: `TOKEN_SIMILARITY` 0.72, `MAX_CANDIDATE_SKIP` 2,
        `MAX_LEAD_SKIP` 1, each with its motivating case in the module docstring.
      - **P3 is licensed on accuracy as well as availability.** Still *not* a standalone cut placer:
        `nearest` 0.40 remains well below `ranked` 0.62, so Group C stays a resolver inside an
        already-narrowed window, never a detector. P2's annotation target (offsets vs which formula
        opens each resolution) is **not a decision to spend attention on** — user, 2026-10-05: "if the
        results are equal I don't care". Annotate whichever field the existing UI makes cheapest.
- **P2 — bounded annotation, only if P1 passes.** `lumped_paragraph_gold_scaffold` holds **80 sampled
  candidates, all `review_status: pending`, zero `gold_offsets`** (out of 463 lumped specs identified,
  445 materialised) — the track was built and never started, which is why `lumped_paragraph_boundary_gold`
  is absent from disk. UI (`build_lumped_paragraph_annotation_ui.py`) and merge script already exist.
  This is the smallest annotation ask in the project and, unlike the hard-period sample, has a
  guaranteed use: it is the only way to tell whether a candidate offset is the *right* cut.
  - **Correction (2026-10-05): it *was* started — 13 of 80 on 2026-09-28 — and the tooling threw the
    work away.** `review_status: pending` in the scaffold is stale; the annotations live in
    `lumped_paragraph_gold_annotations.json`. Three defects, all now fixed, and together they explain
    why the pass stopped at 13:
    - **The UI hard-blocked the human's actual judgment.** `label.js` refused to save a `cuts` verdict
      whose marker count differed from `expected_cuts`, and `expected_cuts` is the concordance's
      `n_share` — *the very thing P3 is testing*. Annotating under that constraint would have made the
      gold agree with the hypothesis by construction (same contamination shape as `para_index == 0`).
      The human is the gold, the concordance is the prediction: any count now saves, disagreement is
      recorded as `expected_cuts_disagrees` and reported, never enforced. One such row already exists
      (`1627-09-20#p0`: concordance 2, human 1), and under the old rule the only way to save it was to
      mislabel it `no_cut`.
    - **The merge script was verdict-blind** (v1-era `skip`/`labelled`), so it raised on the first
      `no_cut` row and wrote nothing — i.e. it could never have produced gold from this UI. It now
      consumes the v2 vocabulary: `cuts`/`no_cut` → `record_type: gold`, `false_lump` → quarantine row
      in the same file, `skip` → counted only; and it collects every violation instead of aborting on
      the first.
    - **`|||START|||`, hand-invented by the annotator**, was silently baked into the gold text as
      literal characters, shifting every offset after it. It marked a real and distinct thing — the
      paragraph opens with an attendance list, resolution text starts at 38 — so it is now a
      first-class marker carried as `head_offset` (never a cut), with a UI button and a one-per-row
      guard. Unknown `|||...|||` markers are rejected rather than absorbed.
  - **Merge now runs: 12 gold, 1 skipped, of 80.** Both cuts land on sanctioned openings
    (`Is geaccordeert dat`, `Is mede gelesen een missiue`), head offset lands just past the attendance
    list. **One convention still unsettled:** `1629-11-09#p0`'s cut sits on the space *before* the
    opening word, not on its first character. Left faithful to the annotator, but a systematic ±1 would
    add noise to any exact-match figure against Group C — settle before the remaining 67.
  - **The 13 are a clean prefix of the shuffled sample, so they estimate the population: 10 of 12
    scored rows are `no_cut`** — 0.833, CP95 [0.516, 0.979]. Read it precisely: this is **precision of
    the scaffold's `n_share>=2` selector, not evidence about mid-paragraph cuts**, which P1 found
    plentiful (73 interior cuts over 33 days, coordinate-checked). The consequence is for the ask, not
    the phenomenon: finishing all 80 projects to **~13 cut-bearing gold rows, CP95 [2, 39]** — thin for
    scoring P3, and the other ~55 rows measure the concordance's over-counting instead. Decision for
    the user before spending the remaining 67: finish as scoped and accept a thin cut-bearing yield, or
    re-sample the scaffold from P1's typed-channel interior-cut population, where cuts are known dense.
  - **User decision (2026-10-06): stop paying for more hand gold; prefer a gold set from proven pairs.**
    Correct call — the 13-row prefix already shows the yield is thin relative to the labor.
  - **Checked and withdrawn (2026-10-06): Group A anchor-collision rows are NOT proven interior cuts.**
    First pass proposed treating `s6b_anchor_harvest`'s 1,098 `tier1_entity_nw` positions carrying 2+
    distinct `enriched_index` values as 1,689 proven cut positions — wrong on inspection.
    `tier1_points` (`scripts/s6b_known_point_ledger.py`) sets `char_position =
    flat_id_char_starts[row.flat_id]`, the start of the **flat resolution's paragraph**, not a
    per-mention offset. Two enriched indices sharing one `char_position` means two enriched
    resolutions matched the *same flat paragraph* — i.e. it just re-states the already-known collision
    count (the 1,597-colliding-paragraphs fact P1's own docstring already reports), with every
    "colliding" row pinned to the identical offset. Zero positional information about where inside the
    paragraph a true split falls. Do not build gold from this; the idea was right, the data source was
    wrong.
  - **What already exists and matches the ask: `synthetic_boundary_*` (docs/steps/
    STEP_SYNTHETIC_BOUNDARY_ENCODER.md).** Pairs of consecutive, independently-`separated`-confirmed
    resolutions on the same day, HTR-concatenated with no separator — the true boundary is the exact
    character length of the first segment, known by construction, zero annotation cost. This *is* "a
    gold set from proven pairs": each resolution's separateness is the concordance's own
    label_separation() finding, not a human call, and the boundary follows deterministically.
    `synthetic_boundary_folds` already holds **2,041 rows** (vs lumped's 80, ~13 cut-bearing) at zero
    further labor. Caveat already recorded there, and it is the real cost of this route: transfer to
    actual lumped paragraphs tops out at F1@50 = 0.259 (`GloBERTise`, docs/
    SYNTHETIC_BOUNDARY_GOLD50_TRANSFER.md) — concatenation-of-separates is an easier, OOD distribution
    relative to a genuinely lumped HTR paragraph (shared seam vocabulary, no hard break). Proven and
    plentiful, but not a free proxy for the harder real phenomenon; P2's thin human sample is still the
    only *in-distribution* check available, just not worth extending further by hand.
  - **Next, not yet done:** redirect P3's offset-carrying test to score against `synthetic_boundary_*`
    corpus-wide (2,041 rows, proven) as the primary gold, keeping the 12-row lumped `no_cut`/`cuts`
    set as the in-distribution diagnostic check rather than the target to extend. P2 is closed at
    12 gold / 80, not continued to 80.
- **P3 — carry the offset through** `build_anchor_backbone`/`segment_gap` so one paragraph can host
  several resolution starts at distinct offsets. Scored on the rekeyed `separated` corpus-wide against
  the uniform null per the ruling; gold correctness as diagnostic only.

### Track S — "shifting anchors": distribution over sessions

The concordance is rigidly **one date → one session** (all 1,123 dates), while 67 sessions serve 2-3
dates and the archive itself puts two days' business in one session. The container is the problem, not
the matching. The harvest already addresses anchors as `(date, inventory, char_position)` — inventory,
not session — so the address is partly free already.

- **S1 — free diagnostic.** Size the shift demand: for the 25 heading-confirmed shared sessions, how
  many resolutions would attach to a session other than their date's resolved one, and what does that
  do to the measured surplus balance (gold+hard scope: **+186 resolutions with no text vs −186
  resolutions' worth of text with nothing claiming it, net +60**)? That near-mirror is the reason to
  suspect misallocation rather than absence; S1 tests whether the shifts actually absorb it.
- **S2 — schema: many-to-many date↔session with paragraph ranges**, populated first only from the 25
  verified shared sessions plus the 3 secret-flag-arbitrated spurious claims. Monotonicity brackets
  stay hard constraints; fingerprint verification is never an arbiter (it identifies a raw session,
  never which date owns it). Scored on `separated`.
- **S3 — extend to the 42 undecided duplicates** via the entity channel.

**Open design question (user, 2026-10-05): calibrate the anchor scoring instead of adding hard rules.**
Three channels failed the same way in one day — Group C attribution (30.9% vs 47.9% baseline), the
boundary-existence 2x2 (windows with no negatives), and heading attribution (376 fuzzy collisions
turning 0% into an apparent 64%) — each a channel that *detects* something real but is forced into a
hard decision it cannot support. **The pipeline is already probabilistic and merely uncalibrated:**
`align_session` composes additive `position_scores`/`rank_scores` bonuses with hand-set weights
(`semantic_weight=0.5` etc.) chosen by whether they moved `separated`, never fitted against how often
they are right. What calibration would buy: abstention becomes one thresholding mechanism instead of
a bespoke rule per pathology (it would have caught the 224 secret-hijack placements for free); weak
channels compose at measured weight instead of facing wire-or-discard (the locality principle *is*
likelihood multiplication, and B's 9.6% / C's 30.9% are parameters, not just rejection evidence);
and confidence becomes validatable by **calibration rather than adjudication**, which pools across
thousands of rows and so extracts far more from thin gold — a direct answer to the problem that
forced the `separated` ruling. Costs, honestly: it creates no information (a calibrated weight will
correctly give Group C near-zero influence, not resurrect it), it risks false precision, so any
probabilistic version must still be scored on `separated` against the uniform null and ship a
reliability curve. **Cheapest first step:** fit the score components already computed (Group A
overlap, TF-IDF similarity, phrase hits, entity surface matches) as log-likelihood ratios on the
population with known outcomes and publish the reliability curve — it converges with the
explanatory-coverage ledger below, since "explained vs unknown" is itself a confidence statement.
Not scoped; needs the user's go.

4. **`archival-provenance`** (new, 2026-10-05)
   - `enriched_resolution_secret_flags`: per-resolution `secret` recovered from source XML (106 `<resolutie status="secreet">` + 18 `<deel status="secreet">`, plus `<noot>` register citations incl. 3906). Replaces the inventory-id proxy, which the XML barely supports.
   - `resolution_archival_provenance`: per-resolution `page_ids`/`scan_ids` from ES `full_resolutions.metadata.page_ids` — 9,356/13,052 (71.7%) resolved, 100% of those carry pages; 4562 at 87.8%. Integrity 100% (ES inventory agrees with flat-id inventory; scans sit in that inventory). First channel that can point a resolution at its actual manuscript image.
   - Open: the 28.3% of flat ids that don't resolve in ES; and 4861 has zero rows in `resolutions_flat` at all.
   - See `docs/DECISIONS.md` 2026-10-05.
   - **Secret-session hijack — user mechanism (2026-10-05), population measured, not yet built.** On a day whose only resolved session is a secret one, that session hijacks the day's `k_e`↔`k_f` matching and the pipeline force-fits every enriched resolution onto it. Proposal (user): exclude the secret resolution from regular per-date matching, then re-attach it afterwards to the enriched resolution the **source secret flag already identifies**. Measured population: **34 dates resolve entirely to inventory 4562 (398 enriched resolutions); 224 of those are predicted at paragraph 0..0** (fabricated), and 17 of the 34 days put the whole day on a single start paragraph. **24 of the 34 days carry exactly one secret-flagged enriched resolution**, so the pairing is available there (276 rows); 1 day has 2 flags, 9 days have none and stay unpairable. Of the 31 resolved secret sessions, 25 hold exactly one flat resolution (clean session-level exclusion); 5 hold 2 and 1 holds 3, where the rule must drop the secret *resolution* only.
     - Two implementation traps: flat-side "secret" is only the inventory-4562 proxy (no source XML on the HTR side) while the enriched side is authoritative; and `1626-03-28`'s enriched #14 is flagged `secreet_deel_count=1`, **not** `secreet_resolutie` — a rule keyed on `secreet_resolutie` alone misses the motivating case. Accept either marker.
     - **The flag channel is trustworthy — it arbitrates, it does not need arbitrating (measured 2026-10-05).** Of the 34 days, 9 carry no secret marker at all (not even a `register_citations` row, so nothing weak was missed). Two checks on those: (i) inventory 4562 spans 1615→1924 across 288 dates but only **127** of its 368 resolutions fall in 1626–1630, against **124** source-marked secret resolutions in the same period — two independently derived numbers three apart, which supports the inventory proxy rather than undermining it; (ii) **3 of the 9 are duplicate claims on a session that already belongs to a flagged date** — `session-4562-num-164` (`1626-03-26` unmarked vs `1626-03-28` flagged), `-num-193` (`1627-01-14` vs `1627-01-19`), `-num-211` (`1627-09-06` vs `1627-09-10`). 3 for 3, no exceptions: the unmarked date's *session match* is wrong, not the flag. **Rule: where two dates claim one secret session, the flagged date wins.** Note this means the archive-verified `1626-03-28` finding implicates `1626-03-26` directly. The remaining 6 unmarked days (`1626-05-13`, `1626-09-14`, `1627-10-16`, `1629-05-04`, `1629-05-09`, `1629-05-25`) are **undetermined** — adjudicate by entity probe, then by scan inspection via `resolution_archival_provenance`.
     - **Gate resolved, and this change is effectively free — UNBLOCKED (2026-10-05).** Under the `separated` ruling, withdrawing the paragraph-0 pileup costs **at most 6 of 8,084 separated rows (0.07%)**: of inventory 4562's 318 placed rows only 6 are `separated` (307 fail on `collision`). Of those 6, **2 are the flagged secret resolutions the mechanism re-attaches anyway** (`1627-07-11` #0/#1, the one day with two flags); the other 4 (`1627-10-06` #2/#3/#4, `1628-12-15` #13) are unflagged and need a per-row decision rather than blanket withdrawal. The criterion is behaving correctly here — 307 collided placements already score zero, so `separated` declines to reward the fabrication by itself.

5. **`resolution-loss-census`** (newly completed 2026-09-29)
   - 621 of 1,137 cross_day_shift sit on verified sessions; 552 (93%) collision-locked
   - 27 are true date-label conflicts; 516 lack fingerprint verification
   - Diagnostic: identifies which unplaced mass is recoverable (relabelling) vs structural (collisions)
   - **Duplicate session claims measured corpus-wide (2026-10-05, user question) — `cross_day_shift` essentially *is* this phenomenon.** **67 of 1,053** resolved sessions are claimed by more than one enriched date (64 by two, 3 by three), involving **137 dates** and **1,884 enriched resolutions**; of those, **1,064 are `cross_day_shift` — 93.6% of the corpus's whole 1,137**. Competing claims are always near-neighbours: **median 2 days apart, max 5, none beyond a week**, consistent with the ledger's ±1-day candidate window rather than wild mismatches. By session inventory: 3185 (29), 3186 (20), 3188 (10), 3187 (5), 4562 (3). This is the "sessions as anchors, not containers" principle showing up as a measurable defect — a session claimed by two dates is the container fallacy.
     - **Disambiguate AS ANCHORS, not as ownership (user correction, 2026-10-05).** An earlier draft of this design treated a duplicate claim as a contest with one winner. That is the container fallacy again: an archival session can *legitimately* carry two calendar days' business — `session-3185-num-56` holds both 27 and 28 March 1626, with the 28th's heading recorded inside it as plain continuing text, and the archive's own catalog files it under the 27th. So the operation is **locate each claimant's content region inside the session**, not award the session. Three outcomes per duplicate: **spurious** (one date's content is not in the session at all → drop that claim), **shared** (the session spans both dates → split the paragraph range; both claims survive as anchors over disjoint ranges), **undetermined**.
     - **Evidence tiers.** (1) **Monotonicity** — now an *ordering* constraint inside the session rather than exclusive ownership: if date A < date B and both claim one session, A's content must precede B's in it. The `s6b` session-offset gate's bracket machinery still supplies the hard constraints (`nihil_actum` skips handled). (2) **Embedded date headings** — the strongest signal for `shared`, and cheap: search the session text for a date phrase matching the second claimant's date (`1626-03-28`'s "Sabbathi den xxviijen. Martij 1626" is the worked example). Reuse `s4_session_date_region_scan.py`'s upstream `text_region_class == 'date'` and the Group C phrase searchers. (3) **Secret flag** where the session is 4562 — decides `spurious`, 3 for 3 above. (4) **Entity overlap** per paragraph — gives the *split point*, not merely a winner (entity channel, not lexical — see the calibration note under the ledger step below).
     - **Deliverable (user, 2026-10-05): disambiguate what we can, then report how much is left** — the same explanatory-coverage shape as the ledger step, scoped to the 67 sessions.
     - **DONE for the heading channel (2026-10-05), `scripts/s6_duplicate_session_date_headings.py`: 25 of 67 (37%) decided, every one `shared`, zero spurious.** 5 `shared_confirmed`, 20 `shared_one_heading`; remaining 42 = 23 `no_heading_signal` + 18 `hits_but_none_verified` + 1 `one_claimant_heading_only`. Those 42 are the entity channel's population. Design is three-stage — **fuzzy match to locate, exact day lookup to verify, weekday as an independent cross-check** — and two earlier designs failed: a fuzzy-phrase-per-candidate-date version reported 43/67 (64%) that was entirely Roman-numeral collision (0 of 41 had the claimants' hits at separate sites; 376 hits are now rejected by the exact parse), and a wildcard-frame version matched the year fuzzily too and missed the validation case. **Keep the held-out validation (`session-3185-num-56` must recover 1626-03-28) as a precondition on any future heading work.** Vocabularies are REPUBLIC's handwritten variants, copied to `scripts/_republic_date_vocab.py` at commit `3b46b43b` — `uv add` is blocked by its `python <3.12` and `fuzzy-search ^2.6.0` pins (we run 3.12.13 / fuzzy_search 3.0.3). Weekday check measured: readable on 354/422 hits, vetoed 3, rescued 11. See `docs/DECISIONS.md` 2026-10-05.
     - **Fingerprint verification is deliberately NOT an arbiter.** It establishes which raw session a flat session is, never which enriched date owns it — which is why `resolution_loss_census` labels those rows `relabel_candidate`, not `recoverable`. Keeping that distinction is what stops dedup from promoting a raw date label to truth.
     - **Gate resolved, but this one is NOT free (measured 2026-10-05, after the `separated` ruling):** of the 820 placed rows on duplicate-claimed sessions, **428 are `separated`** — 5.3% of the corpus's 8,084. So where tiers 1–3 do not decide, **prefer the claimant whose rows are `separated`**. 428 is the exposure, not the bill: a `shared` verdict keeps both claims, and the winning claimant of a `spurious` one keeps its placements.
   - **NEXT STEP, agreed with user 2026-10-05: explanatory-coverage ledger ("how much do we actually know?").** From the gold exercise the user cannot tell, for a resolution the parser misses, whether it is absent from the text, lumped (several logical resolutions in one flat row), overparsed (scattered across rows), lost upstream, or recovered upstream under another session/date. This step does not fix any of those — it measures **how much of the loss we can account for with positive evidence**, over `resolution_loss_census`'s existing 19,120-row denominator.
     - **Two levels, deliberately:** lumping is a property of a *flat row*, absence a property of an *enriched resolution*. A single per-resolution label conflates them — which is also why the existing `s6c_severe_collapse_autopsy.classify_cause` taxonomy (`pigeonhole_forced`/`axis_requires_repeats`/`room_on_axis`) now explains nothing: its own 2026-09-30 correction found 179/179 gaps forced once real anchors are used. Geometry is exhausted; the open questions are about content.
     - **Metric shape:** share of the population where ≥1 cause test fires (`explained`), split into *decided* (exactly one) vs *co-occurring* (≥2 — the user's observation that gaps and lumping appear together in one session predicts this is common), against *unknown*, itself split by why we cannot tell (no discriminative tokens to probe, no scan coverage, hits below threshold). Headline is three numbers: explained, unexplained, and **unexplainable with current channels** — the last being the ceiling on what more analysis could reach without new data. Classification coverage, no displacement/tolerance family. Un-gameable by construction: coverage rises only on found evidence, never on placing more.
     - **v1a (zero search cost, do first — user: "use what is already there as a heuristic and concentrate on hot spots"):** rank days/resolutions by how badly *and how unexplainedly* broken they are, from existing fields only — degenerate pileup at paragraph 0, `k_e` vs `k_f`, distinct-start count, inventory-4562 + `enriched_resolution_secret_flags`, `resolution_loss_census` fingerprint status, `resolution_archival_provenance` scan coverage. Fill in the causes existing data already decides. The secret-session hijack (track 4) is hot spot #1 and is fully decidable here with no searching.
     - **v1b:** calibrate the text-findability probe on the `separated`-and-gold-correct population to get its **false-negative rate** — without this, HTR noise silently becomes "upstream absence" and the most alarming number in the report is an artifact. This is a precondition for any headline number, not an extra.
     - **Probe instrument — use the ENTITY channel, not lexical overlap (settled 2026-10-05 by calibration, do not re-derive).** A rare-token (`[a-z]{7,}`) overlap probe was built and calibrated against archive-verified true pairs and **failed**: on `1626-03-28` the true pair (#14) ranked *second* behind a 4-token fragment; with a ≥20-token floor, flagged resolutions ranked 1st/1st/2nd on three calibration days and fell out of eligibility on a fourth; shared-token counts were only 4–8 even on verified true pairs. The cause is structural and will not improve with tuning: the enriched side is a **modern Dutch summary**, the flat side is **17th-century HTR**, so they barely share surface forms. Near-zero overlap on an unknown day is therefore **no evidence of absence**. The user's own hand procedure used *names* (Sir Thomas Lucas, Mourmont, Wollebrantsz/Tol, Wiggeringe), which survive both sides, and that channel is already in the data: of the 398 secret-resolved rows, `persons` is non-empty on **334**, `places` 225, `institutions` 119, `ships` 0. So reuse Group B's `entity_surface_matches`/`fuzzy_surface_scan`. Group B was deferred as an *anchor* because it attributes to a specific resolution only 9.6% of the time — but as a presence/absence probe inside an already-identified hot spot it does not need to attribute, which is the locality principle again and the job it can actually do.
     - **v1c:** run the probe (entity fingerprint → matched session's axis, then a session window in the same inventory, then ES corpus-wide) only on the top hot spots plus the 74 gold + hard-period days, where labels can be checked against the user's annotations. It automates what the user already did by hand twice: `1626-03-28` (found in `session-3185-num-56` → recovered elsewhere) and `1628-05-15` (four distinctive names absent across a 23-session window → genuine upstream absence). Those two are the validation cases. Lumping/scattering fall out of the same hit map — distinct enriched ids hitting one flat row vs one enriched id spread over ≥2 — so they need no new machinery.
     - Decide corpus-wide only after v1c. Advise commands; the user runs heavy compute.

**Future / parked:**
- **Synthetic boundary encoder** ([docs/steps/STEP_SYNTHETIC_BOUNDARY_ENCODER.md](docs/steps/STEP_SYNTHETIC_BOUNDARY_ENCODER.md))
  - Completed eval 2026-09-28; GloBERTise F1@50=0.407; hard-openings retrain worse
- **Secret resolutions (4562/4861)** — Cherry-picking retrieval design, separate track; user parked 2026-09-29
  - `1626-03-28` case (2026-10-02, corrected twice, see `docs/DECISIONS.md`): only enriched `#15` is a genuine secret resolution (`session-4562-num-164`, archive-verified). The other 15 are **not** a secret-resolutions/cross-inventory matter at all — `#1`/`#7-16` have real text mis-dated into `session-3185-num-56` (archivally filed under 27 March even by the archive's own catalog), and `#2-6` are a confirmed true extraction gap, absent even from the raw per-paragraph HTR axis (content exists on folio 100v, never ingested at all — not a splitting bug, nothing downstream can recover it). Logged under `resolution-loss-census` instead; prevalence of either sub-mechanism elsewhere is unknown, not sized.
  - **Priority reconsidered (2026-10-02), still parked, not scoped:** recovering the per-resolution `secret` flag from source XML now has a second justification — instant triage of cause (a) above instead of a manual archive round-trip each time — on top of the original cherry-picking retrieval design. It would not catch causes (b)/(c). User chose to elevate rather than start this session.
  - **Design sharpened (2026-10-05):** the real payoff isn't triage speed, it's a pipeline fix. `session_date_status_1626_1630` already carries one ledger row per `(inventory_id, enriched_date)`; on 20 dates a trusted single-resolution secret match wins `resolved_session_id` for the whole date while that same date's public-inventory row sits at a correctly-identified but lower-confidence pending status (`+1`/`-1`/`?`), never reviewed. User's proposed fix: give secret-inventory matches their own status track in `s4_day_status_resolution.py`, outside the normal comparison, so they never win by default — resolve the normal sequence first, attach the secret resolution separately after. The recovered `secret` flag is what would drive that split. Still parked, not scoped — see `docs/DECISIONS.md` 2026-10-05.
- **Workspace alignment** — Completed via `dighum_template` sync

## How to navigate
<!-- doc-status: active -->

1. **For work planning:** `uv run python scripts/svz.py review` shows active tracks and metrics
2. **For decisions:** See [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/ITERATION_POLICY.md](docs/ITERATION_POLICY.md)
3. **For the method:** [docs/SEGMENTATION_TRANSFER.md](docs/SEGMENTATION_TRANSFER.md) frames the problem
4. **For results:** [docs/SEGMENTATION_RESULTS.md](docs/SEGMENTATION_RESULTS.md) summarizes findings
5. **For active track details:** Each track in `plans/*.md`

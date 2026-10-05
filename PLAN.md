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

- **P0 — GATE, and it is a canonical-goal decision, not a metric tweak. Needs the user's explicit
  sign-off before P3.** The acceptance criterion and the **11,644 paragraph-level ceiling** both assume
  one resolution per paragraph ("several resolutions sharing one paragraph is a multi-mapping read").
  Sub-paragraph anchors raise that ceiling, so `separated` (`label_separation`'s `unique_start`) must be
  rekeyed from `paragraph_start_index` to `(paragraph, char_offset)` or it **structurally cannot see
  the gain**. Consequence to accept deliberately: today's 8,084 = 68.8% "MET" becomes a smaller
  fraction of a larger ceiling — real coverage rises while the headline number falls. Rekeying the
  metric the `separated` ruling adjudicates on is also moving the goalposts unless it is decided
  openly, which is why it is step zero.
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
- **P2 — bounded annotation, only if P1 passes.** `lumped_paragraph_gold_scaffold` holds **80 sampled
  candidates, all `review_status: pending`, zero `gold_offsets`** (out of 463 lumped specs identified,
  445 materialised) — the track was built and never started, which is why `lumped_paragraph_boundary_gold`
  is absent from disk. UI (`build_lumped_paragraph_annotation_ui.py`) and merge script already exist.
  This is the smallest annotation ask in the project and, unlike the hard-period sample, has a
  guaranteed use: it is the only way to tell whether a candidate offset is the *right* cut.
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

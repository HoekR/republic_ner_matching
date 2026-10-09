# Track P — "placing anchors": sub-paragraph division

<!-- doc-status: active -->

Part of the **main line** (user, 2026-10-05): the two remaining problems are both anchor
operations — (1) we do not know how to divide or join paragraphs → **place anchors** (this
track); (2) the distribution of resolutions/paragraphs over sessions is unresolved → shift
anchors ([plans/TRACK_S_ANCHOR_SHIFTING.md](TRACK_S_ANCHOR_SHIFTING.md)). They are coupled —
several shared-session splits are themselves sub-paragraph, so **P before S**. See `PLAN.md`'s
canonical goal; this file is where new Track P steps get added, `PLAN.md` keeps only the
headline.

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


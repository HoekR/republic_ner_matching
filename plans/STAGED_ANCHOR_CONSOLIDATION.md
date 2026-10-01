# Staged anchor consolidation

<!-- doc-status: active -->

## Relation to existing tracks — read this first

**This is not a new framing.** It is the execution design for
[`plans/COLLISION_AVOIDANCE_TRACK.md`](COLLISION_AVOIDANCE_TRACK.md)'s working hypothesis (user,
2026-09-25), points 1–3: apply `k_e` sequentially along an inventory; treat day separation as a
**local calibration anchor** rather than a partition; correct misplaced day anchors using the
resolutions that *do* align confidently. That track established the framing and measured the free
gates (findings A–D); this doc specifies the *procedure* and the one code change it needs.

Read that track's findings A–D and its Step 6 before working here. Its finding D
(“the anchor-correction channel's data exists and was never wired up”) is the direct precursor.

## Goal

One consolidated anchor set, drawn from **all** evidence channels and applied in confidence order,
that shrinks unresolved gaps as far as the evidence allows — and **abstains honestly** where it
cannot, instead of fabricating precision.

## Definition: a clump is not a result (user, 2026-09-30)

A clump of resolutions that cannot be separated is an **unresolved gap**, not an output. It is not
emitted as a placement. Three consequences, all simplifying:

1. **No schema change.** Unresolved resolutions simply carry no paragraph attribution.
   `paragraph_start_index` / `paragraph_end_index` are already nullable and
   `attach_paragraph_attribution` (`scripts/s4_resolution_concordance.py:115`) already returns
   `None` for them when a prediction does not qualify.
2. **Gap-minimisation is not gameable.** The obvious cheat — declare the whole day one clump — is
   one *maximal* gap, i.e. the worst possible score. No counter-term bounding clump span is needed.
3. **It is consistent with `PLAN.md`, not a reversal of it.** PLAN.md already holds that a
   multi-mapping read is to “filter, don't count as progress” and that “uncovered regions are
   informative — they must be classified, not merely omitted.” This is that position, stated
   operationally.

## The progress ladder — a measure, not a schema

| level | shape | meaning |
|---|---|---|
| 1 | `S start · R1 R2 R3 … Rn · S end` | every resolution individually resolved; no gaps |
| 2 | `R1 · ⟨gap: R2–R3⟩ · R4 · ⟨gap: R5–R6⟩ … Rn` | some resolved singly, the rest left as small ordered gaps |
| 3 | `S1⟨gap: R1–4⟩ · S1R5 … S2R2 · S2R3 · S2⟨gap: R4–6⟩ …` | as level 2, plus session identity carried in the address because session boundaries are themselves uncertain |

Levels are *how much got resolved*, not output formats. Level 3 is the form `PLAN.md`'s canonical
goal already demands: “expressed in session-relative archival terms — a verified archival address,
not a possibly-drifted session number.”

**The measure already exists.** `scripts/s6b_known_point_ledger.py` states it: “the baseline number
is not an F1 — it is how much of the stream is already pinned by known points plus counting, and the
shape of the gap-size distribution.” Baseline in hand: **947 open gaps holding 70.7% of unplaced
work** (`COLLISION_AVOIDANCE_TRACK`). Promote that to the objective; do not build new tooling.

## The procedure

1. Place the most **objective** anchors first — structural/archival facts before content inferences.
2. **Reconcile contradictions among those**, before going further.
3. Subdivide the remaining gaps using the next channel down.
4. Reconcile the contradictions that subdivision creates.
5. Repeat until no gap subdivides further. What remains is the gap set; it is not emitted as
   placements.

**The confidence order already exists**, empirically assigned in
`scripts/s6b_anchor_harvest.py:104` (`CHANNEL_WEIGHT`), and nothing has ever executed against it:

| channel | group | weight | nature |
|---|---|---|---|
| `session_boundary` | D | 5.0 | structural |
| `session_day_find` | D | 4.0 | structural |
| `session_date_verified` | D | 4.0 | content-fingerprint verified |
| `tier1_entity_nw` | A | 3.0 | tagger entity overlap |
| `s2_anchor_phrases` | C | 2.0 | formulaic text |
| `entity_surface_matches` | B | 1.5 | dictionary surface |
| `s4_opening_phrase_candidates` | C | 1.5 | formulaic text |
| `fuzzy_surface_scan` | B | 1.0 | fuzzy surface |

### Why staging makes weak anchors safe

A `fuzzy_surface_scan` hit loose over a 12-paragraph day and the same hit inside an
already-bracketed 2-paragraph gap are not the same evidence — the second has almost no room to be
wrong. Staging raises the reliability of each channel by shrinking the search space before applying
it. This is the answer to “fuzzy matches are too noisy to use”: they are, *unstaged*.

## Findings in hand (2026-09-30)

**The DP consumes ~7% of available anchors.** Measured on the three pathology seed days from
`output/s6b_anchor_harvest.jsonl`:

| day | `tier1_entity_nw` (all the DP sees) | all other channels | DP share |
|---|---|---|---|
| `1630-02-22` | 9 | 123 | 7% |
| `1629-06-03` | 3 | 82 | 3.5% |
| `1627-10-06` | 3 | 72 | 4% |

**Groups B/C/D are structurally invisible, not merely down-weighted.** `align_session`'s
`anchor_only_diagonal` gate (`build_alignment_new.py:900`ff) forbids a diagonal move unless
`entity_match_score > 0` or semantic similarity clears its threshold — and `semantic_weight`
defaults to `0.0`. So a B/C/D anchor cannot make a cell eligible for a diagonal at all. This is why
18 of 28 resolutions on `1630-02-22` are gap moves on a day carrying 123 non-A anchors.

**Anchor strength is often carried by one entity, and ties are where readings diverge.** From the
pathology corpus Step 1 ledger (`plans/PATHOLOGY_CORPUS_RUNLOG.md`): of 7 NW-taken anchors on
`1630-02-22`, four rest on a single entity. Row-local argmax and the global traceback disagree in
exactly two shapes — a **row-internal tie** (one resolution scoring identically at two paragraphs)
and **column contention** (several resolutions best-matching the same paragraph, only one of which
can hold a diagonal). Keep these apart; they need different treatment.

## The one code change with real reach: partial abstention

`segment_day` is documented as a “count-constrained replacement for `interpolate_positions` that
**never abstains**”, returning `k_e − 1` positions unconditionally; its docstring notes that callers
wanting abstention “apply it before calling this”. So abstention exists only at **whole-day**
granularity, decided upstream.

What is missing is **partial abstention** — abstaining on one gap while keeping the resolved anchors
on either side. This is the defect behind `1630-02-22`: the 9 placements at paragraph 0 and 8 at
paragraph 7 are *fabricated precision*, because the DP cannot return “unresolved” for a sub-span
while still reporting the 7 anchors it did resolve. The honest output for that day is **7 placements
plus two characterised gaps**, not 28 placements of which 21 are interpolation.

This change is justified independently of everything else in this doc.

## Gaps are precisely targetable for human intervention (user, 2026-09-30)

This is a positive consequence of clump-as-gap, not a consolation prize. An unresolved gap is a
**bounded, enumerable, well-posed question**: “these 4 resolutions fall somewhere between paragraph
7 and paragraph 9, in this order.” That is answerable by a human in seconds. “Review this day” is
not.

Fabricated precision actively destroys this. A day emitting 28 placements of which 21 are
interpolation *looks finished* — there is nothing for a reviewer to target. The same day emitting 7
placements plus 2 characterised gaps tells a reviewer exactly where to look and how much is at
stake. Partial abstention is therefore a prerequisite for useful human review, not merely a
correctness improvement.

**Human effort compounds through the propagation loop.** A hand-resolved gap becomes a new anchor of
the highest confidence class — `s6b_known_point_ledger` already types gold boundaries as a
known-point kind alongside session starts and production anchors — so re-running the procedure after
an intervention can close *adjacent* gaps for free. One human decision can cascade. This is the
argument for staging over a single pass: the loop is what converts manual effort into leverage.

**The scaffold → annotate → merge pattern already exists three times over** and should be reused
rather than rebuilt:

| scaffold | UI | merge |
|---|---|---|
| `build_lumped_paragraph_gold_scaffold.py` | `build_lumped_paragraph_annotation_ui.py`, `lumped_paragraph_annotation_app.py` | `merge_lumped_paragraph_annotations.py` |
| `build_session_date_mapping_review_ui.py` | — | `merge_session_date_mapping_decisions.py` |
| `build_synthetic_boundary_gold_scaffold.py` | — | `merge_synthetic_boundary_gold_annotations.py` |

A ranked gap set is the natural scaffold input for that pattern.

This is also what `PLAN.md`'s goal statement already asks for: “publish it as a reviewable table
where every placement carries a confidence tier and its evidence, and where the *unplaced* parts are
characterised rather than merely absent.” A gap set **is** that characterisation, and it is
reviewable by construction.

**To define, not assume:** how to rank gaps for human attention. Gap size is the obvious measure and
probably the wrong one on its own — a 2-resolution gap may be cheap to resolve but unlock nothing,
while a large gap may be expensive but unblock a whole session via the cascade above. Rank by
expected unlocked mass, not by size alone, and measure that claim rather than asserting it.

## Guardrails and open problems

1. **The foundation is circular until the mapping question is sized — now sized, 2026-10-01
   (`docs/DECISIONS.md`).** Confidence order puts `session_boundary` first at weight 5.0; the
   date-identity failure mode is small (8/1,123 pinned sittings, 0.7%, confirmed wrong by
   content fingerprint vs raw archival date) and does not block it. But `1630-02-22` — the
   instance that raised this guardrail — itself comes back `date_label_agrees`: its problem
   (28 resolutions, 12-paragraph axis, one-sided zero-anchor pile) is **not** a date-mapping
   error, so this guardrail does not cover it. That failure mode is Steps 3/4's to fix.
2. **Greedy staging is the failure mode this track already named.** `COLLISION_AVOIDANCE_TRACK`
   Step 5c.1: “Gap-filling around unverified anchors propagates error both ways — a wrong anchor
   corrupts the gap on each side of it.” Anchors placed early must remain **revisable**. Constraint
   propagation, not greedy commitment — otherwise this rebuilds the error `separated_accuracy_eval`
   was written to prevent.
3. **The contradiction-resolution rule is undefined.** Candidate: minimum deletion to restore
   monotonicity (LIS), which this track already cites as the standard treatment for noisy anchors
   (MUMmer/NUCmer, Step 3's prior-art menu) and which has the merit of being a stated objective
   rather than a heuristic. Alternatives — yield by weight, or by supporting-evidence count — should
   be measured against it, not assumed.
4. **The termination condition is undefined.** “Resolve gaps → resolve new contradictions” can
   oscillate. Fix the rule before running, per `docs/ITERATION_POLICY.md`.
5. **Metric guardrail.** A gap metric is a coverage metric and can be gamed exactly as `separated`
   was (a uniform spread beat gold on `separated`; coverage and gold correctness disagree in sign on
   solid days — `plans/TFIDF_EMBEDDINGS_TRACK.md`, 2026-09-30). **Any step proposing a placement
   change reports gap-mass *and* gold correctness**, never gap-mass alone.
6. **Granularity.** `s6b_anchor_harvest` is keyed on `char_position`; the DP and the paragraph axis
   are keyed on paragraph index. The char→paragraph join is unverified, and the harvest summary
   carries a `window` field whose scope must be confirmed before any corpus-wide projection.

## Steps

### Step 1 — Size the pinned-but-wrong population
<!-- status: DONE 2026-10-01 -- see docs/DECISIONS.md "Pinned-but-wrong session mapping, sized". -->
Ran `scripts/fingerprint_assignment_audit.py` (already written, never executed): joins every pinned
sitting through `s6b_session_fingerprint_match`'s content fingerprint to `session_index_all`'s raw
archival date, independent of resolutions_flat's own (possibly drifted) label.
**Gate result:** 1,123 pinned sittings — 8 (0.7%) confirmed `date_label_conflict`, 82 (7.3%)
`raw_session_reused` (known multi-claim collisions, not new wrongness), 351 (31.3%)
`unmatched_fingerprint` (unverifiable either way), 682 (60.7%) `date_label_agrees`. Small enough
that `session_boundary`/D stays first in `CHANNEL_WEIGHT` order without further gating. **Does not
explain `1630-02-22`** (comes back `date_label_agrees`) — that instance's crowding is a Step 3/4
problem, not a date-mapping one; do not re-litigate this step to chase it.

### Step 2 — Verify the harvest join and scope
<!-- status: DONE on the 3 seed days ONLY 2026-10-01 -- PASSED there, but see the
     corpus-scope finding below, which this check's own by-product search makes clear does
     NOT generalize. Script: scripts/s6b_char_paragraph_join_check.py, 3 seed days, 292 rows. -->
Confirm the char→paragraph mapping and the harvest's `window` scope (guardrail 6). Without this the
ensemble cannot be placed on the axis the DP uses.
**Gate:** every seed-day anchor maps to exactly one paragraph index; harvest scope is known.

**Result, scoped to exactly 3 calendar dates (`1630-02-22`, `1629-06-03`, `1627-10-06`), 292
anchor rows total across all 8 channels (132 / 85 / 75) -- not a random sample, not corpus-wide:**
- `axis_for_date` (what the DP scores against) is paragraph-for-paragraph identical to the
  same-calendar-day axis `s6b_anchor_harvest.py` used to compute char positions (`axes_match=True`,
  all 3 days) -- the two are not guaranteed identical in general (`axis_for_date` prefers a
  resolved session's own axis when one exists, `scripts/s4_corpus_paragraph_predictions.py:111-116`),
  so this was checked, not assumed.
- Every one of the 292 harvested anchors resolves to exactly one in-bounds paragraph index via
  `bisect` over `char_starts(axis)` -- no separator ambiguity (`char_starts` concatenates
  paragraph text directly, `scripts/s6a_char_axis_evaluation.py:66-73`), no off-by-one, **on
  these 3 dates**.
- `window` scope: confirmed to mean the harvest run's date range (1626-01-01..1630-12-31,
  `s6b_anchor_harvest.jsonl` meta record), not a per-anchor field -- no ambiguity there, and it
  does cover all 3 seeds.

**Corpus-scope finding (does not generalize from the above, found while answering a follow-up
question, not originally scoped into this step): the raw-vs-resolved axis mismatch is common,
not rare.** Checking all `session_by_date` entries corpus-wide: **137 of 1,119 dates (12.2%)**
have `axis_for_date(date) != axis_by_date[date]`. All 3 pathology-corpus seeds happen to fall in
the clean 982/1,119 bucket, so the PASS above says nothing about whether the join holds on the
other 12%. Two concrete failure shapes found there, not hypothetical:
- `1626-01-17`: the raw same-day axis is **empty** (0 paragraphs); `axis_for_date` resolves to
  `session-3185-num-13`, which has **39 real paragraphs**. The harvest script enumerates dates
  from the raw axis-by-calendar-date grouping, so it never runs `_harvest_date_worker` for this
  date at all -- groups B/C/D are silently never harvested here, not because no evidence exists.
- `1626-01-12`: the raw same-day axis has **11** paragraphs (9 from `session-3185-num-10` + 2
  from an unrelated inventory, `session-4562-num-161`, sharing the calendar-date label by
  coincidence); `axis_for_date` correctly isolates the 9 that belong to the resolved session. A
  B/C anchor the harvest found inside those 2 foreign paragraphs would carry a char_position past
  the end of the 9-paragraph axis the DP actually uses -- exactly the `out_of_bounds`/
  `end_of_axis` case this script's join-mechanics check would catch, which is why it did not
  fire on the 3 (clean) seeds but should be expected to on a chunk of the other 137 dates.

**Consequence:** before Step 4 runs on anything beyond the 3 seeds, re-run
`scripts/s6b_char_paragraph_join_check.py` (or a corpus-wide variant of it) against a sample of
the 137 mismatching dates specifically, not just more random dates -- they are the population
this step's gate has not actually tested yet.

### Follow-up (2026-10-01): the 137 mismatches, classified -- and a new, more consequential finding

**Classified all 137 for free, no ES needed, using the inventory number already embedded in
each flat_id's `session-{inventory}-num-{n}-resolution-{r}` format:**

| class | n | shape |
|---|---|---|
| `cross_inventory_contamination` | 66 (48%) | raw same-day grouping pulls in a different inventory's paragraphs, like `1626-01-12` (3185 + 4562) |
| `raw_empty_or_subset` | 62 (45%) | raw same-day axis is empty or a strict subset; `axis_for_date`'s resolved axis adds real content, like `1626-01-17` |
| `same_inventory_diff` | 9 (7%) | raw axis also contains a second, same-inventory session under this date label |

In both of the first two classes (113/137, 93%), `axis_for_date`'s resolved axis is clearly the
one to trust -- confirmed by the id-derived inventory check alone, no live lookup required for
this part. **Neither class resembles the original "adjoining text, shift the anchor N paragraphs"
hypothesis** that motivated checking this in the first place -- that hypothesis is now settled
false for the population it was raised about.

**The remaining 9 are not boundary drift either, and are more consequential than expected.**
Pulled their actual diff content: each one is a *second, fully-numbered, unrelated session* of
the same inventory sharing the calendar-date label -- e.g. `1626-09-21`'s raw axis holds all 16
resolutions of `session-3185-num-156` alongside the resolved `session-3185-num-148`, not an
adjacent 1-2 paragraph spillover. Checked both sessions' real dates via ES `session_metadata`
(`formulation/scripts/export_resolution_es_provenance.py`, built as a **general, reusable
flat-ids-to-ES-provenance tool**, not scoped to this one check -- see
`data_manifest.toml`'s `axis_mismatch_es_provenance` for the one-off 2,617-id pull this produced
as a byproduct):

| mismatching date | resolved session (what `axis_for_date` returns) | ES's own `session_date` for it | "extra" same-inventory session in raw grouping | ES's `session_date` for *that* |
|---|---|---|---|---|
| 1626-09-21 | session-3185-num-148 | **1626-08-30** | session-3185-num-156 | **1626-09-13** |
| 1627-10-19 | session-3186-num-179 | 1627-09-29 | session-3186-num-184 | 1627-10-05 |
| 1628-11-04 | session-3187-num-256 | 1628-11-03 | session-3187-num-283 | 1628-11-26 |
| 1629-02-17 | session-3188-num-46 | 1629-02-19 | session-3188-num-52 | 1629-02-25 |
| 1629-05-18 | session-3188-num-129 | 1629-05-17 | session-3188-num-79 | 1629-03-24 |
| 1629-06-12 | session-3188-num-147 | 1629-06-10 | session-3188-num-151 | 1629-06-16 |
| ... | | | | |

**Neither side of these 9 mismatches carries a `session_date` matching our own pipeline's
calendar-date label, in ES's independent reading.** This is not, by itself, a bug to fix here --
it is consistent with the already-known, already-worked phenomenon this project's whole
concordance effort exists to correct (`resolutions_flat`'s session numbering drifting from the
archive, `docs/DECISIONS.md` 2026-09-21 S4f review) -- but it means these 9 are concrete,
freshly-surfaced instances where even the **resolved** (trusted, `day_status=="resolved_auto"`)
session disagrees with an independent date source, not just the naive raw grouping. That is
exactly the shape of guardrail 1 / Step 1's open "pinned-but-wrong" question ("a confidently-
pinned session can be wrong with nothing flagging it"), which has been blocked pending sizing.
**Do not treat this as resolved either way** -- adjudicating which date is right needs this
project's own existing verification tool (`s6b_session_fingerprint_match`'s content-fingerprint
method), not a naive "trust ES's date" assumption; ES's `session_date` field has not itself been
checked against that same standard here.

**Consequence for Step 1:** these 9 dates are a ready-made, already-identified starter sample
for Step 1's sizing work, found as a byproduct of Step 2 rather than Step 1's own planned method
-- worth feeding in rather than re-deriving independently.

**Consequence for Step 4:** confirmed again, more strongly -- of the 137 raw/resolved axis
disagreements, **zero** show the small-scale boundary-shift shape the original hypothesis
proposed. 93% are a harvest-side grouping defect (fixable by switching the harvest to
`axis_for_date`, no placement question involved); the remaining 7% are a session-date-drift
question that belongs to Step 1, not to anchor placement at all.

**Harvest fix implemented, 2026-10-01, not yet re-run.** `scripts/s6b_anchor_harvest.py`'s
date enumeration now resolves each date via `axis_for_date` (same `axis_by_date` /
`axis_by_session` / `resolved_sessions()` idiom as `s4_corpus_paragraph_predictions.py` and
its other callers) instead of grouping `paragraph_axis_1626_1630` by raw calendar date. This
closes the 93% class outright and adds dates whose raw same-day axis was empty (e.g.
`1626-01-17`) to the harvested population. The 7% session-date-drift class (9 dates) is
unaffected -- it is Step 1's question, not this one. **Not yet re-run** (heavy compute, full
corpus rebuild) -- needs a user-run pass before `s6b_anchor_harvest.jsonl` reflects this.

**Real finding, already documented elsewhere, newly consequential here: harvest group A is stale.**
Cross-checking `tier1_entity_nw` against the paragraph indices already hand-verified for
`1630-02-22` in `plans/PATHOLOGY_CORPUS_RUNLOG.md` Step 1 (9->1, 11->4, 12->5, 14->7, 23->8,
25->10, 26->11) found 3/7 wrong or missing: enriched index 11 absent from the harvest entirely,
23 and 26 mapped one paragraph short. Root cause is already on record, not a new bug:
`docs/DECISIONS.md` 2026-09-29 rebuilt `s6b_known_point_ledger` to use production's live
`align_session` anchors (`production_points()`) because they diverge from the stored
`alignment_1626_1630` TIER1 rows at only 62.9% exact-position agreement corpus-wide — and that
same entry explicitly notes `s6b_anchor_harvest.py`'s group A channel reads the stored rows
directly and **was not** part of that rebuild. This check is the first time that known gap was
actually exercised against this harvest file rather than just cited.

**Consequence for Step 4 (both 4a and 4b).** Do not read group A from
`s6b_anchor_harvest`'s `tier1_entity_nw` rows. Compute group A live per day from
`align_session`/`build_axis_overlap`, exactly as `scripts/pathology_corpus_stage_a.py` and
`s6c_severe_collapse_autopsy.span_verdict_for_day` already do — only groups B/C/D should be
drawn from the harvest file, joined onto the live axis via the now-verified char→paragraph
mapping. (The 2026-10-01 "0/85 chosen" pathology-corpus result is unaffected by this finding —
it never read the harvest file, it called `align_session` directly.)

### Step 3 — Partial abstention in `segment_day`
<!-- status: DONE 2026-10-01 -- see docs/DECISIONS.md “Partial abstention in segment_day Step 3”. -->
Allow the DP to return “unresolved” for a gap while reporting resolved anchors around it. Score on
gap mass **and** gold correctness (guardrail 5). Compare against today's fabricated-precision
output on the pathology corpus seed days.
**Gate:** on `1630-02-22`, output is 7 placements + 2 characterised gaps; corpus-wide gap-mass and
gold correctness both reported.

**Result, 2026-10-01:** Gate PASS on both metrics. **Gap-mass:** seed day 1630-02-22 has exactly
2 abstained gaps with 16 total unresolved resolutions (matching expected); other seed days have
adequate room for their resolutions. **Gold correctness (Guardrail 5):** measured on 19 scoreable
boundary_gold_sample days using existing separated_accuracy_eval convention (exact-start-paragraph
agreement): 0.5080 before and after abstention (no change). Abstaining on forced-collapse gaps does
not hurt correctness on gold. Implementation: `segment_day` returns `list[int | None]` where `None`
marks unresolved positions; callers filter `None` before building boundaries. All 50 existing tests
pass; added 3 new unit tests for abstention behavior.

### Step 4 — Two ways to add channels, run as a comparison, not a single choice
<!-- status: todo — split into 4a/4b 2026-10-01 after pathology-corpus's 0/85-chosen result
     (plans/PATHOLOGY_CORPUS_RUNLOG.md, "Correction (2026-10-01)"), which showed the current
     fill algorithm is optimal given group-A-only evidence and 36/60 ambiguous severe-collapse
     days have a worst gap with paragraph_room=1 -- anchor-starved, not room-starved. That
     motivates actually wiring B/C/D in, but the plan's own "why staging makes weak anchors
     safe" argument (line 79) is itself a claim, not yet tested against the alternative. -->

Both modes below are blocked on the same prerequisite: **Step 2** (char→paragraph join,
guardrail 6) must land first — B/C/D anchors are `char_position`-keyed; neither mode can place
them on the paragraph axis `align_session` uses until that join is verified. **Step 1** (sizing
the pinned-but-wrong population, guardrail 1) is done, 2026-10-01: `session_boundary`/D at weight
5.0, the first channel in both orderings below, is wrong for only 0.7% of pinned sittings
(confirmed) — not a blocker for either mode.

**4a — Staged (sequential), as originally specified.** Add channels in `CHANNEL_WEIGHT` order
(D -> A -> C -> B). At each stage: place that channel's anchors *only inside gaps not yet
resolved by a higher channel*, lock the result, recompute the residual gap boundaries (shrinking
`paragraph_room` for the next stage), then move to the next channel. Mechanically: iterate
`build_anchor_backbone` / `segment_gap` (`scripts/s6c_gap_segmentation.py`,
`scripts/pathology_corpus_stage_a.py`) so each stage's lookup is restricted to the one channel
being added, operating only on the previous stage's residual gaps. Measure gap-mass reduction
*and* gold correctness (guardrail 5) after each stage, cumulatively.

**4b — Combined (unstaged), new, added as a control.** One pass: merge all four groups' anchor
evidence into a single lookup and relax `align_session`'s `anchor_only_diagonal` gate to accept
a diagonal when *any* group's weighted score clears threshold (today it only checks group A's
`entity_match_score`), with no gap-shrinking between groups and no stage order. Measure the same
two metrics in the same single pass.

**Why run both instead of picking one.** The plan's own justification for staging ("Why staging
makes weak anchors safe", line 79) is that a weak channel is only safe *because* a stronger
channel already narrowed the room before it runs — unstaged, the same fuzzy hit over a wide-open
12-paragraph day is reckless. That is a testable claim, not an assumption to build on:
- If **4b matches 4a** on both gap-mass and gold correctness, staging order doesn't matter here
  and the simpler one-shot wiring (4b) is preferable — less code, no contradiction-resolution
  machinery (guardrail 3) needed.
- If **4b matches 4a on gap-mass but loses on gold correctness**, that is the predicted failure
  mode and confirms staging is load-bearing, not just tidier.
- If **4a underperforms 4b on gap-mass**, the per-stage locking is leaving recoverable gaps on
  the table (a stage's placement may be blocking a later channel's correct answer) — a different
  bug, in the staging mechanism itself.

**Gate:** per guardrail 5, neither mode is judged on gap-mass alone. Run on the three pathology
seed days first (cheap, same idiom as `PATHOLOGY_CORPUS_RUNLOG.md` Step 1/2), before the 85
severe-collapse days, before any corpus-wide claim.

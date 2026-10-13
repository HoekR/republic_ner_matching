# Pathology corpus — run log

<!-- doc-status: active -->

Execution record for the pathology-corpus work, written **as it runs**. Plan:
`~/.claude/plans/linear-foraging-goblet.md`.

## What belongs here, and what does not

| goes here | goes elsewhere |
|---|---|
| the command actually run | numeric history → `svz.py metric` (it has `review` trend tooling; do not duplicate series here) |
| gate outcome, pass/fail, with the numbers that decided it | durable decisions → `docs/DECISIONS.md` |
| what was corrected mid-flight, and why | step verdicts a future session needs → the track doc |
| **orphan findings** — real observations that belong to no current step | placement/behaviour claims → the dataset + its provenance |

Written **at each gate**, as part of closing a step — tied to an event, not to intention. A log
nobody writes at a fixed trigger is a log that dies at step 4 (cf. `s6b_session_fingerprint_match`'s
"deferred to a follow-up session", which never happened).

**Terminus.** When this work closes, this log is the *source* for the three-part retirement entry
(`docs/ITERATION_POLICY.md`, "Retired step") — gate outcome / what it establishes regardless /
re-evaluate if. Then it stops. It is not an open-ended journal.

---

## Step 1 — Anchor contribution ledger on the three seed days

**Status: DONE, gate passed, reviewed** (2026-09-30). Final state after three review fixes:

| `1630-02-22` | |
|---|---|
| resolutions | 28 |
| with any group-A anchor | 10 |
| `nw_anchored` (DP takes a diagonal) | **8** |
| `nw_agrees_with_ledger` (agrees with row-local argmax) | 7 |
| `survived_tiered_monotonic_filter` | 9 (1 dropped) |
| tied resolutions | 3 (idx 7, 8, 11 — all `same_entity_set=True`) |
| path disagreements | 3 |

`1629-06-03`: 4 resolutions, 3 anchored, 0 ties, 0 disagreements. `1627-10-06`: 5 resolutions, 1
`nw_anchored`, 0 ties, 2 disagreements (`tiered_kept_nw_unplaced` at idx 2 and 4).

Note the sharpened reading: the DP anchors **8** of the 10 resolutions that carry any group-A
evidence and declines 2 (idx 7/8) — not "7 of 28". The earlier 7/28 figure conflated "the DP
anchored it" with "the DP agreed with the row-local argmax".

**Run:** `PYTHONPATH=. uv run python -m scripts.build_pathology_corpus --seeds`
Created `scripts/build_pathology_corpus.py` (ledger only; no manifest entry, no dataset write, no
span segmentation — those are Steps 2 and 5).

**Gate:** reproduce production's anchor scores on `1630-02-22` exactly. **All 24 checked cells
matched to 3dp**, including every zero row. Re-verified unchanged after the mid-flight correction
below, since that correction touched only the order fields, never the scoring.

### Correction made mid-flight: the brief named the wrong codepath

The original brief told the agent the monotonic filter is `clean_anchors`
(`build_alignment_new.py:838-851`). That belongs to `align_session_milestone_tiered` (`:795`),
which is **not the production placement path** — `s4_corpus_paragraph_predictions.predict()` calls
`align_session` (`:900`), which has neither `anchor_threshold=2.0` nor `clean_anchors`;
monotonicity there comes from the NW traceback itself.

Not a distinction without a difference: `anchor_set_reconciliation` measures the two anchor sets at
**65.7% agreement, 62.9% on exact position** (`data_manifest.toml:271`).

Fixed by recording **both** order facts under honest names — `taken_by_nw_traceback` (the
production fact) and `survived_tiered_monotonic_filter` (the parquet's provenance path, kept
precisely because the two disagree).

Also corrected `docs/writeup_mechanism_anchors.md:156`, which claimed the tiered variant "is what
production actually runs" — it contradicted `data_manifest.toml:656` and the code. Fixed in place
with a dated correction.

### A prior claim was overturned — `anchored_not_honoured` is not a pathology

Earlier the same day it was reported that `1630-02-22` idx 7–8 "carry a real anchor at paragraph 1
and were placed at paragraph 0 anyway". **Wrong.** The NW traceback takes neither as a diagonal
match at all — they are gap moves. Both **tie** at 3.688 across paragraphs 1 and 2, resting solely
on `'s Hertogenbosch`. Diagonals must strictly increase `j`, and idx 9 holds paragraph 1 at 16.224
(`Douglas` + `Herdersum` + `'s Hertogenbosch`). Forcing idx 7/8 diagonal there would cost idx 9 its
far stronger anchor — 7.376 combined against 16.224. The DP is trading correctly.

Same shape at idx 11: not "a strong anchor dropped for order violation" but a genuine tie
(`Herdersum`, 5.673 at both paragraph 1 and 4). Row-local argmax breaks it leftward; the global
traceback breaks it rightward to 4 — the only choice consistent with idx 10→2 and idx 12→5.

*Confidence:* numerically well-supported, not proven — the full 28×N DP table was not re-derived,
so an alternative higher-scoring configuration is not formally excluded.

**Consequence:** the plan's `anchored_not_honoured` span class was retired before Step 2 could mine
for it, and replaced with `tie_break_divergence` — ties on a recurring low-specificity entity, where
row-local and global readings diverge. That shape explains **every** disagreement found
(`1630-02-22` idx 7/8; `1627-10-06` idx 2/4). It is explicitly *not* scored as an error: the global
traceback was right in every case examined, so the class measures where a cheap row-local heuristic
would mislead — a methodology finding, not a defect count.

### Numbers

| | `1630-02-22` |
|---|---|
| `taken_by_nw_traceback` | 7 / 28 |
| `survived_tiered_monotonic_filter` | 9 / 28 (1 dropped: idx 11) |
| disagreements between the two | idx 7, idx 8 |

Other seeds: `1629-06-03` (4 res / 4 para) — 3 anchor cleanly in strict sequence, idx 3 has no
evidence, no disagreements. `1627-10-06` (5 res / 8 para) — only paragraph 0 is ever anchored; idx
1, 2, 4 all pin there, idx 0 and 3 have zero overlap anywhere; disagreements at idx 2 and 4.

### Orphan findings — real, belong to no current step

1. **Low-specificity entities generate the ties.** `'s Hertogenbosch` fires identically (3.688)
   across idx 7, 8, 9 and 10 of `1630-02-22`, and is the *entire* anchor for idx 7/8. Every
   row-local/global disagreement found at Step 1 traces to a tie of this kind. This bears directly
   on `plans/archive/COLLISION_AVOIDANCE_TRACK.md`'s working-hypothesis point 5 ("entity order is
   informative for all entities, not just rare ones… current scoring weights by IDF… and throws
   away order") and on the known weakness in `docs/writeup_mechanism_anchors.md`
   (`nw_matches_gt_rate` 0.957 correct vs 0.962 false-positive — the entity bag barely
   discriminates). No step currently owns it.
2. **Anchor strength is distributed, not carried by rare names.** `1630-02-22` idx 12's 28.734 is
   four moderate entities (`Sterken` 9.907, `Controlleur` 7.71, `Cornelisz` 6.473, `Brabant`
   4.644), not one rare outlier. Relevant to any future re-weighting.
3. **Parked, not a problem here — possible future NER review.** `Controlleur` is tagged `person`
   though it is an office, not a personal name. **User, 2026-09-30:** in early-modern usage the
   office stands for the person holding it, so the tag refers to a person in that quality — the
   anchor is doing real work and this is *not* a defect for this work. It may still be worth a look
   when the NER layer itself is next reviewed. Recorded so it is neither re-litigated as a bug here
   nor lost as an input to that later review.

---

## Step 1 review (2026-09-30, before running Step 2)

Ledger re-run and read directly rather than trusting the agent's summary. Gate **PASS** confirmed
independently. Three findings, all acted on.

**1. Ties were being discarded.** `if score > best_score:` (strictly greater) keeps the *leftmost*
tied paragraph and records nothing about the tie. Since row-internal ties are the mechanism behind
every row-local/global divergence found, the ledger was throwing away the central fact. Fixed by
adding `tied_paragraphs` / `is_tied`; `paragraph` unchanged so the gate still holds.

**2. Scope: this is a DP-input ledger, not an evidence ledger.** Its only source is
`build_axis_overlap` over the three overlap files — `tier1_entity_nw`, group A, **~7% of available
anchors** (measured: `1630-02-22` 9 of 132; `1629-06-03` 3 of 85; `1627-10-06` 3 of 75, from
`output/s6b_anchor_harvest.jsonl`). Correct for its gate (reproduce production's DP inputs), but it
structurally cannot distinguish *no evidence exists* from *evidence exists in a channel the DP cannot
see* — and that misreading was actually made during this session, calling 18 zero-score rows "zero
evidence". Cause: `align_session`'s `anchor_only_diagonal` gate makes groups B/C/D **structurally
invisible**, not merely down-weighted (`semantic_weight` defaults to 0.0). Deferred to
`plans/archive/STAGED_ANCHOR_CONSOLIDATION.md` Step 2, which must verify the char→paragraph join first.

**3. Step 2 restructured — forced vs chosen collapse first.** Per the abstention criterion (user,
2026-09-30), a span holding *k* resolutions in fewer than *k* paragraphs is provably unseparable at
paragraph granularity. `pigeonhole_floor` / `excess_over_floor` already compute this. **Forced**
collapse is a defensible abstention, not a pathology — reported, not mined, not queued for human
review. Only the **chosen** residue (pile above the floor) is classified. Without this gate a
corpus-wide run would mine a large population of provably-unresolvable gaps as though they were
bugs; on `1630-02-22` it is the difference between "9-deep pile" and "floor 3, excess 6, only the
excess actionable". The originally drafted `bracket_starved` and `zero_slack_collision` classes
overlap heavily with **forced** and are largely subsumed.

**4. One phenomenon was actually two.** The four divergences split into `row_tie_divergence` (one
resolution tied across paragraphs; `1630-02-22` idx 7/8, idx 11) and `column_contention` (several
resolutions with *different* scores all best-matching the same paragraph, only one of which can hold
a diagonal; `1627-10-06` idx 1/2/4 at paragraph 0, the day's only anchored paragraph). Conflating
them would have produced a muddled population.

### Second review pass, same day — two field defects found by reading raw output

Verified the tie fix by running the ledger directly rather than relying on the agent's summary. Gate
PASS; 3 ties on `1630-02-22` (idx 7, 8 at `[1,2]`; idx 11 at `[1,4]`), all `same_entity_set=True` —
so every tie is the single-recurring-entity shape, not a numerical coincidence. Zero ties on the
other two days, which **vindicates the row-tie / column-contention split**: `1627-10-06`'s idx 1/2/4
all anchor to paragraph 0, but for idx 2 and 4 that is the only scoring paragraph — nothing to tie
against.

Two defects visible only in the raw output, both fixed before Step 2 because they would corrupt its
classifier:

1. **`taken_by_nw_traceback` conflated opposite facts.** idx 11 is `False` with
   `nw_diagonal_paragraph=4` — the NW *did* anchor it, at the other tied paragraph. idx 7/8 are
   `False` with `nw_diagonal_paragraph=None` — not anchored at all. "Placed elsewhere" and "not
   placed" are opposite and need different treatment. Split into `nw_anchored` and
   `nw_agrees_with_ledger`.
2. **The disagreement detector hid the sharpest case.** It compared the two *booleans*, so idx 11
   was excluded (False under both). Substantively it is the most informative row on the day: **the
   NW path places it at paragraph 4 while the tiered path drops it entirely** — both False, for
   opposite reasons. Changed to compare *placements*, labelled by kind
   (`nw_placed_tiered_dropped` / `tiered_kept_nw_unplaced` / `both_placed_different_paragraph`).

**The idx 11 finding, now from data rather than inference:** tie at `[1,4]`, row-local argmax takes
1, the global traceback takes 4, and 4 is the choice consistent with idx 10→2 and idx 12→5. The
row-local reading is wrong, the DP is right, and this is a concrete instance of the 65.7% / 62.9%
path disagreement in `data_manifest.toml:271` — resolved in the NW path's favour.

### Orphan finding added

4. **Human-attention ranking needs a measure, and gap size is probably the wrong one.** Under the
   abstention framing, effort should go only to chosen collapse — but ranking *within* that by gap
   size may mislead: a 2-resolution gap can be cheap and unlock nothing, while a large one can
   unblock a whole session because a hand-resolved gap becomes a top-confidence anchor that may close
   adjacent gaps on the next pass. Rank by expected unlocked mass; measure it rather than assert it.
   Recorded in `plans/archive/STAGED_ANCHOR_CONSOLIDATION.md` as a to-define item.

---

## Step 2 — Span segmentation + corpus-wide classifier at width 0

**Status: Stage A implemented, not yet run.** Restructured into Stage A (forced vs chosen) / Stage B
(classify the chosen residue only) per the review above.

**Scope up, do not start corpus-wide** (user, 2026-09-30). Run one inventory or one month first, and
only widen once that output has been read. Rationale from Step 1's own history: three defects that
would have corrupted the classifier were invisible in summaries and only appeared on reading raw
rows — at corpus scale they would have produced ~1,100 days of silently wrong classification with no
obvious signal. A month is enough to see whether Stage A's forced/chosen split behaves, and cheap
enough to throw away. Suggested order: one month → one inventory → corpus. Per `CLAUDE.md` the user
runs heavy compute.

**Built:** `scripts/pathology_corpus_stage_a.py` — per-span (one anchor-bracketed gap in
`segment_day`'s backbone) `pigeonhole_floor` / `observed_pile` / `excess_over_floor`, classified
`forced` (pile == floor) vs `chosen` (pile > floor). Reuses `align_session` at production defaults
(no similarity wiring) so the anchors it sees are the anchors `segment_day` sees, and calls
`build_anchor_backbone` / `segment_gap` directly rather than re-deriving the DP's behaviour —
`build_anchor_backbone` was extracted out of `segment_day` (`scripts/s6c_gap_segmentation.py`) for
this, a pure refactor (`tests/test_s6c_gap_segmentation.py` still green, 21/21, no behaviour change).
No dataset write, no manifest entry — same posture as Step 1. Not run yet: per `CLAUDE.md` this is
the user's compute to run.

**Next action (user):**
`PYTHONPATH=. uv run python -m scripts.pathology_corpus_stage_a --month 1630-02`
(covers seed day `1630-02-22`) — read the raw per-span output before widening to one inventory,
then the corpus.

### Run result, 1630-02: 92 spans, 92 forced, 0 chosen — verified, not a bug

User ran the month; every span classified `forced`. Checked directly against the stored
`s4_corpus_paragraph_predictions` row and `s6c_severe_collapse_autopsy` for `1630-02-22`, since that
day is the plan's own "9-deep pile / floor 3 / excess 6" example and a null result there would have
been the sharpest possible sign of a bug.

**Confirmed real, not a bug.** The stored row does show `max_on_paragraph=9` (two piles of 9, at
paragraphs 0 and 7) and the autopsy computes `excess_over_floor=6` from the **whole-day** floor
`ceil(28/12)=3`. But the real anchor backbone (re-derived here, and matching Step 1's already-gated
ledger exactly: idx 9→1, 11→4, 12→5, 14→7, 23→8, 25→10, 26→11) puts both 9-piles in gaps with
**room=1** — the next real anchor is one paragraph away. Local floor there is `ceil(8/1)=8`; observed
pile is 8. `excess_over_floor=0`. Both piles are **fully forced** once anchor position is respected,
not 6-chosen as the day-level statistic implies.

**Consequence — not confined to this one day.** `s6c_severe_collapse_autopsy`'s `excess_over_floor`
(whole-day floor, ignores anchor position) overstates avoidable collapse whenever a day's anchors are
uneven, which is the common case (Step 1: DP anchors only 7-8/28 resolutions on solid days). Stage B's
plan (see linear-foraging-goblet.md Step 2) currently intends to attach this field as a day-context
cell as-is — that should be re-examined before Stage B runs, not trusted as "the" excess measure
alongside span-level `excess_over_floor`.

**Why the whole month is `chosen=0`, structurally, not just on this day.** No `position_scores` /
`resolution_scores` are wired at production defaults (the gated TF-IDF change is undecided, per
`tfidf-embeddings-wiring` in PLAN.md). `segment_gap`'s scoring with no bonus term is pure distance-
to-even-split minimization, which by construction lands at or near the pigeonhole floor. "Chosen"
collapse, as the plan's Context section framed it ("the unanchored default is capacity-blind"), is a
claim about evidence *warping* placement away from even-split — with zero evidence wired in there is
structurally little for Stage A to catch. This does not contradict `staged-anchor-consolidation`
(PLAN.md track 3); it sharpens it: the two room=1 gaps here are exactly what more anchors from groups
B/C/D would open up, not something Stage B's fill classifier can fix.

**Not yet done:** confirming this pattern (span floor == observed almost everywhere) holds across
more of the severe-collapse population before concluding Stage A closes with a structural null.

**Script extended:** `--severe-collapse-ambiguous` targets exactly the 58 (of 83 total)
`s6c_severe_collapse_autopsy` days with `cause_class` in `{axis_requires_repeats, room_on_axis}` —
the day-level-floor-is-below-7-but-still-reports-excess population, i.e. where the 1630-02-22
disagreement could recur. The other 25 (`pigeonhole_forced`) already have day-level floor >= 7,
so are not ambiguous and are skipped. Prints each day's span-level result next to its day-level
`cause_class` / `excess_over_floor` and flags `day_level_disagreements` where the day-level metric
claims nonzero excess but every span is `forced`.

**Next action (user):**
`PYTHONPATH=. uv run python -m scripts.pathology_corpus_stage_a --severe-collapse-ambiguous`
— 58 days, spans 1626-03-18 to 1630-05-03. Heavier than one month (58 lookup builds vs 28), but
still far short of corpus-wide, and it is the exact population this question is about.

### Run result, `--severe-collapse-ambiguous`: 58/58 days, 179/179 spans, zero chosen

Unanimous, not a trend. Every anchor-bracketed gap across all 58 days flagged
`axis_requires_repeats`/`room_on_axis` by `s6c_severe_collapse_autopsy` is exactly at its span-level
pigeonhole floor. `1630-02-22` was not a special case.

**Settles three things:**

1. `s6c_severe_collapse_autopsy`'s `excess_over_floor` measures nothing real for any of these 58
   days — the whole-day floor (`ceil(k_e/paragraph_count)`) is the wrong denominator across the
   whole population, not just once. Any downstream use of that field as "avoidable collapse"
   (`metrics_span_gap_map`'s `severe_collapse_implicated`, Stage B's planned day-context cell) is
   reading an artifact.
2. Stage A's "chosen" residue — the entire mining target Stage B (`linear-foraging-goblet.md` Step
   2) was scoped around — is empty in exactly the population most likely to contain it. Given
   `segment_gap` scores pure distance-to-even-split with no bonus term at production defaults, this
   is very likely structural (it always lands at the floor absent evidence), not a property of these
   58 days specifically — though that stronger claim is not formally proven here, only observed on
   179/179 spans.
3. Corroborates, does not contradict, `staged-anchor-consolidation` (PLAN.md track 3): the fill step
   is already optimal given its anchors; the lever is more anchors (groups B/C/D), not a smarter fill
   classifier.

**Open decision for the user:** Stage B as currently scoped ("classify the chosen-collapse residue
only") has no residue to classify under current default wiring. Options: (a) retire Stage B, fold
this null result into the pathology-corpus writeup as the finding itself; (b) re-scope Stage B to
mine `row_tie_divergence`/`column_contention` over *all* spans regardless of forced/chosen, since
those were originally about row-local-vs-NW-traceback disagreement (Step 1's tie mechanism), a
different axis from forced/chosen and not actually gated by it in the plan's own record schema; (c)
correct `s6c_severe_collapse_autopsy`'s `excess_over_floor` in place (would ripple into
`metrics_span_gap_map`'s `severe_collapse_implicated`). Not decided here — belongs in
`docs/DECISIONS.md` once chosen.

### Fix implemented (2026-10-01): anchor-aware span correction added to `s6c_severe_collapse_autopsy.py`

Picked a variant of option (c) from the open decision above: non-destructive rather than
in-place. Added `span_verdict_for_day` / `attach_span_correction` alongside the existing
whole-day fields instead of overwriting `excess_over_floor`, so `metrics_span_gap_map`'s
`severe_collapse_implicated` is untouched. `span_verdict_for_day` re-runs `align_session`
once per already-flagged severe day (~83, not ~1,100 corpus days) via
`pathology_corpus_stage_a.spans_for_day`, takes the gap with the worst `excess_over_floor`
on that day, and labels the day `anchor_forced` (worst gap at floor) or `chosen_excess`
(worst gap above floor) — a day is only "chosen" if at least one gap provably is.
`attach_span_correction` wires this into the day rows inside `main()`; the module docstring
carries the same note. Whole-day `pigeonhole_floor` / `excess_over_floor` / `cause_class`
are kept unchanged, for continuity and because `pigeonhole_forced` (whole-day floor) remains
a valid, anchor-independent lower bound on its own terms.

**Verified clean, not yet regenerated.** `python3 -m py_compile scripts/s6c_severe_collapse_autopsy.py`
and `uv run pytest tests/test_s6c_severe_collapse_autopsy.py -q` both pass (4/4). `main()`
itself — which re-runs NW alignment over the ~83 severe days and overwrites the
`s6c_severe_collapse_autopsy` dataset — has not been run; per `CLAUDE.md` that run is the
user's to trigger, not run by default here.

**Next action (user):** `PYTHONPATH=. uv run python -m scripts.s6c_severe_collapse_autopsy`,
then read the printed `span_verdict_totals` / `n_chosen_excess_days`. Given Step 2's 58/58
unanimous-forced finding above, a near-zero `n_chosen_excess_days` across the remaining 25
`pigeonhole_forced` days would confirm the pattern, not surprise it.

### Run result, full corpus regeneration: 85/85 severe days, `n_chosen_excess_days=0`

**Run:** `PYTHONPATH=. uv run python -m scripts.s6c_severe_collapse_autopsy` (user, 2026-10-01).
152 records written. `cause_class_totals={pigeonhole_forced: 25, axis_requires_repeats: 49,
room_on_axis: 11}` — 85 severe days total, up from 83 at Step 2's time (corpus/inputs moved
slightly between runs; not investigated, not material to this result). `span_verdict_totals=
{anchor_forced: 85}`, `n_chosen_excess_days=0`.

**This extends, not just repeats, the 58/58 finding.** Step 2's `--severe-collapse-ambiguous`
check covered the 58 `axis_requires_repeats`/`room_on_axis` days as of that run; this
regeneration covers the current full 85-day severe population, including the 25
`pigeonhole_forced` days (expected trivially forced, since their whole-day floor already implies
it) and the now-60 `axis_requires_repeats`/`room_on_axis` days (the population actually in
question). Zero exceptions anywhere.

**Settles the open decision above, for Stage B as scoped — correction below narrows what "settles" means.**
Stage B's mining target ("classify the chosen-collapse residue") is empty across the *entire*
severe-collapse population at production defaults, not a 58-day sample. Of the three options
listed there: (a) retire Stage B / fold this into the writeup as the finding, (b) re-scope Stage B
to `row_tie_divergence`/`column_contention` instead, (c) correct `excess_over_floor` in place —
this result makes (a) the only one with anything left to act on for the forced/chosen axis
specifically; (b) remains live as a *separate* axis (row-local-vs-NW-traceback disagreement, Step
1's tie mechanism, not gated by forced/chosen); (c) was done non-destructively instead (see
above) rather than in place, so the original dataset fields are preserved for any consumer still
reading them. Not yet written to `docs/DECISIONS.md` — this doc's own front matter says durable
decisions belong there, not here; do that before closing the track.

### Correction (2026-10-01): "0/85 chosen" is a group-A-only result, not a verdict on placement quality

The anchor backbone `span_verdict_for_day` re-derives comes from `align_session` at production
defaults — which, per `plans/archive/STAGED_ANCHOR_CONSOLIDATION.md` ("Groups B/C/D are structurally
invisible, not merely down-weighted"), only ever sees **group A** (tagger-entity overlap,
`tier1_entity_nw`), measured at ~4-7% of all harvested anchor evidence. So "every gap is forced"
means *forced given group-A-only evidence*, not "forced, period." Said plainly to the user when
first reported as "settles the decision" — that framing was too strong and is corrected here.

**Manually verified, not just inferred from code, on two of the 85 days (user asked for this
before trusting the aggregate):**

- `1629-06-26`: 20 resolutions, but the day's real HTR only breaks into **2 paragraphs** total
  (checked the actual Dutch text via `axis_for_date`). `pigeonhole_forced` — no anchor tier can
  fix this; the ceiling is paragraph-segmentation granularity itself (the separately blocked
  line-level track), not anchor coverage.
- `1630-01-05`: 20 resolutions, **17 real paragraphs** of text — room exists in principle. Yet 16
  pile onto one paragraph because the worst gap's anchor-bracketed window has `paragraph_room=1`:
  the nearest group-A anchors on either side sit right next to each other near the end of the day,
  so nothing can spread the other 15 resolutions across the 17 paragraphs a few lines away. This
  is exactly the shape more anchor tiers would target.

**Checked this isn't a one-off:** across the 60 days that are not trivially whole-day-forced
(`axis_requires_repeats` + `room_on_axis`), **36/60 have a worst gap with `paragraph_room=1`**
— an anchor-starved gap, not a lack of underlying text. Confirms `1630-01-05`'s shape is the
dominant one in this population, not an outlier.

**Consequence:** today's result is real (the fill algorithm, `segment_gap`, is already optimal
given what it currently sees) but it is not evidence to retire the anchor track — if anything
it is a concrete, corpus-measured argument *for* `staged-anchor-consolidation`: the lever left on
the table is anchor coverage (groups B/C/D), not a smarter classifier over group-A-only gaps.

### Field reference — the per-gap table (`spans_for_day`, `scripts/pathology_corpus_stage_a.py`)

| field | meaning |
|---|---|
| gap (enriched range) | `[left_enriched, right_enriched]` — the two anchored resolution indices bracketing this stretch; everything strictly between is unanchored |
| axis window | `[left_axis, right_axis)` — the paragraph range those two anchors pin, i.e. where the unanchored resolutions must land |
| unanchored | `unanchored_count = right_enriched - left_enriched - 1` — how many resolutions in this gap carry no anchor at all |
| room | `paragraph_room = max(1, right_axis - left_axis)` — how many distinct paragraph slots `segment_gap` has to place them in; mirrors `segment_gap`'s own slot count exactly, not re-derived independently |
| floor | `pigeonhole_floor = ceil(unanchored / room)` — arithmetic minimum: the least any single paragraph in this gap must hold under a non-decreasing assignment, regardless of algorithm |
| observed pile | `observed_pile` — the actual max resolutions-per-paragraph the DP (`segment_gap`) produced for this gap |
| excess | `excess_over_floor = observed_pile - floor` — 0 means the DP did exactly as well as arithmetic allows; positive means it piled up more than the room required |
| class | `collapse_class` — `forced` (excess ≤ 0, not a defect, not mined) vs `chosen` (excess > 0, Stage B's only mining target) |

The correction over `s6c_severe_collapse_autopsy`'s day-level `pigeonhole_floor` is that **room**
and **floor** here come from each gap's real anchor positions, not from the day's total
`paragraph_count` — see the 1630-02-22 result above for why that changes the verdict.

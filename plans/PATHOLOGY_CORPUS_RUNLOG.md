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
   on `plans/COLLISION_AVOIDANCE_TRACK.md`'s working-hypothesis point 5 ("entity order is
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
`plans/STAGED_ANCHOR_CONSOLIDATION.md` Step 2, which must verify the char→paragraph join first.

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
   Recorded in `plans/STAGED_ANCHOR_CONSOLIDATION.md` as a to-define item.

---

## Step 2 — Span segmentation + corpus-wide classifier at width 0

**Status: not started.** Restructured into Stage A (forced vs chosen) / Stage B (classify the chosen
residue only) per the review above.

**Scope up, do not start corpus-wide** (user, 2026-09-30). Run one inventory or one month first, and
only widen once that output has been read. Rationale from Step 1's own history: three defects that
would have corrupted the classifier were invisible in summaries and only appeared on reading raw
rows — at corpus scale they would have produced ~1,100 days of silently wrong classification with no
obvious signal. A month is enough to see whether Stage A's forced/chosen split behaves, and cheap
enough to throw away. Suggested order: one month → one inventory → corpus. Per `CLAUDE.md` the user
runs heavy compute.

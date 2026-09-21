# S4 iteration review (temporary)

**Status:** working document, not canonical. Captures one iteration's reasoning trail
in more narrative form than PLAN.md's compressed changelog allows, because this
iteration turned out to be non-straightforward — several steps changed the diagnosis
of an earlier step. Fold anything durable back into
[docs/SEGMENTATION_TRANSFER.md](SEGMENTATION_TRANSFER.md) or PLAN.md and delete this
file once the track stabilizes; don't treat it as a permanent doc.

---

## Session 2026-09-18

### Starting point

PLAN.md's S4 note ended with: *"A held-out tier-1 inventory ... now has 271 recurring
candidates ... integrate these as positional priors in the next S4 iteration."* That
read as an open task. First step was reviewing whether it actually was one.

### Step 1 — the "next iteration" turned out to already exist

Reading `scripts/s4_paragraph_axis_baseline.py` showed `PHRASE_DATASET =
"s4_opening_phrase_candidates"` already loaded and used in `phrase_hits` /
`snap_to_phrase` (lines 23, 161-162 before this session's edits). Checking output
timestamps confirmed the phrase inventory (`output/s4_opening_phrase_candidates.jsonl`,
15:58, 31 Aug) predates the baseline run that produced the "5/21 eligible days" result
(`output/s4_paragraph_axis_predictions.jsonl`, 16:01, same day, same git commit
`6743446`). So the "integrate as positional priors" framing in PLAN.md was written
*after* the code already did it — the PLAN.md prose narrated the later cut-rate
diagnostics (`s4_opening_phrase_cut_evaluation[_full].jsonl`, built 16:56 and the
next day) as if they preceded and motivated the integration, when they were actually
downstream measurements of an already-integrated signal.

**Lesson, generalized into docs/SEGMENTATION_TRANSFER.md §4.1:** a diagnostic that
measures hit rate directly at gold positions is not the same question as "does this
survive the real pipeline." This diagnostic scored 73.6%/76.4% at true cut points but,
per Step 3 below, only reached 1 of 5 real predicted days.

### Step 2 — root-causing the 16 `insufficient_entity_anchors` abstentions

Wrote a standalone diagnostic (not committed — see `Bash` history in this session's
transcript, not a repo file) reproducing `interpolate_positions`'s internal logic per
gold day, tagging each of the 21 eligible days with why it failed or succeeded.
Result:

| Reason | Count | Days |
|---|---|---|
| predicted (anchors sufficient) | 5 | 1626-02-28, 1627-12-07, 1628-01-27, 1628-12-26, 1629-03-02 |
| `axis_count < k_e` (structural: too few paragraphs globally) | 5 | 1626-04-04, 1628-04-04, 1628-10-26, 1628-11-24, 1630-01-22 |
| `gap_violation` (structural: too few paragraphs between two anchors) | 7 | 1626-01-08, 1627-08-19, 1627-10-05, 1629-10-15, 1630-02-16, 1630-02-27, 1630-03-20 |
| zero anchors, `k_e == 1` (code bug — no anchor should be required) | 2 | 1628-01-01, 1630-03-03 |
| no axis records at all (data gap) | 2 | 1626-05-17, 1627-04-11 |

12/16 abstentions (structural rows) confirm docs/SEGMENTATION_TRANSFER.md §9's own
predicted fallback: *"If K_p < K_e on a meaningful share of days, paragraphs are also
too coarse and cut points must be sought at line level."* 75% clears "meaningful
share." This was not fixed this session — it needs a line-level unit, a separate,
larger piece of work.

The other 4 abstentions split into a real bug (`k_e == 1` days need zero cuts but the
old code required ≥1 anchor unconditionally before returning anything) and a data
completeness gap (2 gold dates missing from `boundary_gold_paragraph_axis` entirely,
not investigated further this session).

### Step 3 — why phrase-snapping only reached 1 of 5 predicted days

User pushed back on the framing that phrase-snapping should unlock *more predicted
days* — correctly: that was never its job (anchor interpolation gates which days
predict at all; snapping only refines position within a day that already predicts).
The real question was why the phrase inventory, despite the 73.6%/76.4% direct hit
rate from Step 1, only touched 6/32 boundaries in the actual predictions.

Tested whether radius/threshold were the limiter (`max_distance` 2→4→8,
`levenshtein_threshold` 0.85→0.75): made no difference — every raw interpolated
position already finds *some* phrase hit within radius 2. So the limiter wasn't
signal coverage.

Traced it to `predict_day`'s revert logic: `snap_to_phrase` was called independently
per boundary, but if *any* two snapped positions in the same day collided (landed on
the same paragraph, breaking strict monotonic order), the revert discarded the
**entire day's** snaps, not just the colliding pair. Direct trace on
`1627-12-07`: raw `[1,2,3,4,5,6]` → naive-snapped `[1,2,3,4,4,4]` (positions 4,5,6 all
pulled toward the same nearby phrase hit) → reverted to all-raw. Same pattern in 3 of
the other 4 days; only `1628-12-26` had zero collisions and kept its snaps.

### Fixes applied

Both in `scripts/s4_paragraph_axis_baseline.py`:

1. `interpolate_positions` short-circuits to `[]` when `enriched_count <= 1` — a
   single-resolution day needs no cut points and shouldn't require an entity anchor
   to say so.
2. New `snap_boundaries` replaces the per-day all-or-nothing revert with a
   per-boundary, order-preserving greedy assignment: process boundaries left to
   right, accept a snap only if it stays strictly between the previously accepted
   position and the next raw position, otherwise fall back to that boundary's own
   raw position (not the whole day's).

4 new unit tests added to `tests/test_s4_paragraph_axis_baseline.py` (9/9 passing).

### Re-run result — read carefully, don't oversell

```
uv run python -m scripts.s4_paragraph_axis_baseline
uv run python -m scripts.evaluate_s4_paragraph_axis
```

- Predicted days: 5/21 → **9/21** (coverage 0.238 → 0.429)
- Phrase-snapped boundaries: 6/32 → **26/32**
- Exact-count satisfaction: 5/5 → 9/9 (still 100%, trivially so for the new days)
- Boundary micro F1 at tolerance 0: **0.576 → 0.576 (unchanged)**
- Boundary micro F1 at tolerance 2: **0.727 → 0.727 (unchanged)**

**Caveat:** all 4 newly-predicted days are `k_e == 1` trivial zero-boundary days (2 of
which have *zero* paragraph-axis records at all — they "predict" vacuously, with no
boundaries to get right or wrong). They inflate the coverage fraction without adding
real segmentation signal. On the original 5 real multi-boundary days, boundary
correctness against gold is **identical** before and after the collision fix, despite
most boundaries switching from raw interpolation to phrase-snapped positions. That's
not obviously wrong — it could mean the collision fix mostly relocated boundaries
that were already about as right/wrong as before — but it wasn't verified this
session (would need per-boundary gold-vs-predicted position diffing, not just the
aggregate F1) and shouldn't be assumed benign either way.

### Open items for the next S4 session

1. **Line-level segmentation** for the 12 structurally-abstaining days (paragraph
   axis coarser than `K_e`) — per docs/SEGMENTATION_TRANSFER.md §9, this is the
   anticipated next unit, not a tuning fix. **Still blocked, 2026-09-18 (corrected
   same day)**: the "cheap page→date overlap check" named as the next action turned
   out not to be cheap — no dataset in `data_manifest.toml` maps (inventory,
   scan/page) to date; `session_index_all.parquet` and
   `session_date_status_1626_1630` are both session-level only. Doing the join
   needs a new extraction step over the unextracted 10 GB
   `sessions_json-2026-02-27.tar.gz`. See docs/DECISIONS.md's second 2026-09-18
   entry ("Correct line-level-segmentation blocker...") and the updated
   `line-level-segmentation` note in `docs/state.json`. Do not start this as a
   quick check; it needs its own scoped step.
2. ~~`boundary_gold_paragraph_axis` data gap for 1626-05-17 and 1627-04-11~~ —
   **resolved 2026-09-18**: not a pipeline bug. Both are `k_e=1, k_f=0,
   flat_ids=[]` in `boundary_gold_sample.json` — the enriched record exists but no
   flat/HTR resolution was ever matched to it, the same `missing_htr` structural
   ceiling already accepted as final for `resolution_concordance_1626_1630`. Since
   `k_e=1`, both are trivial zero-boundary days with no segmentation signal at
   stake. See docs/DECISIONS.md 2026-09-18.
3. ~~Explain the F1-unchanged result~~ — **resolved 2026-09-18**: paragraph-axis
   granularity ceiling, not a scorer defect (gold repeats the same
   `paragraph_stream_index` across multiple boundary slots when the axis is
   coarser than `K_e`). See docs/DECISIONS.md's third 2026-09-18 entry.
4. Fold this file's durable content into PLAN.md/docs/SEGMENTATION_TRANSFER.md and
   delete it once resolved, per the note at the top. With items 2-3 closed and item
   1 re-blocked on a newly-scoped extraction step, S4 has no more cheap,
   already-scoped diagnostic work left on hand — the next session should either
   scope the sessions_json page-range extraction as its own step, or switch tracks
   per `svz.py review`.

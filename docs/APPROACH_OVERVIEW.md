# Approach overview — what exists, what it contributes, how it iterates

**Status:** working overview, written 2026-09-19, §1 row 0a / §5 / §6 updated 2026-09-21
(overlap-builder audit and rebuild swap completed; see `adopt-windowed-overlap-rebuild` in
`docs/state.json`). Complements
[SEGMENTATION_TRANSFER.md](SEGMENTATION_TRANSFER.md) (which frames the problem) and
[ITERATION_POLICY.md](ITERATION_POLICY.md) (which governs track choice) by mapping
*every* approach that exists in the repo against its contribution, metric, and
decision point — including the ones neither of those documents mentions because
they were never registered as tracks.

Written because the approaches had accumulated to the point where it was no longer
possible to see how they combine, what each contributes, or what is missing.

---

## The problem, once

Enriched resolutions (reliable per-day count `K_e`, no link to raw transcription)
and flat/HTR resolutions (continuous paragraph stream, no boundaries marked) do not
line up. Goal: map each enriched resolution to its flat/HTR text span.

---

## 1. Every approach, in one table

| # | Approach | Contributes / where | Metric | Current value | Decision point | Iteration relation |
|---|---|---|---|---|---|---|
| 0a | `build_per_overlap.py`, `build_windowed_overlap.py` → place/org/per overlap xlsx | Anchor input to Layer 1 | rebuild-vs-legacy row delta (place/org/per) | bug confirmed for all three (2026-09-19); all three canonical tables swapped to the variant/fuzzy-aware rebuild, zero regressions (`legacy_only=0`): place +1,265, org +55, per +415 rows (2026-09-19/21) | `excel-overlap-builder-audit` state.json `done`; `adopt-windowed-overlap-rebuild` state.json `inprogress` — swap done, downstream re-run (Layer 1 + B1 + corpus predictions) against the new tables still outstanding | Predates S4 pivot. Fix followed the same pattern `entity-resolution-fix` used for `build_alignment_new.py`; whether the anchor-density/coverage numbers below actually move is unmeasured until the downstream re-run happens |
| 0b | `entity_surface_matches_1626_1630` (`build_entity_surface_matches.py`) | Better entity-recall signal; consumed **only** by Layer 4 | rows recovered (exact/fuzzy) | 18,698 rows (11,330 exact + 7,368 fuzzy), 79s | `entity-resolution-fix`, state.json `done` | Built as the fix for 0a's bug class — but routed only forward to Layer 4, never back into Layer 1's anchors |
| 0c | `s4_fuzzy_surface_form_scan.py` | Full-dictionary entity recovery, corpus-wide | `already_known` vs `newly_recovered` | running (~7-9h), no result | **not in state.json** — ad hoc, no tracked decision | Added 2026-09-19. Flagged same session as possibly lower-leverage: 0b's scoped version already showed only modest downstream lift |
| 1 | `build_alignment_new.py` + `alignment_embeddings.py` + `alignment_llm_judge.py` | Tier-1 anchor set (`alignment_1626_1630`) | anchor density | 5,725 anchors / 13,342 rows ≈ 1 per 2.3 (~78%) | Accepted baseline; no separate stop/go on record | Predates S4 pivot. **Already uses a local LLM as judge** — precedent for the Layer 4 LLM work, not a new pattern |
| 2 (A) | `session_date_status_1626_1630` ledger (S4a-c) | Day-level session match; feeds Layer 3 **and** Layer 5 | rows by status code | 4,916 rows: T=1,012, A=4, E=97, X=3, N=3,800; 49.7% `missing_htr` | S4a/b/c `done` | Built on Layer 1's output; closed once the structural ceiling was confirmed |
| 3 (B1) | `s4_paragraph_axis_baseline.py` — entity-anchor interpolation | Within-day paragraph-level cuts | predicted-day coverage; boundary micro-F1 @ tol0/tol2 | coverage 0.238→0.429; F1 0.576/0.727 (flat) | DECISIONS.md 2026-09-18: F1 is a **paragraph-granularity ceiling**, stop tuning interpolation/snapping for it. Coverage still open | Iterated repeatedly 2026-09-18/19: anchor-sparsity fix → coverage jump; snap-collision fix → F1 unchanged, root-caused |
| 3 (B2) | `align_short_resolutions.py` — phrase-anchor alignment for "no decision" resolutions | Within-day alignment for a **different subset** than B1 | **none recorded** | unknown | **not in state.json** — invisible to `svz.py review` | Built once, never iterated. **Verified orphaned**: output referenced nowhere else in the repo |
| 4 (C) | Interior cuts in B1's bundled paragraphs: entity even-split → +0b dictionary → few-shot local LLM (`s4_llm_split_poc.py`) | Sub-paragraph cuts | recall @ tol50 / tol150, 22-position gold set | 0/27→3/27 (tol50); 9/27→11/27 (tol150); LLM pending | Undecided — active. A win needs a **finer-grained harness** before it can register as tracked progress | Tight chain: entity-density diagnostic (effect size 0.77) → heuristic baseline → dictionary lift → LLM (sidesteps entity-quality dependency) |
| 5 (D) | `s4_resolution_concordance.py` | One row per enriched resolution: day status + B1 attribution + `cross_day_shift` / `inventory_ambiguous` | status distribution | `resolved_auto` 70.7%, `missing_htr` 28.6%, `nihil_actum` 0.6% | `resolution-concordance-completeness`, state.json `done` (accepted final 2026-09-18) | Consumes Layer 2 + B1 only. Closed **before** B2, 0b, 0c and Layer 4 reached their current form; never revisited |

---

## 2. What actually connects

```
Layer 0a overlap builders (bug confirmed + fixed, rebuild swapped in) ──→ Layer 1
                            (downstream re-run against the new tables still pending)
Layer 0b entity_surface_matches (better signal) ─────→ Layer 4 only
Layer 0c fuzzy_surface_form_scan ────────────────────→ nothing yet

Layer 1  build_alignment_new.py (+embeddings, +LLM judge) ──→ alignment_1626_1630
Layer 2  session_date_status ledger ──→ Layer 3 (B1, B2) and Layer 5 (D)
Layer 3  B1 paragraph-axis ──→ Layer 4 (interior cuts) ──→ nothing
         B2 short-resolution ─────────────────────────────→ nothing (verified orphan)
Layer 5  D concordance ← Layer 2 + B1 attribution only
```

**Only one path reaches the final integration point (D):**
`0a → 1 → 2 → B1 → D`. The better entity signal (0b), the corpus-wide scan (0c),
the short-resolution work (B2), and all of Layer 4's interior-cut work currently
dead-end before D, however good each is on its own.

---

## 3. Why iteration only happened on one branch

Confirmed with the user 2026-09-19, and the mechanism matters more than the fact:

Every iteration cycle in the 2026-09-18/19 sessions happened inside the `B1 → C`
branch. Not because the other branches were tried and rejected — because **that is
the only branch with an evaluation harness attached to it.** B1 has predicted-day
coverage and boundary F1; C has the tol50/tol150 gold harness. B2 has no recorded
metric at all; 0a has no metric of its own. A branch with a number attached invites
another turn of the crank; a branch without one offers nothing to iterate against,
so it silently stops receiving attention.

The same mechanism explains the code-level disconnection. B2 and 0c are not merely
unwired — they have **no entry in `docs/state.json`**, so `svz.py review` cannot
surface them for a continue/close decision, and `svz.py doctor` cannot detect them
either (it validates state.json's internal consistency, never cross-checks it
against what exists in the repo). Work that is not registered is not measured; work
that is not measured is not iterated; work that is not iterated silently becomes an
orphan. All three symptoms have one cause.

---

## 4. What is missing: an orchestrator

[STATE.md](STATE.md) and [`scripts/svz.py`](../scripts/svz.py) exist precisely to
solve this: they were built because without an overview it is easy to disappear
into a rabbit hole. That instinct is right and the machinery is roughly two-thirds
of an orchestrator — it records state, tracks metric history, and classifies
trends. The requirement it does not yet meet, stated 2026-09-19:

> iterative tasks should report to an orchestrator, that talks with me about
> decision points and proposes next steps, with a reason and a goal

The missing third is **the proposal**, and it happens to be the part that actually
prevents rabbit holes. Reporting status still requires the reader to do the
prioritising — and someone already deep inside one branch is the person least
likely to notice they should be somewhere else. That is exactly when the tool needs
to say "go here instead, and here is why," rather than handing back a status board.

Three specific gaps:

| Gap | Current behaviour | What the orchestrator needs | Status |
|---|---|---|---|
| **Registration** | `doctor` validates state.json against itself: duplicate ids, invalid statuses, orphan metric scopes. It never asks whether a script in the repo has a corresponding task. B2 is invisible as a result. | Detect work that exists but is not registered. Nothing gets built without a task entry, even if that entry is opened and closed in the same breath. | **Partly closed** 2026-09-19: the three known orphans are now registered (`short-resolution-alignment`, `fuzzy-surface-form-scan`, `interior-cut-evaluation-harness`). Automatic detection of *future* orphans is still missing. |
| **Reporting back** | `svz.py metric` is a manual, optional call. ITERATION_POLICY.md names skipping it an anti-pattern but nothing enforces or detects it. | An iteration is not finished until it has pushed a result — metric, outcome, and a proposed next step — back to the tracking layer. | **Open.** `review` now flags unmeasurable tracks loudly (they get a ranking bonus precisely because they cannot be judged), but nothing enforces write-back. |
| **Proposal** | `review` classified each metric's trend, then stopped at *"See docs/ITERATION_POLICY.md before switching tracks."* It handed the decision back with no recommendation. | Name the recommended next step, the **reason** it is recommended, and the **goal** that would count as success — then put that in front of the user as a decision point, not a menu. | **Closed** 2026-09-19: `review` ends with a `== Proposed next step ==` section. See below. |

**The 2026-09-19 session is the worked example.** `svz.py review` was run at the
very start and did its job correctly: it reported S4's boundary F1 as stagnant with
two cutoff candidates, and listed four other open tracks. The session then spent
itself inside the `B1 → C` branch anyway, plus a long detour into local-LLM
infrastructure (Ollama vs LM Studio vs MLX, memory pressure, an external drive
holding model weights) — none of which advanced any track in §1.

The status report was accurate and was read. It simply did not say what to do, so
the choice fell to momentum: the branch with a harness already attached. An
orchestrator that had answered *"audit the overlap builders first — they are
upstream of every other track in the table, the check is cheap, and nothing
downstream can be trusted until it passes"* would have produced a different and
better session from the same starting information.

---

### 4.1 How the proposal step works (built 2026-09-19)

`svz.py review` now ends with a recommendation rather than a status board.

- **Ranking is by leverage, then cheapness — never by momentum.** A track's score is
  driven by how many other tracks it is upstream of (`blocks`), then by `cost`
  (`cheap` > `session` > `multi-session`). A track with no metric gets a bonus,
  because an unjudgeable track is a defect worth surfacing, per ITERATION_POLICY.md.
- **The reason distinguishes open from closed downstream tracks.** "If this fails,
  2 closed tracks become suspect" is a sharper argument than a raw dependency count,
  and it is the reason the overlap-builder audit currently outranks everything else.
- **Tasks carry `next_action`, `goal`, `cost` and `blocks`** (set via
  `svz.py update --next-action/--goal/--cost/--blocks`). `next_action` falls back to
  parsing a `Next action:` sentence out of existing notes, so tracks that already
  had one work without migration. `doctor` validates `blocks` references and `cost`
  values.
- **In-progress tracks are not assumed to continue.** Each is printed with a verdict:
  improving → continuing is defensible; stagnant → surface to strategy and record a
  decision; no metric → cannot be judged, record one or close it.

### 4.2 Control flow: subtasks return to strategy

Agreed 2026-09-19. Finishing a subtask is fine; *descending further from it* by
default is not.

1. **Revert means recompute, not resume.** After a subtask ends, re-run `review` so
   the next call is computed from the new state. A completed subtask can change
   which track is highest-leverage, so popping back to a previously queued plan is
   wrong.
2. **Termination writes back.** "Finished or terminated" must produce a metric, an
   outcome, and a reason — otherwise the descent's cost is lost and the same hole
   gets re-entered in a later session.
3. **Descents get a budget, and breaching it triggers an early surface.** A subtask
   may legitimately spawn a sub-subtask, but when the cost runs past what the
   experiment is worth, that is itself a reason to surface and ask, rather than to
   keep going.
4. **Revert is the default, not a cage.** The orchestrator recommends surfacing; the
   user can always say "stay on this."

## 5. Open questions

1. ~~Is 0a's unaudited bug silently degrading Layer 1's anchors, and through them
   everything downstream?~~ — **bug confirmed and fixed 2026-09-19/21** (literal-substring
   matching in all three overlap builders, strictly-additive rebuild now canonical). Whether
   it actually *was* degrading Layer 1's anchors is still open until the downstream re-run
   (`build_alignment_new.py`, `s4_paragraph_axis_baseline.py`, `s4_corpus_paragraph_predictions.py`)
   is done and the anchor-density/coverage/F1 numbers are compared before vs. after.
2. Should 0b replace 0a as Layer 1's anchor input, not just feed Layer 4? Never
   evaluated.
3. Was B2 meant to feed D, or was it exploratory? No decision on record either way.
4. Of 19,133 enriched resolutions, how many have paragraph attribution from **any**
   path, and how many from none? This number does not exist today.

---

## 6. Recommended order

1. ~~Register B2 and 0c as real tasks~~ — **done 2026-09-19**, plus
   `interior-cut-evaluation-harness`.
2. ~~Build the proposal step into `svz.py review`~~ — **done 2026-09-19**, see §4.1.
3. ~~Run `excel-overlap-builder-audit` (0a).~~ — **done 2026-09-19/21**: bug confirmed for
   place/org/per, all three canonical overlap tables swapped to the zero-regression
   variant/fuzzy-aware rebuild. Tracked now as `adopt-windowed-overlap-rebuild`.
4. **Re-run downstream consumers** (`build_alignment_new.py`,
   `s4_paragraph_axis_baseline.py`, `s4_corpus_paragraph_predictions.py`) against the
   swapped tables and record whether anchor density / boundary F1 / predicted-day
   coverage move — heavy compute, left for the user to run; this is the one open action
   on `adopt-windowed-overlap-rebuild`.
5. Then: decide, against the coverage number from question 4 above (§5), whether B2 and
   0b are worth wiring into D or should be formally retired.
6. Still open from §4 (orchestrator gaps): automatic detection of *future* orphans
   (registration), and enforced write-back when an iteration ends (reporting back).

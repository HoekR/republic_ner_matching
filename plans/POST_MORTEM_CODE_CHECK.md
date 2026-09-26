# Post-mortem manual code check — S6/segmentation-transfer track

<!-- doc-status: active -->
<!-- status: closed 2026-09-25 — all 5 items done; 3 carried-forward candidates logged below and in docs/DECISIONS.md -->

## Goal

Manually inspect the code behind the closed segmentation-transfer result (Global-primary MET at
68.8% of ceiling, `s6-anchor-chain-alignment` closed 2026-09-23) for anything worth learning —
not to reopen the track. This is a read-only audit, not an optimization attempt.

Guardrail: must not change production concordance, S6c segmentation, or frozen datasets. Any fix
found here is logged as a candidate, not applied inline, unless it's a trivial dead-code prune.

## Why these five

Picked from `docs/SEGMENTATION_RESULTS.md` §5 (successes/pitfalls) — each item below is chosen
because it's the exact shape of bug that already bit this project once (staleness, silent
id-as-name), or it's the piece carrying the most signal so a bug there has the most leverage.

## Checklist

### 1. `scripts/s4_resolution_concordance.py` — staleness risk
<!-- status: done 2026-09-25 -->

Re-run of this exact script (no logic change) alone moved Global-primary 16.8%→68.8%
(docs/DECISIONS.md 2026-09-23). Check: does it read `s4_corpus_paragraph_predictions` and the S6c
DP output fresh on every run, or does anything cache/pickle an intermediate that could silently go
stale again?

**Finding:** The script itself is clean — `main()` loads all four inputs
(`enriched_resolutions_1626_1630`, `s4_day_status_resolution`, `resolutions_flat`,
`s4_corpus_paragraph_predictions`) fresh via `data_io.load()` on every invocation; no caching or
pickling in-process, so it can't itself go stale mid-run.

The real gap is one level up: `data_io/check.py` (`uv run python -m data_io.check`) only verifies
that each manifest dataset's tier is mounted and its file exists — it never compares a dataset's
recorded `parent_sources`/timestamp (already captured in each `*.provenance.json` sidecar via
`save_parquet`) against its parents' current provenance. So nothing in the tooling would catch a
second instance of the exact bug that already happened: `resolution_concordance_1626_1630` sitting
3 rebuilds behind its own stated inputs for about a week, undetected until someone thought to
re-run it. This is a real, reusable gap, not just a note — candidate for a small
`data_io.check --freshness` extension that flags a dataset whose provenance-recorded parent
versions are older than the parents' current provenance. Logged here as a candidate, not built.

### 2. `scripts/s6c_gap_segmentation.py` (`segment_gap`/`segment_day`) — abstention design + cost function
<!-- status: done 2026-09-25 -->

Confirm it never abstains (always emits `K_e−1` cuts) and that repeated-paragraph-index
placements are scored as "not separated" downstream, not miscounted as a hit. Also check the cost
function's current weighting doesn't reintroduce entity-density-as-boundary-signal — the exact
mechanism 5 independently-designed Group-B/C variants already measured as net-negative.

**Finding:** All three hold up.
- `segment_day` never abstains — always returns `enriched_count - 1` positions; `segment_gap`'s DP
  always fills all `count` slots (repeats allowed by construction when the gap is too narrow).
- The production caller, `scripts/s4_corpus_paragraph_predictions.py:108-125`, passes
  `position_scores=None` by default — the comment there is explicit that this keeps the live
  default unchanged and that Group-B evidence only flows through it via the separate offline
  `scripts/s6_group_b_*_eval.py` scripts, never the production path. So the net-negative Group-B/C
  mechanism is not live in production, only in already-measured, already-rejected experiments.
- `metrics_separation_span_table.py:80-88` correctly demotes any date+start-paragraph collision
  (`n_share == 1` check) to not-separated, so a repeated-position placement from an abstention-free
  DP is scored as a miss, not miscounted as a hit. No issue found.

### 3. `scripts/s6b_anchor_harvest.py` — Group B/C wiring after the negative result
<!-- status: done 2026-09-25 -->

Group-B/C evidence was consistently negative for placement. Check whether it's still consumed
anywhere beyond the closed position_scores experiments (e.g. concordance fallback) without having
been measured there.

**Finding:** No live consumer at all, in either direction.
- `s6b_anchor_harvest.py` writes dataset `s6b_anchor_harvest` (`data_manifest.toml:260`). Repo-wide
  grep for that dataset name outside this file itself turns up only prose docstring mentions in
  `s4_paragraph_axis_baseline.py` and `s6c_gap_segmentation.py` ("s6b_anchor_harvest.py's existing
  pattern" / timing reference) — neither actually calls `load("s6b_anchor_harvest")`. So this
  harvest output is genuinely orphaned in-repo: nothing downstream reads it, production or
  experimental.
- Separately, the Group-B position-scores *eval* scripts (`s6_group_b_*_eval.py`) don't even go
  through this harvest file — they load `entity_surface_matches_1626_1630` directly and feed it
  into `s4_corpus_paragraph_predictions.py`'s `predict()` for the closed, already-negative
  experiment. Confirms item 2's finding from the other direction: the negative-result evidence
  path is fully contained in the offline eval scripts, doesn't touch production, and this harvest
  script's own output isn't even part of that path.
- Not a bug, but a real dead-code candidate: `s6b_anchor_harvest.py` (589 lines) computes and
  writes a dataset nothing reads. Worth a one-line note in `docs/APPROACH_OVERVIEW.md`'s
  orphaned-work section if it isn't already there — not deleting it here per the plan's
  read-only guardrail.

### 4. `build_alignment_new.py` — Group A entity NW (the backbone channel)
<!-- status: done 2026-09-25 -->

Carries most of the signal (~43% tier-1 anchors via `resolution-concordance` / `entity-resolution-fix`).
Already had one silent id-as-name bug fixed here. Check the entity id→name resolution path for a
sibling bug in a similar lookup pattern for a different entity type that the original fix didn't
touch.

**Finding:** No sibling *bug*, but a real dead-code finding of the same family, in
`resolve_enriched_entities()` (`build_alignment_new.py:342-377`). Persons and institutions get a
richer resolution layer added by `entity-resolution-fix` (`persons_info`, `institution_names`)
because enriched `persons`/`institutions` really are opaque numeric ids (verified directly:
`enriched["persons"] == ['791967']`, `enriched["institutions"] == ['14']`). Places never got an
equivalent layer — but a direct check of the live data shows they didn't need one and the existing
code is a no-op: `enriched["places"]` already contains plain names (e.g. `['Emden']`, `['Venlo']`),
never `LOC-entities.json`'s `L0006150`-style ids. Checked the full corpus: **all 21,184 enriched
place references miss `loc_names`** (0% hit rate) and fall through the `.get(str(item), str(item))`
fallback to the identity value — which is correct output only because the fallback happens to equal
the input for this field. So `loc_names`/`LOC_ENTITIES_FILE` loading and lookup in this function is
dead weight, not a correctness bug: it produces the right answer by accident of the fallback
matching, while implying (to a reader) that places need id resolution the same way persons/orgs do.
Worth a follow-up cleanup (drop the `loc_names` lookup for `places`, keep it only where LOC ids
genuinely appear elsewhere in the file, e.g. line 1408) — not done here per the read-only
guardrail.

### 5. `scripts/metrics_local_inventory_ceiling.py` — cited-constant sanity check
<!-- status: done 2026-09-25 -->

Confirm a fresh run still reproduces 11,644 (ceiling) and 535 (no-HTR dates) exactly, and that
`resolution_concordance_1626_1630`'s row/date counts still match what PLAN.md cites (1,594 dates).

**Finding:** Clean re-run, `uv run python -m scripts.metrics_local_inventory_ceiling`:
`corpus ceiling: 11644 (expected 11644)`, `no-HTR dates: 535 (expected 535)`, both exact matches.
The 5 annual inventories (3185-3189) still clear the Local ≥50%-of-own-ceiling criterion
(63.9%-72.3%), the 2 non-annual ones still don't (10.5%, 0.0%) — matches STATE.md exactly. No
staleness or drift found; this constant is still live and correctly scripted.

## Deliverable

One line per item above (finding or "no issue found"), plus, if anything is confirmed, one entry
in `docs/DECISIONS.md`. No code changes unless a finding is a trivial, zero-risk dead-code prune —
otherwise log as a candidate for a separate, explicitly scoped fix task.

## Closed 2026-09-25 — carried-forward candidates

All five items are done. Three findings are real but were deliberately not applied under the
read-only guardrail; recorded here and in `docs/DECISIONS.md` so they do not evaporate with this
document. None is a correctness bug, and none blocks current work.

1. **`data_io.check --freshness` (item 1) — the only one with reuse value beyond this repo.**
   `data_io/check.py` verifies that a manifest dataset's tier is mounted and its file exists, but
   never compares its recorded `parent_sources`/timestamp against its parents' *current*
   provenance. The exact bug that already cost this project a week —
   `resolution_concordance_1626_1630` sitting three rebuilds behind its stated inputs, undetected
   until someone thought to re-run it — would be equally invisible a second time. Sidecars already
   carry what a check would need.
2. **Dead `loc_names` lookup for `places` (item 4)**, `build_alignment_new.py:342-377`. All 21,184
   enriched place references miss `loc_names` (0% hit rate) and fall through to the identity
   fallback. Correct output by accident of the fallback matching the input, while implying to a
   reader that places need id resolution the way persons and institutions genuinely do.
3. **`s6b_anchor_harvest.py` output is orphaned (item 3).** 589 lines computing a dataset no code
   loads, in either the production or the experimental path. Worth one line in
   `docs/APPROACH_OVERVIEW.md`'s orphaned-work section rather than deletion — the harvest answered
   its question (anchor supply is not the bottleneck) and the answer is recorded elsewhere.

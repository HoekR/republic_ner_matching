# Iteration policy — deciding what to work on next

This project runs several independent-ish research tracks over time (S4 segmentation transfer,
line-level segmentation, Track B/C name matching, the HOE classifier's `other` bucket, etc.). Each
track can absorb arbitrary further effort without an external signal to stop, and none of them
naturally hands off to another. This is the discipline for choosing which track gets the next
session, and for recognizing when a track should be closed instead of continued.

## Mechanism

- `docs/state.json` (rendered to `docs/STATE.md`) is the source of truth for track status and
  metric history. Every track is one entry in `tasks`.
- A track's metrics live in `metrics`, keyed by `scope` == the task's `id` (or `<id>-<subid>` for a
  finer-grained diagnostic under that track). Record one with:
  `uv run python scripts/svz.py metric <task-id> <metric-name> <value> --label "..."` — this appends
  to the metric's `history`, it does not overwrite it. A track with no recorded metric can't be
  judged; that's a defect to fix by recording one, not a reason to skip the check.
- At the **start** of a session, run `uv run python scripts/svz.py review` and read the "Active
  tracks needing a decision" section before choosing what to work on.

## Definitions

- **Improving**: the latest recorded delta on a metric exceeds the relative threshold (default 3%,
  `--threshold` on `review`), in the direction that matters for that metric (state it when you
  record the metric — e.g. F1 up is good, `other`-bucket share down is good).
- **Stagnant / cutoff candidate**: the most recent delta is within the threshold of zero.
  One stagnant reading is a flag, not a verdict — check whether the session that produced it
  actually targeted that metric, or was working on something upstream of it. Worked example: the
  2026-09-18 S4 session fixed a real bug (per-boundary snap-collision revert) and coverage jumped
  0.238 -> 0.429 (`review` correctly calls this "improving"), but boundary F1 stayed at
  0.576/0.727 exactly (`review` flags this "stagnant <- cutoff candidate"). That flag does **not**
  mean stop working on S4 — it means "the fix that moved coverage did not move F1, and nobody has
  explained why yet," which is itself the next concrete task, not a signal to abandon the track.
- **Structural ceiling**: a documented, verified reason further work on this metric can't move it
  (e.g. the `missing_htr` 49.7%-of-ledger coverage ceiling, or a confirmed zero-overlap ground-truth
  gap like `res_start` or `htr_classified_lines.csv` against inventories 3185-3189). Distinguished
  from ordinary stagnation because it is backed by a specific diagnostic, not "we tried a bit and it
  didn't move."

## Choosing the next track

1. Prefer a track flagged **improving**, or one with a concrete, already-scoped next action, over
   one that needs new tooling or unverified data acquired from scratch — cheaper to keep momentum
   than to cold-start. A "next unit" named in a design doc is not automatically ready; verify its
   prerequisite data actually exists for this project's specific scope before scoping engineering
   work around it (see the line-level-segmentation entry in `docs/state.json` for why).
2. Among ready tracks, prefer the one with more remaining headroom below its plausible ceiling — a
   track at 95% of a metric with a ~97% ceiling is lower priority than one at 45% with no known
   ceiling nearby.
3. A **stagnant** track is not automatically dropped. First check whether the session that produced
   the reading actually targeted that metric. Only treat repeated (2+) stagnant readings *after*
   sessions that directly targeted the metric as a real signal to consider closing it.
4. A track that hits a **structural ceiling**, or whose next step turns out to depend on data that
   does not exist for this project's scope, should not sit `inprogress`/`todo` indefinitely: record
   the finding via
   `svz.py decision "<title>" --context ... --decision ... --reason ...`
   (see `docs/DECISIONS.md`'s 2026-09-18 entries for the shape — one closes a track as final, the
   other blocks a track pending a specific cheap verification) and set the task's `state.json`
   status to `done` (current result accepted as final) or `blocked` (stuck pending something
   specific and named).
5. This is a decision aid, not a formula. `svz.py review` only classifies trend direction from
   recorded numbers; the continue/switch/stop call stays with whoever reads the report (human or
   agent), consistent with this repo's "advisors and editors, not operators" convention
   (`docs/wisdom/cost-sensitive-agent-workflow.md`).

## Anti-patterns

- Working a track for multiple sessions without ever running `svz.py metric` — there is nothing for
  `review` to compare against, and the whole mechanism goes quiet.
- Treating a single stagnant reading as a hard stop without checking whether the metric was
  actually targeted that session.
- Assuming a design doc's "supervision/data already available" claim still holds for this project's
  actual scope (inventories, date range) without checking — verify against the real files first;
  see `docs/SEGMENTATION_TRANSFER.md` section 9's corrected line-classification-coverage note for
  what this looks like when the claim turns out to be wrong.
- Leaving a track that hit a structural ceiling marked `inprogress` — close it out with a decision
  entry so future sessions don't re-litigate it from scratch.

## See also

- `docs/STATE.md` / `docs/state.json` — current track status and metric history.
- `docs/DECISIONS.md` — durable stop/continue/scope decisions.
- `docs/wisdom/cost-sensitive-agent-workflow.md` — the broader "one step per session, user runs
  heavy compute" discipline this policy operates inside.

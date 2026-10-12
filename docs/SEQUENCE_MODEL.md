# The sequence model (rode draad)
<!-- doc-status: active -->

## Why this document exists

The project has seven active tracks, four scripts that each re-derive the same correspondence, three independent "difficulty = 2" thresholds, and a closed taxonomy registered inside a `main()` and nowhere else. Nothing ties them together, so every new measurement invents its own unit, denominator and yardstick. On 2026-10-08, four of five such inventions were wrong in the same way: each reached for whatever was nearest to hand instead of deriving it from what the project already held.

The one rule that *stopped* being broken was the one made executable (`scripts/corpus_scope.py`): *"a rule that only lives in `plans/*.md` is a rule that gets broken."* This document applies that lesson to the model itself. It exists to stop being broken.

Its tone follows the scope bar precedent: `scripts/corpus_scope.py` implements one guard (`in_scope`, `drop_out_of_scope`), with tests that pass/fail together. This document's spine block is promoted into the four loaded instruction files (CLAUDE.md, AGENTS.md, .cursor/rules/project-standards.mdc, .github/copilot-instructions.md) the same way the scope bar was — a short rule, a pointer to the enforcing machinery, and a note about tests.

## Sitting ≡ session — a synchronisation problem

**User, 2026-10-09:** sitting and session refer to the **same** thing — one HHM meeting. The
three sequences below are **separate evidence / representations** of that phenomenon, not three
different events. The open problem is **synchronisation**: aligning those representations (which
scan / HTR block / editorial date name the same meeting), not matching two unlike populations
competing for slots. Graph node types `SittingDay` and `Session` stay distinct because their
*sources* differ; correspondence edges (`PINNED_TO`, `DATED_AS`, …) are the sync links.

**Broad gaps (user, 2026-10-09):** do not treat unsynced mass as “outside” the model. A sync gap
is the **full bracket** between consecutive production anchors on the HTR chain: all editorial
`k_e` and all interior HTR paragraphs in that calendar/session span, whether or not a pin already
exists. Measure with `uv run python -m sequence_graph.sync_gaps` → `sequence_graph_sync_gaps`.

**Entity comparison is sequence comparison (user, 2026-10-09):** inside a bracket, align the
ordered editorial stream against the ordered HTR stream (`align_bracket`); pairwise entity
overlap is only the cell cost. Proof protocol: gold / silver / projection
(`sequence_graph.sync_gap_align --prove`); MATCH cells are plowed back as `ALIGNED_TO:solver`
(`--push-graph`). Perfection is not the gate — ordered evidenced MATCH paths are.

**Sync gaps / trusted brackets are work views, not ALIGNED_TO containers (user, 2026-10-11):**
pin lids must not redefine membership. Soft-window hand-off
(`sequence_graph.sync_gap_align --trusted-brackets`) expands seed geometries by calendar/session
margins; locality is cost (rescaled openings, optional day decay), not a sealed box. Gaps remain
useful *report* slices of where mass sits.

## The three sequences

| sequence | order | status |
|---|---|---|
| **physical** — scans in book order per inventory | `scan_num` | **observed** in `resolution_archival_provenance.scan_ids`; absent from every model |
| **HTR** — sessions → resolutions → paragraphs | `(session_num, resolution_num, para_index)` | observed within itself; `stream.py:131` proved flat order *is* physical order |
| **editorial** — sitting days → enriched resolutions | date, `resolution_index` | observed within itself; the XML has no physical grounding (`Stgen.dtd` has no folio/page/scan element) |

`running_axis` holds sessions and dates in one object with the pin denormalised across both sides (`place_anchor` writes `DateState.resolved_session_id` *and* `SessionSpan.resolved_dates`) and records no provenance for it at all. The single inferred link in the chain — `session → date`, which the 2026-10-08 page reads showed is the broken one — is stored as if it were a fact, cannot carry evidence, cannot hold a competing hypothesis, and cannot be compared against the observed physical path.

## The four cross-sequence edges

| edge | from → to | observed? | evidence | source |
|---|---|---|---|---|
| **OBSERVED_ON** | Session / HtrResolution → Scan | **yes** | recorded archival addressing | `resolution_archival_provenance.scan_ids` |
| **DATED_AS** | Scan → SittingDay | **yes** | date heading on the page | the date region's own heading on that scan; channel ∈ {strict, bootstrap}, bootstrap carrying its measured 1.3% parse error |
| **PINNED_TO** | SittingDay → Session | **no — inferred** | no independent evidence | concordance `resolved_session_id`; this is the broken link |
| **ALIGNED_TO** | EnrichedResolution → HtrResolution | **mixed** | gold (both gold samples, observed=True) + legacy concordance (`resolution_concordance_1626_1630`, observed=False) + solver (`align.py`, observed=False) | Three parallel-edge sources — `add_aligned_to_gold`/`add_aligned_to_legacy_concordance`/`add_aligned_to_solver`. Persisted (`sequence_graph.persist`), not rebuilt per run. |

The fifth edge, **MENTIONS** (EnrichedResolution / HtrResolution → Entity), is observed but used only for scoring, not for placement.

## Seven tracks, four edges

This is the single most important table in the project. Every active track is a question about one of these edges. `kind` names what the track structurally *is*; `tension` names what it establishes, where it falls short today, and what it structurally cannot establish — the `kind` column used to carry both, which hid the second and third parts.

| track | edge(s) | kind | tension |
|---|---|---|---|
| `scan-sequence` | OBSERVED_ON + DATED_AS | observe both and compare physical vs editorial order | **Establishes:** scan-keyed anchors that never consult session attribution, with near-zero monotonicity violations per inventory. **Falls short:** only 12–27% scan density per inventory is anchored this way; it routes around the region→session defect, it does not fix it. **Cannot establish:** positional correspondence between the two layers — they come from independent archival series, so agreement/disagreement is evidence of a real relation, never proof of one at the position level. |
| `sequence-alignment` | DATED_AS vs PINNED_TO | compare two independently-observed sequences for drift | **Establishes:** that the two sequences' disagreement *is* the dating problem, and one checkable ledger (`running_axis`) that stops ambiguous counts from circulating. **Falls short:** 344 unresolved sittings against only 79 unclaimed sessions, so reassignment cannot absorb the gap; two explanatory hypotheses (orphan pages, under-transcription) were raised and refuted, leaving the shortfall's cause open. **Cannot establish:** which session a stuck sitting belongs to — that is PINNED_TO itself, the edge this track studies rather than resolves. |
| `inventory-stream-collision-avoidance` | PINNED_TO | monotonicity within an inventory | **Establishes:** collisions dominate loss 4:1 over extent, and much of the pigeonhole ceiling (2,614 resolutions, 22.5%) is a day-partition artifact, not an archive limit. **Falls short:** the higher stream ceiling is a loose upper bound assuming free reallocation; raising it makes the headline coverage number look worse, not better. **Cannot establish:** which specific resolution fills a freed slot — monotonicity bounds position, it supplies no placement evidence. |
| `track-s-anchor-shifting` | PINNED_TO | many-to-many session↔date mapping, replacing one-date-one-session | **Establishes:** the rigid concordance is itself the problem — 67 sessions legitimately serve 2-3 dates (S1: +186/−186, net +60). **Falls short:** the S2 many-to-many schema is unbuilt, so no resolution has actually been reassigned; S3's 42 undecided duplicates are untouched. **Cannot establish:** *which* date owns a shared session from fingerprint identity alone — fingerprinting proves a raw session's identity, never its ownership. |
| `track-p-subparagraph-division` | CONTAINS (HTR hierarchy) | splitting a Paragraph | **Establishes:** sub-paragraph collision is the single largest loss class (34% of placed resolutions), and Group C candidates beat a uniform-random null (P1, done). **Falls short:** P0 (whether to actually re-paragraph) is still an unsigned gate; splitting would also push 273 currently-separated resolutions over the extent limit. **Cannot establish:** that the top-ranked candidate is the correct cut — the channel's own ranking "cannot find it" per its own measurement; availability is not accuracy. |
| `staged-anchor-consolidation` | ALIGNED_TO | derivation inside a bracket | **Establishes:** a confidence-ordered procedure (objective anchors → reconcile → subdivide → repeat) with an abstain-honestly rule that cannot be gamed by declaring one maximal clump. **Falls short:** it is a specification, not yet executed — the one code change it needs (partial abstention in `segment_day`) is unwired. **Cannot establish:** correctness — gap-minimisation measures how much of the stream is pinned, not whether each pinning is right. |
| `tfidf-embeddings-wiring` | ALIGNED_TO | cost channel | **Establishes:** per-rank, row-normalised similarity moves placements and improves gold correctness (0.5032 → 0.5865) where the absolute-level form provably could not. **Falls short:** NEGATIVE on `separated_count` globally (−25); only positive (+315) when gated to `weak_separation` days. **Cannot establish:** which objective should gate it — correctness vs. coverage is an open, unscoped decision needing the user's call. |
| `archival-provenance` | OBSERVED_ON | source provenance | **Establishes:** real scan/page addressing for 71.7% of resolutions (100% integrity where resolved), and a secret-flag channel that arbitrates duplicate session claims 3-for-3. **Falls short:** 28.3% of flat ids still don't resolve in ES, inventory 4861 has zero rows at all, and 6 of 34 secret-hijack days remain undetermined. **Cannot establish:** a scan address for ids outside ES's coverage, or any claim about session/date identity — OBSERVED_ON is addressing only, nothing else. |
| `resolution-loss-census` | ALIGNED_TO | EnrichedResolution nodes with no edge | **Establishes:** most `cross_day_shift` mass is collision-locked, not a true date-label conflict (552/621 vs 27), and duplicate session claims are shared anchors, not ownership contests (25/67 decided, all `shared`). **Falls short:** 42 of 67 duplicate sessions remain undecided; the entity-overlap probe failed outright on modern-summary-vs-HTR vocabulary mismatch. **Cannot establish:** absence vs. recovery-elsewhere for an unmatched resolution without a calibrated false-negative rate — "no evidence" cannot yet be read as "no match." |

Seven tracks, four edges. That collapse is the point.

## The PINNED_TO rule

Any traversal crossing PINNED_TO is inferred and must say so. This replaces a judgement call that failed repeatedly on 2026-10-08: *"state which of your unit, denominator and yardstick rests on `session → date`"*. The graph form is a query property: **does this path cross PINNED_TO?** If yes, the result is inferred. That is checkable in code, and three of the five 2026-10-08 breaches were exactly this.

## Anchors are claims (not absolute lids)

**User, 2026-10-11:** dates and other anchors are relational, especially when wrong. Treat them as provenance-tagged **claims** on the existing four edges — not as absolute calendar truths baked into node identity.

**Claim ≠ identity.** `SittingDay` / `Session` / `Scan` nodes stay stable identities. Fallible sync lives on correspondence edges. Never overwrite an ISO day node because a clerk lied; add or prefer a competing claim edge.

**Absolute axes** (within an inventory) — `NEXT` chains / order keys:
- physical `scan_num`
- HTR `session_num`
- editorial `resolution_index` within a day

**Relational / fallible** — correspondence edges (parallel channels, same pattern as `PINNED_TO` vs `PINNED_TO:physical` and multi-source `ALIGNED_TO`):

| channel | edge | meaning |
|---|---|---|
| `DATED_AS` / `DATED_AS:literal` | Scan → SittingDay | parser of clerk heading (observed text; calendar can be wrong) |
| `DATED_AS:review` | Scan → SittingDay | human date↔scan note (shaped from `problem_sequence_review_notes`; **not yet written to the graph**) |
| `PINNED_TO` | SittingDay → Session | production concordance (inferred) |
| `PINNED_TO:physical` | SittingDay → Session | physical path (already present) |

**Hard constraints (user-agreed):**
1. **No fifth edge kind** — no `RELATIVE_TO`, no claim-node types.
2. **Absolute axes stay absolute** — scan/session order remain hard scaffolds; calendar sync is what is relational.
3. **Doctrine before graph write** — emit `DATED_AS:review` only after note language is stable. **No `PINNED_TO:review`** until a note explicitly asserts session↔date (date↔scan is weaker and stays on `DATED_AS:review`).

**Conflicts are typed, not merged.** When literal parse, physical pin, and review disagree, record the conflict; query/policy selects an active claim set. Reports must name which set. Trusted brackets / soft windows are **claim-dependent work views**, not sealed absolute lids.

**Note → claim shape** (date track only; not `ALIGNED_TO`): see `sequence_graph.problem_sequence_review.dated_as_review_claims_from_notes` — `{claim_kind: dated_as_review, inventory, scan_num, date, evidence_url, review_id, decided_at, …}`. Resolution↔folio matching is a separate track.

Every measurement must say whether it uses **literal**, **physical**, **production pin**, or **review** claims. Paths that cross any `PINNED_TO*` remain inferred.

## Hard-evidence recalibration (when the reprojection fails)

**User, 2026-10-12:** Scan-keyed `DATED_AS` is a convenience reprojection of heading evidence (ES carries date regions on sessions). It is fine until proven wrong. Then do **not** patch soft lids on top of the error — drop contested production `PINNED_TO` as active lids and restring from the hardest remaining evidence.

**Active hard map:** unique `Session -OBSERVED_ON-> Scan -DATED_AS-> SittingDay` (compose; ignore contested production pins as lids). Claim set name: `hard`.

**Then ALIGNED_TO in order:**
1. **(a)** Literal match of HTR session openings to enriched resolutions (cheap seeds, channel `literal_opening`).
2. **(b)** Existing `align_bracket` DP₁ entity on soft windows whose lids are the hard map only.
3. **(c)** DP₂ short/opening extend on residue (same mechanism as trusted-bracket hand-off).

Hand review notes / `DATED_AS:review` are **held out** from lids and seeds on the first apply; they score the machine path afterward. No production `PINNED_TO` wire. Module: `sequence_graph.hard_recalibrate`.

## Current status

As of 2026-10-09 (overnight session after Stage 0): **Stages 0–3b are DONE, all gates pass.**
`sequence_graph/` exists and is tested (84 tests, all passing):

- **Stage 0** — guards: `scripts/corpus_scope.py` (`is_sidelined`, `suspicious_secret_dates`,
  `assert_no_sidelined`, recursive and string-only).
- **Stage 1** — `sequence_graph/nodes.py`, `build.py`. The three sequences as six `NEXT`-ordered
  chains (`Scan`; `Session`→`HtrResolution`→`Paragraph`; `SittingDay`→`EnrichedResolution`), no
  correspondence yet. Exact node counts verified against the corpus.
- **Stage 2** — `sequence_graph/correspondence.py` (`OBSERVED_ON`, `DATED_AS`, `PINNED_TO`,
  `LABELLED_AS`, `monotone_map`, `traversal_is_inferred`) and `classify.py`. Reproduces
  `reconcile_sequences.py`'s own verdicts exactly: 323 hard anchors / 406 bounded gaps / 81
  unconstrained, problem types `T0`-`T6` matching to the digit.
- **Stage 3** — `sequence_graph/consolidate.py` (`CORRESPONDENCE_CLASSES`, `PROBLEM_TYPES`,
  registered via `running_axis.tally.POPULATIONS`, `check_partition`-verified) and `query.py`
  (`--session`/`--date`/`--scan`, both paths, both pieces of evidence, the IIIF link).
- **Stage 3b** — `sequence_graph/render.py` (three-lane SVG, `TrackNode`/`TrackEdge`), with the
  extraction (`consolidate.track_records`) kept structurally outside it.

**Stage 4** (the solver, `align.py`) is in progress. First pass: the four decisions the overnight
stop-note left open were answered by the user, and `align_bracket` (O(NM), typed
MATCH/DELETION_GAP/INSERTION_SPLIT/SOFT_CLIP moves, semi-global with evidence-gated free end gaps
and abstention, non-collapsing cost) is built and tested (`tests/test_sequence_graph_align.py`).
Run once on the scoped clean bracket (`1629-03-02`, k_e=k_f=5): 3/5 gold exact agreement, 1/5
`separated`.

A second design gap, raised and resolved the same day (`docs/DECISIONS.md` 2026-10-09 "all four
Stage 4 move-set design questions resolved"): nihil-actum days are a checkable milestone invariant,
not a `SKIP` move (live data refines this further — every nihil-actum date has `k_e == 1`, not 0,
and none currently resolve to a session); `DATED_AS`'s `strict`/`bootstrap` channels stay
upstream-only, not folded into solver cost; Track P's sub-paragraph `CONTAINS` refinement should
unify with `ALIGNED_TO` at paragraph granularity (not yet implemented); and "forbid HTR insertion"
turned out to mean no move may ever reorder a read item — already structurally true of this DP
(only forward transitions exist) and now pinned down by a regression test
(`test_read_items_are_never_reordered_only_matched_split_or_dropped`), carrying the caveat that the
"fixed order" trusted here is itself an interpretation of HTR region detection, not a fact about
the page.

`ALIGNED_TO` is then **written back to the graph**, not left as a transient in-memory result
(user: "ONLY if results are discarded explicitly they should not be written back") — three
parallel edge sources: `add_aligned_to_gold` (observed=True, hand-verified, both gold samples),
`add_aligned_to_legacy_concordance` (observed=False, the EXISTING production pipeline's own
placement — `resolution_concordance_1626_1630`, 70% corpus coverage, predating `sequence_graph`
entirely — found missing by direct user audit 2026-10-09), and `add_aligned_to_solver`
(observed=False, the DP's own output, explicitly unfitted). `gold_aligned_pairs`/
`gold_aligned_pairs_detailed` are the sanctioned read paths for any calibration, filtering to
`observed=True` only, so fitting code cannot accidentally train on a derived edge.
`aligned_to_status` is a closed, `check_partition`-verified four-way taxonomy over every
`EnrichedResolution` (`gold_verified` > `legacy_concordance_only` > `solver_derived_only` >
`unaligned`) answering "what's still missing" as a number — unaligned dropped from 18,775 to
**6,068** once the existing production placement was actually counted.
`sequence_graph.query.query_range` reads all of this into a human-readable week/month report
(dates by ISO week, each session's HTR resolutions drilled into individually — clean
correspondences stated directly, unresolved stretches showing the solver's own proposed cut,
"not yet attempted" where it hasn't run), callable from the CLI or a notebook.

**The graph is persisted** (`sequence_graph/persist.py`: `save_graph`/`load_graph`, two registered
datasets) — found missing by direct user audit the same day ("is the graph saved to disk?"), since
every script previously rebuilt it from source on every run. `query.py` now loads the saved graph
rather than rebuilding. A related scalability gap, found immediately after by the user ("this does
not look scalable"): `fit_cost.py`/`position_prior.py` each had their own independent copy of the
gold-interpretation logic and had already silently diverged within the same session — fixed via
`gold_aligned_pairs_detailed`, one shared read path instead of two.

`match_cost`/`gap_cost` are now **fitted** (`sequence_graph.fit_cost`, on gold vs. within-day
derangement negatives) — `match_cost`'s formula changed to a real log-probability
(`-log(sigmoid(...))`), not just new constants on the old linear form. Measured across all 50
alignable gold days: `separated` 15.1% (unfitted) → 45.2% (fitted) — a real ~3x improvement —
**against a uniform-null baseline of 73.9% on the same population.** Stage 4's own
separated-vs-uniform-null gate has **not** passed. `insertion_cost`/`split_discount`/
`soft_clip_cost` remain unfitted (no split-vs-margin-content calibration population exists).
**Still not benchmarked against the three existing DP mechanisms, and not yet run past
`boundary_gold_sample` days** — see `plans/SEQUENCE_GRAPH_SPINE.md`'s Stage 4 for the full
step-by-step record and what's next. **Stage 5** (retiring the legacy scripts) is still not
started.

See `plans/SEQUENCE_GRAPH_SPINE.md` for full stage descriptions, every gate's
actual figures, and the bugs each stage's gate caught.

## How to use this document

When starting any new measurement or script in this project, state which of the four edges the question is about before writing code. If you cannot, the question is probably not yet well-posed. If a result crosses PINNED_TO, it is inferred and must say so. Name which claim channel is active (literal / physical / production / review) when the question is about dating or pins. This replaces a standing instruction that lived in a plan file; here it is executable because the model names what "inferred" means.

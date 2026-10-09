# The rode draad: a three-sequence graph as the project's spine

<!-- doc-status: active -->

> **Moved here 2026-10-09 from `~/.claude/plans/the-two-deep-hits-melodic-avalanche.md`** (a
> Claude-local plan-mode file, outside the repo, not shared, not version-controlled) **into the
> project's own `plans/` directory, per the user's direct instruction: "MAKE THE PLANS STEPPED
> AND EXPLICIT AND IN THE OFFICIAL PLACE, NOT YOUR MEMORY."** Content carried over verbatim where
> unchanged; the former top-of-file status blockquote (a chronological narrative) is restructured
> below into explicit, numbered sub-steps under Stage 4, matching this project's own
> `plans/*.md` convention (see `STAGED_ANCHOR_CONSOLIDATION.md`'s `### Step N` pattern) instead of
> a running commentary. Every other `plans/*.md`/doc cross-reference to the old path has been
> updated to point here.

**STATUS (2026-10-09): Stages 0-3b DONE, all gates PASS. Stage 4 (the solver) is in progress —
first pass built, all four initial move-set design questions resolved, `ALIGNED_TO` written back
to the graph (gold + solver halves), a resolution-level week/month report DONE (Step 4.6), and
`match_cost`/`gap_cost` fitted (Step 4.7) — a real ~3x improvement in separated count over the
unfitted placeholder (15.1% → 45.2%), but still well short of the uniform-null baseline (73.9%).
**Stage 4's own separated-vs-uniform-null gate has not passed.** Stage 5 NOT started.**

## Context

**What was missing was a spine, and its absence was the distraction.** The project had seven
active tracks, four scripts that each re-derive the same correspondence, three independent
"difficulty = 2" thresholds, and a closed taxonomy defined inside a `main()` and registered in no
population. Nothing tied them together, so every new measurement invented its own unit,
denominator and yardstick — and on 2026-10-08 four of five such inventions were wrong in the same
way: each reached for whatever was nearest to hand instead of deriving it from what the project
already held.

The one rule that *stopped* being broken that day was the one made executable
(`scripts/corpus_scope.py`): *"a rule that only lives in `plans/*.md` is a rule that gets
broken."* This plan applies that lesson to the model itself — and, as of today, to its own
location too.

**Three sequences, and the pipeline conflated two and ignored the third:**

| sequence | order | status |
|---|---|---|
| **physical** — scans in book order per inventory | `scan_num` | **observed**; was absent from every model (`grep scan\|page\|folio running_axis/` → 2 prose hits, 0 fields) |
| **HTR** — sessions → resolutions → paragraphs | `(session_num, resolution_num, para_index)` | observed within itself; `stream.py:131` proved flat order *is* physical order |
| **editorial** — sitting days → enriched resolutions | date, `resolution_index` | observed within itself; the XML has no physical grounding (`Stgen.dtd` has no folio/page/scan element) |

`running_axis` holds sessions and dates **in one object** with the pin denormalised across both
sides (`place_anchor` writes `DateState.resolved_session_id` *and* `SessionSpan.resolved_dates`)
and records **no provenance for it at all**. So the single inferred link in the chain — `session →
date`, which the 2026-10-08 page reads showed is the broken one — was stored as if it were a fact,
could not carry evidence, could not hold a competing hypothesis, and could not be compared against
the observed physical path.

---

## How the rode draad is used, at all times

Three jobs. Each is a mechanical lookup, not a judgement call.

**1. It locates any question.** Every open question is a node class, an edge type, or a
classification. All seven (now effectively collapsing) active tracks are questions about four
edges:

| track | where it sits on the graph |
|---|---|
| `scan-sequence` | the physical sequence; `OBSERVED_ON` + `DATED_AS` |
| `sequence-alignment` | `DATED_AS` vs `PINNED_TO` — their disagreement |
| `inventory-stream-collision-avoidance` | `PINNED_TO` monotonicity within an inventory |
| `track-s-anchor-shifting` | `PINNED_TO` as many-to-many (its unbuilt S2 schema *is* an edge set) |
| `track-p-subparagraph-division` | `CONTAINS` refinement on the HTR side — splitting a Paragraph |
| `staged-anchor-consolidation` | `ALIGNED_TO` derivation inside a bracket |
| `tfidf-embeddings-wiring` | an `ALIGNED_TO` cost channel |
| `archival-provenance` | the `OBSERVED_ON` source |
| `resolution-loss-census` | EnrichedResolution nodes with no `ALIGNED_TO` edge |

Seven tracks, four edge types. That collapse is the point.

**2. It supplies the units.** Populations are registered once in `POPULATIONS`, with unit and
attribution, so no measurement invents a denominator. `check_partition` then refuses any reported
split that does not sum over one window.

**3. It flags the broken link mechanically.** This replaced a guard that could not be built as a
judgement call — *"state which of your unit, denominator and yardstick rests on `session →
date`"*. The graph form is a query property: **does this traversal cross `PINNED_TO`?** If yes,
the result is inferred and must say so. That is checkable in code, and three of the five
2026-10-08 breaches were exactly this.

**Where it lives, so it cannot be forgotten.** `docs/SEQUENCE_MODEL.md` is the canonical
reference, and the spine is promoted into the four loaded instruction files (`CLAUDE.md`,
`AGENTS.md`, `.cursor/rules/project-standards.mdc`, `.github/copilot-instructions.md`) the same
way the scope bar was — a short block naming the three sequences, the four edges, and the
`PINNED_TO` rule. `PLAN.md` keeps headlines and points at the model for structure. This plan file
(`plans/SEQUENCE_GRAPH_SPINE.md`) is the detailed, stepped record — in the repo, not in a
Claude-local file.

**And it is queryable, because "refer to at all times" needs an interface, not a document:**

```
uv run python -m sequence_graph.query --session session-3187-num-155
uv run python -m sequence_graph.query --date 1629-05-18
uv run python -m sequence_graph.query --scan 3187 320
```
printing both paths (observed `Session→Scan→Day`, inferred `Day→Session`), their evidence, and the
classification, with the IIIF link. One command to answer "what do we actually know here".

---

## The model

Package `sequence_graph/`, importing `running_axis.tally` for accounting and
`scripts.corpus_scope` for guards. `networkx` is a declared dependency (`uv add networkx`).

**Nodes** (`nodes.py`) — frozen dataclasses, ids derived and stable, never counters:
`Scan(inventory, scan_num)`, `Session(session_id)`, `HtrResolution(flat_id)`, `Paragraph(axis_id)`,
`SittingDay(date)`, `EnrichedResolution(date, index)`, `Entity(entity_id)`.

**Within-sequence edges**: `NEXT` along each of the three orders, `CONTAINS` down each hierarchy.
These are the three sequences, modelled separately.

**Cross-sequence edges** (`correspondence.py`), each carrying
`Evidence{channel, source, observed: bool, confidence, detail}`:

| edge | from → to | observed? | source |
|---|---|---|---|
| `OBSERVED_ON` | Session / HtrResolution → Scan | **yes** | `resolution_archival_provenance.scan_ids` |
| `DATED_AS` | Scan → SittingDay | **yes** | the date region's own heading on that scan; `channel ∈ {strict, bootstrap}`, bootstrap carrying its measured 1.3% parse error |
| `PINNED_TO` | SittingDay → Session | **no — inferred** | concordance `resolved_session_id` |
| `LABELLED_AS` | SittingDay → Session | **no — inferred** | the axis's own date label (added in Stage 2, not in the original plan — see Stage 2 below) |
| `ALIGNED_TO` | EnrichedResolution → HtrResolution | **both** | gold (`boundary_gold_sample`, observed=True) + the solver (`align.py`, observed=False) — see Stage 4, Step 5 |
| `MENTIONS` | EnrichedResolution / HtrResolution → Entity | observed | the overlap tables — a scoring input Stage 4 reads, not a correspondence fact this module asserts |

**Guards at construction** (`build.py`): scope bar and sidelining applied as nodes are created, so
the graph cannot contain post-bar or sidelined material.

**What is kept, not replaced.** `running_axis.tally` is real value — `Tally` refuses
cross-population and overlapping-window arithmetic, `check_partition` raises unless declared
subsets sum exactly. `running_axis.spans.fragments()` encodes nine fixed upstream defects. Nothing
is deleted until a stage gate proves the graph reproduces it.

## Decisions taken (user, 2026-10-08)

1. **Sideline by ledger, mark the cross-cut.** Sideline exactly what *states* provenance
   4562/4861. The 73 dates with an XML `secreet_resolutie` marker resolving to an ordinary-ledger
   session stay in the sequence, **flagged suspicious**. The 344 candidate-only dates are **not**
   sidelined — nothing states their inventory, so provenance is unknown, not secret.
2. **`bracket_gap_census` is rebuilt on the consolidation population**, not `build_brackets`'
   unresolved-date brackets, which are empty by construction once the secret series is sidelined.

---

## Stages — one per session, each with a gate

### Stage 0 DONE (2026-10-09) — the spine, written down and enforced
`docs/SEQUENCE_MODEL.md`; the spine block added to the four loaded instruction files; `networkx`
declared. Plus the guard fix: rewrote `corpus_scope.assert_no_sidelined` to walk a record
**recursively**, testing only string values and parsing each via `inventory_of`, reporting dotted
paths — the one-column version is what let a JSON-substring "verification" match `14562` (a char
count) and `0.4562` (a probability). Added `suspicious_secret_dates()` for decision 1.
**Gate: PASS.** `tests/test_corpus_scope.py` cases using exactly `14562`/`0.4562`; suite green.

### Stage 1 DONE (2026-10-09) — the three sequences
`nodes.py`, `build.py`. Nodes and `NEXT`/`CONTAINS` only, no correspondence.

**Gate corrected before any code was written.** The first draft's target (1,316 sessions, 19,120
paragraphs... "zero sidelined or post-bar nodes") was self-contradictory — 1,316 is the raw axis
session count and *includes* the 102 sidelined 4562 sessions, so it cannot coexist with "zero
sidelined nodes". Re-measured: the physical/HTR sequences (which state their own inventory) are
filtered by `is_main_series` + the scope bar, while the editorial sequence (which states none) is
built unfiltered by sidelining — an `EnrichedResolution` has no inventory field, so sidelining
cannot act on it directly; only a Stage 2 `PINNED_TO` edge could later reveal one.

**Gate: PASS, all six counts exact.** `Scan` 3,195, `Session` 1,034, `HtrResolution` 11,273,
`Paragraph` 18,946, `SittingDay` 1,594, `EnrichedResolution` 19,120. Structural invariants
verified: every `NEXT` chain is a DAG with out/in-degree ≤ 1 (no forks), every `CONTAINS` child
has exactly one parent, zero sidelined identifiers and zero out-of-scope dates reached a node. 15
tests in `tests/test_sequence_graph_nodes.py` / `test_sequence_graph_build.py`.

**One real bug caught by the numbers, not by inspection:** the first `Scan` build used
`not is_sidelined(inventory)` as its filter and produced 292,327 scans instead of 3,195 — true of
every one of `inventory_metadata`'s 674 unrelated inventories, not just the main series. Fixed to
`is_main_series`. The lesson: "not sidelined" and "is main series" are different predicates, and
reaching for the nearer one produced a 90x error that a unit test on synthetic data would not have
caught — only the real count did.

### Stage 2 DONE (2026-10-09) — correspondence, monotonicity, and the `PINNED_TO` rule
`correspondence.py`: four edge types with `Evidence` (`OBSERVED_ON`, `DATED_AS`, `PINNED_TO`, and
one not in the original plan — `LABELLED_AS`, `SittingDay -> Session` from the axis's own date
label, added because faithfully reproducing `reconcile_sequences.py`'s `resolved or label_dates`
fallback needed it), plus `monotone_map(graph, from_kind, to_kind, edge_kind) -> MonotonicityReport`
and `traversal_is_inferred(path) -> bool`. `classify.py` does the actual gate reproduction.

**The target itself needed a second correction before any gate could run.** 323/406/**261** (the
2026-10-09 correction) still carried 180 post-bar-only sessions that `reconcile_sequences.py`
never actually excluded — inherited from `running_axis`'s *deliberate* post-bar visibility, not a
reasoned choice in that script. Verified by restricting the ORIGINAL reference functions (not a
re-derivation) to the same scope-compliant population Stage 1 builds: **323/406/81**, with
`hard_anchors`/`bounded_gaps` unchanged both times. **This is the real target.**

**Gate: PASS, exactly.** Verdicts `{contradicted: 547, reconciled: 406, no_observed_scan: 81}`;
problem types `{T0:406, T1:127, T2:109, T3:170, T4:26, T5:115, T6:81}` (T7 is correctly absent, 0,
after the fix below); consolidation `{hard_anchors: 323, bounded_gaps: 406, unconstrained_gaps:
81}` — all exact. 27 tests across `test_sequence_graph_{correspondence,classify}.py`.

**Two real bugs found by the numbers, both fixed, neither papered over:**
1. **`DiGraph` silently drops one of two edges sharing an endpoint pair.** A date can be *both*
   `resolved_dates` and `label_dates` for the same session (measured: `1626-01-15` is both, for
   `session-3185-num-13`) — a plain `DiGraph` lets the second `add_edge` overwrite the first.
   Fixed: `build.py`/`correspondence.py` use `MultiDiGraph` with the edge kind as the key.
2. **A date can be axis-labelled with zero rows in the enriched table at all.** `1627-09-14`
   (exactly one such date corpus-wide) is claimed by a session's own label but has no
   `EnrichedResolution` — dropping it (as the first build did) cost exactly one session's verdict.
   Fixed: `build_editorial_sequence` unions in every in-scope label/resolved date, giving it a
   bare `SittingDay` with no children, rather than silently discarding the claim (`CLAUDE.md`'s
   standing rule against exactly that).

**One test assertion was also wrong, caught before merging rather than after:** a regression test
claimed some `T4_anchor_bracket_suspect` sessions have a narrow window, to prove the
crowded-window check's precedence over window-width. Checked: false — all 26 have window 3 or 5
days in this corpus. Fixed to assert the measured fact instead of the assumed one.

**`monotone_map` disagrees with the legacy `monotone_anchors` on purpose, and this is a kept
finding, not a discrepancy to resolve.** The legacy rule (sort by date, greedily drop any scan
that is not a new maximum) reports 0.4–0.6%; the general pairwise order-preserving-map check
reports **4.19%** on the same `DATED_AS` edges, because one badly-parsed anchor makes every later,
individually-correct entry look like a violation too under a true pairwise check, which the
greedy rule's one-pass forgiveness hides. `classify.py` uses the legacy rule for gate fidelity
(reproducing the reference exactly) and keeps `monotone_map`'s stricter number as a separate,
documented diagnostic — unifying the two is explicitly not this stage's job.

### Stage 3 DONE (2026-10-09) — accounting, persistence, and the query interface
`consolidate.py`: `CORRESPONDENCE_CLASSES` and `PROBLEM_TYPES` as module-level closed taxonomies,
registered via `running_axis.tally.POPULATIONS.register(...)`, mirroring `axis.ADDRESSABILITY`.
`query.py` built per the plan's own example invocations.

**`CORRESPONDENCE_CLASSES` needed a fourth class to become a genuine partition — the three-way
split was never one.** `hard_anchor`(323) + `bounded_gap`(406) + `unconstrained_gap`(81) = 810,
against 1,034 sessions. The missing 224 are "decided (reconciled or contradicted) either way, but
the implied window is too wide to count as evidence" — visible before only inside the separate
`problem_type` breakdown (`T4`+`T5`, plus wide-but-reconciled sessions folded silently into `T0`).
Added as `wide_window`; `check_partition` now passes for both taxonomies, not asserted by eye.

**`PROBLEM_TYPES` was already an exact partition** (406+127+109+170+26+115+81 = 1,034) —
`check_partition` confirms this rather than newly establishing it. `T7_nothing_inferred` stays in
the taxonomy at 0 (the taxonomy is closed by what it classifies, not by what today's data
produces).

**The "unify three thresholds" item is a documentation decision, not a merge.** `BRACKET_CLASSES`
is a taxonomy, not a threshold — an earlier draft of this plan conflated the two. The two real
"2"-valued thresholds (`chain.NEARLY_DETERMINED`, `NARROW_WINDOW_DAYS`) measure different things
on different sequences; `consolidate.py`'s docstring is their one documented pointer, explaining
both and why they are not forced into one shared constant (that would be surgery on `chain.py`'s
own tested code for no measured benefit).

**Gate: PASS on all three parts.** Dropping one class from `check_partition`'s input raises
(tested); a consolidation rebuilt from `to_records()`/`from_records()` equals the live one exactly
(tested); `query.py` answers `--session`, `--date`, `--scan`, each printing both the observed and
inferred path. **`--date 1629-05-18` is a genuine demonstration of the spine's point**: it is
labelled by *two different sessions* — `session-3188-num-129` (reconciled) and
`session-3188-num-79` (contradicted, +54 days) — a competing-hypothesis case `running_axis`'s
single denormalised pin cannot represent at all. 12 tests across
`test_sequence_graph_{consolidate,query}.py`.

### Stage 3b DONE (2026-10-09) — visualisation (three tracks, correspondence as edges)
A graph is also the easier thing to look at (user), and the discipline exists:
`running_axis/serialize.py` renders from serialised records and *"never reaches back into the
model, so a picture can never show something the serialised state does not contain."* Inherited
that rule — render from Stage 3's `to_records()`, never from a live graph.

`render.py`: three parallel tracks (physical / HTR / editorial), correspondence as edges between
them. Four encodings that make an invariant visible instead of tabulated:

- **Crossing edges are monotonicity violations** — a non-order-preserving map becomes a visual fact.
- **Edge style separates observed from inferred**, so the one broken link is distinguishable at a
  glance from the three solid ones.
- **A track segment with no edge is a gap** — the 261 unconstrained sessions and 344
  unknown-provenance days read as empty stretches, not missing rows.
- **The two paths diverging** (`Session→Scan→Day` vs `Day→Session`) renders as a fork.

`TrackNode`/`TrackEdge` plain records, `render_svg`/`render_legend`/`render_html`, matching
`serialize.py`'s structure. Three lanes top-to-bottom — `Scan`, `SittingDay`, `Session` — chosen
so two of the three edges (`DATED_AS`, `PINNED_TO`/`LABELLED_AS`) are simple one-lane-down arrows
and only `OBSERVED_ON` arcs back up, which is visually distinct for the same reason it is
structurally distinct: the one edge nothing had to be inferred to draw. The extraction
(`consolidate.track_records`) lives outside `render.py` deliberately, so the import constraint is
an `ImportError` if violated, not a convention — verified by parsing `render.py`'s own AST for
forbidden imports, not by trusting its docstring.

**The IIIF-link item is carried in `query.py`, not duplicated in `render.py`.** Linking every edge
to its manuscript image belongs to the interactive query (one session/date/scan at a time) rather
than to the static SVG (potentially thousands of edges).

**Gate: PASS.** `render.py`'s imports are exactly `html`/`dataclasses`/`typing` (AST-checked);
`track_records("3188")` reproduces `query --date 1629-05-18`'s fork directly in the extracted
records (`day:1629-05-18` → both `session-3188-num-79` and `session-3188-num-129`); every scan in
a real inventory survives into the node list even when untouched, flagged `is_gap` rather than
omitted. 8 tests across `test_sequence_graph_{render,track_records}.py`.

### Stage 4 — the solver (the DAG aligner, defects fixed). IN PROGRESS

`align.py`, scoped to a bracket, with the demo's typed transitions — `MATCH`, `INSERTION_SPLIT`,
`DELETION_GAP`, `SOFT_CLIP` — fixing four real defects relative to the demo this was rebuilt from
(not present in this repo; rebuilt from the plan's own specification):

1. **O(NM) edges**, not O(N²M²): only `(i+1,j+1)`, `(i,j+1)`, `(i+1,j)`. The all-forward-pairs
   construction also silently breaks the cost model — R0→R5 costs one MATCH instead of five GAPs.
2. **`SOFT_CLIP` is dead code in the demo** (identical `elif` condition to `INSERTION_SPLIT`, so
   it never fires). Give it a real discriminator: both consume an HTR item without consuming a ref
   item, but a *split* shares entities with the current ref item while *contamination* shares
   none. Compute both costs on `(i,j+1)` and keep the cheaper, recording its type. This is the
   first representation the project has for margin/praesentes contamination.
3. **Semi-global, not global.** The demo pins both ends, which forbids abstention — the one change
   measured as a clear win (gold exact agreement 0.5431 → 0.6486; the abstained population was
   13.9% correct against a 54.3% baseline). Free end gaps, and abstain when the best path's cost
   exceeds a calibrated threshold.
4. **Fix the cost arithmetic.** `max(0.1, 2.0 + match_cost)` with `match_bonus = -2.0` makes one
   and five matching entities both cost 0.1, and `max(0.0, …)` on the START edge discards the
   bonus entirely. Use `base − λ·overlap` floored at ε, with λ **fitted**, not hand-set — this is
   `TRACK_S_ANCHOR_SHIFTING.md`'s open question (*"the pipeline is already probabilistic and
   merely uncalibrated"*).

**Gate (not yet run as a go/no-go):** scored on `separated` via `label_separation()` **against the
`uniform_start_paragraphs` null**, never absolute, with a reliability curve — the standing guard,
because a trivial uniform spread once beat gold's own annotations on `separated`. Exact agreement
only; no boundary-displacement tolerance at any granularity.

**Why Stage 4 was not started the first night, stated plainly rather than left to look like
running out of steam.** Every stage so far was checkable against a number that already existed —
each stage's own gate caught a real defect the same hour it was introduced (the 1,316-sessions
contradiction, the 90x `Scan`-count bug, the `DiGraph` edge collision, the phantom-labelled date,
the 261-vs-81 target correction). Stage 4 is a different kind of task: it scores a solver against
gold correctness and `separated`-vs-uniform-null, where there is no fixed number to check a first
attempt against — only a judgement about whether a cost model is calibrated or merely plausible.
Building and self-certifying that overnight, unreviewed, risked exactly the failure the whole
project session was fighting: a result that looks right and was never checked against the right
thing. So Stages 0–3b were reported as finished and Stage 4 as not started, not as blocked on
something trivial — until the same day's later session picked it up anyway, below, with the four
decisions answered first.

**Four decisions named, so the work that follows could be short rather than starting from zero:**

1. **What does `MENTIONS` actually read?** The plan named "the overlap tables"
   (`place_overlap_1626_1630`, `org_overlap_1626_1630`, `per_overlap_1626_1630`) but Stage 4 needed
   their exact row shape confirmed against a live load before a cost function could be written
   against them — not assumed from a prose description of "shared entities, IDF-weighted".
2. **Is the entity-overlap cost fitted on gold, or on the existing production overlap scores?**
   `TRACK_S_ANCHOR_SHIFTING.md`'s open question says "fit the score components already computed
   as log-likelihood ratios" — on what population, held out how, is a user-level calibration
   choice, not something to default silently.
3. **Which bracket population does Stage 4 run on first?** "Scoped to a bracket" — the natural
   first population is 3187:305→320 (44 sitting days, 15 scans, 665 `k_e`, 114 paragraphs — a
   track's own worst-case example, already hand-verified) or a clean one, and those are different
   kinds of first tests (stress vs. baseline).
4. **Does a Stage 4 result get compared against the three already-measured DP mechanisms in
   `docs/writeup_mechanism_anchors.md`** (`align_session`'s 0.957/0.962 non-discrimination,
   `align_entity_mentions`'s closed-negative unit-cost result, `segment_gap`'s 0.628 exact
   baseline), or is it scored as a clean standalone? Those three numbers are the honest
   benchmarks a fourth DP mechanism has to clear, not a formality.

#### Step 4.1 DONE (2026-10-09) — four decisions answered, mechanism built
Answered before any code: (1) `MENTIONS` row shape checked live — no precomputed score, raw
match-candidate rows; (2) cost fitting deferred, mechanism built first with the existing
production entity-overlap score as an unfitted signal; (3) first population is the clean bracket
`1629-03-02` (k_e=k_f=5), not the 3187:305→320 stress case; (4) scored standalone, not against the
three existing DP mechanisms. `sequence_graph/align.py` implements all four named defect fixes and
`tests/test_sequence_graph_align.py` (9 tests, synthetic, no corpus access) passes. One defect fix
needed a real correction while building it, not just porting the spec: `insertion_cost` cannot
share `match_cost`'s formula, or `match(a) + insertion(b) >= insertion(b)` always holds and the DP
never chooses MATCH-then-SPLIT over skipping ahead to a fresh match — `split_discount` fixes this
(`CostModel.insertion_cost`'s docstring).

**The one real run (`1629-03-02`) found a genuine, undecided limitation, not a bug.** Of 5
enriched/5 HTR resolutions, only 2 pairs carry any entity-overlap evidence at all (checked the raw
matrix directly — this day is short and administrative, sparse evidence is real, not a defect).
The aligner placed only 1 of those 2 real matches: "free trailing" let the DP discard an
*unbounded* run of trailing read items for free once an early quiet stretch made bailing out
cheaper than paying to traverse it, rather than trimming only a short true margin the way genomic
soft-clipping does — confirmed by hand-deriving the discarded alternative path's cost (5.489 vs
the DP's chosen 4.916: the DP was optimal under the current cost model, the model's "free" scope
was just too permissive). **User decision: stop here for that session** rather than bound the
free-gap window or start fitting.

#### Step 4.2 DONE (2026-10-09, later) — free-gap fix
User's framing ("put a high penalty on trailing content so it begs to get resolved") was close but
not adopted as-is: a uniform penalty would also drag genuinely unrelated margin content (zero
evidence anywhere) into forced placements, reopening the exact forced-placement pathology
semi-global alignment exists to avoid. Landed on the sharper version instead: free leading/
trailing status is evidence-gated, not positional — a read item is free only if it carries zero
overlap against every ref item; one item with real evidence ends the free run from that point on.
No new constant needed; `align_bracket`'s docstring and `tests/test_sequence_graph_align.py` (11
tests) carry the detail. Verified on `1629-03-02`: the previously-discarded ref3/read3 match
(overlap 1.027) now survives; total cost moved from 4.916 to the correct 5.489.

#### Step 4.3 DONE (2026-10-09) — tested on a spread of real days
Ran `run_bracket` on 7 gold days from clean (`diff_0`) through severe over/under-segmentation
(`diff_3plus`, up to k_f=47 vs k_e=14) — no crashes, costs and separated-counts scale plausibly
with difficulty. Surfaced one real bug, fixed immediately: `1626-02-28`'s gold boundaries include
`unit: "out_of_range"` entries with no `flat_id` at all (gold genuinely could not place them) —
the scoring adapter assumed every boundary carries one and raised `KeyError`. Fixed to skip
boundaries with no `flat_id`, and to not call `max()` on an empty sequence when nothing is known.

#### Step 4.4 DONE (2026-10-09) — all four move-set design questions resolved live with the user
A second design gap, raised after Step 4.3 (not in the original four decisions): does the move set
need a `SKIP` for nihil-actum days, should `DATED_AS`'s `strict`/`bootstrap` channels be
solver-visible subtypes, how does Track P's sub-paragraph `CONTAINS` refinement interact with
`ALIGNED_TO` identity, and should the move set forbid HTR-side insertion outright? Resolved (full
detail in `docs/DECISIONS.md` 2026-10-09 "all four Stage 4 move-set design questions resolved"):

1. **Nihil-actum is a checkable milestone invariant, not a `SKIP` move.** A nihil-actum day is a
   milestone — a session exists (HTR side), zero resolutions (editorial side) — not a gap needing
   a special transition. Live-data check (`notebooks/sequence_graph_exploration.ipynb` §7) refined
   this further: every one of the 127 nihil-actum dates has `k_e == 1` (the formulaic entry
   itself, not zero), and none currently resolve to an HTR session. No code change yet; recorded
   as a refinement for whenever this becomes an actual move-set change.
2. **`DATED_AS` channel stays upstream-only.** Folding `strict`/`bootstrap` parse-confidence into
   `align.py`'s per-bracket cost would double-count uncertainty the bracket-construction gate
   already prices in.
3. **Track P should unify with `ALIGNED_TO` at paragraph granularity** (not yet implemented) — the
   read sequence should eventually be `Paragraph`/`CONTAINS`-child level, not `HtrResolution`-
   level, so a future sub-paragraph split is a finer read item the same DP already handles.
4. **"Forbid HTR insertion" meant no move may ever reorder a read item** out of its position in
   the flat stream (unlike Levenshtein edit distance) — already structurally true of this DP (only
   forward transitions exist), now pinned down by a regression test
   (`test_read_items_are_never_reordered_only_matched_split_or_dropped`) and stated in
   `align_bracket`'s own docstring, carrying the caveat that the "fixed order" trusted here is
   itself an interpretation of HTR region detection, not a fact about the page; a genuine ordering
   defect is a separate upstream problem to fix at the source.

#### Step 4.5 DONE (2026-10-09) — `ALIGNED_TO` written back to the graph
User pushed back directly on Stage 2's "not built here" framing: *"we have too many things...
ONLY if results are discarded explicitly they should not be written back."* Added:

- **`add_aligned_to_gold`** — `EnrichedResolution -> HtrResolution`, `observed=True`, from
  `boundary_gold_sample` via the general `scripts.separated_accuracy_eval.gold_start_paragraphs`
  (not `align.py`'s own bespoke 1:1-only parsing in `run_bracket`, which explicitly declined to
  generalize). A hard, human-confirmed fact; no confidence value, by the same convention as every
  other `observed=True` edge (hand annotation has no separately measured error rate).
- **`add_aligned_to_solver`** — `EnrichedResolution -> HtrResolution`, `observed=False`, the DP's
  own `MATCH`/`INSERTION_SPLIT` moves (`DELETION_GAP`/`SOFT_CLIP` correctly produce no edge —
  nothing to assert a correspondence to). Carries the move kind and the path's `total_cost` in
  `detail`, and an explicit `cost_model_fitted: False` flag rather than a fabricated confidence
  number. **Scope limit, stated not hidden:** `dates` is currently restricted to
  `boundary_gold_sample` days (same source as `n_ref`/`flat_ids`) — it cannot yet run on the
  ~19,000 enriched resolutions with no gold entry at all, which is most of the corpus. Pulling
  `flat_ids`/`n_ref` from production data directly, independent of gold, is the real corpus-wide
  extension and is not done here.
- **`gold_aligned_pairs(graph)`** — the one sanctioned read path for anything that
  fits/calibrates `CostModel`: filters to `observed=True` only, by construction. The
  non-circularity rule (user: *"evidence should be cumulative, not part of multiple looped
  derivations"*) made executable, not just stated in a docstring — a future fitting script cannot
  accidentally train on the solver's own derived output (the `tier1_anchor`-as-positives trap this
  project already knows about elsewhere).
- **`sequence_graph.consolidate.aligned_to_status`** — a closed, `check_partition`-verified
  three-way taxonomy over every in-scope `EnrichedResolution` (`gold_verified` /
  `solver_derived_only` / `unaligned`), per the user's ask: *"it should be positive clear what is
  fixed, what is still open, what is missing."* 345 gold-verified, 2 solver-derived-only (one test
  bracket beyond gold), 18,775 genuinely unaligned — the honest majority, a checked number rather
  than an impression.

**One real bug found by testing the combination, not by inspection, same session.** Both halves
first keyed their `MultiDiGraph` edge on the literal string `ALIGNED_TO`, so writing a solver edge
on a pair gold already covered silently **overwrote the gold fact** — the single worst version of
"discarding a result" this step exists to prevent (and the same `MultiDiGraph`-edge-collision class
Stage 2 already hit once, for `PINNED_TO`/`LABELLED_AS`). Fixed: `f"{ALIGNED_TO}:gold"` /
`f"{ALIGNED_TO}:solver"` keys, so both coexist as parallel edges; regression test added
(`test_solver_edges_never_overwrite_a_gold_edge_on_the_same_pair`).

**Deferred along the way, not silently dropped:** persisting `DELETION_GAP` ("no HTR match found")
and `SOFT_CLIP` ("dropped as margin content") as their own graph-level facts. Both are real,
useful signals (a `DELETION_GAP` says a baseline resolution has no HTR counterpart in this
bracket; a `SOFT_CLIP` says an HTR resolution is margin content belonging to nothing), but adding
them means either a new edge type with no target node (for `DELETION_GAP`) or a node-level
attribute (for `SOFT_CLIP`) — a real schema question, not decided here. Step 4.6 reads them live
from `align_bracket`'s output instead of persisting them, as a stated stopgap.

#### Step 4.6 DONE (2026-10-09) — a human-readable week/month report, resolution-level drill-down
Per the user's request: `sequence_graph.query.query_range(start, end, solver_dates=...)` — group
in-scope dates by ISO week; each date shows its `PINNED_TO`/`LABELLED_AS` verdict (observed vs.
inferred, reusing `classify.py` directly) and its `ALIGNED_TO` coverage (via
`consolidate.node_aligned_bucket`, the same classifier `aligned_to_status` partitions with, so a
date's own number and the corpus-wide number are never read two different ways). Drilling into a
session lists each HTR resolution's own correspondence: where it cleanly matches one baseline
(enriched) resolution, states that directly (gold or solver, tagged); where a stretch doesn't
resolve cleanly, shows the correspondence state and the proposed cut the solver's own move trace
implies (`SOFT_CLIP` → "dropped as margin content", `INSERTION_SPLIT` → "proposed cut"), read live
from `align_bracket`'s output (`run_bracket` extended to return `flat_ids`, so a read index maps
back to a real HTR id) rather than invented — and "not yet attempted" wherever the solver hasn't
run at all, never silence and never a blank filled in by assumption. Works from a notebook too
(`notebooks/sequence_graph_exploration.ipynb` §8), calling the exact same function the CLI's
`--range`/`--solver-dates` flags call. One real bug found and fixed while testing: a date carrying
both `PINNED_TO` and `LABELLED_AS` to the same session (the Stage-2 `MultiDiGraph` case) was
drilled into twice; deduped by session id, same pattern `query_date` already used for its own
"OBSERVED path" loop. **Gate: PASS.** 5 new tests in `tests/test_sequence_graph_query.py`
(ISO-Monday week-start arithmetic, gold-only coverage, solver-run proposed cuts and dropped
content, empty range, multi-week grouping); full suite 894 passed, 10 skipped (pre-existing,
unrelated); `data_io.check`/`scripts/svz.py doctor` clean. Carries forward Step 4.5's scope limit
(solver output only exists for `boundary_gold_sample` days today) and its deferred item (no
persisted `DELETION_GAP`/`SOFT_CLIP` facts yet — this report reads `align_bracket`'s live output
for that detail instead, which is itself the honest workaround, not a fix).

#### Step 4.7 DONE (2026-10-09) — `match_cost`/`gap_cost` fitted; still loses to the uniform null
`sequence_graph/fit_cost.py`: `build_calibration_pairs` (344 gold-matched positives from
`boundary_gold_sample`, 344 within-day-derangement negatives via
`scripts.d1c_idf_band_order_eval.deranged_indices`/`control_offsets` — the exact technique
already used for the 0.9555 TF-IDF AUC check, not a new method), `fit_match_logit` (sklearn
`LogisticRegression`, one feature, unregularized), `fit_deletion_rate` (empirical, an
upper-bound proxy — "gold does not locate it" conflates true deletion with "not annotated",
same caveat `add_aligned_to_gold` already carries). `CostModel.match_cost` changed to the real
log-probability form (`-log(sigmoid(intercept + coef*overlap))`, i.e. `softplus(-z)`) when
`match_logit` is set — a genuinely different *shape*, not the old linear form with fitted numbers
— gated behind `match_logit=None` by default so no existing test or run changes.
**`insertion_cost`/`split_discount`/`soft_clip_cost` deliberately NOT fit** (no split-vs-margin-
content calibration population exists yet — stated in `CostModel`'s own docstring, not silently
dropped).

**Result, reported against the standing guard (never absolute):** fitted parameters —
`match_logit = (-0.40, 0.45)`, `deletion_rate = 0.421` → `gap_cost = 0.866` (unfitted default
`1.0`). Across all 50 alignable gold days (456 `k_e` total): **unfitted separated 69 (15.1%) →
fitted separated 206 (45.2%)** — a real, ~3x measured improvement over the Decision-2 placeholder.
**But the uniform-null spread still scores 337 (73.9%) on the same population** — the fitted
model is a large step forward from the unfitted one and still well short of the trivial baseline
`docs/ITERATION_POLICY.md` requires every `separated` claim to clear. **This is not yet a result
that beats the null, and is not reported as one.** `exact_agreement` could not be scored across
this population at all: `run_bracket`'s current convention nulls a whole day's agreement if even
one resolution is gold-unlocated, and the 42% deletion rate just measured means that is true of
nearly every multi-resolution gold day — a real limitation of the evaluation tool itself, found
while running this, not of the cost model, and not yet fixed.

**Gate: PASS (mechanical).** 9 tests in `tests/test_sequence_graph_fit_cost.py` (balanced
calibration pairs, non-circularity verified by source inspection — `align_bracket`/
`add_aligned_to_solver` never appear in `fit_cost.py` — positive overlap exceeds negative on
average, fitted slope is positive, deletion rate is a genuine proportion, scope discipline on
which fields move, the fitted formula is a real log-probability checked against a hand-computed
value, the unfitted default is unaffected). Full suite: **903 passed**, 10 skipped;
`data_io.check`/`scripts/svz.py doctor` clean. **No gate on `separated`-vs-uniform-null itself
has passed** — that is Stage 4's real go/no-go gate (per the original plan), and today's result
does not clear it.

**Next:** (a) fix `run_bracket`'s all-or-nothing `exact_agreement` so partial gold coverage can
still score a day, instead of nulling it — needed before correctness (not just `separated`) can
be compared at all; (b) the three-mechanism benchmark comparison (decision 4, still deferred);
(c) the corpus-wide extension past `boundary_gold_sample` days (Step 4.5's named scope limit);
(d) design the split/margin-content annotation population `insertion_cost`/`soft_clip_cost` need;
(e) Stage 5, only after those.

### Stage 5 — scripts become drivers. NOT STARTED
`reconcile_sequences.py`, `bracket_gap_census.py` (rebuilt per decision 2),
`bracket_business_ledger.py`, `type_scan_gap_findings.py` reduce to the 79-line
`build_running_axis_snapshot.py` pattern. Delete the duplicated physical-coordinate readers
(`session_scans` / `observed_scans`, identical bodies), `monotone_anchors`, `implied_range`.
`running_axis.axis`/`chain` keep their public API; `build_brackets` becomes an adapter over the
graph only once Stage 2's gate has held (it has). Has no dependency on Stage 4's fitting work
except the `build_brackets`-as-graph-adapter piece; the script-retirement half could be its own,
smaller session.

## Verification

- `uv run python -m pytest tests/ -q`; per-module `tests/test_sequence_graph_*.py` following the
  existing `test_running_axis_*.py` convention.
- `uv run python -m data_io.check`; `uv run python scripts/svz.py doctor`.
- **Regressions that must not move:** `type_scan_gap_findings --strict-only` reproduces `room <
  charge` on **155 of 593** brackets and **600** total; `build_brackets` class counts still match
  `scripts/session_offset_eval.py`; gap/bracket accounting still reproduces the ledger
  digit-for-digit; `assert_no_sidelined` returns zero over all sequence datasets.
- **Round trip:** consolidation from persisted records equals consolidation from a live build.

## Risks, stated

- **Scale.** Six-plus sessions, not one. Stage 2's gate was the go/no-go: if the graph could not
  reproduce 323/406/261, the plan was to stop rather than adjust the target.
- **A spine can become an eighth track.** The mitigation is the mapping table above: it must
  absorb the seven, not sit beside them. If any track cannot be stated as a question about an
  edge, the model is wrong.
- **False precision in the cost model.** A fitted weight will correctly give a weak channel
  near-zero influence, not resurrect it. Group C's 30.9% and Group B's 9.6% are parameters, not
  rehabilitated channels.
- **No placement change in Stages 0–3b, and none yet from Stage 4 either.** Stage 4 is the first
  thing that *could* move a placement, and it is gated on `separated` against the uniform null —
  not gated yet, so nothing in production has changed.
- Cut proposals stay out of scope: they need the per-anchor known-point chain persisted, and
  `s6b_known_point_ledger` writes only 16 aggregate records while rebuilding its chain in-process
  from three Excel overlap files.

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

1. **The foundation is circular until the mapping question is sized.** Confidence order puts
   `session_boundary` first at weight 5.0, but a confidently-pinned session can be wrong with
   nothing flagging it — `1630-02-22` is `ledger_direct`, `inventory_ambiguous == False`, 28
   resolutions against a 12-paragraph axis. The open `docs/DECISIONS.md` 2026-09-30 item
   (“Pinned-but-wrong session mapping”) is therefore a **prerequisite for step 1 of the procedure**,
   not optional housekeeping.
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
<!-- status: todo — prerequisite, see guardrail 1 -->
Run the cheap follow-up Step 6 named and never executed: for pinned sittings, compare the enriched
date against the content-verified raw session date (`s6b_session_fingerprint_match`) rather than the
flat label. 70 pinned sittings already resolve to a session labelled more than a day away.
**Gate:** how large is the population whose most objective anchor is untrustworthy?

### Step 2 — Verify the harvest join and scope
<!-- status: todo -->
Confirm the char→paragraph mapping and the harvest's `window` scope (guardrail 6). Without this the
ensemble cannot be placed on the axis the DP uses.
**Gate:** every seed-day anchor maps to exactly one paragraph index; harvest scope is known.

### Step 3 — Partial abstention in `segment_day`
<!-- status: todo -->
Allow the DP to return “unresolved” for a gap while reporting resolved anchors around it. Score on
gap mass **and** gold correctness (guardrail 5). Compare against today's fabricated-precision
output on the pathology corpus seed days.
**Gate:** on `1630-02-22`, output is 7 placements + 2 characterised gaps; corpus-wide gap-mass and
gold correctness both reported.

### Step 4 — Staged propagation, one channel at a time
<!-- status: todo -->
Add channels in `CHANNEL_WEIGHT` order, measuring gap-mass reduction and gold correctness per
channel added. Contradiction rule and termination condition fixed before the run (guardrails 3, 4).
**Gate:** does each channel reduce gap mass without degrading correctness? A channel that reduces
gap mass while degrading correctness is rejected, per guardrail 5.

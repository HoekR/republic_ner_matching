# Scan-sequence track — anchoring on the physical page order

<!-- doc-status: active -->

Opened 2026-10-08 (user). A **complementary** track to
[SEQUENCE_ALIGNMENT_TRACK](SEQUENCE_ALIGNMENT_TRACK.md), explicitly **not** a replacement for it
(user: *"add it as a separate track, because the resolutions may still have a similar sequence,
that is fine grained but has different methods of resolving problems. So they are
complementary"*).

## SCOPE BAR, binding on everything below: the corpus ends 1630-05-14

(User, 2026-09-25; restated **FULL STOP** 2026-10-08.) The enriched XML edition ends `1630-05-14`.
Dates after it are not reconsidered and scans or HTR text after it are **not taken into account** —
not as a population, a denominator, a diagnostic or a side finding. The HTR axis runs to
`1630-12-31`, so post-bar scans exist on disk and are dropped explicitly where data enters each
script, via `scripts/corpus_scope.py`.

**Every figure in this document below was re-derived under the bar on 2026-10-08, and several
moved** — the anchor counts, the span model and the bracket table. Where a superseded number is
kept it is labelled. Do not cite a scan-track figure that is not marked as in-scope.

## Two layers, and why they stay distinct

| layer | sequence | grounding |
|---|---|---|
| **logical** | XML sitting-day calendar ↔ sessions ↔ resolutions | none physical |
| **physical** | scans, in book order, per inventory | the book itself |

**The XML baseline has no physical grounding at all.** Confirmed from `Stgen.dtd`, whose entire
element set is `zittingsdag, resolutie, p, noot, literatuur, bibliografie, scheepsnaam, plaats,
instelling, persoon, deel, postprandium, presentielijst, provincie, prespersoon` — there is no
folio, page, scan or inventory element anywhere. So every comparison involving it is
logical-to-logical *by necessity*.

**And the two layers are largely independent** (user, 2026-10-08): the edition was derived from
**another archival series**, which bears no physical relation to the series REPUBLIC imaged and
HTR'd. So they are not two views of one physical object. The consequences are specific:

* **Couple at the DAY, never at the position.** The shared invariant is that both witnesses record
  the same meetings on the same days. Pagination, physical extent, and within-day ordering are
  *not* shared, so the edition's `resolution_index` must never be assumed to map positionally onto
  the HTR's sequence, and `k_e` is usable only as "how much business that day held", never as a
  proxy for physical extent.
* **Independence is a virtue here, not a limitation.** The central failure of 2026-10-07 was that
  the enriched date and the axis label agreed in 100% of `T`/`E` rows **because the pipeline forced
  them to** — agreement carried no information. These two layers cannot be forced into agreement
  that way: they come from different archival series by different routes. So when they *do* agree,
  it is evidence, and when they disagree, the disagreement is real rather than an artefact of how
  the pin was made. That is the main methodological reason to keep both tracks running.
* It also supplies a principled source for the span model's irreducible residual (~2 scans):
  insertions and redactional differences present in one witness and absent from the other.

## Why this track exists: the dates were never the problem, the coordinate was

(User, 2026-10-08, on the 2026-10-08 finding in the sibling track.) 14 human page reads showed
HTR reads heading dates accurately — **13 of 14 are genuinely written on the page** — while the
recorded label is on the page in only 5 of 14, and within one session the resolution text and the
attendance region date about two weeks apart. The defect is in **region→session attribution**, not
in date reading.

`scan_id` is *observed* in the region metadata. Session attribution is *inferred*, and often
wrong. So keying a date to its **scan** rather than to its session routes around the defect
entirely, without fixing it first.

### Measured: the anchors behave on this coordinate

Parsing each `date` region's own text (`h_session_date_vs_heading.read_heading`, with the
weekday-internal-consistency filter) and keying by `scan_id`, **never consulting session
attribution**:

| inv | anchored scans | scan range | density | monotonicity violations |
|---|---|---|---|---|
| 3185 | 133 | 4–517 | 26% | 1 of 132 |
| 3186 | 141 | 4–533 | 27% | **0** of 140 |
| 3187 | 128 | 4–778 | 17% | 1 of 127 |
| 3188 | 146 | 10–630 | 24% | 1 of 145 |
| 3189 | 152 | 17–614 | 25% | **0** of 151 |
| 4562 | 8 | 143–210 | 12% | 0 of 7 |

**708 anchors, 3 monotonicity violations in 702 consecutive pairs — 0.4%.** **SUPERSEDED by the
scope bar (2026-10-08): 98 of those 708 anchors are dated past 1630-05-14, so the in-scope figure
is 610 anchors**, almost all of the loss in 3189 (whose second half is post-bar). The per-inventory
table above is pre-bar and is kept only for the monotonicity rates, which are unaffected in
3185–3188. The comparison this sentence used to draw — "against an 80.9% heading-vs-label
disagreement at session level" — is also superseded: that rate was itself computed over a
population including 184 post-bar sessions and is **77.8%** under the bar. Two further consequences:

* **Density ~1 anchor per 4 scans**, so gaps are narrow (median 3 scans) — the regime where the
  existing count-constrained DP demonstrably works.
* **Monotonicity becomes a free error filter**, which it never was at session level: a scan-keyed
  date running backwards is detectably wrong, with no extra evidence needed.

## Nothing ever explicitly ends (user, 2026-10-08)

*Sessions never explicitly end — they implicitly end when another session begins, and the same is
true of resolutions.* This is structural, not a detail, and it decides the shape of the whole
track.

An end is therefore **not a missing datum that better data could supply; it is not a thing that
exists.** Every start claims forward until the next start. Three consequences:

1. **The bracket is the natural unit, not an approximation.** The scan axis is a partition by
   start points, so comparing inside a bracket is comparing where the structure actually is.
2. **No scan between two anchors is ever unclaimed** — the earlier anchor claims it. This is
   exactly the 2026-10-06 orphan-page error: 420 scans looked unclaimed, and all 86 checked
   belonged to the left bracketing session. That came from deriving an extent as `max(page_ids)`
   instead of "forward to the next start". So **`ES metadata.page_ids` recording only starts is
   COMPLETE information, not partial** — the defect was in the modelling, never in the field.
3. **A bracket cannot be compressed.** Room is fixed by the anchors, so `room < predicted` can
   only mean non-contiguous anchors, absent pages, or a wrong anchor — never that the same
   business was squeezed into fewer pages.

It holds at both granularities, which is precisely why the two tracks are complementary rather
than redundant: the same forward-claim rule governs resolutions inside a session (track 4's
business) and sessions inside a volume (this track's).

## The span model, measured — and it is a weak constraint

User's proposal: a sitting occupies some number of pages, with a distribution and a margin.
Refined on the user's own caveat (*"resolution length may vary as well and it is not always
visible in the XML version, especially if there are insertions"*).

**Refitted with sitting-days and `k_e` as separate predictors** (`scan_anchor_brackets`, **600
in-scope brackets**, fitted on the core so pathological brackets cannot set the coefficients):

```
room_scans  ~  0.16  +  0.872 * sitting_days  +  0.071 * k_e
core MAE 1.32 scans, residual sd 2.06
```

**REFITTED UNDER THE SCOPE BAR, 2026-10-08, and the reading changes.** The pre-bar fit over 698
brackets was `0.29 + 1.321*sitting_days + 0.036*k_e`, from which this section concluded that *"a
sitting day costs ~1.3 scans almost regardless of how much business it holds"* and *"about 28
resolutions to a scan"*. **That was an artefact of post-bar brackets**, which lie in 3189's second
half where no day carries any `k_e` at all and every day counts as sitting — so the fit had no
choice but to load their room onto the day term. In scope it is **~0.87 scans per sitting day and
~14 resolutions to a scan**: `k_e` matters about twice as much as this track claimed, and the
fixed per-day overhead is smaller than claimed. The qualitative conclusion that follows (a weak
constraint, a resolver not a detector) survives; the coefficients and the "28 resolutions" figure
do not.

**A first single-predictor fit (`1.42 + 0.107*k_e`) was wrong in application** — its per-BRACKET
intercept was applied per DAY, inflating multi-day predictions and manufacturing a spurious
"less room than business" class of 35%. Corrected, that class is 6%.

The corrected fit revises the `k_e` idea itself: **a sitting day costs ~1.3 scans almost
regardless of how much business it holds**, while a resolution adds ~0.036 (about 28 resolutions
to a scan). Most of what `k_e` appeared to explain was "more days means more resolutions". That is
what the implicit-end principle predicts — the per-day cost is heading, attendance and layout,
fixed overhead claimed forward until the next start.

**It remains a weak constraint, deliberately.** Residual sd ~2 scans against a median bracket of
3, so the model narrows a bracket and never determines it: a *resolver* inside an already-bracketed
gap, never a *detector*. **Do not** build a global page-allocation optimiser on this prior.

## What the comparison produces

Per bracket: room (`to_scan - from_scan`), requirement (sitting days from the XML calendar, plus
`k_e`), predicted span, residual, type. Measured over 600 in-scope brackets:

| type | n | what it means |
|---|---|---|
| `fits` | 517 (86%) | accounted for; unread dates in between are merely unread |
| `more_room_than_business` | 53 (9%) | unaccounted pages — **where to look** |
| `less_room_than_business` | 30 (5%) | non-contiguous anchors, absent pages, or a bad anchor |

(In-scope, 600 brackets, 2026-10-08. Pre-bar these read 587/68/43 of 698.)

`less_room` is dominated by **4562**, whose 8 anchors span 700-day gaps on adjacent scans — so its
chain is rejected wholesale by the rule itself, not by name. The informative class is `more_room`,
which names a scan range and a quantity, e.g. `3185` scans **327→340: 13 scans between 21 and 22
August, one sitting day, ~11 unaccounted** — either an unread heading sits in there or the anchors
bracket something the calendar does not record.

## Coverage is the limiter, and the chain can bootstrap it

Of 2,295 `date` regions on 1,794 distinct scans, **1,351 fail the strict parser** and only 708
scans survive with a weekday-consistent date (**610 of them in scope**). The failures are overwhelmingly *abbreviated
continuation headings* — `"14. Januarij."`, `"19. Meij."` — which carry no weekday and no year, so
`DATE_PHRASE` (weekday + `den` + day + month + year, in order) cannot fire.

**But the chain supplies exactly the missing context.** Once two anchors bracket a gap, the month
and year are known, so a loose parser becomes *safe* precisely where it is currently unsafe —
bounded by the bracketing dates and checkable against monotonicity. This is a bootstrapping gain
and likely worth several hundred additional anchors. It is the cheapest first step in this track.

## The sharing rule, and the threshold guard

**Days share a scan only when one of them is `Nihil Actum` or should have been** (user,
2026-10-08). Mechanical: a nihil day is two lines, so it never needs its own sheet — it is written
at the head and the real day follows. Tested over the 66 scans carrying 2+ distinct parsed dates
(9.1% of 725 dated scans; an undercount, since the strict parser misses abbreviated continuations):

| the sharing scan involves | n | share |
|---|---|---|
| an explicit `Nihil Actum` | 43 | 65% |
| a Sunday not XML-marked nihil | 9 | 14% |
| a near-empty day (k_e ≤ 2) | 5 | 8% |
| **none of these — all busy days** | **9** | **14%** |

**86% fit the rule.** The sharing day sits at `k_e = 1` — the nihil entry itself (`scan 0342`:
23 Aug nihil k_e=1 + 24 Aug k_e=18). So sharing is *predictable from data already held*, not noise.

**THRESHOLD GUARD** — *superseded 2026-10-08 by the measurement in Step 1b below: `k_e >= 3` was
never the weak part, the flat one-scan charge was.* A day is taken to require its own scan when it is not nihil and
`k_e >= 3`, set from the measurement above (observed sharing days sat at k_e ≤ 2). **It must never
be tuned against the contradiction count**, because slackening the requirement drives
contradictions and forcing to zero *together* — the same gameability the `separated` guard exists
for. Sensitivity, so the dependence is visible: not-nihil alone gives 169 forced / 26
contradictions; k_e≥3 gives 139 / 13; k_e≥4 gives 136 / 9.

## Step 1 DONE 2026-10-08 — bootstrap works, two of my own design claims did not

`scripts/bootstrap_scan_anchors.py` → `scan_anchor_bootstrap`. A loose parse is accepted only when
it disambiguates to **exactly one** date strictly inside the bracket; zero or several is a decline.

| | anchors | monot. violations | median width | forced brackets | forced resolutions | contradictions |
|---|---|---|---|---|---|---|
| strict only | 610 | 3 (0.49%) | 3.0 | 139 | 2,079 | 13 |
| + bootstrap | **1,054** | 6 (0.57%) | **2.0** | **277** | **4,138** | **26** |

**Re-derived under the scope bar, 2026-10-08.** Pre-bar this table read 708 → 1,228 anchors
(+520), 8 violations (0.65%), 284 forced / 4,281 resolutions / 27 contradictions. The bar removes
98 strict anchors and 76 bootstrap ones, so the real gain is **+444, not +520**. Monotonicity still
passes its 1% gate.

**Validated by hold-out, which is what makes the gain trustworthy.** Mask 20% of strict anchors,
rebuild the brackets from the remainder, and let the loose parser recover them: of 677 masked
scans inside a usable bracket, **96.6% recovered correctly, 1.3% wrong, 2.1% declined — 98.6%
precision when it answers.**

**Forced resolutions doubled, 2,079 → 4,138 = 21% of 19,278** (pre-bar: 4,281 = 22%), said at the time to clear "the
declared 20% kill threshold, but only just". **That threshold was never declared by anyone** — see
the provenance note in Step 1b. Disregard the clause; the +444 anchors rest on the hold-out
precision above, which needs no threshold.

### Problems, including two of mine

1. **The contradiction gate was badly designed and is withdrawn.** It conflates anchor error with
   requirement-rule error. The hold-out shows anchors are 98.6% precise, so the growth 13 → 27 is
   mostly the `>=1 scan per busy day` rule being too strong: at ~28 resolutions per scan, two or
   three modest days genuinely can share a spread. Contradictions stay as a *diagnostic list*, not
   a gate. **Monotonicity remains the gate** — it is a pure ordering property, independent of any
   requirement assumption.
2. **No compounding.** The track claimed new anchors would narrow brackets and make the next pass
   safer, repeatedly. It converged after **one** pass: a single pass exhausts the unparsed regions
   inside brackets. The compounding argument was wrong.
3. **Monotonicity rate rose** 0.49% → 0.57% in scope (pre-bar 0.42% → 0.65%) — passes the 1% gate,
   consistent with the measured 1.3% loose-parse error.
4. **The 22% rests on an unmeasured assumption.** "Every day with `k_e >= 3` occupies at least one
   scan" was set from the *sharing* measurement, which is about nihil days, not about whether a
   busy day fills a sheet. Until scans-per-day is measured as a function of `k_e`, the forced
   figure is soft in a known direction.

**Therefore the next step is not more anchors but a measurement:** scans per day against `k_e`,
which replaces the assumption with a number and turns the forced count into a real one.

## Step 1b DONE 2026-10-08 — the measurement is in, and the 22% does not survive it

`scripts/measure_scans_per_day.py` → `scans_per_day_by_ke`. A day's exclusive extent is
`first_scan(next date) − first_scan(this date)` (the forward-claim rule), counted only on
**calendar-adjacent** anchor pairs, so no unread day in between can absorb part of the room.

Two things had to be kept that `build_scan_anchor_brackets.py` discards, or the answer would have
been true by construction: **every `(scan, date)` observation** rather than `setdefault`-collapsing
a scan to its first date, and **`room == 0` brackets** — those *are* the zero-scan days.

### The rule's premise holds; its arithmetic does not

225 sitting days measured (strict anchors, 4562 excluded; median `k_e` 13 against 13 corpus-wide,
so representative on `k_e`):

| `k_e` | days | P(0 scans) | P(1) | P(≥2) | mean | median |
|---|---|---|---|---|---|---|
| 1–2 | 7 | 0.57 | 0.43 | 0.00 | 0.43 | 0 |
| 3–5 | 13 | 0.308 | 0.538 | 0.154 | 1.15 | 1 |
| 6–10 | 44 | 0.136 | 0.682 | 0.182 | 1.07 | 1 |
| 11–20 | 143 | 0.007 | 0.287 | 0.706 | 2.15 | 2 |
| 21–35 | 18 | 0.000 | 0.056 | 0.944 | 2.39 | 2 |

At the rule's own threshold, **`P(≥1 scan | not nihil, k_e ≥ 3) = 0.950`** — so the premise *"a busy
day occupies at least one scan"* is **confirmed**, and that was the stated worry. The real defect is
elsewhere: **`P(exactly 1) = 0.362`, mean 1.89**. The step is at `k_e ≈ 10`, not 3 — a day under ten
resolutions takes one scan, a day over ten takes two. Independently corroborated from a different
population: the 288 in-span *non*-adjacent pairs give a diluted 1.84 scans/day mean, 1.69 median.

Charging what days were measured to take, `room < charge` rises from 13 brackets to **155 of 594
in-span brackets (26%)**. The flat charge was not merely soft — it was low by about half.

### Two defects in the forced count, one of them pure bookkeeping

`forced` fires when `room == len(required days)`. Re-derived here (the flat column reproduces
`bootstrap_scan_anchors` **139 / 2,079 / 13** and (pre-bar) **284 / 4,281 / 27** to the digit, so the
comparison is like for like):

1. **76% of the forced resolutions were never unplaced.** The bracket's day list opens at `d_a`,
   which is the bracket's own **left anchor** — its scan is observed, not deduced. Of the in-scope
   4,138, **3,161 sit on that anchor day** and only **977 are newly positioned**; **228 of the 277
   forced brackets charge nothing but their own anchor day.** This is independent of any
   measurement — a bookkeeping error in `metrics()`.
2. **`room == charge` is not a determination once days take ≠ 1 scan.** Positions follow from
   cumulative charges, so the exactly-one-scan assumption must hold for every charged day but the
   last. At the measured `P(exactly 1) = 0.300`, **≈493 of the 977 survive** (independence across
   days assumed).

**So the real forced figure is ≈493 of 19,278 = 2.6%, not 22%** (strict-only: 388 = 2.0%). All
figures in this step are in scope; the pre-bar equivalents were 4,281 / 3,261 / 1,020 / ≈496.
**The bootstrap's +444 anchors stand** — the hold-out precision of 98.6% is untouched by any of
this, and `room < charge` is now a much larger and better-grounded diagnostic list. What falls is
the *forcing* claim built on top of them.

### Provenance of the forcing frame (user challenge, 2026-10-08): it is not the user's

Checked against the record when the user asked. The user's own contributions to this track are:
its complementarity to track 4, the two layers' independence and why that makes agreement
informative, **nothing ever explicitly ends**, the **sharing rule** (days share a scan only when one
is nihil actum or should have been), the caveat that resolution length varies invisibly because of
insertions, and *the dates were never the problem, the coordinate was*. **The forced count as this
track's headline metric is not among them**; it was introduced here, by me. Its ancestor is "64 of
223 Sunday-to-Sunday windows forced by counting alone" (`docs/DECISIONS.md` 2026-10-06), which was
likewise a determinacy metric I derived from the user's weekly-walk rule — and that rule was local
alignment with a Sunday reset plus checking neighbouring session texts, not a counting-determinacy
claim. **The "declared 20% kill threshold" was declared by nobody**: it occurs nowhere in this repo
outside the sentence that cites it as "declared" and the PLAN.md entry quoting that sentence.

Consequence, and it is larger than the retraction above: the measurement in this step kills a metric
that was never asked for, so *"forced went from 22% to 2.6%"* is not a loss of anything the track
was promised. The things with independent standing are the anchors (hold-out precision), the
monotonicity filter (a pure ordering property), and the `room < charge` list. Step 3 below is
rewritten accordingly.

### Side findings

* **RETRACTED, same day, on the user's challenge: there is no "unaccounted room" class.** This
  section first reported *"47 anchored days absent from the edition entirely, consuming 105 scans —
  physical room no `k_e` can account for"*. Checked date by date, **all 47 are inventory 3189 dated
  1630-05-29 to 1630-12-09, and the edition ends 1630-05-14.** They are out of the edition's scope,
  not unaccounted paper — the boundary `running_axis` already records ("180 past the edition's
  1630-05-14 end while the axis runs to 1630-12-31"). With the span filter in place, **0 anchored
  days inside the edition's span are unrecorded by it**, so the class is empty, not small. The
  script now excludes past-end days and brackets from every denominator and prints any in-span
  unrecorded day individually. Lesson, which is the `measurement-vs-mechanism` trap again: a
  missing `k_e` has two causes — a day the edition skipped, and a day the edition never reached —
  and I reported the interesting one without separating them.
* **The same error was in the bracket denominator.** 97 of the 691 brackets (145 of 1,067 with
  bootstrap) lie wholly past the edition's end, where every day is charged 0 and no bracket can
  ever be forced or contradictory. In-span denominators are **594** and **922**. The forced and
  contradiction *counts* are unchanged; the rates were understated.
* **My own bias hypothesis was wrong.** The strict parser needs a full heading, which a day opening
  a fresh sheet gets, so I expected strict-only days to over-represent long days and the
  bracket-interior days to be shorter. Measured by anchor source, bootstrap-recovered days run
  *longer* (mean 2.31 vs 2.15), not shorter. Caveat on that comparison: bootstrap anchors are
  one-per-scan by construction, so they **cannot** speak to `P(0)` at all; conditioned on `≥1` the
  two are 2.31 vs ~2.25, i.e. no evidence that interior days are shorter.
* The nihil instrument check is **too small to read** — 2 adjacent nihil days on strict anchors,
  both at 1 scan. It neither supports nor contradicts the sharing rule.
* **Known bias, carried in the dataset:** the population is days whose own *and* whose next day's
  heading both parsed, i.e. conditioned on two consecutive legible headings — 225 of 1,433 sitting
  days (15.7%), 551 (38.5%) with bootstrap.

**The THRESHOLD GUARD above is superseded, not retuned.** `k_e ≥ 3` was never the problem; a flat
one-scan charge was. Any successor rule is the measured step function (`scans_per_day_by_ke`'s
`measured_requirement_scans_per_day`), read off the data and monotone by construction, and it still
must not be tuned against the contradiction count.

## Step 3 DONE 2026-10-08 — the timeline is typed, and the finding count is 57, not 155

`scripts/type_scan_gap_findings.py` → `scan_gap_findings`. One row per bracket, ordered along the
axis, with a type, a quantity and the images; plus per-inventory-per-quarter timeline rows. Same
review-worklist form as `unplaced_date_review`, whose `iiif_url` is imported rather than
reimplemented (the populations are disjoint — that one lists enriched dates with no HTR session,
this one lists stretches of paper). **No count of determined placements**, per the rewrite above.

**The construction is verified, not asserted:** the strict run reproduces `room < charge` on
**155 of 593** brackets excluding 4562 — exactly the published figure — and 600 brackets, exactly
`scan_anchor_brackets`.

### The 155 is mostly what a median predicts

`room < charge` charges each day the **median** of its `k_e` bucket, so a bracket a scan or two
short is the expected case, not a finding. Replacing the median with the **empirical distribution**
of exclusive extents for each bucket (`scans_per_day_by_ke`'s day rows, 4,000 draws per bracket,
two tails at α = 0.05) leaves:

| anchor set | brackets | fits | shortfall | surplus_room | anchor_suspect | no business |
|---|---|---|---|---|---|---|
| strict (610 anchors) | 600 | 534 | **8** | **49** | 7 | 2 |
| strict+bootstrap (1,054) | 952 | 842 | **24** | **28** | 41 | 17 |

So **155 → 8** real shortfalls on the clean anchor set. Nothing is fitted and there is no tolerance
to tune: the null is the measurement. Both runs are written, keyed by `anchor_set`, because they
disagree 3x and one view would hide it — the bootstrap converts surpluses into shortfalls by
splitting roomy brackets, which is what filling in a heading should do.

### `surplus_room` means a heading nobody read — confirmed by an independent instrument

Counts cannot be compared across the two runs by subtraction, because a new anchor moves the
bracket boundaries. The direct test: how often Step 1's bootstrap later placed an anchor **inside**
a strict-run bracket, by type. The bootstrap ran before these types existed and never saw them.

**63% of surplus brackets got an interior anchor against a 29% `fits` base rate (2.2x).** The class
is real. **But `shortfall` scores 62% on the same test**, so what the signal detects is "abnormal
bracket", and it does **not** discriminate surplus from shortfall. Supporting (and not used for
typing): 76% of strict surpluses have an interior scan carrying a date region the parser declined,
against a 48% base rate.

### Three things carried as evidence and deliberately not used to type anything

Otherwise "do loose anchors explain the findings" would be true by construction. Cross-tab against
the `fits` base rate, strict+bootstrap run: `loose_anchor` 75%/71% vs 54%, `long_span` 17%/0% vs 1%,
`repeated_anchor_date` 12%/4% vs 1%. A date read off two widely separated scans cannot be right at
both — `3187` scan 320 and scan 434 both claim early August 1628 — and that shape dominates the top
shortfalls, but it is left as evidence for the reviewer.

### Problems and limits, stated

1. **The parse-error bound is not negligible on the dense run.** 444 loose anchors at the hold-out's
   1.3% error rate corrupt ~12 brackets (2 each) against 52 findings, so **up to 22%** of the
   bootstrapped findings could be a bad anchor rather than bad paper. The strict run has no loose
   anchor anywhere and is the clean comparison. This is a bound printed beside the count, never a
   filter.
2. **The nihil-undercount hypothesis is a measured no-op.** A nihil day is charged 0, so an
   undercount would make brackets look short for free, and the production *status column* does
   undercount by 34 dates. But this track never read that column: `calendar()` runs `is_nihil_actum`
   over each date's own text and recovers all **161**, the identical set. **0 shortfalls absorbed.**
   Both charges stay in the rows as a regression guard, not as an explanation.
3. **"Missing pages" is not a type here and no row claims one.** Scan numbering inside an inventory
   is contiguous, so a digitisation gap is not observable from this data. A `shortfall` says the
   paper between two dated headings cannot hold the days the calendar puts there, and leaves the
   cause to the image.
4. **The population bias is inherited unchanged** from `scans_per_day_by_ke`: the null is built from
   days whose own and whose next day's heading both parsed (225 days strict, 545 with bootstrap).

### Where the timeline is worst

On the clean (strict) run, half of all 8 shortfalls sit in **1629Q4 — 4 of 31 brackets** — and the
49 surpluses concentrate hard in inventory **3187, 1628Q3–Q4 (19 of 49)**. The dense run agrees on
`1629Q4` (6 of 49) and adds `1626Q1` (5 of 43), which the strict run does not see (1 of 39), so
`1629Q4` is the one hotspot both anchor sets find. Note this does **not** reproduce the
quarter-drift profile, which called 1626–27 severe and 1628 near-clean: the paper's worst stretches
are not the drift's worst stretches. `1630Q2` has 17 brackets and no findings, the edition ending
mid-quarter.

## Steps

1. **Build the scan axis** — one `(inventory, scan, page-side)` coordinate with the 610 in-scope verified
   anchors on it, reusing `running_axis.chain` rather than a second implementation. Note scans are
   **two-page spreads** (left x≈200, right x≈1460 in region coordinates, seen on
   `NL-HaNA_1.01.02_3185_0190`), so the physical unit is the page and the rate belongs in pages.
2. **Bootstrap the parser** inside brackets, as above; re-measure anchor density and monotonicity.
   Monotonicity violations are the gate: if loosening the parser raises them materially, stop.
3. **Type the gaps.** Between two anchored scans, the XML calendar says how many sitting days
   *must* fall there and the scan count says how much physical room exists. Disagreement is a
   typed, localised finding — missing pages, missing days, or merely an unread date.
   **Rewritten 2026-10-08 after the provenance check above:** this step previously ended "and it is
   the pigeonhole argument from the counting question", which imported the forcing frame nobody
   asked for. It is struck. The deliverable is a **localised, typed finding list** (user: *"sounds
   ok"*) — each row naming an inventory, a scan range, a quantity and a type — and *not* a count of
   determined placements. The input is the `room < charge` population under the measured
   requirement: **155 of 594 in-span brackets**, now the largest and best-grounded list this track
   has produced.
4. **Translate back** to the logical layer through sessions, and re-derive session extents from a
   coordinate that works.

## Open dependency, and non-goals

* **Scan↔resolution needs ES `metadata.page_ids`.** This track yields scan↔**date**; our local
  `resolutions_flat` carries no page ids, so placing resolutions on pages requires that pull. Note
  the standing caveat (2026-10-06) that `page_ids` names only the page a resolution *starts* on,
  so extents derived from it are systematically too narrow.
* **Not** a dating correction mechanism. It produces a grounded coordinate and typed gaps; what to
  do about a wrong date stays with the sibling track and still needs sign-off.
* **No placement change** from any step here without the usual `separated`-against-uniform-null
  scoring.

## Both layers on one bracket — `bracket_business_ledger`, 2026-10-08

`resolution_archival_provenance`'s `flat_id → scan_ids` is the join that finally lets the HTR side
onto the scan axis. Every earlier bracket measurement compared physical room **in scans** against
logical business, and a scan is a weak unit (~14 resolutions to a scan; span-model residual sd ~2
scans against a median bracket of 3). Now the comparison is resolution-to-resolution:

**593 brackets, 19,106 `k_e` vs 10,186 `k_f` vs 17,130 paragraphs.**

**Sessions are assigned, not resolutions.** Per-resolution scan coverage is 71.4% (9,145 of 12,811),
so counting resolutions-with-a-scan would deflate `k_f` unevenly between brackets. A session is
placed by the first scan any of its resolutions is observed on, then *all* its axis resolutions and
paragraphs are counted — sessions sit on contiguous paper, so the placement survives patchy
coverage. **Known defect of that rule:** a session spilling into a bracket from the left is not
counted, which undercounts paragraphs on wide brackets. Fixed to overlap in the next step.

### The misattribution instrument (user agreed to carry both coordinates, 2026-10-08)

A bracket's date range is **observed** — two headings on the paper. A session's date label is
**inferred**, and the 2026-10-08 page reads showed that inference is the broken link. So:

**364 of 593 brackets (61%) hold a session whose own label falls outside the dates observed on its
paper**, and the rate is **flat across bracket width** — 63 / 59 / 65 / 61 / 67% at 1 / 2 / 3 / 4–7 /
8–14 days — so it is not a width artefact. A census built on *logical* brackets cannot see this at
all, because there the inferred label defines the bracket. This is the first instrument here that
names misattribution candidates one at a time.

### Problem-class typology

| class | brackets | `k_e` | `k_f` | what it needs |
|---|---|---|---|---|
| D pigeonhole-blocked (`paragraphs < k_e`) | 303 | 11,974 | 4,132 | sub-paragraph cuts, or nothing |
| B edition splits finer than HTR | 115 | 2,428 | 1,662 | resolution separation |
| C HTR splits finer than edition | 78 | 1,087 | 1,760 | over-split, or foreign paper |
| A one session, several sitting days | 70 | 3,240 | 2,472 | session separation |
| E no HTR text at all | 15 | 217 | 0 | upstream loss |
| G balanced | 12 | 160 | 160 | — |

### The three rankings, and the two that measure the instrument instead of the work

Rankings 1 (gap in dates/sessions) and 2 (cumulative resolutions) are **both topped by the same two
brackets**: `3187` 305→320 (44 sitting days, 3 sessions, 665 `k_e`, 114 paragraphs, **15 scans**) and
`3185` 72→75 (30 days in 3 scans). Forty-four sitting days cannot sit on fifteen scans — these are
bad anchors, and Step 3 had already flagged that stretch via `repeated_anchor_date` (`3187` scan 320
and scan 434 both claim early August 1628). **Run them as the anchor-repair queue, or filter for
anchor sanity before reading them as separation work.** Ranking 3 (resolutions per sitting day) is
clean and independently surfaces the hand-verified `1630-02-22` (28 `k_e`, 9 `k_f`, 12 paragraphs).

### How hard is "pigeonhole-blocked"? Corrected at the day level after a user challenge

**My first answer was optimistic by 3.3x and the reason is instructive.** I judged "is there enough
text here" against the *HTR resolution* length distribution (median 554 chars, p25 306) and measured
per bracket, concluding 6,161 `k_e` were merely unit-blocked. The user's objection — *"there is an
overall ratio and distribution of `K_e` vs `K_f`"* — is right: the yardstick is what an enriched
resolution actually corresponds to, which has to be measured, and the bracket is the wrong unit
because a wide bracket pools no-HTR days in with crowded ones.

**The corpus-wide ratios, measured over the 1,059 in-scope days where both sides are present:**

| quantity | aggregate | per-day median | p25 | p75 |
|---|---|---|---|---|
| `k_e` / `k_f_res` | **1.189** | **1.43** | 1.00 | 2.00 |
| paragraphs per `k_e` | **1.420** | **1.07** | 0.83 | 1.68 |
| chars per `k_e` | **832** | **631** | 452 | 1,051 |

So the edition splits one HTR resolution into ~1.2–1.4 typically, 2+ in the top quartile — that is
the amount of splitting Track P must do. And paragraph capacity is **not** globally tight: on days
with HTR there are 1.42 paragraphs per enriched resolution.

**Decomposed per day, the blocked mass reconstructs the published ceiling to the digit:**

```
19,120  in-scope k_e on dated days
-5,590  on 535 days with NO HTR at all          <- absolutely hard, nothing to cut
-1,886  paragraph deficit on 390 days WITH HTR  <- the only part a sub-paragraph cut can reach
=11,644 = 60.9%  the published paragraph-level ceiling
```

That identity is a free regression check on both this measurement and the ceiling.

* **5,590 `k_e` (29.2% of all, 74.8% of blocked) — no HTR.** This is what the ceiling always was.
* **1,886 `k_e` (9.9% of all, 25.2% of blocked) — crowding on days that have HTR.** **This, not
  6,161, is Track P3's addressable market.** Still material: the stretch-criterion gap is 718.
* Those 390 crowded days carry **455 chars per enriched resolution at the median** against a corpus
  norm of 631 — about the corpus p25, so text-poor but inside the range the edition demonstrably
  operates in. 50.7% of the crowded mass has ≥452 chars/`k_e` (corpus p25), 77.1% has ≥314 (p10).

Caveat carried: blocked rate runs 42% → 69% as width goes 1 → 4–7 days, so the raw 318/12,191 is an
upper bound, not a point estimate.

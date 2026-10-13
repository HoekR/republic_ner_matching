# Sequence alignment track — the dating problem

<!-- doc-status: active -->

Opened 2026-10-06 (user). Reframes session dating from "correct this session's date" to
**aligning two sequences**: the XML sitting-day calendar (normative, every day recorded,
nihil-actum days included) against the HTR session sequence (archive order, drifts). See
`PLAN.md`'s canonical goal and `docs/DECISIONS.md` 2026-10-06 for the full record this file
summarizes going forward — this file is where new steps get added; `PLAN.md` keeps only the
headline.

## Strategy (user, 2026-10-06) and the model it required

The user's stated working order, to which the tracks below are subordinate:

1. **Find the good sequence.** 2. **Identify the gaps in it.** 3. **Resolve the biggest gaps first**,
by (a) placing additional anchors and (b) shifting anchors — learning from successes and failures,
since only a limited number of things can be wrong. 4. **Iterate**, with an explicit way to say
*enough* or *methods exhausted*. Hand editing is reserved for genuinely unclear, unsolvable cases.

**`running_axis/` — DONE 2026-10-06** (new package, 95 tests, `pyproject.toml` registered; dataset
`running_axis_snapshot`; `docs/DECISIONS.md` 2026-10-06). Built because steps 3–4 are *mutations* that
must preserve monotonicity, and because recomputing the sequence from dispersed sources per script is
what let **three gap counts** circulate for one ledger (120 from the one-month run on disk, 947 cited
in this file from an earlier full run, and a third fabricated set, now withdrawn). One loaded object,
every window a *view* of it, so a month and a corpus figure cannot contradict.

- **The `no_axis` defect, and the free win inside it.** `s6b_known_point_ledger` groups the axis by
  each paragraph's `date` field and `continue`s past any date with none, filing them under a
  fabricated inventory named `no_axis` (`scripts/s6b_known_point_ledger.py:412`) — although
  `axis_for_date` exists to prefer the concordance-resolved session and is simply never called.
  Decomposed and machine-checked: **1,594 enriched dates = 1,059 labelled + 66
  dropped_by_label_grouping + 125 nihil_actum + 344 no_session**; **19,120 resolutions = 13,530 + 983
  + 125 + 4,482**. The **66 dates / 983 resolutions already carry a resolved session** and are lost
  only to the grouping rule — a defect in the ledger's *measurement*, since production does call
  `axis_for_date`. October 1628 decomposes 31 = 15 + 3 + 2 + 11 instead of "15 with an axis, 16
  without".
- **Ambiguous counts are now inexpressible, not merely discouraged.** `running_axis/tally.py` binds
  every count to a registered population and a window; cross-population subtraction, overlapping-window
  addition, cross-unit ratios and empty denominators all raise. The four date counts that read as a
  contradiction were each correct over a different population: **1,240** axis date labels, **1,594**
  enriched dates, **1,059** both, **535** enriched without a label, **181** axis labels that are not
  enriched dates (180 past the edition's 1630-05-14 end while the axis runs to 1630-12-31).
- **Gap accounting and brackets DONE 2026-10-06** (`running_axis/chain.py`, 19 tests). Both
  structures, kept distinct because they are easy to conflate: **gaps** are resolution-level within a
  day (`s6b_known_point_ledger`), **brackets** are session-level within an inventory
  (`session_offset_eval`). The model **reproduces the ledger field-for-field** from its own chains —
  120 gaps, determined 70 / nearly_determined 36 / open 14, resolutions 0 / 49 / 61, chars 168,197 /
  92,920 / 51,796, `settled_share_by_gap` 0.8833 and `open_share_by_resolution` 0.5545, all twelve
  fields — and reproduces `session_offset_eval` on sittings (344, k_e 4,482) and determined pairings
  (3 sittings, k_e 40). **One documented difference:** unclaimed sessions are 263 here against its 79,
  which is exactly its 79 + the 184 sessions beyond the enriched edition's 1630-05-14 end that it
  drops via `restrict_to_enriched_span` and this model deliberately keeps visible. Production anchors
  are *not* re-derived — the ledger computes those live through `align_session`, and a second
  implementation of the thing whose numbers we want to check would be worthless as a check.

### What `missing_htr` actually means (2026-10-06)

Definition (`scripts/s4_day_status_resolution.py`): a ledger `N` row with no same-inventory HTR session
within ±14 days. So it means *no session in what upstream delivered*, *not* "no text exists".

- **Our own manipulations are cleared.** The axis carries exactly what `resolutions_flat` holds
  in-window — session numbers match per inventory (184/184, 200/200, 275/275, 266/266, 289/289), the
  136 axis-absent numbers are absent upstream too, and 4562's 102-vs-297 gap is entirely its date range
  (upstream 1615–1924; of its 288 dates exactly 98 fall in 1626–1630 and **all 98 are on the axis**).
- **No surplus of parsed HTR:** 344 unresolved sittings against **79 unclaimed sessions**
  (`session_offset_eval`), so reassignment cannot absorb them.
- **An orphan-page hypothesis was raised and REFUTED.** 420 scans appeared to sit between consecutive
  resolved sessions, 86 of them in 37 gaps bracketing a `missing_htr` date. Queried against
  `session_text_regions-2026-03-25`: all 86 carry text (1,216 regions, 8,720 lines) and **all 86 belong
  to the left bracketing session**. `metadata.page_ids` names only the page a resolution *starts* on,
  so session extents derived from resolutions are systematically too narrow. The derived "~311
  recoverable resolutions" is withdrawn.
- **A second hypothesis — under-transcription in our snapshot — was also tested and REFUTED, same
  day.** `session-3185-num-23` showed ES `para` text at 43,770 characters against our axis's 13,122
  (3.3x, same content: 54.5% of our distinct 6+ letter tokens appear in it), which looked like a lead.
  Generalised over **all 1,316 sessions** by server-side aggregation on `stats.chars`: **median ratio
  0.99, total 1.07** (per inventory 0.95-1.16), so the two snapshots carry the same resolution text
  overall and that session was an outlier, not a pattern. Per-session spread is nonetheless wide (p10
  0.42, p75 1.13, p90 2.97; 379 sessions where ES has less, 522 where it has more) while totals match
  — a signature that would fit text moving between adjacent sessions, but **that was tested too and
  does not hold**: correlation of ratio(N) with ratio(N+1) is **+0.005**, where displacement into a
  neighbour would read negative, and pooling adjacent pairs narrows the spread about as much as
  averaging any two noisy measurements. The variance is real and unexplained; no mechanism is claimed.
- **A third hypothesis — that the unplaced mass is the secret series — was also raised and REFUTED,
  and it names a trap worth remembering.** Grouping the 344 `no_session` dates by the concordance's
  `inventory_id` returns 4861: 191 dates / 2,387 resolutions and 4562: 153 / 2,095, zero in
  3185–3189. That field descends from `session_date_status_1626_1630`, which holds **3 candidate
  inventories per date** (4,916 rows for 1,594 dates) — `s6b_known_point_ledger.inventory_of`
  already declines to use it for exactly this reason. The candidates are structurally *the year's
  main inventory plus 4562* (the main series is annual, 3185 = 1626 … 3189 = 1630, while 4562 spans
  the whole period), and for a `missing_htr` date the pick was never confirmed against HTR because
  there is no session to confirm it against. **It is a tautology: dates without HTR are attributed
  to the inventories without HTR.** `DateState.inventory` is now None unless a resolved session
  establishes it, and brackets carry `rests_on_candidate_inventory`.
- **Decomposed soundly via the XML secret flags and the ES resolutions index.** Of the 323
  XML-flagged secret dates, **264 are `labelled`** — placed, with HTR — so secrecy does not imply
  missing text. Setting them aside leaves 298 dates / 3,848 resolutions; queried against ES
  `full_resolutions` by `metadata.session_date`, 26 dates / 313 resolutions exist upstream and not
  here, 272 dates / 3,535 exist nowhere.

  | the 4,482 `missing_htr` resolutions | dates | resolutions | share |
  |---|---|---|---|
  | on XML-flagged secret dates | 46 | 634 | 14% |
  | in ES but absent here — **recoverable** | 26 | 313 | 7% |
  | absent from the HTR corpus altogether | 272 | 3,535 | 79% |

  **Then withdrawn too (user, 2026-10-06): `resolutions_flat` was built from the ES resolutions
  dump**, so ES is upstream of this corpus and holds no text it lacks — the 0.99 median character
  ratio had already said so. The 26 dates are a *date-attribution* question, not missing text.
- **Which turned out to be the live finding: the date headings were never ingested.** The axis
  descends from `resolutions_flat`, which carries resolution text; ES classes text regions and the
  headings live in `date`-class ones (`attendance` too). `session-3185-num-98` opens mid-attendance
  list on the axis, while ES holds `Heeren Grave, Rantwijck, De Bie, Halewijn, Mercurij den xxen.
  Maij 1626` for it. An earlier weekday test against the axis returned 23 of 24 "no signal" — read
  as a mute channel, actually un-imported evidence.
- **Re-run against ES `date` regions with predictions fixed first**
  (`scripts/h_weekday_date_attribution.py`): **H1 16, H0 1, H2 0**, 5 no signal, 1 undecidable.
  So for **16 of 24 contested dates — 207 resolutions — the enriched date is right and this
  corpus' corrected session date is wrong**; the text is here under another date. **H2
  (Julian/Gregorian) is refuted** — all three 10-day offsets came out H1, and the 10-day offset was
  the only reason to suspect it. Two method fixes, both from the user reading the manuscript: only
  a session's *first* heading dates it, and `Praeside et Praesentibus qui heri` names **yesterday**,
  so such headings shift one day forward — which is why `session-3185-num-16`, reading 20 January
  on the image, is correctly dated the 21st here.
- **Ingestion DONE 2026-10-06** (`session_region_text_1626_1630`): 3,763 `date`/`attendance`
  regions, 262k characters, **date regions for 1,275 of 1,316 sessions (96.9%)**.
- **But the corpus-wide check that ingestion enabled is CIRCULAR — do not cite its 610.**
  The heading's date equals ES's own uncorrected `session_date` 6 of 6 sampled, because **ES
  segmented the sessions using those headings**. Heading and ES are one witness. The same applies
  to the 16-of-24 H1 result above: those dates were *selected* by "ES dates a session here", so a
  readable heading had to agree. One witness counted sixteen times.
- **The arbiter is a human reading the page** — `manuscript_date_verdicts`, 7 readings over 6
  sessions. **The recorded date agrees with the page in 1 of 7; the enriched date in 3 of 6.**
  Offsets: 0, +3, +4, +10, +15, +20, −10. Four error sources all observed: our correction, HTR in
  both directions (a stroke added *and* dropped), the clerk (`martis den xiijen` where the 13th was
  a Monday — so **weekday beats numeral**), and a calendar-style reading that the user **withdrew**
  (this corpus' dates are always modern style, so the two 10-day cases are plain errors of opposite
  sign — suggestive of a mis-applied conversion, hypothesis only).
- **Two mechanisms confirmed on paper:** `qui heri` names *yesterday*, so such headings shift one
  day forward (41 sessions carry it); and `session-3185-num-72` holds 13, 14 **and** 15 April 1626
  — a multi-day block, i.e. **sessions as anchors, not containers, read off the manuscript**. 146
  sessions show several distinct day headings.
- **A non-circular rate does exist**, from the heading's *internal* coherence (weekday matching
  its own numeral is a property of the page, not of ES's date field): of **685** sessions with a
  readable, internally consistent heading, the recorded date **disagrees in 525 (76.6%)**, agrees
  in 160. Offsets cluster small and negative (−1: 49, −2: 43, −5: 55, −6: 35), tail to −18. The
  user's 7 image reads agreed in 1 of 7, same magnitude. **Gated question ANSWERED (user,
  2026-10-06): the date correction is REPUBLIC heuristics, not an external authority** — so the
  disagreement is a heuristic against the manuscript, and the heuristic is the suspect party.
  **And the calendar authority is the XML**: every day recorded, non-session days as `nihil
  actum`, the XML baseline normative for it. So **the enriched date is normative and the recorded
  HTR session date is heuristic** — which is the direction the 16-of-24 headings pointed, a result
  still circular as a *rate* but now independently supported in direction.
- **`postprandium` is in the DTD and we discard it** (user, 2026-10-06; XML now registered as
  `enriched_resolutions_xml_source`). `Stgen.dtd` declares
  `zittingsdag ((presentielijst|postprandium?), resolutie*, noot*)+` — the afternoon sitting is a
  first-class element and the group repeats, so **several sittings per day are explicitly
  modelled**. **109 of 1,595 day files carry it**, and `enriched_resolutions_1626_1630` keeps no
  sitting field at all, so those days were flattened. Of the 109: only 3 have >1 axis session, 67
  have exactly 1, 39 have none (32 in `no_session`). Independent corroboration of Track S from the
  normative source. Only 3 of the 73 multi-session dates are postprandium days, so afternoon
  sittings are not that multiplicity's main source.
  **Not to be chased** (user, 2026-10-06): retrieving the sitting boundaries is likely hard and
  afternoon sittings explain only 3 of the 73 multi-session dates, so it stays a *recording* —
  `postprandium_days`, a 109-date lookup to consult when a day looks structurally confused before
  reaching for a more elaborate explanation.
### Track P's editorial ceiling is ~98%, not a reframing (user, 2026-10-06)

The edition follows resolution order but, per its own `verantwoording`, **sometimes lumps
same-subject resolutions on one day, with no listing of which**. Track P asks where enriched
resolution *i* begins in the HTR, which presumes the editorial and scribal units are the same kind
of object; for a lumped resolution they are not, since it has no single scribal start point.

**Magnitude, from the editor: lumping was never observed in the resolutions he has read, so
"pretty seldom" — a ceiling around 98%, not 100%.** That is an informed estimate from cases seen,
not a measurement, and the lumping stays unidentifiable from the edition side. But at ~2% it is a
footnote rather than a reframing, and the important consequence runs the other way: **the 4,516
resolutions sharing a start paragraph are overwhelmingly placement failures, not editorial
composites, so Track P's premise holds.** Report future Track P results against ~98% rather than
100%, and do not treat the collision mass as substantially editorial.

### No resolution register is missing (2026-10-06)

REPUBLIC's `data/inventories/inventory_metadata.json`: exactly **8 inventories overlap
1626–1630** — the five annual `ordinaris` registers 3185–3189, the `secreet` register 4562
(1615-12-01..1634-12-31), and two `index` volumes. **All six resolution registers are in this
corpus.** So the 3,535 unplaced resolutions with nothing in ES are absent because the text is not
in the digitised registers, not because a register was overlooked — the last structural
explanation, now closed. Also: **4861 is an `index`, not resolutions** (`resolution_type:
speciaal`, 1626–1661), so it never held resolutions to extract, and the 2,387 the candidate column
attributed to it were attributed to a finding aid.

### The dating problem is a sequence alignment (user, 2026-10-06)

**The text is not missing; the dates drift.** Mean offset (page minus recorded) by quarter of each
annual register, on 822 internally consistent headings: 3185 −1.4/−5.2/−15.3/**−16.6**; 3186
−6.2/−13.5/−17.7/**−19.0**; 3187 −0.1/−0.1/−0.1/**−0.9**; 3188 +1.0/−0.4/−5.7/**−6.8**; 3189
−0.9/−3.0/−5.2/**−7.8**. Recorded dates run *ahead*, the error **accumulates within a volume and
resets at the volume boundary**, severe in 1626–27, near-absent in 1628. Verified on the page:
3185 scans 0243/0245 read 2–3 July 1626 where sessions are recorded 16/19 July; 3188 scans
0619–0621 read 2–6 December 1629 where sessions are recorded 11–20 December. **So 17 July 1626 and
13 December 1629 sit under sessions labelled a fortnight later.**

So: a **monotone alignment** of the XML sitting-day sequence (1,433 of 1,595 days, 162 nihil as
fixed skips) against the HTR session sequence (1,316 in archive order) — not per-session dating.
Constraints, cheapest first, with current violations:

| constraint | violations | cost |
|---|---|---|
| dates run forward with session number | **19** of 1,310 pairs | free |
| no Sunday sittings (prior, afternoon exceptions) | **110** of 1,316 | free |
| `gisteren` forces adjacency | **57** of 495 at ≥3 days | free, own text |
| nihil days consume no session | **9** beyond Sundays (feast days) | XML |
| headings name the date | 1,314 of 1,316 have one | ingested |
| sitting-day count between anchors | pigeonhole | XML |

88.5% of `gisteren` references already sit at 1–2 days, so the sequence is **locally right and
globally misaligned** — a greedy heuristic's signature, repaired by global alignment. It also
explains why `session_offset_eval` found only **3** determined brackets: it anchored on resolved
pins, sparse and themselves drifted, where nihil days and Sundays recur weekly.

#### NEXT STEP: is the alignment determined by counting alone?

Before anyone writes an aligner, measure whether the constraints **force** the mapping. Re-run the
bracket/determinacy analysis (`running_axis.chain.build_brackets` already implements the logic)
with the anchor set swapped: **nihil days and Sundays instead of concordance-resolved pins.**
Between consecutive anchors, count XML sitting days against HTR sessions; where the two agree the
mapping in that span is forced by monotonicity alone.

- **Reason:** `session_offset_eval` found only **3** determined brackets because it anchored on
  resolved pins, which are sparse *and* themselves drifted. Nihil days (162) and Sundays (228)
  recur weekly, so the anchors become an order of magnitude denser. If the spans between them come
  out determined, the drift is correctable by counting and needs no model.
- **Goal:** a count of determined spans and the **resolution mass inside them** — i.e. how much of
  the 3,535 unplaced resolutions a pure counting alignment would recover. That number decides
  whether the next step after it is an aligner or a different approach entirely.
- **Scope guard:** diagnostic only, no placement change, so no `separated`-vs-uniform-null scoring
  is needed yet. Note 1,433 sitting days against 1,316 sessions — a surplus of **117** — so the
  alignment is not a bijection and must permit skips on both sides; a span that does not come out
  determined is a finding, not a failure.
- **Does not block on** the heading rewrite: nihil days and Sundays are free, and headings would
  only add anchor density.

- **Also outstanding, smaller:** finish `h_session_date_vs_heading.py` (commit `45b39f6` is WIP —
  the year/month fabrication bug is still live, so no date figure is citable yet, and the manifest
  description still describes the circular test); none of the 19 non-monotone, 110 Sunday or 9
  feast-day datings is corrected, all being a day-status ledger change nobody has designed; and the
  secret-flag extraction has no committed script (`created_by_script: ""`), so it is not
  reproducible.


### Weekly-walk rule — measured 2026-10-06, large offsets NOT yet explained

**The user's rule, verbatim:** "start at the beginning of a year, check the next sunday (nihil
actum), check the previous and next session texts and align, skip to next sunday as nihil actum,
check.... etc." A weekly walk, anchored on Sundays, aligning within each Sunday-to-Sunday window
and verifying against neighbouring session texts. Its virtue: **drift cannot accumulate past one
week**, which is what defeated every global approach tried so far.

- **Measured.** 224 Sundays in the enriched calendar, 223 windows. Mean 5.87 XML sitting days per
  window against 4.65 HTR sessions — a typical week runs about one session short, not usually a
  bijection. **64 of 223 windows (28.7%) are forced by counting alone** (sitting days == sessions).
  Session counts per window: 6×60, 5×49, 4×40, 3×31, 2×20, 1×7, 7–9×15, one window of 18 (likely
  spans missing Sundays).
- **Verdict: sound, ~10x `session_offset_eval`'s 3 determined brackets**, plus a hard weekly
  reset. The remaining 71% are windows of ≤6 slots holding ~4.65 sessions — small enough for the
  rule's own step 3 (previous/next session text, `gisteren` continuity, already 88.5% locally
  consistent) to finish.
- **Caveat already carried: not every Sunday is nihil actum, especially in wartime** — 88 of 224
  Sundays are NOT XML-marked nihil, so each must be checked, not assumed. The rule's own phrasing
  ("check the next sunday") already requires this.
- **CORRECTION to commit `45b39f6`:** that commit claimed the year-fabrication bug was still
  live; it is fixed, and the large offsets seen were real but **the one checked case supports
  neither account** — `Mercuri den xiijen. Martij. 1636.` on a session recorded 1630-03-13 is
  weekday-consistent under **1630**, not 1636, and should have scored `agrees`, not a 2190-day
  offset. **Do not cite `h_session_date_vs_heading.py`'s current counts (agrees 162, disagrees
  700) until this is resolved.**
- **Free constraint not yet applied: volumes are annual** (3185=1626 … 3189=1630), so a heading
  parsed into another decade is wrong by construction — constrain parse-year to the volume's year
  and emit `unreadable` otherwise, rather than accepting a decade-scale offset as data.

#### NEXT, cheap, before anything else (user, 2026-10-07): widen the anchor set with XML-native nihil days, not a calendar

Two related points from the user, both cheaper than they first look and both already partly done:

- **Not every nihil-actum day is a Sunday.** Easter (2 days), Pentecost (2 days), Christmas (2
  days), and other feast days are also non-sitting — and these are reliably computable from the
  Python standard calendar (`dateutil.easter` + fixed-date feasts), no manuscript reading needed.
- **But check the XML directly first, rather than inferring feast days from a calendar.** The XML
  sitting-day sequence already records nihil actum explicitly as a day-status (chain.py's
  `NIHIL_STATUS` / the 162-day figure already consumed above) — so the question is whether that
  extraction is *already* complete for feast days, not whether to compute them separately. Grep
  the source XML for `nihil` / `nihil actum` literal markers and diff against the computed
  calendar-feast set: where they agree, the calendar add nothing; where the XML has nihil days the
  calendar wouldn't predict (e.g. an ad-hoc fast day) or the calendar predicts days the XML doesn't
  mark (plausible in wartime, matching the already-flagged 88/224 non-nihil-Sunday caveat), that
  gap is itself informative and should be sized before trusting either source alone.
- **Action, in order:** (1) confirm what fraction of XML-marked nihil days the 162-day figure
  already captures vs. the full XML nihil count; (2) compute the feast-day calendar set as a
  cross-check, not a primary source; (3) only then decide whether feast days add meaningful anchor
  density beyond Sundays for the weekly-walk window count above. Diagnostic only — no placement
  change yet.

#### DONE 2026-10-07: the XML audit, and a different free win than expected

`scripts/h_xml_nihil_vs_feast_calendar.py` (dataset `h_xml_nihil_vs_feast_calendar`) scans
`enriched_resolutions_xml_source`'s 1,594 real day files directly (excluding the `NihilActum.xml`
template) for the literal anchored `is_nihil_actum` marker — imported from
`s4_candidate_scoring`, not reimplemented — instead of trusting any of the three nihil counts
already in circulation (162 `candidate_scoring`, 127 `resolution_concordance_1626_1630` status,
125 the `running_axis` addressability bucket).

- **The three prior counts are now reconciled, not contradictory.** 161 of the 1,594 dated files
  are literally nihil in the XML (the 162nd "candidate_scoring" count is an artifact: one enriched
  record has an unset `date` field, grouping under the literal string `"None"`). `resolution_concordance`'s
  127 are a **clean subset** of the 161 — zero concordance-nihil dates are absent from the XML's
  own literal marker, so the production figure, where it fires, is sound.
- **But it only fires 78.9% of the time (127/161) — not because the XML needed a calendar
  cross-check, but because the day-status pipeline skips the nihil check for a specific status
  class.** The 34 XML-literal nihil dates the concordance does *not* mark nihil are not edge
  cases or parsing failures: `s4_day_status_resolution.py`'s own docstring says it — `"T"`/`"E"`
  ledger rows "pass through as `resolved_auto` directly, no scoring needed", so `is_nihil_actum`
  is never consulted for them. All 34 are ledger status `E` ("one direct exact-date HTR session
  candidate"), and the exact-date candidate is not a stub: **680 paragraphs, 354,154 characters
  across all 6 inventories** (3185–3189 and one in 4562), e.g. `1626-01-28`'s XML reads literally
  "Nihil Actum: Bededag." in full, while `session-3185-num-22` (86 paragraphs, 39,691 chars) is
  pinned to that date with status `resolved_auto`. **Not yet explained — hypothesis only, not
  confirmed on the page:** the exact-date match is most likely the known heuristic `session_date`
  field (already shown corpus-wide to disagree with the manuscript 76.6% of the time, 2026-10-06
  entry above) landing a drifted session on a calendar day the normative XML independently says
  was empty — the same drift mechanism this whole track exists to fix, caught here from the nihil
  side rather than the heading side. Sizing only; no correction made.
- **Action 2 (feast-day calendar, cross-check only):** Easter+1/Pentecost+1/Christmas+1 computed
  via `dateutil.easter` (Gregorian, per the user's 2026-10-06 withdrawal of the calendar-style
  hypothesis) over 1626–1630 gives 30 feast dates. 11 already fall on a Sunday, and of the
  remaining 19, all but **11** are already caught by the XML-literal or concordance nihil checks
  above — so **feast days add only 11 new anchor-dates across the entire 5-year corpus** (mostly
  Pentecost Monday and two Christmas dates in 1630), confirming the extraction is largely already
  complete rather than systematically missing feast days.
- **Answer to Action 3: feast days are not worth a separate mechanism.** 11 anchors over 5 years
  is negligible next to 161 nihil dates and 228+ Sundays already in play — cheap to add (the
  dataset already lists the 11 dates) but not a density source worth designing around. The
  34-date `E`/`T`-bypass gap above is the more consequential finding from this same run: it is
  ~3x the size (34 vs 11) and touches substantial HTR mass (680 paragraphs) rather than adding
  anchor dates.
- **Not yet decided:** whether to widen `is_nihil_actum` scoring into the `T`/`E` precedence
  branch of `s4_day_status_resolution.py` (would reduce false pins, but changes production
  output — needs explicit sign-off, same bar as the `axis_for_date` fix).

#### DONE 2026-10-07: confirmed on the page — the 34-date gap is overwhelmingly drift

`scripts/h_nihil_pin_heading_check.py` (dataset `h_nihil_pin_heading_check`) resolves the hedge
above. For each of the 34 sessions, it parses the session's own opening `date`-class heading
(`session_region_text_1626_1630`, already-ingested ES text — no live query) directly: weekday,
day, month, year, by exact lookup (`s6_duplicate_session_date_headings.parse_day_token`, the
same vocabulary and `qui heri` back-reference rule as `h_weekday_date_attribution.py`), checked
non-circularly against the **enriched** date only, never against this corpus's own derived
`session_date`.

| verdict | n | meaning |
|---|---|---|
| `contradicts_pin` | 20 | heading names a different, weekday-consistent date |
| `confirms_pin` | 3 | heading genuinely reads the same date the edition calls Nihil Actum |
| `inconsistent` | 6 | day numeral and weekday disagree (HTR noise) — set aside, not counted |
| `no_signal` | 5 | no readable heading |

**Of the 23 decidable cases, 87% (20/23) contradict the pin** — the exact-date ledger match
pinned a real session to a calendar day the session's own heading does not name. **19 of those
20 are negative offsets** (heading earlier than the pin, −1 to −26 days), the same direction as
the corpus-wide "recorded dates run ahead" drift already measured (2026-10-06 entry above) — not
a new mechanism, the same one caught from the nihil side. The one positive outlier (+245 days,
`session-4562-num-257`) sits in inventory 4562, already documented as order-breaking and
anchor-starved, so a badly wrong exact-date pin there fits its known pathology rather than
suggesting a second mechanism. **Correction (user caught it, 2026-10-07): the 3 `confirms_pin` cases are NOT edition omissions —
checked further, they are a second drift sub-mechanism.** The script only read each session's
*first* date region; pulling every date region for these 3 (`session_region_text_1626_1630`)
shows each one opens with the nihil Sunday heading and is immediately followed by a **Monday**
heading or attendance list one day later — `session-3188-num-119`: "Dominica den vjen. Mey,
1629." then "...**Luna den vije. Meyj; 1629**"; `session-3189-num-13`: "Dominica den xiijen.
Januarij 1630." then a separate region "**14. Januarij.** / 1630"; `session-3189-num-56`: one
heading carrying both, "Dominica den iijen. Martij 1630. **Luna den iiijen. Marty 1630**." All
three Mondays verified (`pd.Period.dayofweek` 0). The paragraph axis confirms the shape: each
session's first paragraph is literally `"Nihil Actum"`, immediately followed by 20/28/12
paragraphs of real resolution content. So the Sunday genuinely is nihil, exactly as the edition
says — the real content belongs to the **following Monday**, and the exact-date ledger match
pinned the whole two-day session to the Sunday because it only keys off the session's first
heading. **This is the same drift family as the other 20, not an independent edition error**:
a day-boundary misattribution (the "sessions as anchors, not containers" pathology already
named elsewhere in this doc, here specifically a nihil-day-glued-to-the-next-day shape). Revises
the 87% figure's framing: all 23 decidable cases point to a boundary/drift mechanism, split
between ordinary date drift (20) and this nihil-glued-to-next-day shape (3), not 20 drift + 3
genuine omissions.

**Updates the open decision above:** widening `is_nihil_actum` into the `T`/`E` precedence
branch is now evidenced, not merely plausible — it would catch roughly the 87%-decidable share
of a 34-date, 680-paragraph population. Still needs explicit sign-off before touching production
(`s4_day_status_resolution.py`), since it changes `resolved_session_id`/`day_status` for live
rows, not just a diagnostic.

### Carrying the heading channel through: from anchor-placement to date correction (2026-10-07)

User direction: use the heading check "not just for placing anchors, but for checking and
shifting wrong dates." Sized first, per the standing measure-before-build discipline. **Nothing
below writes to production; no placement or `day_status` changed.**

#### The instrument is now citable (one bug fixed)

`scripts/h_session_date_vs_heading.py` already implemented the corpus-wide check; its counts were
under a standing "do not cite" because of the `Mercuri den xiijen. Martij. 1636.` case. **Fixed
2026-10-07:** a year token parsed outside its volume's nominal year (3185=1626 … 3189=1630) was
accepted as data, turning OCR digit noise into decade-scale offsets. Such a year is now replaced
with the volume's **nominal** year — never with the recorded date's year, which is bug #1 this
script already rejects, because the nominal year is a structural fact about which physical volume
the page sits in while the recorded date is the label under test. Weekday/day/month are still
checked against it, so a wholly wrong heading still yields `heading_inconsistent`.

The fix moved **9 sessions** (3 to `agrees`, 6 still disagreeing), so **it was not the source of
the large offsets — those are real.** Corpus-wide now: 1,314 sessions with a date region, `agrees`
165, `disagrees` 700, `heading_inconsistent` 11, `unreadable` 438; of 865 decidable, **80.9%
disagree**. Five residual year-scale offsets are **named and set aside, not absorbed**:
`3188-num-234/235` (a consecutive, mutually weekday-consistent 1630 run at the tail of a 1629
volume), `3189-num-154` (a 1631 heading), `4562-num-251/253` (the order-breaking secret series).

#### Shift demand per volume, over the `T`/`E` population

`T` = "one trusted Tier-1 session candidate" (1,012 ledger rows, content evidence from the
entity-overlap alignment); `E` = "one direct exact-date HTR session candidate" (97 rows, the date
label alone). Both are `s4_day_status_resolution.DIRECT_STATUSES` — they "pass through as
`resolved_auto` directly, no scoring needed", which is also why they skipped the nihil check.

| inv | year | T/E rows | decidable | agrees | disagrees | disag % | median \|offset\| | >7 days |
|---|---|---|---|---|---|---|---|---|
| 3185 | 1626 | 182 | 162 | 11 | 151 | 93.2% | 12 | 90 |
| 3186 | 1627 | 198 | 172 | 4 | 168 | 97.7% | 16 | 140 |
| 3187 | 1628 | 269 | 146 | 110 | 36 | **24.7%** | 2 | 1 |
| 3188 | 1629 | 259 | 179 | 1 | 178 | 99.4% | 4 | 29 |
| 3189 | 1630 | 108 | 65 | 32 | 33 | 50.8% | 2 | 0 |
| 4562 | — | 93 | 7 | 6 | 1 | 14.3% | 231 | 1 |

Totals: 731 decidable, **567 disagreeing (77.6%)**, 500 of them negative (heading earlier than
the label), **261 beyond ±7 days** — provably unreachable by the ledger's ±1-day candidate
window, which is what `session_offset_eval` predicted but could only show for 3 sittings.
**This profile independently reproduces the quarter-by-quarter page measurement (2026-10-06)
from a different population by a different route**: 1628 near-clean against 1626–27 severe, with
1629 disagreeing almost universally but at small magnitude and carrying the only substantial
positive offsets (66 of 178), matching its recorded +1.0 first quarter.

#### The three-way comparison, and why `T` is NOT a second witness

**A framing stated earlier in this session was wrong and is retracted here.** `T` was described as
carrying "independent content evidence", making a heading contradiction a conflict between two
witnesses. Measured: for all 731 decidable `T`/`E` rows the enriched date **D** and the axis label
**R** are identical — **100%, by construction.** `E` selects a session *because* its label equals
the enriched date; `T`'s tier-1 anchors can only exist between an enriched date and sessions
*already carrying that same label*, since the alignment is computed within a day. The content
overlap establishes that the resolutions sit in that session; it never had the opportunity to
disagree about *which calendar day*.

Run across all resolved dates (784 with a decidable heading), conditioned on ledger status:

| pattern | dates | share | resolutions |
|---|---|---|---|
| **D==R, heading is the outlier** | 568 | 72.4% | 7,298 |
| all three agree | 159 | 20.3% | 2,008 |
| all three differ | 52 | 6.6% | 822 |
| H==R, enriched D is the outlier | 5 | 0.6% | 69 |
| **H==D, axis label R is the outlier** | **0** | — | — |

**The zero cell is the result.** There is no case where the heading backs the enriched edition
against the axis label, because a pin can only form where D and R already agree (or sit inside the
±1 window). **So the enriched edition cannot act as an independent check on the axis label** —
they are locked together by the pinning mechanism in 727 of 784 cases, and the heading is the only
witness not downstream of the label chain. The 52 "all three differ" dates are 42/52 rows pinned
by candidate *scoring* rather than direct pass-through: the population where everything is in play.

Carry the **selection effect** with any use of these rates: `T`/`E` is *selected* for
label-agreement, so it is the population where drift is least likely to be visible — and 77.6% of
it still has a dissenting heading.

#### Design: feed the heading into the alignment, do NOT build a per-session date-shifter

Two measurements rule out the obvious mechanism.

1. **Shift targets are mostly occupied.** Of 695 disagreeing sessions (the 5 named year-scale cases
   excluded), the heading's date **already has a labelled session in the same volume in 527
   (75.8%)**; only 168 land in an empty slot. And of those 527, **393 occupants also disagree with
   their own heading.** So a per-session shift is not an independent edit — it is a cascade.
2. **No single per-volume shift fits.** Offsets are multimodal: 3185 has modes at −1 (29) *and*
   −16 (17) with spread −40..−1; 3186 modes −18/−16/−20; 3188 mode +1 (41) with −5 (29). A
   constant per-volume or per-quarter correction would be wrong for most sessions in the volume.

Both point the same way, and it is the direction `PLAN.md`'s canonical framing already takes:
**the heading is an observation feeding the monotone sequence alignment, not a correction to apply
per session.** 527 occupied targets with 393 of the occupants themselves displaced *is* a
re-sequencing problem, which is exactly the global alignment the track opened with — and the
heading channel raises its anchor density from "nihil days + Sundays" to "1,314 sessions, 865 of
them with a weekday-verified date statement."

**Where a shift would write, when one is eventually made (answering the open design question):**
a new reviewable dataset, never an in-place edit of `resolution_concordance_1626_1630` or
`session_date_status_1626_1630`. Rationale: the 72.4% figure means a naive apply would rewrite the
dating of 7,298 resolutions on one witness's evidence, against two sources that agree with each
other; and `paragraph_axis_1626_1630`'s date is consumed by essentially every downstream metric,
so an in-place change makes every historical number in `docs/` incomparable without warning. The
dataset carries, per session: current label, heading's stated date, offset, weekday-verification
status, `year_corrected_to_nominal`, whether the target slot is occupied and by what, and the
proposed action — so it is auditable and reversible, and `separated` can be scored with and
without it before anything downstream reads it.

#### Worked example: `session-3185-num-103` (the 72.4% pattern, traced end to end)

The three dates, for a single session, with every claim below checked against the data rather
than inferred:

| | date | source |
|---|---|---|
| **D** | 1626-06-12 | the **enriched edition** files 5 summarised resolutions under this date |
| **R** | 1626-06-12 | **this corpus'** label for the session (`paragraph_axis_1626_1630.date`) |
| **H** | 1626-05-28 | the **manuscript page** itself: `"Jovis den xxviijen. Maij 1626."` -- and 28 May 1626 was a Thursday, so the heading is internally consistent |

**The pin is right -- content confirms it 5 for 5.** Every one of the edition's five summaries for
12 June appears in that session's HTR text: Sackville Crow/Buckingham (`"Opt versouck van
Sackville Crouw dienaer van hertoch van Buckingam"`), the Venetian ambassadors (`"Marco Antonio
Corraro, ende Angelo Contareni"`), Aeltge Willems and Maria Hansses, Jan de Salle, Goswinus
Meurskens. So the resolutions genuinely sit in this session and the disagreement is **only about
which calendar day the session is**. Note what cannot be concluded from D and R agreeing: R is
*why* the pin was made, so it is not a second vote against the page.

**The scans, read by the user on the images 2026-10-07 — and a claim retracted.** This example
first asserted that the session held "a fortnight in one unit" and therefore "needs splitting".
**That was wrong, and it was my inference, not a measurement.** The session's regions sit on scans
0190 and 0192, and these are two-page spreads: on 0190 the attendance list is at x=231 (left page,
y=2585) and the date heading at **x=1464** (right page) — so the layout runs attendance, then the
date on the facing page. On 0192 all three ingested regions are at x=185-275, **left page only**.
The user read the image: the next day's date is there on 0192, right after the attendance list,
and it is **29 May**. So the session is **28 + 29 May 1626, two consecutive days** — the ordinary
multi-day block, not a fortnight-wide unit.

**A missing heading, which is ordinary attrition — not a finding** (user, 2026-10-07: "missing
dates happen"). The 29 May heading is absent from `session_region_text_1626_1630`: 0192's
right-hand page produced no ingested regions, and the ingestion pulled only the `date` and
`attendance` classes (188 letterless regions dropped), so a second-day heading ES classed
otherwise is invisible to us. Expected in this material; recorded here only because the coverage
number is worth having: **98 sessions carry 2+ attendance regions (so 2+ sittings) but fewer than
2 date regions**, 71 of them `disagrees` rows, against 487 where 2+ date regions make the
multi-day structure visible. The practical consequence is a coverage limit, not a defect to chase:
some share of the 438 `unreadable` sessions is un-ingested rather than illegible, and that share
has not been separated.

**What remains genuinely open, stated precisely.** The page dates this session 28-29 May; the
edition dates the resolutions inside it to 12 June. Which is right turns on **how far the
session's text actually extends**, and that is not established: `metadata.page_ids` records only
the scan a resolution *starts* on, and the track already found session extents derived from
resolutions to be systematically too narrow (2026-10-06). If the resolutions stop at 0192 the
edition's date is displaced by ~15 days; if the session's text runs on past 0192 toward 12 June
then the session is genuinely wide after all. **Do not assume either.** Establishing the scan
extent of one session's resolution text is the cheap next check, and it decides between the two.

#### RETRACTION (2026-10-07, user's prompt: "doesnt the entity check give a clue"): the heading disagreement is probably NOT drift

Everything above treats the heading as the one witness independent of the label chain, and its
80.9%/72.4% dissent as the live signal. **A cheap check overturns that reading, and the earlier
framing in this section should not be acted on.**

The content channel *can* be used non-circularly — just not the way the pin uses it. The pin asks
"does this session match the date it is pinned to", with candidates restricted to same-labelled
sessions, which is rigged. Instead ask: **of all dates in a window, which one's enriched summaries
does this session's text actually match?** Nothing restricts that, and the label never enters the
matching (session HTR text vs the 2001 edition's summaries, matched on distinctive proper names,
fuzzy ≥85 to absorb HTR spelling: `Carraro`/`Corraro`).

For the worked example `session-3185-num-103` the profile is unambiguous against a 15-20%
background floor: **12 June 80% (35/44 probes), 13 June 62%, while the page heading's 28 May scores
15% and 29 May 20%.** The content is 12 June business. The heading is the outlier, and the label
is right.

Sampled across disagreeing sessions (|offset| ≥ 5 days, random within 4 volumes, **n=6**):

| session | label R | heading H | offset | content-best | rate |
|---|---|---|---|---|---|
| 3185-num-146 | 1626-09-10 | 1626-08-25 | −16 | 1626-09-12 | 68% |
| 3185-num-121 | 1626-07-23 | 1626-07-08 | −15 | **1626-07-23** | 60% |
| 3186-num-26 | 1627-02-13 | 1627-02-07 | −6 | **1627-02-13** | 60% |
| 3186-num-112 | 1627-06-27 | 1627-06-08 | −19 | 1627-06-28 | 68% |
| 3188-num-173 | 1629-07-25 | 1629-07-20 | −5 | **1629-07-25** | 33% |
| 3188-num-269 | 1629-11-21 | 1629-11-13 | −8 | **1629-11-21** | 67% |

**6 of 6 back the label (4 exactly, 2 within 2 days). 0 of 6 back the heading.** So where a
session's heading dissents by a week or more, the session's own content agrees with its recorded
label — which is also the edition's date, since D==R for this population.

**What that reframes.** The disagreement is most likely in the **page↔session mapping**, not in the
dates: the `date` region attributed to a session frequently is not that session's own heading —
either ES's region→session attribution is off (the dataset's own meta already reports **284
straddling attributions** and 48 out of scope), or scans are offset from sessions by roughly the
same magnitude. Under that reading the per-quarter "page minus recorded" drift means recorded
2026-10-06 may be measuring attribution error rather than calendar drift, and **feeding heading
dates into an aligner would inject noise.** The user's own direct page reads (3185 scans 0243/0245
reading 2-3 July where sessions are recorded 16/19 July) are *consistent* with a scan↔session
offset of the same size, so they do not settle it either way.

**What this does NOT establish**, stated so it is not over-read the way the drift claim was: n=6,
one sampling rule, |offset| ≥ 5 only — it says nothing about the ±1-2 day disagreements, which are
the largest single group (111 of 567 within ±1 day). It does not distinguish ES misattribution from
a scan↔session offset. And a high content rate confirms *which enriched date's business is in a
session*, not which calendar day the clerk sat.

**Cheapest decisive follow-up (not run):** extend this profile corpus-wide over all `disagrees`
sessions and report, per volume, how often content backs the label vs the heading vs neither.
If it backs the label at scale, the heading channel is a page↔session diagnostic, not a dating
channel, and the drift measurements in this track need re-deriving from a source that is not the
attributed heading.

#### Ground truth requested and PREPARED, awaiting page reads (user, 2026-10-07)

The user's own framing: page reads are expensive but are the arbiter — *"you give me your
interpretation for a few dates and the scan, and i'll read it... A spreadsheet with your inference
and links and a field where ik can transcribe the actual date... but keep it strategic... that is
what i meant with more ground truth"*.

`scripts/build_ground_truth_date_sample.py` -> `ground_truth_date_sample` (`explore` phase,
`.xlsx`, 14 rows). Rows are chosen to **discriminate between H-drift and H-attribution**, not to be
representative; each carries the label date, the heading date and HTR's raw reading, the
content-profile best date and rate, my inference, the hypothesis tested, what each hypothesis
predicts, IIIF scan links, and four blank transcription columns. Case classes A-G: the already
part-read worked example; large offsets in 3185/3186; headings naming no label; the ±1-day class;
a **control in clean 3187** (a miss there invalidates the instrument); the user's own
attendance-implies-next-day rule sampled where the second heading is *unreadable*; and a
nihil-pinned Sunday.

**The content profile over these 14 strategically chosen sessions: 10 back the label, 3 land within
±1-2 days of it, 1 has no signal (8%), and 0 back the heading.** The 3187 control correctly backs
its label at 62%, so the instrument reads right where everything already agrees. That is now 20 of
20 sessions across two samples with no case where content backs the heading — but all of it is one
instrument, which is exactly why the page reads are needed before the drift measurements in this
track are re-derived or discarded.

#### RESOLVED 2026-10-08 by human page reads: the regions are misattributed, the labels are broadly right

14 page reads (`ground_truth_date_reads`, annotator rik; workbook `ground_truth_date_sample`)
settle the question the two preceding sections could not, and they settle it against **both** of
my readings.

**The HTR heading date is genuinely written on the page: 13 of 14.** So HTR reads dates well and
the disagreement is not OCR noise. The single miss is `3185-num-112`, where HTR read 16 June for a
page reading **6** June — a stroke added, the documented failure mode. **The recorded label is
written on the page in only 5 of 14**, and those 5 are exactly the small-offset cases.

| verdict | n | what it is |
|---|---|---|
| `only_heading_on_page` | 8 | large offsets (−11 to −40): the label's date is nowhere on that scan |
| `both_dates_on_page` | 5 | the scan carries both — a Sunday `Nihil Actum` then Monday's sitting |
| `neither_on_page` | 1 | `3185-num-112`, the added-stroke misread |

**Two distinct phenomena, which the aggregate 80.9% had been fusing.**

*Small offsets (±1 day)* are benign and fully explained: the scan carries both dates, so the
heading names the nihil Sunday while the label names the working Monday. `3185-num-10` carries
three (11, 12, 13 Jan). Our label collapses a day boundary; it is not a wrong date. This is the
nihil-glued-to-next-day shape found on 2026-10-07, now confirmed on the page.

*Large offsets* are a **region-attribution defect**, confirmed by three independent channels that
split exactly along the region boundary. Using the edition's own person ids (see
`enriched_person_name_variants`, built the same day on the user's note that "the edition also uses
his assigned id"):

| session | resolution text profiles to | attendance region profiles to |
|---|---|---|
| `3185-num-103` | 12–13 June — the **label** (75%/54%) | 28 May — the **heading** (86%) |
| `3186-num-49` | 18 March — the **label**, exactly (47%) | 1–5 March — the **heading's week** (73%/67%) |

So within one session the `date`/`attendance` regions come from one place in the volume and the
resolution text from another about two weeks later. The human read confirms the scan really does
carry the heading's date, and the roster — a different text region, independent of the heading's
own words — agrees with it. **The heading attributed to a session is frequently not that session's
heading.**

**Consequences, stated plainly.**

1. The corpus-wide heading-vs-label disagreement (80.9% / 72.4%) measures **region misattribution**,
   not calendar drift. It must not be cited as a drift rate.
2. The per-quarter "page minus recorded" drift figures recorded 2026-10-06, and the user's
   0243/0245 observation, rest on the same compromised instrument and are **unmeasured again**,
   not disproved. Whether genuine drift also exists is now an open question with no instrument.
3. `session_region_text_1626_1630` carries the defect (its own meta already reports 284 straddling
   attributions); every heading-derived conclusion in this track inherits it.
4. The edition is **faithful** where it could be checked: for `3186-num-2` the user read a date,
   one resolution, then another date, and the edition files exactly 1 resolution under 1 Jan 1627
   and 13 under 2 Jan — an exact structural match, including the `Languerack` three-letters item.
   n=1, but structural rather than loose, and it supports `PLAN.md`'s "the summaries are the
   reference line".
5. Two channels are now available that do not depend on headings at all: **content profiling
   against a date's person ids** and **roster matching against `president_ids`/`deputy_ids`**
   (1,428 dates covered). The roster discriminates only weakly — the deputies are stable
   week-to-week — but it is independent of both the heading and the resolution text.

**The next question is therefore not "which date is right" but "which scans does a session's text
actually come from".** That is a page↔session mapping problem, and it is upstream of every dating
question this track has been asking.

**NEXT (needs the user's go, nothing started):** rather than a shifter, run the heading dates as
observations through the weekly-walk/monotone alignment already specified above, and measure
whether adding them raises the 64/223 forced-window count and how much of the 7,298-resolution
mass lands in a determined span. That is the same gate the counting question already has, with a
denser anchor set.

**Open, and not to be papered over:** which side is right where D==R and the heading dissents. The
2026-10-06 ruling ("the XML calendar is normative, the recorded HTR session date is heuristic")
does not arbitrate here, because for this population the normative and heuristic values are the
same number. The 7 manuscript reads in `manuscript_date_verdicts` are the only true arbiter so far
and they agreed with the page in 1 of 7. Resolving it needs more page reads, not more derivation.

## 2026-10-08 (ruling): the census layer — both coordinates, not the logical one

A bracket census plus anchor-implied split proposals was proposed for **this** track's logical
brackets (`running_axis.chain.build_brackets`), with the scan layer kept complementary. The
discipline in that proposal is adopted and is evidence-backed, not merely prudent: reuse
`s6b_known_point_ledger`'s resolution-start chain and `align_session`'s tier-1 NER co-occurrence
cells rather than opening a third channel; propose a cut **only** where those anchors already imply
one; **abstain** rather than even-split (partial abstention moved gold exact agreement 0.5431 →
0.6486 on 2026-10-01, and the abstained population was 13.9% correct against a 54.3% baseline);
census integrity checked against `session_offset_eval` class counts; census first, proposals second.

**But the census does not sit on this track's brackets alone.** They are built from the session↔date
pins — the inference the 2026-10-08 page reads showed is the broken link — so a census on that layer
cannot see its own defect, because there the inferred label *defines* the bracket. **Ruling (user,
2026-10-08): carry both coordinates**, and make observed-range-vs-inferred-label a first-class
column. On the scan layer, where the date range is observed from two headings on the paper,
`bracket_business_ledger` measures **364 of 593 brackets (61%) holding a session whose own label
falls outside the dates observed on its paper, flat across bracket width (59–67%)**.

Two gates in the proposal need repair before Deliverable 3 runs: the session-split gate ("≥80% of
proposed split paragraphs land on the known second-day boundary") is **not measurable** on the 25
heading-confirmed shared cases, which record *that* a session is shared and not *where* the cut
falls — it needs `lumped_paragraph_boundary_gold`; and the gates omit the standing guard that
`separated` is reported against `uniform_start_paragraphs`, never absolute, with exact agreement
only and no tolerance bands at any granularity.

See `docs/DECISIONS.md` 2026-10-08 (two entries) and `plans/archive/SCAN_SEQUENCE_TRACK.md`'s
`bracket_business_ledger` section.

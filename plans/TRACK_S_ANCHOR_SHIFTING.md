# Track S — "shifting anchors": distribution over sessions

<!-- doc-status: active -->

Part of the **main line** (user, 2026-10-05), paired with
[plans/TRACK_P_SUBPARAGRAPH_DIVISION.md](TRACK_P_SUBPARAGRAPH_DIVISION.md) — P before S, since
several shared-session splits are themselves sub-paragraph. See `PLAN.md`'s canonical goal; this
file is where new Track S steps get added, `PLAN.md` keeps only the headline.

### Track S — "shifting anchors": distribution over sessions

The concordance is rigidly **one date → one session** (all 1,123 dates), while 67 sessions serve 2-3
dates and the archive itself puts two days' business in one session. The container is the problem, not
the matching. The harvest already addresses anchors as `(date, inventory, char_position)` — inventory,
not session — so the address is partly free already.

- **S1 — free diagnostic.** Size the shift demand: for the 25 heading-confirmed shared sessions, how
  many resolutions would attach to a session other than their date's resolved one, and what does that
  do to the measured surplus balance (gold+hard scope: **+186 resolutions with no text vs −186
  resolutions' worth of text with nothing claiming it, net +60**)? That near-mirror is the reason to
  suspect misallocation rather than absence; S1 tests whether the shifts actually absorb it.
- **S2 — schema: many-to-many date↔session with paragraph ranges**, populated first only from the 25
  verified shared sessions plus the 3 secret-flag-arbitrated spurious claims. Monotonicity brackets
  stay hard constraints; fingerprint verification is never an arbiter (it identifies a raw session,
  never which date owns it). Scored on `separated`.
- **S3 — extend to the undecided duplicates** via the entity channel.
  - **2026-10-09:** heading `lesten` fix took 39→36 undecided (3 wired). Entity channel (`s6_duplicate_session_entity_splits`) **NO-GO** against heading gold (filtered within-3 0.67 on n=3). S3 remains open for a stronger instrument, not a weak wire.

**Open design question (user, 2026-10-05): calibrate the anchor scoring instead of adding hard rules.**
Three channels failed the same way in one day — Group C attribution (30.9% vs 47.9% baseline), the
boundary-existence 2x2 (windows with no negatives), and heading attribution (376 fuzzy collisions
turning 0% into an apparent 64%) — each a channel that *detects* something real but is forced into a
hard decision it cannot support. **The pipeline is already probabilistic and merely uncalibrated:**
`align_session` composes additive `position_scores`/`rank_scores` bonuses with hand-set weights
(`semantic_weight=0.5` etc.) chosen by whether they moved `separated`, never fitted against how often
they are right. What calibration would buy: abstention becomes one thresholding mechanism instead of
a bespoke rule per pathology (it would have caught the 224 secret-hijack placements for free); weak
channels compose at measured weight instead of facing wire-or-discard (the locality principle *is*
likelihood multiplication, and B's 9.6% / C's 30.9% are parameters, not just rejection evidence);
and confidence becomes validatable by **calibration rather than adjudication**, which pools across
thousands of rows and so extracts far more from thin gold — a direct answer to the problem that
forced the `separated` ruling. Costs, honestly: it creates no information (a calibrated weight will
correctly give Group C near-zero influence, not resurrect it), it risks false precision, so any
probabilistic version must still be scored on `separated` against the uniform null and ship a
reliability curve. **Cheapest first step:** fit the score components already computed (Group A
overlap, TF-IDF similarity, phrase hits, entity surface matches) as log-likelihood ratios on the
population with known outcomes and publish the reliability curve — it converges with the
explanatory-coverage ledger below, since "explained vs unknown" is itself a confidence statement.
Not scoped; needs the user's go.

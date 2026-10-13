# republic_ner_matching — implementation plan

<!-- doc-status: active -->
<!-- canonical-goal -->

> **Separate the resolutions.** For most of the ~19,120 enriched resolutions (1626-1630 editorial
> summaries), determine where that resolution begins and ends in the HTR transcription, expressed
> in session-relative archival terms — a verified archival address, not a possibly-drifted session
> number. Publish it as a reviewable table where every placement carries a confidence tier and its
> evidence, and where the *unplaced* parts are characterised rather than merely absent.
>
> Framing: patchy alignment, after ancient DNA. Damaged, fragmented aDNA matched against a known
> reference yields patchy alignment — that is the expected shape of a good result, not a failure.
> A confidently placed resolution is an aligned read; several resolutions sharing one paragraph is
> a multi-mapping read (filter, don't count as progress); an unplaced resolution is an uncovered
> region, and uncovered regions are informative — they must be classified, not merely omitted.
>
> **Acceptance criteria** (`docs/DECISIONS.md`): a resolution is **separated** iff its start
> paragraph is shared with no other resolution on its date and its extent is ≤ 3 paragraphs.
> The paragraph-level ceiling is **11,644 / 19,120 = 60.9%** (pigeonhole: 535 days have no HTR),
> not physics. Targets stated against that ceiling, never 100%.
>
> ### Phase 1 — CLOSED (MET, 2026-10-12)
>
> | criterion | baseline (2026-09-29) | status |
> |-----------|----------------------|--------|
> | Global primary: ≥ 50% of ceiling | 8,015 = 68.8% | **MET** |
> | Global stretch: ≥ 75% of ceiling | 9,550 = 82.0% (2026-10-12; was 9,580 before nihil strip) | **MET** (cleared at 8,738 on 3186 Aug–Sep) |
> | Global spans: ≥ 6 spans / ≥ 180 days | 9 spans / 445 days (gap=2, 2026-10-12 post hard-pin) | **MET** (was 4 / 177) |
> | Local: ≥ 50% of inventory ceiling | 3185–3189 all clear | **MET** |
>
> Primary/stretch % against **11,644** are retired as live targets (historical MET only).
>
> ### Phase 2 — theoretical optimum (splitting-conditional)
>
> Optimum depends on whether resolution splitting **re-paragraphs** the axis
> (`docs/DECISIONS.md` 2026-10-13; Track P P0). Report nested horizons; never one collapsed %.
>
> **Recalculated 2026-10-13 (main series 3185–3189 only):** the old ~5,590 “no HTR”
> mass is **retired** — it was displaced / mis-dated HTR (user 2026-10-09), not absent
> text. Concordance `missing_htr` on main series is **0**. Live capacity uses the
> *resolved session’s* paragraph count, not same-calendar-day axis zeros.
>
> | horizon | denominator / unlock | role |
> |---------|----------------------|------|
> | Hard structural | **127** `k_e` nihil_actum only | Splitting-invariant |
> | Session-resolved ceiling | **12,048** of 14,240 main `k_e` | Live Phase-1-style pigeonhole |
> | Theoretical max | **14,113** (= 14,240 − 127) | All non-nihil once re-paragraph can add starts |
> | Phase-2 unlock (pigeonhole) | **2,065** on 387 crowded days | `theoretical_max − session_ceiling` |
> | Collision (diagnostic) | **3,482** placed rows sharing a start | Track P addressable among placed |
> | Historical Phase-1 ceiling | **11,644** (same-day formula; MET targets) | Dual-report only — not live denominator |
>
> Adjudication unchanged: `separated` vs gold when they disagree; every claim vs
> `uniform_start_paragraphs`. Residuals are **classified** (aDNA), not omitted.
> **P0 signed off 2026-10-13**; **no-HTR retirement + ceiling recalc 2026-10-13**.

## Status summary
<!-- doc-status: active -->

**Phase 1 — CLOSED MET (2026-10-12).** Full track narrative archived:
[`docs/archive/PLAN_PHASE1_TRACK_NARRATIVE.md`](docs/archive/PLAN_PHASE1_TRACK_NARRATIVE.md).
Superseded plan files: [`plans/archive/`](plans/archive/). SvZ tasks/metrics:
`uv run python scripts/svz.py archived`.

**Closed (headline only):** S0–S6 segmentation transfer; S4a–e ledger; metrics O/P/D/V;
collision-avoidance / sequence-alignment / scan-sequence / Track S (→ `sequence_graph`);
TF-IDF gated wiring kept; staged-anchor consolidation exhausted; resolution-loss census +
hard-pin remediation through 1628–1630 (separated **9,550** = 82.0% of ceiling); archival
hijack wired; secret series 4562/4861 parked.

**Active tracks (use `svz.py review`):**

1. **`track-p-subparagraph-division`** ([plans/TRACK_P_SUBPARAGRAPH_DIVISION.md](plans/TRACK_P_SUBPARAGRAPH_DIVISION.md))
   — Phase-2 ceiling lever. **P0–P5 PASS**; successor
   `paragraph_axis_p5_predicted_v1` written (376/590 days accepted; 661 cuts;
   18,946→19,607 paras; Δ+1,355 sep on accepted days). Next: dual-ceiling Tier O.

2. **`sequence-graph`** ([plans/SEQUENCE_GRAPH_SPINE.md](plans/SEQUENCE_GRAPH_SPINE.md),
   [docs/SEQUENCE_MODEL.md](docs/SEQUENCE_MODEL.md))
   — Spine + remediation procedure (hard recalibrate → place under lids). Phase-1 acceptance
   cleared via hard-pin place; windowed boundary encoder default `win_512_s256`.
   Deferred mop-up: uncertain `num-150`; bulk `--on-neighbourhood`; early-1626 leftovers;
   `1626-11-04` HTR (`room_lt_ke_abstain`).

**NEXT (Phase 2):** (a) Dual-ceiling Tier O on `paragraph_axis_p5_predicted_v1`;
(b) residual typology under session-resolved horizons (12,048 / 14,113);
(c) early-1626 / `11-04` = optional Phase-1 mop-up.

**Future / parked:**
- Preceding-scan / session-tail boundary channel (deferred hard-case)
- Synthetic boundary encoder eval complete; hardgold continue-train experimental only
- Secret resolutions 4562/4861 — parked; do not reimport via `missing_htr`

## How to navigate
<!-- doc-status: active -->

1. **For work planning:** `uv run python scripts/svz.py review` shows active tracks and metrics
2. **For decisions:** See [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/ITERATION_POLICY.md](docs/ITERATION_POLICY.md)
3. **For the method:** [docs/SEGMENTATION_TRANSFER.md](docs/SEGMENTATION_TRANSFER.md) frames the problem
4. **For results:** [docs/SEGMENTATION_RESULTS.md](docs/SEGMENTATION_RESULTS.md) summarizes findings
5. **For active track details:** `plans/TRACK_P_SUBPARAGRAPH_DIVISION.md`, `plans/SEQUENCE_GRAPH_SPINE.md`
6. **Phase-1 history:** [`docs/archive/PLAN_PHASE1_TRACK_NARRATIVE.md`](docs/archive/PLAN_PHASE1_TRACK_NARRATIVE.md), [`plans/archive/`](plans/archive/), `svz.py archived`

# Remediation track gold (stages 1–6)
<!-- doc-status: active -->

**One step per session.** Doctrine: [`docs/SEQUENCE_MODEL.md`](../SEQUENCE_MODEL.md).

## Track

| Stage | Name | Edge focus |
|-------|------|------------|
| 1 | Gap | Unsynced brackets (`sequence_graph_sync_gaps`) |
| 2 | Rearrange | Drop contested production `PINNED_TO` lids |
| 3 | Diagnostic | Where the break starts (lag window) |
| 4 | Recalibration | Hard map a→b→c (`hard_recalibrate_proof`) |
| 5 | Re-alignment | Date-free `ALIGNED_TO` identity |
| 6 | Split | Multi-claim flat → segment inventory |
| 7 | Pin promote | Production `PINNED_TO` + concordance session id |
| 8 | Place under lids | Pack paragraphs on pinned session stream |
| 9 | Wire backbone | Concordance spans + `ALIGNED_TO:hard_place` (gate: `separated`↑) |

**Imperfect closure is OK.** Residuals must say where holes remain and how big.

**Complicated gaps** (several alignments wrong *and* date placement): type failures by edge; do not joint-fix. Dating = stages 2–4; content/slot = 5; overflow = 6. Many residual kinds at once is expected.

## Bake

```bash
# Seed window (3185, 1626-09-21..10-25)
uv run python -m sequence_graph.bake_remediation_track_gold --write

# Next similar gap (example)
uv run python -m sequence_graph.bake_remediation_track_gold \
  --window-id next_1626-08-13_19 \
  --calendar-lo 1626-08-13 --calendar-hi 1626-08-19 \
  --merge --write
```

Dataset: `remediation_track_gold`. Overflow-only slice remains `aligned_to_overflow_track_gold` (stages 5–6).

Neighbourhood hand labels: [`STEP_NEIGHBOURHOOD_SESSION_SHIFT.md`](STEP_NEIGHBOURHOOD_SESSION_SHIFT.md) (stages 5–6 only).

## Stage 6 apply — DONE 2026-10-12 (PASS, imperfect)

```bash
uv run python -m sequence_graph.overflow_align_apply --write
```

Fingerprint-gated multi-claim flats → encoder/even cut expand → `align_bracket` (entity+fingerprint) on hard-window content sessions. Dataset `overflow_align_apply`.

| Result | n |
|--------|---|
| `clean_split` (2-claimant, 1:1 MATCH) | 2 |
| `needs_human_cuts` (4–5 claimants) | 2 |
| Lumped baseline deletions (unexpanded) | 9 |

Cuts stay `is_gold: false`. No production wire.

## After this step

**Human cut approve DONE:** both flats `approve` / `is_gold: true` in `overflow_cut_reviews`.

| Flat | `gold_offsets` | Note |
|------|----------------|------|
| `num-150-resolution-5` | `[1257, 3263, 3397]` | uncertain (3 cuts / 5 claimants) |
| `num-151-resolution-2` | `[1241, 1702, 2367]` | clean |

**DONE 7c:** `uv run python -m sequence_graph.overflow_cut_promote --write` → `overflow_cut_gold`. Machine `aligned_to_overflow_track_gold` cut_proposal rows unchanged.

**DONE Step 8:** `uv run python -m sequence_graph.overflow_align_wire --write --push-graph` → `overflow_align_wire` + `ALIGNED_TO:overflow` on saved graph (8 edges: 4 clean-split + 4 `num-151` cut gold; `num-150` uncertain skipped). Still not a pin rewrite.

## Restored-seed apply (2026-10-12)

After Aug widen left a thin hard map (`hard_active=1`, `num-148` skipped), seed Sep–Oct was restored (`hard_active=17`). Re-run:

```bash
uv run python -m sequence_graph.overflow_align_apply --write
```

**PASS:** `in_window=4`; `num-148-resolution-4` / `-7` → `clean_split`; `num-150` / `num-151` → `needs_human_cuts` (unchanged; do not re-cut). Graph already has 8 `ALIGNED_TO:overflow`.

## Gated hard pin repin — DONE 2026-10-12

```bash
uv run python -m sequence_graph.hard_pin_repin --write --push-graph
```

**PASS:** 17 `PINNED_TO:hard` edges (15 shift + 2 new_pin), monotone. Separated guard (placements unchanged): before 142 vs uniform 174. Dataset `hard_pin_repin`. Production `PINNED_TO` key and concordance **not** rewritten.

## Out of scope

Uncertain cut gold without count agreement; re-running heavy parents inside the bake. Bulk `--on-neighbourhood` until seed pin promote settles.

## Doctrine update (2026-10-12)

Inherit sitting date from `ALIGNED_TO`∘session∘hard (`OBSERVED_ON∘DATED_AS`); production pin promote gates on hard + monotone — **not** on content re-align. See `docs/DECISIONS.md`.

## Production pin promote — DONE 2026-10-12 (wired)

```bash
uv run python -m sequence_graph.hard_pin_promote --write --wire --push-graph
# → 17 dates / +17 −15 production PINNED_TO; Δ sep 0
uv run python -m sequence_graph.persist --snapshot after_hard_pin_promote
```

Compare: `seed_overflow_wire` (old pins) vs `after_hard_pin_promote` / live.

## Stages 8–9 place under lids — seed

```bash
uv run python -m sequence_graph.hard_pin_place --write
# Gate PASS → wire concordance + ALIGNED_TO:hard_place
uv run python -m sequence_graph.hard_pin_place --write --wire --push-graph
```

Dataset: `hard_pin_placement_lift`. Stage 7 alone is not track-done; every window runs through stage 9. Uncertain `num-150` / bulk `--on-neighbourhood` still deferred.

## Nov window `1626-11-03..11-12` — DONE through stage 9 gate (2026-10-12)

```bash
uv run python -m sequence_graph.hard_recalibrate \
  --inventory 3185 --calendar-lo 1626-11-03 --calendar-hi 1626-11-12 \
  --write --compare-notes
# → hard_active=6, shifts=6, literal=6/6

uv run python -m sequence_graph.bake_remediation_track_gold \
  --window-id next_1626-11-03_12 \
  --calendar-lo 1626-11-03 --calendar-hi 1626-11-12 \
  --merge --write
# → stages_present=4/6 (5–6 empty); gate PASS imperfect

uv run python -m sequence_graph.hard_pin_repin \
  --inventory 3185 --calendar-lo 1626-11-03 --calendar-hi 1626-11-12 \
  --write --push-graph
# → 6 PINNED_TO:hard (scoped push keeps seed edges)

uv run python -m sequence_graph.hard_pin_promote \
  --inventory 3185 --calendar-lo 1626-11-03 --calendar-hi 1626-11-12 \
  --write --wire --push-graph
# → PASS, 6 dates, Δ sep 0, corpus 8526

uv run python -m sequence_graph.hard_pin_place --write
# first run FAIL 48→47 — heading-only room on 11-04
# fix: scan-span room + abstain room<k_e → PASS 48→59 (Δ+11)
uv run python -m sequence_graph.hard_pin_place --write --wire --push-graph
# → 5 dates placed / 56 ALIGNED_TO:hard_place; 11-04 room_lt_ke_abstain
#    span 449..456, scans_without_session=[450..455] (HTR missing)
```

Graph push for `:hard` / `:hard_place` is **date-scoped** (other windows retained). Sitting room = `DATED_AS` heading scan through scan before next `DATED_AS` (no invented headings on continuation pages).

## Years 1628–1630 — DONE through stage 9 (2026-10-12)

Severe `|Δ|≥7` lag is gone after 1626–27; later years used hard-map `production_disagrees` (and mild `|Δ|≥4` on 1629). Queue:

```bash
./scripts/run_remediation_window.sh 3187 1628-10-20 1628-11-14 next_1628-10-20_11-14
./scripts/run_remediation_window.sh 3187 1628-11-17 1628-12-28 next_1628-11-17_12-28
./scripts/run_remediation_window.sh 3188 1629-01-04 1629-03-31 next_1629-01-04_03-31
./scripts/run_remediation_window.sh 3188 1629-04-01 1629-07-08 next_1629-04-01_07-08
./scripts/run_remediation_window.sh 3188 1629-07-10 1629-09-01 next_1629-07-10_09-01
./scripts/run_remediation_window.sh 3188 1629-09-07 1629-11-13 next_1629-09-07_11-13
./scripts/run_remediation_window.sh 3188 1629-11-20 1629-12-14 next_1629-11-20_12-14
./scripts/run_remediation_window.sh 3189 1630-03-15 1630-05-01 next_1630-03-15_05-01
```

| Window | place Δ corpus |
|--------|----------------|
| 1628-10-20..11-14 | +27 |
| 1628-11-17..12-28 | +47 |
| 1629-01-04..03-31 | +110 |
| 1629-04-01..07-08 | +196 |
| 1629-07-10..09-01 | +110 |
| 1629-09-07..11-13 | +59 |
| 1629-11-20..12-14 | +49 |
| 1630-03-15..05-01 | +82 |
| **Total** | **+680 → 9580 (82.3% ceiling)** |

**Skipped then closed (2026-10-13):** hard map said `1628-11-15`→num-267 / `1628-11-16`→num-266 (monotone fail). Hand resolve: **keep production** (`15→266`, `16→267`). Hard dates were bootstrap artefacts (scan 676 `"16. ee d t…"`); content+size match production. Do not promote. See `docs/DECISIONS.md` 2026-10-13.

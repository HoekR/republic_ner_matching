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

## After this step

**Correct session overflow with the new align machinery** — fingerprint-gated multi-claim flats → `align_bracket` / `INSERTION_SPLIT` on hard lids; human-checked cuts. Dating stays stages 2–4; this is stage 6 apply, not a pin rewrite.

## Out of scope (until overflow-correct step)

Production `PINNED_TO` / `ALIGNED_TO` wire; promoting cut offsets to gold; re-running heavy parents inside the bake.

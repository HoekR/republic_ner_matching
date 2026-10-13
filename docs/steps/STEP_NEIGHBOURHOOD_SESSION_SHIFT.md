# Neighbourhood identity + overflow/split (ALIGNED_TO stages 5–6)
<!-- doc-status: active -->

**One step per session.** Full track (1–6 + residuals): [`STEP_REMEDIATION_TRACK_GOLD.md`](STEP_REMEDIATION_TRACK_GOLD.md). Doctrine: [`docs/SEQUENCE_MODEL.md`](../SEQUENCE_MODEL.md).

## Doctrine

- Dating lids (`PINNED_TO` / hard map) ≠ content (`ALIGNED_TO` / fingerprint).
- Concordance is date-signed → lag (right text, often wrong date). Fingerprint proves **identity**, never ownership.
- **Split signal:** several XML summaries fingerprint to the **same** HTR flat ⇒ that flat should be split.
- Fingerprint **detects**; GloBERTise (or half-windows) **places** cuts. Content never writes `PINNED_TO`.
- This guide is **stages 5–6 only**. Full remediation gold: `remediation_track_gold`.

## Pipeline

| Step | Status | Command / action |
|------|--------|------------------|
| 1 Scaffold identity gold | DONE | `--scaffold-neighbourhood-gold --write` |
| 2 Hand label | DONE | `uv run neighbourhood-shift-gold-ui` (http://127.0.0.1:5057) |
| 3 Identity gate | DONE PASS | `--on-neighbourhood-gold --write` |
| 4 Overflow/split proof | DONE PASS | `--on-overflow-split --write` → `fingerprint_overflow_split_proof` |
| 5 Overflow slice bake | DONE | `--bake-track-gold --write` → `aligned_to_overflow_track_gold` |
| 6 Full track gold | DONE | `bake_remediation_track_gold --write` → `remediation_track_gold` |
| 6b Overflow align apply | DONE PASS | `overflow_align_apply --write` → `overflow_align_apply` (2 clean / 2 needs_human) |
| 7 Human cut/treatment review | DONE | UI + revised offsets in `overflow_cut_reviews` |
| 7b Confirm approve/skip | DONE | Both `approve` / `is_gold: true` (`num-150` uncertain: 3 cuts vs 5 claimants) |
| 7c Promote cut gold | DONE | `overflow_cut_promote --write` → `overflow_cut_gold` (`cut_proposal` `is_gold: true`) |
| 8 Production wire | DONE | `overflow_align_wire --write --push-graph` → `ALIGNED_TO:overflow` (8 edges; uncertain skipped) |
| 9 Gated hard pin | DONE | `hard_pin_repin --write --push-graph` → 17 `PINNED_TO:hard` (no production key) |

Bulk `--on-neighbourhood` (S vs S+Δ) is parked relative to overflow/split. `--on-lag` remains diagnostic only. **After 9 (doctrine 2026-10-12):** production pin promote from hard is **not** gated on content re-align; content path inherits date via `ALIGNED_TO`∘hard. See `docs/DECISIONS.md`.

## Label statuses (identity)

| Status | Meaning |
|--------|---------|
| `found` | Text belongs in `correct_session` |
| `found_needs_split` | Session OK; HTR lumped (note often says split) |
| `not_found` | Absent in neighbourhood |

## Track gold (Step 5)

| Record | Role | Gold? |
|--------|------|-------|
| `as_is` | volgnr → fingerprint top-1 flat (may be lumped) | yes |
| `flat_as_is` | multi-claim flat + claimant list | yes |
| `proposed_end` | ordered segments (`segment_rank`, `prefer_half`) | yes |
| `cut_proposal` | encoder / even char offsets | **no** (`is_gold: false`) |

Segment order: HALF_A before HALF_B before WHOLE, then volgnr. No char cuts as truth.

## Out of scope until Step 5 PASS + Step 6

Corpus-wide detect; fit Stage 4 `split_discount`; concordance / graph `ALIGNED_TO` write; preceding-scan channel.

## Step 7 — cut review UI

```bash
uv run overflow-cut-review-ui
# http://127.0.0.1:5058
```

Two `needs_human_cuts` flats (4–5 claimants). Machine cuts pre-seeded as `|||CUT|||`. Verdicts: `approve` (promote-ready `gold_offsets` / `is_gold`) · `defer` · `skip`. Persists to `overflow_cut_reviews`. Promote: `uv run python -m sequence_graph.overflow_cut_promote --write` → `overflow_cut_gold`. No production wire.

## Manifest datasets

| Logical name | Role |
|--------------|------|
| `neighbourhood_shift_gold` | Hand identity labels |
| `fingerprint_session_shift_neighbourhood_gold` | Identity apply gate |
| `fingerprint_overflow_split_proof` | Multi-claim flats + cut proposals |
| `aligned_to_overflow_track_gold` | Full-track as-is → proposed_end gold |
| `overflow_align_apply` | Stage 6 align_bracket apply on hard-window overflow flats |
| `overflow_cut_reviews` | Human approve/defer/skip + gold_offsets on needs_human_cuts |
| `overflow_cut_gold` | Promoted approve cuts (`cut_proposal` `is_gold: true`) |
| `overflow_align_wire` | Scoped `ALIGNED_TO:overflow` plan (+ optional graph push) |
| `fingerprint_session_shift_gold` | Synthetic instrument gate |
| `fingerprint_session_shift_lag` | Date-join diagnostic only |

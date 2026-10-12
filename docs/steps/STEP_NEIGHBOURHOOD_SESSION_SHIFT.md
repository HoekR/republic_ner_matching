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
| 6 Full track gold | see STEP_REMEDIATION | `bake_remediation_track_gold --write` |
| 7 Human cut/treatment review | deferred | Against track gold; promote `cut_proposal` only after approve |
| 8 Production wire | deferred | Only after Step 7; scoped inventory/window |

Bulk `--on-neighbourhood` (S vs S+Δ) is parked relative to overflow/split. `--on-lag` remains diagnostic only.

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

Corpus-wide detect; fit Stage 4 `split_discount`; concordance / graph `ALIGNED_TO` write; preceding-scan channel; overflow review UI (parked).

## Manifest datasets

| Logical name | Role |
|--------------|------|
| `neighbourhood_shift_gold` | Hand identity labels |
| `fingerprint_session_shift_neighbourhood_gold` | Identity apply gate |
| `fingerprint_overflow_split_proof` | Multi-claim flats + cut proposals |
| `aligned_to_overflow_track_gold` | Full-track as-is → proposed_end gold |
| `fingerprint_session_shift_gold` | Synthetic instrument gate |
| `fingerprint_session_shift_lag` | Date-join diagnostic only |

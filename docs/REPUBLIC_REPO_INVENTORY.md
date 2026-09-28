# Republic repos on `~/develop` — inventory, actuality, and cleanup

*Updated 2026-09-28. Canonical pull fork: **`republicgit`**. No pushes to `HuygensING/republic-project`.*

## Actuality scale

| Label | Meaning |
|-------|---------|
| **Current** | Active research; open work in last ~3 months |
| **Maintained** | Still the right place for that role; quiet but not superseded |
| **Stale** | Useful history; do not extend — archive or thin-keep |
| **Superseded** | Replaced by another repo |
| **Deleted** | Removed from `develop` (and/or hard-deleted) |

---

## Master table

| Dir | Size (was) | Role | Actuality | Disposition |
|-----|------------|------|-----------|-------------|
| **`republicgit`** | 2.8G | Local pull fork of `HuygensING/republic-project` | **Current** (upstream sync) | **CANONICAL** — only clone to `git pull` |
| `republic_ner_matching` | ~32G | NER / HOE / alignment app | **Current** | Keep; shrink `data.bak`+`output` per [NER_DATA_PURGE.md](NER_DATA_PURGE.md) |
| `gnb_analysis` | 465M | RPP 1610–1630 + 18th c. | **Current** | Keep separate; remote `HoekR/gnb_analysis` (push deferred) |
| `streamlit_worksheet` | 669M | Delegate QA UI | **Current** | Keep (`HoekR/delegate-qa`) |
| `republic_resolutions_early` | 271M | Pre-1626 segmentation | **Current** | Keep separate; remote created, push deferred |
| `republic_attendance_1630` | 207M | 1630–1704 attendance | **Current** | Keep separate (implements gnb plan); push deferred |
| `republic_delegates_data` | 1.8G | Perioded delegate releases | **Maintained** | Data product — warm-tier + manifests, not an app |
| `republic_delegates` | 108K | Tiny GNB helpers | **Stale** | Merge into `gnb_analysis` when convenient |
| `republic_corpus` | 132K | Thin warm-tier access package | **Maintained** | Keep / publish when attendance needs it |
| `huygens_name_index` | 1.6G | Name-index platform | **Current** | Keep |
| `hist-text-utils` | 353M | General historical text utils | **Maintained** | Keep general; trim weight later |
| `historic-matcher` | 19M | W2V + FAISS matcher | **Maintained** (messy) | Keep; tidy when next touched |
| `fuzzysearch` | 27M | OCR fuzzy search (upstream) | **Maintained** | Keep shallow |
| `pagexml` | 4.5M | PageXML tools (upstream) | **Maintained** | Keep |
| `notebook-archive` | ~5G after import | Older notebooks home | **Current** (archive role) | Received `republic_clean` salvage |
| `republic_latest` | 1.3G | Duplicate upstream clone | **Deleted** | Redundant vs `republicgit` |
| `republic_clean` | 6.4G | Dirty 2022 clone | **Deleted** | Unique notebooks → `notebook-archive` |
| `republic-clean` | 207M | Older hyphen twin | **Superseded** | In scratch archive |
| `republic-project` | 43M | Stuck 2021 merge branch | **Superseded** | In scratch archive |
| `namenindex` | 524M | Legacy name-index sources | **Superseded** | Archive (GitHub remains) |
| `namenindexserver` / `client` / `_old` | ~69M | Old Flask/client stack | **Deleted** | Hard-deleted from archive |
| `republic-hocr-parser` | 7.2M | 2020 hOCR parser | **Stale** | Scratch archive |
| `resolutions_states_general` | 5.3M | 2018 RSG precursor | **Stale** | Scratch archive |
| `gnbartikel` | 112M | 2017–19 RSG scrap | **Stale** | Scratch archive |
| `gnb_models` | 547M | One notebook + `.venv` | **Stale** | Archive; notebook extracted |

**Not Republic:** `trifecta-annotation`, food/recipe repos — separate track.

---

## What was done (2026-09-28)

1. **Canonical:** `republicgit` marked (`CANONICAL_UPSTREAM.md`); pull-only from HuygensING.
2. **Salvage:** unique `republic_clean` notebooks → [`notebook-archive/notebooks/republic/`](file:///Users/rikhoekstra/develop/notebook-archive/notebooks/republic/README.md); bulk sidecar → `notebook-archive/output/republic_clean_sidecar/` (gitignored).
3. **Deleted from develop:** `republic_clean`, `republic_latest` (~7.7G).
4. **Hard-deleted:** `namenindexserver`, `namenindexclient`, `namenindexserver_old`.
5. **Earlier archive move:** other legacy trees → `/Volumes/Extreme SSD/scratch/_archive/republic_legacy_20260928/`.

## Still open (accepted cleanup order)

- NER purge: `data.bak` (~11G) + relocate `output` models (~18G) — see [NER_DATA_PURGE.md](NER_DATA_PURGE.md)
- Optional: push personal `HoekR/gnb_analysis` etc. when you ask (never HuygensING)
- Optional: tidy `historic-matcher`; merge `republic_delegates` helpers into `gnb_analysis`

# S6b — constraint baseline: known points and counted gaps

Window **1626-01-01 → 1630-12-31**, generated from the registered `s6b_known_point_ledger` dataset by [scripts/s6b_constraint_baseline_report.py](../scripts/s6b_constraint_baseline_report.py).

## What this measures

This is a baseline of the **problem**, not of a model — nothing here predicts anything.
Along each day's character stream the ledger chains every *known* point:

```
[session start] … [known resolution i] —gap: N resolutions must fall here— [known resolution j] … [session end]
```

Because `K_e` (the enriched resolution count per day) is normative and hand-checked, every
interval between two consecutive known points carries a count that **must** be satisfied.
A gap holding 0 unplaced resolutions is already determined; one holding 1–2 is nearly
determined by its endpoints plus counting; larger gaps are where the real work is.

Known points are kept **typed** rather than merged, so the ledger shows which kind of
knowledge does the pinning: session start/end sentinels, tier-1 entity anchors, and
hand-annotated gold boundaries.

## Headline

- **1059** days carry an HTR paragraph axis; **535** have enriched
  resolutions but no axis at all — the accepted `missing_htr` ceiling.
- **13530** resolutions, of which **5111** are pinned by a known point
  (**37.8%**): 350 gold_boundary, 4761 tier1_anchor.
- **7504** resolutions remain unplaced across **6026** gaps.

| bucket | gaps | unplaced resolutions | share of unplaced | characters |
| --- | ---: | ---: | ---: | ---: |
| determined (0) | 3400 | 0 | 0.0% | 4,746,176 |
| nearly determined (1–2) | 1679 | 2202 | 29.3% | 3,378,337 |
| **open (>2)** | **947** | **5302** | **70.7%** | 3,132,619 |

### Read both shares, never one

Counting **gaps**, 84.3% are determined or nearly so — which sounds excellent.
Counting **resolutions**, 70.7% of the unplaced work sits in the 947 open gaps.
Both are true. A gap of size 0 contributes a row to the distribution but zero work, so
gap-count shares are dominated by already-solved intervals.
[`SEGMENTATION_TRANSFER.md` §7](SEGMENTATION_TRANSFER.md) argues from roughly the gap-count view that
"the residual problem is small and locally constrained"; that holds by gap count and fails by
resolution count (see [DECISIONS.md](DECISIONS.md), 2026-09-20). The longest gap runs **25** resolutions.

## By month

Monthly **counts** are solid and show exactly where the corpus goes dark. Monthly **ratios**
rest on thin cells, so check the year and inventory rollups below before reading a trend into
month-to-month movement.

| month | days | no axis | resolutions | pinned | pinned % | det. | nearly | open | unplaced | in open | open % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1626-01 | 20 | 11 | 223 | 82 | 36.8% | 53 | 30 | 16 | 124 | 84 | 67.7% |
| 1626-02 | 15 | 13 | 164 | 78 | 47.6% | 57 | 20 | 11 | 76 | 48 | 63.2% |
| 1626-03 | 19 | 12 | 196 | 57 | 29.1% | 31 | 30 | 15 | 120 | 85 | 70.8% |
| 1626-04 | 21 | 9 | 230 | 97 | 42.2% | 63 | 30 | 15 | 122 | 83 | 68.0% |
| 1626-05 | 20 | 11 | 256 | 60 | 23.4% | 36 | 22 | 22 | 176 | 148 | 84.1% |
| 1626-06 | 11 | 19 | 149 | 33 | 22.1% | 23 | 7 | 14 | 105 | 96 | 91.4% |
| 1626-07 | 16 | 15 | 207 | 85 | 41.1% | 60 | 21 | 18 | 108 | 79 | 73.1% |
| 1626-08 | 14 | 17 | 211 | 78 | 37.0% | 47 | 30 | 15 | 119 | 81 | 68.1% |
| 1626-09 | 14 | 16 | 144 | 49 | 34.0% | 31 | 22 | 10 | 81 | 53 | 65.4% |
| 1626-10 | 15 | 16 | 183 | 75 | 41.0% | 46 | 28 | 10 | 99 | 60 | 60.6% |
| 1626-11 | 14 | 16 | 163 | 73 | 44.8% | 57 | 14 | 11 | 81 | 60 | 74.1% |
| 1626-12 | 17 | 14 | 190 | 61 | 32.1% | 43 | 24 | 11 | 112 | 80 | 71.4% |
| 1627-01 | 18 | 13 | 202 | 49 | 24.3% | 28 | 21 | 18 | 135 | 106 | 78.5% |
| 1627-02 | 17 | 11 | 207 | 77 | 37.2% | 52 | 27 | 15 | 113 | 79 | 69.9% |
| 1627-03 | 15 | 16 | 183 | 60 | 32.8% | 37 | 25 | 13 | 108 | 75 | 69.4% |
| 1627-04 | 20 | 10 | 266 | 110 | 41.4% | 68 | 42 | 20 | 136 | 82 | 60.3% |
| 1627-05 | 19 | 12 | 203 | 63 | 31.0% | 40 | 29 | 13 | 121 | 83 | 68.6% |
| 1627-06 | 15 | 15 | 155 | 39 | 25.2% | 18 | 25 | 11 | 101 | 69 | 68.3% |
| 1627-07 | 17 | 14 | 228 | 48 | 21.1% | 29 | 19 | 17 | 163 | 139 | 85.3% |
| 1627-08 | 20 | 11 | 242 | 90 | 37.2% | 60 | 30 | 16 | 136 | 98 | 72.1% |
| 1627-09 | 21 | 8 | 259 | 95 | 36.7% | 68 | 25 | 18 | 148 | 116 | 78.4% |
| 1627-10 | 19 | 12 | 222 | 67 | 30.2% | 52 | 14 | 17 | 139 | 117 | 84.2% |
| 1627-11 | 19 | 11 | 221 | 89 | 40.3% | 62 | 30 | 16 | 113 | 76 | 67.3% |
| 1627-12 | 16 | 15 | 207 | 110 | 53.1% | 80 | 32 | 10 | 85 | 45 | 52.9% |
| 1628-01 | 26 | 5 | 290 | 133 | 45.9% | 91 | 45 | 18 | 136 | 79 | 58.1% |
| 1628-02 | 26 | 3 | 290 | 115 | 39.7% | 87 | 29 | 25 | 149 | 114 | 76.5% |
| 1628-03 | 26 | 5 | 287 | 119 | 41.5% | 83 | 44 | 18 | 142 | 81 | 57.0% |
| 1628-04 | 22 | 8 | 226 | 95 | 42.0% | 64 | 41 | 10 | 111 | 57 | 51.4% |
| 1628-05 | 23 | 8 | 290 | 92 | 31.7% | 54 | 36 | 25 | 175 | 129 | 73.7% |
| 1628-06 | 18 | 12 | 231 | 84 | 36.4% | 53 | 30 | 19 | 129 | 92 | 71.3% |
| 1628-07 | 23 | 8 | 343 | 140 | 40.8% | 91 | 45 | 21 | 186 | 126 | 67.7% |
| 1628-08 | 23 | 8 | 270 | 95 | 35.2% | 64 | 37 | 17 | 152 | 97 | 63.8% |
| 1628-09 | 27 | 3 | 364 | 149 | 40.9% | 93 | 51 | 26 | 194 | 130 | 67.0% |
| 1628-10 | 15 | 16 | 230 | 100 | 43.5% | 66 | 31 | 14 | 119 | 76 | 63.9% |
| 1628-11 | 23 | 7 | 280 | 129 | 46.1% | 84 | 43 | 18 | 135 | 77 | 57.0% |
| 1628-12 | 22 | 9 | 301 | 139 | 46.2% | 104 | 28 | 20 | 149 | 111 | 74.5% |
| 1629-01 | 28 | 3 | 335 | 97 | 29.0% | 69 | 27 | 29 | 210 | 173 | 82.4% |
| 1629-02 | 21 | 7 | 238 | 90 | 37.8% | 67 | 28 | 16 | 127 | 89 | 70.1% |
| 1629-03 | 28 | 3 | 340 | 153 | 45.0% | 108 | 50 | 21 | 161 | 96 | 59.6% |
| 1629-04 | 22 | 8 | 309 | 143 | 46.3% | 95 | 35 | 20 | 159 | 112 | 70.4% |
| 1629-05 | 25 | 6 | 301 | 96 | 31.9% | 65 | 33 | 23 | 180 | 139 | 77.2% |
| 1629-06 | 19 | 11 | 235 | 70 | 29.8% | 45 | 28 | 16 | 146 | 113 | 77.4% |
| 1629-07 | 19 | 12 | 280 | 108 | 38.6% | 61 | 41 | 21 | 157 | 99 | 63.1% |
| 1629-08 | 23 | 8 | 433 | 164 | 37.9% | 116 | 40 | 31 | 246 | 192 | 78.0% |
| 1629-09 | 20 | 10 | 214 | 75 | 35.0% | 52 | 28 | 15 | 119 | 84 | 70.6% |
| 1629-10 | 25 | 6 | 388 | 134 | 34.5% | 93 | 34 | 29 | 232 | 183 | 78.9% |
| 1629-11 | 21 | 9 | 321 | 108 | 33.6% | 65 | 42 | 22 | 192 | 133 | 69.3% |
| 1629-12 | 14 | 17 | 208 | 73 | 35.1% | 48 | 23 | 15 | 122 | 91 | 74.6% |
| 1630-01 | 27 | 4 | 359 | 151 | 42.1% | 100 | 48 | 24 | 187 | 127 | 67.9% |
| 1630-02 | 23 | 5 | 371 | 159 | 42.9% | 99 | 44 | 24 | 204 | 152 | 74.5% |
| 1630-03 | 24 | 7 | 365 | 176 | 48.2% | 115 | 56 | 21 | 173 | 101 | 58.4% |
| 1630-04 | 24 | 6 | 389 | 163 | 41.9% | 105 | 51 | 27 | 206 | 139 | 67.5% |
| 1630-05 | 10 | 4 | 131 | 36 | 27.5% | 22 | 14 | 10 | 85 | 68 | 80.0% |

## By year

| year | days | no axis | resolutions | pinned | pinned % | det. | nearly | open | unplaced | in open | open % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1626 | 196 | 169 | 2316 | 828 | 35.8% | 547 | 278 | 168 | 1323 | 957 | 72.3% |
| 1627 | 216 | 148 | 2595 | 897 | 34.6% | 594 | 319 | 184 | 1498 | 1085 | 72.4% |
| 1628 | 274 | 92 | 3402 | 1390 | 40.9% | 934 | 460 | 231 | 1777 | 1169 | 65.8% |
| 1629 | 265 | 100 | 3602 | 1311 | 36.4% | 884 | 409 | 258 | 2051 | 1504 | 73.3% |
| 1630 | 108 | 26 | 1615 | 685 | 42.4% | 441 | 213 | 106 | 855 | 587 | 68.7% |

## By inventory

Inventory is read from the flat id (`session-3185-num-7-resolution-1`), not from
`session_date_status.inventory_id`, which enumerates several *candidate* inventories per date.
`no_axis` collects the days with no HTR text at all.

| inventory | days | no axis | resolutions | pinned | pinned % | det. | nearly | open | unplaced | in open | open % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3185 | 183 | 0 | 2130 | 815 | 38.3% | 544 | 274 | 149 | 1163 | 804 | 69.1% |
| 3186 | 198 | 0 | 2376 | 883 | 37.2% | 586 | 313 | 166 | 1311 | 907 | 69.2% |
| 3187 | 271 | 0 | 3372 | 1380 | 40.9% | 925 | 458 | 229 | 1760 | 1154 | 65.6% |
| 3188 | 261 | 0 | 3552 | 1311 | 36.9% | 885 | 409 | 253 | 2005 | 1458 | 72.7% |
| 3189 | 108 | 0 | 1615 | 685 | 42.4% | 441 | 213 | 106 | 855 | 587 | 68.7% |
| 4562 | 38 | 0 | 485 | 37 | 7.6% | 19 | 12 | 44 | 410 | 392 | 95.6% |
| no_axis | 0 | 535 | 0 | 0 | 0.0% | 0 | 0 | 0 | 0 | 0 | 0.0% |

### Anchor-starved inventories

Flagged automatically: pinned share below half the corpus average (18.9%).

- **4562** — 485 resolutions over 38 days, but only 37 pinned (**7.6%**), leaving **95.6%** of its unplaced work in open gaps. Tier-1 anchoring essentially does not reach this material, so it is a different problem from the rest of the corpus and should not be pooled with it when fitting anything.

## Gap-size distribution

| resolutions in gap | gaps |
| ---: | ---: |
| 0 | 3400 |
| 1 | 1156 |
| 2 | 523 |
| 3 | 306 |
| 4 | 183 |
| 5 | 119 |
| 6 | 84 |
| 7 | 73 |
| 8 | 44 |
| 9 | 32 |
| 10 | 19 |
| 11 | 21 |
| 12 | 15 |
| 13 | 10 |
| 14 | 15 |
| 15 | 9 |
| 16 | 4 |
| 17 | 3 |
| 18 | 2 |
| 19 | 1 |
| 20 | 2 |
| 21 | 1 |
| 23 | 2 |
| 24 | 1 |
| 25 | 1 |

## What this implies

The work is **concentrated, not diffuse**: 947 open gaps spanning
3,132,619 characters hold 70.7% of the unplaced resolutions,
while the remaining intervals are already determined or pinned to within a resolution or two by
counting alone. A placement model only has to be good inside those stretches — a far better
specified target than "improve boundary F1" over the whole corpus.


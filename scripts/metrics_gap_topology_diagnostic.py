#!/usr/bin/env python3
"""Character-axis topology of the *unresolved* gaps between consolidated anchors (user, 2026-10-05).

For each gap bracketed by two Group-A anchors in the live backbone, compare the characters actually
available against the characters the gap's unplaced resolutions would need. Three statistics per gap:

- elasticity   `eps = L_char / (K * mu_len)`           -- the ratio the user asked for
- tension      `tau = ln(max(eps, 1e-4)) ** 2`         -- symmetric penalty on compression/dilatation
- surprise     `z   = (L_char - K * mu_len) / (sqrt(K) * sd_len)`

**`z`, not `eps`, is the ranking statistic, and that is the main correction to the proposed design.**
Resolution length is highly dispersed -- measured CV_1 = sd/mean = **0.95**, i.e. the standard
deviation is as large as the mean -- so a single resolution's expected length says essentially
nothing and `eps` on a K=1 gap is noise. A gap's *total* concentrates: the CV of the sum falls as
0.95/sqrt(K), so reaching CV <= 0.30 needs **K >= 11**. On the gold + hard-period scope only
**12 of 154 unresolved gaps (7.8%)** clear that bar, because the gap size distribution is dominated
by small gaps (median K = 2, p90 = 8). That is the honest scope of this whole measure: it is decisive
for a crowded minority and uninformative for the rest. `z` carries the sqrt(K) scaling; `eps` and
`tau` do not, which is why ranking by either puts tiny gaps at the top of the friction list.

**`mu_len` is measured, never assumed.** The proposed design used 650 characters. Measured three
ways at runtime: pooled (total axis characters / total enriched resolutions) gives **885**, the only
estimate consistent with "every character belongs to exactly one resolution"; the mean over
`separated` placements gives **1166**, but that subset is length-biased (cleanly-bounded resolutions
run longer); the per-day median is **633**. 650 is near the 25th percentile of the per-resolution
distribution, so adopting it would inflate every `eps` by ~1.4x against pooled and ~1.8x against the
separated mean -- turning genuine compressions isometric, which is the one class that matters, since
compression is what missing HTR text looks like. That the three estimates span 633-1166 is itself the
warning: `eps`'s absolute level is only as good as the denominator chosen, so the gap `eps`
distribution is printed as quantiles and the friction ranking uses `z`, which is scale-aware.

Validation (convergent, not circular): ranking *days* by `z` with no knowledge of inventories or
secret flags puts 8 of the 34 inventory-4562 "secret hijack" days in the top 20, against a 3.0% base
rate -- a 13x enrichment -- and surfaces `1630-02-22` (the known row-internal-tie crowding pathology)
at rank 3. A gap-level run should reproduce that concentration or be treated as suspect.

What the first run showed, so the two classes are read correctly:
- **Compression** (many unplaced resolutions, few characters) is what *missing text* looks like. The
  gold/hard-period run put `1626-04-24`, `1627-01-14`, `1626-05-29`, `1629-02-02`, `1626-12-16` and
  `1626-03-28` at the top -- the same severe-collapse / secret-hijack days identified today by
  entirely separate channels (inventory 4562, secret flags, annotation). Convergent, not circular.
- **Dilatation** (far more text than the unplaced count implies) is the *inverse* pathology and is
  new: `1628-12-14` has one unplaced resolution across 44 paragraphs / 37,561 characters. That is not
  one enormous resolution; it is text whose resolutions the ledger does not know about -- a missing
  enriched entry, or another date's business sitting in a shared session. It is therefore a lead for
  the duplicate/shared-session work, not noise.
- `1626-03-28` appears in *both* classes on the same day (a K=1 dilatation over the secret
  resolution's own 8 paragraphs, and a K=13 compression into a single paragraph), which is the user's
  observation that gaps and lumping co-occur in one session, now visible as two numbers.

**Scope boundary (user decision, 2026-10-05): this measure stays on gaps and never touches anchors.**
It is a measurement, not a diagnosis: the only claim it is entitled to make is "there are x
resolutions assigned here while the text supports about y". Having no causal content, it has no
business adjudicating which anchors survive, so the proposed `delta_tau` gatekeeper (reject a
candidate anchor if it raises total tension) is **out of scope by design**, not merely deferred. Two
further reasons it would have been a bad bet even if it were in scope: inserting any anchor splits one
gap into two, so a *correct* anchor usually raises `tau` as pure arithmetic and the rule would need a
random-anchor null showing the correct and wrong `delta_tau` distributions actually separate; and as a
withdrawal-type mechanism it is structurally disfavoured by the `separated` ruling. Do not revive it
from the formula alone.

Char offsets are used to measure *lengths* only, never to score boundary precision -- the same line
`length_prior_eval` drew, and the tolerance-metric family stays excluded.

Usage:
    PYTHONPATH=. uv run python -m scripts.metrics_gap_topology_diagnostic --days gold
    PYTHONPATH=. uv run python -m scripts.metrics_gap_topology_diagnostic --days all
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from build_alignment_new import align_session, calculate_idf_weights
from data_io import load, save_semi_structured
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.pathology_corpus_stage_a import load_combined_overlap
from scripts.s4_corpus_paragraph_predictions import axis_for_date, grouped_enriched
from scripts.s4_paragraph_axis_baseline import build_axis_overlap
from scripts.s6c_gap_segmentation import build_anchor_backbone
from scripts.separated_accuracy_eval import label_separation

CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "gap_topology_diagnostic"
GOLD_DATASETS = ("boundary_gold_sample", "boundary_gold_hard_period_sample")

# Conventions carried over from the proposed design, kept so counts are comparable -- but the
# measured gap `eps` median is ~0.70, i.e. the whole distribution sits below 1, so these cut points
# are NOT centred on this corpus and the class counts should be read as "relative to a convention",
# never as "this many gaps are anomalous". Quantile rank is the honest summary.
COMPRESSION_EPS = 0.35
DILATATION_EPS = 2.5


def measure_length_scale(
    concordance: pd.DataFrame,
    axis_by_date: dict[str, Any],
    axis_by_session: dict[str, Any],
    session_by_date: dict[str, str],
) -> tuple[float, float, dict[str, float]]:
    """`(mu_len, sd_len, alternatives)` measured from the corpus, with the biases stated."""
    total_chars = 0
    total_resolutions = 0
    per_day_ratios: list[float] = []
    for date, group in concordance.groupby("enriched_date"):
        axis = axis_for_date(str(date), axis_by_date, axis_by_session, session_by_date)
        if not axis:
            continue
        chars = sum(len(str(record.get("text") or "")) for record in axis)
        total_chars += chars
        total_resolutions += len(group)
        per_day_ratios.append(chars / len(group))

    placed = concordance.dropna(subset=["paragraph_start_index", "paragraph_end_index"]).copy()
    labelled = label_separation(placed)
    separated = labelled[labelled["separated"]]
    extents: list[int] = []
    for date, group in separated.groupby("enriched_date"):
        axis = axis_for_date(str(date), axis_by_date, axis_by_session, session_by_date)
        if not axis:
            continue
        lengths = [len(str(record.get("text") or "")) for record in axis]
        for row in group.itertuples():
            start, end = int(row.paragraph_start_index), int(row.paragraph_end_index)
            if 0 <= start < len(lengths):
                extents.append(sum(lengths[start:min(end, len(lengths) - 1) + 1]))
    extents_series = pd.Series([e for e in extents if e > 0], dtype=float)

    mu = total_chars / max(1, total_resolutions)
    # Dispersion has to come from the separated extents -- the pooled estimate gives a mean but no
    # spread. Its level is biased upward, so only its *shape* is used here.
    sd = float(extents_series.std()) if not extents_series.empty else mu
    alternatives = {
        "pooled_mu": mu,
        "separated_mean": float(extents_series.mean()) if not extents_series.empty else float("nan"),
        "per_day_median": float(np.median(per_day_ratios)) if per_day_ratios else float("nan"),
        "separated_sd": sd,
    }
    return mu, sd, alternatives


def classify(eps: float, k: int) -> str:
    if k == 0:
        return "no_unplaced"
    if eps <= COMPRESSION_EPS:
        return "compression"
    if eps >= DILATATION_EPS:
        return "dilatation"
    return "isometric"


def gaps_for_day(
    date: str,
    enriched_ids: list[str],
    axis: list[dict[str, Any]],
    combined_overlap: Any,
    idf_weights: dict[str, float],
    mu: float,
    sd: float,
) -> list[dict[str, Any]]:
    """Anchor-bracketed gaps for one day, with elasticity, tension and surprise."""
    lengths = [len(str(record.get("text") or "")) for record in axis]
    axis_ids = [record["axis_id"] for record in axis]
    overlap_lookup = build_axis_overlap(axis, combined_overlap)
    alignments = align_session(enriched_ids, axis_ids, overlap_lookup, idf_weights)
    backbone = build_anchor_backbone(len(enriched_ids), len(axis_ids), alignments)

    gaps = []
    for (left_e, left_a), (right_e, right_a) in zip(backbone, backbone[1:]):
        k = right_e - left_e - 1
        if k <= 0:
            continue
        low, high = left_a, max(left_a, right_a - 1)
        l_char = sum(lengths[low:high + 1]) if low < len(lengths) else 0
        expected = k * mu
        eps = l_char / max(1.0, expected)
        # The whole output in the units of the problem (user, 2026-10-05): the only claim this
        # measure is entitled to make is "there are k_unplaced resolutions assigned here while the
        # text supports about k_implied". `eps` is the same ratio with the units hidden, and
        # `k_surplus` is how many resolutions have nowhere to go (positive) or how much text has no
        # resolution claiming it, expressed as resolutions (negative).
        k_implied = l_char / mu
        gaps.append({
            "date": date,
            "k_unplaced": k,
            "k_implied": k_implied,
            "k_surplus": k - k_implied,
            "room_paragraphs": high - low + 1,
            "l_char": l_char,
            "expected_char": expected,
            "eps": eps,
            "tau": math.log(max(eps, 1e-4)) ** 2,
            "z": (l_char - expected) / (math.sqrt(k) * sd),
            "classification": classify(eps, k),
        })
    return gaps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", choices=("gold", "all"), default="gold",
                        help="'gold' = the 74 gold + hard-period days (fast); 'all' = corpus (slow)")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--no-write", action="store_true",
                        help="print only; by default the per-gap rows are persisted")
    args = parser.parse_args()

    axis_by_date, axis_by_session, session_by_date = load_axis_indexes()
    concordance = load(CONCORDANCE_DATASET)
    concordance["enriched_date"] = concordance["enriched_date"].astype(str)

    mu, sd, alternatives = measure_length_scale(
        concordance, axis_by_date, axis_by_session, session_by_date
    )
    print("resolution length scale, measured (the design's assumed 650 is not used):")
    for name, value in alternatives.items():
        print(f"  {name:16s} {value:8.0f}")
    print(f"  -> mu_len={mu:.0f} (pooled, the only estimate consistent with a partition), "
          f"sd_len={sd:.0f}, CV={sd / mu:.2f}\n")

    if args.days == "gold":
        dates = sorted({
            str(day["date"]) for name in GOLD_DATASETS for day in load(name)["days"]
        })
    else:
        dates = sorted(concordance["enriched_date"].unique())
    print(f"scope: {len(dates)} days\n")

    combined_overlap = load_combined_overlap()
    idf_weights = calculate_idf_weights(combined_overlap)
    enriched_by_date = grouped_enriched()

    rows: list[dict[str, Any]] = []
    for date in dates:
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)
        enriched_ids = enriched_by_date.get(date)
        if not axis or not enriched_ids:
            continue
        rows.extend(
            gaps_for_day(date, enriched_ids, axis, combined_overlap, idf_weights, mu, sd)
        )

    if not rows:
        print("no unresolved gaps found in scope")
        return
    frame = pd.DataFrame(rows)
    counts: Counter[str] = Counter(frame["classification"])
    total = len(frame)
    print(f"unresolved gaps: {total} over {frame['date'].nunique()} days, "
          f"holding {int(frame['k_unplaced'].sum())} unplaced resolutions\n")
    print("classification (thresholds are conventions, not findings -- see the eps quantiles below):")
    for name, count in counts.most_common():
        print(f"  {name:12s} {count:4d} ({count / total:5.1%})")
    print("\neps quantiles: " + "  ".join(
        f"p{int(q * 100)}={frame['eps'].quantile(q):.2f}" for q in (0.1, 0.25, 0.5, 0.75, 0.9)
    ))
    print("k_unplaced:    " + "  ".join(
        f"p{int(q * 100)}={frame['k_unplaced'].quantile(q):.0f}" for q in (0.5, 0.75, 0.9)
    ))
    # CV of a gap's total length is CV_1 / sqrt(K), so the K needed for a given precision follows
    # from the measured dispersion rather than from a round number.
    k_needed = math.ceil((sd / mu / 0.3) ** 2)
    usable = frame[frame["k_unplaced"] >= k_needed]
    print(f"\ngaps where the length test is informative (CV of the total <= 0.30 needs "
          f"k >= {k_needed} at CV_1 = {sd / mu:.2f}): {len(usable)} of {total} "
          f"({len(usable) / total:.1%})")

    print(f"\ntop {args.top} friction peaks by |z| (K-aware; ranking by eps or tau would list "
          "tiny gaps instead):")
    ranked = frame.reindex(frame["z"].abs().sort_values(ascending=False).index)
    shown = ranked.head(args.top).copy()
    shown["k_implied"] = shown["k_implied"].round(1)
    shown["k_surplus"] = shown["k_surplus"].round(1)
    print(shown[["date", "k_unplaced", "k_implied", "k_surplus", "room_paragraphs", "l_char",
                 "eps", "z", "classification"]].to_string(index=False))
    print("\nread a row as: k_unplaced resolutions are assigned here, the text supports about "
          "k_implied; k_surplus is the shortfall in resolutions. That is the only claim this "
          "measure makes -- it names no cause.")

    if args.no_write:
        return
    # The length scale is written as a header row because every eps/tau/z below is relative to it:
    # a later reader comparing two runs must be able to see whether mu_len moved underneath them.
    records = [{
        "record_type": "run", "scope": args.days, "days_in_scope": len(dates),
        "days_with_gaps": int(frame["date"].nunique()), "gaps": total,
        "unplaced_resolutions": int(frame["k_unplaced"].sum()),
        "mu_len": mu, "sd_len": sd, "cv_1": sd / mu, "k_for_cv_0.30": k_needed,
        "informative_gaps": int(len(usable)),
        "compression_eps_threshold": COMPRESSION_EPS, "dilatation_eps_threshold": DILATATION_EPS,
        **{f"mu_alt_{name}": value for name, value in alternatives.items()},
    }]
    records.extend(
        {"record_type": "gap", "friction_rank": rank, **row}
        for rank, row in enumerate(ranked.to_dict(orient="records"), start=1)
    )
    save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[CONCORDANCE_DATASET],
        description=(
            f"Gap topology over scope={args.days}: {total} unresolved anchor-bracketed gaps, "
            f"mu_len={mu:.0f} sd_len={sd:.0f} measured at runtime. z is the ranking statistic; "
            "a screen, not a diagnosis."
        ),
        script=__file__,
    )
    print(f"\nwrote {len(records)} rows to `{OUTPUT_DATASET}` (1 run header + {total} gaps)")


if __name__ == "__main__":
    main()

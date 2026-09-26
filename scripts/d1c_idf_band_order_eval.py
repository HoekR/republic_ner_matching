#!/usr/bin/env python3
"""Step 3's gate (plans/COLLISION_AVOIDANCE_TRACK.md) -- is entity *order* consistent for COMMON
entities, or only for rare ones?

Step 3 proposes moving the alignment's unit from the resolution to the entity mention and dropping
IDF weighting, on hypothesis 5: "entity order is informative for all entities, not just rare ones --
because this is a sequence, a common entity still constrains the alignment path". The track's gate
for that step is to re-run D1c (Kendall tau on entity order in trusted tier-1 pairs) *stratified by
IDF band*: if common-entity order consistency is comparable to rare-entity, the hypothesis holds and
the entity-stream alignment is worth building; if it is near-random, Step 3 closes for the price of
this one diagnostic.

**Why a re-run rather than reading the existing number.** `run_diagnostics.run_d1c_entity_order_kendall`
already emits `mean_kendall_tau_high_idf` / `mean_kendall_tau_low_idf`, but its band test is
`avg_idf >= 2.0` against weights defined as `log((total_docs + 1) / (freq + 1)) + 1` with
`total_docs` the whole flat-resolution corpus. That floor is above 2.0 for essentially every name,
so the stored run (output/diagnostics_summary.json) has `tau_high_idf == tau_all == 0.638` and
`tau_low_idf == 0.0` on **n = 0** pairs: the stratification exists in the code and has never
measured anything. Banding here is by *quantile*, which cannot degenerate that way.

Method, and where it deliberately departs from the original D1c:

* **All 5,730 tier-1 pairs**, not a 2,000-pair sample -- the vocabulary is small enough (946 names)
  that the full set costs seconds.
* **Vocabulary = the distinct entity names (>= 4 characters, this repo's fuzzy-match floor) in the
  three overlap tables**, i.e. exactly the names production's own `calculate_idf_weights` covers.
  Frequency = number of overlap evidence rows carrying the name, the same count that IDF inverts, so
  "common" here means "common in the evidence production down-weights".
* **Bands are mention-weighted terciles** over the mentions actually observed in these pairs (so each
  band carries roughly a third of the observed mentions, not a third of the vocabulary). `common` is
  the top-frequency third = the lowest-IDF third.
* **A band's tau is computed over that band's mentions alone** inside one pair, so a common-band tau
  is never carried by rare mentions sitting in the same pair. A pair contributes to a band only when
  it shares >= 2 mentions in that band.
* Whole-pair tau is also reported, for comparability with the standing 0.638 figure.

The same run measures the competing explanation the track names: at mean entity containment 0.295
the binding scarcity may be *recall on the matched side* rather than alphabet density, in which case
a denser alphabet is a non-problem. `pairs_with_multi_mentions` and the shared-count distribution
answer that directly.

**Mismatched-pair control.** A high tau is not by itself evidence of alignable order: both sides are
formulaic, so "Holland early, then the specific place" could be a positional convention that any two
texts of this corpus share. The control re-runs the identical measurement on *deliberately wrong*
pairings (each enriched text against another pair's flat text, a fixed derangement, self-pairings and
same-`flat_id` collisions dropped). If the control's band taus match the real ones, the order signal
is convention rather than alignment evidence.

Gate thresholds, fixed before the run:

* `MIN_PAIRS_PER_BAND = 50` -- below this, verdict is `no_data`, not a result.
* **pass**: `tau_common >= 0.40` AND `tau_common >= 0.75 * tau_rare`.
* **fail**: `tau_common < 0.20` (near-random -- common entities carry no order signal).
* anything else: `inconclusive`.

The control's own threshold was fixed after the first (control-free) run reported `pass`, and before
the control itself ran -- stated plainly because the order matters for how much the margin is worth:

* **pass** additionally requires `tau_common - control_tau_common >= 0.20`; otherwise the verdict is
  `convention_not_alignment`, which is a fail for Step 3's purpose.

Caveat to carry into any reading of the result: a tier-1 `flat_text` is a whole flat resolution,
which under 81.1% HTR under-segmentation routinely holds the material of several enriched
resolutions. So these taus measure order agreement between one editorial summary and a possibly
larger HTR span -- the same property the original D1c had, stated rather than corrected.

Usage:
    uv run python -m scripts.d1c_idf_band_order_eval
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kendalltau

from data_io import load, resolve, save_semi_structured

ALIGNMENT_DATASET = "alignment_1626_1630"
OVERLAP_DATASETS = ("place_overlap_1626_1630", "org_overlap_1626_1630", "per_overlap_1626_1630")
OUTPUT_DATASET = "d1c_idf_band_order_eval"

MIN_NAME_LENGTH = 4
BANDS = ("common", "mid", "rare")
MIN_PAIRS_PER_BAND = 50
PASS_TAU_FLOOR = 0.40
PASS_RATIO = 0.75
FAIL_TAU_CEILING = 0.20
MIN_MARGIN_OVER_CONTROL = 0.20
HIGH_CONCORDANCE_TAU = 0.8


def overlap_frame() -> pd.DataFrame:
    frames = []
    for dataset in OVERLAP_DATASETS:
        frame = pd.read_excel(resolve(dataset))
        if "name" not in frame.columns and "naam" in frame.columns:
            frame = frame.rename(columns={"naam": "name"})
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def name_frequencies(overlap: pd.DataFrame) -> dict[str, int]:
    """Lowercased entity name -> overlap evidence rows carrying it (the count IDF inverts)."""
    names = overlap["name"].dropna().astype(str).str.strip().str.lower()
    return {name: count for name, count in Counter(names).items() if len(name) >= MIN_NAME_LENGTH}


def shared_mentions(
    enriched_text: str, flat_text: str, vocabulary: Iterable[str]
) -> list[tuple[str, int, int]]:
    """(name, first offset in the enriched text, first offset in the flat text) for shared names."""
    enriched = enriched_text.lower()
    flat = flat_text.lower()
    found: list[tuple[str, int, int]] = []
    for name in vocabulary:
        enriched_at = enriched.find(name)
        if enriched_at < 0:
            continue
        flat_at = flat.find(name)
        if flat_at < 0:
            continue
        found.append((name, enriched_at, flat_at))
    return found


def band_edges(frequencies: Sequence[int]) -> tuple[float, float]:
    """33rd/67th percentile of the observed mention frequencies (mention-weighted terciles)."""
    if not frequencies:
        return (0.0, 0.0)
    return (
        float(np.percentile(frequencies, 100 / 3)),
        float(np.percentile(frequencies, 200 / 3)),
    )


def band_of(frequency: int, edges: tuple[float, float]) -> str:
    """`common` = high evidence frequency = low IDF; `rare` = the opposite end."""
    low, high = edges
    if frequency > high:
        return "common"
    if frequency > low:
        return "mid"
    return "rare"


def pair_tau(mentions: Sequence[tuple[str, int, int]]) -> float | None:
    """Kendall tau between enriched-side and flat-side mention order within one pair."""
    if len(mentions) < 2:
        return None
    tau, _ = kendalltau([offset for _, offset, _ in mentions], [offset for _, _, offset in mentions])
    return None if tau is None or np.isnan(tau) else float(tau)


def summarize_taus(taus: Sequence[float]) -> dict[str, Any]:
    if not taus:
        return {"pairs": 0, "mean_tau": None, "median_tau": None, "share_tau_ge_0.8": None}
    series = pd.Series(taus)
    return {
        "pairs": int(len(series)),
        "mean_tau": round(float(series.mean()), 4),
        "median_tau": round(float(series.median()), 4),
        "share_tau_ge_0.8": round(float((series >= HIGH_CONCORDANCE_TAU).mean()), 4),
    }


def gate_verdict(
    by_band: dict[str, dict[str, Any]], control_by_band: dict[str, dict[str, Any]] | None = None
) -> tuple[str, str]:
    """(verdict, reason) under the thresholds fixed in this module's docstring."""
    common = by_band.get("common", {})
    rare = by_band.get("rare", {})
    if common.get("pairs", 0) < MIN_PAIRS_PER_BAND or rare.get("pairs", 0) < MIN_PAIRS_PER_BAND:
        return "no_data", (
            f"fewer than {MIN_PAIRS_PER_BAND} pairs in a band "
            f"(common={common.get('pairs', 0)}, rare={rare.get('pairs', 0)})"
        )
    tau_common = common["mean_tau"]
    tau_rare = rare["mean_tau"]
    if tau_common < FAIL_TAU_CEILING:
        return "fail", f"common-band tau {tau_common} is below the near-random ceiling {FAIL_TAU_CEILING}"
    if not (tau_common >= PASS_TAU_FLOOR and tau_common >= PASS_RATIO * tau_rare):
        return "inconclusive", (
            f"common-band tau {tau_common} is real but below the floor {PASS_TAU_FLOOR} "
            f"or below {PASS_RATIO} x the rare-band tau {tau_rare}"
        )
    if control_by_band is not None:
        control_common = control_by_band.get("common", {})
        if control_common.get("pairs", 0) < MIN_PAIRS_PER_BAND:
            return "no_data", (
                f"the mismatched-pair control has fewer than {MIN_PAIRS_PER_BAND} common-band pairs "
                f"({control_common.get('pairs', 0)}), so the margin is unmeasured"
            )
        margin = round(tau_common - control_common["mean_tau"], 4)
        if margin < MIN_MARGIN_OVER_CONTROL:
            return "convention_not_alignment", (
                f"common-band tau {tau_common} beats deliberately wrong pairings by only {margin} "
                f"(threshold {MIN_MARGIN_OVER_CONTROL}): the order agreement is positional convention "
                "shared by any two texts of this corpus, not alignment evidence"
            )
        return "pass", (
            f"common-band tau {tau_common} clears the {PASS_TAU_FLOOR} floor, is >= {PASS_RATIO} x "
            f"the rare-band tau {tau_rare}, and beats the mismatched-pair control by {margin}"
        )
    return "pass", (
        f"common-band tau {tau_common} clears the {PASS_TAU_FLOOR} floor and is "
        f">= {PASS_RATIO} x the rare-band tau {tau_rare}"
    )


def deranged_indices(count: int) -> list[int]:
    """A fixed offset permutation: no index maps to itself, so every control pairing is wrong."""
    if count < 2:
        return []
    offset = max(1, count // 2)
    return [(index + offset) % count for index in range(count)]


def aggregate(
    mentions_per_pair: Sequence[Sequence[tuple[str, int, int]]],
    frequencies: dict[str, int],
    edges: tuple[float, float],
) -> dict[str, Any]:
    """Whole-pair and per-band tau summaries, plus mention scarcity, for one set of pairings."""
    whole_pair_taus: list[float] = []
    band_taus: dict[str, list[float]] = {band: [] for band in BANDS}
    band_frequencies: dict[str, list[int]] = {band: [] for band in BANDS}
    shared_counts: list[int] = []
    multi_mention_pairs = 0
    multi_common_only = 0
    per_pair: list[dict[str, Any]] = []

    for mentions in mentions_per_pair:
        shared_counts.append(len(mentions))
        by_band: dict[str, list[tuple[str, int, int]]] = {band: [] for band in BANDS}
        for mention in mentions:
            band = band_of(frequencies[mention[0]], edges)
            by_band[band].append(mention)
            band_frequencies[band].append(frequencies[mention[0]])

        tau = pair_tau(mentions)
        if tau is not None:
            multi_mention_pairs += 1
            whole_pair_taus.append(tau)
            if len(by_band["common"]) >= 2 and not by_band["mid"] and not by_band["rare"]:
                multi_common_only += 1

        band_results: dict[str, float | None] = {}
        for band in BANDS:
            band_tau = pair_tau(by_band[band])
            band_results[band] = band_tau
            if band_tau is not None:
                band_taus[band].append(band_tau)
        per_pair.append(
            {
                "shared_mentions": len(mentions),
                "mentions_by_band": {band: len(by_band[band]) for band in BANDS},
                "whole_pair_tau": tau,
                "band_tau": band_results,
            }
        )

    return {
        "whole_pair": summarize_taus(whole_pair_taus),
        "by_band": {band: summarize_taus(band_taus[band]) for band in BANDS},
        "band_frequency_ranges": {
            band: (
                {
                    "mentions": len(values),
                    "min": int(min(values)),
                    "max": int(max(values)),
                }
                if values
                else {"mentions": 0, "min": None, "max": None}
            )
            for band, values in band_frequencies.items()
        },
        "scarcity": {
            "pairs": len(shared_counts),
            "pairs_with_multi_mentions": multi_mention_pairs,
            "share_pairs_with_multi_mentions": round(multi_mention_pairs / len(shared_counts), 4)
            if shared_counts
            else None,
            "mean_shared_mentions": round(float(np.mean(shared_counts)), 3) if shared_counts else None,
            "median_shared_mentions": float(np.median(shared_counts)) if shared_counts else None,
            "pairs_whose_multi_mentions_are_all_common_band": multi_common_only,
        },
        "per_pair": per_pair,
    }


def main() -> None:
    alignment = load(ALIGNMENT_DATASET)
    tier1 = alignment.loc[
        alignment["confidence_tier"].astype(str).str.contains("tier1", case=False)
    ].reset_index(drop=True)
    frequencies = name_frequencies(overlap_frame())
    vocabulary = sorted(frequencies)

    enriched_texts = tier1["enriched_text"].fillna("").astype(str).tolist()
    flat_texts = tier1["flat_text"].fillna("").astype(str).tolist()
    flat_ids = tier1["flat_id"].astype(str).tolist()

    real_mentions = [
        shared_mentions(enriched, flat, vocabulary) for enriched, flat in zip(enriched_texts, flat_texts)
    ]

    # Mismatched-pair control: a fixed derangement so no pair is matched with itself, dropping any
    # pairing that would (by coincidence) reuse the same flat_id -- that is not a wrong pairing.
    control_order = deranged_indices(len(tier1))
    control_mentions = [
        shared_mentions(enriched_texts[i], flat_texts[control_order[i]], vocabulary)
        if i < len(control_order) and flat_ids[control_order[i]] != flat_ids[i]
        else []
        for i in range(len(tier1))
    ]

    observed = [frequencies[name] for mentions in real_mentions for name, _, _ in mentions]
    edges = band_edges(observed)

    real = aggregate(real_mentions, frequencies, edges)
    control = aggregate(control_mentions, frequencies, edges)
    verdict, reason = gate_verdict(real["by_band"], control["by_band"])

    pair_records = [
        {
            "record_type": "pair",
            "enriched_id": str(row.enriched_id),
            "flat_id": str(row.flat_id),
            "date": str(row.date)[:10],
            **real_record,
            "control_shared_mentions": control_record["shared_mentions"],
            "control_whole_pair_tau": control_record["whole_pair_tau"],
        }
        for row, real_record, control_record in zip(tier1.itertuples(index=False), real["per_pair"], control["per_pair"])
    ]

    summary = {
        "record_type": "summary",
        "gate": "Step 3 (plans/COLLISION_AVOIDANCE_TRACK.md) -- hypothesis 5, order over all entities",
        "verdict": verdict,
        "verdict_reason": reason,
        "thresholds": {
            "min_pairs_per_band": MIN_PAIRS_PER_BAND,
            "pass_tau_floor": PASS_TAU_FLOOR,
            "pass_ratio_vs_rare": PASS_RATIO,
            "fail_tau_ceiling": FAIL_TAU_CEILING,
            "min_margin_over_control": MIN_MARGIN_OVER_CONTROL,
        },
        "tier1_pairs": int(len(tier1)),
        "vocabulary_names": len(vocabulary),
        "band_edges_evidence_rows": {"common_above": edges[1], "rare_at_or_below": edges[0]},
        "real": {k: v for k, v in real.items() if k != "per_pair"},
        "control": {k: v for k, v in control.items() if k != "per_pair"},
        "method_note": (
            "Bands are mention-weighted terciles of overlap-evidence frequency; a band's tau uses "
            "only that band's mentions within a pair. Whole-pair tau is reported for comparability "
            "with the standing 0.638 D1c figure. The control re-runs the same measurement on "
            "deliberately mismatched enriched/flat pairings (fixed derangement). No tolerance-family "
            "metric is computed."
        ),
    }

    output = save_semi_structured([summary, *pair_records], logical_name=OUTPUT_DATASET, script=__file__)

    print(f"Wrote D1c IDF-band order evaluation to {output}")
    print(f"tier-1 pairs: {summary['tier1_pairs']}; vocabulary: {summary['vocabulary_names']} names")
    print(f"band edges (overlap evidence rows): rare <= {edges[0]:.0f} < mid <= {edges[1]:.0f} < common")
    for label, data in (("real", real), ("control", control)):
        whole = data["whole_pair"]
        print(f"[{label}] whole pair: n={whole['pairs']:>5} mean tau={whole['mean_tau']} share>=0.8={whole['share_tau_ge_0.8']}")
        for band in BANDS:
            stats = data["by_band"][band]
            freq = data["band_frequency_ranges"][band]
            print(
                f"[{label}] {band:>8}: n={stats['pairs']:>5} mean tau={stats['mean_tau']} "
                f"median={stats['median_tau']} share>=0.8={stats['share_tau_ge_0.8']} "
                f"mentions={freq['mentions']} freq={freq['min']}..{freq['max']}"
            )
    print(f"real scarcity: {real['scarcity']}")
    print(f"GATE: {verdict} -- {reason}")


if __name__ == "__main__":
    main()

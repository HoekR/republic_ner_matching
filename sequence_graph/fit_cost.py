"""Fit Stage 4's cost model on gold -- the calibration pass Decision 2 (2026-10-09) deferred.

**Scope, decided with the user 2026-10-09: fit `match_cost`/`gap_cost` only.** `insertion_cost`/
`split_discount` and `soft_clip_cost` stay at `CostModel`'s original Decision-2 placeholders --
gold labels final correspondences, not the split-vs-margin-content distinction those moves need,
so there is no calibration population for them yet. See `CostModel`'s own docstring for the same
caveat, stated where it is most likely to be read before being misused as fully calibrated.

**Non-circular by construction.** The positive population is exactly `gold_aligned_pairs_detailed`'s
data (every `boundary_gold_sample`/`boundary_gold_hard_period_sample` hand-verified
correspondence already on the graph), never a solver-derived or legacy-concordance `ALIGNED_TO`
edge -- the same rule `sequence_graph.correspondence`'s module docstring states for anything that
fits `CostModel`. Negatives are a within-day derangement of that same day's gold-matched HTR
resolutions, reusing `scripts.d1c_idf_band_order_eval.deranged_indices`/`control_offsets` --
the exact technique already used for the 0.9555 TF-IDF AUC discrimination check -- rather than a
new ad hoc negative-sampling method.

**Reads the graph, not `boundary_gold_sample` directly (fixed 2026-10-09, user: "this does not
look scalable").** This module used to re-derive gold correspondences itself
(`gold_start_paragraphs` + iterating both gold datasets by hand) -- a second copy of exactly what
`sequence_graph.correspondence.add_aligned_to_gold` already does, and the two silently diverged
within the same session (this module's old copy never picked up
`boundary_gold_hard_period_sample`, 344 positives vs. the graph's 391). Now reads
`gold_aligned_pairs_detailed(load_graph())`: one source of gold interpretation, not two.

**The fit changes `match_cost`'s formula, not just its constants.** A straight line
(`base - lambda*overlap`) cannot be a calibrated probability's cost; the real form is
`-log(sigmoid(intercept + coef*overlap))` (`CostModel.match_cost`, when `match_logit` is set).
`gap_cost` needs no formula change -- it was always meant to read as `-log(P(deletion))`, fitting
it just means using the measured deletion rate instead of a guessed `1.0`.

Usage:
    uv run python -m sequence_graph.fit_cost
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict

import pandas as pd
from sklearn.linear_model import LogisticRegression

from data_io import load
from scripts.corpus_scope import in_scope
from scripts.d1c_idf_band_order_eval import control_offsets, deranged_indices
from scripts.separated_accuracy_eval import gold_start_paragraphs, label_separation, uniform_start_paragraphs

from sequence_graph.align import CostModel, build_entity_overlap_scorer, day_paragraph_stream, run_bracket
from sequence_graph.correspondence import gold_aligned_pairs_detailed
from sequence_graph.persist import load_graph

GOLD_DATASET = "boundary_gold_sample"  # still used by _gold_day_spread/_alignable_gold_dates below


def build_calibration_pairs() -> pd.DataFrame:
    """One positive + one negative row per gold-located resolution: the real gold match, scored
    by the production entity-overlap function, and a within-day derangement control (same day,
    wrong HTR target among that day's OTHER gold-matched resolutions) -- never a cross-day
    pairing, which would trivially score near zero and teach nothing near the actual decision
    boundary.
    """
    scorer = build_entity_overlap_scorer()
    by_date: dict[str, list[dict]] = defaultdict(list)
    for record in gold_aligned_pairs_detailed(load_graph()):
        by_date[record["date"]].append(record)

    rows: list[dict] = []
    for date, records in by_date.items():
        flat_ids = sorted({r["flat_id"] for r in records})
        n_read = len(flat_ids)
        if n_read < 2:
            continue  # a derangement needs >= 2 items to guarantee every pairing is wrong
        offsets = control_offsets(n_read, 1)
        shift = deranged_indices(n_read, offsets[0])

        for record in records:
            ref_index, flat_id = record["ref_index"], record["flat_id"]
            volgnr = f"{date}_{ref_index}"
            read_index = flat_ids.index(flat_id)
            rows.append({
                "date": date, "ref_index": ref_index, "label": 1,
                "overlap": scorer(volgnr, flat_id),
            })
            neg_flat_id = flat_ids[shift[read_index]]
            rows.append({
                "date": date, "ref_index": ref_index, "label": 0,
                "overlap": scorer(volgnr, neg_flat_id),
            })
    return pd.DataFrame(rows)


def fit_match_logit(pairs: pd.DataFrame) -> tuple[float, float]:
    """`(intercept, coef)` of a logistic `P(match | overlap)` fit. One feature, no regularization
    search -- the calibration population (hundreds of rows, not thousands) does not justify more,
    and an unregularized fit is the honest baseline to report before tuning anything. sklearn
    1.8's `LogisticRegression` default is already unpenalized (`penalty` is deprecated in favour
    of `C`/`l1_ratio`, and the new default applies neither) -- no extra argument needed."""
    model = LogisticRegression()
    model.fit(pairs[["overlap"]].to_numpy(), pairs["label"].to_numpy())
    return float(model.intercept_[0]), float(model.coef_[0][0])


def fit_deletion_rate() -> float:
    """Empirical `P(deletion)`: share of gold resolutions `gold_start_paragraphs` cannot locate,
    across BOTH gold datasets (`boundary_gold_sample` + `boundary_gold_hard_period_sample`) --
    this still reads the raw datasets directly, unlike `build_calibration_pairs` above, because it
    needs the population `add_aligned_to_gold` does NOT record: days/resolutions gold attempted
    and located NOTHING for leave no trace in the graph's `ALIGNED_TO` edges at all, so the
    denominator can't be read off the graph alone. This is the one place in this module that still
    parses gold directly, and it does so for a stated reason, not by oversight.

    **An upper-bound proxy, not an exact deletion rate** -- "gold does not locate it" conflates a
    genuine missing HTR match with "gold was not annotated this far", the same ambiguity
    `add_aligned_to_gold` already lives with and states for the identical reason.
    """
    total = located = 0
    for dataset_name in ("boundary_gold_sample", "boundary_gold_hard_period_sample"):
        for day in load(dataset_name)["days"]:
            if not in_scope(day["date"]):
                continue
            starts = gold_start_paragraphs(day, day["k_e"])
            total += len(starts)
            located += sum(1 for position in starts if position is not None)
    return (total - located) / total if total else 0.0


def fit_cost_model(base: CostModel | None = None) -> tuple[CostModel, dict]:
    """The one fitted `CostModel` this project has: `match_cost` and `gap_cost` calibrated on
    gold; `insertion_cost`/`split_discount`/`soft_clip_cost` left at `base`'s values -- see the
    module docstring for why those have no calibration population yet."""
    base = base or CostModel()
    pairs = build_calibration_pairs()
    intercept, coef = fit_match_logit(pairs)
    deletion_rate = fit_deletion_rate()
    gap_cost = max(base.epsilon, -math.log(deletion_rate)) if deletion_rate > 0 else base.gap_cost

    fitted = CostModel(
        base_match=base.base_match, match_lambda=base.match_lambda, gap_cost=gap_cost,
        soft_clip_cost=base.soft_clip_cost, split_discount=base.split_discount,
        epsilon=base.epsilon, abstain_threshold=base.abstain_threshold,
        match_logit=(intercept, coef),
    )
    report = {
        "n_pairs": len(pairs), "n_positive": int((pairs["label"] == 1).sum()),
        "match_logit": (intercept, coef), "deletion_rate": deletion_rate, "gap_cost": gap_cost,
    }
    return fitted, report


def _gold_day_spread() -> list[str]:
    """The same clean-to-severe spread used in `notebooks/sequence_graph_exploration.ipynb` §6,
    reused rather than re-picked, so the before/after comparison is on the exact days already
    shown to scale plausibly with the unfitted model.

    `boundary_gold_sample` only, not the hard-period sample, by necessity rather than oversight:
    `run_bracket` -- the thing this spread is run through, which wraps the DP itself -- only reads
    `boundary_gold_sample`. Extending the solver's own scope to the hard-period sample is a
    separate, not-yet-done piece of work (noted, not silently left unexamined)."""
    candidates = sorted(
        (day["date"], len(day["enriched_ids"]), len(day["flat_ids"]))
        for day in load(GOLD_DATASET)["days"]
    )
    alignable = [c for c in candidates if c[2] > 0]
    alignable.sort(key=lambda c: abs(c[1] - c[2]))
    picks = {alignable[0][0], alignable[len(alignable) // 4][0],
             alignable[len(alignable) // 2][0], alignable[-1][0]}
    return sorted(picks)


def _uniform_separated_count(date: str, k_e: int) -> int:
    """The standing guard (`docs/ITERATION_POLICY.md`): a trivial uniform spread once beat gold's
    own annotations on `separated`, so every `separated` count here is reported against this
    null, never absolute."""
    stream = day_paragraph_stream(date)
    if not stream or k_e == 0:
        return 0
    positions = uniform_start_paragraphs(len(stream), k_e)
    frame = pd.DataFrame({
        "enriched_date": date, "paragraph_start_index": positions, "paragraph_end_index": positions,
    })
    return int(label_separation(frame)["separated"].sum())


def _alignable_gold_dates() -> list[str]:
    return sorted(
        day["date"] for day in load(GOLD_DATASET)["days"]
        if in_scope(day["date"]) and len(day["flat_ids"]) > 0
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    fitted, report = fit_cost_model()
    print(f"calibration pairs: {report['n_pairs']} ({report['n_positive']} positive, "
          f"{report['n_pairs'] - report['n_positive']} negative)")
    print(f"match_logit (intercept, coef): "
          f"({report['match_logit'][0]:.3f}, {report['match_logit'][1]:.3f})")
    print(f"deletion_rate: {report['deletion_rate']:.3f}  ->  gap_cost: {report['gap_cost']:.3f} "
          f"(unfitted default: {CostModel().gap_cost})")

    unfitted = CostModel()

    def _fmt_agreement(report: dict) -> str:
        if report["exact_agreement"] is None:
            return "n/a"
        return f"{report['exact_agreement']:.2f} (n={report['exact_agreement_n']}/{report['k_e']})"

    print(f"\n{'date':<12}{'k_e':>4}{'k_f':>4}  {'unfitted exact':>20}  {'fitted exact':>20}  "
          f"{'unfitted sep':>12}  {'fitted sep':>10}  {'uniform-null sep':>16}")
    totals = {"unfitted_sep": 0, "fitted_sep": 0, "k_e": 0, "uniform_sep": 0}
    for date in _gold_day_spread():
        before = run_bracket(date, unfitted)
        after = run_bracket(date, fitted)
        uniform_sep = _uniform_separated_count(date, before["k_e"])
        print(f"{date:<12}{before['k_e']:>4}{before['k_f']:>4}  "
              f"{_fmt_agreement(before):>20}  {_fmt_agreement(after):>20}  "
              f"{before['separated_count']:>12}  {after['separated_count']:>10}  {uniform_sep:>16}")

    print("\naggregate over all alignable gold days "
          "(separated reported against the uniform null, never absolute -- standing guard):")
    for date in _alignable_gold_dates():
        before = run_bracket(date, unfitted)
        after = run_bracket(date, fitted)
        totals["unfitted_sep"] += before["separated_count"]
        totals["fitted_sep"] += after["separated_count"]
        totals["uniform_sep"] += _uniform_separated_count(date, before["k_e"])
        totals["k_e"] += before["k_e"]
    print(f"  k_e total: {totals['k_e']}")
    print(f"  unfitted separated: {totals['unfitted_sep']} ({totals['unfitted_sep'] / totals['k_e']:.1%})")
    print(f"  fitted separated:   {totals['fitted_sep']} ({totals['fitted_sep'] / totals['k_e']:.1%})")
    print(f"  uniform-null separated: {totals['uniform_sep']} ({totals['uniform_sep'] / totals['k_e']:.1%})")


if __name__ == "__main__":
    main()

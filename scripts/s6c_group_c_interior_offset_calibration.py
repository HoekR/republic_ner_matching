#!/usr/bin/env python3
"""Track P step P1 (PLAN.md "Main line", 2026-10-05): can Group C place a cut *inside* a
paragraph, or is it only available there?

Track P rests on the user's granularity rule -- within text, anchor placement may be
character-wise, because a resolution boundary inside a paragraph means that paragraph was
never a real unit. Availability of interior candidates is already measured (Group C gives
>=1 interior candidate on 78% of the 1,597 colliding paragraphs, enough for every needed cut
on 62%; Group B reaches 98%/94% but at median 9 candidates per cut, i.e. recall without
precision). Availability is not accuracy, and P1 is the free pre-check that asks the second
question before any annotation is commissioned: *given* that a candidate exists in the right
paragraph, does it land where gold's cut is -- better than guessing a position at random in
that same paragraph?

Population: every `unit == "mid_paragraph"`, `kind in {"cut", "start"}` slot in
`boundary_gold_sample` and `boundary_gold_hard_period_sample` -- **81 slots across 33 days**,
which is the real sample Track P was costed against, unlike the n=8 / n=12 populations that
defeated this session's `floor > 1` boundary-existence measurements. (PLAN.md attributes the
7 `mid_paragraph`/`start` slots to the hard-period sample; they are in fact in the original
sample -- 65 cut + 7 start there, 9 cut in the hard-period sample. The 81/33 totals hold.)
8 of the 81 carry `char_offset == 0`: a `mid_paragraph` marker placed at the paragraph's own
first character, which is a paragraph boundary described in the other unit's terms and has no
interior position to find. They are reported and held out, leaving **73 interior cuts in 63
host paragraphs** (54 paragraphs host one cut, 8 host two, 1 hosts three).

The null, and why it is the whole point
---------------------------------------
A candidate generator is scored against a **uniform-random position inside the same
paragraph**, because paragraph length is the only thing a position-blind guesser needs to do
well: a 90-character paragraph admits no bad guess, and reporting raw displacement without
that control would read a short-paragraph sample as signal. Two nulls, matched to two
different questions, both exact (closed form over the L-1 interior integer positions -- no
Monte Carlo, no seed) for the per-cut facets:

* `nearest` -- displacement from gold to the *closest* Group C candidate in the paragraph,
  against **n uniform draws, n matched to the observed candidate count**. Count matching is
  not a refinement, it is the only fair comparison: nearest-of-9 beats nearest-of-1 on
  displacement for free, which is exactly the Group B pathology. Answers "is the candidate
  *set* informative?" -- it uses gold to pick within the set, so it is an upper bound on what
  a real selector could reach, not a usable accuracy.
* `ranked` -- displacement to the candidate the channel itself would pick (highest
  Levenshtein similarity, longer phrase as tie-break, mirroring `phrase_hits`'s own key),
  against **one** uniform draw. Answers "is the channel's own ranking usable?" -- this is the
  honest number, because production has no gold to pick with.

A third, joint facet (`assignment`) scores the monotone one-to-one assignment of a
paragraph's gold cuts to its candidates -- order-preserving, each candidate used once -- so a
multi-cut paragraph cannot score well by having every cut snap to the same candidate. Its
null draws n distinct interior positions and runs the same assignment, so it needs Monte
Carlo (seeded, `--reps`). It is identical to `nearest` on the 54 single-cut paragraphs.

Reported, per facet: mean/median displacement in characters and as a fraction of paragraph
length, the matched null's expectation, the ratio, and a one-sided exact sign test over the
per-cut wins. Also the per-cut null p-value (the probability the matched null does at least
as well) -- median 0.5 is the no-signal expectation.

**And the same sign test clustered by day, plus a day-level bootstrap CI on the ratio, because
the per-cut version overstates its own n and does so worst where it matters.** 33 days supply
the 73 cuts, one day supplies 7, and one paragraph hosts 3, so cuts are not independent. The
difference is decision-relevant rather than cosmetic: `ranked` -- the only facet that decides
anything -- is p=0.0082 per cut but **p=0.061 day-clustered**, i.e. marginal rather than
significant, while `nearest` survives clustering untouched (p=0.0030, ratio CI well below 1).
Quote the clustered figure when this measurement is cited.

**No tolerance-threshold metric at any granularity**, per the standing ban (docs/METRICS.md):
displacement is reported as a continuous quantity, never as precision/recall/F1 at a
character tolerance. The p <= 0.05 counts below are a significance threshold on the null
distribution, not a tolerance on displacement.

**Channel calibration, not a track target metric.** A pass here does not place anything and
is not a `separated` claim; it licenses P2's bounded annotation. A fail means placing anchors
is available but not accurate, and Track P stops rather than proceeding on availability alone.

Channels (`--channels`), and why the harness takes more than one
----------------------------------------------------------------
Everything above -- population, coordinate check, nulls, facets, clustering -- is fixed. The
*channel* is the only thing that varies, which is the point: the first run of this script
diagnosed the old channel rather than measuring Track P, and the rebuilt channel has to be
compared against it on the same 73 cuts or the comparison means nothing.

* `legacy` -- `build_combined_c_searcher` as production defines it: `s2_anchor_phrase_inventory`'s
  top 20 **unfiltered** plus `s4_opening_phrase_candidates` at `word_count >= 3`, so single-word
  phrases ("is", "synde", "ontfangen", "opt") are live members and fire at positions carrying no
  opening evidence at all.
* `legacy:3` -- the same channel with a >=3-word floor, the first-pass calibration idea that
  PLAN.md records and then rejects (`de heeren van` is three words and sails through it).
* `typed` -- `s6c_group_c_typed_formula_channel`: REPUBLIC's in-period frames for admissibility
  and class, our empirical n-grams admitted only where they attach to one, the participial
  construction as a pattern, `max_start_offset` honoured as a snap window, intake-before-decision
  ordering applied.
* `typed-no-ordering` / `typed-no-pattern` -- the same, with one component switched off, so a
  gain can be attributed to a mechanism instead of to the rebuild in general.

The two `legacy` arms are a regression check as well as a control: they must still report what
PLAN.md records (ranked ratio 1.01 at no floor, 0.78 at >=3 words; nearest 0.49; assignment 0.45),
and if they do not, the harness moved and no comparison here is readable.

Coordinates: gold's `(paragraph_stream_index, char_offset)` is a within-paragraph offset into
`boundary_gold_paragraph_axis`'s own paragraph text (`scripts.s6a_char_axis_evaluation`'s
composition convention). This script reads the live `axis_for_date` stream instead, because
the 3 hard-period days have no `boundary_gold_paragraph_axis` records, and asserts the two
agree paragraph-for-paragraph on the 30 original days that do -- a built-in regression check
on the coordinate assumption `s6c_group_c_boundary_existence_check.py` makes silently.

`1626-03-28` needs no exclusion here (unlike the sibling existence check): it carries no
`mid_paragraph` opening slot at all.

Scope: 63 paragraph-local phrase searches, not a corpus pass. No dataset write, no manifest
entry -- diagnostic only, same as `s6c_group_c_boundary_existence_check.py`.

Usage:
    PYTHONPATH=. uv run python -m scripts.s6c_group_c_interior_offset_calibration
    PYTHONPATH=. uv run python -m scripts.s6c_group_c_interior_offset_calibration \
        --channels legacy legacy:3 typed typed-no-ordering typed-no-pattern
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
from collections import Counter, defaultdict
from typing import Any

from data_io import load
from scripts.build_pathology_corpus import load_axis_indexes
from scripts.s4_corpus_paragraph_predictions import axis_for_date
from scripts.s6c_group_c_typed_formula_channel import Candidate, build_channel
from scripts.separated_accuracy_eval import OPENING_KINDS, is_located

GOLD_DATASET = "boundary_gold_sample"
HARD_GOLD_DATASET = "boundary_gold_hard_period_sample"
GOLD_AXIS_DATASET = "boundary_gold_paragraph_axis"

INTERIOR_UNIT = "mid_paragraph"
DEFAULT_REPS = 10_000


# --------------------------------------------------------------------------- exact nulls


def p_within(gold: int, distance: int, length: int) -> float:
    """`P(|U - gold| <= distance)` for `U` uniform over the interior positions `1..length-1`."""
    total = length - 1
    if total <= 0:
        return 1.0
    low = max(1, gold - distance)
    high = min(total, gold + distance)
    return max(0, high - low + 1) / total


def null_p_value(gold: int, observed: int, length: int, draws: int) -> float:
    """One-sided: the chance `draws` uniform positions put one at least as close as `observed`."""
    return 1.0 - (1.0 - p_within(gold, observed, length)) ** draws


def expected_null_displacement(gold: int, length: int, draws: int) -> float:
    """`E[min_i |U_i - gold|]` over `draws` uniform interior positions, summed exactly.

    `E[M] = sum_{k>=0} P(M > k)` for a non-negative integer variable, and
    `P(M > k) = (1 - P(|U - gold| <= k))^draws`.
    """
    furthest = max(gold - 1, (length - 1) - gold)
    return sum((1.0 - p_within(gold, k, length)) ** draws for k in range(max(0, furthest)))


# ------------------------------------------------------------------ monotone assignment


def assignment_cost(golds: list[int], candidates: list[int]) -> float | None:
    """Min total displacement over order-preserving one-to-one assignments, or None if short.

    Order-preserving because resolutions do not interleave: cut `i` precedes cut `i+1` in the
    text, so its candidate must too. One-to-one because two resolutions cannot open at the
    same character -- the failure mode a per-cut nearest-candidate score cannot see.
    """
    n_golds, n_candidates = len(golds), len(candidates)
    if n_candidates < n_golds:
        return None
    infinity = float("inf")
    # dp[i] = best cost for the first i golds using the candidates seen so far.
    dp = [0.0] + [infinity] * n_golds
    for candidate in candidates:
        for i in range(n_golds, 0, -1):
            if dp[i - 1] < infinity:
                dp[i] = min(dp[i], dp[i - 1] + abs(candidate - golds[i - 1]))
    return dp[n_golds] if dp[n_golds] < infinity else None


def null_assignment_cost(
    golds: list[int], length: int, draws: int, reps: int, rng: random.Random
) -> float | None:
    """Mean monotone-assignment cost when the `draws` candidates are uniform interior positions."""
    population = range(1, length)
    if draws > len(population) or draws < len(golds):
        return None
    total = 0.0
    for _ in range(reps):
        sample = sorted(rng.sample(population, draws))
        cost = assignment_cost(golds, sample)
        if cost is None:
            return None
        total += cost
    return total / reps


# --------------------------------------------------------------------------- collection


def interior_slots(day: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        slot
        for slot in day.get("boundaries") or []
        if slot.get("unit") == INTERIOR_UNIT and slot.get("kind") in OPENING_KINDS
    ]


def load_gold_days() -> list[tuple[str, str, dict[str, Any]]]:
    """`(source, date, day)` across both gold samples; a date in both would be double-scored."""
    rows: list[tuple[str, str, dict[str, Any]]] = []
    seen: dict[str, str] = {}
    for source in (GOLD_DATASET, HARD_GOLD_DATASET):
        for day in load(source)["days"]:
            date = str(day["date"])
            if date in seen:
                raise ValueError(f"{date} appears in both {seen[date]} and {source}")
            seen[date] = source
            rows.append((source, date, day))
    return rows


def gold_axis_by_date() -> dict[str, list[dict[str, Any]]]:
    axis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in load(GOLD_AXIS_DATASET):
        axis[str(record["date"])].append(record)
    return axis


def collect_cuts(
    channel: Any,
    axis_indexes: tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, str]],
    gold_axis: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, int]]:
    """One row per gold interior opening slot, with its paragraph's Group C candidate set."""
    axis_by_date, axis_by_session, session_by_date = axis_indexes
    tallies: Counter[str] = Counter()
    coordinate_check = {"days_with_gold_axis": 0, "days_axis_identical": 0}
    rows: list[dict[str, Any]] = []
    candidate_cache: dict[tuple[str, int], list[Candidate]] = {}

    for source, date, day in load_gold_days():
        slots = interior_slots(day)
        if not slots:
            continue
        tallies["days"] += 1
        axis = axis_for_date(date, axis_by_date, axis_by_session, session_by_date)

        reference = gold_axis.get(date)
        if reference:
            coordinate_check["days_with_gold_axis"] += 1
            identical = [record["text"] for record in axis] == [
                record["text"] for record in reference
            ]
            coordinate_check["days_axis_identical"] += int(identical)
            if not identical:
                tallies["days_axis_mismatch"] += 1
                tallies["slots_dropped_axis_mismatch"] += len(slots)
                continue

        for slot in slots:
            tallies["slots"] += 1
            if not is_located(slot):
                tallies["slots_unlocated"] += 1
                continue
            index = int(slot["paragraph_stream_index"])
            if not 0 <= index < len(axis):
                tallies["slots_out_of_axis"] += 1
                continue
            text = axis[index]["text"]
            gold = int(slot["char_offset"])
            if gold <= 0:
                # A mid_paragraph marker on the paragraph's first character: the same point a
                # paragraph_boundary cut on index-1 describes, with no interior cut to find.
                tallies["slots_degenerate_offset_zero"] += 1
                continue
            if gold >= len(text):
                tallies["slots_offset_past_paragraph"] += 1
                continue

            key = (date, index)
            if key not in candidate_cache:
                candidate_cache[key] = channel.candidates(axis[index]["axis_id"], text)
            candidates = candidate_cache[key]
            rows.append(
                {
                    "source": source,
                    "date": date,
                    "paragraph_stream_index": index,
                    "paragraph_chars": len(text),
                    "gold_offset": gold,
                    "candidates": candidates,
                }
            )
            tallies["cuts_interior"] += 1
            tallies["cuts_with_candidate" if candidates else "cuts_without_candidate"] += 1
    return rows, tallies, coordinate_check


# ---------------------------------------------------------------------------- reporting


def sign_test(wins: int, losses: int) -> float:
    """One-sided exact binomial p for `wins` of `wins + losses` under a fair coin."""
    trials = wins + losses
    if trials == 0:
        return 1.0
    tail = sum(math.comb(trials, k) for k in range(wins, trials + 1))
    return tail / (2**trials)


def clustered(scores: list[dict[str, Any]], reps: int, seed: int) -> str:
    """Day-clustered sign test and day-level bootstrap CI on the pooled ratio.

    Cuts are NOT independent: 33 days supply 73 of them, one day supplies 7, and a single
    paragraph can host 3. A per-cut sign test therefore overstates its own n, and it does so
    worst on the facet closest to the significance boundary -- which on this measurement is
    `ranked`, the only facet that decides anything (per-cut p=0.0082, day-clustered p=0.061).
    One vote per day, plus a bootstrap that resamples whole days, is the honest version.
    """
    per_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for score in scores:
        per_day[score["date"]].append(score)
    wins = losses = 0
    for day_scores in per_day.values():
        observed = statistics.fmean(score["observed"] for score in day_scores)
        expected = statistics.fmean(score["expected"] for score in day_scores)
        if observed < expected:
            wins += 1
        elif observed > expected:
            losses += 1

    dates = list(per_day)
    rng = random.Random(seed)
    ratios: list[float] = []
    for _ in range(reps):
        resampled = [score for _ in dates for score in per_day[rng.choice(dates)]]
        denominator = statistics.fmean(score["expected"] for score in resampled)
        if denominator:
            ratios.append(statistics.fmean(score["observed"] for score in resampled) / denominator)
    if not ratios:
        return f"day-clustered {wins}/{wins + losses} days (sign-test p={sign_test(wins, losses):.4f})"
    ratios.sort()
    low = ratios[int(0.025 * len(ratios))]
    high = ratios[min(len(ratios) - 1, int(0.975 * len(ratios)))]
    return (
        f"day-clustered {wins}/{len(dates)} days (sign-test p={sign_test(wins, losses):.4f}), "
        f"ratio 95% CI [{low:.3f}, {high:.3f}] over {len(dates)} days"
    )


def describe(label: str, scores: list[dict[str, Any]], reps: int, seed: int) -> None:
    if not scores:
        print(f"  {label:11} -- no scoreable cuts")
        return
    observed = [score["observed"] for score in scores]
    expected = [score["expected"] for score in scores]
    normalised = [score["observed"] / score["paragraph_chars"] for score in scores]
    normalised_null = [score["expected"] / score["paragraph_chars"] for score in scores]
    wins = sum(1 for score in scores if score["observed"] < score["expected"])
    losses = sum(1 for score in scores if score["observed"] > score["expected"])
    ratio = statistics.fmean(observed) / statistics.fmean(expected) if statistics.fmean(expected) else float("nan")
    print(
        f"  {label:11} n={len(scores):3}  "
        f"mean {statistics.fmean(observed):7.1f} chars vs null {statistics.fmean(expected):7.1f}  "
        f"ratio {ratio:5.2f}  "
        f"median {statistics.median(observed):7.1f} vs {statistics.median(expected):7.1f}"
    )
    ordered = sorted(observed)
    quantiles = [ordered[min(len(ordered) - 1, int(q * len(ordered)))] for q in (0.25, 0.75, 0.9)]
    # Exact character agreement, the char-axis analogue of the project's own exact
    # start-paragraph agreement -- a point on the displacement distribution, not a tolerance band.
    print(
        f"  {'':11} observed displacement p25/p75/p90 "
        f"{quantiles[0]:.0f} / {quantiles[1]:.0f} / {quantiles[2]:.0f} chars; "
        f"exact (0 chars) on {sum(1 for value in observed if value == 0)}/{len(observed)}"
    )
    print(
        f"  {'':11} normalised mean {statistics.fmean(normalised):6.3f} of paragraph "
        f"vs null {statistics.fmean(normalised_null):6.3f}  |  "
        f"beats own null {wins}/{wins + losses} per cut (sign-test p={sign_test(wins, losses):.4f})"
    )
    print(f"  {'':11} {clustered(scores, reps, seed)}")
    p_values = [score["p_value"] for score in scores if score.get("p_value") is not None]
    if p_values:
        print(
            f"  {'':11} null p-value median {statistics.median(p_values):.3f} "
            f"(0.5 = no signal), p<=0.05 on {sum(1 for p in p_values if p <= 0.05)}/{len(p_values)}, "
            f"p<=0.10 on {sum(1 for p in p_values if p <= 0.10)}/{len(p_values)}"
        )


def score_facets(
    rows: list[dict[str, Any]], reps: int, seed: int, channel: Any
) -> dict[str, list[dict[str, Any]]]:
    """Per-cut `nearest` / `ranked` scores and per-paragraph `assignment` scores, flattened.

    Every score carries its `date`, because the day is the clustering unit `clustered` needs.
    """
    rng = random.Random(seed)
    facets: dict[str, list[dict[str, Any]]] = {"nearest": [], "ranked": [], "assignment": []}

    for row in rows:
        candidates = row["candidates"]
        if not candidates:
            continue
        gold, length = row["gold_offset"], row["paragraph_chars"]
        offsets = [candidate.offset for candidate in candidates]
        draws = len(offsets)

        nearest = min(abs(offset - gold) for offset in offsets)
        facets["nearest"].append(
            {
                "date": row["date"],
                "observed": float(nearest),
                "expected": expected_null_displacement(gold, length, draws),
                "paragraph_chars": float(length),
                "p_value": null_p_value(gold, nearest, length, draws),
            }
        )

        picked = abs(channel.pick(candidates).offset - gold)
        facets["ranked"].append(
            {
                "date": row["date"],
                "observed": float(picked),
                "expected": expected_null_displacement(gold, length, 1),
                "paragraph_chars": float(length),
                "p_value": null_p_value(gold, picked, length, 1),
            }
        )

    by_paragraph: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_paragraph[(row["date"], row["paragraph_stream_index"])].append(row)
    for group in by_paragraph.values():
        candidates = group[0]["candidates"]
        if not candidates:
            continue
        length = group[0]["paragraph_chars"]
        golds = sorted(row["gold_offset"] for row in group)
        offsets = [candidate.offset for candidate in candidates]
        observed = assignment_cost(golds, offsets)
        if observed is None:
            continue  # fewer candidates than cuts: an availability shortfall, not an error
        expected = null_assignment_cost(golds, length, len(offsets), reps, rng)
        if expected is None:
            continue
        facets["assignment"].append(
            {
                "date": group[0]["date"],
                "observed": observed / len(golds),
                "expected": expected / len(golds),
                "paragraph_chars": float(length),
                "p_value": None,
            }
        )
    return facets


def report(label: str, rows: list[dict[str, Any]], reps: int, seed: int, channel: Any) -> None:
    scoreable = [row for row in rows if row["candidates"]]
    if not rows:
        print(f"\n{label}: no interior cuts")
        return
    counts = [len(row["candidates"]) for row in rows]
    cuts_needed: Counter[tuple[str, int]] = Counter(
        (row["date"], row["paragraph_stream_index"]) for row in rows
    )
    supply = {
        (row["date"], row["paragraph_stream_index"]): len(row["candidates"]) for row in rows
    }
    shortfall = sum(1 for key, needed in cuts_needed.items() if supply[key] < needed)
    print(f"\n{label}")
    print(
        f"  availability: {len(scoreable)}/{len(rows)} cuts have >=1 interior candidate "
        f"({len(scoreable) / len(rows):.1%}); {len(cuts_needed)} host paragraphs, "
        f"{shortfall} with fewer candidates than cuts"
    )
    print(
        f"  candidates per cut: median {statistics.median(counts):.1f}, "
        f"mean {statistics.fmean(counts):.2f}, max {max(counts)}"
    )
    facets = score_facets(rows, reps, seed, channel)
    describe("nearest", facets["nearest"], reps, seed)
    describe("ranked", facets["ranked"], reps, seed)
    describe("assignment", facets["assignment"], reps, seed)
    # Selector headroom: how often the channel's own ranking picks the candidate gold agrees
    # with most. The nearest/ranked gap is entirely this, so it bounds what a better selector
    # could buy without a single new candidate.
    agree = sum(
        1
        for nearest, ranked in zip(facets["nearest"], facets["ranked"])
        if nearest["observed"] == ranked["observed"]
    )
    print(
        f"  selector    the channel's own ranking picks its closest-to-gold candidate "
        f"{agree}/{len(facets['nearest'])} times"
    )


def parse_channel(spec: str) -> tuple[str, int]:
    """`name` or `name:min_words`; the floor applies to the legacy channel only."""
    name, _, floor = spec.partition(":")
    return name, int(floor) if floor else 1


def class_mix(rows: list[dict[str, Any]]) -> str:
    """Candidate formula classes, for the typed channel. `unclassified` is the legacy channel."""
    mix = Counter(
        candidate.formula_class for row in rows for candidate in row["candidates"]
    )
    return ", ".join(f"{name} {count}" for name, count in sorted(mix.items()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="P1: calibrate Group C interior candidates against gold mid-paragraph cuts."
    )
    parser.add_argument(
        "--channels",
        nargs="+",
        default=["legacy", "legacy:3", "typed"],
        help=(
            "channels to report on the same fixed population: legacy[:min_words], typed, "
            "typed-no-ordering, typed-no-pattern. The legacy arms are the control and the "
            "harness regression check."
        ),
    )
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS, help="assignment-null draws")
    parser.add_argument("--seed", type=int, default=20261005, help="assignment-null seed")
    args = parser.parse_args()

    axis_indexes = load_axis_indexes()
    gold_axis = gold_axis_by_date()

    for spec in args.channels:
        name, min_words = parse_channel(spec)
        channel = build_channel(name, min_words)
        rows, tallies, coordinate_check = collect_cuts(channel, axis_indexes, gold_axis)
        print("\n" + "=" * 100)
        print(f"P1 -- interior offset calibration: {spec} -- {channel.label}")
        print("=" * 100)
        print(
            f"\ngold population: {tallies['days']} days, {tallies['slots']} mid_paragraph opening "
            f"slots -> {tallies['cuts_interior']} interior cuts "
            f"(held out: {tallies['slots_degenerate_offset_zero']} at char_offset 0, "
            f"{tallies['slots_unlocated']} unlocated, {tallies['slots_out_of_axis']} outside the axis, "
            f"{tallies['slots_offset_past_paragraph']} past the paragraph end, "
            f"{tallies['slots_dropped_axis_mismatch']} on axis-mismatched days)"
        )
        print(
            f"coordinate check: live axis identical to {GOLD_AXIS_DATASET} on "
            f"{coordinate_check['days_axis_identical']}/{coordinate_check['days_with_gold_axis']} "
            f"days that have gold-axis records"
        )
        print(f"candidate classes: {class_mix(rows) or 'none'}")
        report("ALL", rows, args.reps, args.seed, channel)
        for source in (GOLD_DATASET, HARD_GOLD_DATASET):
            subset = [row for row in rows if row["source"] == source]
            if subset:
                report(source, subset, args.reps, args.seed, channel)


if __name__ == "__main__":
    main()

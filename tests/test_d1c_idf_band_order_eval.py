import pandas as pd

from scripts.d1c_idf_band_order_eval import (
    MIN_MARGIN_OVER_CONTROL,
    MIN_PAIRS_PER_BAND,
    aggregate,
    band_edges,
    band_of,
    deranged_indices,
    gate_verdict,
    name_frequencies,
    pair_tau,
    shared_mentions,
    summarize_taus,
)


def test_name_frequencies_counts_evidence_rows_and_drops_short_names():
    overlap = pd.DataFrame({"name": ["Holland", "holland", " HOLLAND ", "Uyt", None, "Zeeland"]})

    frequencies = name_frequencies(overlap)

    # Case and surrounding whitespace are the same name; "Uyt" is below the 4-character floor.
    assert frequencies == {"holland": 3, "zeeland": 1}


def test_shared_mentions_returns_first_offsets_on_both_sides():
    enriched = "Gedeputeerden van Holland en Zeeland"
    flat = "de heeren Gedeputeerden der provincie Zeeland ende Holland"

    mentions = shared_mentions(enriched, flat, ["holland", "zeeland", "utrecht"])

    assert mentions == [("holland", 18, 51), ("zeeland", 29, 38)]


def test_shared_mentions_requires_presence_on_both_sides():
    assert shared_mentions("Holland alone", "Zeeland alone", ["holland", "zeeland"]) == []


def test_band_edges_and_band_of_split_mentions_into_terciles():
    # Mention-weighted: the frequent name occupies most of the observed mentions.
    frequencies = [1, 1, 1, 5, 5, 5, 400, 400, 400]

    edges = band_edges(frequencies)

    assert band_of(400, edges) == "common"
    assert band_of(5, edges) == "mid"
    assert band_of(1, edges) == "rare"


def test_band_of_never_degenerates_to_one_band_on_a_skewed_distribution():
    # The defect this script exists to correct: a fixed IDF floor put every name in one band.
    frequencies = [1356, 1219, 727, 634, 604, 581, 502, 411, 373, 365, 2, 1]
    edges = band_edges(frequencies)

    assigned = {band_of(frequency, edges) for frequency in frequencies}

    assert assigned == {"common", "mid", "rare"}


def test_pair_tau_needs_two_mentions():
    assert pair_tau([]) is None
    assert pair_tau([("holland", 0, 10)]) is None


def test_pair_tau_is_one_for_agreeing_order_and_minus_one_for_reversal():
    agreeing = [("holland", 0, 5), ("zeeland", 10, 20), ("utrecht", 20, 40)]
    reversed_order = [("holland", 0, 40), ("zeeland", 10, 20), ("utrecht", 20, 5)]

    assert pair_tau(agreeing) == 1.0
    assert pair_tau(reversed_order) == -1.0


def test_summarize_taus_reports_the_high_concordance_share():
    stats = summarize_taus([1.0, 1.0, 0.8, 0.2])

    assert stats["pairs"] == 4
    assert stats["mean_tau"] == 0.75
    assert stats["share_tau_ge_0.8"] == 0.75


def test_summarize_taus_on_no_pairs_reports_none_rather_than_zero():
    # An empty band must not read as "measured, and the answer is zero" -- that was the
    # original D1c's failure mode (tau_low_idf = 0.0 on n = 0 pairs).
    assert summarize_taus([]) == {"pairs": 0, "mean_tau": None, "median_tau": None, "share_tau_ge_0.8": None}


def _band(pairs: int, mean_tau: float) -> dict[str, object]:
    return {"pairs": pairs, "mean_tau": mean_tau, "median_tau": mean_tau, "share_tau_ge_0.8": 0.5}


def test_gate_verdict_passes_when_common_order_is_comparable_to_rare_and_no_control_given():
    verdict, _ = gate_verdict({"common": _band(500, 0.62), "rare": _band(300, 0.65)})

    assert verdict == "pass"


def test_gate_verdict_fails_when_common_order_is_near_random():
    verdict, reason = gate_verdict({"common": _band(500, 0.05), "rare": _band(300, 0.65)})

    assert verdict == "fail"
    assert "0.05" in reason


def test_gate_verdict_is_inconclusive_between_the_thresholds():
    verdict, _ = gate_verdict({"common": _band(500, 0.30), "rare": _band(300, 0.65)})

    assert verdict == "inconclusive"


def test_gate_verdict_reports_no_data_rather_than_a_result_on_a_thin_band():
    verdict, reason = gate_verdict(
        {"common": _band(MIN_PAIRS_PER_BAND - 1, 0.9), "rare": _band(300, 0.65)}
    )

    assert verdict == "no_data"
    assert str(MIN_PAIRS_PER_BAND) in reason


def test_gate_verdict_passes_when_common_band_clears_the_mismatched_pair_control():
    real = {"common": _band(500, 0.80), "rare": _band(300, 0.60)}
    control = {"common": _band(200, 0.10)}

    verdict, reason = gate_verdict(real, control)

    assert verdict == "pass"
    assert "control" in reason


def test_gate_verdict_flags_convention_not_alignment_when_control_matches_the_real_tau():
    # The defect this control exists to catch: a high tau that a wrong pairing reproduces too.
    real = {"common": _band(500, 0.80), "rare": _band(300, 0.60)}
    control = {"common": _band(200, 0.75)}

    verdict, reason = gate_verdict(real, control)

    assert verdict == "convention_not_alignment"
    assert "0.05" in reason  # margin = 0.80 - 0.75


def test_gate_verdict_reports_no_data_when_the_control_band_is_too_thin():
    real = {"common": _band(500, 0.80), "rare": _band(300, 0.60)}
    control = {"common": _band(MIN_PAIRS_PER_BAND - 1, 0.10)}

    verdict, reason = gate_verdict(real, control)

    assert verdict == "no_data"
    assert "control" in reason


def test_min_margin_over_control_is_a_real_gap_not_zero():
    # A regression guard: MIN_MARGIN_OVER_CONTROL must actually discriminate real order agreement
    # from a control that ties it, or the convention_not_alignment branch above never fires.
    assert MIN_MARGIN_OVER_CONTROL > 0


def test_deranged_indices_has_no_fixed_point():
    indices = deranged_indices(7)

    assert len(indices) == 7
    assert sorted(indices) == list(range(7))
    assert all(index != value for index, value in enumerate(indices))


def test_deranged_indices_handles_small_counts():
    assert deranged_indices(0) == []
    assert deranged_indices(1) == []


def test_aggregate_reports_per_band_taus_and_scarcity():
    mentions_per_pair = [
        [("holland", 0, 5), ("zeeland", 10, 20)],
        [("utrecht", 0, 100)],  # single mention: cannot carry a tau
        [],
    ]
    frequencies = {"holland": 900, "zeeland": 900, "utrecht": 2}
    edges = (10.0, 100.0)  # both mentions must land in "common" for this test
    assert band_of(900, edges) == "common"
    assert band_of(2, edges) == "rare"

    result = aggregate(mentions_per_pair, frequencies, edges)

    assert result["whole_pair"]["pairs"] == 1
    assert result["by_band"]["common"]["pairs"] == 1
    assert result["scarcity"]["pairs"] == 3
    assert result["scarcity"]["pairs_with_multi_mentions"] == 1
    assert len(result["per_pair"]) == 3

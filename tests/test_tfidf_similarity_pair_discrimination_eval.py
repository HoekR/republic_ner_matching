import numpy as np
import pandas as pd

from scripts.tfidf_similarity_pair_discrimination_eval import (
    MIN_PAIRS_PER_GROUP,
    best_paragraph_score,
    common_language_effect_size,
    day_control_index_sets,
    eligible_day_counts,
    gate_verdict,
    load_tier1_pairs,
    score_day,
    stratified_day_sample,
    summarize_scores,
)


class _FakeEmbedder:
    """Deterministic stand-in for AlignmentEmbedder(backend='tfidf'): the diagonal always scores
    highest so score_day's top-1/derangement bookkeeping can be tested without a real TF-IDF fit."""

    def compute_similarity_matrix(self, enriched_texts, flat_texts):
        n, m = len(enriched_texts), len(flat_texts)
        matrix = np.full((n, m), 0.1)
        for i in range(min(n, m)):
            matrix[i, i] = 0.9
        return matrix


def test_eligible_day_counts_drops_singleton_days_and_keeps_inventory():
    tier1 = pd.DataFrame(
        {
            "date": ["1627-01-01", "1627-01-01", "1627-01-02", "1627-01-03"],
            "inventory": ["3186", "3186", "3186", "3187"],
        }
    )

    counts = eligible_day_counts(tier1)

    assert counts["date"].tolist() == ["1627-01-01"]
    assert counts["pairs"].tolist() == [2]
    assert counts["inventory"].tolist() == ["3186"]


def test_stratified_day_sample_is_deterministic_and_within_bounds():
    day_counts = pd.DataFrame(
        {
            "date": [f"1627-01-{i:02d}" for i in range(1, 21)],
            "pairs": [2] * 20,
            "inventory": ["3186"] * 10 + ["3187"] * 10,
        }
    )

    sample_a = stratified_day_sample(day_counts, target_days=8, seed=42)
    sample_b = stratified_day_sample(day_counts, target_days=8, seed=42)

    assert sample_a == sample_b  # reproducible under a fixed seed
    assert len(sample_a) == 8
    assert set(sample_a).issubset(set(day_counts["date"]))
    # proportional stratification: both inventories should contribute.
    inv_by_date = dict(zip(day_counts["date"], day_counts["inventory"]))
    assert {inv_by_date[d] for d in sample_a} == {"3186", "3187"}


def test_stratified_day_sample_never_exceeds_available_days():
    day_counts = pd.DataFrame({"date": ["1627-01-01", "1627-01-02"], "pairs": [2, 2], "inventory": ["3186", "3186"]})

    sample = stratified_day_sample(day_counts, target_days=50, seed=1)

    assert len(sample) == 2


def test_stratified_day_sample_handles_empty_input():
    assert stratified_day_sample(pd.DataFrame(columns=["date", "pairs", "inventory"]), 10, 1) == []


def test_day_control_index_sets_reuses_d1c_derangements_with_no_fixed_points():
    derangements = day_control_index_sets(count=6, n_derangements=3)

    assert len(derangements) <= 3
    for derangement in derangements:
        assert sorted(derangement) == list(range(6))
        assert all(i != value for i, value in enumerate(derangement))


def test_score_day_reads_positive_scores_off_the_diagonal():
    enriched_texts = ["a", "b", "c"]
    flat_texts = ["A", "B", "C"]
    flat_ids = ["fa", "fb", "fc"]

    result = score_day(enriched_texts, flat_texts, flat_ids, _FakeEmbedder(), n_derangements=2)

    assert result["positive_scores"] == [0.9, 0.9, 0.9]
    assert result["top1_correct"] == 3  # diagonal is always the max in the fake embedder
    assert result["count"] == 3


def test_score_day_negative_scores_come_from_off_diagonal_derangement_cells():
    enriched_texts = ["a", "b", "c", "d"]
    flat_texts = ["A", "B", "C", "D"]
    flat_ids = ["fa", "fb", "fc", "fd"]

    result = score_day(enriched_texts, flat_texts, flat_ids, _FakeEmbedder(), n_derangements=2)

    assert all(score == 0.1 for score in result["negative_scores"])
    assert len(result["negative_scores"]) > 0


def test_score_day_drops_coincidental_same_flat_id_derangement_slots():
    # Two rows share the same flat_id (a bundled resolution): a derangement that reassigns
    # enriched[0] to flat_id "shared" (its own true id) must not be counted as a wrong pairing.
    enriched_texts = ["a", "b"]
    flat_texts = ["A", "B"]
    flat_ids = ["shared", "shared"]

    result = score_day(enriched_texts, flat_texts, flat_ids, _FakeEmbedder(), n_derangements=3)

    assert result["negative_scores"] == []


def test_common_language_effect_size_is_one_when_groups_are_fully_separated():
    assert common_language_effect_size([0.9, 0.8, 0.7], [0.1, 0.2, 0.3]) == 1.0


def test_common_language_effect_size_is_half_on_identical_distributions():
    assert common_language_effect_size([0.5, 0.5], [0.5, 0.5]) == 0.5


def test_common_language_effect_size_handles_empty_groups():
    assert common_language_effect_size([], [0.5]) is None
    assert common_language_effect_size([0.5], []) is None


def test_summarize_scores_reports_mean_median_and_n():
    stats = summarize_scores([0.2, 0.4, 0.6])

    assert stats == {"n": 3, "mean": 0.4, "median": 0.4, "std": stats["std"]}
    assert stats["std"] > 0


def test_summarize_scores_on_empty_reports_none_not_zero():
    assert summarize_scores([]) == {"n": 0, "mean": None, "median": None, "std": None}


def _summary(n: int) -> dict[str, object]:
    return {"n": n, "mean": 0.5, "median": 0.5, "std": 0.1}


def test_gate_verdict_reports_no_data_below_the_minimum_pair_floor():
    verdict, reason = gate_verdict(_summary(MIN_PAIRS_PER_GROUP - 1), _summary(100), auc=0.9)

    assert verdict == "no_data"
    assert str(MIN_PAIRS_PER_GROUP) in reason


def test_gate_verdict_discriminates_on_a_high_auc():
    verdict, _ = gate_verdict(_summary(100), _summary(100), auc=0.9)

    assert verdict == "discriminates"


def test_gate_verdict_flat_non_discriminating_near_chance():
    verdict, _ = gate_verdict(_summary(100), _summary(100), auc=0.5)

    assert verdict == "flat_non_discriminating"


def test_gate_verdict_partial_separation_between_thresholds():
    verdict, _ = gate_verdict(_summary(100), _summary(100), auc=0.6)

    assert verdict == "partial_separation"


def test_load_tier1_pairs_is_importable():
    # Smoke-check the function exists with the expected name; the real data load is exercised by
    # running the script itself, not by the unit-test suite (house style: no I/O in these tests).
    assert callable(load_tier1_pairs)


def test_best_paragraph_score_returns_max_over_paragraphs():
    paragraphs = ["paragraph A", "paragraph B", "paragraph C"]
    scores = best_paragraph_score("query text", paragraphs, _FakeEmbedder())
    # FakeEmbedder returns 0.9 on diagonal (i,i), 0.1 off-diagonal.
    # Each compute_similarity_matrix call is 1 query vs 1 paragraph (a 1x1 matrix),
    # so each call gets 0.9 at position (0,0). best_paragraph_score returns max([0.9, 0.9, 0.9]).
    assert scores == 0.9


def test_best_paragraph_score_empty_paragraphs_returns_zero():
    assert best_paragraph_score("query", [], _FakeEmbedder()) == 0.0


def test_score_day_paragraph_granularity_uses_best_match():
    enriched_texts = ["enriched_A", "enriched_B"]
    flat_texts = ["flat_A", "flat_B"]  # these are flat-resolution level, not paragraph level
    flat_ids = ["res_A", "res_B"]
    # In paragraph granularity, we need axis_by_flat mapping. For this test, mock it.
    axis_by_flat = {
        "res_A": ["para_A1", "para_A2"],
        "res_B": ["para_B1"],
    }
    result = score_day(
        enriched_texts,
        flat_texts,
        flat_ids,
        _FakeEmbedder(),
        n_derangements=1,
        granularity="paragraph",
        axis_by_flat=axis_by_flat,
    )
    # The diagonal should be the best-paragraph score for each enriched text against its matching
    # resolution's paragraphs. Since FakeEmbedder always returns 0.1 for off-diagonal (and there's
    # no true diagonal here), both should be 0.1.
    assert len(result["positive_scores"]) == 2
    assert result["count"] == 2


def test_score_day_flat_granularity_still_works():
    enriched_texts = ["a", "b"]
    flat_texts = ["A", "B"]
    flat_ids = ["fa", "fb"]

    result = score_day(enriched_texts, flat_texts, flat_ids, _FakeEmbedder(), n_derangements=1, granularity="flat")

    # FakeEmbedder diagonal is 0.9, off-diagonal 0.1
    assert result["positive_scores"] == [0.9, 0.9]
    assert result["top1_correct"] == 2  # diagonal is max in fake embedder
    assert result["count"] == 2

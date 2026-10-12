"""Unit tests for corpus-wide train/test resolution fingerprint (no data load)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sequence_graph.resolution_fingerprint_eval import (
    FINGERPRINT_OVERLAP_SCALE,
    TrainFittedTfidfFingerprint,
    blend_entity_fingerprint_scorer,
    build_fingerprint_scorer,
    score_day_matrix,
    train_test_day_split,
)


def test_train_test_day_split_stratified_and_deterministic():
    day_counts = pd.DataFrame(
        {
            "date": [f"1627-01-{i:02d}" for i in range(1, 21)],
            "pairs": [3] * 20,
            "inventory": ["3186"] * 10 + ["3187"] * 10,
        }
    )
    train_a, test_a = train_test_day_split(day_counts, train_fraction=0.7, seed=7)
    train_b, test_b = train_test_day_split(day_counts, train_fraction=0.7, seed=7)
    assert train_a == train_b and test_a == test_b
    assert set(train_a).isdisjoint(test_a)
    assert set(train_a) | set(test_a) == set(day_counts["date"])
    inv = dict(zip(day_counts["date"], day_counts["inventory"]))
    assert {inv[d] for d in train_a} == {"3186", "3187"}
    assert {inv[d] for d in test_a} == {"3186", "3187"}


def test_train_fitted_fingerprint_diagonal_beats_off_diagonal():
    fp = TrainFittedTfidfFingerprint()
    # Repeated tokens so min_df=2 keeps features.
    train = [
        "resolutie holland amsterdam koopman koopman",
        "resolutie zeeland middelburg schip schip",
        "resolutie utrecht sticht raad raad",
        "resolutie friesland leeuwarden gedeputeerde gedeputeerde",
    ]
    fp.fit(train)
    enr = ["holland amsterdam koopman"]
    flt = ["holland amsterdam koopman", "zeeland middelburg schip"]
    mat = fp.similarity_matrix(enr, flt)
    assert mat.shape == (1, 2)
    assert float(mat[0, 0]) > float(mat[0, 1])


def test_score_day_matrix_top1_and_negatives():
    matrix = np.array(
        [
            [0.9, 0.1, 0.2],
            [0.2, 0.8, 0.1],
            [0.1, 0.2, 0.7],
        ],
        dtype=float,
    )
    scored = score_day_matrix(matrix, ["a", "b", "c"], n_derangements=2)
    assert scored["top1_correct"] == 3
    assert scored["count"] == 3
    assert len(scored["positive_scores"]) == 3
    assert scored["negative_scores"]  # derangements yield off-diagonals
    assert max(scored["positive_scores"]) >= max(scored["negative_scores"])


def test_fingerprint_scorer_scales_into_cost_model_units():
    fp = TrainFittedTfidfFingerprint()
    fp.fit([
        "resolutie holland amsterdam koopman",
        "resolutie zeeland middelburg schip",
    ])
    scorer = build_fingerprint_scorer(
        fp,
        enriched_text_by_volgnr={"v1": "holland amsterdam koopman"},
        flat_text_by_id={
            "f1": "holland amsterdam koopman",
            "f2": "zeeland middelburg schip",
        },
        scale=FINGERPRINT_OVERLAP_SCALE,
    )
    assert scorer("v1", "f1") > 1.0  # beats gap under CostModel base=2
    assert scorer("v1", "f1") > scorer("v1", "f2")
    blended = blend_entity_fingerprint_scorer(lambda _v, _f: 3.0, scorer)
    assert blended("v1", "f1") == 3.0 + scorer("v1", "f1")

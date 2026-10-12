"""Resolution fingerprint: train/test split on known ALIGNED_TO-style pairs (isolated).

Corpus-wide (main series), **not** scoped to the late-Aug hard-recalibration window.
Positive pairs = ``alignment_1626_1630`` ``tier1_anchor`` (known-correct enriched↔flat).
Split is by **calendar day** (stratified by inventory): fit the fingerprint on train-day
texts only, evaluate top-1 / AUC on held-out test days with within-day derangement
negatives.

This differs from ``scripts.tfidf_similarity_pair_discrimination_eval``, which fits
TF-IDF **per day** (no train/test). Here the vectorizer never sees test-day text at fit.

Channels reported:
  * ``tfidf_fingerprint`` — word(1–2) + char_wb(3–5) TF-IDF cosine (train-fit)
  * ``entity_overlap`` — existing graph entity scorer (no fit; same split for compare)

Usage:
    uv run python -m sequence_graph.resolution_fingerprint_eval --write
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from data_io import save_semi_structured
from scripts.corpus_scope import is_main_series, scope_meta
from scripts.d1c_idf_band_order_eval import control_offsets, deranged_indices
from scripts.tfidf_similarity_pair_discrimination_eval import (
    common_language_effect_size,
    eligible_day_counts,
    load_tier1_pairs,
    summarize_scores,
)
from sequence_graph.align import build_entity_overlap_scorer

OUTPUT_DATASET = "resolution_fingerprint_train_test"
RANDOM_SEED = 20261012
TRAIN_FRACTION = 0.7
MIN_DAY_PAIRS = 2
CONTROL_DERANGEMENTS = 3
TEST_DAY_CAP = 200  # evaluate at most this many test days (cost); train uses all train days for fit

# Map cosine [0,1] into CostModel overlap units so a held-out positive (~0.17) beats
# gap_cost=1 under base_match=2 (need overlap ≳ 1), while a derangement (~0.04) does not.
# Fixed from train/test fingerprint eval means before wiring into hard_recalibrate.
FINGERPRINT_OVERLAP_SCALE = 15.0


class TrainFittedTfidfFingerprint:
    """Word + char TF-IDF fitted once on a train corpus; cosine on any later texts."""

    def __init__(self) -> None:
        # min_df=1 matches AlignmentEmbedder; train corpus is large enough that hapax
        # are rare relative to signal. Fit never sees test-day texts.
        self.word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)
        self.char = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1
        )
        self._fitted = False

    def fit(self, texts: Sequence[str]) -> None:
        corpus = [t.strip() if t and str(t).strip() else " " for t in texts]
        if len(corpus) < 2:
            raise ValueError("need >= 2 train texts to fit fingerprint")
        self.word.fit(corpus)
        self.char.fit(corpus)
        self._fitted = True

    def similarity_matrix(
        self, enriched_texts: Sequence[str], flat_texts: Sequence[str]
    ) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("fit() before similarity_matrix()")
        enr = [t.strip() if t and str(t).strip() else " " for t in enriched_texts]
        flt = [t.strip() if t and str(t).strip() else " " for t in flat_texts]
        if not enr or not flt:
            return np.zeros((len(enr), len(flt)), dtype=np.float32)
        sim_w = cosine_similarity(self.word.transform(enr), self.word.transform(flt))
        sim_c = cosine_similarity(self.char.transform(enr), self.char.transform(flt))
        return np.clip(0.4 * sim_w + 0.6 * sim_c, 0.0, 1.0)

    def pair_score(self, enriched_text: str, flat_text: str) -> float:
        return float(self.similarity_matrix([enriched_text], [flat_text])[0, 0])


def _main_series_tier1() -> pd.DataFrame:
    tier1 = load_tier1_pairs()
    mask = tier1["session_id"].astype(str).map(is_main_series)
    return tier1.loc[mask].reset_index(drop=True)


def train_test_day_split(
    day_counts: pd.DataFrame,
    *,
    train_fraction: float,
    seed: int,
) -> tuple[list[str], list[str]]:
    """Stratified-by-inventory shuffle split of eligible dates."""
    rng = np.random.default_rng(seed)
    train: list[str] = []
    test: list[str] = []
    for _inv, group in day_counts.groupby("inventory"):
        dates = group["date"].tolist()
        order = rng.permutation(len(dates))
        n_train = max(1, int(round(len(dates) * train_fraction)))
        n_train = min(n_train, len(dates) - 1) if len(dates) >= 2 else len(dates)
        picked = [dates[i] for i in order]
        train.extend(picked[:n_train])
        test.extend(picked[n_train:])
    return sorted(train), sorted(test)


def fit_fingerprint_on_tier1(
    *,
    exclude_dates: set[str] | None = None,
) -> tuple[TrainFittedTfidfFingerprint, dict[str, Any]]:
    """Fit fingerprint on main-series tier1 pairs, optionally holding out calendar dates.

    Hold-out is for applying the scorer inside a lag window (hard recalibrate) without
    fitting on that window's own known-correct pairs.
    """
    pairs = _main_series_tier1()
    excluded = exclude_dates or set()
    if excluded:
        train = pairs.loc[~pairs["date"].astype(str).isin(excluded)].reset_index(drop=True)
    else:
        train = pairs
    texts = (
        train["enriched_text"].fillna("").astype(str).tolist()
        + train["flat_text"].fillna("").astype(str).tolist()
    )
    fingerprint = TrainFittedTfidfFingerprint()
    fingerprint.fit(texts)
    meta = {
        "n_tier1_pairs_available": int(len(pairs)),
        "n_tier1_pairs_fit": int(len(train)),
        "n_fit_texts": len(texts),
        "n_exclude_dates": len(excluded),
        "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
    }
    return fingerprint, meta


def build_fingerprint_scorer(
    fingerprint: TrainFittedTfidfFingerprint,
    *,
    enriched_text_by_volgnr: Mapping[str, str],
    flat_text_by_id: Mapping[str, str],
    scale: float = FINGERPRINT_OVERLAP_SCALE,
) -> Callable[[str, str], float]:
    """`(volgnr, flat_id) -> scaled cosine` for CostModel / align_streams."""

    def scorer(volgnr: str, flat_id: str) -> float:
        enr = enriched_text_by_volgnr.get(volgnr) or ""
        flt = flat_text_by_id.get(flat_id) or ""
        if not enr.strip() or not flt.strip():
            return 0.0
        return scale * fingerprint.pair_score(enr, flt)

    return scorer


def blend_entity_fingerprint_scorer(
    entity_scorer: Callable[[str, str], float],
    fingerprint_scorer: Callable[[str, str], float],
) -> Callable[[str, str], float]:
    """DP1 overlap = entity + scaled fingerprint (additive in CostModel units)."""

    def scorer(volgnr: str, flat_id: str) -> float:
        return float(entity_scorer(volgnr, flat_id)) + float(
            fingerprint_scorer(volgnr, flat_id)
        )

    return scorer


def score_day_matrix(
    matrix: np.ndarray,
    flat_ids: Sequence[str],
    n_derangements: int,
) -> dict[str, Any]:
    count = matrix.shape[0]
    diagonal = [float(matrix[i, i]) for i in range(count)]
    top1_correct = sum(
        1 for i in range(count) if flat_ids[int(np.argmax(matrix[i]))] == flat_ids[i]
    )
    negative_scores: list[float] = []
    for offset in control_offsets(count, n_derangements):
        derangement = deranged_indices(count, offset)
        for i, j in enumerate(derangement):
            if flat_ids[j] == flat_ids[i]:
                continue
            negative_scores.append(float(matrix[i, j]))
    return {
        "count": count,
        "positive_scores": diagonal,
        "negative_scores": negative_scores,
        "top1_correct": top1_correct,
    }


def entity_day_matrix(
    volgnrs: Sequence[str],
    flat_ids: Sequence[str],
    scorer: Any,
) -> np.ndarray:
    n, m = len(volgnrs), len(flat_ids)
    mat = np.zeros((n, m), dtype=np.float32)
    for i, v in enumerate(volgnrs):
        for j, f in enumerate(flat_ids):
            mat[i, j] = float(scorer(v, f))
    return mat


def evaluate_split(
    pairs: pd.DataFrame,
    dates: Sequence[str],
    *,
    channel: str,
    matrix_fn: Any,
    n_derangements: int,
    day_cap: int | None = None,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    date_list = list(dates)
    if day_cap is not None and len(date_list) > day_cap:
        rng = np.random.default_rng(seed)
        date_list = sorted(rng.choice(date_list, size=day_cap, replace=False).tolist())

    pos_all: list[float] = []
    neg_all: list[float] = []
    top1_ok = 0
    top1_n = 0
    n_days = 0
    for date in date_list:
        day = pairs.loc[pairs["date"] == date].reset_index(drop=True)
        if len(day) < MIN_DAY_PAIRS:
            continue
        matrix = matrix_fn(day)
        scored = score_day_matrix(
            matrix, day["flat_id"].astype(str).tolist(), n_derangements
        )
        pos_all.extend(scored["positive_scores"])
        neg_all.extend(scored["negative_scores"])
        top1_ok += int(scored["top1_correct"])
        top1_n += int(scored["count"])
        n_days += 1

    pos_s = summarize_scores(pos_all)
    neg_s = summarize_scores(neg_all)
    auc = common_language_effect_size(pos_all, neg_all)
    return {
        "record_type": "split_metrics",
        "channel": channel,
        "n_days": n_days,
        "n_positive": pos_s["n"],
        "n_negative": neg_s["n"],
        "positive": pos_s,
        "negative": neg_s,
        "auc": None if auc is None else round(float(auc), 4),
        "top1_accuracy": (
            round(top1_ok / top1_n, 4) if top1_n else None
        ),
        "top1_n": top1_n,
    }


def run(
    *,
    train_fraction: float = TRAIN_FRACTION,
    seed: int = RANDOM_SEED,
    control_derangements: int = CONTROL_DERANGEMENTS,
    test_day_cap: int = TEST_DAY_CAP,
) -> list[dict[str, Any]]:
    pairs = _main_series_tier1()
    # Entity scorer keys on enriched volgnr (= alignment enriched_id, e.g. 1630-04-03_0).
    if "volgnr" not in pairs.columns:
        pairs = pairs.copy()
        pairs["volgnr"] = pairs["enriched_id"].astype(str)
    day_counts = eligible_day_counts(pairs)
    train_dates, test_dates = train_test_day_split(
        day_counts, train_fraction=train_fraction, seed=seed
    )
    train_set, test_set = set(train_dates), set(test_dates)
    train_pairs = pairs.loc[pairs["date"].isin(train_set)]
    test_pairs = pairs.loc[pairs["date"].isin(test_set)]

    train_texts = (
        train_pairs["enriched_text"].fillna("").astype(str).tolist()
        + train_pairs["flat_text"].fillna("").astype(str).tolist()
    )
    fingerprint = TrainFittedTfidfFingerprint()
    fingerprint.fit(train_texts)

    def tfidf_matrix(day: pd.DataFrame) -> np.ndarray:
        return fingerprint.similarity_matrix(
            day["enriched_text"].fillna("").astype(str).tolist(),
            day["flat_text"].fillna("").astype(str).tolist(),
        )

    entity_scorer = build_entity_overlap_scorer()

    def entity_matrix(day: pd.DataFrame) -> np.ndarray:
        if "volgnr" not in day.columns:
            return np.zeros((len(day), len(day)), dtype=np.float32)
        return entity_day_matrix(
            day["volgnr"].astype(str).tolist(),
            day["flat_id"].astype(str).tolist(),
            entity_scorer,
        )

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "edge": "ALIGNED_TO",
            "pair_source": "alignment_1626_1630.tier1_anchor",
            "scope": "main_series_corpus",
            "isolated_from": "hard_recalibrate_late_aug_window",
            "train_fraction": train_fraction,
            "seed": seed,
            "n_eligible_days": int(len(day_counts)),
            "n_train_days": len(train_dates),
            "n_test_days": len(test_dates),
            "n_train_pairs": int(len(train_pairs)),
            "n_test_pairs": int(len(test_pairs)),
            "n_train_fit_texts": len(train_texts),
            "test_day_cap": test_day_cap,
            "control_derangements": control_derangements,
            "policy": (
                "Train/test by calendar day (stratified inventory). "
                "TF-IDF fingerprint fitted on train texts only; test days held out. "
                "Within-day derangement negatives. Entity overlap reported on same split. "
                "No production ALIGNED_TO / PINNED_TO wire."
            ),
            **scope_meta(),
        }
    ]

    for split_name, split_dates, day_cap in (
        ("train", train_dates, None),
        ("test", test_dates, test_day_cap),
    ):
        for channel, matrix_fn in (
            ("tfidf_fingerprint", tfidf_matrix),
            ("entity_overlap", entity_matrix),
        ):
            metrics = evaluate_split(
                pairs,
                split_dates,
                channel=channel,
                matrix_fn=matrix_fn,
                n_derangements=control_derangements,
                day_cap=day_cap,
                seed=seed + (1 if split_name == "test" else 0),
            )
            metrics["split"] = split_name
            rows.append(metrics)

    # Compact verdict from test TF-IDF
    test_tfidf = next(
        r
        for r in rows
        if r.get("record_type") == "split_metrics"
        and r.get("split") == "test"
        and r.get("channel") == "tfidf_fingerprint"
    )
    test_ent = next(
        r
        for r in rows
        if r.get("record_type") == "split_metrics"
        and r.get("split") == "test"
        and r.get("channel") == "entity_overlap"
    )
    rows.append({
        "record_type": "verdict",
        "test_tfidf_auc": test_tfidf.get("auc"),
        "test_tfidf_top1": test_tfidf.get("top1_accuracy"),
        "test_entity_auc": test_ent.get("auc"),
        "test_entity_top1": test_ent.get("top1_accuracy"),
        "knowability": (
            "Fingerprint useful iff test AUC ≫ 0.5 and test top-1 recovers correct "
            "flat among same-day alternatives. Train metrics are fit diagnostics only."
        ),
    })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-fraction", type=float, default=TRAIN_FRACTION)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--control-derangements", type=int, default=CONTROL_DERANGEMENTS)
    parser.add_argument("--test-day-cap", type=int, default=TEST_DAY_CAP)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rows = run(
        train_fraction=args.train_fraction,
        seed=args.seed,
        control_derangements=args.control_derangements,
        test_day_cap=args.test_day_cap,
    )
    meta = next(r for r in rows if r["record_type"] == "meta")
    print(
        f"pairs tier1 main-series  train_days={meta['n_train_days']} "
        f"test_days={meta['n_test_days']}  "
        f"train_pairs={meta['n_train_pairs']} test_pairs={meta['n_test_pairs']}"
    )
    for r in rows:
        if r.get("record_type") != "split_metrics":
            continue
        print(
            f"  {r['split']:<5} {r['channel']:<18} "
            f"days={r['n_days']:<4} pos={r['n_positive']:<5} "
            f"AUC={r['auc']}  top1={r['top1_accuracy']}  "
            f"pos_mean={r['positive']['mean']} neg_mean={r['negative']['mean']}"
        )
    verdict = next(r for r in rows if r["record_type"] == "verdict")
    print(
        f"verdict test tfidf AUC={verdict['test_tfidf_auc']} "
        f"top1={verdict['test_tfidf_top1']}  |  "
        f"entity AUC={verdict['test_entity_auc']} top1={verdict['test_entity_top1']}"
    )
    if args.write:
        save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            description=(
                "Isolated corpus-wide train/test resolution fingerprint on tier1_anchor "
                "pairs: TF-IDF fit on train days only; test top-1/AUC vs within-day "
                "derangements; entity_overlap on same split. Not scoped to hard-recalibrate "
                "window. No production wire."
            ),
            parent_sources=["alignment_1626_1630"],
        )
        print(f"wrote {OUTPUT_DATASET}")


if __name__ == "__main__":
    main()

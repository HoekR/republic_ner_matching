from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).parent
OUT_DIR = ROOT / "data" / "eval"
DEFAULT_LINKING_EVAL = OUT_DIR / "eval_real.parquet"
DEFAULT_OUTPUT = OUT_DIR / "error_level_summary.json"

REQUIRED_SPAN_COLUMNS = {"sentence_idx", "token_start", "token_end", "span_text"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Separate span-extraction errors from delegate-linking errors."
    )
    parser.add_argument(
        "--linking-eval",
        default=str(DEFAULT_LINKING_EVAL),
        help="Path to eval_real.parquet from build_linking_benchmark.py",
    )
    parser.add_argument(
        "--predicted-spans",
        default="",
        help=(
            "Optional path to predicted spans (.parquet or .csv). "
            "If omitted, only linking-level errors are summarized."
        ),
    )
    parser.add_argument(
        "--gold-spans",
        default="",
        help=(
            "Optional path to gold spans (.parquet or .csv). "
            "Required when --predicted-spans is set."
        ),
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT),
        help="Output JSON path.",
    )
    return parser.parse_args()


def load_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type for {path}; expected .parquet or .csv")


def safe_f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def summarize_linking(eval_real: pd.DataFrame) -> dict[str, Any]:
    if "top1_correct" not in eval_real.columns:
        raise ValueError("linking eval file must contain top1_correct")

    total = int(len(eval_real))
    correct = int(eval_real["top1_correct"].sum())
    errors = total - correct
    no_candidate = int(eval_real["cand_1"].isna().sum()) if "cand_1" in eval_real.columns else 0
    wrong_candidate = int(((~eval_real["top1_correct"]) & eval_real["cand_1"].notna()).sum())

    divergence_summary: list[dict[str, Any]] = []
    if "divergence_band" in eval_real.columns:
        grouped = eval_real.groupby("divergence_band", dropna=False)
        for band, group in grouped:
            divergence_summary.append(
                {
                    "band": band if pd.notna(band) else "",
                    "rows": int(len(group)),
                    "top1_accuracy": round(float(group["top1_correct"].mean()), 4),
                    "top1_error_rate": round(1.0 - float(group["top1_correct"].mean()), 4),
                }
            )
        divergence_summary.sort(key=lambda item: item["rows"], reverse=True)

    return {
        "benchmark_scope": "linking_only",
        "benchmark_note": (
            "This benchmark feeds known name variants into the matcher, so span detection is held constant. "
            "Observed failures here are identity-resolution errors, not extraction misses."
        ),
        "rows": total,
        "top1_correct": correct,
        "top1_errors": errors,
        "top1_accuracy": round(correct / total, 4) if total else 0.0,
        "top1_error_rate": round(errors / total, 4) if total else 0.0,
        "error_breakdown": {
            "no_candidate": no_candidate,
            "wrong_delegate": wrong_candidate,
        },
        "divergence_breakdown": divergence_summary,
    }


def validate_span_columns(frame: pd.DataFrame, label: str) -> None:
    missing = sorted(REQUIRED_SPAN_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def attach_split(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "split" not in result.columns:
        result["split"] = "all"
    return result


def exact_match(gold: pd.Series, pred: pd.Series) -> bool:
    return (
        int(gold["sentence_idx"]) == int(pred["sentence_idx"])
        and int(gold["token_start"]) == int(pred["token_start"])
        and int(gold["token_end"]) == int(pred["token_end"])
    )


def overlap_match(gold: pd.Series, pred: pd.Series) -> bool:
    if int(gold["sentence_idx"]) != int(pred["sentence_idx"]):
        return False
    return max(int(gold["token_start"]), int(pred["token_start"])) < min(
        int(gold["token_end"]), int(pred["token_end"])
    )


def greedy_match(gold: pd.DataFrame, pred: pd.DataFrame, matcher) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    matched_gold: set[int] = set()
    matched_pred: set[int] = set()
    matches = 0

    gold_records = list(gold.iterrows())
    pred_records = list(pred.iterrows())

    for gold_idx, gold_row in gold_records:
        for pred_idx, pred_row in pred_records:
            if gold_idx in matched_gold or pred_idx in matched_pred:
                continue
            if matcher(gold_row, pred_row):
                matched_gold.add(gold_idx)
                matched_pred.add(pred_idx)
                matches += 1
                break

    missed_gold = [gold.loc[idx].to_dict() for idx in gold.index if idx not in matched_gold]
    extra_pred = [pred.loc[idx].to_dict() for idx in pred.index if idx not in matched_pred]

    matched_rows: list[dict[str, Any]] = []
    for gold_idx in matched_gold:
        gold_row = gold.loc[gold_idx]
        matched_rows.append(
            {
                "sentence_idx": int(gold_row["sentence_idx"]),
                "token_start": int(gold_row["token_start"]),
                "token_end": int(gold_row["token_end"]),
                "span_text": str(gold_row["span_text"]),
            }
        )
    return matches, matched_rows, missed_gold, extra_pred


def score_span_split(gold: pd.DataFrame, pred: pd.DataFrame) -> dict[str, Any]:
    exact_matches, _, exact_missed, exact_extra = greedy_match(gold, pred, exact_match)
    overlap_matches, _, overlap_missed, overlap_extra = greedy_match(gold, pred, overlap_match)

    gold_total = int(len(gold))
    pred_total = int(len(pred))

    exact_precision = round(exact_matches / pred_total, 4) if pred_total else 0.0
    exact_recall = round(exact_matches / gold_total, 4) if gold_total else 0.0
    overlap_precision = round(overlap_matches / pred_total, 4) if pred_total else 0.0
    overlap_recall = round(overlap_matches / gold_total, 4) if gold_total else 0.0

    return {
        "gold_spans": gold_total,
        "predicted_spans": pred_total,
        "exact": {
            "matches": int(exact_matches),
            "precision": exact_precision,
            "recall": exact_recall,
            "f1": safe_f1(exact_precision, exact_recall),
            "missed_gold": int(len(exact_missed)),
            "extra_predicted": int(len(exact_extra)),
        },
        "overlap": {
            "matches": int(overlap_matches),
            "precision": overlap_precision,
            "recall": overlap_recall,
            "f1": safe_f1(overlap_precision, overlap_recall),
            "missed_gold": int(len(overlap_missed)),
            "extra_predicted": int(len(overlap_extra)),
        },
    }


def summarize_spans(gold_spans: pd.DataFrame, predicted_spans: pd.DataFrame) -> dict[str, Any]:
    validate_span_columns(gold_spans, "gold spans")
    validate_span_columns(predicted_spans, "predicted spans")

    gold_spans = attach_split(gold_spans)
    predicted_spans = attach_split(predicted_spans)

    all_splits = sorted(set(gold_spans["split"].astype(str)) | set(predicted_spans["split"].astype(str)))
    split_scores: dict[str, Any] = {}
    for split in all_splits:
        gold_split = gold_spans[gold_spans["split"].astype(str) == split].reset_index(drop=True)
        pred_split = predicted_spans[predicted_spans["split"].astype(str) == split].reset_index(drop=True)
        split_scores[split] = score_span_split(gold_split, pred_split)

    split_scores["all"] = score_span_split(
        gold_spans.reset_index(drop=True),
        predicted_spans.reset_index(drop=True),
    )

    return {
        "benchmark_scope": "span_detection",
        "benchmark_note": "This benchmark measures extraction quality before delegate linking.",
        "by_split": split_scores,
    }


def combine_summary(linking: dict[str, Any], spans: dict[str, Any] | None) -> dict[str, Any]:
    if spans is None:
        headline = (
            "Current measured errors are linking-level errors. Span-level errors are not yet quantified in this run "
            "because no predicted-span file was provided."
        )
    else:
        span_recall = spans["by_split"]["all"]["overlap"]["recall"]
        linking_accuracy = linking["top1_accuracy"]
        headline = (
            "Span and linking errors are now separated. The overlap span recall estimates how often the mention is "
            f"found at all ({span_recall}), while the linking benchmark measures identity resolution once a span is present ({linking_accuracy})."
        )

    return {
        "headline": headline,
        "linking": linking,
        "spans": spans,
    }


def main() -> None:
    args = parse_args()
    linking_eval_path = Path(args.linking_eval)
    out_path = Path(args.out)

    linking_eval = load_table(linking_eval_path)
    linking_summary = summarize_linking(linking_eval)

    span_summary = None
    if args.predicted_spans:
        if not args.gold_spans:
            raise ValueError("--gold-spans is required when --predicted-spans is provided")
        predicted_spans = load_table(Path(args.predicted_spans))
        gold_spans = load_table(Path(args.gold_spans))
        span_summary = summarize_spans(gold_spans, predicted_spans)

    payload = combine_summary(linking_summary, span_summary)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

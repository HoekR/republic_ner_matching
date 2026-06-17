from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from match import build_attendance_year_index, build_store, match_ner
from preprocess import clean_span


ROOT = Path(__file__).parent
OUT_DIR = ROOT / "data" / "eval"
RC3_PATH = Path(
    "/Users/rikhoekstra/develop/republic_delegates_data/1705_1795/consolidated/"
    "delegates_with_patterns_1705_1795_v1.0_rc3.parquet"
)
PROD_REF_PATH = ROOT / "data" / "delegates_reference.parquet"
ATTENDANCE_PATHS = [
    "/Users/rikhoekstra/develop/republic_delegates_data/1705_1795/consolidated/attendance_long_1705_1795_v1.0-rc3.parquet",
    "/Users/rikhoekstra/develop/republic_delegates_data/1610_1630/consolidated/attendance_long_1610_1630_v1.0-rc1.parquet",
]

PROSE_MARKERS = {
    "requeste",
    "verstaan",
    "gedelibereert",
    "goedgevonden",
    "voldongen",
    "insinuatie",
    "verstek",
    "poene",
    "weeken",
    "relaas",
    "kamerbewaarder",
    "salvo",
    "geinsinueert",
    "suppliant",
}
DIVERGENCE_BINS = [0.0, 0.15, 0.35, 0.55, 1.01]
DIVERGENCE_LABELS = ["near_canonical", "moderate", "distant", "outlier"]


def normalize_name(text: str) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    return re.sub(r"\s+", " ", clean_span(str(text))).strip()


def split_pattern_field(value: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [part.strip(" -,:") for part in value.split(";") if part.strip(" -,:")]


def looks_like_name_variant(text: str) -> bool:
    if not isinstance(text, str):
        return False
    candidate = re.sub(r"\s+", " ", text).strip()
    if len(candidate) < 3 or len(candidate) > 80:
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]", candidate):
        return False
    if any(ch.isdigit() for ch in candidate):
        return False
    token_count = len(re.findall(r"[A-Za-zÀ-ÿ']+(?:-[A-Za-zÀ-ÿ']+)?", candidate))
    if token_count == 0 or token_count > 8:
        return False
    lower = candidate.lower()
    if sum(marker in lower for marker in PROSE_MARKERS) >= 1 and token_count > 5:
        return False
    return True


def build_benchmark_source(rc3: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for _, row in rc3.iterrows():
        canonical_source = row.get("lowerpattern", row.get("pattern", ""))
        canonical_variants = {
            normalize_name(variant)
            for variant in split_pattern_field(canonical_source)
            if normalize_name(variant)
        }

        historical_seen: set[str] = set()
        # Use lowerpattern — the clean semicolon-separated OCR-variant field.
        # "patterns" (plural) is the raw session-attendance log and must NOT be used here
        # as it contains names of co-attending delegates, not spelling variants.
        variant_source = row.get("lowerpattern", "")
        if not variant_source or not isinstance(variant_source, str):
            continue

        for raw_variant in split_pattern_field(variant_source):
            if not looks_like_name_variant(raw_variant):
                continue

            norm_variant = normalize_name(raw_variant)
            if not norm_variant or norm_variant in historical_seen:
                continue
            historical_seen.add(norm_variant)

            # lowerpattern variants are genuine OCR forms; keep them even if they
            # overlap with the canonical pattern — the point is to test how well
            # the matcher resolves real spelling variation.
            # Only skip exact duplicates already seen for this delegate.

            minjaar = row.get("minjaar", pd.NA)
            maxjaar = row.get("maxjaar", pd.NA)
            if pd.notna(minjaar) and pd.notna(maxjaar):
                eval_year = int(round((float(minjaar) + float(maxjaar)) / 2))
            elif pd.notna(minjaar):
                eval_year = int(minjaar)
            elif pd.notna(maxjaar):
                eval_year = int(maxjaar)
            else:
                eval_year = 1750

            records.append(
                {
                    "cons_id_str": str(row["cons_id_str"]),
                    "fullname": row.get("fullname", ""),
                    "variant_raw": raw_variant,
                    "variant_norm": norm_variant,
                    "year": eval_year,
                    "minjaar": minjaar,
                    "maxjaar": maxjaar,
                }
            )

    return pd.DataFrame(records)


def divergence_from_canonical(variant_norm: str, canonical_forms: list[str]) -> float:
    if not canonical_forms:
        return 1.0
    best = max(SequenceMatcher(None, variant_norm, canonical).ratio() for canonical in canonical_forms)
    return round(1.0 - best, 4)


def extract_family_key(fullname: str) -> str:
    value = str(fullname or "").strip()
    if not value:
        return ""
    if "," in value:
        return value.split(",")[0].strip().lower()
    parts = value.split()
    return parts[-1].lower() if parts else value.lower()


def build_test_real(rc3: pd.DataFrame, benchmark_source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    canonical_forms_by_id: dict[str, list[str]] = {}
    for _, row in rc3.iterrows():
        cons_id = str(row["cons_id_str"])
        source = row.get("lowerpattern", row.get("pattern", ""))
        forms = [normalize_name(variant) for variant in split_pattern_field(source) if normalize_name(variant)]
        if forms:
            canonical_forms_by_id[cons_id] = forms

    records_with_divergence: list[dict[str, object]] = []
    for _, row in benchmark_source.iterrows():
        divergence = divergence_from_canonical(row["variant_norm"], canonical_forms_by_id.get(row["cons_id_str"], []))
        band = DIVERGENCE_LABELS[next(i for i, upper in enumerate(DIVERGENCE_BINS[1:]) if divergence < upper)]
        records_with_divergence.append({**row.to_dict(), "divergence": divergence, "divergence_band": band})

    benchmark_source_div = pd.DataFrame(records_with_divergence)

    split_records: list[dict[str, object]] = []
    for _cons_id, group in benchmark_source_div.groupby("cons_id_str"):
        rows = group.sort_values("divergence", ascending=False).reset_index(drop=True)
        n_test = max(1, round(len(rows) * 0.30))
        for rank, (_, row) in enumerate(rows.iterrows()):
            split_records.append(
                {
                    **row.to_dict(),
                    "split": "test" if rank < n_test else "index",
                    "source": "real_pattern",
                }
            )

    benchmark_split = pd.DataFrame(split_records)
    test_real = benchmark_split[benchmark_split["split"] == "test"].copy()
    test_real["query_text"] = test_real["variant_norm"].map(clean_span)
    test_real = test_real[test_real["query_text"].str.len() > 0].reset_index(drop=True)
    return benchmark_split, test_real


def evaluate_linking(
    test_real: pd.DataFrame,
    rc3: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    prod_ref = pd.read_parquet(PROD_REF_PATH)
    prod_store = build_store(prod_ref)
    attendance_index = build_attendance_year_index(ATTENDANCE_PATHS)
    match_input = test_real[["query_text", "year"]].rename(columns={"query_text": "tag_text"})
    results = match_ner(
        prod_store,
        match_input,
        top_k=5,
        year_tolerance=0,
        min_score=0.0,
        attendance_years_by_id=attendance_index,
        attendance_boost=0.1,
    )
    results = results.drop(columns=["span_idx", "tag_text", "year"], errors="ignore")

    eval_real = pd.concat([test_real.reset_index(drop=True), results.reset_index(drop=True)], axis=1)
    eval_real["top1_correct"] = eval_real["cand_1"].fillna("").astype(str) == eval_real["cons_id_str"].astype(str)
    eval_real["top3_correct"] = eval_real.apply(
        lambda row: row["cons_id_str"] in {row.get(f"cand_{rank}", "") for rank in range(1, 4)},
        axis=1,
    )
    eval_real["top5_correct"] = eval_real.apply(
        lambda row: row["cons_id_str"] in {row.get(f"cand_{rank}", "") for rank in range(1, 6)},
        axis=1,
    )
    eval_real["score_gap_12"] = eval_real["score_1"].fillna(0) - eval_real["score_2"].fillna(0)

    id_to_name = rc3.set_index("cons_id_str")["fullname"].to_dict()
    eval_real["pred_fullname"] = eval_real["cand_1"].map(lambda value: id_to_name.get(value, value if pd.notna(value) else ""))
    eval_real["gold_family"] = eval_real["fullname"].map(extract_family_key)
    eval_real["pred_family"] = eval_real["pred_fullname"].map(extract_family_key)

    confusion_pairs = (
        eval_real.loc[~eval_real["top1_correct"]]
        .groupby(["fullname", "pred_fullname"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    focus_labels = eval_real.loc[~eval_real["top1_correct"], "gold_family"].value_counts().head(15).index.tolist()
    pred_focus = eval_real.loc[~eval_real["top1_correct"], "pred_family"].value_counts().head(15).index.tolist()
    matrix_labels = list(dict.fromkeys([label for label in focus_labels + pred_focus if label]))
    confusion_matrix = pd.crosstab(eval_real["gold_family"], eval_real["pred_family"], dropna=False)
    if matrix_labels:
        confusion_matrix = confusion_matrix.reindex(index=matrix_labels, columns=matrix_labels, fill_value=0)

    summary = {
        "rows": int(len(eval_real)),
        "delegates": int(eval_real["cons_id_str"].nunique()),
        "top1_accuracy": round(float(eval_real["top1_correct"].mean()), 4),
        "top3_recall": round(float(eval_real["top3_correct"].mean()), 4),
        "top5_recall": round(float(eval_real["top5_correct"].mean()), 4),
        "mean_score_1": round(float(eval_real["score_1"].mean()), 4),
        "mean_gap_12": round(float(eval_real["score_gap_12"].mean()), 4),
        "confusion_matrix_scope": "family-level matrix for the top confusion-heavy families",
        "temporal_prior": "strict minjaar/maxjaar gating with attendance-year soft boost",
        "attendance_delegate_count": int(len(attendance_index)),
    }
    return eval_real, confusion_pairs, confusion_matrix, summary


def main() -> None:
    if not RC3_PATH.exists():
        raise FileNotFoundError(f"Missing rc3 source: {RC3_PATH}")
    if not PROD_REF_PATH.exists():
        raise FileNotFoundError(f"Missing production reference: {PROD_REF_PATH}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rc3 = pd.read_parquet(RC3_PATH)
    benchmark_source = build_benchmark_source(rc3)
    benchmark_split, test_real = build_test_real(rc3, benchmark_source)
    eval_real, confusion_pairs, confusion_matrix, summary = evaluate_linking(test_real, rc3)

    outputs = {
        "benchmark_source": OUT_DIR / "benchmark_source.parquet",
        "benchmark_split": OUT_DIR / "benchmark_split.parquet",
        "test_real": OUT_DIR / "test_real.parquet",
        "eval_real": OUT_DIR / "eval_real.parquet",
        "confusion_pairs": OUT_DIR / "linking_confusion_pairs.csv",
        "confusion_matrix": OUT_DIR / "linking_confusion_matrix_family.csv",
        "summary": OUT_DIR / "linking_eval_summary.json",
    }

    benchmark_source.to_parquet(outputs["benchmark_source"], index=False)
    benchmark_split.to_parquet(outputs["benchmark_split"], index=False)
    test_real.to_parquet(outputs["test_real"], index=False)
    eval_real.to_parquet(outputs["eval_real"], index=False)
    confusion_pairs.to_csv(outputs["confusion_pairs"], index=False)
    confusion_matrix.to_csv(outputs["confusion_matrix"])

    payload = {
        **summary,
        "benchmark_source_rows": int(len(benchmark_source)),
        "test_real_rows": int(len(test_real)),
        "outputs": {key: str(path) for key, path in outputs.items() if key != "summary"},
    }
    outputs["summary"].write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
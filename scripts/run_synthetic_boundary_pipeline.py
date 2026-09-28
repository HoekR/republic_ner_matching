#!/usr/bin/env python3
"""Run the synthetic boundary encoder pipeline end-to-end and write a markdown report.

Steps: folds → train GysBERT → train GloBERTise → eval → docs report.

Usage:
    uv run python scripts/run_synthetic_boundary_pipeline.py
    uv run python scripts/run_synthetic_boundary_pipeline.py --skip-train   # eval only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load

MODELS = ("emanjavacas/GysBERT", "globalise/GloBERTise")
REPORT_PATH = PROJECT_ROOT / "docs" / "SYNTHETIC_BOUNDARY_ENCODER_REPORT.md"
TOLERANCES = (0, 50, 150)


def run(cmd: list[str]) -> None:
    print("\n$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))


def format_report(eval_records: list[dict[str, Any]]) -> str:
    meta = next(r for r in eval_records if r.get("record_type") == "meta")
    results = [r for r in eval_records if r.get("record_type") == "result"]
    lines = [
        "# Synthetic boundary encoder — run report",
        "<!-- doc-status: active -->",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Setup",
        "",
        f"- Device: `{meta.get('device')}`",
        f"- Synthetic test n: **{meta.get('n_synthetic_test')}**",
        f"- Gold n: **{meta.get('n_gold')}** (scaffold suggested_boundaries auto-accepted; not hand-reviewed)",
        f"- Models: {', '.join(f'`{m}`' for m in meta.get('models') or [])}",
        f"- Tolerances: {', '.join(str(t) for t in meta.get('tolerances') or TOLERANCES)}",
        "",
        "Task: recover internal char cut points in concatenated HTR (no separator).",
        "Baseline: even character split knowing `n_cuts`. Encoders: token-level boundary taggers fine-tuned with curriculum (2-res then 2+4-res).",
        "",
        "## Results",
        "",
    ]
    for set_name in ("synthetic_test", "gold"):
        lines.append(f"### {set_name}")
        lines.append("")
        header = "| predictor | " + " | ".join(f"F1@{t}" for t in TOLERANCES) + " | exact-count |"
        sep = "|---|---:|---:|---:|---:|"
        lines.extend([header, sep])
        for result in results:
            scores = result["sets"][set_name]
            row = (
                f"| `{result['predictor']}` | "
                + " | ".join(f"{scores[f'tol{t}']['f1']:.3f}" for t in TOLERANCES)
                + f" | {scores['exact_count_rate']:.3f} |"
            )
            lines.append(row)
        lines.append("")

    # Simple ranking on gold tol50
    ranked = sorted(
        results,
        key=lambda r: r["sets"]["gold"]["tol50"]["f1"],
        reverse=True,
    )
    best = ranked[0]
    baseline = next(r for r in results if r["predictor"] == "even_split_baseline")
    lines.extend(
        [
            "## Comparison",
            "",
            f"- Best on gold @tol50: **`{best['predictor']}`** "
            f"(F1={best['sets']['gold']['tol50']['f1']:.3f}) vs even-split "
            f"(F1={baseline['sets']['gold']['tol50']['f1']:.3f}).",
            f"- Synthetic-test @tol50 best: **`{max(results, key=lambda r: r['sets']['synthetic_test']['tol50']['f1'])['predictor']}`**.",
            "",
            "## Caveats",
            "",
            "- Gold boundaries equal machine `suggested_boundaries` (cumulative segment lengths), not hand review.",
            "- Examples truncated at encoder `max_length=512`; fold builder also capped concat at 2500 chars.",
            "- Train caps: 1200 pairs + 600 quads (see `synthetic_boundary_folds` meta).",
            "- MPS/CPU run; not a full hyperparameter sweep.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-folds", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()

    if not args.skip_folds:
        run([sys.executable, "scripts/build_synthetic_boundary_folds.py"])

    if not args.skip_train:
        for model in MODELS:
            run(
                [
                    sys.executable,
                    "scripts/train_synthetic_boundary_encoder.py",
                    "--model",
                    model,
                    "--epochs",
                    str(args.epochs),
                    "--batch-size",
                    str(args.batch_size),
                ]
            )

    run(
        [
            sys.executable,
            "scripts/eval_synthetic_boundary_encoder.py",
            "--models",
            *MODELS,
        ]
    )

    eval_records = load("synthetic_boundary_eval_report")
    REPORT_PATH.write_text(format_report(eval_records), encoding="utf-8")
    print(f"\nWrote report to {REPORT_PATH}")


if __name__ == "__main__":
    main()

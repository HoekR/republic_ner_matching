#!/usr/bin/env python3
"""Build a hard-period boundary-gold sample (session-days) for re-annotation.

Prioritises severe-collapse / high |K_e−K_f| days that are *not* already in
``boundary_gold_sample``. Output is a separate scaffold so the original 50-day
gold stays untouched.

Usage:
    uv run python scripts/build_hard_period_boundary_sample.py
    uv run python build_boundary_annotation_ui.py \\
      --sample output/boundary_gold_hard_period_sample.json \\
      --out output/boundary_annotation_ui_hard_period.html
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from build_alignment_new import OUTPUT_DIR, load_data
from build_boundary_gold_sample import compute_session_stats
from data_io import load

BOUNDARY_GOLD = "boundary_gold_sample"
COLLAPSE_DATASET = "s6c_severe_collapse_autopsy"
OUTPUT_DATASET = "boundary_gold_hard_period_sample"
OUT_JSON = OUTPUT_DIR / "boundary_gold_hard_period_sample.json"
SEED = 42
TARGET_DEFAULT = 25


def existing_gold_dates() -> set[str]:
    gold = load(BOUNDARY_GOLD)
    return {str(day["date"])[:10] for day in gold.get("days", [])}


def collapse_dates() -> set[str]:
    try:
        rows = load(COLLAPSE_DATASET)
    except Exception:
        return set()
    out: set[str] = set()
    for row in rows:
        if row.get("record_type") not in {None, "day", "example"} and "date" not in row:
            continue
        date = row.get("date") or row.get("enriched_date")
        if date:
            out.add(str(date)[:10])
        # autopsy may store collapse days only in meta
        if row.get("record_type") == "meta":
            for key in ("collapse_dates", "severe_collapse_dates"):
                for d in row.get(key) or []:
                    out.add(str(d)[:10])
    # Also collect any row with max_on_paragraph / severe flag
    for row in rows:
        if row.get("severe_collapse") or row.get("max_on_paragraph", 0) >= 7:
            if row.get("date"):
                out.add(str(row["date"])[:10])
    return out


def pick_hard_days(
    stats: list[dict[str, Any]],
    *,
    exclude: set[str],
    prefer: set[str],
    target: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Prefer collapse dates, then fill from largest |K_e−K_f|."""
    available = [s for s in stats if str(s["date"])[:10] not in exclude and int(s["k_e"]) > 1]
    preferred = [s for s in available if str(s["date"])[:10] in prefer]
    preferred.sort(key=lambda s: (-abs(int(s["diff_ke_kf"])), str(s["date"])))
    rest = [s for s in available if str(s["date"])[:10] not in prefer]
    rest.sort(key=lambda s: (-abs(int(s["diff_ke_kf"])), str(s["date"])))

    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    # Take up to 60% from collapse pool (shuffled among top mismatches).
    n_pref = min(len(preferred), max(1, round(target * 0.6)))
    pool_pref = preferred[: max(n_pref * 2, n_pref)]
    rng.shuffle(pool_pref)
    for item in pool_pref[:n_pref]:
        row = dict(item)
        row["stratum"] = "severe_collapse"
        row["hard_reason"] = "severe_collapse"
        chosen.append(row)

    need = target - len(chosen)
    pool_rest = rest[: max(need * 3, need)]
    rng.shuffle(pool_rest)
    for item in pool_rest[:need]:
        row = dict(item)
        abs_diff = abs(int(row["diff_ke_kf"]))
        row["stratum"] = f"diff_{abs_diff}" if abs_diff < 3 else "diff_3plus"
        row["hard_reason"] = "high_ke_kf_diff"
        chosen.append(row)

    chosen.sort(key=lambda s: s["date"])
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description="Hard-period boundary gold sample.")
    parser.add_argument("--target", type=int, default=TARGET_DEFAULT)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    exclude = existing_gold_dates()
    prefer = collapse_dates()
    enriched_all, res_df, *_ = load_data()
    stats = compute_session_stats(enriched_all, res_df)
    sample = pick_hard_days(stats, exclude=exclude, prefer=prefer, target=args.target, seed=args.seed)

    for day in sample:
        day["boundaries"] = []
        day["annotator"] = None
        day["annotated_at"] = None
        day["upstream_res_start_match"] = None
        day["starts_mid_resolution"] = None

    stratum_counts: dict[str, int] = defaultdict(int)
    reason_counts: dict[str, int] = defaultdict(int)
    for day in sample:
        stratum_counts[str(day.get("stratum"))] += 1
        reason_counts[str(day.get("hard_reason"))] += 1

    payload = {
        "sample_size": len(sample),
        "random_seed": args.seed,
        "sample_kind": "hard_period",
        "excluded_boundary_gold_dates": len(exclude),
        "n_collapse_dates_available": len(prefer - exclude),
        "stratum_counts": dict(stratum_counts),
        "hard_reason_counts": dict(reason_counts),
        "instructions": (
            "Hard-period session-days (severe collapse and/or high |K_e−K_f|), "
            "excluding the original boundary_gold_sample dates. Place K_e-1 resolution "
            "transitions with |||CUT||| or |||END|||…|||START RES|||. Mark calendar-date "
            "spillovers with |||DATE_END|||…|||DATE_START|||."
        ),
        "days": sample,
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON} with {len(sample)} days")
    print(f"  excluded original gold dates: {len(exclude)}")
    print(f"  hard_reason_counts: {dict(reason_counts)}")
    print(f"  stratum_counts: {dict(stratum_counts)}")
    print(
        "Next:\n"
        "  uv run python build_boundary_annotation_ui.py "
        f"--sample {OUT_JSON} --out output/boundary_annotation_ui_hard_period.html\n"
        "  open output/boundary_annotation_ui_hard_period.html"
    )


if __name__ == "__main__":
    main()

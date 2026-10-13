"""Same-day sync report: content-run verdict + pin≠trusted (windowed).

Does not replace hard_pin monotone. Flags days where consecutive content fails
on the pin stream and/or concordance pin disagrees with trusted/exact ledger.

Usage:
    uv run python -m p5_axis_viewer.report --from 1629-05-01 --to 1629-05-31
    uv run python -m p5_axis_viewer.report --from 1629-05-12 --to 1629-05-12 --write
"""

from __future__ import annotations

import argparse
from typing import Any

from p5_axis_viewer.store import day_sync_report_row, list_days_in_range

REPORT_DATASET = "p5_day_sync_report"


def build_sync_report(start: str, end: str) -> list[dict[str, Any]]:
    """One row per sitting day in ``[start, end]`` (corpus / main series)."""
    lo, hi = min(start, end), max(start, end)
    days = list_days_in_range(lo, hi, mode="corpus")
    rows = [day_sync_report_row(str(d["enriched_date"])) for d in days]
    flagged = sum(1 for r in rows if r.get("flag_review"))
    content_fail = sum(1 for r in rows if r.get("content_day_verdict") == "content_fail")
    pin_mismatch = sum(1 for r in rows if r.get("pin_trusted_mismatch"))
    cal_ok_pin_fail = sum(1 for r in rows if r.get("calendar_ok_pin_fail"))
    meta = {
        "record_type": "summary",
        "calendar_lo": lo,
        "calendar_hi": hi,
        "n_days": len(rows),
        "n_flag_review": flagged,
        "n_content_fail": content_fail,
        "n_pin_trusted_mismatch": pin_mismatch,
        "n_calendar_ok_pin_fail": cal_ok_pin_fail,
        "note": (
            "Same-day flags only. content_fail = ≥k consecutive pin-stream mismatches; "
            "calendar_ok_pin_fail = calendar HTR matches but pin stream fails; "
            "pin_trusted_mismatch = concordance pin ∉ trusted/exact. "
            "Not a monotone check; not a hard_pin gate."
        ),
    }
    return [meta, *rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", required=True, help="Inclusive start YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="Inclusive end YYYY-MM-DD")
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write {REPORT_DATASET} via data_io.save_semi_structured",
    )
    args = parser.parse_args(argv)

    rows = build_sync_report(args.date_from, args.date_to)
    summary = rows[0]
    print(
        f"p5_day_sync_report  {summary['calendar_lo']}→{summary['calendar_hi']}  "
        f"days={summary['n_days']}  flag_review={summary['n_flag_review']}  "
        f"content_fail={summary['n_content_fail']}  "
        f"pin≠trusted={summary['n_pin_trusted_mismatch']}  "
        f"cal_ok_pin_fail={summary['n_calendar_ok_pin_fail']}"
    )
    flagged = [r for r in rows if r.get("record_type") == "day" and r.get("flag_review")]
    for r in flagged[:20]:
        print(
            f"  {r['enriched_date']}  content={r['content_day_verdict']}  "
            f"pin={r['content_pin_verdict']}  cal={r['content_calendar_verdict']}  "
            f"mismatch={r['pin_trusted_mismatch']}  "
            f"pins={r['pin_sessions']}  trusted={r['exact_sessions'] or r['trusted_sessions']}"
        )
    if len(flagged) > 20:
        print(f"  … {len(flagged) - 20} more flagged")

    if args.write:
        from data_io import save_semi_structured

        path = save_semi_structured(
            rows,
            logical_name=REPORT_DATASET,
            script=__file__,
        )
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

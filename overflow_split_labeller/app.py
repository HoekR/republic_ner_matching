"""Superseded by ``overflow-cut-review-ui`` (Step 7).

Was PARKED pending track gold; that gate is closed. Use the live UI.
"""

from __future__ import annotations

import sys


def main() -> None:
    raise SystemExit(
        "overflow_split_labeller is superseded.\n"
        "  uv run overflow-cut-review-ui\n"
        "  # http://127.0.0.1:5058  →  overflow_cut_reviews\n"
        "See docs/steps/STEP_NEIGHBOURHOOD_SESSION_SHIFT.md (Step 7)."
    )


if __name__ == "__main__":
    main()
    sys.exit(1)

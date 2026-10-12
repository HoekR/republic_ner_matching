"""PARKED: human review of overflow-split cut proposals.

Blocked until track gold is baked and inspected. See package docstring.
"""

from __future__ import annotations

import sys


def main() -> None:
    raise SystemExit(
        "overflow-split-review-ui is PARKED until aligned_to_overflow_track_gold "
        "is baked and inspected.\n"
        "  uv run python -m sequence_graph.fingerprint_session_shift "
        "--bake-track-gold --write\n"
        "See docs/steps/STEP_NEIGHBOURHOOD_SESSION_SHIFT.md (Step 5 → Step 6)."
    )


if __name__ == "__main__":
    main()
    sys.exit(1)

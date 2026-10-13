#!/usr/bin/env bash
# One remediation lag window: recalibrate → bake → repin → promote → place(+wire).
# Usage: scripts/run_remediation_window.sh INV CAL_LO CAL_HI WINDOW_ID
set -euo pipefail
INV="${1:?inventory}"
LO="${2:?calendar-lo}"
HI="${3:?calendar-hi}"
WID="${4:?window-id}"

echo "======== remediation window ${WID}  inv=${INV}  ${LO}..${HI} ========"

uv run python -m sequence_graph.hard_recalibrate \
  --inventory "$INV" --calendar-lo "$LO" --calendar-hi "$HI" \
  --write --compare-notes

uv run python -m sequence_graph.bake_remediation_track_gold \
  --window-id "$WID" --inventory "$INV" \
  --calendar-lo "$LO" --calendar-hi "$HI" \
  --merge --write

uv run python -m sequence_graph.hard_pin_repin \
  --inventory "$INV" --calendar-lo "$LO" --calendar-hi "$HI" \
  --write --push-graph

uv run python -m sequence_graph.hard_pin_promote \
  --inventory "$INV" --calendar-lo "$LO" --calendar-hi "$HI" \
  --write --wire --push-graph

uv run python -m sequence_graph.hard_pin_place --write
uv run python -m sequence_graph.hard_pin_place --write --wire --push-graph

echo "======== DONE ${WID} ========"

# Stretch conflict timeline + remediation morph

Two views in one Vite app:

1. **Conflicts** (`/`) — calendar timeline + conflict table for annotated
   stretch claims (production vs physical vs review). Click a day for
   OpenSeadragon IIIF + note text.
2. **Remediation** (`/remediate.html`) — D3 bipartite **before→after morph**
   of hard recalibration: production `PINNED_TO` → hard
   `OBSERVED_ON∘DATED_AS` (+ literal openings, held-out review). Slider /
   play interpolates session endpoints; optional scan mid-rail shows the
   hard path. Tool choice: **D3**, not three.js — the remapping is 2D
   date↔session; depth would recreate the rejected lane spaghetti.

## Refresh data (required after clone)

`public/stretch.json` and `public/remediation.json` are **gitignored**
generated payloads. Regenerate before `pnpm dev`:

```bash
uv run python -m sequence_graph.stretch_viz_export
uv run python -m sequence_graph.remediation_viz_export
# other window (e.g. second 3185 lag cluster):
# uv run python -m sequence_graph.hard_recalibrate --inventory 3185 \
#   --calendar-lo 1626-09-21 --calendar-hi 1626-10-25 --write
# uv run python -m sequence_graph.remediation_viz_export \
#   --focus-lo 1626-09-21 --focus-hi 1626-10-25
# full Jul–Sep lag instead of Aug–Sep focus:
# uv run python -m sequence_graph.remediation_viz_export --full-lag
```

Remediation export requires `hard_recalibrate_proof` on disk
(`uv run python -m sequence_graph.hard_recalibrate --inventory 3185 --write --compare-notes`).

## Run

```bash
cd viz/sequence_stretch
pnpm install
pnpm dev
```

Open http://localhost:5173 (conflicts) or http://localhost:5173/remediate.html

pnpm 12 blocks dependency build scripts until approved. This app allows
`esbuild` via `pnpm-workspace.yaml` (`allowBuilds.esbuild: true`). If install
still fails with `ERR_PNPM_IGNORED_BUILDS`, run `pnpm approve-builds esbuild -y`
then `pnpm install` again.

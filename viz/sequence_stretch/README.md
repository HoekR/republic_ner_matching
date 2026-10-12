# Stretch conflict timeline

Calendar timeline + conflict table for an annotated inventory window.
Shows where **production** and **physical** pins disagree, and where
**review** date↔scan claims sit. Click a day for **OpenSeadragon** IIIF
(zoom/pan) + note text. Timeline: scroll zoom, drag pan, double-click reset.

## Refresh data

```bash
uv run python -m sequence_graph.stretch_viz_export
```

## Run

```bash
cd viz/sequence_stretch
pnpm install
pnpm dev
```

Open http://localhost:5173

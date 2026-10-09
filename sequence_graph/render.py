"""Render the three sequences as parallel tracks, correspondence drawn as edges. Stage 3b.

**Same discipline as `running_axis/serialize.py`, inherited rather than reinvented.** That module's
own stated reason: *"the visualisation is driven off the serialised spans rather than off live
objects... a picture can never show something the serialised state does not contain."* This module
takes only plain records (dicts / the frozen dataclasses below) and **imports nothing from
`sequence_graph.build` or `.correspondence`** -- the extraction that turns a live graph into these
records lives in `sequence_graph.consolidate.track_records`, deliberately outside this file, so the
constraint is structural (an import error) rather than a convention someone could forget.

**One inventory at a time, three horizontal lanes, top to bottom: `Scan`, `SittingDay`,
`Session`.** That order makes two of the three correspondence edges a simple one-lane-down arrow
(`DATED_AS`: Scan to SittingDay; `PINNED_TO`/`LABELLED_AS`: SittingDay to Session) and leaves
`OBSERVED_ON` (Session to Scan) as the one edge that has to arc back up across both lanes --
visually distinct for exactly the reason it is structurally distinct: it is the one edge this
model did not have to infer anything to draw.

**Four encodings, each a direct answer to a question the plan asked this stage to make visible
instead of tabulated:**

* **Crossing edges are monotonicity violations.** Two `DATED_AS` or `PINNED_TO`/`LABELLED_AS` edges
  drawn so their lines cross are exactly a pair `monotone_map` would flag -- the picture does not
  need a separate "is this monotone" column.
* **Edge style separates observed from inferred.** `OBSERVED_ON`/`DATED_AS` are solid; `PINNED_TO`/
  `LABELLED_AS` are dashed -- the one inferred step in the chain is never visually mistakable for
  an observed one.
* **A track segment with no edge is a gap**, drawn in the ribbon's own `unclaimed` grey rather than
  omitted -- an `unconstrained_gap` session or an unlabelled day reads as a visibly empty node.
* **Two edges into or out of the same node is a fork** -- drawn as both lines, not collapsed to one,
  which is `query --date 1629-05-18`'s own finding (two sessions claim one date) made visible.

No plotting dependency, matching `serialize.py`: the output is a self-contained SVG string.

Usage: see `sequence_graph.consolidate.track_records` for how to produce the records this module
consumes; this module has no `main()` of its own because it is never run standalone against live
data, by design.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Sequence

OBSERVED_STYLE = {"stroke-dasharray": "none"}
INFERRED_STYLE = {"stroke-dasharray": "4,3"}
GAP_COLOUR = "#e8e8e8"
LANE_COLOURS = {"Scan": "#4878d0", "SittingDay": "#ee854a", "Session": "#6acc64"}
LANES = ("Scan", "SittingDay", "Session")  # top to bottom; OBSERVED_ON arcs Session -> Scan


@dataclass(frozen=True)
class TrackNode:
    """One node in one lane, at an integer position along that lane's own order."""

    lane: str  # one of LANES
    node_id: str
    position: int
    label: str = ""
    is_gap: bool = False  # no correspondence edge touches this node at all

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane, "node_id": self.node_id, "position": self.position,
            "label": self.label, "is_gap": self.is_gap,
        }


@dataclass(frozen=True)
class TrackEdge:
    """One correspondence edge between two nodes in two (possibly the same) lanes."""

    from_id: str
    to_id: str
    kind: str  # OBSERVED_ON / DATED_AS / PINNED_TO / LABELLED_AS
    observed: bool
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id, "to_id": self.to_id, "kind": self.kind,
            "observed": self.observed, "label": self.label,
        }


def render_svg(
    nodes: Sequence[TrackNode],
    edges: Sequence[TrackEdge],
    *,
    title: str = "",
    width: int = 960,
    lane_height: int = 36,
    node_w: int = 10,
) -> str:
    """A self-contained SVG: three lanes, nodes as small rects, edges as lines between them."""
    by_lane: dict[str, list[TrackNode]] = {lane: [] for lane in LANES}
    for node in nodes:
        by_lane.setdefault(node.lane, []).append(node)
    if not nodes:
        return "<p>no nodes in this window</p>"

    max_pos = max((n.position for n in nodes), default=1)
    track_w = width - 70
    pos_x = {n.node_id: 60 + (n.position / max(max_pos, 1)) * track_w for n in nodes}
    lane_y = {lane: 20 + i * lane_height for i, lane in enumerate(LANES) if lane in by_lane}
    height = len(lane_y) * lane_height + 40

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'font-family="system-ui,sans-serif" font-size="10">'
    ]
    if title:
        parts.append(f'<text x="0" y="14" font-size="12" font-weight="600">{html.escape(title)}</text>')

    for lane, y in lane_y.items():
        parts.append(f'<text x="0" y="{y + 7}" fill="#444" font-size="11">{html.escape(lane)}</text>')

    # Edges first, so node rects draw on top of the lines they connect.
    node_lane = {n.node_id: n.lane for n in nodes}
    for edge in edges:
        if edge.from_id not in pos_x or edge.to_id not in pos_x:
            continue
        x1, y1 = pos_x[edge.from_id], lane_y.get(node_lane.get(edge.from_id), 0) + 10
        x2, y2 = pos_x[edge.to_id], lane_y.get(node_lane.get(edge.to_id), 0) + 10
        dash = "4,3" if not edge.observed else "none"
        colour = "#999" if not edge.observed else "#333"
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1}" x2="{x2:.1f}" y2="{y2}" '
            f'stroke="{colour}" stroke-width="1.2" stroke-dasharray="{dash}">'
            f"<title>{html.escape(edge.label or edge.kind)}</title></line>"
        )

    for node in nodes:
        x = pos_x[node.node_id]
        y = lane_y.get(node.lane, 0)
        colour = GAP_COLOUR if node.is_gap else LANE_COLOURS.get(node.lane, "#cccccc")
        parts.append(
            f'<rect x="{x - node_w/2:.1f}" y="{y}" width="{node_w}" height="20" '
            f'fill="{colour}" stroke="#fff" stroke-width="0.6">'
            f"<title>{html.escape(node.label or node.node_id)}</title></rect>"
        )
    parts.append("</svg>")
    return "".join(parts)


def render_legend() -> str:
    lane_swatches = "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:12px">'
        f'<span style="width:11px;height:11px;background:{colour};display:inline-block;'
        f'margin-right:4px;border:1px solid #fff"></span>'
        f'<span style="font:11px system-ui,sans-serif">{html.escape(lane)}</span></span>'
        for lane, colour in LANE_COLOURS.items()
    )
    edge_swatches = (
        '<span style="font:11px system-ui,sans-serif;margin-right:12px">'
        '&mdash; observed</span>'
        '<span style="font:11px system-ui,sans-serif">&#8211;&#8211; inferred</span>'
    )
    return f'<div style="margin:6px 0">{lane_swatches}{edge_swatches}</div>'


def render_html(
    nodes: Sequence[TrackNode], edges: Sequence[TrackEdge], *, title: str = "", width: int = 960
) -> str:
    """Convenience: legend plus the SVG, exactly as `serialize.render_html` does for the ribbon."""
    return render_legend() + render_svg(nodes, edges, title=title, width=width)

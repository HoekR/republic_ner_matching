"""Stage 3b's gate: `render.py` imports nothing from `build`/`correspondence`/`consolidate`,
and renders correctly from a hand-written record list -- never from a live graph.

`plans/SEQUENCE_GRAPH_SPINE.md` Stage 3b: "render.py imports nothing from
build.py; tested by rendering from a hand-written record list." Follows the same discipline as
`running_axis/serialize.py`, whose own module docstring states the reason: a picture can never
show something the serialised state does not contain.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from sequence_graph.render import TrackEdge, TrackNode, render_html, render_legend, render_svg

RENDER_PATH = Path(sys.modules["sequence_graph.render"].__file__)


def test_render_module_imports_nothing_from_the_graph_modules():
    """Checked by parsing the file's own import statements, not by trusting the module
    docstring's claim -- an `import` added later without updating the docstring would otherwise
    go unnoticed."""
    tree = ast.parse(RENDER_PATH.read_text())
    forbidden = {"sequence_graph.build", "sequence_graph.correspondence", "sequence_graph.consolidate"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    assert not (found & forbidden), f"render.py imports from: {found & forbidden}"


def test_renders_a_hand_written_record_list_with_all_four_encodings():
    """A minimal, entirely hand-written scene exercising all four stated encodings: a fork (two
    edges into one session), a gap (an untouched scan), observed vs inferred edge style, and a
    crossing pair (the monotonicity-violation signature)."""
    nodes = [
        TrackNode("Scan", "scan:X:1", position=1, label="scan 1"),
        TrackNode("Scan", "scan:X:2", position=2, label="scan 2"),
        TrackNode("Scan", "scan:X:3", position=3, label="gap scan", is_gap=True),
        TrackNode("SittingDay", "day:A", position=1, label="day A"),
        TrackNode("SittingDay", "day:B", position=2, label="day B"),
        TrackNode("Session", "session:P", position=1, label="session P"),
        TrackNode("Session", "session:Q", position=2, label="session Q"),
    ]
    edges = [
        TrackEdge("scan:X:1", "day:B", "DATED_AS", observed=True),   # crosses scan:X:2 -> day:A
        TrackEdge("scan:X:2", "day:A", "DATED_AS", observed=True),
        TrackEdge("day:A", "session:P", "PINNED_TO", observed=False),
        TrackEdge("day:A", "session:Q", "LABELLED_AS", observed=False),  # the fork
        TrackEdge("session:P", "scan:X:1", "OBSERVED_ON", observed=True),
    ]
    svg = render_svg(nodes, edges, title="test scene")
    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert svg.count("<rect") == len(nodes)
    assert svg.count("<line") == len(edges)
    # the gap node renders in the gap colour, not a lane colour
    assert 'fill="#e8e8e8"' in svg
    # at least one inferred (dashed) and one observed (solid) edge are both present
    assert 'stroke-dasharray="4,3"' in svg
    assert 'stroke-dasharray="none"' in svg


def test_render_html_includes_the_legend():
    svg = render_html([TrackNode("Scan", "scan:X:1", 1)], [], title="t")
    assert "<svg" in svg
    legend = render_legend()
    assert "observed" in legend and "inferred" in legend


def test_empty_node_list_does_not_raise():
    assert "no nodes" in render_svg([], [])


def test_edges_to_a_node_not_in_the_list_are_silently_skipped_not_an_error():
    """A record list can be hand-trimmed to a window; a dangling edge reference must not crash
    the renderer -- it is exactly the situation a partial, hand-written scene produces."""
    nodes = [TrackNode("Scan", "scan:X:1", 1)]
    edges = [TrackEdge("scan:X:1", "session:not_in_the_list", "OBSERVED_ON", observed=True)]
    svg = render_svg(nodes, edges)
    assert svg.count("<line") == 0

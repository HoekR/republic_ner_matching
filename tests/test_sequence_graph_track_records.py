"""`consolidate.track_records`: the extraction `render.py` deliberately cannot do itself."""

from __future__ import annotations

from sequence_graph.consolidate import track_records
from sequence_graph.render import render_html


def test_track_records_produces_renderable_output_for_a_real_inventory():
    nodes, edges = track_records("3187")
    assert nodes and edges
    svg = render_html(nodes, edges, title="Inventory 3187")
    assert svg.count("<rect") == len(nodes)
    assert "<svg" in svg


def test_every_scan_in_the_inventory_is_present_even_when_untouched():
    """The encoding rule is 'a track segment with no edge is a gap', not 'omitted' -- confirm
    at least one genuinely untouched scan survives into the node list, flagged `is_gap`."""
    nodes, _edges = track_records("3187")
    scans = [n for n in nodes if n.lane == "Scan"]
    assert any(n.is_gap for n in scans), "expected at least one untouched scan in a real inventory"


def test_a_fork_date_appears_with_edges_to_both_sessions():
    """1629-05-18 is the hand-verified two-session case (query --date); confirm it survives
    into inventory 3188's records with both PINNED_TO/LABELLED_AS edges intact."""
    nodes, edges = track_records("3188")
    day_node = "day:1629-05-18"
    assert any(n.node_id == day_node for n in nodes)
    targets = {e.to_id for e in edges if e.from_id == day_node}
    assert {"session:session-3188-num-79", "session:session-3188-num-129"} <= targets

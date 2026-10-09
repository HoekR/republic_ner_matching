"""Node identity: ids are derived from the archival identifier, never a counter.

Stage 1 of `plans/SEQUENCE_GRAPH_SPINE.md`. See `sequence_graph/nodes.py`.
"""

from __future__ import annotations

import pytest

from sequence_graph.nodes import (
    EnrichedResolution,
    Entity,
    HtrResolution,
    Paragraph,
    Scan,
    Session,
    SittingDay,
)


def test_scan_id_is_derived_and_stable():
    a = Scan(inventory="3185", scan_num=190)
    b = Scan(inventory="3185", scan_num=190)
    assert a.node_id == b.node_id == "scan:3185:190"


def test_session_from_session_id_parses_inventory_and_num():
    s = Session.from_session_id("session-3185-num-12")
    assert s.inventory == "3185"
    assert s.session_num == 12
    assert s.node_id == "session:session-3185-num-12"


def test_htr_resolution_from_flat_id_parses_all_three_parts():
    r = HtrResolution.from_flat_id("session-3185-num-12-resolution-3")
    assert r.session_id == "session-3185-num-12"
    assert r.inventory == "3185"
    assert r.resolution_num == 3
    assert r.node_id == "htr_res:session-3185-num-12-resolution-3"


def test_paragraph_id_uses_the_axis_own_stable_id():
    p = Paragraph(
        axis_id="session-3185-num-1-resolution-1#p0",
        flat_id="session-3185-num-1-resolution-1",
        para_index=0,
    )
    assert p.node_id == "para:session-3185-num-1-resolution-1#p0"


def test_sitting_day_and_enriched_resolution_carry_no_physical_inventory():
    """The editorial sequence has no inventory field at all -- it cannot state provenance,
    per `sequence_graph/build.py`'s module docstring, so sidelining cannot act on it directly."""
    day = SittingDay(date="1626-01-01")
    res = EnrichedResolution(date="1626-01-01", index=0)
    assert not hasattr(day, "inventory")
    assert not hasattr(res, "inventory")
    assert day.node_id == "day:1626-01-01"
    assert res.node_id == "enriched:1626-01-01:0"


def test_entity_has_no_next_order_field():
    """An entity is a label two sequences attach to, not a position in its own sequence."""
    e = Entity(entity_id="791967")
    assert e.node_id == "entity:791967"
    assert not hasattr(e, "resolution_num")
    assert not hasattr(e, "para_index")


def test_all_node_types_are_frozen_and_hashable():
    """Required for use as networkx node keys / in sets without an extra wrapper."""
    nodes = [
        Scan("3185", 1),
        Session.from_session_id("session-3185-num-1"),
        HtrResolution.from_flat_id("session-3185-num-1-resolution-1"),
        Paragraph("session-3185-num-1-resolution-1#p0", "session-3185-num-1-resolution-1", 0),
        SittingDay("1626-01-01"),
        EnrichedResolution("1626-01-01", 0),
        Entity("1"),
    ]
    for node in nodes:
        hash(node)  # must not raise
        with pytest.raises(Exception):
            node.node_id = "mutated"  # frozen: assignment must fail

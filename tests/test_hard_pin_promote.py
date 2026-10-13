"""Unit tests for scoped production PINNED_TO promote — no corpus I/O."""

from __future__ import annotations

import networkx as nx
import pandas as pd

from sequence_graph.build import CONTAINS
from sequence_graph.correspondence import ALIGNED_TO, Evidence, PINNED_TO
from sequence_graph.hard_pin_repin import EDGE_KEY as HARD_EDGE_KEY
from sequence_graph.hard_pin_promote import (
    CHANNEL,
    apply_concordance_promote,
    hard_dates_for_session,
    inherit_date_rows,
    push_production_pins_to_graph,
    run_hard_pin_promote,
)
from sequence_graph.nodes import (
    EnrichedResolution,
    HtrResolution,
    Session,
    SittingDay,
)


def _repin_fixture() -> list[dict]:
    return [
        {
            "record_type": "meta",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
            "gate": "PASS",
        },
        {
            "record_type": "wire_edge",
            "date": "1626-09-21",
            "session_id": "session-3185-num-157",
            "session_num": 157,
            "production_session": "session-3185-num-148",
            "production_disagrees": True,
            "verdict": "shift",
            "dated_scans_on_session": [300],
            "edge_key": HARD_EDGE_KEY,
            "gate_eligible": True,
        },
        {
            "record_type": "wire_edge",
            "date": "1626-09-22",
            "session_id": "session-3185-num-158",
            "session_num": 158,
            "production_session": "session-3185-num-158",
            "production_disagrees": False,
            "verdict": "agree",
            "dated_scans_on_session": [301],
            "edge_key": HARD_EDGE_KEY,
            "gate_eligible": True,
        },
        {
            "record_type": "wire_edge",
            "date": "1626-09-23",
            "session_id": "session-3185-num-160",
            "session_num": 160,
            "production_session": None,
            "production_disagrees": True,
            "verdict": "new_pin",
            "dated_scans_on_session": [302],
            "edge_key": HARD_EDGE_KEY,
            "gate_eligible": True,
        },
        {
            "record_type": "summary",
            "n_wire_edges": 3,
            "gate": "PASS",
            "monotone_ok": True,
        },
    ]


def _concordance_fixture() -> pd.DataFrame:
    rows = []
    for date, sid, k in (
        ("1626-09-21", "session-3185-num-148", 3),
        ("1626-09-22", "session-3185-num-158", 2),
        ("1626-09-23", "session-3185-num-150", 1),
    ):
        for i in range(k):
            rows.append({
                "enriched_date": date,
                "resolution_index": i,
                "paragraph_start_index": i,
                "paragraph_end_index": i,
                "resolved_session_id": sid,
                "paragraph_prediction_status": "baseline",
            })
    return pd.DataFrame(rows)


def test_concordance_rewrites_session_keeps_spans() -> None:
    before = _concordance_fixture()
    edges = [r for r in _repin_fixture() if r["record_type"] == "wire_edge"]
    after, log = apply_concordance_promote(before, edges)
    wired = [r for r in log if r.get("wired")]
    assert len(wired) == 3
    day = after.loc[after["enriched_date"] == "1626-09-21"]
    assert set(day["resolved_session_id"]) == {"session-3185-num-157"}
    assert list(day["paragraph_start_index"]) == [0, 1, 2]
    assert (day["paragraph_prediction_status"] == "hard_pin_promote").all()


def test_push_replaces_production_keeps_hard() -> None:
    graph = nx.MultiDiGraph()
    day = SittingDay(date="1626-09-21")
    old = Session.from_session_id("session-3185-num-148")
    new = Session.from_session_id("session-3185-num-157")
    graph.add_node(day.node_id, kind="SittingDay", obj=day)
    graph.add_node(old.node_id, kind="Session", obj=old)
    graph.add_node(new.node_id, kind="Session", obj=new)
    graph.add_edge(
        day.node_id, old.node_id, key=PINNED_TO, kind=PINNED_TO,
        evidence=Evidence(channel="resolved_session_id", source="test", observed=False),
    )
    graph.add_edge(
        day.node_id, new.node_id, key=HARD_EDGE_KEY, kind=PINNED_TO,
        evidence=Evidence(channel="hard", source="test", observed=False),
    )
    stats = push_production_pins_to_graph(
        graph,
        [{
            "record_type": "wire_edge",
            "date": "1626-09-21",
            "session_id": "session-3185-num-157",
            "verdict": "shift",
            "production_session": "session-3185-num-148",
        }],
    )
    assert stats["added"] == 1
    assert stats["dropped"] == 1
    prod = [
        (v, k)
        for _u, v, k, d in graph.out_edges(day.node_id, keys=True, data=True)
        if d.get("kind") == PINNED_TO and k == PINNED_TO
    ]
    hard = [
        (v, k)
        for _u, v, k, d in graph.out_edges(day.node_id, keys=True, data=True)
        if d.get("kind") == PINNED_TO and k == HARD_EDGE_KEY
    ]
    assert prod == [(new.node_id, PINNED_TO)]
    assert hard == [(new.node_id, HARD_EDGE_KEY)]
    ev = graph.edges[day.node_id, new.node_id, PINNED_TO]["evidence"]
    assert ev.channel == CHANNEL


def test_inherit_date_composition() -> None:
    graph = nx.MultiDiGraph()
    day = SittingDay(date="1626-09-21")
    sess = Session.from_session_id("session-3185-num-157")
    enriched = EnrichedResolution(date="1626-09-10", index=0)
    htr = HtrResolution.from_flat_id("session-3185-num-157-resolution-1")
    for node, kind, obj in (
        (day.node_id, "SittingDay", day),
        (sess.node_id, "Session", sess),
        (enriched.node_id, "EnrichedResolution", enriched),
        (htr.node_id, "HtrResolution", htr),
    ):
        graph.add_node(node, kind=kind, obj=obj)
    graph.add_edge(
        day.node_id, sess.node_id, key=HARD_EDGE_KEY, kind=PINNED_TO,
        evidence=Evidence(channel="hard", source="test", observed=False),
    )
    graph.add_edge(sess.node_id, htr.node_id, key=CONTAINS, kind=CONTAINS)
    graph.add_edge(
        enriched.node_id,
        htr.node_id,
        key=f"{ALIGNED_TO}:overflow",
        kind=ALIGNED_TO,
        evidence=Evidence(channel="overflow", source="test", observed=True),
    )
    assert hard_dates_for_session(graph, sess.session_id) == ["1626-09-21"]
    rows = inherit_date_rows(
        graph,
        calendar_lo="1626-09-01",
        calendar_hi="1626-10-25",
        inventory="3185",
    )
    assert len(rows) == 1
    assert rows[0]["verdict"] == "shift"
    assert rows[0]["inherited_date"] == "1626-09-21"
    assert rows[0]["editorial_date"] == "1626-09-10"


def test_run_gate_pass_with_fixtures() -> None:
    rows = run_hard_pin_promote(
        repin_rows=_repin_fixture(),
        concordance=_concordance_fixture(),
        graph=nx.MultiDiGraph(),
    )
    summary = next(r for r in rows if r["record_type"] == "summary")
    meta = next(r for r in rows if r["record_type"] == "meta")
    assert summary["gate"] == "PASS"
    assert summary["n_wire_edges"] == 3
    assert summary["n_shift"] == 1
    assert summary["delta_slice_separated"] == 0
    assert meta["channel"] == CHANNEL
    assert summary["n_dates_wired_preview"] == 3

"""Unit tests for gated PINNED_TO:hard repin — no corpus / graph I/O."""

from __future__ import annotations

import networkx as nx
import pandas as pd

from sequence_graph.correspondence import PINNED_TO
from sequence_graph.hard_pin_repin import (
    EDGE_KEY,
    hard_pins_monotone,
    propose_repin_rows,
    push_hard_pins_to_graph,
    run_hard_pin_repin,
    uniform_separated_on_dates,
)


def _hard_fixture() -> list[dict]:
    return [
        {
            "record_type": "meta",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
        },
        {
            "record_type": "hard_map",
            "date": "1626-09-21",
            "session_id": "session-3185-num-157",
            "session_num": 157,
            "unique": True,
            "active": True,
            "production_session": "session-3185-num-148",
            "production_disagrees": True,
            "dated_scans_on_session": [300],
        },
        {
            "record_type": "hard_map",
            "date": "1626-09-22",
            "session_id": "session-3185-num-158",
            "session_num": 158,
            "unique": True,
            "active": True,
            "production_session": "session-3185-num-158",
            "production_disagrees": False,
            "dated_scans_on_session": [301],
        },
        {
            "record_type": "hard_map",
            "date": "1626-09-23",
            "session_id": "session-3185-num-160",
            "session_num": 160,
            "unique": True,
            "active": True,
            "production_session": None,
            "production_disagrees": True,
            "dated_scans_on_session": [302],
        },
    ]


def _concordance_fixture() -> pd.DataFrame:
    rows = []
    for date, k in (("1626-09-21", 3), ("1626-09-22", 2), ("1626-09-23", 1)):
        for i in range(k):
            rows.append({
                "enriched_date": date,
                "resolution_index": i,
                "paragraph_start_index": i,
                "paragraph_end_index": i,
                "resolved_session_id": "session-3185-num-148",
            })
    return pd.DataFrame(rows)


def test_propose_verdicts() -> None:
    edges = propose_repin_rows([
        r for r in _hard_fixture() if r["record_type"] == "hard_map"
    ])
    by_date = {e["date"]: e for e in edges if e["record_type"] == "wire_edge"}
    assert by_date["1626-09-21"]["verdict"] == "shift"
    assert by_date["1626-09-22"]["verdict"] == "agree"
    assert by_date["1626-09-23"]["verdict"] == "new_pin"
    assert all(e["edge_key"] == EDGE_KEY for e in by_date.values())


def test_monotone_detects_inversion() -> None:
    ok = hard_pins_monotone(propose_repin_rows([
        r for r in _hard_fixture() if r["record_type"] == "hard_map"
    ]))
    assert ok["ok"] is True
    bad = hard_pins_monotone([
        {
            "record_type": "wire_edge",
            "date": "1626-09-21",
            "session_num": 160,
        },
        {
            "record_type": "wire_edge",
            "date": "1626-09-22",
            "session_num": 150,
        },
    ])
    assert bad["ok"] is False
    assert bad["n_violations"] == 1


def test_run_gate_pass() -> None:
    rows = run_hard_pin_repin(
        proof_rows=_hard_fixture(),
        concordance=_concordance_fixture(),
    )
    summary = next(r for r in rows if r["record_type"] == "summary")
    meta = next(r for r in rows if r["record_type"] == "meta")
    assert summary["gate"] == "PASS"
    assert summary["n_wire_edges"] == 3
    assert summary["n_shift"] == 1
    assert summary["n_agree"] == 1
    assert summary["n_new_pin"] == 1
    assert meta["edge_key"] == EDGE_KEY
    assert summary["before_slice_separated"] == 6


def test_uniform_guard_counts() -> None:
    out = uniform_separated_on_dates(
        _concordance_fixture(), {"1626-09-21", "1626-09-22"}
    )
    assert out["attributed"] == 5
    assert out["separated"] == 5


def test_push_writes_hard_key_only() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("day:1626-09-21", kind="SittingDay")
    graph.add_node("session:session-3185-num-157", kind="Session")
    # stale hard edge to replace
    graph.add_edge(
        "day:1626-09-21",
        "session:session-3185-num-157",
        key=EDGE_KEY,
        kind=PINNED_TO,
    )
    wire = [
        {
            "record_type": "wire_edge",
            "date": "1626-09-21",
            "session_id": "session-3185-num-157",
            "verdict": "shift",
            "production_session": "session-3185-num-148",
            "production_disagrees": True,
            "dated_scans_on_session": [300],
        }
    ]
    n = push_hard_pins_to_graph(graph, wire)
    assert n == 1
    edges = list(graph.edges(keys=True, data=True))
    assert len(edges) == 1
    _u, _v, k, d = edges[0]
    assert k == EDGE_KEY
    assert d["kind"] == PINNED_TO
    assert d["evidence"].channel == "hard_observed_on_compose_dated_as"


def test_push_hard_pins_preserves_other_window() -> None:
    graph = nx.MultiDiGraph()
    for day, sess in (
        ("1626-09-21", "session-3185-num-157"),
        ("1626-11-05", "session-3185-num-180"),
    ):
        graph.add_node(f"day:{day}", kind="SittingDay")
        graph.add_node(f"session:{sess}", kind="Session")
        graph.add_edge(
            f"day:{day}",
            f"session:{sess}",
            key=EDGE_KEY,
            kind=PINNED_TO,
        )
    graph.add_node("session:session-3185-num-181", kind="Session")
    n = push_hard_pins_to_graph(
        graph,
        [{
            "record_type": "wire_edge",
            "date": "1626-11-05",
            "session_id": "session-3185-num-181",
            "verdict": "shift",
            "production_session": "session-3185-num-180",
            "production_disagrees": True,
            "dated_scans_on_session": [400],
        }],
    )
    assert n == 1
    assert graph.has_edge(
        "day:1626-09-21", "session:session-3185-num-157", key=EDGE_KEY
    )
    assert graph.has_edge(
        "day:1626-11-05", "session:session-3185-num-181", key=EDGE_KEY
    )
    assert not graph.has_edge(
        "day:1626-11-05", "session:session-3185-num-180", key=EDGE_KEY
    )

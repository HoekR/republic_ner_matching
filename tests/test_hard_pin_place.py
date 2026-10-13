"""Unit tests for hard_pin_place — no corpus I/O."""

from __future__ import annotations

import networkx as nx
import pandas as pd

from sequence_graph.build import CONTAINS
from sequence_graph.correspondence import ALIGNED_TO, DATED_AS, OBSERVED_ON, PINNED_TO
from sequence_graph.hard_pin_place import (
    EDGE_KEY,
    apply_placements,
    drop_hard_place_edges_for_dates,
    place_date_on_session,
    push_align_edges,
    run_hard_pin_place,
    sitting_scan_span,
    span_paragraph_stream,
    strip_nihil_hard_place,
)
from sequence_graph.nodes import (
    EnrichedResolution,
    HtrResolution,
    Scan,
    Session,
    SittingDay,
)


def _promote_fixture() -> list[dict]:
    return [
        {
            "record_type": "meta",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
        },
        {
            "record_type": "wire_edge",
            "date": "1626-09-21",
            "session_id": "session-3185-num-157",
            "verdict": "shift",
        },
        {
            "record_type": "wire_edge",
            "date": "1626-09-23",
            "session_id": "session-3185-num-159",
            "verdict": "new_pin",
        },
    ]


def _concordance_piled() -> pd.DataFrame:
    """Two dates piled on start 0 — room to gain separated by packing."""
    rows = []
    for date, k in (("1626-09-21", 4), ("1626-09-23", 3)):
        for i in range(k):
            rows.append({
                "enriched_date": date,
                "resolution_index": i,
                "paragraph_start_index": 0,
                "paragraph_end_index": 0,
                "resolved_session_id": "session-3185-num-148",
            })
    return pd.DataFrame(rows)


def test_place_spreads_unique_starts() -> None:
    group = _concordance_piled().loc[
        lambda d: d["enriched_date"] == "1626-09-21"
    ]
    stream = [f"session-3185-num-157-resolution-{i}" for i in range(1, 9)]
    placements, entry = place_date_on_session(
        group, session_id="session-3185-num-157", stream=stream
    )
    assert entry["placed"] is True
    assert entry["n_unique_starts"] == 4
    assert [p[0] for p in placements] == [0, 1, 2, 3]


def test_apply_and_gate_pass() -> None:
    streams = {
        "session-3185-num-157": [
            f"session-3185-num-157-resolution-{i}" for i in range(1, 9)
        ],
        "session-3185-num-159": [
            f"session-3185-num-159-resolution-{i}" for i in range(1, 9)
        ],
    }
    rows = run_hard_pin_place(
        promote_rows=_promote_fixture(),
        concordance=_concordance_piled(),
        streams=streams,
    )
    summary = next(r for r in rows if r["record_type"] == "summary")
    assert summary["gate"] == "PASS"
    assert summary["delta_slice_separated"] > 0
    assert summary["n_align_edges"] == 7


def test_push_align_edges() -> None:
    graph = nx.MultiDiGraph()
    day = SittingDay(date="1626-09-21")
    sess = Session.from_session_id("session-3185-num-157")
    enriched = EnrichedResolution(date="1626-09-21", index=0)
    htr = HtrResolution.from_flat_id("session-3185-num-157-resolution-1")
    for node, kind, obj in (
        (day.node_id, "SittingDay", day),
        (sess.node_id, "Session", sess),
        (enriched.node_id, "EnrichedResolution", enriched),
        (htr.node_id, "HtrResolution", htr),
    ):
        graph.add_node(node, kind=kind, obj=obj)
    graph.add_edge(sess.node_id, htr.node_id, key=CONTAINS, kind=CONTAINS)
    n = push_align_edges(
        graph,
        [{
            "record_type": "wire_edge",
            "date": "1626-09-21",
            "resolution_index": 0,
            "session_id": "session-3185-num-157",
            "flat_id": "session-3185-num-157-resolution-1",
            "paragraph_start_index": 0,
            "paragraph_end_index": 0,
        }],
    )
    assert n == 1
    assert graph.has_edge(enriched.node_id, htr.node_id, key=EDGE_KEY)
    assert graph.edges[enriched.node_id, htr.node_id, EDGE_KEY]["kind"] == ALIGNED_TO


def test_room_lt_ke_abstains() -> None:
    group = _concordance_piled().loc[lambda d: d["enriched_date"] == "1626-09-21"]
    stream = [f"session-3185-num-157-resolution-{i}" for i in range(1, 3)]  # room=2 < k=4
    placements, entry = place_date_on_session(
        group, session_id="session-3185-num-157", stream=stream
    )
    assert placements == []
    assert entry["placed"] is False
    assert entry["reason"] == "room_lt_ke_abstain"
    assert entry["room"] == 2
    assert entry["k_e"] == 4


def test_nihil_actum_abstains() -> None:
    group = pd.DataFrame([{
        "enriched_date": "1626-08-23",
        "resolution_index": 0,
        "paragraph_start_index": pd.NA,
        "paragraph_end_index": pd.NA,
        "resolved_session_id": pd.NA,
        "day_status": "nihil_actum",
    }])
    stream = [f"session-3185-num-145-resolution-{i}" for i in range(1, 5)]
    placements, entry = place_date_on_session(
        group, session_id="session-3185-num-145", stream=stream
    )
    assert placements == []
    assert entry["placed"] is False
    assert entry["reason"] == "nihil_actum_abstain"


def test_strip_nihil_hard_place_clears_session_and_para() -> None:
    conc = pd.DataFrame([
        {
            "enriched_date": "1626-08-23",
            "resolution_index": 0,
            "day_status": "nihil_actum",
            "resolved_session_id": "session-3185-num-145",
            "paragraph_start_index": 0,
            "paragraph_end_index": 0,
            "paragraph_prediction_status": "hard_pin_place",
        },
        {
            "enriched_date": "1626-09-21",
            "resolution_index": 0,
            "day_status": "resolved_auto",
            "resolved_session_id": "session-3185-num-157",
            "paragraph_start_index": 0,
            "paragraph_end_index": 0,
            "paragraph_prediction_status": "hard_pin_place",
        },
    ])
    after, log = strip_nihil_hard_place(conc)
    assert len(log) == 1
    assert log[0]["date"] == "1626-08-23"
    nihil = after.loc[after["enriched_date"] == "1626-08-23"].iloc[0]
    assert pd.isna(nihil["resolved_session_id"])
    assert pd.isna(nihil["paragraph_start_index"])
    assert pd.isna(nihil["paragraph_prediction_status"])
    kept = after.loc[after["enriched_date"] == "1626-09-21"].iloc[0]
    assert kept["resolved_session_id"] == "session-3185-num-157"
    assert kept["paragraph_start_index"] == 0


def test_drop_hard_place_edges_for_dates() -> None:
    graph = nx.MultiDiGraph()
    e1 = EnrichedResolution(date="1626-08-23", index=0)
    e2 = EnrichedResolution(date="1626-09-21", index=0)
    h1 = HtrResolution.from_flat_id("session-3185-num-145-resolution-1")
    h2 = HtrResolution.from_flat_id("session-3185-num-157-resolution-1")
    for obj in (e1, e2, h1, h2):
        graph.add_node(obj.node_id, kind=type(obj).__name__, obj=obj)
    graph.add_edge(e1.node_id, h1.node_id, key=EDGE_KEY, kind=ALIGNED_TO)
    graph.add_edge(e2.node_id, h2.node_id, key=EDGE_KEY, kind=ALIGNED_TO)
    n = drop_hard_place_edges_for_dates(graph, {"1626-08-23"})
    assert n == 1
    assert not graph.has_edge(e1.node_id, h1.node_id, key=EDGE_KEY)
    assert graph.has_edge(e2.node_id, h2.node_id, key=EDGE_KEY)


def test_sitting_scan_span_excludes_next_heading() -> None:
    """Continuation scans belong to the sitting; next DATED_AS opens the next day."""
    graph = nx.MultiDiGraph()
    day4 = SittingDay(date="1626-11-04")
    day5 = SittingDay(date="1626-11-05")
    for sn in (449, 450, 451):
        sc = Scan(inventory="3185", scan_num=sn)
        graph.add_node(sc.node_id, kind="Scan", obj=sc)
    graph.add_node(day4.node_id, kind="SittingDay", obj=day4)
    graph.add_node(day5.node_id, kind="SittingDay", obj=day5)
    graph.add_edge("scan:3185:449", day4.node_id, key=DATED_AS, kind=DATED_AS)
    graph.add_edge("scan:3185:451", day5.node_id, key=DATED_AS, kind=DATED_AS)
    sess = Session.from_session_id("session-3185-num-184")
    graph.add_node(sess.node_id, kind="Session", obj=sess)
    graph.add_edge(sess.node_id, "scan:3185:449", key=OBSERVED_ON, kind=OBSERVED_ON)
    # 450 has no OBSERVED_ON — continuation paper, no HTR session yet
    meta = sitting_scan_span(graph, "3185", "1626-11-04")
    assert meta["span_lo"] == 449
    assert meta["span_hi_exclusive"] == 451  # before 5 Nov heading
    assert meta["span_scans"] == [449, 450]
    assert meta["span_sessions"] == ["session-3185-num-184"]
    assert meta["scans_without_session"] == [450]


def test_span_stream_concats_sessions() -> None:
    streams = {
        "session-3185-num-184": ["a1", "a2"],
        "session-3185-num-184b": ["b1"],
    }
    out = span_paragraph_stream(
        ["session-3185-num-184", "session-3185-num-184b"],
        fallback_session_id="session-3185-num-184",
        streams=streams,
    )
    assert out == ["a1", "a2", "b1"]


def test_push_align_edges_preserves_other_window() -> None:
    graph = nx.MultiDiGraph()
    seed_e = EnrichedResolution(date="1626-09-21", index=0)
    seed_h = HtrResolution.from_flat_id("session-3185-num-157-resolution-1")
    nov_e = EnrichedResolution(date="1626-11-05", index=0)
    nov_h_old = HtrResolution.from_flat_id("session-3185-num-180-resolution-1")
    nov_h_new = HtrResolution.from_flat_id("session-3185-num-181-resolution-1")
    for obj in (seed_e, seed_h, nov_e, nov_h_old, nov_h_new):
        graph.add_node(obj.node_id, kind=type(obj).__name__, obj=obj)
    graph.add_edge(seed_e.node_id, seed_h.node_id, key=EDGE_KEY, kind=ALIGNED_TO)
    graph.add_edge(nov_e.node_id, nov_h_old.node_id, key=EDGE_KEY, kind=ALIGNED_TO)
    n = push_align_edges(
        graph,
        [{
            "record_type": "wire_edge",
            "date": "1626-11-05",
            "resolution_index": 0,
            "session_id": "session-3185-num-181",
            "flat_id": "session-3185-num-181-resolution-1",
            "paragraph_start_index": 0,
            "paragraph_end_index": 0,
        }],
    )
    assert n == 1
    assert graph.has_edge(seed_e.node_id, seed_h.node_id, key=EDGE_KEY)
    assert graph.has_edge(nov_e.node_id, nov_h_new.node_id, key=EDGE_KEY)
    assert not graph.has_edge(nov_e.node_id, nov_h_old.node_id, key=EDGE_KEY)

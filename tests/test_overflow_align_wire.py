"""Unit tests for overflow ALIGNED_TO wire — no corpus / graph I/O."""

from __future__ import annotations

from sequence_graph.overflow_align_wire import (
    EDGE_KEY,
    push_wire_edges_to_graph,
    run_overflow_align_wire,
    wire_rows_from_clean_split,
    wire_rows_from_cut_gold,
)


def _apply_fixture() -> list[dict]:
    return [
        {
            "record_type": "meta",
            "inventory": "3185",
            "calendar_lo": "1626-09-21",
            "calendar_hi": "1626-10-25",
        },
        {
            "record_type": "residual_gap",
            "flat_id": "session-3185-num-148-resolution-4",
            "kind": "clean_split",
        },
        {
            "record_type": "flat_apply",
            "flat_id": "session-3185-num-148-resolution-4",
            "session_id": "session-3185-num-148",
            "cut_source": "encoder",
            "status": "ok",
            "cuts": [100],
            "flat_char_len": 250,
            "segment_char_lens": [100, 150],
        },
        {
            "record_type": "align_pair",
            "flat_id": "session-3185-num-148-resolution-4",
            "cut_source": "encoder",
            "move_kind": "MATCH",
            "order_ok": True,
            "volgnr": "1626-09-21_2",
            "read_index": 0,
        },
        {
            "record_type": "align_pair",
            "flat_id": "session-3185-num-148-resolution-4",
            "cut_source": "encoder",
            "move_kind": "MATCH",
            "order_ok": True,
            "volgnr": "1626-09-21_3",
            "read_index": 1,
        },
        {
            "record_type": "align_pair",
            "flat_id": "session-3185-num-148-resolution-4",
            "cut_source": "even_split",
            "move_kind": "MATCH",
            "order_ok": True,
            "volgnr": "1626-09-21_2",
            "read_index": 0,
        },
    ]


def _gold_fixture() -> list[dict]:
    return [
        {
            "record_type": "cut_proposal",
            "flat_id": "session-3185-num-151-resolution-2",
            "session_id": "session-3185-num-151",
            "gold_offsets": [100, 200, 300],
            "n_claimants": 4,
            # deliberately unsorted — wire must editorial-sort
            "claimant_volgnrs": [
                "1626-09-24_0",
                "1626-09-24_2",
                "1626-09-24_3",
                "1626-09-24_1",
            ],
            "flat_char_len": 400,
            "uncertain": False,
            "is_gold": True,
        },
        {
            "record_type": "cut_proposal",
            "flat_id": "session-3185-num-150-resolution-5",
            "session_id": "session-3185-num-150",
            "gold_offsets": [100, 200, 300],
            "n_claimants": 5,
            "claimant_volgnrs": [
                "1626-09-23_0",
                "1626-09-23_5",
                "1626-09-23_6",
                "1626-09-23_7",
                "1626-09-23_8",
            ],
            "flat_char_len": 500,
            "uncertain": True,
            "expected_cuts_disagrees": True,
            "is_gold": True,
        },
    ]


def test_clean_split_wires_encoder_order_ok_only() -> None:
    edges = wire_rows_from_clean_split(_apply_fixture())
    assert len(edges) == 2
    assert all(e["channel"] == "overflow_segment_dp" for e in edges)
    assert all(e["observed"] is False for e in edges)
    by_v = {e["volgnr"]: e for e in edges}
    assert by_v["1626-09-21_2"]["char_start"] == 0
    assert by_v["1626-09-21_2"]["char_end"] == 100
    assert by_v["1626-09-21_3"]["char_start"] == 100
    assert by_v["1626-09-21_3"]["char_end"] == 250


def test_cut_gold_skips_uncertain_and_sorts_claimants() -> None:
    parts = wire_rows_from_cut_gold(_gold_fixture(), include_uncertain=False)
    edges = [r for r in parts if r["record_type"] == "wire_edge"]
    skipped = [r for r in parts if r["record_type"] == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "uncertain_cut_gold"
    assert len(edges) == 4
    assert [e["volgnr"] for e in edges] == [
        "1626-09-24_0",
        "1626-09-24_1",
        "1626-09-24_2",
        "1626-09-24_3",
    ]
    assert all(e["observed"] is True for e in edges)
    assert all(e["channel"] == "overflow_cut_gold" for e in edges)
    assert edges[0]["char_start"] == 0
    assert edges[0]["char_end"] == 100
    assert edges[3]["char_start"] == 300
    assert edges[3]["char_end"] == 400


def test_uncertain_still_skips_count_mismatch_when_included() -> None:
    parts = wire_rows_from_cut_gold(_gold_fixture(), include_uncertain=True)
    skipped = [r for r in parts if r["record_type"] == "skipped"]
    assert any(r["reason"] == "claimant_segment_count_mismatch" for r in skipped)


def test_run_combines_sources() -> None:
    rows = run_overflow_align_wire(
        apply_rows=_apply_fixture(),
        gold_rows=_gold_fixture(),
    )
    meta = next(r for r in rows if r["record_type"] == "meta")
    summary = next(r for r in rows if r["record_type"] == "summary")
    assert meta["gate"] == "PASS"
    assert summary["n_clean_split_edges"] == 2
    assert summary["n_cut_gold_edges"] == 4
    assert summary["n_wire_edges"] == 6
    assert EDGE_KEY == "ALIGNED_TO:overflow"


def test_push_requires_nodes() -> None:
    import networkx as nx

    from sequence_graph.correspondence import ALIGNED_TO
    from sequence_graph.nodes import EnrichedResolution, HtrResolution

    graph = nx.MultiDiGraph()
    flat = "session-3185-num-148-resolution-4"
    e0 = EnrichedResolution(date="1626-09-21", index=2)
    e1 = EnrichedResolution(date="1626-09-21", index=3)
    h = HtrResolution.from_flat_id(flat)
    graph.add_node(e0.node_id, kind="EnrichedResolution")
    graph.add_node(e1.node_id, kind="EnrichedResolution")
    graph.add_node(h.node_id, kind="HtrResolution")

    wire = wire_rows_from_clean_split(_apply_fixture())
    n = push_wire_edges_to_graph(graph, wire)
    assert n == 2
    edges = list(graph.edges(keys=True, data=True))
    assert len(edges) == 2
    assert all(k == EDGE_KEY for _u, _v, k, _d in edges)
    assert all(d["kind"] == ALIGNED_TO for _u, _v, _k, d in edges)

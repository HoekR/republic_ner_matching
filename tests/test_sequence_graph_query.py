"""`query` answers for a session, a date and a scan -- Stage 3's third gate requirement."""

from __future__ import annotations

from sequence_graph.query import query_date, query_scan, query_session


def test_query_session_runs_and_names_the_known_t4_case(capsys):
    """session-3187-num-155 is the hand-verified T4_anchor_bracket_suspect case from
    plans/SCAN_SEQUENCE_TRACK.md -- an offset of +44 days against a shared implied window."""
    query_session("session-3187-num-155")
    out = capsys.readouterr().out
    assert "T4_anchor_bracket_suspect" in out
    assert "+44" in out


def test_query_date_shows_two_competing_session_claims(capsys):
    """1629-05-18 is labelled by TWO different sessions -- one reconciled, one contradicted --
    which running_axis's single denormalised pin cannot represent at all. This is the concrete
    demonstration of why the spine carries evidence per edge instead of one fact per date."""
    query_date("1629-05-18")
    out = capsys.readouterr().out
    assert "session-3188-num-79" in out
    assert "session-3188-num-129" in out
    assert "contradicted" in out
    assert "reconciled" in out


def test_query_scan_names_the_session_observed_there(capsys):
    query_scan("3187", 320)
    out = capsys.readouterr().out
    assert "session-3187-num-152" in out
    assert "1628-08-06" in out


def test_query_session_handles_a_session_not_on_the_graph(capsys):
    """Sidelined, post-bar, or simply not real -- must report cleanly, not raise."""
    query_session("session-4562-num-1")
    out = capsys.readouterr().out
    assert "not on the graph" in out


def test_query_date_handles_an_out_of_scope_date(capsys):
    query_date("1630-12-25")
    out = capsys.readouterr().out
    assert "not on the graph" in out


def test_query_scan_handles_an_out_of_range_scan(capsys):
    query_scan("3187", 999999)
    out = capsys.readouterr().out
    assert "not on the graph" in out

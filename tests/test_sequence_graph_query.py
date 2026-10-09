"""`query` answers for a session, a date and a scan -- Stage 3's third gate requirement.

`query_range` (Step 4.6, `plans/SEQUENCE_GRAPH_SPINE.md`) is tested separately below.
"""

from __future__ import annotations

from sequence_graph.query import _week_start, query_date, query_range, query_scan, query_session


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


def test_week_start_is_the_iso_monday():
    assert _week_start("1629-03-02") == "1629-02-26"  # 1629-03-02 is a Sunday
    assert _week_start("1629-02-26") == "1629-02-26"  # already a Monday


def test_query_range_shows_gold_coverage_without_a_solver_run(capsys):
    """1629-03-02 is gold-verified end to end; without --solver-dates, the report must say so
    from ALIGNED_TO coverage and gold tags alone, and must flag the solver as not yet attempted."""
    query_range("1629-03-02", "1629-03-02")
    out = capsys.readouterr().out
    assert "ALIGNED_TO 5/5 gold" in out
    assert "solver not yet attempted" in out
    assert "enriched:1629-03-02:0 [gold]" in out


def test_query_range_with_solver_dates_shows_proposed_cuts(capsys):
    """1626-11-16 (k_e=14, k_f=47, severe over-segmentation) must show at least one proposed cut
    (INSERTION_SPLIT) when the solver is actually run -- the resolution-level drill-down the user
    asked for, not just a session-level summary. The SOFT_CLIP ("dropped as margin content") case
    is no longer reachable on THIS day once legacy_concordance is in the graph: its one resolution
    with no gold coverage now has an existing production placement, which correctly outranks a
    fresh, unfitted solver guess -- see test_sequence_graph_consolidate.py's priority test for
    that ordering directly, rather than relying on a real day to exhibit the SOFT_CLIP path."""
    query_range("1626-11-16", "1626-11-16", solver_dates=["1626-11-16"])
    out = capsys.readouterr().out
    assert "solver run" in out
    assert "proposed cut [solver, INSERTION_SPLIT" in out
    assert "enriched:1626-11-16:0 [legacy concordance]" in out


def test_query_range_handles_an_empty_range(capsys):
    query_range("1700-01-01", "1700-01-02")
    out = capsys.readouterr().out
    assert "no in-scope dates" in out


def test_query_range_groups_multiple_weeks(capsys):
    """A 9-day range spans parts of two ISO weeks -- both WEEK headers must appear, each with the
    right Monday-start date, not one flat list."""
    query_range("1629-02-24", "1629-03-02")
    out = capsys.readouterr().out
    assert "WEEK 1629-02-19..1629-02-25" in out
    assert "WEEK 1629-02-26..1629-03-02" in out

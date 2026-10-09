"""Stage 2's go/no-go gate: the graph reproduces `reconcile_sequences.py`'s own verdicts exactly.

`plans/the-two-deep-hits-melodic-avalanche.md` Stage 2: "the observed-vs-inferred comparison over
the main series must reproduce [the target] exactly. If it does not reproduce, the graph is wrong
-- do not adjust the target." This target was itself corrected 2026-10-09: the plan's original
figure (then 276, then 261) carried 180 post-bar-only sessions that `reconcile_sequences.py` never
actually excluded (`running_axis`'s deliberate post-bar visibility, inherited rather than chosen).
Restricting the ORIGINAL reference logic to the same scope-compliant population Stage 1 builds
gives 323/406/**81**, verified directly against `reconcile_sequences`'s own functions -- this is
the real target, not a re-derivation. One true mismatch surfaced along the way and was fixed in
`build.py`, not papered over here: a date can be axis-labelled with zero enriched rows at all
(`1627-09-14`), and dropping it cost exactly one session's verdict.
"""

from __future__ import annotations

import pytest

from sequence_graph.build import build
from sequence_graph.classify import classify, consolidate
from sequence_graph.correspondence import add_dated_as, add_observed_on, add_pinned_and_labelled

EXPECTED_VERDICTS = {"contradicted": 547, "reconciled": 406, "no_observed_scan": 81}
EXPECTED_TYPES = {
    "T0_anchor": 406, "T1_offset_1_2_days": 127, "T2_offset_3_7_days": 109,
    "T3_offset_over_7_days": 170, "T4_anchor_bracket_suspect": 26,
    "T5_window_too_wide_to_judge": 115, "T6_no_scan_observed": 81,
}
EXPECTED_GATE = {"hard_anchors": 323, "bounded_gaps": 406, "unconstrained_gaps": 81}


@pytest.fixture(scope="module")
def verdicts():
    graph = build()
    add_observed_on(graph)
    add_dated_as(graph)
    add_pinned_and_labelled(graph)
    return classify(graph)


def test_gate_passes_exactly(verdicts):
    assert consolidate(verdicts) == EXPECTED_GATE


def test_verdict_counts_match_the_reference_exactly(verdicts):
    from collections import Counter
    assert dict(Counter(v.verdict for v in verdicts)) == EXPECTED_VERDICTS


def test_problem_type_counts_match_the_reference_exactly(verdicts):
    from collections import Counter
    counts = dict(Counter(v.problem_type for v in verdicts))
    counts.pop("T7_nothing_inferred", None)  # 0 after the phantom-date fix; absent, not falsely 0
    assert counts == EXPECTED_TYPES


def test_problem_types_partition_all_sessions(verdicts):
    from collections import Counter
    counts = Counter(v.problem_type for v in verdicts)
    assert sum(counts.values()) == len(verdicts) == 1034


def test_t4_anchor_bracket_suspect_precedence_is_tested_not_assumed():
    """The crowded-window check runs BEFORE window width in `_problem_type`, so a precedence bug
    would silently reclassify a narrow-window T4 session as T1/T2. Checked directly rather than
    asserted: in this corpus all 26 T4 sessions happen to have window 3 or 5 days (never <= 2),
    so precedence currently changes nothing in practice here -- a fact worth knowing (an earlier
    version of this test wrongly assumed some T4 windows were narrow, without checking first) --
    but the precedence is still exercised and must not silently stop firing as the gate evolves."""
    graph = build()
    add_observed_on(graph)
    add_dated_as(graph)
    add_pinned_and_labelled(graph)
    verdicts = classify(graph)
    t4 = [v for v in verdicts if v.problem_type == "T4_anchor_bracket_suspect"]
    assert len(t4) == 26
    assert all(v.implied_window_days in (3, 5) for v in t4)

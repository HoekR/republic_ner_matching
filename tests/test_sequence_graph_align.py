"""The DAG aligner's four fixed defects, on synthetic sequences -- no corpus access needed.

Stage 4 of `plans/the-two-deep-hits-melodic-avalanche.md` (`~/.claude/plans/`). See
`sequence_graph/align.py`'s module docstring for what each defect was and how it's fixed.
"""

from __future__ import annotations

from sequence_graph.align import (
    DELETION_GAP,
    INSERTION_SPLIT,
    MATCH,
    SOFT_CLIP,
    CostModel,
    align_bracket,
)


def zero_overlap(_i: int, _j: int) -> float:
    return 0.0


def test_perfect_match_all_matched_at_zero_extra_cost():
    """Five ref items, five read items, full overlap everywhere on the diagonal only ->
    every step should be a MATCH, nothing abstained, nothing free."""
    def overlap(i: int, j: int) -> float:
        return 5.0 if i == j else 0.0

    result = align_bracket(5, 5, overlap, CostModel())
    assert not result.abstained
    assert [p.kind for p in result.pairs] == [MATCH] * 5
    assert [p.ref_index for p in result.pairs] == [0, 1, 2, 3, 4]
    assert [p.read_index for p in result.pairs] == [0, 1, 2, 3, 4]


def test_defect_1_no_edge_skips_intermediate_items():
    """Old bug: an all-forward-pairs construction let a MATCH jump straight from ref[0] to
    read[5], silently absorbing read[1..4] at one MATCH's cost instead of five gap moves.
    Here only (i-1,j-1)/(i-1,j)/(i,j-1) exist, so matching ref[0] to read[5] (both carrying
    the only real overlap) must still pay for the four read items in between as separate
    SOFT_CLIP/INSERTION_SPLIT steps, not absorb them for free into one MATCH."""
    def overlap(i: int, j: int) -> float:
        return 10.0 if (i, j) == (0, 5) else 0.0

    result = align_bracket(1, 6, overlap, CostModel(abstain_threshold=None))
    match_pairs = [p for p in result.pairs if p.kind == MATCH]
    assert len(match_pairs) == 1
    assert match_pairs[0].ref_index == 0
    # read items 0..4 must each appear as their own step -- none are skipped by the match.
    read_indices_consumed = sorted(p.read_index for p in result.pairs if p.read_index is not None)
    assert read_indices_consumed == [0, 1, 2, 3, 4, 5]


def test_defect_2_soft_clip_discriminates_from_insertion_split():
    """Both INSERTION_SPLIT and SOFT_CLIP sit on the same (i, j-1)->(i, j) move. A read item
    with no overlap at all to the current ref item must be typed SOFT_CLIP (contamination);
    a read item that does share overlap must be typed INSERTION_SPLIT (a real split of the
    current ref item), even though both consume a read item without advancing ref.

    `ref[0]`'s overlap with `read[0]` is decisive (5.0, clamped to the cost floor) so the DP
    has no incentive to skip it in favour of a later direct match -- `split_discount` is what
    actually makes the discriminator reachable at all: without it, `insertion_cost` and
    `match_cost` are the same formula, and `match(a) + insertion(b) >= insertion(b)` always
    holds, so the DP would rather skip read 0 as a free leading clip and match ref 0 straight
    to read 1 than ever choose MATCH-then-SPLIT. See `CostModel.insertion_cost`'s docstring."""
    overlap_table = {
        (0, 0): 5.0,
        (0, 1): 1.0,   # modest overlap -- a split of ref 0, not a fresh match on its own
        (0, 2): 0.0,   # contamination
        (1, 3): 5.0,
    }

    def overlap(i: int, j: int) -> float:
        return overlap_table.get((i, j), 0.0)

    model = CostModel(base_match=2.0, match_lambda=1.0, epsilon=0.05, soft_clip_cost=0.5, split_discount=0.3)
    result = align_bracket(2, 4, overlap, model)
    by_read = {p.read_index: p.kind for p in result.pairs if p.read_index is not None}
    assert by_read[0] == MATCH
    assert by_read[1] == INSERTION_SPLIT  # shares entities with ref 0 -> split, not contamination
    assert by_read[2] == SOFT_CLIP        # shares nothing -> contamination
    assert by_read[3] == MATCH


def test_defect_3_free_leading_and_trailing_read_only_runs():
    """Read items before the first match and after the last match must cost nothing and must
    not force a DELETION_GAP or paid SOFT_CLIP step on the ref side."""
    def overlap(i: int, j: int) -> float:
        return 5.0 if (i, j) == (0, 2) else 0.0

    result = align_bracket(1, 5, overlap, CostModel())
    assert not result.abstained
    assert result.n_leading_free == 2   # read 0, 1 before the match
    assert result.n_trailing_free == 2  # read 3, 4 after the match
    # the only real cost in the path is the match itself.
    match_pairs = [p for p in result.pairs if p.kind == MATCH]
    assert len(match_pairs) == 1


def test_defect_3_abstains_when_best_path_exceeds_threshold():
    """No overlap anywhere -> every ref item costs a full DELETION_GAP. With a threshold set
    below that total, the bracket must abstain rather than emit a forced placement."""
    model = CostModel(gap_cost=1.0, abstain_threshold=2.5)
    result = align_bracket(5, 5, zero_overlap, model)
    assert result.abstained
    assert result.pairs == ()


def test_defect_3_does_not_abstain_when_threshold_is_none():
    model = CostModel(gap_cost=1.0, abstain_threshold=None)
    result = align_bracket(5, 5, zero_overlap, model)
    assert not result.abstained


def test_defect_4_cost_keeps_scaling_with_overlap_past_one_unit():
    """Old bug: `max(0.1, 2.0 + match_cost)` with `match_bonus=-2.0` floors immediately, so one
    shared entity and five both cost 0.1 -- additional evidence stops mattering. Here cost must
    strictly decrease as overlap grows, until the floor is genuinely reached."""
    model = CostModel(base_match=2.0, match_lambda=1.0, epsilon=0.05)
    cost_one = model.match_cost(overlap=1.0)
    cost_more = model.match_cost(overlap=1.5)
    cost_five = model.match_cost(overlap=5.0)  # past the point where the floor is reached
    assert cost_one > cost_more > cost_five
    assert cost_five == model.epsilon  # five units of overlap genuinely clears the base cost


def test_defect_4_floor_is_the_true_floor_not_an_early_plateau():
    model = CostModel(base_match=2.0, match_lambda=1.0, epsilon=0.05)
    # 1.9 and 1.99 units of overlap are both below the point where base - lambda*overlap
    # would cross epsilon -- they must NOT be collapsed to the same cost as 5.0 units.
    assert model.match_cost(1.9) != model.match_cost(5.0)
    assert model.match_cost(1.9) > model.epsilon


def test_free_trailing_cannot_discard_evidence_bearing_content():
    """Regression for the `1629-03-02` finding (2026-10-09): a genuine match deep in a trailing
    run must not be waved through for free just because an earlier, evidence-free item makes
    bailing out look cheaper. ref1 matches read1 (strong); read2 carries no evidence anywhere;
    read3 genuinely matches ref3 (weaker, but real) -- the old unconditional free-trailing cutoff
    discarded ref3/read3 entirely (and read2, read4) because dp[n_ref][1] was cheaper than paying
    to reach read3. Now the cutoff may only start inside the genuinely evidence-free tail."""
    overlap_table = {(1, 1): 5.0, (3, 3): 1.0}

    def overlap(i: int, j: int) -> float:
        return overlap_table.get((i, j), 0.0)

    model = CostModel(base_match=2.0, match_lambda=1.0, epsilon=0.05, gap_cost=1.0, soft_clip_cost=0.8)
    result = align_bracket(5, 5, overlap, model)
    matched_refs = {p.ref_index for p in result.pairs if p.kind == MATCH}
    assert matched_refs == {1, 3}  # both real matches survive -- neither discarded for free
    assert result.n_trailing_free == 1  # read4 alone is genuinely evidence-free and stays free;
    # read2 (between the two matches) and read3 (the second match) are not, and are not skipped.


def test_free_trailing_still_applies_to_a_genuinely_evidence_free_tail():
    """The gate must not become so strict that true margin content stops being free."""
    overlap_table = {(0, 0): 5.0}

    def overlap(i: int, j: int) -> float:
        return overlap_table.get((i, j), 0.0)

    result = align_bracket(1, 4, overlap, CostModel())
    assert result.n_trailing_free == 3  # reads 1, 2, 3 carry no evidence anywhere -- still free


def test_deletion_gap_is_routine_and_cheap_not_an_edge_case():
    """A ref item with no matching read content at all should take a DELETION_GAP, not get
    dragged into a bad MATCH -- 'an enriched resolution with no distinct HTR match is routine.'"""
    model = CostModel(base_match=2.0, match_lambda=1.0, gap_cost=0.3, soft_clip_cost=5.0)
    result = align_bracket(1, 1, zero_overlap, model)
    assert [p.kind for p in result.pairs] == [DELETION_GAP]

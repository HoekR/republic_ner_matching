"""The DAG aligner. Stage 4 of `plans/the-two-deep-hits-melodic-avalanche.md` (`~/.claude/plans/`).

**Scope decided with the user, 2026-10-09, before any of this was written** (the plan's own "four
decisions" list):

1. `MENTIONS` row shape: checked live (`place_overlap_1626_1630` / `org_overlap_1626_1630` /
   `per_overlap_1626_1630`) -- raw match-candidate rows keyed by `volgnr` (editorial) and
   `paragraph_id` (HTR), carrying **no precomputed IDF-weighted score column**. There is nothing to
   read off the shelf; a cost function has to aggregate them. Reused rather than reimplemented:
   `build_alignment_new.build_overlap_lookups` / `calculate_idf_weights` / `score_typed_overlap` --
   this module supplies only the `paragraph_id -> flat_id` map (from `paragraph_axis_1626_1630`'s
   own `entity_source_paragraph_ids`, which already exists and makes the legacy annotation-file
   parse unnecessary) and the DP mechanics.
2. **Cost fitting: deferred.** Build the aligner mechanism first with the existing production
   entity-overlap score as an *unfitted* signal; calibrating `MATCH_LAMBDA`/`BASE_MATCH_COST`/etc.
   against gold is explicitly left open, not silently decided here. `CostModel`'s module docstring
   says this again where it is most likely to be read before being misused as calibrated.
3. **First population: a clean bracket, not the stress case.** `1629-03-02`
   (`session-3188-num-58`, inventory 3188) -- `k_e = k_f = 5`, `diff_ke_kf = 0`, the single cleanest
   day in `boundary_gold_sample` (no other gold day has zero split/collapse at all), gold-annotated.
   A baseline test that the mechanism works at all, not a stress test of 3187:305->320.
4. **Benchmark: standalone.** Scored on `separated` via `label_separation()` against
   `uniform_start_paragraphs`, plus gold exact agreement for this one bracket. Not compared against
   `align_session`'s 0.957/0.962, `align_entity_mentions`'s closed-negative result, or `segment_gap`'s
   0.628 baseline -- that comparison is explicitly deferred, per decision 4.

**The four defects this fixes, relative to the demo the plan describes** (not present in this
repo -- rebuilt from the plan's specification, not patched from existing code):

1. **O(NM) edges, not O(N**2**M**2**).** Only three moves from cell `(i, j)`: `(i+1, j+1)` MATCH,
   `(i+1, j)` DELETION_GAP, `(i, j+1)` INSERTION_SPLIT/SOFT_CLIP. No all-pairs edge can let a match
   skip over intermediate items at one MATCH's cost.
2. **SOFT_CLIP has a real discriminator.** Both INSERTION_SPLIT and SOFT_CLIP sit on `(i, j+1)` --
   both consume a read (HTR) item without consuming a ref (enriched) item. The split shares entities
   with the ref item just placed (`ref[i-1]`, the one `i` is currently sitting next to); contamination
   shares none. Both costs are computed and the cheaper one wins, with its type recorded -- this is
   the project's first representation of margin/praesentes contamination, named but never built
   before (`plans/ARCHIVAL_PROVENANCE_TRACK.md`'s secret-session hijack is a different, session-level
   version of the same "stray content gets force-fit" family).
3. **Semi-global, with free end gaps and abstention.** Leading read-only moves are free
   (`dp[0][j] = 0`): HTR material before the bracket's first matched item never did belong to it.
   Trailing read-only moves are free by never extending the path past the best `dp[n][j]` -- nothing
   forces the aligner to account for every read item, which is what let the old demo's pinned-both-
   ends form forbid abstention (the measured win: gold exact agreement 0.5431 -> 0.6486 when
   `segment_day` was given partial abstention instead of forced placement). `abstain_threshold`
   extends the same idea to the whole bracket: too costly a best path abstains outright rather than
   emitting a forced, low-confidence alignment.
4. **Cost arithmetic that does not collapse evidence.** The old form, `max(0.1, 2.0 + match_cost)`
   with `match_bonus = -2.0`, floors immediately: one shared entity and five both cost 0.1, so
   additional evidence stops mattering as soon as there is any. Here, `base - lambda * overlap`
   floored at `epsilon` keeps scaling with `overlap` until the floor is actually reached.

Usage (the one scoped run, decision 3 above):
    uv run python -m sequence_graph.align --date 1629-03-02
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pandas as pd

from data_io import load, resolve
from running_axis.stream import parse_flat_id

MATCH = "MATCH"
DELETION_GAP = "DELETION_GAP"
INSERTION_SPLIT = "INSERTION_SPLIT"
SOFT_CLIP = "SOFT_CLIP"


@dataclass(frozen=True)
class CostModel:
    """**Not fitted.** Decision 2 (2026-10-09): deferred, kept open rather than hand-set-and-
    forgotten. These are structural placeholders chosen only to preserve the right *ordering*
    (more shared evidence costs less; a routine deletion is cheap; a contaminated read item is
    flat-rate) -- not calibrated values, and must not be read as a measured result. Fitting them
    (on gold, held out by day, per `TRACK_S_ANCHOR_SHIFTING.md`'s own open question) is the next
    session's work, not this one's.
    """

    base_match: float = 2.0
    match_lambda: float = 1.0
    gap_cost: float = 1.0
    soft_clip_cost: float = 0.8
    split_discount: float = 0.3
    epsilon: float = 0.05
    abstain_threshold: float | None = None

    def match_cost(self, overlap: float) -> float:
        return max(self.epsilon, self.base_match - self.match_lambda * overlap)

    def insertion_cost(self, overlap: float) -> float:
        """Deliberately **not** the same formula as `match_cost`, even though both price "this
        read item belongs with that ref item": a split is additional evidence for a resolution
        already placed, not a fresh independent correspondence, so it must be cheaper than
        re-matching would be -- otherwise the free leading/trailing row (defect 3, `dp[0][j] = 0`
        for every `j`) always lets the DP skip ahead and match the *later* read item directly
        instead of ever choosing MATCH-then-SPLIT, since `match(a) + insertion(b) >= insertion(b)`
        whenever `insertion == match`. `split_discount` is scaled `base_match` before the overlap
        term, not the floor itself, so a split with *zero* overlap still costs as much as
        `soft_clip_cost` should decide (see the discriminator: `insertion_cost(0)` must stay above
        `soft_clip_cost` for contamination to still win when there is no shared evidence at all)."""
        return max(self.epsilon, self.base_match * self.split_discount - self.match_lambda * overlap)


@dataclass(frozen=True)
class AlignedPair:
    """One step of the chosen path. `ref_index`/`read_index` are `None` when this step did not
    consume that side (DELETION_GAP has no read_index; INSERTION_SPLIT/SOFT_CLIP have no ref_index)."""

    kind: str
    ref_index: int | None
    read_index: int | None
    cost: float


@dataclass(frozen=True)
class AlignmentResult:
    pairs: tuple[AlignedPair, ...]
    total_cost: float
    n_leading_free: int
    n_trailing_free: int
    abstained: bool

    def match_for_ref(self, ref_index: int) -> int | None:
        """The read index MATCHed to this ref item, if any (not DELETION_GAP)."""
        for pair in self.pairs:
            if pair.kind == MATCH and pair.ref_index == ref_index:
                return pair.read_index
        return None


def align_bracket(
    n_ref: int,
    n_read: int,
    overlap: Callable[[int, int], float],
    cost: CostModel = CostModel(),
) -> AlignmentResult:
    """Align a ref sequence (length `n_ref`, the editorial/enriched side, the stable backbone --
    every sitting day is recorded, nihil-actum included) against a read sequence (length `n_read`,
    the HTR/archive side, which drifts and under-segments). `overlap(i, j)` scores shared evidence
    between `ref[i]` and `read[j]`; it is the only data dependency, so this function is directly
    testable on synthetic sequences with no corpus access.

    **No move ever reorders a read item (user clarification, 2026-10-09).** Unlike a Levenshtein-
    style edit distance, an HTR resolution can never be relocated out of its position in the flat
    stream -- there is no "insert move" that moves content around. Only three transitions exist,
    `(i+1,j+1)`/`(i+1,j)`/`(i,j+1)`, so the read index `j` never decreases and is consumed at most
    once each; a read item is MATCHed, attached to the ref item just placed (`INSERTION_SPLIT`), or
    dropped as margin content such as an attendance list or a date heading (`SOFT_CLIP`) -- never
    moved. Reordering isn't a move that got left out; it cannot be expressed in this DP at all
    (regression: `test_read_items_are_never_reordered_only_matched_split_or_dropped`).

    **Caveat, stated rather than assumed away:** the flat stream this trusts as fixed-order is
    itself an interpretation of HTR region detection, which can mis-order or mis-classify a region
    (heading, page number, attendance list, marginalia vs. body text) -- there is no single
    canonical reading order inherent to a page. For all practical purposes this project treats that
    stream's order as fixed. If region detection is actually wrong for some bracket, that is a
    separate upstream defect to flag and fix at the source (never something this move set should
    try to route around by reordering).

    `dp[i][j]` = min cost aligning `ref[0:i]` with `read[0:j]`. Three predecessors only -- defect 1.

    **Free end gaps are evidence-gated, not unconditional (2026-10-09, same session, found by
    running the first real bracket).** The first cut let *any* leading/trailing run go free
    regardless of content, which discarded a genuine match (`1629-03-02`'s ref3/read3 pair,
    overlap 1.027, cheaper than deletion) because reaching it meant paying to cross an
    evidence-free read item first, and bailing out for free was cheaper than paying that toll --
    confirmed by hand-deriving the discarded path's real cost (5.489) against the DP's chosen one
    (4.916). The fix is not a penalty on trailing content (that would also drag genuinely
    unrelated margin material into forced placements, reopening the exact pathology semi-global
    alignment exists to avoid) -- it is narrowing *what counts as free* to only the content that
    earns it: a read item is free leading/trailing material only if it carries zero overlap
    against every ref item, checked directly, not assumed from position. One item with real
    evidence breaks the free run from that point on; nothing after it in that run is free either,
    since the margin phase is over.
    """
    neg_inf = float("inf")
    dp = [[neg_inf] * (n_read + 1) for _ in range(n_ref + 1)]
    move: list[list[tuple[str, float] | None]] = [[None] * (n_read + 1) for _ in range(n_ref + 1)]

    has_evidence = [any(overlap(i, j) > 0 for i in range(n_ref)) for j in range(n_read)]

    leading_free_len = 0
    for j in range(n_read):
        if has_evidence[j]:
            break
        leading_free_len = j + 1

    trailing_free_start = n_read
    for j in range(n_read - 1, -1, -1):
        if has_evidence[j]:
            break
        trailing_free_start = j

    dp[0][0] = 0.0
    for j in range(1, n_read + 1):
        if j <= leading_free_len:
            dp[0][j] = 0.0  # genuinely evidence-free margin -- free, defect 3's leading half
            move[0][j] = (SOFT_CLIP, 0.0)
        else:
            # Past the evidence-free prefix: no ref item exists yet to split against, so the
            # only honest charge is the full SOFT_CLIP cost -- never a free pass, even for a
            # later item that itself has no evidence (the margin phase already ended).
            dp[0][j] = dp[0][j - 1] + cost.soft_clip_cost
            move[0][j] = (SOFT_CLIP, cost.soft_clip_cost)
    for i in range(1, n_ref + 1):
        dp[i][0] = dp[i - 1][0] + cost.gap_cost
        move[i][0] = (DELETION_GAP, cost.gap_cost)

    for i in range(1, n_ref + 1):
        for j in range(1, n_read + 1):
            best_cost = neg_inf
            best_move: tuple[str, float] | None = None

            match_c = dp[i - 1][j - 1] + cost.match_cost(overlap(i - 1, j - 1))
            if match_c < best_cost:
                best_cost, best_move = match_c, (MATCH, cost.match_cost(overlap(i - 1, j - 1)))

            del_c = dp[i - 1][j] + cost.gap_cost
            if del_c < best_cost:
                best_cost, best_move = del_c, (DELETION_GAP, cost.gap_cost)

            # defect 2: both options on (i, j-1) -> (i, j) are computed, cheaper wins, typed.
            split_overlap = overlap(i - 1, j - 1)  # entities shared with the ref item just left of i
            split_cost = cost.insertion_cost(split_overlap)
            clip_cost = cost.soft_clip_cost
            if split_cost <= clip_cost:
                ins_c, ins_kind, ins_step_cost = dp[i][j - 1] + split_cost, INSERTION_SPLIT, split_cost
            else:
                ins_c, ins_kind, ins_step_cost = dp[i][j - 1] + clip_cost, SOFT_CLIP, clip_cost
            if ins_c < best_cost:
                best_cost, best_move = ins_c, (ins_kind, ins_step_cost)

            dp[i][j] = best_cost
            move[i][j] = best_move

    # defect 3, trailing half: free cutoff points are restricted to the genuinely evidence-free
    # trailing run -- anything with real overlap must be resolved through the recurrence above
    # (which already costs MATCH/DELETION_GAP/INSERTION_SPLIT/SOFT_CLIP correctly), never waved
    # through for free just because it happens to sit at the end.
    best_j = min(range(trailing_free_start, n_read + 1), key=lambda j: dp[n_ref][j])
    total_cost = dp[n_ref][best_j]
    n_trailing_free = n_read - best_j

    abstained = cost.abstain_threshold is not None and total_cost > cost.abstain_threshold
    if abstained:
        return AlignmentResult(
            pairs=(), total_cost=total_cost, n_leading_free=0,
            n_trailing_free=n_trailing_free, abstained=True,
        )

    pairs: list[AlignedPair] = []
    i, j = n_ref, best_j
    while i > 0 or j > 0:
        kind, step_cost = move[i][j]
        if kind == MATCH:
            pairs.append(AlignedPair(MATCH, i - 1, j - 1, step_cost))
            i, j = i - 1, j - 1
        elif kind == DELETION_GAP:
            pairs.append(AlignedPair(DELETION_GAP, i - 1, None, step_cost))
            i -= 1
        else:  # INSERTION_SPLIT or SOFT_CLIP
            pairs.append(AlignedPair(kind, None, j - 1, step_cost))
            j -= 1
    pairs.reverse()

    n_leading_free = 0
    for pair in pairs:
        if pair.kind in (INSERTION_SPLIT, SOFT_CLIP) and pair.ref_index is None:
            n_leading_free += 1
        else:
            break

    return AlignmentResult(
        pairs=tuple(pairs), total_cost=total_cost,
        n_leading_free=n_leading_free, n_trailing_free=n_trailing_free, abstained=False,
    )


# --- Real-data adapter: the one scoped run (decision 3), nothing more. ---

def _paragraph_to_resolution_map() -> dict[str, str]:
    """`paragraph_id -> flat_id`, from `paragraph_axis_1626_1630`'s own `entity_source_paragraph_ids`
    -- the same fact the legacy `build_paragraph_to_resolution_map` parsed out of annotation files,
    already sitting in a dataset this project builds and reads elsewhere. Not reimplemented, just
    read from a different, already-correct source."""
    mapping: dict[str, str] = {}
    for row in load("paragraph_axis_1626_1630"):
        for paragraph_id in row.get("entity_source_paragraph_ids") or []:
            mapping[str(paragraph_id)] = row["flat_id"]
    return mapping


def build_entity_overlap_scorer() -> Callable[[str, str], float]:
    """`(volgnr, flat_id) -> combined overlap score`, via the production scorer -- reused, not
    reimplemented: `build_alignment_new.build_overlap_lookups` / `calculate_idf_weights` /
    `score_typed_overlap`. Loads the corpus-wide overlap tables once; callers key into the result.
    """
    from build_alignment_new import PERSON_SIGNAL_SCALE, build_overlap_lookups, calculate_idf_weights, score_typed_overlap

    places_df = pd.read_excel(resolve("place_overlap_1626_1630"))
    orgs_df = pd.read_excel(resolve("org_overlap_1626_1630"))
    persons_df = pd.read_excel(resolve("per_overlap_1626_1630"))
    paragraph_to_resolution = _paragraph_to_resolution_map()

    place_lookup, org_lookup, person_lookup, _combined = build_overlap_lookups(
        places_df, orgs_df, paragraph_to_resolution, persons_df=persons_df,
    )
    all_overlaps = pd.concat(
        [places_df[["name"]], orgs_df[["name"]], persons_df[["name"]]], ignore_index=True,
    )
    idf_weights = calculate_idf_weights(all_overlaps)

    def scorer(volgnr: str, flat_id: str) -> float:
        _anchor, _person, combined = score_typed_overlap(
            volgnr, flat_id, place_lookup, org_lookup, person_lookup, idf_weights,
            person_signal_scale=PERSON_SIGNAL_SCALE,
        )
        return combined

    return scorer


def _day_paragraph_stream(date: str) -> list[str]:
    """This date's paragraph axis rows, in stream order -- the same order `segment_day` assigns
    `paragraph_start_index` over. Ordered by each row's own HTR position (resolution_num, then
    para_index), not by dict/file order."""
    rows = [row for row in load("paragraph_axis_1626_1630") if row["date"] == date]

    def key(row: dict) -> tuple[int, int, int]:
        inventory, session_num, resolution_num = parse_flat_id(row["flat_id"])
        return (session_num, resolution_num, row["para_index"])

    rows.sort(key=key)
    return [row["flat_id"] for row in rows]


def run_bracket(date: str, cost: CostModel = CostModel()) -> dict:
    """The one scoped run: align one gold-annotated day's enriched resolutions against its HTR
    resolutions, then score via `label_separation` against `uniform_start_paragraphs` -- the
    standing gate, not an alternative one invented for this run."""
    from scripts.separated_accuracy_eval import label_separation, uniform_start_paragraphs

    gold = load("boundary_gold_sample")
    day = next((row for row in gold["days"] if row["date"] == date), None)
    if day is None:
        raise ValueError(f"{date} is not in boundary_gold_sample")

    flat_ids = sorted(day["flat_ids"], key=lambda fid: parse_flat_id(fid)[2])
    enriched_ids = list(day["enriched_ids"])
    n_ref, n_read = len(enriched_ids), len(flat_ids)

    scorer = build_entity_overlap_scorer()
    volgnrs = [f"{date}_{index}" for index in range(n_ref)]

    overlap_cache: dict[tuple[int, int], float] = {}

    def overlap(i: int, j: int) -> float:
        key = (i, j)
        if key not in overlap_cache:
            overlap_cache[key] = scorer(volgnrs[i], flat_ids[j])
        return overlap_cache[key]

    result = align_bracket(n_ref, n_read, overlap, cost)

    paragraph_stream = _day_paragraph_stream(date)
    flat_first_paragraph: dict[int, int] = {}
    for position, flat_id in enumerate(paragraph_stream):
        read_idx = flat_ids.index(flat_id) if flat_id in flat_ids else None
        if read_idx is not None and read_idx not in flat_first_paragraph:
            flat_first_paragraph[read_idx] = position

    predictions: list[dict] = []
    if not result.abstained:
        last_position = 0
        for ref_index in range(n_ref):
            read_index = result.match_for_ref(ref_index)
            if read_index is not None and read_index in flat_first_paragraph:
                last_position = flat_first_paragraph[read_index]
            predictions.append({
                "enriched_date": date,
                "paragraph_start_index": last_position,
                "paragraph_end_index": last_position,
            })

    frame = pd.DataFrame(predictions)
    scored = label_separation(frame) if not frame.empty else frame
    null_positions = uniform_start_paragraphs(len(paragraph_stream), n_ref)

    # Gold records one boundary per resolution transition, keyed by the flat_id it introduces,
    # not one per enriched index -- `1629-03-02` gives 4 cuts for 5 resolutions, missing only the
    # last (no `end_of_last_resolution` marker in this file, unlike some other gold days). Since
    # this day is 1:1 and 1-paragraph-per-resolution by construction (k_e == k_f == 5), the
    # implied final start is one past the last recorded cut -- true for this specific validated
    # day, not asserted as a general rule.
    # Not every boundary names a flat_id -- `1626-02-28`'s gold records `unit: "out_of_range"`
    # entries with no `flat_id` at all (gold genuinely could not place them), found by running
    # this on a spread of real days rather than only the one clean validation case. Those entries
    # carry no position to read, not a position of 0 or similar; skipped, not guessed.
    flat_to_gold_start: dict[str, int] = {}
    for boundary in day["boundaries"]:
        if boundary["kind"] in ("cut", "end_of_last_resolution") and boundary.get("flat_id"):
            flat_to_gold_start.setdefault(boundary["flat_id"], boundary["paragraph_stream_index"])
    gold_start_positions = [flat_to_gold_start.get(fid) for fid in flat_ids]
    known_positions = [p for p in gold_start_positions if p is not None]
    if gold_start_positions and gold_start_positions[-1] is None and known_positions:
        gold_start_positions[-1] = max(known_positions) + 1

    exact_agreement = None
    if predictions and None not in gold_start_positions:
        predicted_starts = [p["paragraph_start_index"] for p in predictions]
        exact_agreement = sum(
            p == g for p, g in zip(predicted_starts, gold_start_positions)
        ) / n_ref

    return {
        "date": date,
        "k_e": n_ref,
        "k_f": n_read,
        "abstained": result.abstained,
        "total_cost": result.total_cost,
        "moves": [(p.kind, p.ref_index, p.read_index) for p in result.pairs],
        "separated_count": int(scored["separated"].sum()) if not scored.empty else 0,
        "uniform_null_positions": null_positions,
        "exact_agreement": exact_agreement,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="1629-03-02", help="the scoped first bracket (decision 3)")
    args = parser.parse_args()

    report = run_bracket(args.date)
    print(f"date: {report['date']}  k_e={report['k_e']}  k_f={report['k_f']}")
    print(f"abstained: {report['abstained']}  total_cost: {report['total_cost']:.3f}")
    for kind, ref_i, read_i in report["moves"]:
        print(f"  {kind:<16} ref={ref_i}  read={read_i}")
    print(f"separated_count: {report['separated_count']} / {report['k_e']}")
    print(f"uniform-null start positions (same gap, no evidence): {report['uniform_null_positions']}")
    print(f"gold exact agreement: {report['exact_agreement']}")


if __name__ == "__main__":
    main()

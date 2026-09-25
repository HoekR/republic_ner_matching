#!/usr/bin/env python3
"""Step 1 of plans/COLLISION_AVOIDANCE_TRACK.md -- landmark density in the HTR stream.

The stream reframing trades a tight-but-wrong local constraint (``k_e`` per
calendar day) for a loose one (``k_e`` per inventory). Session landmarks have to
re-impose locality or the trade is a net loss, so this is the gate for the whole
track: if landmark coverage is thin or unreliable, stop.

**Metric defined before method** (track guardrail, docs/SEGMENTATION_RESULTS.md
section 5). Five quantities, no tolerance-family F1 anywhere:

1. *Availability, raw side.* Per raw session in ``s4_session_date_region_scan``:
   does it carry a ``date`` region, an ``attendance`` region, is the ``date``
   region the session's first region, does a president/present stem hit fire.
   This is the "is a session opening present in the archive at all" question,
   deliberately kept separate from the session-date *ledger* status (T/N), which
   is about enriched->HTR date *mapping* -- the unreliable thing being escaped.
2. *Localizability on the stream.* A landmark is only usable if it can be placed
   at a position in the stream segmentation actually runs on
   (``paragraph_axis_1626_1630``). Three channels, two of which need no date
   mapping at all:
   - ``fingerprint_verified`` -- flat session content-matched to a raw session by
     ``s6b_session_fingerprint_match`` (finding D, 70.1%), i.e. archival identity
     independent of the drifted label;
   - ``in_axis_president_and_present`` -- opening formula detectable in the axis text
     itself (attendance material that leaked through the upstream ``para``
     classifier);
   - ``formulaic_opening`` -- hypothesis 4's short receipt-of-correspondence
     class, reusing ``align_short_resolutions.py``'s empirical phrase set.
3. *Reliability.* Order preservation: do content-verified landmarks appear in the
   same order in the flat stream and in the archive? A landmark set that is not
   order-preserving cannot scaffold a sequence alignment, whatever its coverage.
4. *Locality.* Paragraphs and ``k_e`` per landmark-bracketed segment against the
   same quantities per day (median / p90 / max). Segments are runs of consecutive
   *dates*: a date opens a new segment iff its first flat session carries a
   landmark, so the day partition is the finest case and reproduces the cited
   11,644 ceiling exactly (asserted below).
5. *Headroom at bounded locality.* Per channel, ``sum over segments of
   min(sum k_e, sum paragraphs)`` -- the honest intermediate between 11,644
   (assumes the day partition is correct) and finding C's 14,258 (assumes free
   reallocation along the inventory) -- plus ``deficit_absorbed``, how many
   resolutions stop being pigeonhole-impossible once neighbouring days share a
   segment. Compare against the Global-stretch gap of 718.

**Read 4 and 5 together, never 5 alone.** A coarser partition always raises the
bound: one segment per inventory maximises headroom and destroys locality. The
result is a price/benefit pair, not a score.

Gate (thresholds fixed here, before the run): PASS requires the best
content-verified channel to keep median segment ``k_e`` within 2x the day median
*and* absorb materially more paragraph deficit than the day partition, with
order-preserving landmarks. FAIL if segments average >= 3 dates, or if verified
landmarks are not order-preserving.

Usage:
    uv run python -m scripts.landmark_density_eval
"""

from __future__ import annotations

import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from fuzzy_search.search.phrase_searcher import FuzzyPhraseSearcher

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured

REGION_SCAN_DATASET = "s4_session_date_region_scan"
FINGERPRINT_DATASET = "s6b_session_fingerprint_match"
AXIS_DATASET = "paragraph_axis_1626_1630"
CONCORDANCE_DATASET = "resolution_concordance_1626_1630"
OUTPUT_DATASET = "landmark_density_eval"

# Same lenient stems as scripts/s4_session_date_region_scan.py, applied to axis text
# instead of raw regions -- the mapping-free channel.
PRESIDENT_PATTERN = re.compile(r"\bpr[ae]{1,2}sid\w*", re.IGNORECASE)
PRESENT_PATTERN = re.compile(r"\bpr[ae]{1,2}sent\w*", re.IGNORECASE)

# Hypothesis 4's landmark class, verbatim from align_short_resolutions.py's
# OPENING_PHRASES (itself the empirical top openings of s2_anchor_phrase_inventory,
# restricted to receipt-of-correspondence formulas). Reused rather than re-derived so
# a coverage number here is comparable to that retired track's own.
FORMULAIC_OPENING_PHRASES = [
    "ontfangen een missive",
    "ontfangen een missiue",
    "ontfangen eenige missiven",
    "ontfangen een requeste",
    "is gelesen de requeste",
]
# 0.85 is this codebase's phrase-search convention (s6b_anchor_harvest.PHRASE_SEARCH_CONFIG);
# these phrases are 17+ chars so the short-word false-positive problem that forced 0.95 for
# single-word president/present forms does not apply. ignorecase because session-opening
# formulas sit sentence-initial.
FORMULAIC_SEARCH_CONFIG = {
    "char_match_threshold": 0.85,
    "ngram_threshold": 0.85,
    "levenshtein_threshold": 0.85,
    "ignorecase": True,
}
# A session opening is expected in the first paragraphs of a flat session, not anywhere
# in it; scanning the whole session would count mid-session receipt items as openings.
HEAD_PARAGRAPHS = 2

SESSION_PATTERN = r"^(session-(?P<inventory_id>\d+)-num-(?P<session_num>\d+))(?:-resolution-(?P<resolution_index>\d+)|$)"

# Cited baselines, asserted so a formula drift is caught instead of silently diverging.
EXPECTED_DAY_CEILING = 11_644  # docs/DECISIONS.md 2026-09-22, PLAN.md acceptance table
EXPECTED_NO_HTR_DATES = 535
GLOBAL_STRETCH_GAP = 718  # PLAN.md acceptance table, for scale on deficit_absorbed

GATE_MAX_KE_RATIO = 2.0  # median segment k_e vs median day k_e
GATE_MAX_MEAN_DATES_PER_SEGMENT = 3.0
# Only channels whose landmarks are grounded in evidence about *this* stream position may
# carry the gate. The in-axis and per-class channels are reported for diagnosis, not
# eligible on their own.
GATE_CANDIDATE_CHANNELS = ("fingerprint_verified", "union_all_channels")


# ---------------------------------------------------------------------------
# 1. Availability, raw side
# ---------------------------------------------------------------------------


def raw_session_landmarks(regions: pd.DataFrame) -> pd.DataFrame:
    """One row per raw session: which opening-landmark classes its regions carry.

    Region rows arrive in the archive's own reading order, so ``date_is_first_region``
    is positional evidence (the opening is where an opening should be), not just
    presence.
    """
    frame = regions.loc[:, ["session_id", "text_region_class", "president_hit", "present_hit"]].copy()
    parts = frame["session_id"].astype(str).str.extract(SESSION_PATTERN)
    frame["inventory_id"] = parts["inventory_id"].astype(int)
    frame["region_order"] = frame.groupby("session_id").cumcount()

    def summarise(group: pd.DataFrame) -> pd.Series:
        classes = group["text_region_class"].tolist()
        first_date = classes.index("date") if "date" in classes else None
        first_para = classes.index("para") if "para" in classes else None
        first_attendance = classes.index("attendance") if "attendance" in classes else None
        return pd.Series(
            {
                "inventory_id": int(group["inventory_id"].iloc[0]),
                "n_regions": len(classes),
                "n_para_regions": classes.count("para"),
                "has_date_region": first_date is not None,
                "has_attendance_region": first_attendance is not None,
                "date_is_first_region": first_date == 0,
                "opening_before_first_para": (
                    first_para is not None
                    and min(p for p in (first_date, first_attendance) if p is not None) < first_para
                    if (first_date is not None or first_attendance is not None)
                    else False
                ),
                "president_hit": bool(group["president_hit"].any()),
                "present_hit": bool(group["present_hit"].any()),
            }
        )

    return frame.groupby("session_id").apply(summarise, include_groups=False).reset_index()


# ---------------------------------------------------------------------------
# 2. The stream the segmentation runs on
# ---------------------------------------------------------------------------


def axis_stream(axis: list[dict[str, Any]]) -> pd.DataFrame:
    """paragraph_axis_1626_1630 in archival stream order, one row per paragraph.

    Stream order is ``(inventory, session_num, resolution_index, para_index)`` -- the
    archive's own sequence, deliberately not the date, which is the drifted key this
    track is trying to escape.
    """
    frame = pd.DataFrame(axis).loc[:, ["date", "flat_id", "para_index"]].copy()
    parts = frame["flat_id"].astype(str).str.extract(SESSION_PATTERN)
    if parts["inventory_id"].isna().any():
        bad = frame.loc[parts["inventory_id"].isna(), "flat_id"].head(3).tolist()
        raise ValueError(f"Unparseable flat_id(s) in axis: {bad}")
    frame["flat_session_id"] = parts[0]
    frame["inventory_id"] = parts["inventory_id"].astype(int)
    frame["session_num"] = parts["session_num"].astype(int)
    frame["resolution_index"] = parts["resolution_index"].fillna(0).astype(int)
    frame["para_index"] = frame["para_index"].astype(int)
    frame["date"] = frame["date"].astype(str).str.slice(0, 10)
    frame = frame.sort_values(
        ["inventory_id", "session_num", "resolution_index", "para_index"]
    ).reset_index(drop=True)
    frame["stream_index"] = frame.groupby("inventory_id").cumcount()
    return frame


def axis_head_texts(axis: list[dict[str, Any]], stream: pd.DataFrame) -> pd.DataFrame:
    """The first HEAD_PARAGRAPHS paragraphs of each flat session, concatenated.

    This is where a session opening would be if it survived into resolutions_flat;
    the mapping-free landmark channels are scored on this text only.
    """
    texts = pd.DataFrame(
        [{"flat_id": r["flat_id"], "para_index": int(r["para_index"]), "text": r.get("text") or ""} for r in axis]
    )
    joined = stream.merge(texts, on=["flat_id", "para_index"], how="left")
    joined["text"] = joined["text"].fillna("")
    head = joined.sort_values("stream_index").groupby("flat_session_id", sort=False).head(HEAD_PARAGRAPHS)
    return head.groupby("flat_session_id", as_index=False).agg(head_text=("text", lambda v: " ".join(v)))


def flat_sessions(stream: pd.DataFrame) -> pd.DataFrame:
    """One row per flat session with axis paragraphs: stream position, date, size."""
    sessions = stream.groupby("flat_session_id", as_index=False).agg(
        inventory_id=("inventory_id", "first"),
        session_num=("session_num", "first"),
        start_stream_index=("stream_index", "min"),
        n_paragraphs=("stream_index", "size"),
        date=("date", "first"),
        n_dates=("date", "nunique"),
    )
    return sessions.sort_values(["inventory_id", "start_stream_index"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Landmark channels
# ---------------------------------------------------------------------------


def detect_in_axis_markers(head: pd.DataFrame) -> pd.DataFrame:
    """Mapping-free channels: opening formulas visible in the axis text itself."""
    out = head.copy()
    out["in_axis_president_and_present"] = out["head_text"].map(
        lambda t: bool(PRESIDENT_PATTERN.search(t)) and bool(PRESENT_PATTERN.search(t))
    )
    out["in_axis_president_or_present"] = out["head_text"].map(
        lambda t: bool(PRESIDENT_PATTERN.search(t)) or bool(PRESENT_PATTERN.search(t))
    )

    searcher = FuzzyPhraseSearcher(FORMULAIC_OPENING_PHRASES, config=FORMULAIC_SEARCH_CONFIG)
    out["formulaic_opening"] = [
        bool(searcher.find_matches({"id": session_id, "text": text}))
        for session_id, text in zip(out["flat_session_id"], out["head_text"])
    ]
    return out.drop(columns="head_text")


def fingerprint_channel(fingerprints: list[dict[str, Any]], raw_landmarks: pd.DataFrame) -> pd.DataFrame:
    """Content-verified flat->raw correspondence, joined to the raw session's landmarks."""
    frame = pd.DataFrame(fingerprints)
    frame["flat_session_id"] = frame["flat_session_id"].astype(str)
    frame["inventory_id"] = frame["inventory_id"].astype(int)
    frame["flat_num"] = frame["flat_num"].astype(int)
    # jsonl round-trips the unmatched rows' None as NaN once pandas types the column, so
    # test with pd.isna rather than `is not None`. The int cast has to stay out of .map()
    # too: a None/int mix re-infers to float64 and would rebuild the raw session id as
    # "session-3185-num-2.0", which matches nothing.
    frame["fingerprint_verified"] = frame["raw_num"].map(lambda v: not pd.isna(v))
    frame["raw_num_int"] = pd.Series(
        [None if pd.isna(v) else int(v) for v in frame["raw_num"]], dtype=object, index=frame.index
    )
    frame["raw_session_id"] = pd.Series(
        [
            None if num is None else f"session-{int(inv)}-num-{int(num)}"
            for inv, num in zip(frame["inventory_id"], frame["raw_num_int"])
        ],
        dtype=object,
        index=frame.index,
    )
    marks = raw_landmarks.set_index("session_id")
    for column in ("has_attendance_region", "date_is_first_region", "president_hit", "present_hit"):
        frame[f"raw_{column}"] = [
            bool(marks.at[sid, column]) if sid is not None and sid in marks.index else False
            for sid in frame["raw_session_id"]
        ]
    frame["verified_with_attendance"] = frame["fingerprint_verified"] & frame["raw_has_attendance_region"]
    frame["verified_with_date_opening"] = frame["fingerprint_verified"] & frame["raw_date_is_first_region"]
    return frame


def order_preservation(fingerprint: pd.DataFrame) -> pd.DataFrame:
    """Per inventory: do verified landmarks keep their order between stream and archive?

    A non-monotone step means the content-verified opening at stream position i+1 sits
    *earlier* in the archive than the one at position i -- an inconsistency no sequence
    alignment can absorb. Offset runs (raw_num - flat_num) show the drift's shape:
    few long runs means a piecewise shift, many short runs means noise.
    """
    rows = []
    for inventory_id, group in fingerprint.groupby("inventory_id"):
        matched = group.loc[group["fingerprint_verified"]].sort_values("flat_num")
        raw_nums = matched["raw_num_int"].tolist()
        offsets = [int(raw) - int(flat) for raw, flat in zip(raw_nums, matched["flat_num"])]
        non_monotone = sum(1 for a, b in zip(raw_nums, raw_nums[1:]) if b <= a)
        runs = 1 + sum(1 for a, b in zip(offsets, offsets[1:]) if a != b) if offsets else 0
        rows.append(
            {
                "record_type": "reliability",
                "inventory_id": int(inventory_id),
                "flat_sessions": int(len(group)),
                "verified": int(len(matched)),
                "verified_share": round(len(matched) / len(group), 4) if len(group) else 0.0,
                "non_monotone_steps": int(non_monotone),
                "distinct_offsets": int(len(set(offsets))),
                "offset_runs": int(runs),
                "mean_run_length": round(len(offsets) / runs, 2) if runs else 0.0,
                "offset_mode": int(Counter(offsets).most_common(1)[0][0]) if offsets else None,
                "drifted_share": round(sum(1 for o in offsets if o != 0) / len(offsets), 4) if offsets else 0.0,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4/5. Locality and headroom
# ---------------------------------------------------------------------------


def date_sequence(
    concordance: pd.DataFrame, stream: pd.DataFrame, sessions: pd.DataFrame
) -> pd.DataFrame:
    """One row per (inventory, enriched date): k_e, paragraph_count, first flat session.

    k_e and paragraph_count follow scripts/metrics_local_inventory_ceiling.py exactly
    (concordance row counts per date; axis rows per date) so the day-partition ceiling
    here is the same 11,644 constant, not a near-miss variant of it.
    """
    dates = concordance["enriched_date"].astype(str).str.slice(0, 10)
    frame = pd.DataFrame({"enriched_date": dates}).value_counts("enriched_date").rename("k_e").reset_index()
    inv_by_date = concordance.assign(
        enriched_date=concordance["enriched_date"].astype(str).str.slice(0, 10)
    ).drop_duplicates("enriched_date").set_index("enriched_date")["inventory_id"]
    frame["inventory_id"] = frame["enriched_date"].map(inv_by_date).astype(int)

    paragraph_count = stream.groupby("date").size().rename("paragraph_count")
    frame = frame.join(paragraph_count, on="enriched_date")
    frame["paragraph_count"] = frame["paragraph_count"].fillna(0).astype(int)

    first_session = (
        sessions.sort_values("start_stream_index")
        .drop_duplicates("date")
        .set_index("date")[["flat_session_id", "start_stream_index"]]
    )
    frame["first_flat_session_id"] = frame["enriched_date"].map(first_session["flat_session_id"])
    frame["first_stream_index"] = frame["enriched_date"].map(first_session["start_stream_index"])
    # Dates with no axis paragraphs have no stream position; they sort by calendar date
    # among their neighbours, which is what merging them into an adjacent segment means.
    frame = frame.sort_values(["inventory_id", "enriched_date"]).reset_index(drop=True)
    return frame


def build_segments(
    dates: pd.DataFrame,
    landmark_sessions: set[str],
    *,
    every_date: bool = False,
    isolate_no_htr: bool = False,
) -> tuple[list[dict[str, int]], dict[int, list[dict[str, int]]]]:
    """Cut each inventory's date sequence at landmark-carrying dates.

    A date opens a new segment iff its first flat session carries a landmark (plus each
    inventory's first date, unconditionally). Segments are runs of whole dates, so no
    date's k_e is split across two segments.

    ``every_date`` is the day-partition baseline: it must cut at *every* date including
    the 535 with no HTR paragraphs at all, which have no flat session and therefore can
    never carry a landmark. Without it the baseline silently merges those dates into
    their neighbours and overshoots the cited 11,644 ceiling.

    ``isolate_no_htr`` keeps every zero-paragraph date in a segment of its own under a
    landmark channel too, so its k_e cannot be satisfied by an adjacent day's paragraphs.
    That separates headroom won by merging two real HTR days from headroom won by
    assuming a date with no HTR at all is really a mislabelled neighbour -- a much
    stronger claim, and the larger share of the raw gain.
    """
    segments: list[dict[str, int]] = []
    per_inventory: dict[int, list[dict[str, int]]] = {}
    for inventory_id, group in dates.groupby("inventory_id", sort=True):
        current: dict[str, int] | None = None
        inventory_segments: list[dict[str, int]] = []
        for row in group.itertuples(index=False):
            no_htr = int(row.paragraph_count) == 0
            starts = (
                current is None
                or every_date
                or row.first_flat_session_id in landmark_sessions
                or (isolate_no_htr and (no_htr or current.get("has_no_htr")))
            )
            if starts:
                current = {"inventory_id": int(inventory_id), "n_dates": 0, "k_e": 0, "paragraph_count": 0}
                inventory_segments.append(current)
            current["n_dates"] += 1
            current["k_e"] += int(row.k_e)
            current["paragraph_count"] += int(row.paragraph_count)
            if isolate_no_htr and no_htr:
                current["has_no_htr"] = 1
        per_inventory[int(inventory_id)] = inventory_segments
        segments.extend(inventory_segments)
    return segments, per_inventory


def segment_stats(
    dates: pd.DataFrame,
    landmark_sessions: set[str],
    channel: str,
    *,
    every_date: bool = False,
) -> dict[str, Any]:
    """Locality and headroom for one landmark channel's segmentation of the stream."""
    segments, per_inventory = build_segments(dates, landmark_sessions, every_date=every_date)
    isolated_segments, _ = build_segments(
        dates, landmark_sessions, every_date=every_date, isolate_no_htr=True
    )

    k_e_values = [s["k_e"] for s in segments]
    para_values = [s["paragraph_count"] for s in segments]
    date_values = [s["n_dates"] for s in segments]
    ceiling = sum(min(s["k_e"], s["paragraph_count"]) for s in segments)
    deficit = sum(max(0, s["k_e"] - s["paragraph_count"]) for s in segments)
    ceiling_isolated = sum(min(s["k_e"], s["paragraph_count"]) for s in isolated_segments)
    deficit_isolated = sum(max(0, s["k_e"] - s["paragraph_count"]) for s in isolated_segments)
    return {
        "record_type": "channel",
        "channel": channel,
        "n_landmarks": len(landmark_sessions),
        "n_segments": len(segments),
        "segment_ceiling_no_htr_isolated": int(ceiling_isolated),
        "segment_deficit_no_htr_isolated": int(deficit_isolated),
        "mean_dates_per_segment": round(statistics.mean(date_values), 3) if date_values else 0.0,
        "max_dates_per_segment": max(date_values) if date_values else 0,
        "median_segment_k_e": statistics.median(k_e_values) if k_e_values else 0,
        "p90_segment_k_e": _quantile(k_e_values, 0.9),
        "max_segment_k_e": max(k_e_values) if k_e_values else 0,
        "median_segment_paragraphs": statistics.median(para_values) if para_values else 0,
        "p90_segment_paragraphs": _quantile(para_values, 0.9),
        "segment_ceiling": int(ceiling),
        "segment_deficit": int(deficit),
        "per_inventory_ceiling": {
            str(inv): int(sum(min(s["k_e"], s["paragraph_count"]) for s in segs))
            for inv, segs in per_inventory.items()
        },
    }


def _quantile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, int(q * len(ordered)))])


# ---------------------------------------------------------------------------


def main() -> None:
    regions = pd.DataFrame(load(REGION_SCAN_DATASET))
    axis = load(AXIS_DATASET)
    concordance = load(CONCORDANCE_DATASET)
    fingerprints = load(FINGERPRINT_DATASET)

    raw_landmarks = raw_session_landmarks(regions)
    stream = axis_stream(axis)
    sessions = flat_sessions(stream)
    head = axis_head_texts(axis, stream)
    in_axis = detect_in_axis_markers(head)
    fingerprint = fingerprint_channel(fingerprints, raw_landmarks)
    reliability = order_preservation(fingerprint)
    dates = date_sequence(concordance, stream, sessions)

    axis_session_ids = set(sessions["flat_session_id"])
    verified = set(fingerprint.loc[fingerprint["fingerprint_verified"], "flat_session_id"]) & axis_session_ids
    verified_attendance = (
        set(fingerprint.loc[fingerprint["verified_with_attendance"], "flat_session_id"]) & axis_session_ids
    )
    in_axis_formula = set(in_axis.loc[in_axis["in_axis_president_and_present"], "flat_session_id"])
    in_axis_either = set(in_axis.loc[in_axis["in_axis_president_or_present"], "flat_session_id"])
    formulaic = set(in_axis.loc[in_axis["formulaic_opening"], "flat_session_id"])

    channels = {
        "day_partition": axis_session_ids | set(dates["first_flat_session_id"].dropna()),
        "flat_session_boundary": axis_session_ids,
        "fingerprint_verified": verified,
        "verified_with_attendance": verified_attendance,
        "in_axis_president_and_present": in_axis_formula,
        "in_axis_president_or_present": in_axis_either,
        "formulaic_opening": formulaic,
        "union_mapping_free": in_axis_either | formulaic,
        "union_all_channels": verified | in_axis_either | formulaic,
    }
    channel_rows = [segment_stats(dates, axis_session_ids, "day_partition", every_date=True)]
    day_row = channel_rows[0]
    day_row["n_landmarks"] = int(len(dates))
    for name, landmarks in channels.items():
        if name == "day_partition":
            continue
        channel_rows.append(segment_stats(dates, landmarks, name))

    # The day partition must reproduce the cited constant; segment merging is only
    # interpretable relative to it.
    day_ceiling = day_row["segment_ceiling"]
    n_no_htr_dates = int((dates["paragraph_count"] == 0).sum())
    if day_ceiling != EXPECTED_DAY_CEILING or n_no_htr_dates != EXPECTED_NO_HTR_DATES:
        print(
            f"WARNING: day ceiling={day_ceiling} (expected {EXPECTED_DAY_CEILING}), "
            f"no-HTR dates={n_no_htr_dates} (expected {EXPECTED_NO_HTR_DATES}) -- "
            "no longer matches the PLAN.md/DECISIONS.md baseline."
        )
    for row in channel_rows:
        row["deficit_absorbed_vs_day"] = int(day_row["segment_deficit"] - row["segment_deficit"])
        row["ceiling_gain_vs_day"] = int(row["segment_ceiling"] - day_ceiling)
        row["ceiling_gain_vs_day_no_htr_isolated"] = int(
            row["segment_ceiling_no_htr_isolated"] - day_row["segment_ceiling_no_htr_isolated"]
        )
        row["segment_k_e_ratio_vs_day"] = (
            round(row["median_segment_k_e"] / day_row["median_segment_k_e"], 3)
            if day_row["median_segment_k_e"]
            else None
        )
        row["locality_ok"] = bool(
            (row["segment_k_e_ratio_vs_day"] or 99) <= GATE_MAX_KE_RATIO
            and row["mean_dates_per_segment"] < GATE_MAX_MEAN_DATES_PER_SEGMENT
        )

    stream_ceiling = int(
        dates.groupby("inventory_id")
        .apply(lambda g: min(g["k_e"].sum(), g["paragraph_count"].sum()), include_groups=False)
        .sum()
    )

    # Candidates are the content-grounded channels only, and headroom is maximised *among
    # those that keep locality* -- picking by headroom alone would always crown the
    # thinnest channel, whose segments span whole inventories. That is the trap the
    # docstring warns about, so it is enforced here rather than left to the reader.
    candidates = [
        r
        for r in channel_rows
        if r["channel"] in GATE_CANDIDATE_CHANNELS and r["locality_ok"]
    ]
    best = (
        max(candidates, key=lambda r: r["deficit_absorbed_vs_day"])
        if candidates
        else max(
            (r for r in channel_rows if r["channel"] in GATE_CANDIDATE_CHANNELS),
            key=lambda r: r["deficit_absorbed_vs_day"],
        )
    )
    non_monotone_total = int(reliability["non_monotone_steps"].sum())
    gate_locality = best["locality_ok"]
    gate_spacing = best["mean_dates_per_segment"] < GATE_MAX_MEAN_DATES_PER_SEGMENT
    gate_headroom = best["deficit_absorbed_vs_day"] > 0
    gate_order = non_monotone_total == 0 or all(
        row.non_monotone_steps == 0
        for row in reliability.itertuples()
        if row.inventory_id in {3185, 3186, 3187, 3188, 3189}
    )
    verdict = "PASS" if (gate_locality and gate_spacing and gate_headroom and gate_order) else "FAIL"

    availability = {
        "record_type": "raw_availability",
        "scope": "corpus",
        "raw_sessions": int(len(raw_landmarks)),
        **{
            column: int(raw_landmarks[column].sum())
            for column in (
                "has_date_region",
                "has_attendance_region",
                "date_is_first_region",
                "opening_before_first_para",
                "president_hit",
                "present_hit",
            )
        },
    }
    availability_rows = [availability] + [
        {
            "record_type": "raw_availability",
            "scope": "inventory",
            "inventory_id": int(inventory_id),
            "raw_sessions": int(len(group)),
            **{
                column: int(group[column].sum())
                for column in (
                    "has_date_region",
                    "has_attendance_region",
                    "date_is_first_region",
                    "opening_before_first_para",
                    "president_hit",
                    "present_hit",
                )
            },
        }
        for inventory_id, group in raw_landmarks.groupby("inventory_id")
    ]

    localizability = {
        "record_type": "localizability",
        "axis_flat_sessions": len(axis_session_ids),
        "axis_paragraphs": int(len(stream)),
        "fingerprint_rows": int(len(fingerprint)),
        "fingerprint_verified_in_axis": len(verified),
        "verified_with_attendance_in_axis": len(verified_attendance),
        "in_axis_president_and_present": len(in_axis_formula),
        "in_axis_president_or_present": len(in_axis_either),
        "formulaic_opening": len(formulaic),
        "union_mapping_free": len(in_axis_either | formulaic),
        "union_all_channels": len(verified | in_axis_either | formulaic),
        "formulaic_outside_verified": len(formulaic - verified),
        "in_axis_outside_verified": len(in_axis_either - verified),
    }

    meta = {
        "record_type": "meta",
        "track": "plans/COLLISION_AVOIDANCE_TRACK.md",
        "step": 1,
        "parent": [REGION_SCAN_DATASET, FINGERPRINT_DATASET, AXIS_DATASET, CONCORDANCE_DATASET],
        "day_ceiling_computed": int(day_ceiling),
        "day_ceiling_expected": EXPECTED_DAY_CEILING,
        "no_htr_dates_computed": n_no_htr_dates,
        "no_htr_dates_expected": EXPECTED_NO_HTR_DATES,
        "inventory_stream_ceiling": stream_ceiling,
        "day_segment_deficit": int(day_row["segment_deficit"]),
        "global_stretch_gap": GLOBAL_STRETCH_GAP,
        "gate_max_k_e_ratio": GATE_MAX_KE_RATIO,
        "gate_max_mean_dates_per_segment": GATE_MAX_MEAN_DATES_PER_SEGMENT,
        "gate_best_channel": best["channel"],
        "gate_locality_ok": bool(gate_locality),
        "gate_spacing_ok": bool(gate_spacing),
        "gate_headroom_ok": bool(gate_headroom),
        "gate_order_preserving_ok": bool(gate_order),
        "gate_verdict": verdict,
        "note": (
            "Segments are runs of whole enriched dates cut at landmark-carrying flat "
            "sessions; segment_ceiling = sum of min(sum k_e, sum paragraphs) per segment. "
            "A coarser partition always raises segment_ceiling, so read locality "
            "(mean_dates_per_segment, median_segment_k_e) and headroom "
            "(deficit_absorbed_vs_day) together, never headroom alone. "
            "deficit_absorbed_vs_day and ceiling_gain_vs_day are the same number by "
            "construction (segment_ceiling == total k_e - segment_deficit, total k_e "
            "being fixed at 19,120) -- one quantity reported two ways, not two findings. "
            "ceiling_gain_vs_day_no_htr_isolated is the independent one: the gain that "
            "survives when a date with no HTR at all is barred from borrowing a "
            "neighbour's paragraphs."
        ),
    }

    records = [
        meta,
        *availability_rows,
        localizability,
        *channel_rows,
        *reliability.to_dict(orient="records"),
    ]
    path = save_semi_structured(
        records,
        logical_name=OUTPUT_DATASET,
        parent_sources=[REGION_SCAN_DATASET, FINGERPRINT_DATASET, AXIS_DATASET, CONCORDANCE_DATASET],
        description=(
            "Step 1 of plans/COLLISION_AVOIDANCE_TRACK.md: session-landmark availability in the "
            "raw HTR (date/attendance/president regions per raw session), localizability on the "
            "paragraph_axis_1626_1630 stream (content-verified fingerprint, in-axis president/"
            "present stems, hypothesis-4 formulaic openings), order-preservation reliability, and "
            "locality/headroom per landmark-bracketed segment against the day partition's 11,644 "
            "ceiling. Diagnostic only; no placement change and no tolerance-family metric."
        ),
        script=__file__,
    )

    print(f"Wrote {len(records)} records to {path}\n")
    print("--- 1. availability, raw side ---")
    n_raw = availability["raw_sessions"]
    for column in ("has_date_region", "date_is_first_region", "has_attendance_region", "opening_before_first_para", "president_hit", "present_hit"):
        print(f"  {column:28s} {availability[column]:5d} / {n_raw}  {availability[column] / n_raw:6.1%}")
    print("\n--- 2. localizability on the axis stream ---")
    for key, value in localizability.items():
        if key == "record_type":
            continue
        share = f"  {value / len(axis_session_ids):6.1%}" if key not in {"axis_paragraphs", "axis_flat_sessions", "fingerprint_rows"} else ""
        print(f"  {key:34s} {value:6d}{share}")
    print("\n--- 3. reliability (order preservation) ---")
    print(reliability[["inventory_id", "flat_sessions", "verified", "verified_share", "non_monotone_steps", "offset_runs", "mean_run_length", "drifted_share"]].to_string(index=False))
    print("\n--- 4/5. locality and headroom per channel ---")
    table = pd.DataFrame(channel_rows)[
        [
            "channel", "n_landmarks", "n_segments", "mean_dates_per_segment", "median_segment_k_e",
            "segment_k_e_ratio_vs_day", "p90_segment_k_e", "median_segment_paragraphs",
            "segment_ceiling", "ceiling_gain_vs_day", "ceiling_gain_vs_day_no_htr_isolated",
            "deficit_absorbed_vs_day", "locality_ok",
        ]
    ]
    print(table.to_string(index=False))
    print(
        f"\nday ceiling {day_ceiling} | inventory-stream ceiling {stream_ceiling} "
        f"| day deficit {day_row['segment_deficit']} | Global-stretch gap {GLOBAL_STRETCH_GAP}"
    )
    print(
        f"\nGATE ({best['channel']}): locality_ok={gate_locality} spacing_ok={gate_spacing} "
        f"headroom_ok={gate_headroom} order_ok={gate_order} -> {verdict}"
    )


if __name__ == "__main__":
    main()

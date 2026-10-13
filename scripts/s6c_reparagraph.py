#!/usr/bin/env python3
"""Track P P3 — re-paragraph an axis at char offsets, then place via segment_gap.

P0 signed off that a mid-paragraph cut *materialises* as a new paragraph boundary
(`docs/DECISIONS.md` 2026-10-13). The placement DP stays paragraph-indexed; offsets
are an intermediate that produces a versioned successor stream. `separated` is
unchanged and simply runs over the finer axis.

This module:

1. Splits host paragraphs at interior char offsets into a successor axis with
   provenance (never mutates the parent stream in place).
2. Remaps offset-bearing alignments ``(enriched_index, paragraph_index, char_offset)``
   onto the successor's paragraph indices.
3. Hands the remapped (paragraph-only) alignments to the existing
   ``build_anchor_backbone`` / ``segment_day`` path.

See ``plans/TRACK_P_SUBPARAGRAPH_DIVISION.md`` P3.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from scripts.s6c_gap_segmentation import build_anchor_backbone, segment_day

# Alignment with an optional within-paragraph char offset.
# ``char_offset is None`` means paragraph-start (offset 0).
OffsetAlignment = tuple[int | None, int | None, int | None]

AXIS_VERSION_P3 = "paragraph_axis_p3_reparagraph_v1"
# Production successor from gated predicted Group-C cuts (Track P P5).
AXIS_VERSION_P5 = "paragraph_axis_p5_predicted_v1"

# Host cut-fill: only materialise cuts when the channel fully fills n_needed.
HOST_GATE_ENOUGH_CUTS = "enough_cuts"
HOST_GATE_ANY = "any"
HOST_GATES = (HOST_GATE_ENOUGH_CUTS, HOST_GATE_ANY)

# Day materialisation: require separated gain and/or no extent regression vs plain.
DAY_GATE_BEATS_PLAIN = "beats_plain"
DAY_GATE_NO_EXTENT_REGRESSION = "no_extent_regression"
DAY_GATE_BEATS_AND_NO_EXTENT = "beats_plain_and_no_extent_regression"
DAY_GATE_NONE = "none"
DAY_GATES = (
    DAY_GATE_BEATS_AND_NO_EXTENT,
    DAY_GATE_BEATS_PLAIN,
    DAY_GATE_NO_EXTENT_REGRESSION,
    DAY_GATE_NONE,
)


def interior_cuts(
    cuts: Sequence[tuple[int, int]],
    paragraph_lengths: Sequence[int],
) -> list[tuple[int, int]]:
    """Dedupe/sort cuts; drop offsets that are already paragraph boundaries.

    A cut at ``0`` or ``len(text)`` is not interior — those are the host's edges.
    Out-of-range paragraph indices and offsets are dropped (fail closed on garbage).
    """
    kept: set[tuple[int, int]] = set()
    for paragraph_index, char_offset in cuts:
        para = int(paragraph_index)
        offset = int(char_offset)
        if para < 0 or para >= len(paragraph_lengths):
            continue
        length = int(paragraph_lengths[para])
        if offset <= 0 or offset >= length:
            continue
        kept.add((para, offset))
    return sorted(kept)


def reparagraph_axis(
    axis: Sequence[Mapping[str, Any]],
    cuts: Sequence[tuple[int, int]],
    *,
    version: str = AXIS_VERSION_P3,
    parent_dataset: str | None = None,
) -> dict[str, Any]:
    """Split paragraphs at interior cuts into a versioned successor axis.

    Each new paragraph carries ``parent_para_index``, ``parent_char_start``,
    ``parent_char_end``, and ``axis_version``. Parent fields on the source row are
    preserved via deepcopy; ``text`` / ``para_index`` / ``axis_id`` are rewritten.

    Returns a dict with ``axis``, ``version``, ``parent_dataset``, ``cuts_applied``,
    ``new_to_old`` (new_idx -> (old_idx, start, end)), and ``old_to_new``
    (old_idx -> list of (new_idx, start, end) pieces in order).
    """
    lengths = [len(str(row.get("text") or "")) for row in axis]
    applied = interior_cuts(cuts, lengths)
    cuts_by_para: dict[int, list[int]] = {}
    for para, offset in applied:
        cuts_by_para.setdefault(para, []).append(offset)

    new_axis: list[dict[str, Any]] = []
    new_to_old: dict[int, tuple[int, int, int]] = {}
    old_to_new: dict[int, list[tuple[int, int, int]]] = {}

    for old_idx, row in enumerate(axis):
        text = str(row.get("text") or "")
        offsets = cuts_by_para.get(old_idx, [])
        # Piece boundaries: 0, cut..., len(text)
        bounds = [0, *offsets, len(text)]
        pieces: list[tuple[int, int, int]] = []
        for piece_start, piece_end in zip(bounds, bounds[1:]):
            if piece_end < piece_start:
                continue
            # Empty trailing piece only if the cut sat at len (already filtered);
            # allow empty only when the host itself was empty.
            if piece_end == piece_start and len(text) > 0:
                continue
            new_idx = len(new_axis)
            piece = deepcopy(dict(row))
            piece["text"] = text[piece_start:piece_end]
            piece["para_index"] = new_idx
            piece["parent_para_index"] = old_idx
            piece["parent_char_start"] = piece_start
            piece["parent_char_end"] = piece_end
            piece["axis_version"] = version
            parent_id = row.get("axis_id") or row.get("flat_id") or f"p{old_idx}"
            piece["axis_id"] = f"{parent_id}#repara:{piece_start}-{piece_end}"
            if parent_dataset is not None:
                piece["parent_dataset"] = parent_dataset
            new_axis.append(piece)
            new_to_old[new_idx] = (old_idx, piece_start, piece_end)
            pieces.append((new_idx, piece_start, piece_end))
        old_to_new[old_idx] = pieces

    return {
        "axis": new_axis,
        "version": version,
        "parent_dataset": parent_dataset,
        "cuts_applied": applied,
        "new_to_old": new_to_old,
        "old_to_new": old_to_new,
        "n_paragraphs_before": len(axis),
        "n_paragraphs_after": len(new_axis),
        "n_cuts_applied": len(applied),
    }


def map_offset_to_new_index(
    old_para: int,
    char_offset: int | None,
    old_to_new: Mapping[int, Sequence[tuple[int, int, int]]],
) -> int | None:
    """Map ``(old_para, char_offset)`` onto the successor paragraph that *opens* there.

    A cut at offset ``C`` starts the right-hand piece at ``C``. Offset ``None`` or
    ``0`` lands on the leftmost piece. An offset past the last piece maps to the
    last piece (fail soft for annotation ±1 noise at the end).
    """
    pieces = list(old_to_new.get(int(old_para), ()))
    if not pieces:
        return None
    offset = 0 if char_offset is None else int(char_offset)
    for new_idx, start, end in pieces:
        if start <= offset < end:
            return int(new_idx)
        # Exact end of a non-final piece is the next piece's start — prefer next.
        if offset == end:
            continue
    # offset == final end, or past end: last piece
    return int(pieces[-1][0])


def remap_alignments(
    alignments: Sequence[OffsetAlignment],
    old_to_new: Mapping[int, Sequence[tuple[int, int, int]]],
) -> list[tuple[int | None, int | None]]:
    """Drop char offsets after mapping onto the successor paragraph stream."""
    remapped: list[tuple[int | None, int | None]] = []
    for enriched_index, paragraph_index, char_offset in alignments:
        if enriched_index is None or paragraph_index is None:
            remapped.append((enriched_index, paragraph_index))
            continue
        new_idx = map_offset_to_new_index(int(paragraph_index), char_offset, old_to_new)
        remapped.append((int(enriched_index), new_idx))
    return remapped


def cuts_from_alignments(alignments: Sequence[OffsetAlignment]) -> list[tuple[int, int]]:
    """Interior cut proposals carried by offset-bearing alignments."""
    cuts: list[tuple[int, int]] = []
    for _enriched, paragraph_index, char_offset in alignments:
        if paragraph_index is None or char_offset is None:
            continue
        if int(char_offset) > 0:
            cuts.append((int(paragraph_index), int(char_offset)))
    return cuts


def segment_day_with_offsets(
    enriched_count: int,
    axis: Sequence[Mapping[str, Any]],
    alignments: Sequence[OffsetAlignment],
    *,
    position_scores: dict[int, float] | None = None,
    resolution_scores: Mapping[int, Mapping[int, float]] | None = None,
    version: str = AXIS_VERSION_P3,
    parent_dataset: str | None = None,
    extra_cuts: Sequence[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Re-paragraph at alignment (and optional extra) cuts, then ``segment_day``.

    Returns ``positions`` on the *successor* axis (same contract as ``segment_day``:
    starts for resolutions 1..k_e-1), plus the successor payload under ``successor``.
    ``position_scores`` / ``resolution_scores`` must already be keyed by *successor*
    paragraph indices when supplied — this function does not remap soft scores.
    """
    proposed = list(cuts_from_alignments(alignments))
    if extra_cuts:
        proposed.extend((int(p), int(c)) for p, c in extra_cuts)
    successor = reparagraph_axis(
        axis, proposed, version=version, parent_dataset=parent_dataset
    )
    remapped = remap_alignments(alignments, successor["old_to_new"])
    positions = segment_day(
        enriched_count,
        len(successor["axis"]),
        remapped,
        position_scores=position_scores,
        resolution_scores=resolution_scores,
    )
    return {
        "positions": positions,
        "successor": successor,
        "remapped_alignments": remapped,
        "backbone": build_anchor_backbone(
            enriched_count, len(successor["axis"]), remapped
        ),
    }


def select_interior_cuts(
    candidates: Sequence[Any],
    n_needed: int,
) -> list[int]:
    """Pick up to ``n_needed`` interior offsets from a ranked candidate set.

    Ranking uses each candidate's ``.rank`` (higher better, same contract as
    ``TypedFormulaChannel.pick``). Accepted offsets are returned in text order so
    they can feed ``reparagraph_axis`` directly. Fewer than ``n_needed`` is an
    honest partial unlock when the channel under-proposes.
    """
    if n_needed <= 0:
        return []
    ordered = sorted(candidates, key=lambda candidate: candidate.rank, reverse=True)
    chosen: list[int] = []
    seen: set[int] = set()
    for candidate in ordered:
        offset = int(candidate.offset)
        if offset in seen:
            continue
        chosen.append(offset)
        seen.add(offset)
        if len(chosen) >= n_needed:
            break
    return sorted(chosen)


def gate_host_cuts(
    cuts: Sequence[int],
    n_needed: int,
    *,
    mode: str = HOST_GATE_ENOUGH_CUTS,
) -> list[int]:
    """Cut-fill gate: drop a host's cuts when the channel under-proposes.

    ``enough_cuts`` (default) keeps cuts only when ``len(cuts) >= n_needed``.
    ``any`` keeps whatever was predicted (P4 diagnostic behaviour).
    """
    if mode not in HOST_GATES:
        raise ValueError(f"unknown host gate {mode!r}; expected one of {HOST_GATES}")
    ordered = sorted(int(c) for c in cuts)
    if n_needed <= 0:
        return []
    if mode == HOST_GATE_ANY:
        return ordered
    if len(ordered) >= int(n_needed):
        return ordered
    return []


def day_passes_gate(
    *,
    separated_predicted: int,
    separated_plain: int,
    extent_gt_max_predicted: int,
    extent_gt_max_plain: int,
    mode: str = DAY_GATE_BEATS_AND_NO_EXTENT,
) -> bool:
    """Day materialisation gate after scoring gated cuts vs the pre-split baseline."""
    if mode not in DAY_GATES:
        raise ValueError(f"unknown day gate {mode!r}; expected one of {DAY_GATES}")
    beats = int(separated_predicted) > int(separated_plain)
    extent_ok = int(extent_gt_max_predicted) <= int(extent_gt_max_plain)
    if mode == DAY_GATE_NONE:
        return True
    if mode == DAY_GATE_BEATS_PLAIN:
        return beats
    if mode == DAY_GATE_NO_EXTENT_REGRESSION:
        return extent_ok
    return beats and extent_ok


def identity_axis_row(
    row: Mapping[str, Any],
    *,
    version: str,
    parent_dataset: str | None = None,
    parent_para_index: int | None = None,
) -> dict[str, Any]:
    """Copy a parent paragraph with successor provenance and no text change."""
    piece = deepcopy(dict(row))
    old_idx = (
        int(parent_para_index)
        if parent_para_index is not None
        else int(row.get("para_index") or 0)
    )
    text = str(row.get("text") or "")
    piece["parent_para_index"] = old_idx
    piece["parent_char_start"] = 0
    piece["parent_char_end"] = len(text)
    piece["axis_version"] = version
    if parent_dataset is not None:
        piece["parent_dataset"] = parent_dataset
    return piece


def apply_cuts_to_corpus_rows(
    parent_rows: Sequence[Mapping[str, Any]],
    cuts_by_axis_id: Mapping[str, Sequence[int]],
    *,
    version: str = AXIS_VERSION_P5,
    parent_dataset: str | None = None,
) -> dict[str, Any]:
    """Build a versioned successor stream from parent rows + per-``axis_id`` cut lists.

    Rows without cuts are copied with identity provenance. Parent is never mutated.
    ``para_index`` stays **within ``flat_id``** (parent contract); ``parent_para_index``
    is the parent *stream* index for join-back.
    """
    new_axis: list[dict[str, Any]] = []
    n_split = 0
    n_cuts = 0
    current_flat: Any = object()
    local_para = 0
    for old_idx, row in enumerate(parent_rows):
        flat_id = row.get("flat_id")
        if flat_id != current_flat:
            current_flat = flat_id
            local_para = 0
        axis_id = str(row.get("axis_id") or "")
        offsets = [int(o) for o in cuts_by_axis_id.get(axis_id, ())]
        if not offsets:
            piece = identity_axis_row(
                row,
                version=version,
                parent_dataset=parent_dataset,
                parent_para_index=old_idx,
            )
            piece["para_index"] = local_para
            local_para += 1
            new_axis.append(piece)
            continue
        day_cuts = [(0, offset) for offset in offsets]
        # Local one-row axis so reparagraph_axis's para index is 0.
        local = reparagraph_axis(
            [dict(row)],
            day_cuts,
            version=version,
            parent_dataset=parent_dataset,
        )
        for piece in local["axis"]:
            piece["para_index"] = local_para
            local_para += 1
            # parent_para_index must refer to the corpus stream index, not the
            # local 0 used inside the one-row reparagraph call.
            piece["parent_para_index"] = old_idx
            new_axis.append(piece)
        n_split += 1
        n_cuts += len(local["cuts_applied"])
    return {
        "axis": new_axis,
        "version": version,
        "parent_dataset": parent_dataset,
        "n_paragraphs_before": len(parent_rows),
        "n_paragraphs_after": len(new_axis),
        "n_hosts_split": n_split,
        "n_cuts_applied": n_cuts,
    }


def starts_from_segment_positions(
    positions: Sequence[int | None],
    *,
    session_start: int = 0,
) -> list[int | None]:
    """Prepend resolution-0's session start to ``segment_day``'s returned list."""
    return [session_start, *list(positions)]


def extents_from_starts(
    starts: Sequence[int | None],
    axis_count: int,
) -> list[tuple[int | None, int | None]]:
    """Inclusive ``(start, end)`` paragraph spans; ``None`` where start is unresolved."""
    spans: list[tuple[int | None, int | None]] = []
    for index, start in enumerate(starts):
        if start is None:
            spans.append((None, None))
            continue
        next_starts = [s for s in starts[index + 1 :] if s is not None]
        end = (min(next_starts) - 1) if next_starts else (axis_count - 1)
        if end < int(start):
            end = int(start)
        spans.append((int(start), int(end)))
    return spans

"""Step 8: scoped production ALIGNED_TO wire from overflow apply + cut gold.

Writes reviewable ``overflow_align_wire`` rows and optionally pushes
``ALIGNED_TO:overflow`` edges onto the saved sequence graph.

Sources (hard-window / main-series only):
  - ``clean_split`` flats from ``overflow_align_apply`` (encoder MATCH pairs,
    ``observed=False``, channel ``overflow_segment_dp``)
  - certain ``overflow_cut_gold`` flats (``uncertain=False``, editorial 1:1
    segment↔claimant when ``n_segments == n_claimants``; ``observed=True``,
    channel ``overflow_cut_gold``)

Targets the parent HTR flat node with ``char_start`` / ``char_end`` /
``segment_rank`` in evidence detail — segment ids are not graph nodes.

Never writes ``PINNED_TO``. Uncertain cut gold is skipped unless
``--include-uncertain`` (still not auto-assigned when cuts disagree with
claimant count).

Usage:
    uv run python -m sequence_graph.overflow_align_wire --write
    uv run python -m sequence_graph.overflow_align_wire --write --push-graph
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from data_io import load, save_semi_structured
from scripts.corpus_scope import in_scope, is_main_series, scope_meta
from sequence_graph.align import MATCH
from sequence_graph.correspondence import ALIGNED_TO, Evidence
from sequence_graph.nodes import EnrichedResolution, HtrResolution
from sequence_graph.overflow_align_apply import CHANNEL as APPLY_CHANNEL
from sequence_graph.overflow_align_apply import normalize_cuts, slice_segments
from sequence_graph.overflow_cut_promote import OUTPUT_DATASET as CUT_GOLD
from sequence_graph.persist import load_graph, save_loaded_graph

APPLY_DATASET = "overflow_align_apply"
OUTPUT_DATASET = "overflow_align_wire"
EDGE_KEY = f"{ALIGNED_TO}:overflow"
GOLD_CHANNEL = "overflow_cut_gold"
PREFERRED_CUT_SOURCE = "encoder"


def _parse_volgnr(volgnr: str) -> tuple[str, int] | None:
    if len(volgnr) < 12 or volgnr[10] != "_":
        return None
    date, _, idx = volgnr.partition("_")
    if len(date) != 10 or not in_scope(date):
        return None
    try:
        return date, int(idx)
    except ValueError:
        return None


def _editorial_volgnrs(vols: list[str]) -> list[str]:
    parsed: list[tuple[tuple[str, int], str]] = []
    for v in vols:
        p = _parse_volgnr(str(v))
        if p is None:
            continue
        parsed.append((p, str(v)))
    parsed.sort(key=lambda t: t[0])
    return [v for _, v in parsed]


def _segment_bounds(text_len: int, cuts: list[int]) -> list[tuple[int, int]]:
    """Inclusive-exclusive char spans for contiguous segments after interior cuts."""
    if text_len <= 0:
        return [(0, 0)]
    cleaned = normalize_cuts(cuts, text_len, len(cuts)) if cuts else []
    # Reuse slice_segments on a dummy string of the right length for bound geometry.
    dummy = "x" * text_len
    segs = slice_segments(dummy, cleaned)
    bounds: list[tuple[int, int]] = []
    cursor = 0
    for seg in segs:
        end = cursor + len(seg)
        bounds.append((cursor, end))
        cursor = end
    if not bounds:
        return [(0, text_len)]
    if bounds[-1][1] != text_len:
        bounds[-1] = (bounds[-1][0], text_len)
    return bounds


def _clean_split_flat_ids(apply_rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(r["flat_id"])
        for r in apply_rows
        if r.get("record_type") == "residual_gap"
        and r.get("kind") == "clean_split"
        and r.get("flat_id")
    }


def _encoder_flat_apply(
    apply_rows: list[dict[str, Any]], flat_id: str
) -> dict[str, Any] | None:
    for r in apply_rows:
        if (
            r.get("record_type") == "flat_apply"
            and r.get("flat_id") == flat_id
            and r.get("cut_source") == PREFERRED_CUT_SOURCE
            and r.get("status") == "ok"
        ):
            return r
    return None


def wire_rows_from_clean_split(
    apply_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build wire candidate rows from encoder MATCH pairs on clean_split flats."""
    clean = _clean_split_flat_ids(apply_rows)
    out: list[dict[str, Any]] = []
    for flat_id in sorted(clean):
        if not is_main_series(flat_id):
            continue
        flat = _encoder_flat_apply(apply_rows, flat_id)
        if flat is None:
            continue
        cuts = [int(c) for c in (flat.get("cuts") or [])]
        text_len = int(flat.get("flat_char_len") or 0)
        if text_len <= 0:
            # Reconstruct from segment_char_lens if present
            lens = flat.get("segment_char_lens") or []
            text_len = int(sum(int(x) for x in lens)) if lens else 0
        bounds = _segment_bounds(text_len, cuts) if text_len else []
        pairs = [
            r
            for r in apply_rows
            if r.get("record_type") == "align_pair"
            and r.get("flat_id") == flat_id
            and r.get("cut_source") == PREFERRED_CUT_SOURCE
            and r.get("move_kind") == MATCH
            and r.get("order_ok") is True
            and r.get("volgnr")
            and r.get("read_index") is not None
        ]
        for pair in pairs:
            read_i = int(pair["read_index"])
            volgnr = str(pair["volgnr"])
            parsed = _parse_volgnr(volgnr)
            if parsed is None:
                continue
            date, index = parsed
            if read_i < 0 or read_i >= len(bounds):
                continue
            char_start, char_end = bounds[read_i]
            out.append({
                "record_type": "wire_edge",
                "source": APPLY_DATASET,
                "flat_id": flat_id,
                "session_id": flat.get("session_id"),
                "volgnr": volgnr,
                "date": date,
                "resolution_index": index,
                "segment_rank": read_i,
                "char_start": char_start,
                "char_end": char_end,
                "cuts": cuts,
                "cut_source": PREFERRED_CUT_SOURCE,
                "observed": False,
                "channel": APPLY_CHANNEL,
                "uncertain": False,
                "kind": "clean_split",
            })
    return out


def wire_rows_from_cut_gold(
    gold_rows: list[dict[str, Any]],
    *,
    include_uncertain: bool = False,
) -> list[dict[str, Any]]:
    """Editorial 1:1 wire from certain (or opted-in) cut gold."""
    out: list[dict[str, Any]] = []
    for row in gold_rows:
        if row.get("record_type") != "cut_proposal":
            continue
        flat_id = str(row.get("flat_id") or "")
        if not flat_id or not is_main_series(flat_id):
            continue
        uncertain = bool(row.get("uncertain"))
        if uncertain and not include_uncertain:
            out.append({
                "record_type": "skipped",
                "flat_id": flat_id,
                "reason": "uncertain_cut_gold",
                "note": row.get("note") or "",
            })
            continue
        offsets = [int(c) for c in (row.get("gold_offsets") or [])]
        vols = _editorial_volgnrs([str(v) for v in (row.get("claimant_volgnrs") or [])])
        text_len = int(row.get("flat_char_len") or 0)
        n_segs = len(offsets) + 1 if offsets else 0
        if text_len <= 0 or n_segs == 0:
            out.append({
                "record_type": "skipped",
                "flat_id": flat_id,
                "reason": "missing_geometry",
            })
            continue
        if len(vols) != n_segs:
            out.append({
                "record_type": "skipped",
                "flat_id": flat_id,
                "reason": "claimant_segment_count_mismatch",
                "n_claimants": len(vols),
                "n_segments": n_segs,
                "uncertain": uncertain,
            })
            continue
        bounds = _segment_bounds(text_len, offsets)
        if len(bounds) != len(vols):
            out.append({
                "record_type": "skipped",
                "flat_id": flat_id,
                "reason": "bounds_mismatch",
                "n_bounds": len(bounds),
                "n_claimants": len(vols),
            })
            continue
        for rank, volgnr in enumerate(vols):
            parsed = _parse_volgnr(volgnr)
            if parsed is None:
                continue
            date, index = parsed
            char_start, char_end = bounds[rank]
            out.append({
                "record_type": "wire_edge",
                "source": CUT_GOLD,
                "flat_id": flat_id,
                "session_id": row.get("session_id"),
                "volgnr": volgnr,
                "date": date,
                "resolution_index": index,
                "segment_rank": rank,
                "char_start": char_start,
                "char_end": char_end,
                "cuts": offsets,
                "cut_source": "gold_offsets",
                "observed": True,
                "channel": GOLD_CHANNEL,
                "uncertain": uncertain,
                "kind": "cut_gold",
            })
    return out


def run_overflow_align_wire(
    *,
    apply_rows: list[dict[str, Any]] | None = None,
    gold_rows: list[dict[str, Any]] | None = None,
    include_uncertain: bool = False,
) -> list[dict[str, Any]]:
    """Build reviewable wire plan (does not mutate the graph)."""
    if apply_rows is None:
        apply_rows = list(load(APPLY_DATASET))
    if gold_rows is None:
        gold_rows = list(load(CUT_GOLD))

    apply_meta = next(
        (r for r in apply_rows if r.get("record_type") == "meta"), {}
    )
    clean_edges = wire_rows_from_clean_split(apply_rows)
    gold_parts = wire_rows_from_cut_gold(
        gold_rows, include_uncertain=include_uncertain
    )
    gold_edges = [r for r in gold_parts if r.get("record_type") == "wire_edge"]
    skipped = [r for r in gold_parts if r.get("record_type") == "skipped"]

    edges = clean_edges + gold_edges
    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "overflow_align_wire",
            "edge": ALIGNED_TO,
            "edge_key": EDGE_KEY,
            "stage": 8,
            "inventory": apply_meta.get("inventory"),
            "calendar_lo": apply_meta.get("calendar_lo"),
            "calendar_hi": apply_meta.get("calendar_hi"),
            "include_uncertain": include_uncertain,
            "n_clean_split_edges": len(clean_edges),
            "n_cut_gold_edges": len(gold_edges),
            "n_skipped": len(skipped),
            "policy": (
                "Scoped production ALIGNED_TO:overflow only. Clean-split encoder "
                "MATCH (observed=False) + certain cut gold 1:1 editorial "
                "(observed=True). Parent flat + char span detail. No PINNED_TO."
            ),
            **scope_meta(),
        },
        *edges,
        *skipped,
    ]
    gate_ok = len(edges) > 0
    rows.append({
        "record_type": "summary",
        "n_wire_edges": len(edges),
        "n_clean_split_edges": len(clean_edges),
        "n_cut_gold_edges": len(gold_edges),
        "n_skipped": len(skipped),
        "gate": "PASS" if gate_ok else "FAIL_OR_THIN",
        "next": (
            "Re-run with --push-graph to plow edges into sequence_graph_edges; "
            "still no PINNED_TO rewrite. Widen window only after coverage log."
        ),
    })
    rows[0]["gate"] = rows[-1]["gate"]
    return rows


def push_wire_edges_to_graph(
    graph: Any,
    wire_rows: list[dict[str, Any]],
) -> int:
    """Add ALIGNED_TO:overflow edges for wire_edge rows. Returns edges added."""
    added = 0
    for row in wire_rows:
        if row.get("record_type") != "wire_edge":
            continue
        flat_id = str(row["flat_id"])
        if not is_main_series(flat_id):
            continue
        date = str(row["date"])
        index = int(row["resolution_index"])
        if not in_scope(date):
            continue
        enriched_node = EnrichedResolution(date=date, index=index).node_id
        htr_node = HtrResolution.from_flat_id(flat_id).node_id
        if enriched_node not in graph or htr_node not in graph:
            continue
        graph.add_edge(
            enriched_node,
            htr_node,
            key=EDGE_KEY,
            kind=ALIGNED_TO,
            evidence=Evidence(
                channel=str(row["channel"]),
                source="sequence_graph.overflow_align_wire",
                observed=bool(row["observed"]),
                confidence=None,
                detail={
                    "flat_id": flat_id,
                    "volgnr": row.get("volgnr"),
                    "segment_rank": row.get("segment_rank"),
                    "char_start": row.get("char_start"),
                    "char_end": row.get("char_end"),
                    "cuts": list(row.get("cuts") or []),
                    "cut_source": row.get("cut_source"),
                    "kind": row.get("kind"),
                    "uncertain": bool(row.get("uncertain")),
                },
            ),
        )
        added += 1
    return added


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"persist {OUTPUT_DATASET}",
    )
    parser.add_argument(
        "--push-graph",
        action="store_true",
        help="add ALIGNED_TO:overflow edges to the saved sequence graph",
    )
    parser.add_argument(
        "--include-uncertain",
        action="store_true",
        help="attempt uncertain cut gold (still skips count mismatches)",
    )
    args = parser.parse_args(argv)

    rows = run_overflow_align_wire(include_uncertain=args.include_uncertain)
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    print(
        f"overflow_align_wire  gate={meta['gate']}  "
        f"edges={summary['n_wire_edges']}  "
        f"clean={summary['n_clean_split_edges']}  "
        f"cut_gold={summary['n_cut_gold_edges']}  "
        f"skipped={summary['n_skipped']}"
    )
    print(f"  next: {summary.get('next')}")
    kinds = Counter(r.get("record_type") for r in rows)
    print(f"  records: {dict(kinds)}")

    if args.write:
        path = save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[APPLY_DATASET, CUT_GOLD],
        )
        from sequence_graph.remediation_run_log import log_overflow_wire

        log_overflow_wire(rows)
        print(f"wrote {path}")

    if args.push_graph:
        graph = load_graph()
        n = push_wire_edges_to_graph(graph, rows)
        coverage = save_loaded_graph(graph)
        print(f"pushed {n} ALIGNED_TO:overflow edges")
        print("ALIGNED_TO coverage, before -> after:")
        for name, after_value in coverage["after"].items():
            before_value = (coverage["before"] or {}).get(name)
            print(f"  {name:<25}{str(before_value):>8} -> {after_value}")


if __name__ == "__main__":
    main()

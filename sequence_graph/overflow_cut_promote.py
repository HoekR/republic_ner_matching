"""Step 7c: promote approved overflow cut reviews into cut gold.

Reads ``overflow_cut_reviews`` (verdict=approve → is_gold) and joins
``aligned_to_overflow_track_gold`` cut_proposal context. Writes a new dataset
``overflow_cut_gold`` with ``cut_proposal`` rows flipped to ``is_gold: true``
and human ``gold_offsets`` — does **not** mutate the machine track-gold file.

Production ``ALIGNED_TO`` wire is Step 8 (``overflow_align_wire``); never ``PINNED_TO``.

Usage:
    uv run python -m sequence_graph.overflow_cut_promote --write
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from data_io import load, resolve, save_semi_structured
from overflow_cut_labeller.store import (
    ANNOTATIONS_LOGICAL,
    load_annotations,
    normalize_annotation,
)
from scripts.corpus_scope import scope_meta

OUTPUT_DATASET = "overflow_cut_gold"
TRACK_GOLD = "aligned_to_overflow_track_gold"
APPLY_DATASET = "overflow_align_apply"


def approved_reviews(annotations: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return flat_id → normalized approve rows with is_gold and gold_offsets."""
    out: dict[str, dict[str, Any]] = {}
    for flat_id, raw in (annotations.get("annotations") or {}).items():
        row = normalize_annotation(dict(raw or {}))
        if row.get("verdict") != "approve" or not row.get("is_gold"):
            continue
        offsets = [int(c) for c in (row.get("gold_offsets") or [])]
        if not offsets:
            continue
        out[str(flat_id)] = {
            **row,
            "gold_offsets": offsets,
        }
    return out


def _cut_proposal_index(track_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(r["flat_id"]): r
        for r in track_rows
        if r.get("record_type") == "cut_proposal" and r.get("flat_id")
    }


def run_overflow_cut_promote(
    *,
    annotations: dict[str, Any] | None = None,
    track_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build overflow_cut_gold rows from approved reviews + track cut_proposal."""
    if annotations is None:
        resolve(ANNOTATIONS_LOGICAL)
        annotations = load_annotations()
    if track_rows is None:
        resolve(TRACK_GOLD)
        track_rows = list(load(TRACK_GOLD))

    approved = approved_reviews(annotations)
    proposals = _cut_proposal_index(track_rows)

    n_ann = len(annotations.get("annotations") or {})
    n_skip = sum(
        1
        for r in (annotations.get("annotations") or {}).values()
        if normalize_annotation(dict(r or {})).get("verdict") == "skip"
    )
    n_defer = sum(
        1
        for r in (annotations.get("annotations") or {}).values()
        if normalize_annotation(dict(r or {})).get("verdict") == "defer"
    )

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "overflow_cut_promote",
            "edge": "ALIGNED_TO",
            "stage": "6_cut_gold",
            "n_review_annotations": n_ann,
            "n_approved": len(approved),
            "n_skip": n_skip,
            "n_defer": n_defer,
            "policy": (
                "Approved overflow_cut_reviews gold_offsets promoted to "
                "cut_proposal is_gold=true. Machine track-gold cut_proposal "
                "rows left unchanged. No PINNED_TO / production ALIGNED_TO wire."
            ),
            **scope_meta(),
        }
    ]

    n_uncertain = 0
    n_missing_proposal = 0
    for flat_id in sorted(approved):
        review = approved[flat_id]
        prop = proposals.get(flat_id) or {}
        if not prop:
            n_missing_proposal += 1
        offsets = list(review["gold_offsets"])
        uncertain = bool(review.get("uncertain"))
        if uncertain:
            n_uncertain += 1
        n_claimants = prop.get("n_claimants")
        expected_cuts = (
            max(0, int(n_claimants) - 1) if n_claimants is not None else None
        )
        rows.append({
            "record_type": "cut_proposal",
            "flat_id": flat_id,
            "session_id": prop.get("session_id"),
            "gold_offsets": offsets,
            "n_cuts": len(offsets),
            "n_claimants": n_claimants,
            "claimant_volgnrs": list(prop.get("claimant_volgnrs") or []),
            "expected_cuts": expected_cuts,
            "expected_cuts_disagrees": (
                expected_cuts is not None and len(offsets) != expected_cuts
            ),
            "encoder_cuts": prop.get("encoder_cuts"),
            "even_split_cuts": prop.get("even_split_cuts"),
            "encoder_available": prop.get("encoder_available"),
            "model_name": prop.get("model_name"),
            "checkpoint": prop.get("checkpoint"),
            "flat_char_len": prop.get("flat_char_len"),
            "uncertain": uncertain,
            "note": review.get("note") or "",
            "source_review": ANNOTATIONS_LOGICAL,
            "is_gold": True,
            "policy": (
                "Human-approved cut gold from overflow_cut_reviews. "
                "Not a production ALIGNED_TO wire."
            ),
        })

    gate_ok = len(approved) > 0 and n_missing_proposal == 0
    rows[0].update({
        "n_uncertain": n_uncertain,
        "n_missing_track_proposal": n_missing_proposal,
        "gate": "PASS" if gate_ok else "FAIL_OR_THIN",
    })
    rows.append({
        "record_type": "summary",
        "n_cut_gold": len(approved),
        "n_uncertain": n_uncertain,
        "n_missing_track_proposal": n_missing_proposal,
        "gate": rows[0]["gate"],
        "next": (
            "Step 8: uv run python -m sequence_graph.overflow_align_wire "
            "--write --push-graph (scoped ALIGNED_TO:overflow; no PINNED_TO)."
        ),
    })
    return rows


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
    args = parser.parse_args(argv)
    rows = run_overflow_cut_promote()
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    print(
        f"overflow_cut_promote  gate={meta['gate']}  "
        f"approved={meta['n_approved']}  uncertain={meta['n_uncertain']}  "
        f"missing_proposal={meta['n_missing_track_proposal']}"
    )
    print(f"  next: {summary.get('next')}")
    kinds = Counter(r.get("record_type") for r in rows)
    print(f"  records: {dict(kinds)}")
    if args.write:
        path = save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[ANNOTATIONS_LOGICAL, TRACK_GOLD, APPLY_DATASET],
        )
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

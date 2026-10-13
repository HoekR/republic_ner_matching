"""Stage 6 apply: fingerprint-gated overflow → align_bracket on hard lids.

Consumes ``fingerprint_overflow_split_proof`` multi-claim flats + cut proposals
and ``hard_recalibrate_proof`` lids. Expands each overflow flat into ordered
segments (encoder cuts preferred; even-split as control), then runs
``align_bracket`` (entity + TF-IDF fingerprint) so claimants can MATCH segments.

Doctrine:
  - Dating stays stages 2–4 (hard lids name the window; content session owns the
    HTR stream — do not joint-fix pin conflicts here).
  - Cut offsets stay ``is_gold: false`` until human treatment.
  - No production ``PINNED_TO`` / ``ALIGNED_TO`` wire.

Usage:
    uv run python -m sequence_graph.overflow_align_apply --write
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from data_io import load, save_semi_structured
from scripts.corpus_scope import drop_out_of_scope, in_scope, is_main_series, scope_meta
from sequence_graph.align import (
    INSERTION_SPLIT,
    MATCH,
    CostModel,
    AlignmentResult,
    build_entity_overlap_scorer,
)
from sequence_graph.fingerprint_session_shift import (
    OVERFLOW_SPLIT_DATASET,
    _enriched_text_by_volgnr,
    _flat_text_by_id,
    _flats_for_session,
)
from sequence_graph.hard_recalibrate import _chunk_entity_fingerprint_scorer
from sequence_graph.resolution_fingerprint_eval import (
    FINGERPRINT_OVERLAP_SCALE,
    fit_fingerprint_on_tier1,
)
from sequence_graph.sync_gap_align import (
    _axis_by_inv_sess,
    _path_summary,
    align_streams,
)

OUTPUT_DATASET = "overflow_align_apply"
HARD_RECAL = "hard_recalibrate_proof"
CHANNEL = "overflow_segment_dp"
def normalize_cuts(cuts: list[Any] | None, text_len: int, n_cuts: int) -> list[int]:
    """Clamp/sort unique interior cut offsets; pad/truncate to ``n_cuts`` if needed."""
    if n_cuts <= 0 or text_len <= 1:
        return []
    raw: list[int] = []
    for c in cuts or []:
        try:
            raw.append(int(c))
        except (TypeError, ValueError):
            continue
    cleaned = sorted({c for c in raw if 0 < c < text_len})
    if len(cleaned) >= n_cuts:
        return cleaned[:n_cuts]
    # Fall back to even split for missing slots
    even = [
        max(1, min(text_len - 1, (text_len * (i + 1)) // (n_cuts + 1)))
        for i in range(n_cuts)
    ]
    merged = sorted(set(cleaned) | set(even))
    return merged[:n_cuts]


def slice_segments(text: str, cuts: list[int]) -> list[str]:
    """Split ``text`` at sorted interior cut offsets into contiguous segments."""
    if not text:
        return [""]
    bounds = [0, *normalize_cuts(cuts, len(text), len(cuts)), len(text)]
    # Drop duplicate bounds after normalize
    uniq: list[int] = []
    for b in bounds:
        if not uniq or b != uniq[-1]:
            uniq.append(b)
    if len(uniq) < 2:
        return [text]
    return [text[uniq[i] : uniq[i + 1]] for i in range(len(uniq) - 1)]


def segment_ids(flat_id: str, n: int) -> list[str]:
    return [f"{flat_id}::seg{i}" for i in range(n)]


def order_match_rate(result: AlignmentResult, n: int) -> float | None:
    """Share of refs that MATCH the same-index read (diagonal), among MATCHed refs."""
    if n <= 0:
        return None
    matched = 0
    diagonal = 0
    for pair in result.pairs:
        if pair.kind != MATCH or pair.ref_index is None or pair.read_index is None:
            continue
        matched += 1
        if pair.ref_index == pair.read_index:
            diagonal += 1
    if matched == 0:
        return 0.0
    return round(diagonal / matched, 4)


def _parse_volgnr_key(volgnr: str) -> tuple[str, int]:
    """Editorial order key: calendar date then index (never HALF preference)."""
    if len(volgnr) >= 12 and volgnr[10] == "_":
        date, _, idx = volgnr.partition("_")
        try:
            return date, int(idx)
        except ValueError:
            return volgnr, 0
    return volgnr, 0


def _ordered_claimants(
    prop: dict[str, Any],
    half_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[str]:
    """Claimants in editorial stream order (volgnr). HALF ranks stay diagnostic only.

    Drops out-of-scope dates at entry via ``drop_out_of_scope`` (fail closed) —
    do not rely on upstream proof filtering alone.
    """
    del half_by_key  # retained in signature for call-site clarity; not used for DP order
    vols = [str(v) for v in (prop.get("claimant_volgnrs") or [])]
    in_scope_vols, _dropped = drop_out_of_scope(vols, lambda v: v[:10])
    return sorted(in_scope_vols, key=_parse_volgnr_key)


def _hard_window_meta() -> dict[str, Any]:
    try:
        rows = list(load(HARD_RECAL))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"{HARD_RECAL} missing — run hard_recalibrate --write") from exc
    meta = next((r for r in rows if r.get("record_type") == "meta"), {})
    hard_maps = [
        r for r in rows if r.get("record_type") == "hard_map" and r.get("active")
    ]
    return {
        "inventory": meta.get("inventory") or "3185",
        "calendar_lo": meta.get("calendar_lo"),
        "calendar_hi": meta.get("calendar_hi"),
        "hard_sessions": {str(r["session_id"]) for r in hard_maps if r.get("session_id")},
        "production_sessions": {
            str(r["production_session"])
            for r in hard_maps
            if r.get("production_session")
        },
        "hard_maps": hard_maps,
        "meta": meta,
    }


def _in_hard_window(session_id: str, hard: dict[str, Any]) -> bool:
    """Content session is eligible if it is a hard lid or the production side of one."""
    return (
        session_id in hard["hard_sessions"]
        or session_id in hard["production_sessions"]
    )


def _align_claimants_to_segments(
    *,
    volgnrs: list[str],
    segment_keys: list[str],
    seg_texts: dict[str, str],
    enr_text: dict[str, str],
    fingerprint: Any,
    entity_scorer: Any,
) -> tuple[AlignmentResult, dict[tuple[int, int], float], dict[str, Any]]:
    scorer = _chunk_entity_fingerprint_scorer(
        volgnrs,
        segment_keys,
        entity_scorer=entity_scorer,
        fingerprint=fingerprint,
        enr_text=enr_text,
        flat_text=seg_texts,
    )
    result, cache = align_streams(volgnrs, segment_keys, scorer, cost=CostModel())
    summary = _path_summary(result, cache)
    summary["order_match_rate"] = order_match_rate(result, len(volgnrs))
    summary["n_insertion_split"] = summary.get("move_counts", {}).get(
        INSERTION_SPLIT, 0
    )
    return result, cache, summary


def _pair_rows(
    *,
    flat_id: str,
    session_id: str,
    cut_source: str,
    volgnrs: list[str],
    segment_keys: list[str],
    result: AlignmentResult,
    cache: dict[tuple[int, int], float],
    cuts: list[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in result.pairs:
        row: dict[str, Any] = {
            "record_type": "align_pair",
            "flat_id": flat_id,
            "session_id": session_id,
            "cut_source": cut_source,
            "move_kind": pair.kind,
            "ref_index": pair.ref_index,
            "read_index": pair.read_index,
            "step_cost": round(pair.cost, 4),
            "cuts": cuts,
            "is_gold": False,
        }
        if pair.ref_index is not None and 0 <= pair.ref_index < len(volgnrs):
            row["volgnr"] = volgnrs[pair.ref_index]
        if pair.read_index is not None and 0 <= pair.read_index < len(segment_keys):
            row["segment_id"] = segment_keys[pair.read_index]
        if (
            pair.kind == MATCH
            and pair.ref_index is not None
            and pair.read_index is not None
        ):
            row["overlap"] = round(
                float(cache.get((pair.ref_index, pair.read_index), 0.0)), 4
            )
            row["order_ok"] = pair.ref_index == pair.read_index
        rows.append(row)
    return rows


def run_overflow_align_apply() -> list[dict[str, Any]]:
    """Expand overflow flats → align_bracket on hard-window content sessions."""
    try:
        proof = list(load(OVERFLOW_SPLIT_DATASET))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"{OVERFLOW_SPLIT_DATASET} missing — run "
            "--on-overflow-split --write first"
        ) from exc

    hard = _hard_window_meta()
    proposals = [r for r in proof if r.get("record_type") == "split_proposal"]
    half_by_key = {
        (str(r["flat_id"]), str(r["volgnr"])): r
        for r in proof
        if r.get("record_type") == "half_window"
    }
    proof_meta = next((r for r in proof if r.get("record_type") == "meta"), {})

    exclude_dates: set[str] = set()
    if hard.get("calendar_lo") and hard.get("calendar_hi"):
        # Hold out the hard apply window from fingerprint fit (same discipline as recal).
        lo, hi = str(hard["calendar_lo"]), str(hard["calendar_hi"])
        for prop in proposals:
            for v in prop.get("claimant_volgnrs") or []:
                d = str(v)[:10]
                if in_scope(d) and lo <= d <= hi:
                    exclude_dates.add(d)

    fingerprint, fp_meta = fit_fingerprint_on_tier1(exclude_dates=exclude_dates)
    entity_scorer = build_entity_overlap_scorer()
    flat_texts = _flat_text_by_id()
    enr_text = _enriched_text_by_volgnr()
    axis_index = _axis_by_inv_sess()

    rows: list[dict[str, Any]] = [
        {
            "record_type": "meta",
            "mode": "overflow_align_apply",
            "edge": "ALIGNED_TO",
            "stage": 6,
            "inventory": hard["inventory"],
            "calendar_lo": hard["calendar_lo"],
            "calendar_hi": hard["calendar_hi"],
            "n_split_proposals": len(proposals),
            "overflow_proof_gate": proof_meta.get("gate"),
            "fingerprint_overlap_scale": FINGERPRINT_OVERLAP_SCALE,
            "evidence_channel": CHANNEL,
            "policy": (
                "Stage 6 apply: fingerprint-gated multi-claim flats expanded by "
                "cut_proposal offsets, then align_bracket (entity+fingerprint) on "
                "hard-window content sessions. Encoder cuts preferred; even-split "
                "control. Cuts is_gold=false. No PINNED_TO / production ALIGNED_TO wire."
            ),
            **fp_meta,
            **scope_meta(),
        }
    ]

    n_in_window = 0
    n_encoder_paths = 0
    n_claimant_match = 0
    n_claimant_total = 0
    n_order_ok = 0
    n_order_matched = 0
    n_lumped_deletion = 0

    for prop in sorted(proposals, key=lambda r: str(r.get("flat_id") or "")):
        flat_id = str(prop["flat_id"])
        sid = str(prop.get("session_id") or "")
        if not is_main_series(flat_id):
            continue
        if not _in_hard_window(sid, hard):
            rows.append({
                "record_type": "skipped",
                "flat_id": flat_id,
                "session_id": sid,
                "reason": "session_outside_hard_window",
            })
            continue
        claimants = _ordered_claimants(prop, half_by_key)
        if not claimants:
            rows.append({
                "record_type": "skipped",
                "flat_id": flat_id,
                "session_id": sid,
                "reason": "no_in_scope_claimants",
            })
            continue
        n_in_window += 1
        whole = flat_texts.get(flat_id) or ""
        n_cuts = max(0, len(claimants) - 1)
        enc_cuts = normalize_cuts(prop.get("encoder_cuts"), len(whole), n_cuts)
        even_cuts = normalize_cuts(prop.get("even_split_cuts"), len(whole), n_cuts)

        # Control: lumped flat (no expansion) — expect DELETION_GAP for extras
        lumped_scorer = _chunk_entity_fingerprint_scorer(
            claimants,
            [flat_id],
            entity_scorer=entity_scorer,
            fingerprint=fingerprint,
            enr_text=enr_text,
            flat_text={flat_id: whole},
        )
        lumped_result, lumped_cache = align_streams(
            claimants, [flat_id], lumped_scorer, cost=CostModel()
        )
        lumped_summary = _path_summary(lumped_result, lumped_cache)
        n_lumped_deletion += int(lumped_summary.get("n_deletion") or 0)
        rows.append({
            "record_type": "lumped_baseline",
            "flat_id": flat_id,
            "session_id": sid,
            "n_claimants": len(claimants),
            "claimant_volgnrs": claimants,
            **lumped_summary,
            "note": "Unexpanded flat: extras should DELETION_GAP — shows why split is needed.",
        })

        for cut_source, cuts in (("encoder", enc_cuts), ("even_split", even_cuts)):
            if n_cuts > 0 and not cuts:
                rows.append({
                    "record_type": "flat_apply",
                    "flat_id": flat_id,
                    "session_id": sid,
                    "cut_source": cut_source,
                    "status": "no_cuts",
                    "n_claimants": len(claimants),
                    "is_gold": False,
                })
                continue
            segs = slice_segments(whole, cuts)
            if len(segs) != len(claimants):
                # Force segment count to claimants via even bounds if encoder oddity
                segs = slice_segments(
                    whole,
                    normalize_cuts(
                        [
                            max(1, min(len(whole) - 1, (len(whole) * (i + 1)) // len(claimants)))
                            for i in range(n_cuts)
                        ],
                        len(whole),
                        n_cuts,
                    ),
                )
            keys = segment_ids(flat_id, len(segs))
            seg_texts = dict(zip(keys, segs, strict=True))
            result, cache, summary = _align_claimants_to_segments(
                volgnrs=claimants,
                segment_keys=keys,
                seg_texts=seg_texts,
                enr_text=enr_text,
                fingerprint=fingerprint,
                entity_scorer=entity_scorer,
            )
            status = "ok"
            if result.abstained:
                status = "abstained"
            rows.append({
                "record_type": "flat_apply",
                "flat_id": flat_id,
                "session_id": sid,
                "cut_source": cut_source,
                "status": status,
                "n_claimants": len(claimants),
                "n_segments": len(keys),
                "claimant_volgnrs": claimants,
                "segment_ids": keys,
                "cuts": cuts,
                "flat_char_len": len(whole),
                "segment_char_lens": [len(s) for s in segs],
                "is_gold": False,
                "encoder_available": bool(prop.get("encoder_available")),
                **summary,
            })
            rows.extend(
                _pair_rows(
                    flat_id=flat_id,
                    session_id=sid,
                    cut_source=cut_source,
                    volgnrs=claimants,
                    segment_keys=keys,
                    result=result,
                    cache=cache,
                    cuts=cuts,
                )
            )
            if cut_source == "encoder":
                n_encoder_paths += 1
                n_claimant_total += len(claimants)
                n_claimant_match += int(summary.get("n_match") or 0)
                for pair in result.pairs:
                    if pair.kind != MATCH:
                        continue
                    n_order_matched += 1
                    if pair.ref_index == pair.read_index:
                        n_order_ok += 1
                n_match = int(summary.get("n_match") or 0)
                if n_match == len(claimants) and summary.get("order_match_rate") == 1.0:
                    rows.append({
                        "record_type": "residual_gap",
                        "after_stage": 6,
                        "kind": "clean_split",
                        "flat_id": flat_id,
                        "session_id": sid,
                        "size_claimants": len(claimants),
                        "note": "Encoder segments MATCH claimants 1:1 in editorial order.",
                    })
                else:
                    rows.append({
                        "record_type": "residual_gap",
                        "after_stage": 6,
                        "kind": "needs_human_cuts",
                        "flat_id": flat_id,
                        "session_id": sid,
                        "size_claimants": len(claimants),
                        "size_matched": n_match,
                        "size_insertion_split": int(
                            summary.get("n_insertion_split") or 0
                        ),
                        "size_deletion": int(summary.get("n_deletion") or 0),
                        "order_match_rate": summary.get("order_match_rate"),
                        "cuts": cuts,
                        "note": (
                            "Machine cuts leave INSERTION_SPLIT/DELETION_GAP — "
                            "human cut/treatment review before promote."
                        ),
                    })

        # Session-level expanded stream (encoder cuts) under hard window
        session_flats = _flats_for_session(sid, axis_index)
        if session_flats and claimants:
            expanded: list[str] = []
            expanded_texts: dict[str, str] = {}
            for fid in session_flats:
                if fid == flat_id and n_cuts > 0 and enc_cuts:
                    segs = slice_segments(whole, enc_cuts)
                    keys = segment_ids(fid, len(segs))
                    expanded.extend(keys)
                    for k, s in zip(keys, segs, strict=True):
                        expanded_texts[k] = s
                else:
                    expanded.append(fid)
                    expanded_texts[fid] = flat_texts.get(fid) or ""
            # Refs = all neighbourhood assignments on this session from proof
            sess_volgnrs = sorted(
                {
                    str(a["volgnr"])
                    for a in proof
                    if a.get("record_type") == "assignment"
                    and a.get("session_id") == sid
                    and a.get("volgnr")
                }
            )
            if len(sess_volgnrs) >= 1 and len(expanded) >= 1:
                scorer = _chunk_entity_fingerprint_scorer(
                    sess_volgnrs,
                    expanded,
                    entity_scorer=entity_scorer,
                    fingerprint=fingerprint,
                    enr_text=enr_text,
                    flat_text=expanded_texts,
                )
                sess_result, sess_cache = align_streams(
                    sess_volgnrs, expanded, scorer, cost=CostModel()
                )
                sess_summary = _path_summary(sess_result, sess_cache)
                sess_summary["n_insertion_split"] = sess_summary.get(
                    "move_counts", {}
                ).get(INSERTION_SPLIT, 0)
                rows.append({
                    "record_type": "session_apply",
                    "session_id": sid,
                    "overflow_flat_id": flat_id,
                    "cut_source": "encoder",
                    "n_ref": len(sess_volgnrs),
                    "n_read_expanded": len(expanded),
                    "n_read_lumped": len(session_flats),
                    "lids": "hard_window_content_session",
                    "is_gold": False,
                    **sess_summary,
                })

    match_rate = (
        round(n_claimant_match / n_claimant_total, 4) if n_claimant_total else None
    )
    order_rate = (
        round(n_order_ok / n_order_matched, 4) if n_order_matched else None
    )
    residuals = [r for r in rows if r.get("record_type") == "residual_gap"]
    n_clean = sum(1 for r in residuals if r.get("kind") == "clean_split")
    n_needs_human = sum(1 for r in residuals if r.get("kind") == "needs_human_cuts")
    # 2-claimant flats are the mechanism smoke test; larger overflows may residual.
    two_way = [
        r
        for r in rows
        if r.get("record_type") == "flat_apply"
        and r.get("cut_source") == "encoder"
        and int(r.get("n_claimants") or 0) == 2
    ]
    two_way_ok = bool(two_way) and all(
        int(r.get("n_match") or 0) == 2 and r.get("order_match_rate") == 1.0
        for r in two_way
    )
    # Imperfect closure OK: every in-window flat typed clean or needs_human_cuts.
    gate_ok = (
        n_in_window > 0
        and n_encoder_paths == n_in_window
        and two_way_ok
        and (n_clean + n_needs_human) == n_in_window
        and n_lumped_deletion > 0  # expansion must beat lumped baseline
    )
    rows[0].update({
        "n_overflow_in_hard_window": n_in_window,
        "n_encoder_paths": n_encoder_paths,
        "n_claimant_total": n_claimant_total,
        "n_claimant_match": n_claimant_match,
        "claimant_match_rate": match_rate,
        "order_match_rate": order_rate,
        "n_lumped_deletion_sum": n_lumped_deletion,
        "n_clean_split": n_clean,
        "n_needs_human_cuts": n_needs_human,
        "two_way_mechanism_ok": two_way_ok,
        "gate": "PASS" if gate_ok else "FAIL_OR_THIN",
    })
    rows.append({
        "record_type": "summary",
        "n_overflow_in_hard_window": n_in_window,
        "n_encoder_paths": n_encoder_paths,
        "claimant_match_rate": match_rate,
        "order_match_rate": order_rate,
        "n_lumped_deletion_sum": n_lumped_deletion,
        "n_clean_split": n_clean,
        "n_needs_human_cuts": n_needs_human,
        "two_way_mechanism_ok": two_way_ok,
        "gate": rows[0]["gate"],
        "next": (
            "Human cut/treatment review on needs_human_cuts flats; "
            "promote cuts only after approve. Production wire still deferred."
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
    rows = run_overflow_align_apply()
    meta = next(r for r in rows if r.get("record_type") == "meta")
    summary = next(r for r in rows if r.get("record_type") == "summary")
    print(
        f"overflow_align_apply  gate={meta['gate']}  "
        f"in_window={meta['n_overflow_in_hard_window']}  "
        f"match_rate={meta['claimant_match_rate']}  "
        f"order_rate={meta['order_match_rate']}  "
        f"lumped_deletions={meta['n_lumped_deletion_sum']}"
    )
    print(f"  next: {summary.get('next')}")
    kinds = Counter(r.get("record_type") for r in rows)
    print(f"  records: {dict(kinds)}")
    if args.write:
        path = save_semi_structured(
            rows,
            logical_name=OUTPUT_DATASET,
            script=__file__,
            parent_sources=[OVERFLOW_SPLIT_DATASET, HARD_RECAL],
        )
        from sequence_graph.remediation_run_log import log_overflow_apply

        log_overflow_apply(rows)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

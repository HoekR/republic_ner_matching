#!/usr/bin/env python3
"""Run precision benchmark on labeled ground truth with LLM judge for unanchored candidates.

Evaluates:
  1. Base sequence alignment (Place + Org + Person anchors + TF-IDF)
  2. Filtered alignment using local LLM judge (llama3.2:latest) for ambiguous / zero-anchor diagonal pairs

Usage:
    uv run python benchmark_llm_judge.py
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from alignment_llm_judge import check_ollama_available, evaluate_pair
from build_alignment_new import (
    OUTPUT_DIR,
    load_data,
    enriched_volgnr,
    enriched_text,
    candidate_text,
)

LABELED_FILE = OUTPUT_DIR / "ground_truth_labeled.json"
STRAT_MATCHES_FILE = OUTPUT_DIR / "ground_truth_stratified_matches.json"
BENCHMARK_OUTPUT_FILE = OUTPUT_DIR / "llm_judge_benchmark_results.json"


def main() -> None:
    print("Loading labeled ground truth and stratified sequence matches...")
    with open(LABELED_FILE, "r", encoding="utf-8") as f:
        gt_list = json.load(f)
    with open(STRAT_MATCHES_FILE, "r", encoding="utf-8") as f:
        strat_list = json.load(f)

    gt_dict = {
        (item["enriched_id"], item["flat_id"]): item
        for item in gt_list
    }
    strat_dict = {
        (item["enriched_id"], item["flat_id"]): item
        for item in strat_list
    }

    ollama_ok = check_ollama_available()
    print(f"Ollama daemon available: {ollama_ok}")
    if not ollama_ok:
        print("⚠ Please start Ollama before running this benchmark.")
        return

    enriched_all, res_df, places_df, orgs_df, loc_names, per_names, org_names, persons_df = load_data()
    enriched_by_id = {enriched_volgnr(e): e for e in enriched_all if enriched_volgnr(e)}
    flat_by_id = dict(zip(res_df["id"].astype(str), res_df.to_dict("records")))

    results = []
    
    # Track metrics
    total_judged = len(gt_dict)
    retained_in_sequence = 0
    correct_base = 0
    fp_base = 0

    llm_accepted_correct = 0
    llm_accepted_fp = 0
    llm_rejected_correct = 0
    llm_rejected_fp = 0

    print(f"\nEvaluating {len(gt_dict)} ground-truth pairs...")

    for (eid, fid), gt_entry in gt_dict.items():
        verdict = gt_entry.get("verdict", "unknown")
        in_sequence = (eid, fid) in strat_dict
        strat_entry = strat_dict.get((eid, fid))

        overlap_score = strat_entry.get("overlap_score", 0.0) if strat_entry else 0.0
        semantic_sim = strat_entry.get("semantic_similarity", 0.0) if strat_entry else 0.0

        if not in_sequence:
            results.append({
                "enriched_id": eid,
                "flat_id": fid,
                "verdict": verdict,
                "in_sequence": False,
                "overlap_score": 0.0,
                "llm_action": "dropped_by_sequence",
                "final_decision": "rejected",
            })
            continue

        retained_in_sequence += 1
        if verdict == "correct":
            correct_base += 1
        elif verdict == "false_positive":
            fp_base += 1

        # Decision rule:
        # If strong anchor (overlap_score >= 2.0), accept directly.
        # If low/no anchor (overlap_score < 2.0), ask LLM Judge.
        if overlap_score >= 2.0:
            llm_decision = "match"
            confidence = 1.0
            reason = "High entity overlap score (anchor)"
            final_decision = "accepted"
            if verdict == "correct":
                llm_accepted_correct += 1
            elif verdict == "false_positive":
                llm_accepted_fp += 1
        else:
            enr_record = enriched_by_id.get(eid)
            flat_record = flat_by_id.get(fid)
            enr_t = enriched_text(enr_record) if enr_record else ""
            flat_t = candidate_text(flat_record) if flat_record else ""

            judgement = evaluate_pair(enr_t, flat_t, model="llama3.2:latest")
            llm_decision = judgement.decision
            confidence = judgement.confidence
            reason = judgement.reason

            if llm_decision == "match":
                final_decision = "accepted"
                if verdict == "correct":
                    llm_accepted_correct += 1
                elif verdict == "false_positive":
                    llm_accepted_fp += 1
            else:
                final_decision = "rejected"
                if verdict == "correct":
                    llm_rejected_correct += 1
                elif verdict == "false_positive":
                    llm_rejected_fp += 1

        results.append({
            "enriched_id": eid,
            "flat_id": fid,
            "verdict": verdict,
            "in_sequence": True,
            "overlap_score": round(overlap_score, 2),
            "semantic_sim": round(semantic_sim, 3),
            "llm_decision": llm_decision,
            "confidence": confidence,
            "reason": reason,
            "final_decision": final_decision,
        })
        print(f"  [{verdict:14s}] overlap={overlap_score:4.1f} -> LLM: {llm_decision:9s} (final: {final_decision}) | {eid}")

    total_final_accepted = llm_accepted_correct + llm_accepted_fp
    final_precision = (llm_accepted_correct / total_final_accepted * 100) if total_final_accepted > 0 else 0.0

    print("\n" + "=" * 50)
    print("=== BENCHMARK SUMMARY ===")
    print(f"Total Judged Reference Pairs: {total_judged}")
    print(f"\n--- BASE SEQUENCE ALIGNMENT ---")
    print(f"Retained by sequence alignment: {retained_in_sequence}")
    print(f"  - Correct: {correct_base}")
    print(f"  - False Positives: {fp_base}")
    print(f"  - Base Precision: {correct_base / retained_in_sequence * 100:.1f}%")
    print(f"\n--- WITH TARGETED LLM JUDGE (llama3.2:latest) ---")
    print(f"Final Accepted Matches: {total_final_accepted}")
    print(f"  - Correct Accepted (True Positives): {llm_accepted_correct}")
    print(f"  - False Positives Accepted: {llm_accepted_fp}")
    print(f"  - False Positives Filtered (True Negatives): {llm_rejected_fp}")
    print(f"  - Correct Dropped (False Negatives): {llm_rejected_correct}")
    print(f"  - LLM Filtered Precision: {final_precision:.1f}%")
    print("=" * 50)

    with open(BENCHMARK_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_judged": total_judged,
                "base_precision_pct": round(correct_base / retained_in_sequence * 100, 1),
                "llm_precision_pct": round(final_precision, 1),
                "true_positives": llm_accepted_correct,
                "false_positives": llm_accepted_fp,
                "true_negatives_filtered": llm_rejected_fp,
                "false_negatives": llm_rejected_correct,
                "results": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"✓ Saved full benchmark details to {BENCHMARK_OUTPUT_FILE}")


if __name__ == "__main__":
    main()

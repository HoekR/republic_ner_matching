#!/usr/bin/env python3
"""Batch LLM judge for Tier 3 boundary/unanchored candidate resolutions.

Takes unanchored opening templates (tier3_head_template) and tail resolutions (tier3_tail)
from the frozen alignment dataset and routes them through local Ollama (llama3.2:latest)
to verify matches vs unrecorded resolutions.

Usage:
    uv run python judge_tier3_candidates.py --limit 30
    uv run python judge_tier3_candidates.py --all
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tqdm import tqdm
import pandas as pd

from alignment_llm_judge import check_ollama_available, evaluate_pair
from data_io import load, resolve, save_semi_structured

ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "output" / "tier3_llm_judgements.jsonl"


def load_cached_judgements(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    cached = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    cached[(obj["enriched_id"], obj["flat_id"])] = obj
                except json.JSONDecodeError:
                    pass
    return cached


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch judge Tier 3 alignment candidates with local LLM.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum unjudged pairs to process (0 = all)")
    parser.add_argument("--all", action="store_true", help="Process all Tier 3 candidates")
    parser.add_argument("--model", type=str, default="llama3.2:latest", help="Ollama model name")
    parser.add_argument("--tier", type=str, default="all", choices=["all", "tier3_head_template", "tier3_tail"], help="Filter by specific tier")
    args = parser.parse_args()

    if not check_ollama_available():
        print("⚠ Local Ollama daemon is not running at http://localhost:11434.")
        print("  Please start Ollama (e.g. `ollama serve`) and ensure the model is pulled:")
        print(f"  `ollama pull {args.model}`")
        return

    print("Loading frozen alignment dataset...")
    df = load("alignment_1626_1630")
    print(f"✓ Loaded {len(df)} alignment rows.")

    # Filter to Tier 3 rows
    if args.tier == "all":
        df_tier3 = df[df["confidence_tier"].str.startswith("tier3")].copy()
    else:
        df_tier3 = df[df["confidence_tier"] == args.tier].copy()

    print(f"✓ Found {len(df_tier3)} candidates in {args.tier} (head templates & unanchored tails).")

    cached_map = load_cached_judgements(OUTPUT_FILE)
    print(f"✓ Loaded {len(cached_map)} existing cached judgements.")

    to_process = []
    for _, row in df_tier3.iterrows():
        pair_key = (str(row["enriched_id"]), str(row["flat_id"]))
        if pair_key not in cached_map:
            to_process.append(row)

    print(f"✓ Remaining unjudged candidates: {len(to_process)}")

    if not to_process:
        print("All candidate pairs are already judged in cache.")
    else:
        limit = len(to_process) if args.all or args.limit <= 0 else min(args.limit, len(to_process))
        batch = to_process[:limit]
        print(f"\nProcessing {len(batch)} pairs with model {args.model}...")

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f_out:
            for row in tqdm(batch, desc="LLM Judging"):
                eid = str(row["enriched_id"])
                fid = str(row["flat_id"])
                e_text = str(row.get("enriched_text") or "")
                f_text = str(row.get("flat_text") or "")

                verdict = evaluate_pair(e_text, f_text, model=args.model)
                rec = {
                    "enriched_id": eid,
                    "flat_id": fid,
                    "date": str(row.get("date")),
                    "session_id": str(row.get("session_id")),
                    "confidence_tier": str(row.get("confidence_tier")),
                    "overlap_score": float(row.get("overlap_score", 0.0)),
                    "semantic_similarity": float(row.get("semantic_similarity", 0.0)),
                    "llm_model": args.model,
                    "decision": verdict.decision,
                    "confidence": verdict.confidence,
                    "reason": verdict.reason,
                }
                f_out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f_out.flush()
                cached_map[(eid, fid)] = rec

    # Summarize all cached judgements for Tier 3
    all_judged = list(cached_map.values())
    match_count = sum(1 for j in all_judged if j.get("decision") == "match")
    no_match_count = sum(1 for j in all_judged if j.get("decision") == "no_match")
    uncertain_count = sum(1 for j in all_judged if j.get("decision") == "uncertain")

    print("\n" + "=" * 50)
    print("=== TIER 3 LLM JUDGEMENT SUMMARY ===")
    print(f"Total Judged in Cache: {len(all_judged)}")
    print(f"  - Confirmed Matches:   {match_count} ({match_count/len(all_judged)*100 if all_judged else 0:.1f}%)")
    print(f"  - Non-Matches (FPs):   {no_match_count} ({no_match_count/len(all_judged)*100 if all_judged else 0:.1f}%)")
    print(f"  - Uncertain:           {uncertain_count} ({uncertain_count/len(all_judged)*100 if all_judged else 0:.1f}%)")
    print("=" * 50)
    print(f"Cached results stored at: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

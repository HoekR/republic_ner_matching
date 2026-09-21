#!/usr/bin/env python3
"""POC: few-shot local-LLM split-point prediction on gold bundled paragraphs.

Companion to scripts/s4_bundled_split_poc.py -- same 22-position gold set
(bundled_positions), same scoring (score_predicted_cuts, tol 50/150 chars).
Existing baselines to beat: stage1 (entity-span even-split heuristic) 0/27
tol50, 9/27 tol150; stage2 (+ scoped dictionary lookup) 3/27 tol50, 11/27
tol150 (PLAN.md, 2026-09-18 split-point POC session).

This stage replaces the heuristic entirely: few-shot prompt a local model
with N *other* gold positions (leave-one-out, no self-leakage) as
"paragraph text -> interior cut character offsets" examples, then ask it to
predict cuts for the held-out position. The point is to test whether a model
reading raw text directly (formulaic openings, subject changes, proper
names) can beat the entity-count heuristic ceiling -- without fine-tuning on
the upstream NER tagger's own noisy labels, which this session's
docs/DECISIONS.md (2026-09-18) already ruled out as unable to close its own
training data's recall gap.

Uses mlx-lm (in-process, no daemon) via the vendored mlx_llm package, not
Ollama: Ollama's model weights on this machine live on an external USB
drive (`~/.ollama/models` -> `/Volumes/2tb disk/ollama_models`), which has
repeatedly caused load failures when unmounted or when its exFAT filesystem
corrupts model manifests -- see docs/wisdom/local-llm-model-storage.md. An
earlier version of this script worked around that by targeting LM Studio
instead; that in turn proved unreliable too, which is why the whole local-LLM
surface moved to mlx-lm (docs/DECISIONS.md). Note a cold (not-yet-loaded)
model's first call can legitimately take minutes just to read weights off
disk -- that is not a hang. Checkpointed per position (flat_id, para_index);
safe to --resume after a kill.

Usage:
    uv run python -m scripts.s4_llm_split_poc                # mlx_llm.DEFAULT_MODEL (unverified tag -- smoke test first, see mlx_llm/README.md)
    uv run python -m scripts.s4_llm_split_poc --limit 3       # smoke test
    uv run python -m scripts.s4_llm_split_poc --model mlx-community/Qwen2.5-14B-Instruct-4bit  # smaller/faster fallback
    uv run python -m scripts.s4_llm_split_poc --resume        # continue after a kill
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from mlx_llm import generate
from mlx_llm.model import DEFAULT_MODEL

from data_io import load, resolve
from data_io.provenance import ProvenanceRecord, git_commit_hash, write_sidecar
from scripts.s4_bundled_split_poc import TOLERANCES, bundled_positions, score_predicted_cuts
from scripts.s4_entity_density_split_diagnostic import AXIS_DATASET, GOLD_DATASET, review_codes

OUTPUT_LOGICAL_NAME = "s4_llm_split_poc"
N_FEWSHOT = 4

PROMPT_TEMPLATE = """You are analyzing 17th-century Dutch archival resolution text (Staten-Generaal minutes). \
A paragraph below actually contains multiple separate resolutions bundled together, without a paragraph break. \
Your job: find the exact character offset(s) where a NEW resolution begins inside the paragraph text \
(each new resolution typically starts with a formulaic opening like "Is ghelesen...", "Op de requeste van...", \
"Is goedgevonden...", or an abrupt new subject/proper name after a full stop).

{examples}
Now do the same for this paragraph. It contains exactly {k} interior cut point(s) ({k_plus_1} resolutions bundled together).

TEXT: {text}

Respond with ONLY a JSON list of {k} integer character offsets, e.g. [123] or [45, 210]. No other text.
"""

EXAMPLE_TEMPLATE = """TEXT: {text}
CUTS ({k} interior cut point(s)): {offsets}
"""


def build_prompt(target: dict[str, Any], examples: list[dict[str, Any]]) -> str:
    example_text = "\n".join(
        EXAMPLE_TEMPLATE.format(text=example["text"], k=example["target_splits"], offsets=example["gold_offsets"])
        for example in examples
    )
    return PROMPT_TEMPLATE.format(
        examples=example_text,
        k=target["target_splits"],
        k_plus_1=target["target_splits"] + 1,
        text=target["text"],
    )


def call_lmstudio(model: str, prompt: str, timeout: int = 900) -> str:
    """First call to a not-yet-loaded model can take minutes (multi-GB weights off disk);
    the 900s default covers a cold load, not just generation."""
    result = generate(prompt, model=model, temperature=0.0)
    if result is None:
        raise RuntimeError(f"Local LLM model {model} unavailable or generation failed")
    return result


def parse_offsets(raw_response: str) -> list[int] | None:
    match = re.search(r"\[[\d,\s]*\]", raw_response)
    if not match:
        return None
    try:
        offsets = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(offsets, list) or not all(isinstance(value, int) for value in offsets):
        return None
    return sorted(offsets)


def already_processed_keys(output_path: Path) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    if not output_path.exists():
        return keys
    with output_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            keys.add((record["flat_id"], record["para_index"]))
    return keys


def select_examples(positions: list[dict[str, Any]], target_index: int, n_fewshot: int) -> list[dict[str, Any]]:
    target = positions[target_index]
    pool = [position for index, position in enumerate(positions) if index != target_index]
    same_k = [position for position in pool if position["target_splits"] == target["target_splits"]]
    return (same_k or pool)[:n_fewshot]


def main() -> None:
    parser = argparse.ArgumentParser(description="Few-shot local-LLM split-point prediction POC.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None, help="Cap number of positions scanned (smoke test).")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--n-fewshot", type=int, default=N_FEWSHOT)
    args = parser.parse_args()

    gold = load(GOLD_DATASET)
    axis = load(AXIS_DATASET)
    codes = review_codes()
    positions = bundled_positions(gold, axis, codes)
    print(f"{len(positions)} bundled gold positions ({sum(p['target_splits'] for p in positions)} interior cuts)")

    output_path = resolve(OUTPUT_LOGICAL_NAME)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done = already_processed_keys(output_path) if args.resume else set()
    if not args.resume and output_path.exists():
        output_path.unlink()

    tally = {"abstain": 0, **{f"hits_tol{t}": 0 for t in TOLERANCES}}
    total_gold_cuts = 0
    scanned = 0

    mode = "a" if args.resume else "w"
    with output_path.open(mode, encoding="utf-8") as out_handle:
        for index, position in enumerate(positions):
            if args.limit is not None and scanned >= args.limit:
                break
            key = (position["flat_id"], position["para_index"])
            if key in done:
                continue
            scanned += 1
            total_gold_cuts += position["target_splits"]

            examples = select_examples(positions, index, args.n_fewshot)
            prompt = build_prompt(position, examples)
            raw_response = call_lmstudio(args.model, prompt)
            predicted = parse_offsets(raw_response)

            record: dict[str, Any] = {
                "date": position["date"],
                "flat_id": position["flat_id"],
                "para_index": position["para_index"],
                "target_splits": position["target_splits"],
                "gold_offsets": position["gold_offsets"],
                "raw_response": raw_response,
                "predicted": predicted,
            }
            if predicted is None:
                tally["abstain"] += 1
            else:
                for tolerance in TOLERANCES:
                    hits = score_predicted_cuts(predicted, position["gold_offsets"], tolerance)
                    record[f"hits_tol{tolerance}"] = hits
                    tally[f"hits_tol{tolerance}"] += hits

            out_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_handle.flush()
            print(f"[{scanned}] {position['date']} k={position['target_splits']} -> predicted={predicted}")

    with output_path.open("r", encoding="utf-8") as handle:
        total_records = sum(1 for _ in handle)

    write_sidecar(
        output_path,
        ProvenanceRecord(
            logical_name=OUTPUT_LOGICAL_NAME,
            phase="semi",
            parent_sources=["boundary_gold_sample", "boundary_gold_paragraph_axis"],
            description=(
                "Few-shot local-LLM (mlx-lm) split-point predictions on the 22 bundled gold "
                "positions, scored with s4_bundled_split_poc's tolerance harness."
            ),
            created_by_script=__file__,
            record_count=total_records,
            git_commit=git_commit_hash(output_path.parent),
        ),
    )

    attempted = scanned - tally["abstain"]
    print(f"\nThis run: attempted {attempted}/{scanned} (abstained/unparseable {tally['abstain']})")
    if total_gold_cuts:
        for tolerance in TOLERANCES:
            hits = tally[f"hits_tol{tolerance}"]
            print(f"  tol={tolerance}: {hits}/{total_gold_cuts} gold cuts recovered ({hits / total_gold_cuts:.1%})")


if __name__ == "__main__":
    main()

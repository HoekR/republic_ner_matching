#!/usr/bin/env python3
"""Step 3 of plans/SHORT_RESOLUTION_SIDE_PLAN.md — add experiment-only structured summarizer.

Generates inspectable semantic evidence for each HTR candidate using a local LLM.
Reuses local model availability and JSON extraction from alignment_llm_judge.py,
but keeps summarization separate from the pairwise judge contract.

Produces experiment-only JSONL with provenance and structured summaries.

Usage:
    uv run python scripts/build_short_resolution_summaries.py [--dry-run] [--sample-mode]
    uv run python scripts/build_short_resolution_summaries.py --recover-only
    uv run python scripts/build_short_resolution_summaries.py --retry-failed
    uv run python scripts/build_short_resolution_summaries.py --quality-check

Options:
    --dry-run          Mock LLM calls; emit schema-valid placeholders for testing
    --sample-mode      Process only the first 5 records (quick validation)
    --recover-only     Re-parse saved raw_response fields with the lenient extractor;
                       no LLM calls. Use after fixing extract_json to salvage failures.
    --retry-failed     Recover-from-raw first, then re-call the LLM only for records
                       that still fail the evidence/structure gate. Merge into the
                       existing dataset. Required before treating summaries as
                       authoritative for ranking, opening diagnostics, or a corpus
                       receipt/no-decision index.
    --quality-check    Report gate-pass rate and exit 0 only if the authoritative
                       threshold is met (no LLM calls).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_io import load, save_semi_structured
from mlx_llm.parsing import extract_json

try:
    from mlx_llm import generate
    from mlx_llm.model import DEFAULT_MODEL
    HAS_MLX = True
except ImportError:
    HAS_MLX = False
    DEFAULT_MODEL = "mlx-community/Qwen2.5-32B-Instruct-4bit"

OUTPUT_DATASET = "short_resolution_structured_summaries"
PROMPT_VERSION = "v1"
TEMPERATURE = 0.0  # Deterministic

# Training split: fetch few-shot examples from train data only
TRAIN_SPLIT = "train"

# Downstream consumers (ranking, opening signal, corpus receipt index) may treat
# summaries as authoritative only when gate_pass_rate >= this threshold.
AUTHORITATIVE_GATE_PASS_RATE = 0.90


def is_summary_failure(record: dict[str, Any]) -> bool:
    """True when the record lacks a usable structured summary."""
    return not bool(record.get("gate_passed"))


def summary_quality_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute parse/gate coverage and whether the authoritative threshold is met."""
    n = len(records)
    n_parse = sum(1 for r in records if r.get("parse_success"))
    n_gate = sum(1 for r in records if r.get("gate_passed"))
    failed_ids = [str(r.get("htr_id", "")) for r in records if is_summary_failure(r)]
    gate_rate = (n_gate / n) if n else 0.0
    return {
        "n_records": n,
        "n_parse_success": n_parse,
        "n_gate_passed": n_gate,
        "n_failed": len(failed_ids),
        "parse_rate": (n_parse / n) if n else 0.0,
        "gate_pass_rate": gate_rate,
        "failed_htr_ids": failed_ids,
        "authoritative_threshold": AUTHORITATIVE_GATE_PASS_RATE,
        "authoritative": n > 0 and gate_rate >= AUTHORITATIVE_GATE_PASS_RATE,
    }


def print_quality_report(report: dict[str, Any], *, heading: str = "SUMMARY QUALITY") -> None:
    print(f"\n=== {heading} ===")
    n = report["n_records"]
    print(f"  Records:          {n}")
    print(f"  Parse success:    {report['n_parse_success']}/{n} ({100 * report['parse_rate']:.1f}%)")
    print(f"  Gate pass:        {report['n_gate_passed']}/{n} ({100 * report['gate_pass_rate']:.1f}%)")
    print(f"  Failed (retry):   {report['n_failed']}")
    print(f"  Authoritative ≥{100 * report['authoritative_threshold']:.0f}%: "
          f"{'YES' if report['authoritative'] else 'NO'}")
    if report["failed_htr_ids"] and report["n_failed"] <= 20:
        print(f"  Failed htr_ids:   {', '.join(report['failed_htr_ids'])}")
    elif report["n_failed"] > 20:
        sample = ", ".join(report["failed_htr_ids"][:10])
        print(f"  Failed htr_ids:   {sample}, … (+{report['n_failed'] - 10} more)")


@dataclass
class StructuredSummary:
    """Schema for structured HTR candidate summaries."""
    kind: Literal[
        "receipt", "petition", "decision", "appointment",
        "continuation", "no_decision", "other", "uncertain"
    ]
    actor: str
    subject: str
    action_or_decision: str
    is_receipt_or_no_decision: bool
    is_session_opening: bool
    is_continuation: bool
    evidence_quote: str
    uncertainty: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryRecord:
    """Full record for one HTR candidate summary with provenance."""
    session_day: str
    enriched_id: str
    htr_id: str
    is_session_initial: bool
    position_stratum: str
    split: str  # train, dev, or test
    htr_text_len: int
    htr_text: str
    
    # LLM provenance
    model: str
    prompt_version: str
    temperature: float
    max_tokens: int
    input_char_limit: int
    
    # Raw and parsed responses
    raw_response: str | None
    parsed_summary: dict[str, Any] | None
    parse_success: bool
    parse_error: str | None
    
    # Post-parse gate
    has_evidence_quote: bool
    has_valid_structure: bool
    gate_passed: bool
    gate_notes: list[str]
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_few_shot_examples() -> list[dict[str, Any]]:
    """Load and return a few representative training-split candidates for few-shot context."""
    manifest_data = load("short_resolution_llm_sample_manifest")
    
    examples = []
    for record in manifest_data:
        if isinstance(record, dict) and record.get("record_type") == "candidate":
            if record.get("split") == TRAIN_SPLIT:
                examples.append(record)
                if len(examples) >= 3:
                    break
    
    return examples


def build_few_shot_prompt_context(examples: list[dict[str, Any]]) -> str:
    """Build few-shot prompt context from training examples.
    
    In a production system, you would fetch HTR texts and construct
    detailed examples. For now, return a template.
    """
    context = """You are analyzing 17th-century Dutch Republic States-General resolutions, transcribed via HTR (hand-text recognition).

Your task: summarize the semantic content of a given HTR text snippet into a structured form.

Key guidance:
1. Short resolutions near session opening may be receipts, petitions, appointments, or formulaic no-decisions.
2. Longer merged items may be continuations or bundled multiple resolutions — mark uncertain if unclear.
3. Extract actor (who), subject (what), and decision (action taken).
4. Mark is_session_opening=true only if this clearly opens a session (often formal receipt or opening phrase).
5. Mark is_continuation=true if text refers to prior day's discussion or "continued from above".
6. Provide an evidence_quote directly from the HTR text, even if corrupted.
7. If the HTR text is too corrupted, merged with following text, or semantically opaque, populate uncertainty with reasons.

Examples (from training split):
- Receipt of petition: kind="petition", actor="[submitter]", subject="[topic]", is_receipt_or_no_decision=true
- Appointment: kind="appointment", actor="[person appointed]", subject="[role]", action_or_decision="[terms]"
- Continuation: kind="continuation", is_continuation=true, uncertainty=["unclear extent of merge with following text"]
- No-decision: kind="no_decision", is_receipt_or_no_decision=true, action_or_decision="[deferred or no action taken]"

Respond with valid JSON only (no markdown, no preamble)."""
    return context


def build_summarization_prompt(htr_text: str, context: str, char_limit: int = 1500) -> str:
    """Build the full summarization prompt for one HTR candidate."""
    truncated_text = htr_text[:char_limit]
    remainder_msg = f"\n[... text truncated at {char_limit} chars ...]" if len(htr_text) > char_limit else ""
    
    prompt = f"""{context}

[HTR TEXT TO SUMMARIZE]
{truncated_text}{remainder_msg}

[RESPOND WITH JSON SCHEMA]
{{
  "kind": "receipt|petition|decision|appointment|continuation|no_decision|other|uncertain",
  "actor": "",
  "subject": "",
  "action_or_decision": "",
  "is_receipt_or_no_decision": false,
  "is_session_opening": false,
  "is_continuation": false,
  "evidence_quote": "",
  "uncertainty": []
}}
"""
    return prompt


def call_llm_summarize(
    htr_text: str,
    few_shot_context: str,
    model: str = DEFAULT_MODEL,
    temperature: float = TEMPERATURE,
    max_tokens: int = 500,
    dry_run: bool = False,
) -> tuple[str | None, dict[str, Any] | None, bool, str | None]:
    """Call LLM to summarize one HTR candidate.
    
    Returns: (raw_response, parsed_dict, parse_success, parse_error_msg)
    """
    if dry_run:
        # Return a mock valid response for testing
        raw = json.dumps({
            "kind": "uncertain",
            "actor": "[mock]",
            "subject": "[mock summary]",
            "action_or_decision": "[deferred to production]",
            "is_receipt_or_no_decision": False,
            "is_session_opening": False,
            "is_continuation": False,
            "evidence_quote": "[dry-run placeholder]",
            "uncertainty": ["dry_run_mode"]
        })
        parsed = json.loads(raw)
        return raw, parsed, True, None
    
    prompt = build_summarization_prompt(htr_text, few_shot_context)
    
    try:
        raw_response = generate(
            prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        return None, None, False, f"LLM call failed: {e}"
    
    if raw_response is None:
        return None, None, False, "LLM returned None"
    
    # Extract JSON
    try:
        parsed = extract_json(raw_response)
        if parsed is None:
            return raw_response, None, False, "extract_json returned None"
        return raw_response, parsed, True, None
    except Exception as e:
        return raw_response, None, False, f"JSON extraction failed: {e}"


def validate_summary(
    parsed: dict[str, Any] | None,
    raw: str | None,
) -> tuple[bool, bool, list[str]]:
    """Post-parse validation gate.
    
    Returns: (has_evidence_quote, has_valid_structure, gate_notes)
    """
    notes = []
    has_evidence = False
    has_valid_structure = False
    
    if parsed is None:
        notes.append("No parsed JSON")
        return False, False, notes
    
    # Check for required fields
    required_fields = [
        "kind", "actor", "subject", "action_or_decision",
        "is_receipt_or_no_decision", "is_session_opening", "is_continuation",
        "evidence_quote", "uncertainty"
    ]
    
    missing = [f for f in required_fields if f not in parsed]
    if missing:
        notes.append(f"Missing fields: {missing}")
    else:
        has_valid_structure = True
    
    # Check for evidence quote
    evidence_quote = str(parsed.get("evidence_quote", "")).strip()
    if evidence_quote and len(evidence_quote) > 3:
        has_evidence = True
    else:
        notes.append("No usable evidence quote (empty or < 3 chars)")
    
    return has_evidence, has_valid_structure, notes


def apply_recover_to_record(rec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Try to salvage one record from raw_response without an LLM call.

    Returns (updated_record, status) where status is one of:
    ``kept``, ``recovered``, ``still_fail``.
    """
    out = dict(rec)
    raw = out.get("raw_response")
    if out.get("gate_passed") and out.get("parsed_summary"):
        return out, "kept"

    # Prefer re-extracting whenever parse failed or gate failed but raw exists
    if not isinstance(raw, str) or not raw.strip():
        out["gate_notes"] = list(out.get("gate_notes") or []) + ["recover_no_raw"]
        return out, "still_fail"

    parsed = extract_json(raw)
    if parsed is None:
        out["parse_success"] = False
        out["parse_error"] = "extract_json returned None (after recover)"
        out["parsed_summary"] = None
        has_evidence, has_valid, gate_notes = validate_summary(None, raw)
        out["has_evidence_quote"] = has_evidence
        out["has_valid_structure"] = has_valid
        out["gate_passed"] = False
        out["gate_notes"] = gate_notes + ["recover_attempted"]
        return out, "still_fail"

    has_evidence, has_valid, gate_notes = validate_summary(parsed, raw)
    gate_passed = has_evidence and has_valid
    out["parsed_summary"] = parsed
    out["parse_success"] = True
    out["parse_error"] = None
    out["has_evidence_quote"] = has_evidence
    out["has_valid_structure"] = has_valid
    out["gate_passed"] = gate_passed
    out["gate_notes"] = gate_notes + ["recovered_from_raw_response"]
    return out, ("recovered" if gate_passed else "still_fail")


def recover_from_saved_raw(*, save: bool = True) -> list[dict[str, Any]]:
    """Re-parse existing raw_response fields; no LLM calls.

    Salvages cases where the model emitted valid JSON then continued past
    ``<|endoftext|>`` — the old greedy extractor rejected those.
    """
    print("=" * 70)
    print("STEP 3a: Recover structured summaries from saved raw_response")
    print("=" * 70)

    records = load(OUTPUT_DATASET)
    if not isinstance(records, list) or not records:
        print(f"✗ No records in {OUTPUT_DATASET}")
        sys.exit(1)

    before = summary_quality_report(records)
    recovered = 0
    still_fail = 0
    updated: list[dict[str, Any]] = []

    for rec in records:
        out, status = apply_recover_to_record(rec)
        if status == "recovered":
            recovered += 1
        elif status == "still_fail" and is_summary_failure(out):
            still_fail += 1
        updated.append(out)

    if save:
        save_semi_structured(
            updated,
            logical_name=OUTPUT_DATASET,
            script=__file__,
        )

    after = summary_quality_report(updated)
    print(f"\n✓ Recovered {recovered} previously failed records "
          f"({still_fail} still failing after recover)")
    print(f"  Parse success: {before['n_parse_success']}/{before['n_records']} → "
          f"{after['n_parse_success']}/{after['n_records']} "
          f"({100 * after['parse_rate']:.1f}%)")
    print(f"  Gate pass:     {before['n_gate_passed']}/{before['n_records']} → "
          f"{after['n_gate_passed']}/{after['n_records']} "
          f"({100 * after['gate_pass_rate']:.1f}%)")
    print(f"  Dataset: {OUTPUT_DATASET}")
    print_quality_report(after, heading="AFTER RECOVER")
    return updated


def retry_failed_summaries(*, dry_run: bool = False) -> None:
    """Recover-from-raw, then re-call LLM only for records that still fail the gate.

    Merges into the existing dataset. Required before treating summaries as
    authoritative for ranking / opening diagnostics / corpus receipt index.
    """
    print("=" * 70)
    print("STEP 3a: Retry failed structured summaries")
    print("=" * 70)

    if not dry_run and not HAS_MLX:
        print("✗ mlx_llm not available; use --dry-run or install mlx_llm")
        sys.exit(1)

    # Cheap salvage first (no LLM)
    records = recover_from_saved_raw(save=False)
    before = summary_quality_report(records)
    to_retry = [r for r in records if is_summary_failure(r)]
    print(f"\n[retry] {len(to_retry)} records still failing after recover-from-raw")

    if not to_retry:
        save_semi_structured(records, logical_name=OUTPUT_DATASET, script=__file__)
        print_quality_report(before, heading="AFTER RETRY (nothing to re-call)")
        if not before["authoritative"]:
            print("✗ Still below authoritative threshold (unexpected with 0 failures)")
            sys.exit(1)
        print("✓ Summaries meet authoritative threshold")
        return

    print("\n[retry] Loading few-shot context and HTR texts...")
    few_shot_examples = load_few_shot_examples()
    few_shot_context = build_few_shot_prompt_context(few_shot_examples)
    flat_df = load("resolutions_flat")
    flat_by_id: dict[str, str] = {}
    for _, row in flat_df.iterrows():
        fid = str(row.get("id", "")).strip()
        text = str(row.get("resolutions_text") or "")
        if fid:
            flat_by_id[fid] = text

    if dry_run:
        print("  [DRY-RUN MODE] Mocking LLM calls for failures only")

    by_htr = {str(r.get("htr_id", "")): dict(r) for r in records}
    retried_ok = 0
    retried_fail = 0

    for i, rec in enumerate(to_retry, 1):
        htr_id = str(rec.get("htr_id", ""))
        htr_text = flat_by_id.get(htr_id) or str(rec.get("htr_text") or "")
        if not htr_text:
            print(f"  [{i}/{len(to_retry)}] {htr_id}: ✗ HTR text not found")
            retried_fail += 1
            continue

        raw_resp, parsed, parse_ok, parse_err = call_llm_summarize(
            htr_text,
            few_shot_context,
            model=DEFAULT_MODEL,
            temperature=TEMPERATURE,
            dry_run=dry_run,
        )
        has_evidence, has_valid, gate_notes = validate_summary(parsed, raw_resp)
        gate_passed = has_evidence and has_valid

        out = dict(rec)
        out["model"] = DEFAULT_MODEL
        out["prompt_version"] = PROMPT_VERSION
        out["temperature"] = TEMPERATURE
        out["max_tokens"] = 500
        out["input_char_limit"] = 1500
        out["raw_response"] = raw_resp
        out["parsed_summary"] = parsed
        out["parse_success"] = parse_ok
        out["parse_error"] = parse_err
        out["has_evidence_quote"] = has_evidence
        out["has_valid_structure"] = has_valid
        out["gate_passed"] = gate_passed
        out["gate_notes"] = gate_notes + ["llm_retry"]
        by_htr[htr_id] = out

        if gate_passed:
            retried_ok += 1
            status = "✓"
        else:
            retried_fail += 1
            status = "✗"
        print(f"  [{i}/{len(to_retry)}] {htr_id}: {status} "
              f"[parse={parse_ok}, gate={gate_passed}]")

    # Preserve original order
    updated = [by_htr[str(r.get("htr_id", ""))] for r in records]
    save_semi_structured(updated, logical_name=OUTPUT_DATASET, script=__file__)

    after = summary_quality_report(updated)
    print(f"\n✓ LLM retry: {retried_ok} recovered, {retried_fail} still failing")
    print_quality_report(after, heading="AFTER RETRY")
    if after["authoritative"]:
        print("✓ Summaries meet authoritative threshold — safe for ranking / "
              "opening diagnostics / corpus receipt index")
    else:
        print("✗ Still below authoritative threshold. Inspect remaining failures "
              "before treating a night corpus run as authoritative.")
        sys.exit(1)


def quality_check_only() -> None:
    """Report summary quality and exit non-zero if below threshold."""
    records = load(OUTPUT_DATASET)
    if not isinstance(records, list) or not records:
        print(f"✗ No records in {OUTPUT_DATASET}")
        sys.exit(1)
    report = summary_quality_report(records)
    print_quality_report(report)
    if report["authoritative"]:
        print("✓ Authoritative threshold met")
        sys.exit(0)
    print("✗ Below authoritative threshold. Run:")
    print("    uv run python scripts/build_short_resolution_summaries.py --retry-failed")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mock LLM calls with placeholder responses"
    )
    parser.add_argument(
        "--sample-mode",
        action="store_true",
        help="Process only first 5 candidates (validation)"
    )
    parser.add_argument(
        "--recover-only",
        action="store_true",
        help="Re-parse saved raw_response with lenient extractor; no LLM",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Recover-from-raw then re-LLM only gate failures; merge into dataset",
    )
    parser.add_argument(
        "--quality-check",
        action="store_true",
        help="Report gate-pass rate; exit 0 only if authoritative threshold met",
    )
    args = parser.parse_args()

    if args.recover_only:
        recover_from_saved_raw()
        return
    if args.quality_check:
        quality_check_only()
        return
    if args.retry_failed:
        retry_failed_summaries(dry_run=args.dry_run)
        return

    
    print("=" * 70)
    print("STEP 3: Short-Resolution Structured Summarizer")
    print("=" * 70)
    
    # Check LLM availability
    if not args.dry_run and not HAS_MLX:
        print("✗ mlx_llm not available; use --dry-run or install mlx_llm")
        sys.exit(1)
    
    # Load manifest and prepare few-shot context
    print("\n[1/4] Loading frozen sample manifest...")
    manifest_data = load("short_resolution_llm_sample_manifest")
    
    meta_record = next((r for r in manifest_data if r.get("record_type") == "manifest_meta"), None)
    candidate_records = [r for r in manifest_data if r.get("record_type") == "candidate"]
    
    print(f"  Meta: {meta_record.get('n_candidates')} candidates, seed={meta_record.get('random_seed')}")
    print(f"  Loaded {len(candidate_records)} candidate records")
    
    print("\n[2/4] Loading training-split examples for few-shot context...")
    few_shot_examples = load_few_shot_examples()
    print(f"  Loaded {len(few_shot_examples)} training examples")
    
    few_shot_context = build_few_shot_prompt_context(few_shot_examples)
    
    # Load enriched and flat text for candidates
    print("\n[3/4] Loading enriched resolutions and flat HTR texts...")
    enriched_data = load("enriched_resolutions_1626_1630")
    flat_df = load("resolutions_flat")
    
    enriched_by_id = {}
    for item in enriched_data:
        vid = str(item.get("volgnr") or "").strip()
        if vid and vid.lower() != "none":
            enriched_by_id[vid] = item
        # Also try file::index key
        file_name = item.get("file", "unknown")
        res_idx = item.get("resolution_index", 0)
        alt_id = f"{file_name}::{res_idx}"
        enriched_by_id[alt_id] = item
    
    # Build flat text lookup from pandas DataFrame
    flat_by_id = {}
    for _, row in flat_df.iterrows():
        fid = str(row.get("id", "")).strip()
        text = str(row.get("resolutions_text") or "")
        if fid:
            flat_by_id[fid] = text
    
    print(f"  Enriched index: {len(enriched_by_id)} entries")
    print(f"  Flat text lookup: {len(flat_by_id)} entries")
    
    # Process candidates
    print("\n[4/4] Generating structured summaries...")
    if args.sample_mode:
        candidate_records = candidate_records[:5]
        print(f"  [SAMPLE MODE] Processing {len(candidate_records)} records only")
    
    if args.dry_run:
        print("  [DRY-RUN MODE] Mocking LLM calls")
    
    results = []
    successes = 0
    parse_failures = 0
    gate_passes = 0
    gate_failures = 0
    
    for i, cand in enumerate(candidate_records, 1):
        htr_id = cand.get("htr_id", "")
        htr_text = flat_by_id.get(htr_id, "")
        
        if not htr_text:
            print(f"  [{i}/{len(candidate_records)}] {htr_id}: ✗ HTR text not found")
            continue
        
        # Call LLM
        raw_resp, parsed, parse_ok, parse_err = call_llm_summarize(
            htr_text,
            few_shot_context,
            model=DEFAULT_MODEL,
            temperature=TEMPERATURE,
            dry_run=args.dry_run,
        )
        
        # Validate
        has_evidence, has_valid, gate_notes = validate_summary(parsed, raw_resp)
        gate_passed = has_evidence and has_valid
        
        if parse_ok:
            successes += 1
        else:
            parse_failures += 1
        
        if gate_passed:
            gate_passes += 1
        else:
            gate_failures += 1
        
        # Build summary record
        record = SummaryRecord(
            session_day=cand.get("session_day", ""),
            enriched_id=cand.get("enriched_id", ""),
            htr_id=htr_id,
            is_session_initial=cand.get("is_session_initial", False),
            position_stratum=cand.get("position_stratum", ""),
            split=cand.get("split", ""),
            htr_text_len=len(htr_text),
            htr_text=htr_text[:1500],  # Store truncated text for analysis
            
            model=DEFAULT_MODEL,
            prompt_version=PROMPT_VERSION,
            temperature=TEMPERATURE,
            max_tokens=500,
            input_char_limit=1500,
            
            raw_response=raw_resp,
            parsed_summary=parsed,
            parse_success=parse_ok,
            parse_error=parse_err,
            
            has_evidence_quote=has_evidence,
            has_valid_structure=has_valid,
            gate_passed=gate_passed,
            gate_notes=gate_notes,
        )
        results.append(record)
        
        status = "✓" if gate_passed else ("⚠" if parse_ok else "✗")
        print(f"  [{i}/{len(candidate_records)}] {htr_id}: {status} "
              f"[parse={parse_ok}, gate={gate_passed}]")
    
    # Save results
    print("\n" + "=" * 70)
    print("SAVING RESULTS")
    print("=" * 70)
    
    output_records = []
    for rec in results:
        output_records.append(rec.to_dict())
    
    save_semi_structured(
        output_records,
        logical_name=OUTPUT_DATASET,
        script=__file__,
    )
    
    # Summary stats
    print(f"\n✓ Processed {len(results)} candidates")
    print(f"  Parse success: {successes}/{len(results)} ({100*successes/len(results):.1f}%)")
    print(f"  Gate pass (evidence + valid structure): {gate_passes}/{len(results)} ({100*gate_passes/len(results):.1f}%)")
    print(f"  Parse failures retained for analysis: {parse_failures}")
    print(f"  Gate failures retained for analysis: {gate_failures}")

    report = summary_quality_report(output_records)
    print_quality_report(report, heading="SUMMARY QUALITY (Step 3a gate)")
    if not report["authoritative"]:
        print("\n⚠ Summaries are NOT yet authoritative for ranking / opening / "
              "corpus receipt index.")
        print("  Next process step:")
        print("    uv run python scripts/build_short_resolution_summaries.py --retry-failed")
        print("  Then confirm:")
        print("    uv run python scripts/build_short_resolution_summaries.py --quality-check")
    
    print(f"\n✓ Dataset registered and saved: {OUTPUT_DATASET}")


if __name__ == "__main__":
    main()

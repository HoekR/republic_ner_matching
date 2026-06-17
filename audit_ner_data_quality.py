#!/usr/bin/env python3
"""
Audit LOC training data for quality issues that could explain low F1 scores.

Checks:
1. Overlapping spans within each resolution
2. Boundary inconsistency (same canonical entity, different character ranges)
3. Spans that don't actually match the paragraph text
4. Partial vs full entity coverage

Usage:
    uv run python audit_ner_data_quality.py
"""

import pandas as pd
from pathlib import Path
from collections import defaultdict
import sys

DATA_DIR = Path("data")
TRAINING_PAIRS_FILE = DATA_DIR / "training_pairs_loc_1626_1630_dedup.parquet"

def check_overlapping_spans(df):
    """Find overlapping PLACE annotations within each resolution."""
    print("\n" + "=" * 80)
    print("CHECK 1: OVERLAPPING SPANS (conflicting labels)")
    print("=" * 80)
    
    overlap_count = 0
    overlap_details = []
    
    for res_id, group in df.groupby('resolution_id'):
        spans = []
        for idx, row in group.iterrows():
            offset = row['offset']
            end = offset + len(str(row['htr_span']))
            spans.append({
                'idx': idx,
                'offset': offset,
                'end': end,
                'text': row['htr_span'],
                'canonical': row['canonical_entity']
            })
        
        # Check for overlaps
        for i, span1 in enumerate(spans):
            for span2 in spans[i+1:]:
                # Overlap if: start1 < end2 AND end1 > start2
                if span1['offset'] < span2['end'] and span1['end'] > span2['offset']:
                    overlap_count += 1
                    overlap_details.append({
                        'res_id': res_id,
                        'span1': span1['text'],
                        'span2': span2['text'],
                        'range1': f"{span1['offset']}-{span1['end']}",
                        'range2': f"{span2['offset']}-{span2['end']}"
                    })
    
    print(f"\nOverlapping spans found: {overlap_count}")
    if overlap_details:
        print("\nFirst 10 examples:")
        for i, detail in enumerate(overlap_details[:10]):
            print(f"  {i+1}. Res {detail['res_id']}: '{detail['span1']}' ({detail['range1']}) vs '{detail['span2']}' ({detail['range2']})")
    
    return overlap_count

def check_boundary_inconsistency(df):
    """Find same canonical entity with different character ranges."""
    print("\n" + "=" * 80)
    print("CHECK 2: BOUNDARY INCONSISTENCY (same entity, different spans)")
    print("=" * 80)
    
    inconsistencies = defaultdict(list)
    
    for canonical, group in df.groupby('canonical_entity'):
        # Collect all (htr_span, offset, end) tuples for this canonical
        spans_for_canonical = set()
        for _, row in group.iterrows():
            offset = row['offset']
            end = offset + len(str(row['htr_span']))
            htr_span = row['htr_span']
            spans_for_canonical.add((htr_span, offset, end))
        
        # If >1 unique span for same canonical, it's inconsistent
        if len(spans_for_canonical) > 1:
            inconsistencies[canonical] = list(spans_for_canonical)
    
    print(f"\nCanonical entities with multiple boundary variants: {len(inconsistencies)}")
    if inconsistencies:
        print("\nFirst 10 examples:")
        for i, (canonical, variants) in enumerate(list(inconsistencies.items())[:10]):
            print(f"  {i+1}. '{canonical}' ({len(variants)} variants):")
            for htr_span, offset, end in variants[:3]:
                print(f"     - '{htr_span}' at {offset}-{end}")
            if len(variants) > 3:
                print(f"     - ... and {len(variants) - 3} more")
    
    return len(inconsistencies)

def check_text_match(df):
    """Verify that spans actually exist in the paragraph text at the claimed offsets."""
    print("\n" + "=" * 80)
    print("CHECK 3: TEXT MATCH (span text vs paragraph at offset)")
    print("=" * 80)
    
    mismatch_count = 0
    mismatch_details = []
    
    for _, row in df.iterrows():
        para_text = str(row['paragraph_texts'])
        offset = row['offset']
        htr_span = str(row['htr_span'])
        end = offset + len(htr_span)
        
        # Extract text at the claimed offset
        extracted = para_text[offset:end]
        
        if extracted != htr_span:
            mismatch_count += 1
            mismatch_details.append({
                'canonical': row['canonical_entity'],
                'claimed': htr_span,
                'actual': extracted,
                'offset': offset,
                'end': end,
                'res_id': row['resolution_id']
            })
    
    print(f"\nMismatches found: {mismatch_count} / {len(df)} ({100*mismatch_count/len(df):.2f}%)")
    if mismatch_details:
        print("\nFirst 10 examples:")
        for i, detail in enumerate(mismatch_details[:10]):
            print(f"  {i+1}. Canonical: '{detail['canonical']}'")
            print(f"     Claimed: '{detail['claimed']}'")
            print(f"     Actual:  '{detail['actual']}' at offset {detail['offset']}-{detail['end']}")
    
    return mismatch_count

def check_partial_coverage(df):
    """Find cases where only part of a multi-word entity is annotated."""
    print("\n" + "=" * 80)
    print("CHECK 4: PARTIAL ENTITY COVERAGE (incomplete multi-word spans)")
    print("=" * 80)
    
    partial_count = 0
    partial_details = []
    
    for res_id, group in df.groupby('resolution_id'):
        para_text = str(group.iloc[0]['paragraph_texts'])
        
        for canonical, canon_group in group.groupby('canonical_entity'):
            # Get all spans for this canonical in this resolution
            spans = []
            for _, row in canon_group.iterrows():
                offset = row['offset']
                end = offset + len(str(row['htr_span']))
                spans.append((offset, end, row['htr_span']))
            
            # If multiple spans, could be partial coverage
            if len(spans) > 1:
                # Check if they form a contiguous region with gaps
                spans_sorted = sorted(spans, key=lambda x: x[0])
                for i in range(len(spans_sorted) - 1):
                    gap = spans_sorted[i+1][0] - spans_sorted[i][1]
                    if 0 <= gap <= 5:  # Small gap (punctuation, whitespace)
                        partial_count += 1
                        partial_details.append({
                            'canonical': canonical,
                            'res_id': res_id,
                            'spans': spans_sorted,
                            'gap': gap
                        })
    
    print(f"\nPotential partial coverages: {partial_count}")
    if partial_details:
        print("\nFirst 5 examples:")
        for i, detail in enumerate(partial_details[:5]):
            print(f"  {i+1}. '{detail['canonical']}' in res {detail['res_id']}:")
            for offset, end, text in detail['spans']:
                print(f"     - '{text}' at {offset}-{end}")
    
    return partial_count

def main():
    print("=" * 80)
    print("NER DATA QUALITY AUDIT")
    print(f"Started: {pd.Timestamp.now()}")
    print("=" * 80)
    
    # Load data
    print(f"\nLoading {TRAINING_PAIRS_FILE}...")
    df = pd.read_parquet(TRAINING_PAIRS_FILE)
    print(f"Loaded {len(df)} training records")
    print(f"Unique resolutions: {df['resolution_id'].nunique()}")
    print(f"Unique canonical entities: {df['canonical_entity'].nunique()}")
    
    # Run checks
    overlaps = check_overlapping_spans(df)
    inconsistencies = check_boundary_inconsistency(df)
    mismatches = check_text_match(df)
    partials = check_partial_coverage(df)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Overlapping spans: {overlaps}")
    print(f"Boundary inconsistencies: {inconsistencies}")
    print(f"Text mismatches: {mismatches}")
    print(f"Partial coverages: {partials}")
    
    total_issues = overlaps + inconsistencies + mismatches + partials
    print(f"\nTotal issues: {total_issues}")
    
    if mismatches > 0:
        print(f"\n⚠️  WARNING: {mismatches} spans don't match paragraph text!")
        print("   This will cause label errors during training.")
    
    if inconsistencies > 100:
        print(f"\n⚠️  WARNING: {inconsistencies} canonical entities have inconsistent boundaries!")
        print("   The model learns conflicting patterns for the same entity.")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Build training pairs from 1626-1630 resolutions using authoritative person annotations.

STRATEGY: Annotation-based person/delegate matching
====================================================

Use verified REPUBLIC project person annotations as the source of truth:

1. LOAD canonical person names from PER-entities.json
   - Delegates with standardized IDs (P00XXXXX format)
   - Each entity has biographical data

2. LOAD all PER-annotations from PER-annotations.json
   - 2M verified person annotations
   - Each references a canonical entity_id
   - Includes exact character offsets

3. FILTER to 1626-1630 date range
   - Use resolution dates from resolutions_flat.parquet

4. CREATE training pairs directly from annotations
   - Authority-based (no fuzzy matching)
   - Exact offsets preserved for training
   - Expected: Partial alignment (more OCR errors in names than places)

Usage:
    uv run python build_training_pairs_per.py
"""

import json
from pathlib import Path
import pandas as pd
from tqdm import tqdm
from datetime import datetime

# Configuration
DATADIR = Path("data")
PER_ENTITIES_FILE = "PER-entities.json"
PER_ANNOTATIONS_FILE = "PER-annotations.json"
RESOLUTIONS_FILE = "resolutions_flat.parquet"

OUTPUT_PARQUET = DATADIR / "training_pairs_1626_1630_per_from_annotations.parquet"
OUTPUT_JSONL = DATADIR / "training_pairs_1626_1630_per_from_annotations.jsonl"


def load_per_entities():
    """Load canonical person names from PER-entities.json."""
    print("Loading PER-entities...")
    with open(DATADIR / PER_ENTITIES_FILE) as f:
        entities = json.load(f)
    
    # Build id -> name mapping
    id_to_name = {}
    for ent in entities:
        ent_id = ent.get('id')
        # Try different name fields
        name = ent.get('name') or ent.get('full_name') or ent.get('display_name')
        if ent_id and name:
            id_to_name[ent_id] = name
    
    print(f"  Loaded {len(id_to_name)} canonical persons")
    return id_to_name


def load_per_annotations():
    """Load PER-annotations.json."""
    print("Loading PER-annotations...")
    with open(DATADIR / PER_ANNOTATIONS_FILE) as f:
        annotations = json.load(f)
    
    print(f"  Loaded {len(annotations)} annotations")
    return annotations


def load_resolutions_with_dates():
    """Load resolution dates from resolutions_flat.parquet."""
    print("Loading resolution dates...")
    res_df = pd.read_parquet(DATADIR / RESOLUTIONS_FILE)
    
    # Create mapping: resolution_id -> date
    res_dates = {}
    for res_id, date_val in zip(res_df['id'], res_df['date']):
        res_dates[res_id] = date_val
    
    print(f"  Loaded {len(res_dates)} resolutions")
    return res_dates


def filter_annotations_by_date(annotations, res_dates, year_min=1626, year_max=1630):
    """
    Filter annotations to date range.
    
    Returns filtered annotations.
    """
    print(f"Filtering annotations to {year_min}-{year_max}...")
    
    filtered = []
    filtered_out = 0
    
    for ann in annotations:
        ref = ann.get('reference', {})
        resolution_id = ref.get('resolution_id')
        
        if not resolution_id or resolution_id not in res_dates:
            filtered_out += 1
            continue
        
        date_val = res_dates[resolution_id]
        if pd.isna(date_val):
            filtered_out += 1
            continue
        
        # Extract year
        try:
            year = pd.Timestamp(date_val).year
            if year_min <= year <= year_max:
                filtered.append(ann)
            else:
                filtered_out += 1
        except:
            filtered_out += 1
    
    print(f"  Kept {len(filtered)} annotations in date range")
    print(f"  Filtered out {filtered_out} outside date range")
    
    return filtered


def build_training_pairs_from_annotations(annotations, id_to_name, res_dates):
    """
    Convert person annotations to training pairs.
    
    Each annotation becomes one training pair with:
      - entity_id, canonical_name (from PER-entities)
      - htr_span, offset, end (from annotation)
      - resolution_id, date (from annotation + resolution lookup)
    """
    print("Building training pairs from annotations...")
    
    pairs = []
    skipped = 0
    skipped_reasons = {'no_entity': 0, 'no_span': 0, 'no_resolution': 0, 'parse_error': 0}
    
    for ann in tqdm(annotations, desc="Annotations", unit="ann"):
        ref = ann.get('reference', {})
        
        # Extract annotation fields
        resolution_id = ref.get('resolution_id')
        tag_text = ref.get('tag_text', '').lower()  # Case-agnostic
        offset_str = ref.get('offset')
        end_str = ref.get('end')
        
        # Extract entity_id (remove URN prefix if present)
        entity_ref = ann.get('entity', '')
        entity_id = entity_ref.replace('urn:republic:entity:', '')
        
        # Skip if missing required fields
        if not entity_id:
            skipped_reasons['no_entity'] += 1
            skipped += 1
            continue
        
        if not tag_text:
            skipped_reasons['no_span'] += 1
            skipped += 1
            continue
        
        if not resolution_id:
            skipped_reasons['no_resolution'] += 1
            skipped += 1
            continue
        
        # Skip if entity not in canonical list
        canonical_name = id_to_name.get(entity_id)
        if not canonical_name:
            skipped_reasons['no_entity'] += 1
            skipped += 1
            continue
        
        # Parse offsets
        try:
            offset = int(offset_str) if offset_str else None
            end = int(end_str) if end_str else None
        except (ValueError, TypeError):
            skipped_reasons['parse_error'] += 1
            skipped += 1
            continue
        
        # Get resolution date
        date_val = res_dates.get(resolution_id)
        
        # Build pair
        pair = {
            'entity_id': entity_id,
            'canonical_name': canonical_name,
            'htr_span': tag_text,
            'offset': offset,
            'end': end,
            'resolution_id': resolution_id,
            'date': date_val,
            'source': 'PER-annotations',
        }
        
        pairs.append(pair)
    
    print(f"  Created {len(pairs)} training pairs")
    print(f"  Skipped {skipped} annotations:")
    for reason, count in skipped_reasons.items():
        if count > 0:
            print(f"    {reason}: {count}")
    
    return pairs


def deduplicate_pairs(training_pairs):
    """
    Deduplicate on (entity_id, htr_span, resolution_id).
    Keep first occurrence of each unique combination.
    """
    print("Deduplicating...")
    
    seen = set()
    deduped = []
    
    for pair in training_pairs:
        key = (pair['entity_id'], pair['htr_span'], pair['resolution_id'])
        if key not in seen:
            seen.add(key)
            deduped.append(pair)
    
    print(f"  Before dedup: {len(training_pairs)} pairs")
    print(f"  After dedup: {len(deduped)} pairs")
    print(f"  Removed: {len(training_pairs) - len(deduped)} duplicates")
    
    return deduped


def save_training_pairs(training_pairs):
    """Save training pairs to parquet and JSON-L."""
    print("\n=== Saving training pairs ===")
    
    training_df = pd.DataFrame(training_pairs)
    
    # Save parquet
    training_df.to_parquet(OUTPUT_PARQUET)
    print(f"  Saved {len(training_df)} pairs to {OUTPUT_PARQUET}")
    
    # Save JSON-L
    print("  Writing JSON-L...")
    with open(OUTPUT_JSONL, 'w') as f:
        for _, row in tqdm(training_df.iterrows(), total=len(training_df), desc="JSON-L export", unit="row", leave=False):
            f.write(json.dumps(row.to_dict(), default=str) + '\n')
    print(f"  Saved JSON-L to {OUTPUT_JSONL}")
    
    # Quality analysis
    print("\n=== Quality Analysis ===")
    print(f"  Total pairs: {len(training_df)}")
    print(f"  Unique entities: {training_df['entity_id'].nunique()}")
    print(f"  Unique HTR spans: {training_df['htr_span'].nunique()}")
    print(f"  Unique resolutions: {training_df['resolution_id'].nunique()}")
    
    print(f"\n  Offset coverage:")
    print(f"    With valid offsets: {training_df['offset'].notna().sum()}")
    print(f"    Missing offsets: {training_df['offset'].isna().sum()}")
    
    print(f"\n  Date coverage:")
    print(f"    With date: {training_df['date'].notna().sum()}")
    print(f"    Missing date: {training_df['date'].isna().sum()}")
    
    print(f"\n  Span length statistics:")
    training_df['span_length'] = training_df['htr_span'].str.len()
    print(f"    Min: {training_df['span_length'].min()}")
    print(f"    Max: {training_df['span_length'].max()}")
    print(f"    Mean: {training_df['span_length'].mean():.1f}")
    print(f"    Median: {training_df['span_length'].median():.1f}")


def main():
    """
    Main pipeline: Build training pairs from person annotations.
    
    Steps:
    1. Load canonical persons from PER-entities.json
    2. Load annotations from PER-annotations.json
    3. Load resolution dates
    4. Filter annotations to 1626-1630
    5. Convert annotations to training pairs
    6. Deduplicate
    7. Save to parquet + JSON-L
    """
    start_time = datetime.now()
    print("=" * 70)
    print("Annotation-Based Person Training Pair Extraction (1626-1630)")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    # Load data
    print("[1/6] Loading data...")
    id_to_name = load_per_entities()
    annotations = load_per_annotations()
    res_dates = load_resolutions_with_dates()
    print()
    
    # Filter by date
    print("[2/6] Filtering by date range...")
    annotations_filtered = filter_annotations_by_date(annotations, res_dates)
    print()
    
    # Build training pairs
    print("[3/6] Building training pairs...")
    training_pairs = build_training_pairs_from_annotations(annotations_filtered, id_to_name, res_dates)
    print()
    
    # Deduplicate
    print("[4/6] Deduplicating...")
    training_pairs = deduplicate_pairs(training_pairs)
    print()
    
    # Save
    print("[5/6] Saving results...")
    save_training_pairs(training_pairs)
    
    end_time = datetime.now()
    duration = end_time - start_time
    print("\n" + "=" * 70)
    print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {duration.total_seconds():.1f} seconds")
    print("=" * 70)


if __name__ == '__main__':
    main()

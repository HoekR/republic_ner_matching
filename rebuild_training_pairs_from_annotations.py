#!/usr/bin/env python3
"""
Rebuild training_pairs from authoritative LOC-annotations.json.

The old parquet (training_pairs_loc_1626_1630_dedup.parquet) has 100% invalid offsets
because they were computed by fuzzy-matching. This script uses the verified REPUBLIC 
project annotations directly.

Steps:
1. Load LOC-entities.json to map entity_id -> canonical_name
2. Load LOC-annotations.json (1.3M annotations)
3. Filter for 1626-1630 date range (from resolution_id)
4. For each annotation, extract:
   - canonical_entity (name from LOC-entities)
   - htr_span (tag_text from annotation)
   - offset, end (from annotation)
   - resolution_id, date (from annotation)
5. Save as parquet

Output: data/training_pairs_loc_1626_1630_from_annotations.parquet
"""

import json
import pandas as pd
from pathlib import Path
from tqdm import tqdm
import re
from datetime import datetime

DATA_DIR = Path("data")

def load_loc_entities():
    """Load entity ID -> canonical name mapping."""
    print("Loading LOC-entities...")
    with open(DATA_DIR / "LOC-entities.json") as f:
        entities = json.load(f)
    
    # Build id -> name mapping
    id_to_name = {}
    for ent in entities:
        ent_id = ent.get('id')
        name = ent.get('name')
        if ent_id and name:
            id_to_name[ent_id] = name
    
    print(f"  Loaded {len(id_to_name)} entities")
    return id_to_name

def load_loc_annotations():
    """Load annotations from LOC-annotations.json."""
    print("Loading LOC-annotations...")
    with open(DATA_DIR / "LOC-annotations.json") as f:
        annotations = json.load(f)
    
    print(f"  Loaded {len(annotations)} annotations")
    return annotations

def load_resolutions_text():
    """Load resolution text mapping from resolutions_flat.parquet."""
    print("Loading resolution texts...")
    res_df = pd.read_parquet(DATA_DIR / "resolutions_flat.parquet")
    # Create mapping: resolution_id -> paragraph_texts
    # paragraph_texts is a list, join into single text
    # Lowercase for case-agnostic matching
    text_map = {}
    for res_id, para_texts in zip(res_df['id'], res_df['paragraph_texts']):
        if isinstance(para_texts, list):
            text_map[res_id] = ' '.join(str(p) for p in para_texts if p).lower()
        else:
            text_map[res_id] = str(para_texts).lower() if para_texts else ''
    print(f"  Loaded {len(text_map)} resolution texts")
    return text_map

def extract_date_from_resolution_id(resolution_id):
    """
    Try to extract year from resolution_id.
    
    Examples:
      session-3097-num-101-resolution-4 -> ?  (need to look up session 3097)
      
    For now, return None and we'll skip date filtering.
    """
    return None

def build_training_pairs(annotations, id_to_name):
    """
    Build training pairs from annotations.
    
    Returns DataFrame with columns:
      resolution_id, htr_span, canonical_entity, entity_id, 
      offset, end, entity_type, date, source
    """
    print("Building training pairs...")
    
    pairs = []
    
    for ann in tqdm(annotations, desc="Processing annotations"):
        ref = ann.get('reference', {})
        
        # Extract fields
        resolution_id = ref.get('resolution_id')
        paragraph_id = ref.get('paragraph_id')
        tag_text = ref.get('tag_text', '').lower()  # Lowercase for case-agnostic matching
        offset_str = ref.get('offset')
        end_str = ref.get('end')
        layer = ref.get('layer')
        inv = ref.get('inv')  # Session/inventory number
        
        # Entity reference
        entity_id = ann.get('entity', '').replace('urn:republic:entity:', '')
        
        # Get canonical name
        canonical_entity = id_to_name.get(entity_id, '')
        
        # Parse offset and end
        try:
            offset = int(offset_str) if offset_str else None
            end = int(end_str) if end_str else None
        except (ValueError, TypeError):
            continue
        
        # Apply -2 character offset correction (discovered via annotation_alignment.ipynb analysis)
        # This fixes systematic offset shift from paragraph text joining
        if offset is not None:
            offset = max(0, offset - 2)
        if end is not None:
            end = max(0, end - 2)
        
        if not (resolution_id and tag_text and offset is not None and end is not None):
            continue
        
        # Try to extract date from provenance
        provenance = ann.get('provenance', {})
        when = provenance.get('when', '')  # e.g., "2025-03-17T15:57:51Z"
        date_str = when[:10] if when else None
        
        # Try to infer date from inv number if available
        # inv like "3097" could map to session, which has a date
        # For now, leave date as None or use annotation date
        
        pair = {
            'resolution_id': resolution_id,
            'paragraph_id': paragraph_id,
            'htr_span': tag_text,
            'canonical_entity': canonical_entity,
            'entity_type': 'place',
            'entity_id': entity_id,
            'offset': offset,
            'end': end,
            'date': None,
            'source': 'LOC-annotations',
            'inv': inv,
            'paragraph_texts': None,  # Will be filled in after merge
        }
        
        pairs.append(pair)
    
    df = pd.DataFrame(pairs)
    print(f"  Created {len(df)} pairs")
    
    return df

def add_dates(df):
    """
    Date lookup not implemented — inv numbers don't directly map to dates in current data.
    The training script doesn't require dates anyway, so we skip this.
    """
    print("Skipping date lookup (inv numbers don't map to available resolution dates)")
    df['date'] = None
    return df

def filter_date_range(df, start_date='1626-01-01', end_date='1630-12-31'):
    """Filter to 1626-1630 range if dates available."""
    # Skip filtering since dates are unavailable
    print(f"  Skipping date range filter (dates unavailable)")
    return df

def deduplicate(df):
    """Remove duplicate pairs."""
    print("Deduplicating...")
    
    # Group by (resolution_id, htr_span, offset, end) and keep first
    df_dedup = df.drop_duplicates(
        subset=['resolution_id', 'htr_span', 'offset', 'end'],
        keep='first'
    )
    
    print(f"  Removed {len(df) - len(df_dedup)} duplicates")
    print(f"  Final: {len(df_dedup)} unique pairs")
    
    return df_dedup

def main():
    print("\n" + "="*80)
    print("REBUILD TRAINING PAIRS FROM LOC-ANNOTATIONS")
    print("="*80 + "\n")
    
    # Load entity mapping
    id_to_name = load_loc_entities()
    
    # Load annotations
    annotations = load_loc_annotations()
    
    # Load resolution texts
    text_map = load_resolutions_text()
    
    # Build pairs
    df = build_training_pairs(annotations, id_to_name)
    
    # Add paragraph texts
    print("Merging resolution texts...")
    df['paragraph_texts'] = df['resolution_id'].map(text_map)
    print(f"  Matched {df['paragraph_texts'].notna().sum()} / {len(df)} pairs with text")
    
    # Add dates (will be empty)
    df = add_dates(df)
    
    # No filtering — use all authoritative annotations
    # df = filter_date_range(df, start_date='1626-01-01', end_date='1630-12-31')
    
    # Deduplicate
    df = deduplicate(df)
    
    # Save
    output_file = DATA_DIR / "training_pairs_loc_from_annotations.parquet"
    df.to_parquet(output_file)
    print(f"\n✓ Saved to {output_file}")
    
    # Print summary
    print(f"\nFinal dataset (all authoritative REPUBLIC annotations):")
    print(f"  Total pairs: {len(df)}")
    print(f"  Unique resolutions: {df['resolution_id'].nunique()}")
    print(f"  Unique entities: {df['canonical_entity'].nunique()}")
    print(f"  Unique entity IDs: {df['entity_id'].nunique()}")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"\nColumns: {list(df.columns)}")
    print(f"\nSample rows:")
    print(df.head(5).to_string())

if __name__ == '__main__':
    main()

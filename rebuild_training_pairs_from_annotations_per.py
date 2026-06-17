#!/usr/bin/env python3
"""
Rebuild PER (person name) training pairs from authoritative REPUBLIC annotations.
Uses: PER-annotations.json + PER-entities.json (no fuzzy-matching corruption)
"""
import json
import pandas as pd
from pathlib import Path
from collections import Counter
from tqdm import tqdm

DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "training_pairs_per_from_annotations.parquet"

print("=" * 80)
print("REBUILD TRAINING PAIRS FROM PER-ANNOTATIONS")
print("=" * 80)

# Load entities
print("\nLoading PER-entities...")
with open(DATA_DIR / "PER-entities (1).json") as f:
    entities = json.load(f)
id_to_name = {e['id']: e['name'] for e in entities}
print(f"  Loaded {len(entities)} entities")

# Load annotations
print("Loading PER-annotations...")
with open(DATA_DIR / "PER-annotations.json") as f:
    annotations = json.load(f)
print(f"  Loaded {len(annotations)} annotations")

# Load resolution texts
print("Loading resolution texts...")
res_df = pd.read_parquet(DATA_DIR / "resolutions_flat.parquet")
text_map = {}
for res_id, para_texts in zip(res_df['id'], res_df['paragraph_texts']):
    if isinstance(para_texts, list):
        text_map[res_id] = ' '.join(str(p) for p in para_texts if p).lower()
    else:
        text_map[res_id] = str(para_texts).lower() if para_texts else ''
print(f"  Loaded {len(text_map)} resolution texts")

# Build training pairs
print("Building training pairs...")
pairs = []
for ann in tqdm(annotations, desc="Processing annotations"):
    ref = ann.get('reference', {})
    entity_id = ann.get('entity')
    
    # Extract fields
    resolution_id = ref.get('resolution_id')
    paragraph_id = ref.get('paragraph_id')
    htr_span = ref.get('tag_text', '').lower()  # Lowercase for case-agnostic matching
    offset = ref.get('offset')
    end = ref.get('end')
    inv = ref.get('inv')
    
    # Apply -2 character offset correction (discovered via annotation_alignment.ipynb analysis)
    # This fixes systematic offset shift from paragraph text joining
    if offset is not None:
        offset = max(0, offset - 2)
    if end is not None:
        end = max(0, end - 2)
    
    # Map entity ID to canonical name
    canonical_entity = id_to_name.get(entity_id, htr_span)
    
    pairs.append({
        'resolution_id': resolution_id,
        'paragraph_id': paragraph_id,
        'htr_span': htr_span,
        'canonical_entity': canonical_entity,
        'entity_type': 'person',
        'entity_id': entity_id,
        'offset': offset,
        'end': end,
        'date': None,
        'source': 'PER-annotations',
        'inv': inv,
        'paragraph_texts': text_map.get(resolution_id, ''),  # Include resolution text
    })

print(f"  Created {len(pairs)} pairs")

# Convert to DataFrame
df = pd.DataFrame(pairs)

# Count text coverage
text_count = (df['paragraph_texts'] != '').sum()
print(f"  Resolution texts matched: {text_count} / {len(df)}")

# Deduplicate
print("Deduplicating...")
dedup_key = ['resolution_id', 'htr_span', 'offset', 'end']
before = len(df)
df = df.drop_duplicates(subset=dedup_key)
after = len(df)
print(f"  Removed {before - after} duplicates")
print(f"  Final: {after} unique pairs")

# Save
print(f"\n✓ Saved to {OUTPUT_FILE}")
df.to_parquet(OUTPUT_FILE)

# Statistics
print("\nFinal dataset (all authoritative REPUBLIC annotations):")
print(f"  Total pairs: {len(df)}")
print(f"  Unique resolutions: {df['resolution_id'].nunique()}")
print(f"  Unique entities: {df['entity_id'].nunique()}")
print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
print(f"\nColumns: {list(df.columns)}")
print(f"\nSample rows:")
print(df.head())

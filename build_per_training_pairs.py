#!/usr/bin/env python3
"""
Generate training pairs from PER-annotations.json for delegate name recognition.

Maps PER-entity IDs to canonical delegate names and creates training records
with character offsets for exact sequence labeling.

Usage:
    uv run python build_per_training_pairs.py
"""

import json
import pandas as pd
from pathlib import Path
from collections import defaultdict
from tqdm import tqdm

DATA_DIR = Path("data")

def load_per_annotations():
    """Load person annotations (2M records with offsets)."""
    print("Loading PER annotations...")
    with open(DATA_DIR / "PER-annotations.json") as f:
        data = json.load(f)
    
    # Flatten nested structure
    annotations = []
    for record in data:
        ref = record.get('reference', {})
        if not ref.get('resolution_id'):
            continue
        
        annotations.append({
            'entity': record.get('entity'),
            'tag_text': ref.get('tag_text'),
            'resolution_id': ref.get('resolution_id'),
            'offset': ref.get('offset'),
            'end': ref.get('end'),
        })
    
    print(f"  Loaded {len(annotations)} annotations")
    return annotations

def load_per_entities():
    """Load person entity definitions (8K entities with canonical names)."""
    print("Loading PER entities...")
    with open(DATA_DIR / "PER-entities (1).json") as f:
        data = json.load(f)
    
    # Build entity_id -> name mapping
    entity_map = {}
    for ent in data:
        entity_map[ent['id']] = ent['name']
    
    print(f"  Loaded {len(entity_map)} entities")
    return entity_map

def load_training_dates():
    """Get resolution -> date mapping from training pairs."""
    print("Loading training pair dates...")
    df = pd.read_parquet(DATA_DIR / "training_pairs_1626_1630_dedup.parquet")
    res_dates = df.groupby('resolution_id')['date'].first().to_dict()
    print(f"  Loaded {len(res_dates)} unique resolutions in 1626-1630")
    return res_dates

def load_resolutions(res_ids):
    """Load only resolutions referenced in training data."""
    print("Loading paragraph texts...")
    df = pd.read_parquet(
        DATA_DIR / "resolutions_flat.parquet",
        columns=['id', 'paragraph_texts']
    )
    
    # Filter to resolution IDs we need
    df = df[df['id'].isin(res_ids)]
    res_paragraphs = df.set_index('id')['paragraph_texts'].to_dict()
    print(f"  Loaded {len(res_paragraphs)} resolutions")
    return res_paragraphs

def build_per_training_pairs():
    """
    Main pipeline: build training pairs from PER annotations.
    
    Strategy:
    - Filter PER annotations to 1626-1630 resolutions
    - For each annotation, extract tag_text and offset
    - Look up entity ID -> canonical name
    - Create training record: (resolution_id, paragraph_texts, htr_span, canonical_entity, 'delegate', entity_id, offset, date)
    """
    
    # Load data
    annotations = load_per_annotations()
    entity_map = load_per_entities()
    res_dates = load_training_dates()
    
    # Filter to resolutions in training period
    print("\nFiltering to 1626-1630 period...")
    annotations_filtered = [
        a for a in annotations 
        if a['resolution_id'] in res_dates
    ]
    print(f"  {len(annotations_filtered)} annotations in period")
    
    # Load paragraph texts for these resolutions
    unique_res_ids = set(a['resolution_id'] for a in annotations_filtered)
    res_paragraphs = load_resolutions(unique_res_ids)
    
    # Build training records
    print("\nBuilding training records...")
    records = []
    skipped = defaultdict(int)
    
    for annotation in tqdm(annotations_filtered, desc="Processing"):
        resolution_id = annotation['resolution_id']
        entity_id = annotation['entity']
        htr_span = annotation['tag_text']
        offset = annotation['offset']
        
        # Skip if missing data
        if not htr_span or not entity_id or offset is None:
            skipped['missing_fields'] += 1
            continue
        
        if resolution_id not in res_paragraphs:
            skipped['no_paragraph'] += 1
            continue
        
        # Get canonical name
        canonical_name = entity_map.get(entity_id)
        if not canonical_name:
            skipped['no_entity_map'] += 1
            continue
        
        # Get date
        date = res_dates.get(resolution_id)
        if not date:
            skipped['no_date'] += 1
            continue
        
        paragraph_texts = res_paragraphs[resolution_id]
        
        record = {
            'resolution_id': resolution_id,
            'paragraph_texts': paragraph_texts,
            'htr_span': htr_span,
            'canonical_entity': canonical_name,
            'entity_type': 'delegate',
            'entity_id': entity_id,
            'offset': offset,
            'date': date,
            'source': 'PER-annotations',
        }
        records.append(record)
    
    print(f"\nCreated {len(records)} training records")
    if skipped:
        print("Skipped:")
        for reason, count in sorted(skipped.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
    
    # Deduplicate
    print("\nDeduplicating...")
    df = pd.DataFrame(records)
    dedup_cols = ['resolution_id', 'htr_span', 'canonical_entity', 'offset']
    df_dedup = df.drop_duplicates(subset=dedup_cols)
    print(f"  After dedup: {len(df_dedup)} records ({100*(1-len(df_dedup)/len(df)):.1f}% removed)")
    
    # Save
    output_path = DATA_DIR / "training_pairs_per_1626_1630_dedup.parquet"
    df_dedup.to_parquet(output_path)
    print(f"\nSaved to {output_path}")
    print(f"Columns: {df_dedup.columns.tolist()}")
    print(f"Date range: {df_dedup['date'].min()} to {df_dedup['date'].max()}")
    print(f"Entity types: {df_dedup['entity_type'].unique()}")

if __name__ == "__main__":
    build_per_training_pairs()

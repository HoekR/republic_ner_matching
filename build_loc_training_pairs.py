#!/usr/bin/env python3
"""
Build training data from LOC-annotations.json + LOC-entities.json.

Strategy:
- Load LOC-annotations (1.3M location spans with entity IDs)
- Load LOC-entities (map entity IDs → canonical place names)
- Filter to resolutions in 1626-1630 training period
- Create BIO-tagged sentences with accurate PLACE labels
- Output to parquet for Flair fine-tuning
"""

import json
import pandas as pd
from pathlib import Path
from collections import defaultdict
from tqdm import tqdm

DATA_DIR = Path("data")


def load_loc_data():
    """Load LOC annotations and entity dictionary."""
    print("Loading LOC annotations...")
    with open(DATA_DIR / "LOC-annotations.json") as f:
        loc_annot = json.load(f)
    
    print("Loading LOC entities...")
    with open(DATA_DIR / "LOC-entities.json") as f:
        loc_entities = json.load(f)
    
    entity_dict = {e['id']: e['name'] for e in loc_entities}
    
    print(f"  {len(loc_annot)} annotations")
    print(f"  {len(entity_dict)} entities")
    
    return loc_annot, entity_dict


def load_training_dates():
    """Load resolution IDs and dates from training pairs."""
    print("Loading training pair dates...")
    pairs = pd.read_parquet(DATA_DIR / "training_pairs_1626_1630_dedup.parquet")
    
    # Get resolution → date mapping
    res_dates = pairs.groupby('resolution_id')['date'].first().to_dict()
    
    print(f"  {len(res_dates)} resolutions in 1626-1630 period")
    
    return res_dates


def load_resolutions(res_ids):
    """Load only resolutions we need."""
    print("Loading paragraph texts...")
    resolutions = pd.read_parquet(
        DATA_DIR / "resolutions_flat.parquet",
        filters=[('id', 'in', list(res_ids))]
    )
    
    res_text = resolutions.set_index('id')['paragraph_texts'].to_dict()
    print(f"  {len(res_text)} resolutions loaded")
    
    return res_text


def build_loc_training_pairs():
    """Build training pairs from LOC annotations."""
    loc_annot, entity_dict = load_loc_data()
    res_dates = load_training_dates()
    
    # Filter LOC annotations to our resolutions
    relevant_annot = [
        a for a in loc_annot 
        if a['reference']['resolution_id'] in res_dates
    ]
    
    print(f"\nFiltered to {len(relevant_annot)} annotations in 1626-1630")
    
    # Group by resolution
    by_resolution = defaultdict(list)
    for annot in relevant_annot:
        res_id = annot['reference']['resolution_id']
        by_resolution[res_id].append(annot)
    
    print(f"  {len(by_resolution)} resolutions with LOC annotations")
    
    # Load paragraph texts
    res_text = load_resolutions(by_resolution.keys())
    
    # Create training records
    records = []
    for res_id, annots in tqdm(by_resolution.items(), desc="Building records"):
        if res_id not in res_text:
            continue
        
        text = res_text[res_id]
        if not text or pd.isna(text):
            continue
        
        date = res_dates.get(res_id)
        
        # Each annotation is one training pair
        for annot in annots:
            ref = annot['reference']
            entity_name = entity_dict.get(annot['entity'], '')
            
            if not entity_name:
                continue
            
            records.append({
                'resolution_id': res_id,
                'paragraph_texts': text,
                'htr_span': ref['tag_text'],
                'canonical_entity': entity_name,
                'entity_type': 'place',
                'entity_id': annot['entity'],
                'offset': int(ref['offset']),
                'date': date,
                'source': 'LOC-annotations',
            })
    
    print(f"\nCreated {len(records)} training records")
    
    # Create dataframe
    df = pd.DataFrame(records)
    
    # Deduplicate by (resolution_id, htr_span, canonical_entity, offset)
    df_dedup = df.drop_duplicates(
        subset=['resolution_id', 'htr_span', 'canonical_entity', 'offset']
    )
    
    print(f"After dedup: {len(df_dedup)} records ({(1 - len(df_dedup)/len(df))*100:.1f}% removed)")
    
    # Save
    output_file = DATA_DIR / "training_pairs_loc_1626_1630_dedup.parquet"
    df_dedup.to_parquet(output_file)
    
    print(f"\nSaved to {output_file}")
    print(f"Columns: {df_dedup.columns.tolist()}")
    print(f"\nDate range: {df_dedup['date'].min()} to {df_dedup['date'].max()}")
    print(f"Entity types: {df_dedup['entity_type'].unique()}")
    
    return df_dedup


if __name__ == "__main__":
    df = build_loc_training_pairs()

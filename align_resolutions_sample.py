#!/usr/bin/env python3
"""
Sample-based resolution alignment to test date tolerance.

Tests different date windows (0, ±1, ±3, ±7 days) and reports alignment
success rates to help determine optimal date tolerance.

Usage:
    uv run python align_resolutions_sample.py
"""

import json
from pathlib import Path
import pandas as pd
from tqdm import tqdm
from datetime import datetime, timedelta
from collections import defaultdict

# Configuration
DATADIR = Path("data")
ENRICHED_FILE = "enriched_resolutions_1626_1630_complete.json"
RESOLUTIONS_FILE = "resolutions_flat.parquet"
LOC_ENTITIES_FILE = "LOC-entities.json"
PER_ENTITIES_FILE = "PER-entities.json"
ORG_ENTITIES_FILE = "ORG-entities.json"

SAMPLE_SIZE = 500  # Test on 500 enriched resolutions


def load_enriched_resolutions():
    """Load enriched resolutions with structured entity metadata."""
    print("Loading enriched resolutions...")
    with open(DATADIR / ENRICHED_FILE) as f:
        enriched = json.load(f)
    print(f"  Loaded {len(enriched)} enriched resolutions")
    return enriched


def load_resolutions_flat():
    """Load HTR corpus."""
    print("Loading resolutions_flat parquet...")
    res_df = pd.read_parquet(DATADIR / RESOLUTIONS_FILE)
    print(f"  Loaded {len(res_df)} resolutions")
    return res_df


def load_entity_names(entity_type):
    """Load canonical entity names (LOC/PER/ORG)."""
    file_map = {
        'LOC': LOC_ENTITIES_FILE,
        'PER': PER_ENTITIES_FILE,
        'ORG': ORG_ENTITIES_FILE,
    }
    
    if entity_type not in file_map:
        return {}
    
    try:
        with open(DATADIR / file_map[entity_type]) as f:
            entities = json.load(f)
    except FileNotFoundError:
        print(f"  Warning: {file_map[entity_type]} not found")
        return {}
    
    # Build id -> name mapping
    id_to_name = {}
    for ent in entities:
        ent_id = ent.get('id')
        name = ent.get('name')
        if ent_id and name:
            id_to_name[ent_id] = name
    
    print(f"  Loaded {len(id_to_name)} canonical {entity_type} names")
    return id_to_name


def extract_entities_from_enriched(resolution, id_maps):
    """Extract all entity names from an enriched resolution."""
    places = []
    persons = []
    orgs = []
    
    # Places
    if 'places' in resolution and isinstance(resolution['places'], list):
        places = [p for p in resolution['places'] if p and isinstance(p, str)]
    
    # Persons/Delegates
    if 'persons' in resolution and isinstance(resolution['persons'], list):
        for p in resolution['persons']:
            if isinstance(p, dict):
                name = p.get('name') or p.get('full_name') or p.get('display_name')
                if name:
                    persons.append(name)
            elif isinstance(p, str):
                persons.append(p)
    
    # Organizations
    if 'organizations' in resolution and isinstance(resolution['organizations'], list):
        for o in resolution['organizations']:
            if isinstance(o, dict):
                name = o.get('name')
                if name:
                    orgs.append(name)
            elif isinstance(o, str):
                orgs.append(o)
    
    return {
        'places': places,
        'persons': persons,
        'orgs': orgs,
    }


def extract_entity_mentions_from_text(text, id_maps):
    """Extract entity mentions from HTR text by keyword matching."""
    if not text:
        return {'places': [], 'persons': [], 'orgs': []}
    
    text_lower = text.lower() if isinstance(text, str) else ''
    mentions = {'places': [], 'persons': [], 'orgs': []}
    
    # Scan canonical names
    for entity_type, id_map in id_maps.items():
        type_key = {'LOC': 'places', 'PER': 'persons', 'ORG': 'orgs'}.get(entity_type)
        if not type_key:
            continue
        
        for entity_name in id_map.values():
            if entity_name.lower() in text_lower:
                mentions[type_key].append(entity_name)
    
    return mentions


def compute_overlap_score(enriched_entities, htr_mentions):
    """Compute Jaccard similarity for each entity type."""
    scores = {}
    
    for entity_type in ['places', 'persons', 'orgs']:
        enriched_set = set(enriched_entities.get(entity_type, []))
        htr_set = set(htr_mentions.get(entity_type, []))
        
        if not enriched_set and not htr_set:
            scores[entity_type] = 1.0
        elif not enriched_set or not htr_set:
            scores[entity_type] = 0.0
        else:
            intersection = len(enriched_set & htr_set)
            union = len(enriched_set | htr_set)
            scores[entity_type] = intersection / union if union > 0 else 0.0
    
    # Combined score: weighted average (places most important)
    combined = (
        0.5 * scores['places'] +
        0.3 * scores['persons'] +
        0.2 * scores['orgs']
    )
    
    scores['combined'] = combined
    return scores


def build_entity_index(resolutions_df, id_maps):
    """Build inverted index: entity_name → set of resolution_ids."""
    print("Building entity index...")
    
    entity_to_res_ids = defaultdict(set)
    
    for res_idx, res in tqdm(resolutions_df.iterrows(), total=len(resolutions_df), desc="Indexing", unit="res", leave=False):
        res_id = res.get('id')
        
        # Get text
        paragraphs = res.get('paragraph_texts') or []
        if isinstance(paragraphs, list):
            text = ' '.join(str(p) for p in paragraphs if p)
        else:
            text = str(paragraphs)
        
        # Extract mentions
        htr_mentions = extract_entity_mentions_from_text(text, id_maps)
        
        # Add to index
        for entity_type in ['places', 'persons', 'orgs']:
            for entity_name in htr_mentions[entity_type]:
                entity_to_res_ids[entity_name].add(res_id)
    
    print(f"  Built index with {len(entity_to_res_ids)} unique entities")
    return entity_to_res_ids


def test_date_tolerances(enriched_resolutions, resolutions_df, id_maps, entity_to_res_ids, sample_size=500):
    """
    Test different date tolerances on a sample.
    
    Returns dict with results for each tolerance level.
    """
    print(f"\nTesting date tolerances on {sample_size} samples...")
    
    # Sample enriched resolutions
    sample_enriched = enriched_resolutions[:sample_size]
    
    # Test different date windows
    date_windows = [0, 1, 3, 7]  # days
    results = {window: {'matches': 0, 'attempts': 0, 'date_diffs': []} for window in date_windows}
    
    for enriched in tqdm(sample_enriched, desc="Samples", unit="res"):
        enriched_entities = extract_entities_from_enriched(enriched, id_maps)
        
        # Skip if no entities
        total_entities = len(enriched_entities['places']) + len(enriched_entities['persons']) + len(enriched_entities['orgs'])
        if total_entities == 0:
            continue
        
        enriched_date = enriched.get('date')
        enriched_id = enriched.get('id')
        
        if not enriched_date:
            continue
        
        # Find candidates
        candidate_res_ids = set()
        for entity_type in ['places', 'persons', 'orgs']:
            for entity_name in enriched_entities[entity_type]:
                if entity_name in entity_to_res_ids:
                    candidate_res_ids.update(entity_to_res_ids[entity_name])
        
        if not candidate_res_ids:
            continue
        
        # Find best match (ignoring date)
        best_match = None
        best_score = -1
        best_date_diff = None
        
        for res_id in candidate_res_ids:
            res = resolutions_df[resolutions_df['id'] == res_id].iloc[0]
            res_date = res.get('date')
            
            # Get text
            paragraphs = res.get('paragraph_texts') or []
            if isinstance(paragraphs, list):
                text = ' '.join(str(p) for p in paragraphs if p)
            else:
                text = str(paragraphs)
            
            # Extract mentions
            htr_mentions = extract_entity_mentions_from_text(text, id_maps)
            
            # Compute similarity
            scores = compute_overlap_score(enriched_entities, htr_mentions)
            final_score = scores['combined']
            
            # Track best match
            if final_score > best_score:
                best_score = final_score
                best_match = res_id
                
                # Compute date difference
                try:
                    ed = pd.Timestamp(enriched_date).date()
                    rd = pd.Timestamp(res_date).date()
                    best_date_diff = abs((ed - rd).days)
                except:
                    best_date_diff = None
        
        # Test each tolerance level
        if best_match and best_score > 0.1:
            for window in date_windows:
                results[window]['attempts'] += 1
                
                if best_date_diff is not None:
                    results[window]['date_diffs'].append(best_date_diff)
                    
                    if best_date_diff <= window:
                        results[window]['matches'] += 1
    
    # Report results
    print("\n=== Date Tolerance Test Results ===")
    for window in date_windows:
        r = results[window]
        if r['attempts'] > 0:
            match_rate = r['matches'] / r['attempts'] * 100
            avg_diff = sum(r['date_diffs']) / len(r['date_diffs']) if r['date_diffs'] else 0
            max_diff = max(r['date_diffs']) if r['date_diffs'] else 0
            print(f"\nWindow: ±{window} days")
            print(f"  Attempts: {r['attempts']}")
            print(f"  Matches: {r['matches']} ({match_rate:.1f}%)")
            print(f"  Avg date diff: {avg_diff:.1f} days")
            print(f"  Max date diff: {max_diff} days")
    
    return results


def main():
    """Main pipeline."""
    start_time = datetime.now()
    print("=" * 70)
    print("Resolution Alignment - Date Tolerance Test")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    # Load data
    print("[1/4] Loading data...")
    enriched = load_enriched_resolutions()
    res_df = load_resolutions_flat()
    print()
    
    # Load entity names
    print("[2/4] Loading entity canonical names...")
    id_maps = {
        'LOC': load_entity_names('LOC'),
        'PER': load_entity_names('PER'),
        'ORG': load_entity_names('ORG'),
    }
    print()
    
    # Build entity index
    print("[3/4] Building entity index...")
    entity_to_res_ids = build_entity_index(res_df, id_maps)
    print()
    
    # Test date tolerances
    print("[4/4] Testing date tolerances...")
    results = test_date_tolerances(enriched, res_df, id_maps, entity_to_res_ids, SAMPLE_SIZE)
    
    end_time = datetime.now()
    duration = end_time - start_time
    print("\n" + "=" * 70)
    print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {duration.total_seconds():.1f} seconds")
    print("=" * 70)


if __name__ == '__main__':
    main()

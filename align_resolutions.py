#!/usr/bin/env python3
"""
Align enriched_resolutions_1626_1630_complete.json with resolutions_flat.parquet.

STRATEGY: Entity-overlap based resolution alignment
====================================================

For each enriched resolution (with structured entity metadata), find the
matching resolution in the HTR corpus (resolutions_flat.parquet) by looking
for entity overlap.

Steps:
1. Load enriched resolutions (structured metadata with places, persons, orgs)
2. Load resolutions_flat parquet (HTR corpus)
3. Load entity canonical names (LOC, PER, ORG entities)
4. For each enriched resolution:
   - Extract entities (places, persons, orgs)
   - Score resolutions_flat by entity overlap
   - Find best match (if confidence > threshold)
5. Output alignment mapping with confidence scores

Expected use: Understand which HTR resolutions correspond to enriched metadata,
enabling better training data linking.

Usage:
    uv run python align_resolutions.py
"""

import json
from pathlib import Path
import pandas as pd
from tqdm import tqdm
from datetime import datetime
from collections import defaultdict

# Configuration
DATADIR = Path("data")
ENRICHED_FILE = "enriched_resolutions_1626_1630_complete.json"
RESOLUTIONS_FILE = "resolutions_flat.parquet"
LOC_ENTITIES_FILE = "LOC-entities.json"
PER_ENTITIES_FILE = "PER-entities.json"
ORG_ENTITIES_FILE = "ORG-entities.json"

OUTPUT_ALIGNMENT = DATADIR / "resolution_alignment_1626_1630.json"
OUTPUT_STATS = DATADIR / "resolution_alignment_stats.json"


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
    """
    Extract all entity names from an enriched resolution.
    
    Returns dict with 'places', 'persons', 'orgs' lists.
    """
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
                # Try different name fields
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
    """
    Extract entity mentions from HTR text by looking for canonical names.
    
    Simple keyword matching - scans text for any canonical entity names.
    """
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
    """
    Compute Jaccard similarity for each entity type.
    
    Returns dict with 'places', 'persons', 'orgs' scores and 'combined' score.
    """
    scores = {}
    
    for entity_type in ['places', 'persons', 'orgs']:
        enriched_set = set(enriched_entities.get(entity_type, []))
        htr_set = set(htr_mentions.get(entity_type, []))
        
        if not enriched_set and not htr_set:
            scores[entity_type] = 1.0  # Both empty = perfect match
        elif not enriched_set or not htr_set:
            scores[entity_type] = 0.0  # One empty, other not
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
    """
    Build inverted index: entity_name → set of resolution_ids.
    
    Massively faster than scanning all resolutions for each enriched one.
    """
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


def align_resolutions(enriched_resolutions, resolutions_df, id_maps, entity_to_res_ids):
    """
    For each enriched resolution, find best match in resolutions_flat using index.
    
    Returns list of alignment records with confidence scores.
    """
    print("Aligning resolutions using entity index...")
    
    alignments = []
    skipped_no_entities = 0
    skipped_no_candidates = 0
    
    for enriched_idx, enriched in enumerate(tqdm(enriched_resolutions, desc="Enriched resolutions", unit="res")):
        # Extract entities from enriched resolution
        enriched_entities = extract_entities_from_enriched(enriched, id_maps)
        
        # Skip if no entities to match on
        total_entities = len(enriched_entities['places']) + len(enriched_entities['persons']) + len(enriched_entities['orgs'])
        if total_entities == 0:
            skipped_no_entities += 1
            continue
        
        # Get enriched metadata
        enriched_date = enriched.get('date')
        enriched_id = enriched.get('id')
        
        # Find candidate resolutions using index
        candidate_res_ids = set()
        for entity_type in ['places', 'persons', 'orgs']:
            for entity_name in enriched_entities[entity_type]:
                if entity_name in entity_to_res_ids:
                    candidate_res_ids.update(entity_to_res_ids[entity_name])
        
        if not candidate_res_ids:
            skipped_no_candidates += 1
            continue
        
        # Score candidates
        best_match = None
        best_score = -1
        best_scores = None
        
        for res_id in candidate_res_ids:
            # Get resolution row
            res = resolutions_df[resolutions_df['id'] == res_id].iloc[0]
            res_date = res.get('date')
            
            # Prefer date matches (exact or ±1 day)
            date_penalty = 0.0
            if enriched_date and res_date:
                try:
                    ed = pd.Timestamp(enriched_date).date()
                    rd = pd.Timestamp(res_date).date()
                    
                    if ed == rd:
                        date_penalty = 0.0  # Exact match
                    else:
                        # Try ±1 day
                        import datetime as dt
                        delta = abs((ed - rd).days)
                        if delta <= 1:
                            date_penalty = 0.15  # Small penalty for ±1 day
                        else:
                            date_penalty = 0.5  # Large penalty for further dates
                except:
                    pass
            
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
            final_score = scores['combined'] * (1.0 - date_penalty)
            
            # Track best match
            if final_score > best_score:
                best_score = final_score
                best_match = res_id
                best_scores = scores
        
        # Add to alignments if confidence > threshold
        if best_score > 0.1:  # Low threshold to see partial matches
            alignments.append({
                'enriched_id': enriched_id,
                'enriched_date': enriched_date,
                'matched_resolution_id': best_match,
                'confidence': best_score,
                'scores': best_scores,
                'entities': {
                    'places': len(enriched_entities['places']),
                    'persons': len(enriched_entities['persons']),
                    'orgs': len(enriched_entities['orgs']),
                }
            })
    
    print(f"  Found {len(alignments)} alignments (score > 0.1)")
    print(f"  Skipped {skipped_no_entities} enriched resolutions with no entities")
    print(f"  Skipped {skipped_no_candidates} enriched resolutions with no matching entities in index")
    
    return alignments


def save_alignments(alignments):
    """Save alignment results."""
    print("\n=== Saving alignments ===")
    
    # Save JSON
    with open(OUTPUT_ALIGNMENT, 'w') as f:
        json.dump(alignments, f, indent=2, default=str)
    print(f"  Saved {len(alignments)} alignments to {OUTPUT_ALIGNMENT}")
    
    # Compute statistics
    stats = {
        'total_alignments': len(alignments),
        'confidence_distribution': {
            'high (>0.8)': sum(1 for a in alignments if a['confidence'] > 0.8),
            'medium (0.5-0.8)': sum(1 for a in alignments if 0.5 <= a['confidence'] <= 0.8),
            'low (0.1-0.5)': sum(1 for a in alignments if 0.1 <= a['confidence'] < 0.5),
        },
        'entity_coverage': {
            'with_places': sum(1 for a in alignments if a['entities']['places'] > 0),
            'with_persons': sum(1 for a in alignments if a['entities']['persons'] > 0),
            'with_orgs': sum(1 for a in alignments if a['entities']['orgs'] > 0),
        }
    }
    
    with open(OUTPUT_STATS, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"  Saved statistics to {OUTPUT_STATS}")
    
    # Print stats
    print("\n=== Alignment Statistics ===")
    print(f"  Total alignments: {stats['total_alignments']}")
    print(f"\n  Confidence distribution:")
    for level, count in stats['confidence_distribution'].items():
        print(f"    {level}: {count}")
    print(f"\n  Entity coverage:")
    for entity_type, count in stats['entity_coverage'].items():
        print(f"    {entity_type}: {count}")


def main():
    """Main pipeline."""
    start_time = datetime.now()
    print("=" * 70)
    print("Resolution Alignment (Enriched → Flat Parquet)")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    # Load data
    print("[1/5] Loading data...")
    enriched = load_enriched_resolutions()
    res_df = load_resolutions_flat()
    print()
    
    # Load entity names
    print("[2/5] Loading entity canonical names...")
    id_maps = {
        'LOC': load_entity_names('LOC'),
        'PER': load_entity_names('PER'),
        'ORG': load_entity_names('ORG'),
    }
    print()
    
    # Build entity index
    print("[3/5] Building entity index...")
    entity_to_res_ids = build_entity_index(res_df, id_maps)
    print()
    
    # Align
    print("[4/5] Aligning resolutions...")
    alignments = align_resolutions(enriched, res_df, id_maps, entity_to_res_ids)
    print()
    
    # Save
    print("[5/5] Saving results...")
    save_alignments(alignments)
    
    end_time = datetime.now()
    duration = end_time - start_time
    print("\n" + "=" * 70)
    print(f"Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {duration.total_seconds():.1f} seconds")
    print("=" * 70)


if __name__ == '__main__':
    main()

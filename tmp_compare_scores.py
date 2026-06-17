import sys
sys.path.insert(0, '/Users/rikhoekstra/develop/republic_ner_matching')
import importlib
import generate_alignment.build_alignment_artifacts as ba

importlib.reload(ba)

def old_score_candidate(enriched_entities, flat_text, enriched_date, candidate_date_raw):
    candidate_date = None
    if candidate_date_raw is not None and str(candidate_date_raw).strip():
        try:
            candidate_date = ba.pd.Period(str(candidate_date_raw)[:10], freq='D')
        except (TypeError, ValueError):
            candidate_date = None
    place_matches = sum(1 for name in enriched_entities['places'] if name and name.lower() in flat_text)
    person_matches = sum(1 for name in enriched_entities['persons'] if name and name.lower() in flat_text)
    org_matches = sum(1 for name in enriched_entities['orgs'] if name and name.lower() in flat_text)
    total_matches = place_matches + person_matches + org_matches
    same_day = candidate_date == enriched_date
    entity_types_matched = sum(1 for value in (place_matches, person_matches, org_matches) if value > 0)
    place_weight = place_matches * 300
    score = (same_day * 10000) + place_weight + (person_matches * 100) + (org_matches * 100) + entity_types_matched
    return {
        'candidate_date': candidate_date,
        'place_matches': place_matches,
        'person_matches': person_matches,
        'org_matches': org_matches,
        'total_matches': total_matches,
        'same_day': same_day,
        'entity_types_matched': entity_types_matched,
        'place_weight': place_weight,
        'score': score,
    }

all_data = ba.load_data()
enriched_all, res_df, loc_names, per_names, org_names = all_data
anchor_map = ba.build_date_anchor_map(enriched_all, res_df, loc_names, per_names, org_names)

preview_current = ba.build_preview_matches(enriched_all, res_df, loc_names, per_names, org_names, anchor_map=anchor_map, limit=8)
strat_current = ba.build_stratified_matches(enriched_all, res_df, loc_names, per_names, org_names, anchor_map=anchor_map, sample_size=30)

orig_score_candidate = ba.score_candidate
ba.score_candidate = old_score_candidate
preview_old = ba.build_preview_matches(enriched_all, res_df, loc_names, per_names, org_names, anchor_map=anchor_map, limit=8)
strat_old = ba.build_stratified_matches(enriched_all, res_df, loc_names, per_names, org_names, anchor_map=anchor_map, sample_size=30)
ba.score_candidate = orig_score_candidate

print('PREVIEW: current vs old')
for i in range(max(len(preview_current), len(preview_old))):
    cur = preview_current[i] if i < len(preview_current) else None
    old = preview_old[i] if i < len(preview_old) else None
    print('---', i+1)
    if cur:
        print('current:', cur['enriched'].get('file'), cur['enriched'].get('resolution_index'), cur['best_match'].get('id'), cur['same_day'], cur['date_diff_days'], cur['score'])
    else:
        print('current: None')
    if old:
        print('old:    ', old['enriched'].get('file'), old['enriched'].get('resolution_index'), old['best_match'].get('id'), old['same_day'], old['date_diff_days'], old['score'])
    else:
        print('old:    None')
    print()

cur_pairs = {(item['enriched'].get('file'), item['enriched'].get('resolution_index'), item['best_match'].get('id')) for item in strat_current}
old_pairs = {(item['enriched'].get('file'), item['enriched'].get('resolution_index'), item['best_match'].get('id')) for item in strat_old}
print('STRATIFIED: current', len(strat_current), 'old', len(strat_old))
print('common', len(cur_pairs & old_pairs))
print('only current', len(cur_pairs - old_pairs))
print('only old', len(old_pairs - cur_pairs))
if cur_pairs != old_pairs:
    print('\nDIFFERENT stratified pairs:')
    for item in sorted(cur_pairs ^ old_pairs):
        print(item)

cur_preview_pairs = {(item['enriched'].get('file'), item['enriched'].get('resolution_index'), item['best_match'].get('id')) for item in preview_current}
old_preview_pairs = {(item['enriched'].get('file'), item['enriched'].get('resolution_index'), item['best_match'].get('id')) for item in preview_old}
print('\nPREVIEW pairs common', len(cur_preview_pairs & old_preview_pairs))
print('only current preview', len(cur_preview_pairs - old_preview_pairs))
print('only old preview', len(old_preview_pairs - cur_preview_pairs))
if cur_preview_pairs != old_preview_pairs:
    print('\nDIFFERENT preview pairs:')
    for item in sorted(cur_preview_pairs ^ old_preview_pairs):
        print(item)

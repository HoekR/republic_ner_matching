import json
from pathlib import Path

path = Path('manual_entitiy_alignment.ipynb')
nb = json.loads(path.read_text())
cell = nb['cells'][41]
assert cell['cell_type'] == 'code'
old = [
    "dated_places['date'] = pd.PeriodIndex(dated_places['date'].astype(str), freq='D')\n",
    "overlap_common = set(dated_places['date']) & set(org_overlap['date'])\n",
    "pd.DataFrame(list(overlap_common), columns=['date']).to_excel(data_path / \"overlap_common_dates.xlsx\", index=False)"
]
new = [
    "dated_places['date'] = pd.PeriodIndex(dated_places['date'].astype(str), freq='D')\n",
    "dated_places['date_str'] = dated_places['date'].astype(str)\n",
    "loc_annotations_dated_window['date_str'] = loc_annotations_dated_window['date'].astype(str)\n",
    "overlap_common = set(dated_places['date_str']) & set(loc_annotations_dated_window['date_str'])\n",
    "pd.DataFrame(sorted(overlap_common), columns=['date']).to_excel(data_path / \"overlap_common_dates.xlsx\", index=False)"
]

if cell['source'] != old:
    raise SystemExit('Cell source does not match expected exact content. Actual content:\n' + ''.join(cell['source']))

cell['source'] = new
path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + '\n')
print('Notebook cell patched')

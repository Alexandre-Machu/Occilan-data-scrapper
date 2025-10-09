from pathlib import Path
import sys
# ensure repo root on path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils import parse_opgg_adversaires_csv
import re

p = Path('data/raw/Occi\'lan #6 - OPGG Adversaires.csv')
df = parse_opgg_adversaires_csv(p, edition=6)
print('rows:', len(df))
print('raw role counts:')
print(df['role'].value_counts(dropna=False).to_dict())

# normalization matching app.py
def _normalize_role(r):
    try:
        if not isinstance(r, str):
            return r
        s = r.strip().lower()
    except Exception:
        return r
    try:
        s_clean = re.sub(r'[^a-z0-9]', '', s)
    except Exception:
        s_clean = ''.join(ch for ch in s if ch.isalnum())
    if s_clean in ('support', 'supp', 'sup', 's'):
        return 'Supp'
    if s_clean in ('top', 'toplane'):
        return 'Top'
    if s_clean in ('jungle', 'jg'):
        return 'Jungle'
    if s_clean in ('mid', 'middle'):
        return 'Mid'
    if s_clean in ('adc', 'bot', 'bottom', 'carry'):
        return 'Adc'
    try:
        return s_clean.capitalize() if s_clean else r
    except Exception:
        return r

print('\nnormalized role counts:')
print(df['role'].apply(_normalize_role).value_counts(dropna=False).to_dict())
print('\nsample normalized roles:', sorted(set(df['role'].apply(_normalize_role).dropna().unique())))

from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
from src.utils import parse_opgg_adversaires_csv
import re
p = Path("data/raw/Occi'lan #6 - OPGG Adversaires.csv")
df = parse_opgg_adversaires_csv(p, edition=6)

def inspect_role(r):
    s = r.strip()
    tokens = re.split(r'[\,;\|/\s]+', s)
    tokens = [t for t in tokens if t]
    candidate=None
    for t in tokens:
        tl=t.lower()
        if tl in ('support','supp','sup','s','top','toplane','jungle','jg','mid','middle','adc','bot','bottom','carry'):
            candidate=tl; break
        tc=re.sub(r'[^a-z]','',tl)
        if tc in ('support','supp','sup','s','top','toplane','jungle','jg','mid','middle','adc','bot','bottom','carry'):
            candidate=tc; break
    if candidate is None:
        cleaned = re.sub(r'[^a-z0-9]','',s.lower())
        if 'supp' in cleaned:
            candidate='supp'
        elif 'top' in cleaned and 'toplane' not in cleaned:
            candidate='top'
        elif 'toplane' in cleaned:
            candidate='toplane'
        elif 'jungle' in cleaned or 'jg' in cleaned:
            candidate='jungle'
        elif 'middle' in cleaned or 'mid' in cleaned:
            candidate='mid'
        elif 'adc' in cleaned or 'bot' in cleaned or 'bottom' in cleaned or 'carry' in cleaned:
            candidate='adc'
        else:
            candidate=cleaned
    return {'orig':r,'tokens':tokens,'candidate':candidate,'cleaned': re.sub(r'[^a-z0-9]','',s.lower())}

for v in sorted(set(df['role'])):
    if 'supp' in v.lower():
        print(inspect_role(v))

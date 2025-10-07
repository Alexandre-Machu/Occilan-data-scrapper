from pathlib import Path
import sys
# ensure src is importable
sys.path.append(str(Path(__file__).parent.parent / 'src'))
from utils import parse_opgg_adversaires_csv, normalize_elo

# Use double quotes to avoid escaping the apostrophe in the filename
p = Path("data/raw/Occi'lan #4 - OPGG Adversaires.csv")
if not p.exists():
    print('Fichier introuvable:', p)
    raise SystemExit(1)

df = parse_opgg_adversaires_csv(p, edition=4, split_alternates=True)
print('Rows parsed:', len(df))
print(df.head(20).to_string())

# Show rows where the original summoner_raw included a slash (alternates)
alt_rows = df[df['summoner_raw'].str.contains('/')]
if not alt_rows.empty:
    print('\nRows with slash in original summoner_raw (after distribution):')
    print(alt_rows.to_string())

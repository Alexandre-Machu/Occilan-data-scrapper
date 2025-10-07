from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent / 'src'))
from utils import parse_opgg_adversaires_csv

p = Path("data/raw/Occi'lan #4 - OPGG Adversaires.csv")
if not p.exists():
    raise SystemExit('file missing')

df = parse_opgg_adversaires_csv(p, edition=4, split_alternates=True)

# Rows where the original cell contained a slash or the summoner is ZoogieWoogie/Nikzebi
mask = df['summoner_raw'].str.contains('/') | df['summoner_raw'].str.contains('ZoogieWoogie') | df['summoner_raw'].str.contains('Nikzebi')
print('Total rows:', len(df))
print('\nAffected rows:')
print(df[mask].to_string(index=False))

print('\nAll players for teams containing "PPG" or "Tayme":')
mask2 = df['team'].str.contains('PPG') | df['team'].str.contains('Tayme') | df['team'].str.contains('Zoogie')
print(df[mask2].to_string(index=False))

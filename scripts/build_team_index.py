"""Script: build team players mapping for an edition.

Usage: python scripts/build_team_index.py 6
"""
import sys
from pathlib import Path
from src.team_utils import build_team_players

def main():
    if len(sys.argv) < 2:
        print('Usage: build_team_index.py <edition>')
        return
    ed = int(sys.argv[1])
    proc_csv = Path('data') / 'processed' / f'players_edition{ed}.csv'
    cache_dir = Path('data') / 'cache' / 'matches'
    out = Path('data') / 'processed' / f'team_players_edition{ed}.json'
    teams = build_team_players(ed, proc_csv, cache_dir, out)
    print(f'Wrote {out} with {len(teams)} teams')

if __name__ == '__main__':
    main()

"""
Create a processed match_stats file for a given edition using only cached match JSONs
Reads:
 - data/tournament_matches.json (expects keys like edition_7 -> [match ids])
 - data/cache/matches/*.json
Writes:
 - data/processed/match_stats_edition{edition}_{ts}.json

This is an offline-only utility (no Riot API calls).
"""
import json
import time
from pathlib import Path
import argparse

ROOT = Path(__file__).parent.parent
TOUR_FILE = ROOT / 'data' / 'tournament_matches.json'
CACHE_DIR = ROOT / 'data' / 'cache' / 'matches'
OUT_DIR = ROOT / 'data' / 'processed'
OUT_DIR.mkdir(parents=True, exist_ok=True)

import sys
sys.path.insert(0, str(ROOT))
from src.match_stats import aggregate_matches


def load_cached_match_by_id(mid: str):
    p = CACHE_DIR / f"{mid}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def build_puuid_map(matches):
    puuid_map = {}
    for m in matches:
        if not isinstance(m, dict):
            continue
        info = m.get('info') or {}
        for p in info.get('participants', []):
            pu = p.get('puuid')
            name = p.get('summonerName') or p.get('riotIdGameName') or p.get('summonerId')
            if isinstance(name, str):
                name = name.strip()
            if pu and name:
                puuid_map[pu] = name
    return puuid_map


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--edition', type=int, default=7)
    args = parser.parse_args()

    if not TOUR_FILE.exists():
        print('tournament_matches.json not found at', TOUR_FILE)
        return 2
    data = json.loads(TOUR_FILE.read_text(encoding='utf-8'))
    key = f'edition_{args.edition}'
    ids = data.get(key, [])
    if not ids:
        print(f'No match ids found for {key} in {TOUR_FILE}')
        return 1

    matches = []
    for mid in ids:
        m = load_cached_match_by_id(mid)
        if m is None:
            print('Missing cached match:', mid)
            continue
        matches.append(m)

    if not matches:
        print('No cached matches available for the provided ids.')
        return 1

    agg = aggregate_matches(matches)
    puuid_map = build_puuid_map(matches)

    ts = int(time.time())
    out = OUT_DIR / f'match_stats_edition{args.edition}_{ts}.json'
    payload = {
        'matches': [m.get('metadata', {}) for m in matches],
        'agg': agg,
        'puuid_map': puuid_map,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Wrote', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

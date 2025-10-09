"""
Admin script: fetch match id lists for players (uses match-v5 by-puuid ids endpoint).
- Input: JSON teams_with_puuid.json or a CSV with puuids
- Output: data/tournament_matches.json (list of match ids)

Adapted from OccilanStats-6 fetch_matches.py but simplified and admin-gated.
"""
import os
import sys
import json
import argparse
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.match_stats import REGION_ROUTING

import requests


def fetch_for_puuid(puuid: str, api_key: str, region: str = 'euw', count: int = 100):
    if not puuid or not api_key:
        return []
    region_routing = REGION_ROUTING.get(region.lower(), 'europe')
    base = f'https://{region_routing}.api.riotgames.com'
    url = f"{base}/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {'start': 0, 'count': count}
    try:
        r = requests.get(url, params=params, headers={'X-Riot-Token': api_key}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[fetch_matches] API error for puuid {puuid}: {e}")
        return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--teams-json', default='data/processed/teams_with_puuid.json')
    p.add_argument('--out', default='data/tournament_matches.json')
    p.add_argument('--api-key', default=os.environ.get('OCCILAN_RIOT_API_KEY'))
    p.add_argument('--region', default='euw')
    p.add_argument('--per-player', type=int, default=50)
    args = p.parse_args()

    tpath = Path(args.teams_json)
    if not tpath.exists():
        print(f"[fetch_matches] teams json not found: {tpath}")
        return
    teams = json.loads(tpath.read_text(encoding='utf-8'))

    match_set = []
    # iterate players
    for team, players in teams.items():
        for p in players:
            puuid = p.get('puuid')
            if not puuid:
                continue
            ids = fetch_for_puuid(puuid, args.api_key, region=args.region, count=args.per_player)
            for mid in ids:
                if mid not in match_set:
                    match_set.append(mid)
            # polite
            time.sleep(0.12)

    # persist
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(match_set, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[fetch_matches] Wrote {len(match_set)} match ids to {outp}")


if __name__ == '__main__':
    main()

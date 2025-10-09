"""
Admin script: resolve puuids for players.
- Prefer resolving from local cached match JSONs (no network).
- Optionally use Riot Summoner-V4 by-name endpoint when --api is provided (admin-only).
- Writes out a `data/processed/teams_with_puuid.json` mapping if possible.

This file is adapted/simplified from OccilanStats-6 fetch_puuid.py and made safe for viewer mode
(we never print or expose PUUIDs to stdout for non-admins).
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path

# make repo root importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import team_utils
from src.match_stats import PLATFORM_ROUTING


def lookup_via_api(name: str, api_key: str, region: str = 'euw'):
    """Lookup summoner by name using Summoner-V4 (returns puuid or None)."""
    import requests
    if not api_key or not name:
        return None
    platform = PLATFORM_ROUTING.get(region.lower(), region.lower())
    base = f'https://{platform}.api.riotgames.com'
    url = f"{base}/lol/summoner/v4/summoners/by-name/{name}"
    try:
        r = requests.get(url, params={}, headers={'X-Riot-Token': api_key}, timeout=8)
        r.raise_for_status()
        data = r.json()
        return data.get('puuid')
    except Exception as e:
        print(f"[fetch_puuid] API lookup failed for {name}: {e}")
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--players-csv', help='Processed players CSV (optional)', default='data/processed/players_edition7.csv')
    p.add_argument('--cache-matches', help='Cache matches dir', default='data/cache/matches')
    p.add_argument('--out', help='Output json for teams with puuid', default='data/processed/teams_with_puuid.json')
    p.add_argument('--api-key', help='Riot API key (admin-only)', default=os.environ.get('OCCILAN_RIOT_API_KEY'))
    p.add_argument('--region', help='Region for Summoner v4 lookups', default='euw')
    args = p.parse_args()

    cache_dir = Path(args.cache_matches)
    out_path = Path(args.out)

    # First try to resolve from cache
    print('[fetch_puuid] Building puuid index from cached matches...')
    puuid_index = team_utils.build_puuid_index(cache_dir)
    print(f"[fetch_puuid] Found {len(puuid_index)} names in cache")

    teams_map = {}
    # prefer processed CSV input
    try:
        import pandas as pd
        csvp = Path(args.players_csv)
        if csvp.exists():
            df = pd.read_csv(csvp)
            for _, r in df.iterrows():
                team = r.get('team') or '—'
                name = (r.get('summoner') or r.get('summoner_raw') or r.get('summonerName') or '')
                name = str(name).strip()
                if not name:
                    continue
                puuid = puuid_index.get(name)
                resolved = 'cache' if puuid else None
                # try API if available and not resolved
                if not puuid and args.api_key:
                    puuid = lookup_via_api(name, args.api_key, region=args.region)
                    if puuid:
                        resolved = 'api'
                        # small sleep to be polite
                        time.sleep(0.15)
                teams_map.setdefault(team, []).append({'name': name, 'puuid': puuid, 'resolved_via': resolved})

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(teams_map, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"[fetch_puuid] Wrote teams->players with puuid to {out_path}")
            return
    except Exception:
        # pandas not available or CSV missing — fall back to cache-only scan
        pass

    # Fallback: convert cache index into a single pseudo-team mapping
    for name, puuid in puuid_index.items():
        teams_map.setdefault('resolved_from_cache', []).append({'name': name, 'puuid': puuid, 'resolved_via': 'cache'})

    if teams_map:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(teams_map, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"[fetch_puuid] Wrote {len(teams_map)} teams entries to {out_path} (cache-only)")
    else:
        print('[fetch_puuid] No data to write')


if __name__ == '__main__':
    main()

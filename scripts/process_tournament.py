"""Process all match IDs listed in data/tournament_matches.json for a given edition.

Writes output to data/processed/match_stats_edition<edition>_<timestamp>.json
The output includes 'matches' (metadata as before), 'agg' (aggregated stats) and
'puuid_map' (puuid -> summonerName) to make viewer apps able to resolve PUUIDs.

Usage:
  python scripts/process_tournament.py --edition 6 --region euw

Requires OCCILAN_RIOT_API_KEY in environment or in .env at repository root.
"""
import argparse
from pathlib import Path
import json
import time
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
env_path = ROOT / '.env'
if env_path.exists():
    load_dotenv(env_path)

import sys
sys.path.insert(0, str(ROOT))
from src.match_stats import get_match, aggregate_matches

OUT_DIR = ROOT / 'data' / 'processed'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--edition', type=int, default=6, help='edition number as in tournament_matches.json')
    parser.add_argument('--region', default='euw', help='region short code (euw, na, kr, etc)')
    args = parser.parse_args()

    api_key = __import__('os').environ.get('OCCILAN_RIOT_API_KEY')
    if not api_key:
        print('No OCCILAN_RIOT_API_KEY found — set it in .env or environment.')
        return 2

    tm_file = ROOT / 'data' / 'tournament_matches.json'
    if not tm_file.exists():
        print('tournament_matches.json not found at', tm_file)
        return 2

    data = json.loads(tm_file.read_text(encoding='utf-8'))
    key = f'edition_{args.edition}'
    ids = data.get(key, [])
    if not ids:
        print(f'No match ids found for {key} in {tm_file}')
        return 1

    print(f'Processing {len(ids)} match(es) for edition {args.edition}...')
    matches = []
    for mid in ids:
        try:
            print('Fetching', mid)
            m = get_match(mid, api_key=api_key, region=args.region)
            matches.append(m)
            # small sleep to be polite; get_match caches results
            time.sleep(1.0)
        except Exception as e:
            print('Failed fetching', mid, e)

    if not matches:
        print('No matches fetched.')
        return 2

    agg = aggregate_matches(matches)

    # build puuid_map from full matches (info.participants)
    puuid_map = {}
    for m in matches:
        info = (m.get('info') or {})
        for p in info.get('participants', []):
            pu = p.get('puuid')
            name = p.get('summonerName')
            if pu and name:
                puuid_map[pu] = name

    ts = int(time.time())
    out = OUT_DIR / f'match_stats_edition{args.edition}_{ts}.json'
    payload = {
        'matches': [m.get('metadata', {}) for m in matches],
        'agg': agg,
        'puuid_map': puuid_map,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Written', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

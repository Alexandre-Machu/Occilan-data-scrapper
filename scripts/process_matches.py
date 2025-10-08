"""Process a list of Riot match IDs and compute aggregated statistics.

Usage:
  # process a single match id
  python scripts/process_matches.py --match EUW1_... --region euw

  # process a CSV file with one matchId per line
  python scripts/process_matches.py --csv matches.csv --region euw

Output: writes data/processed/match_stats_<timestamp>.json with aggregated results and per-match details.
"""
import argparse
from pathlib import Path
import json
import sys
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
    parser.add_argument('--match', help='A single match ID')
    parser.add_argument('--csv', help='CSV file with match IDs, one per line')
    parser.add_argument('--region', default='euw', help='region short code (euw, na, kr, etc)')
    args = parser.parse_args()

    api_key = None
    api_key = __import__('os').environ.get('OCCILAN_RIOT_API_KEY')
    if not api_key:
        print('No OCCILAN_RIOT_API_KEY found — aborting. Set your Riot API key in .env or environment.')
        return 2

    match_ids = []
    if args.match:
        match_ids = [args.match]
    elif args.csv:
        p = Path(args.csv)
        if not p.exists():
            print('CSV not found:', p)
            return 2
        for line in p.read_text(encoding='utf-8').splitlines():
            s=line.strip()
            if s:
                match_ids.append(s)
    else:
        print('Provide --match or --csv')
        return 1

    matches = []
    for mid in match_ids:
        try:
            m = get_match(mid, api_key=api_key, region=args.region)
            matches.append(m)
            time.sleep(1.0)
        except Exception as e:
            print('Failed fetching match', mid, e)

    if not matches:
        print('No matches fetched.')
        return 2

    agg = aggregate_matches(matches)
    ts = int(time.time())
    out = OUT_DIR / f'match_stats_{ts}.json'
    out.write_text(json.dumps({'matches': [m.get('metadata',{}) for m in matches], 'agg': agg}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Written', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())

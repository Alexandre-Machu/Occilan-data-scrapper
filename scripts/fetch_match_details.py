"""
Admin script: fetch and cache match detail JSONs for a list of match ids.
- Reads data/tournament_matches.json (list of match ids)
- Uses src.match_stats.get_match which already caches to data/cache/matches
"""
import os
import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.match_stats import get_match


def main():
    import time
    p = argparse.ArgumentParser()
    p.add_argument('--matches-json', default='data/tournament_matches.json')
    p.add_argument('--api-key', default=os.environ.get('OCCILAN_RIOT_API_KEY'))
    p.add_argument('--region', default='euw')
    p.add_argument('--use-cache', action='store_true', help='Do not call API if cache hits')
    args = p.parse_args()

    mpath = Path(args.matches_json)
    if not mpath.exists():
        print(f"[fetch_match_details] matches file not found: {mpath}")
        return
    mids = json.loads(mpath.read_text(encoding='utf-8'))
    print(f"[fetch_match_details] Found {len(mids)} match ids; fetching (use_cache={args.use_cache})")
    fetched = 0
    for mid in mids:
        try:
            mj = get_match(mid, args.api_key, region=args.region, use_cache=args.use_cache)
            fetched += 1
        except Exception as e:
            print(f"[fetch_match_details] failed {mid}: {e}")
    print(f"[fetch_match_details] Processed {fetched}/{len(mids)} matches")


if __name__ == '__main__':
    main()

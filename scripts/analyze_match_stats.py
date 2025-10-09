"""
Admin script: analyze cached match JSONs and produce aggregated stats JSONs.
- Reads cached match JSONs from data/cache/matches
- Uses src.match_stats.aggregate_matches
- Writes outputs to data/processed/match_stats_*.json
"""
import os
import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.match_stats import aggregate_matches


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cache-dir', default='data/cache/matches')
    p.add_argument('--out', default=None, help='Output JSON path (optional)')
    args = p.parse_args()

    cache = Path(args.cache_dir)
    if not cache.exists():
        print(f"[analyze_match_stats] cache dir not found: {cache}")
        return

    matches = []
    for f in sorted(cache.glob('*.json')):
        try:
            obj = json.loads(f.read_text(encoding='utf-8'))
            matches.append(obj)
        except Exception:
            continue

    print(f"[analyze_match_stats] Loaded {len(matches)} cached match JSONs")
    agg = aggregate_matches(matches)

    outp = args.out
    if not outp:
        import time
        ts = int(time.time())
        outp = f"data/processed/match_stats_{ts}.json"
    outp = Path(outp)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[analyze_match_stats] Wrote aggregated stats to {outp}")


if __name__ == '__main__':
    main()

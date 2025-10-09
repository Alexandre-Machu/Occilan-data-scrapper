"""
Rebuild tournament_matches.json from cached match JSONs and build a pseudonym mapping
between the processed players CSV and names observed in cached matches.

Outputs:
- data/tournament_matches.json  (list of match ids found in cache)
- data/processed/pseudonym_mapping.json  (csv_name -> observed names + puuid + count)

This is safe and offline (reads only local cache). You can later edit the mapping JSON
manually to correct mismatches.
"""
import json
from pathlib import Path
from collections import defaultdict
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CACHE_DIR = Path('data') / 'cache' / 'matches'
OUT_MATCHES = Path('data') / 'tournament_matches.json'
OUT_MAP = Path('data') / 'processed' / 'pseudonym_mapping.json'

# possible processed players CSVs to try
CANDIDATE_CSVS = [Path('data') / 'processed' / 'players_edition7.csv', Path('data') / 'processed' / 'players_edition6.csv']


def load_cached_matches(cache_dir: Path):
    matches = []
    for p in sorted(cache_dir.glob('*.json')):
        try:
            obj = json.loads(p.read_text(encoding='utf-8'))
            matches.append(obj)
        except Exception:
            continue
    return matches


def extract_match_ids(matches):
    ids = []
    for mj in matches:
        mid = mj.get('metadata', {}).get('matchId') or mj.get('metadata', {}).get('gameId')
        if mid:
            ids.append(mid)
    # unique preserving order
    seen = set()
    unique = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)
    return unique


def load_csv_names():
    import csv
    names = []
    for cand in CANDIDATE_CSVS:
        try:
            if cand.exists():
                with cand.open(encoding='utf-8') as fh:
                    reader = csv.DictReader(fh)
                    # try common fields
                    for r in reader:
                        name = r.get('summoner') or r.get('summoner_raw') or r.get('summonerName') or r.get('name')
                        if name:
                            names.append(name.strip())
                break
        except Exception:
            continue
    return list(dict.fromkeys(names))


def build_mapping(names, matches):
    # collect observed participants per match
    observed_by_name = defaultdict(lambda: defaultdict(int))
    observed_puuid = defaultdict(set)
    for mj in matches:
        for p in (mj.get('info') or {}).get('participants', []) or []:
            raw_name = p.get('riotIdGameName') or p.get('summonerName') or p.get('summonerId')
            if not raw_name:
                continue
            name = raw_name.strip()
            observed_by_name[name]['count'] += 1
            puuid = p.get('puuid')
            if puuid:
                observed_puuid[name].add(puuid)

    # for each csv name, find exact matches and close matches (simple substring / case-insensitive)
    mapping = {}
    lowered_to_observed = {n.lower(): n for n in observed_by_name.keys()}
    observed_names = list(observed_by_name.keys())

    for csv_name in names:
        item = {'observed': [], 'observed_count': 0}
        if not csv_name:
            mapping[csv_name] = item
            continue
        # exact/ci match
        key = csv_name.strip()
        k_lower = key.lower()
        exact = lowered_to_observed.get(k_lower)
        if exact:
            item['observed'].append({'name': exact, 'count': observed_by_name[exact]['count'], 'puuid': list(observed_puuid.get(exact, []))})
            item['observed_count'] += observed_by_name[exact]['count']
        # substring matches
        for on in observed_names:
            if on.lower() == k_lower:
                continue
            if k_lower in on.lower() or on.lower() in k_lower:
                item['observed'].append({'name': on, 'count': observed_by_name[on]['count'], 'puuid': list(observed_puuid.get(on, []))})
                item['observed_count'] += observed_by_name[on]['count']
        mapping[key] = item
    return mapping


def main():
    matches = load_cached_matches(CACHE_DIR)
    print(f"Loaded {len(matches)} cached match files from {CACHE_DIR}")
    ids = extract_match_ids(matches)
    print(f"Extracted {len(ids)} unique match ids from cache")

    OUT_MATCHES.parent.mkdir(parents=True, exist_ok=True)
    OUT_MATCHES.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Wrote {len(ids)} match ids to {OUT_MATCHES}")

    csv_names = load_csv_names()
    print(f"Loaded {len(csv_names)} player names from processed CSV(s)")

    mapping = build_mapping(csv_names, matches)
    OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
    OUT_MAP.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Wrote pseudonym mapping to {OUT_MAP}")

    # short summary
    mapped = sum(1 for k, v in mapping.items() if v.get('observed'))
    print(f"Mapping: {mapped}/{len(mapping)} CSV names have observed matches in cache")

if __name__ == '__main__':
    main()

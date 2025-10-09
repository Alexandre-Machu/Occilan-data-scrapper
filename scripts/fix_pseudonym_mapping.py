"""
Auto-fix pseudonym mapping by matching CSV names to observed names in cached matches.
Writes: data/processed/pseudonym_mapping_fixed.json
Prints a short report of fixes.
"""
import json
from pathlib import Path
import unicodedata
import re
from collections import Counter, defaultdict
import difflib

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / 'data' / 'cache' / 'matches'
IN_MAP = ROOT / 'data' / 'processed' / 'pseudonym_mapping.json'
OUT_MAP = ROOT / 'data' / 'processed' / 'pseudonym_mapping_fixed.json'


def normalize(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.strip()
    # remove trailing tags like ',,Silver,3' (keep part before first comma if csv-like)
    if ',' in s and len(s) > 1:
        # heuristics: if the name contains multiple commas and the first token looks like a name, keep it
        tokens = [t for t in s.split(',') if t]
        if tokens:
            # if the first token contains letters, prefer it
            if re.search(r'[A-Za-zÀ-ÿ]', tokens[0]):
                s = tokens[0]
    # normalize unicode
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    # remove non-alnum except spaces
    s = re.sub(r'[^a-z0-9 ]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def gather_observed_names(cache_dir: Path):
    counts = Counter()
    puuid_map = defaultdict(set)
    for p in sorted(cache_dir.glob('*.json')):
        try:
            obj = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        info = obj.get('info') or {}
        for part in info.get('participants', []) or []:
            names = []
            # prefer visible names
            for k in ('summonerName', 'riotIdGameName', 'summonerId'):
                v = part.get(k)
                if v and isinstance(v, str):
                    names.append(v.strip())
            # record all name variants
            for n in names:
                if n:
                    counts[n] += 1
                    pu = part.get('puuid')
                    if pu:
                        puuid_map[n].add(pu)
    return counts, puuid_map


def best_match(csv_name_norm, observed_norm_map):
    # exact
    if csv_name_norm in observed_norm_map:
        return observed_norm_map[csv_name_norm]
    # substring
    for onorm, oname in observed_norm_map.items():
        if csv_name_norm in onorm or onorm in csv_name_norm:
            return oname
    # fuzzy via difflib
    choices = list(observed_norm_map.keys())
    if not choices:
        return None
    close = difflib.get_close_matches(csv_name_norm, choices, n=1, cutoff=0.75)
    if close:
        return observed_norm_map[close[0]]
    # fallback: return None
    return None


def main():
    if not IN_MAP.exists():
        print('Input mapping not found:', IN_MAP)
        return 2
    with IN_MAP.open(encoding='utf-8') as f:
        mapping = json.load(f)

    # gather observed names from cache
    counts, puuids = gather_observed_names(CACHE_DIR)
    observed_names = list(counts.keys())
    # build normalized map
    observed_norm_map = {}
    for n in observed_names:
        observed_norm_map[normalize(n)] = n

    fixed = {}
    fixed_count = 0
    suggestions = {}

    for csv_name, entry in mapping.items():
        # if already has observed, keep as-is
        if entry and entry.get('observed'):
            fixed[csv_name] = entry
            continue
        # try to find
        csv_norm = normalize(csv_name)
        candidate = None
        if csv_norm:
            candidate = best_match(csv_norm, observed_norm_map)
        if candidate:
            fixed_count += 1
            obs_entry = {'name': candidate, 'count': counts.get(candidate, 0), 'puuid': list(puuids.get(candidate, []))}
            fixed[csv_name] = {'observed': [obs_entry], 'observed_count': obs_entry['count']}
            suggestions[csv_name] = obs_entry
        else:
            # keep original (empty)
            fixed[csv_name] = entry

    # write out
    OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
    OUT_MAP.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding='utf-8')

    # summary
    print('Read', len(mapping), 'csv names')
    print('Observed unique names in cache:', len(observed_names))
    print('Auto-fixed entries:', fixed_count)
    if fixed_count > 0:
        print('\nSample fixes:')
        for i, (k, v) in enumerate(suggestions.items()):
            if i >= 10:
                break
            print(f" - {k} => {v['name']} (count {v['count']})")

    return 0

if __name__ == '__main__':
    raise SystemExit(main())

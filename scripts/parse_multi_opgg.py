"""
Parse multi-OPGG links per team and build a table (Equipe, Position, RiotName, RiotTag)
from the OPGG Adversaires CSV structure.

Usage:
  python scripts/parse_multi_opgg.py --edition 6

Output:
  data/processed/team_riot_ids_edition{edition}.csv
"""
import argparse
from pathlib import Path
import csv
from urllib.parse import urlparse, parse_qs, unquote
import re
import unicodedata

ROOT = Path(__file__).parent.parent
DATA_RAW = ROOT / 'data' / 'raw'
OUT_DIR = ROOT / 'data' / 'processed'
OUT_DIR.mkdir(parents=True, exist_ok=True)

import sys
sys.path.insert(0, str(ROOT))
from src.utils import parse_opgg_adversaires_csv

FNAME_MAP = {
    4: "Occi'lan #4 - OPGG Adversaires.csv",
    5: "Occi'lan #5 - OPGG Adversaires.csv",
    6: "Occi'lan #6 - OPGG Adversaires.csv",
    7: "Occi'lan #7 - OPGG Adversaires.csv",
}


def normalize(s: str) -> str:
    if not isinstance(s, str):
        return ''
    s = s.strip()
    # remove multi commas/tags e.g. 'Killycurly,,,'
    s = re.sub(r',+', ',', s)
    s = s.strip(', ')
    # normalize unicode and case
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    # replace multiple spaces and remove non-alnum except space
    s = re.sub(r'[^a-z0-9 ]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def parse_multi_link(link: str):
    """Return list of (riot_name, riot_tag) parsed from an op.gg multi link.
    Accepts formats like:
      https://op.gg/multisearch/euw?summoners=Name1%23TAG,Name2%23EUW
    """
    if not link:
        return []
    try:
        url = urlparse(link)
        qs = parse_qs(url.query)
        summ = qs.get('summoners') or qs.get('summoner') or []
        if not summ:
            # sometimes the 'summoners=' part is after '#' or in path; try a regex
            m = re.search(r'summoners=([^&#]+)', link)
            if m:
                summ = [m.group(1)]
        items = []
        for blob in summ:
            # blob may contain CSV of urlencoded identifiers
            raw = unquote(blob)
            # split by comma; entries like "Name#TAG" or just "Name"
            for tok in raw.split(','):
                t = tok.strip()
                if not t:
                    continue
                if '#' in t:
                    name, tag = t.split('#', 1)
                else:
                    name, tag = t, ''
                # clean up (remove trailing -EUW suffixes if any)
                name = re.sub(r'-EUW\s*$', '', name, flags=re.IGNORECASE)
                items.append((name.strip(), tag.strip()))
        # deduplicate preserving order
        seen = set()
        out = []
        for n, tg in items:
            key = (n.lower(), tg.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((n, tg))
        return out
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--edition', type=int, default=6)
    args = ap.parse_args()

    src = DATA_RAW / FNAME_MAP.get(args.edition, '')
    if not src.exists():
        print('Raw CSV not found:', src)
        return 2

    df = parse_opgg_adversaires_csv(src, edition=args.edition, split_alternates=True)
    if df is None or df.empty:
        print('Parsed DataFrame is empty from', src)
        return 1

    # group by team (each group has up to 5 rows with roles and summoner_raw)
    out_rows = []
    unresolved = 0
    for team, g in df.groupby('team'):
        # pick a non-empty multi link (they should be identical inside the group)
        multi = ''
        for v in g['opgg_multilink'].tolist():
            if isinstance(v, str) and v.strip():
                multi = v.strip()
                break
        tokens = parse_multi_link(multi)  # list of (name, tag)
        # build index by normalized name for matching
        idx = {normalize(n): (n, tg) for n, tg in tokens}

        for _, row in g.iterrows():
            role = str(row.get('role') or '').strip() or ''
            summ_csv = str(row.get('summoner_raw') or '').strip()
            key = normalize(summ_csv)
            riot_name, riot_tag = '', ''
            if key in idx:
                riot_name, riot_tag = idx[key]
            else:
                # attempt more forgiving match: remove spaces
                key2 = key.replace(' ', '')
                found = None
                for k, (n, tg) in idx.items():
                    if k.replace(' ', '') == key2:
                        found = (n, tg)
                        break
                if found is None:
                    # substring both ways
                    for k, (n, tg) in idx.items():
                        if key in k or k in key:
                            found = (n, tg)
                            break
                if found:
                    riot_name, riot_tag = found
                else:
                    unresolved += 1
            out_rows.append({'Equipe': team, 'Position': role, 'RiotName': riot_name or summ_csv, 'RiotTag': riot_tag})

    out_path = OUT_DIR / f'team_riot_ids_edition{args.edition}.csv'
    with out_path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['Equipe', 'Position', 'RiotName', 'RiotTag'])
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print('Wrote', out_path)
    if unresolved:
        print('Unresolved entries (kept CSV name without tag):', unresolved)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

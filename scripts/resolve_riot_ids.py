"""
Resolve RiotName#Tag (from team_riot_ids_edition{edition}.csv) to PUUID via Account-V1.
Writes: data/processed/teams_with_puuid.json

Privacy: This is an admin-only helper; PUUIDs are written to a processed JSON file for server-side use only.
"""
import argparse
import os
import time
import csv
from pathlib import Path
import json
import requests

ROOT = Path(__file__).parent.parent
OUT_JSON = ROOT / 'data' / 'processed' / 'teams_with_puuid.json'

REGIONAL_ROUTING = {
    'euw': 'europe', 'eune': 'europe', 'tr': 'europe', 'ru': 'europe',
    'na': 'americas', 'br': 'americas', 'lan': 'americas', 'las': 'americas', 'oc': 'americas',
    'kr': 'asia', 'jp': 'asia'
}


def guess_regional(tag: str) -> str:
    s = (tag or '').lower()
    if 'euw' in s or s == '' or s.isnumeric() or s.isalpha():
        return 'europe'
    return 'europe'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--edition', type=int, default=6)
    ap.add_argument('--api-key', default=os.environ.get('OCCILAN_RIOT_API_KEY'))
    args = ap.parse_args()

    if not args.api_key:
        print('No OCCILAN_RIOT_API_KEY in environment/.env')
        return 2

    csv_path = ROOT / 'data' / 'processed' / f'team_riot_ids_edition{args.edition}.csv'
    if not csv_path.exists():
        print('Input CSV not found:', csv_path)
        return 2

    teams = {}
    with csv_path.open(encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            team = row.get('Equipe') or '—'
            name = (row.get('RiotName') or '').strip()
            tag = (row.get('RiotTag') or '').strip()
            if not name:
                continue
            base = f"https://{guess_regional(tag)}.api.riotgames.com"
            url = f"{base}/riot/account/v1/accounts/by-riot-id/{requests.utils.quote(name)}/{requests.utils.quote(tag)}"
            puuid = None
            try:
                r = requests.get(url, headers={'X-Riot-Token': args.api_key}, timeout=8)
                if r.status_code == 200:
                    puuid = r.json().get('puuid')
                else:
                    print('Resolve failed', name, '#', tag, r.status_code)
            except Exception as e:
                print('Resolve exception', name, tag, e)
            teams.setdefault(team, []).append({'name': name, 'tag': tag, 'puuid': puuid, 'resolved_via': 'account-v1' if puuid else None})
            time.sleep(0.12)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(teams, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Wrote', OUT_JSON)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

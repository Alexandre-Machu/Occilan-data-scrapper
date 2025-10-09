import json
from pathlib import Path
from typing import Dict, List


def build_puuid_index(cache_matches_dir: Path) -> Dict[str, str]:
    """Scan cached full match JSONs and build a mapping summonerName -> puuid.

    Returns a dict mapping normalized summonerName -> puuid (first seen).
    """
    idx = {}
    if not cache_matches_dir.exists():
        return idx
    for p in cache_matches_dir.glob('*.json'):
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        info = data.get('info') or {}
        for part in info.get('participants', []) or []:
            puuid = part.get('puuid')
            # prefer riot display name fields
            name = part.get('riotIdGameName') or part.get('summonerName') or part.get('summonerId')
            if not name or not isinstance(name, str):
                continue
            key = name.strip()
            if key and key not in idx and puuid:
                idx[key] = puuid
    return idx


def build_team_players(edition: int, processed_players_csv: Path, cache_matches_dir: Path, out_json: Path) -> Dict[str, List[Dict]]:
    """Build a mapping team -> list of players with optional puuid when resolvable.

    - processed_players_csv: CSV produced by parse_opgg_adversaires_csv (if available)
    - cache_matches_dir: directory with full match JSONs to resolve names -> puuid
    - out_json: path to write result
    """
    teams = {}
    puuid_index = build_puuid_index(cache_matches_dir)

    # try reading processed players CSV
    try:
        import pandas as _pd
        if processed_players_csv.exists():
            df = _pd.read_csv(processed_players_csv)
            for _, r in df.iterrows():
                team = r.get('team') or '—'
                name = (r.get('summoner') or r.get('summoner_raw') or '')
                name = str(name).strip()
                if not name:
                    continue
                puuid = puuid_index.get(name)
                entry = {'name': name, 'puuid': puuid, 'resolved_via': 'cache' if puuid else None}
                teams.setdefault(team, []).append(entry)
            # persist
            try:
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps(teams, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                pass
            return teams
    except Exception:
        pass

    # fallback: try infer from cached matches (group by team not known)
    # We will not invent teams here; return empty mapping.
    return teams

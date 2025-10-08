import requests
import time
import json
from pathlib import Path
from typing import List, Dict, Any

# minimal region map for match-v5 (regional endpoints)
REGION_ROUTING = {
    'euw': 'europe',
    'eune': 'europe',
    'na': 'americas',
    'br': 'americas',
    'lan': 'americas',
    'las': 'americas',
    'kr': 'asia',
    'jp': 'asia',
}

CACHE_DIR = Path('data') / 'cache' / 'matches'
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_get(match_id: str):
    p = CACHE_DIR / f"{match_id}.json"
    try:
        if p.exists():
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None
    return None


def _cache_set(match_id: str, data: dict):
    p = CACHE_DIR / f"{match_id}.json"
    try:
        p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def get_match(match_id: str, api_key: str, region: str = 'euw', use_cache: bool = True) -> Dict[str, Any]:
    """Fetch a match by match-v5 id, using regional routing. Caches results in data/cache/matches."""
    if use_cache:
        cached = _cache_get(match_id)
        if cached:
            return cached

    region_routing = REGION_ROUTING.get(region.lower(), 'europe')
    base = f'https://{region_routing}.api.riotgames.com'
    url = f"{base}/lol/match/v5/matches/{match_id}"
    headers = {'X-Riot-Token': api_key}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    # cache
    try:
        data['_fetched_at'] = time.time()
        _cache_set(match_id, data)
    except Exception:
        pass
    return data


def _normalize_role(teamPosition: str, lane: str = '') -> str:
    """Normalize Riot teamPosition/lane to Top/Jungle/Mid/Adc/Supp.
    teamPosition values: TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY (sometimes empty)
    lane might be 'BOTTOM' and role 'DUO_CARRY' etc. We'll map common combos."""
    if not teamPosition:
        return ''
    tp = teamPosition.upper()
    if tp == 'TOP':
        return 'Top'
    if tp == 'JUNGLE':
        return 'Jungle'
    if tp in ('MIDDLE', 'MID'):
        return 'Mid'
    if tp == 'BOTTOM' or tp == 'BOT':
        # decide between Adc/Support via role/lane heuristics if provided
        # default to Adc
        if 'support' in lane.lower() or 'utility' in tp.lower():
            return 'Supp'
        return 'Adc'
    if tp in ('UTILITY', 'SUPPORT'):
        return 'Supp'
    return tp.title()


def parse_match(match_json: dict) -> Dict[str, Any]:
    """Extract participant-level stats and bans from a match JSON (match-v5 structure).

    Returns dict with keys: gameDuration (sec), participants: list of dicts with fields
    summonerName, puuid, championName, kills,deaths,assists,cs,cs_per_min,visionScore,win,role,teamId
    and bans: list of championIds (per match aggregated)
    """
    info = match_json.get('info', {})
    game_duration = info.get('gameDuration', 0)
    participants = []
    for p in info.get('participants', []):
        summ = p.get('summonerName') or p.get('summonerId') or p.get('puuid')
        champ = p.get('championName')
        kills = p.get('kills', 0)
        deaths = p.get('deaths', 0)
        assists = p.get('assists', 0)
        total_minions = p.get('totalMinionsKilled', 0)
        neutral_minions = p.get('neutralMinionsKilled', 0)
        cs = total_minions + neutral_minions
        duration_min = max(game_duration / 60.0, 1/60.0)
        cs_per_min = cs / duration_min
        vision = p.get('visionScore', 0)
        win = p.get('win', False)
        team_pos = p.get('teamPosition') or p.get('position') or ''
        lane = p.get('lane', '')
        role = _normalize_role(team_pos, lane)
        kda = (kills + assists) / (deaths if deaths > 0 else 1)
        participants.append({
            'summonerName': summ,
            'puuid': p.get('puuid'),
            'championName': champ,
            'kills': kills,
            'deaths': deaths,
            'assists': assists,
            'cs': cs,
            'cs_per_min': round(cs_per_min, 2),
            'visionScore': vision,
            'win': win,
            'role': role,
            'teamId': p.get('teamId'),
            'kda': round(kda, 2),
        })

    # bans
    bans = []
    for t in info.get('teams', []):
        for b in t.get('bans', []) or []:
            champ_id = b.get('championId')
            if champ_id is not None:
                bans.append(champ_id)

    return {'gameDuration': game_duration, 'participants': participants, 'bans': bans}


def aggregate_matches(match_jsons: List[dict]) -> Dict[str, Any]:
    """Compute aggregate statistics across a list of parsed match JSONs (raw match objects).

    Returns a dictionary containing overall stats and per-role stats as requested.
    """
    # collect parsed participants across matches
    all_parts = []
    ban_counts = {}
    for mj in match_jsons:
        parsed = parse_match(mj)
        for b in parsed.get('bans', []):
            ban_counts[b] = ban_counts.get(b, 0) + 1
        for p in parsed.get('participants', []):
            # attach match id if present
            p['_match_id'] = mj.get('metadata', {}).get('matchId') or mj.get('metadata', {}).get('gameId')
            all_parts.append(p)

    # helper aggregations
    from collections import defaultdict, Counter
    champ_counter = Counter()
    champ_wins = Counter()
    for p in all_parts:
        champ = p.get('championName')
        if champ:
            champ_counter[champ] += 1
            if p.get('win'):
                champ_wins[champ] += 1

    # most/least played champs
    most_played = champ_counter.most_common(1)[0] if champ_counter else (None, 0)
    least_played = min(champ_counter.items(), key=lambda x: x[1]) if champ_counter else (None, 0)

    def winrate(champ):
        if not champ or champ_counter.get(champ, 0) == 0:
            return 0.0
        return round(champ_wins.get(champ, 0) / champ_counter.get(champ) * 100, 1)

    # most banned champ (by champion id) -> keep id/count
    most_banned = max(ban_counts.items(), key=lambda x: x[1]) if ban_counts else (None, 0)

    # best per-stat (single match highest) — across participants
    def best_by(field):
        if not all_parts:
            return None
        best = max(all_parts, key=lambda x: x.get(field) or 0)
        return {'player': best.get('summonerName'), 'value': best.get(field), 'champion': best.get('championName'), 'role': best.get('role')}

    top_kills = best_by('kills')
    top_deaths = best_by('deaths')
    top_assists = best_by('assists')
    top_cs = best_by('cs')
    top_kda = best_by('kda')
    top_cs_min = best_by('cs_per_min')
    top_vision = best_by('visionScore')

    # per-role aggregation
    roles = ['Top', 'Jungle', 'Mid', 'Adc', 'Supp']
    per_role = {}
    for role in roles:
        parts_role = [p for p in all_parts if p.get('role') == role]
        if not parts_role:
            per_role[role] = {}
            continue
        # champion most/least played in this role
        cctr = Counter(p.get('championName') for p in parts_role if p.get('championName'))
        most = cctr.most_common(1)[0] if cctr else (None, 0)
        least = min(cctr.items(), key=lambda x: x[1]) if cctr else (None, 0)
        wins = Counter(p.get('championName') for p in parts_role if p.get('win'))
        def wr(ch):
            if not ch or cctr.get(ch,0)==0:
                return 0.0
            return round(wins.get(ch,0)/cctr.get(ch,0)*100,1)
        per_role[role] = {
            'most_played_champ': most[0],
            'most_played_count': most[1],
            'most_played_champ_winrate': wr(most[0]) if most[0] else 0.0,
            'least_played_champ': least[0] if least else None,
            'least_played_count': least[1] if least else 0,
            # top performers in this role
            'top_kills': max(parts_role, key=lambda x: x.get('kills',0))['summonerName'] if parts_role else None,
            'top_deaths': max(parts_role, key=lambda x: x.get('deaths',0))['summonerName'] if parts_role else None,
            'top_assists': max(parts_role, key=lambda x: x.get('assists',0))['summonerName'] if parts_role else None,
            'top_cs': max(parts_role, key=lambda x: x.get('cs',0))['summonerName'] if parts_role else None,
            'top_kda': max(parts_role, key=lambda x: x.get('kda',0))['summonerName'] if parts_role else None,
            'top_cs_per_min': max(parts_role, key=lambda x: x.get('cs_per_min',0))['summonerName'] if parts_role else None,
            'top_vision_per_min': max(parts_role, key=lambda x: x.get('visionScore',0))['summonerName'] if parts_role else None,
        }

    agg = {
        'most_played_champion': most_played[0],
        'most_played_count': most_played[1],
        'most_played_champion_winrate': winrate(most_played[0]) if most_played[0] else 0.0,
        'least_played_champion': least_played[0] if least_played else None,
        'least_played_count': least_played[1] if least_played else 0,
        'most_banned_champion_id': most_banned[0],
        'most_banned_count': most_banned[1],
        'top_kills': top_kills,
        'top_deaths': top_deaths,
        'top_assists': top_assists,
        'top_cs': top_cs,
        'top_kda': top_kda,
        'top_cs_per_min': top_cs_min,
        'top_vision': top_vision,
        'per_role': per_role,
        # helpful mappings for UI/visualisation
        'champion_counts': dict(champ_counter),
        'ban_counts': dict(ban_counts),
    }

    return agg


if __name__ == '__main__':
    print('Utility module; use scripts/process_matches.py')

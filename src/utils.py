import re
import csv
import pandas as pd
from pathlib import Path
from urllib.parse import unquote


def _get_row_value(row, idx):
    try:
        v = row[idx]
        return '' if pd.isna(v) else str(v).strip()
    except Exception:
        return ''


def parse_opgg_adversaires_csv(path: Path, edition: int = None, split_alternates: bool = True) -> pd.DataFrame:
    """Parse a CSV exported from the OPGG Adversaires sheet into a players DataFrame.

    This implementation reads the CSV with pandas (no header) and walks rows looking for blocks
    starting with 'Equipe', 'Lien multi', 'Role', 'Pseudo', 'Elo', 'Main champ'. It handles merged
    cells (empty cells) and distributes alternate pseudos (A / B) across duplicate appearances when
    `split_alternates=True`.
    """
    # Read CSV robustly using the stdlib csv.reader to avoid pandas tokenization errors
    raw_rows = []
    with open(path, 'r', encoding='utf-8', errors='replace', newline='') as fh:
        reader = csv.reader(fh)
        for r in reader:
            # normalize to at least 6 columns; if more, join extras into the last column
            if len(r) < 6:
                r += [''] * (6 - len(r))
            elif len(r) > 6:
                r = r[:5] + [','.join(r[5:])]
            raw_rows.append(r)

    df_csv = pd.DataFrame(raw_rows)

    rows_out = []
    i = 0
    n = len(df_csv)
    while i < n:
        first = _get_row_value(df_csv.iloc[i], 0).lower()
        if first.startswith('equipe'):
            # team name typically in column 1
            team = _get_row_value(df_csv.iloc[i], 1)
            opgg_link = ''
            roles = []
            pseudos = []
            elos = []
            mains = []
            i += 1
            # consume block until next 'Equipe' or end
            while i < n and not _get_row_value(df_csv.iloc[i], 0).lower().startswith('equipe'):
                r0 = _get_row_value(df_csv.iloc[i], 0).lower()
                if r0.startswith('lien'):
                    opgg_link = _get_row_value(df_csv.iloc[i], 1)
                elif r0.startswith('role'):
                    # roles across columns 1..
                    roles = [str(x).strip() for x in df_csv.iloc[i, 1:6].tolist()]
                elif r0.startswith('pseudo'):
                    pseudos = [str(x).strip() for x in df_csv.iloc[i, 1:6].tolist()]
                elif r0.startswith('elo'):
                    elos = [str(x).strip() for x in df_csv.iloc[i, 1:6].tolist()]
                elif r0.startswith('main'):
                    mains = [str(x).strip() for x in df_csv.iloc[i, 1:6].tolist()]
                i += 1

            # pad to length 5
            def pad(lst):
                lst = [x for x in lst]
                if len(lst) < 5:
                    lst += [''] * (5 - len(lst))
                return lst[:5]

            roles = pad(roles)
            pseudos = pad(pseudos)
            elos = pad(elos)
            mains = pad(mains)

            # handle alternates like 'A / B' appearing multiple times across roles
            final_pseudos = list(pseudos)
            if split_alternates:
                # find duplicates of the same combined string
                seen = {}
                for idx, val in enumerate(pseudos):
                    key = (val or '').strip()
                    if key == '':
                        continue
                    seen.setdefault(key, []).append(idx)

                for key, idxs in seen.items():
                    if '/' in key and len(idxs) >= 2:
                        parts = [p.strip() for p in key.split('/') if p.strip()]
                        # assign parts in order to the duplicate positions
                        for k, pos in enumerate(idxs):
                            if k < len(parts):
                                final_pseudos[pos] = parts[k]
                            else:
                                final_pseudos[pos] = parts[0]
                    elif '/' in key and len(idxs) == 1:
                        # single occurrence: keep first part (safer)
                        pos = idxs[0]
                        final_pseudos[pos] = key.split('/')[0].strip()

            # Build output rows
            for idx in range(5):
                summoner = final_pseudos[idx]
                if not summoner:
                    continue
                elo_raw = elos[idx]
                main = mains[idx]
                role = roles[idx]
                rows_out.append({
                    'edition': edition,
                    'team': team,
                    'role': role,
                    'summoner_raw': summoner,
                    'elo_raw': elo_raw,
                    'eft_elo': normalize_elo(elo_raw),
                    'main_champ_raw': main,
                    'opgg_multilink': unquote(opgg_link) if opgg_link else '',
                    'notes': ''
                })
        else:
            i += 1

    return pd.DataFrame(rows_out)


def normalize_elo(elo_raw: str) -> str:
    """Normalize various elo strings into coarse buckets: Grandmaster, Master, Diamond, Platinum, Gold, Silver, Bronze, Iron, Unknown"""
    if not isinstance(elo_raw, str) or elo_raw.strip() == '':
        return ''
    s = elo_raw.lower()
    if 'grandmaster' in s:
        return 'Grandmaster'
    if 'master' in s:
        return 'Master'
    if 'diamond' in s or s.startswith('d') and len(s) <= 3:
        return 'Diamond'
    if 'plat' in s or s.startswith('p'):
        return 'Platinum'
    if 'gold' in s:
        return 'Gold'
    if 'silver' in s:
        return 'Silver'
    if 'bronze' in s or 'b' == s:
        return 'Bronze'
    if 'iron' in s or 'fer' in s:
        return 'Iron'
    # french words
    if 'diamant' in s:
        return 'Diamond'
    if 'platine' in s:
        return 'Platinum'
    if 'or' in s:
        return 'Gold'
    if 'argent' in s:
        return 'Silver'
    if 'bronze' in s:
        return 'Bronze'
    return elo_raw


# --- DataDragon helpers -------------------------------------------------
import json
import requests
from pathlib import Path

_DD_CACHE_DIR = Path(__file__).parent.parent / 'data' / 'cache' / 'dd'
_DD_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _dd_cache_path(name: str) -> Path:
    return _DD_CACHE_DIR / name

def get_dd_latest_version(timeout: float = 5.0) -> str:
    """Return the latest DataDragon version string, using cache when possible."""
    ver_p = _dd_cache_path('version.txt')
    if ver_p.exists():
        try:
            return ver_p.read_text(encoding='utf-8').strip()
        except Exception:
            pass
    try:
        r = requests.get('https://ddragon.leagueoflegends.com/api/versions.json', timeout=timeout)
        r.raise_for_status()
        versions = r.json()
        if isinstance(versions, list) and versions:
            latest = versions[0]
            try:
                ver_p.write_text(latest, encoding='utf-8')
            except Exception:
                pass
            return latest
    except Exception:
        pass
    return ''

def load_champion_metadata(timeout: float = 5.0) -> dict:
    """Load champion metadata (mapping id -> name and name -> image url).

    Caches a local copy in data/cache/dd/champions.json to avoid repeated network calls.
    """
    cache_p = _dd_cache_path('champions.json')
    if cache_p.exists():
        try:
            return json.loads(cache_p.read_text(encoding='utf-8'))
        except Exception:
            pass

    version = get_dd_latest_version()
    if not version:
        return {}

    url = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json'
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        # store cache
        try:
            cache_p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        return data
    except Exception:
        return {}

def champ_id_to_name(champion_id: int) -> str:
    """Map a numeric champion id to the human-readable champion name using DataDragon metadata."""
    try:
        data = load_champion_metadata()
        if not data:
            return ''
        for cname, info in (data.get('data') or {}).items():
            try:
                if int(info.get('key')) == int(champion_id):
                    return info.get('id')
            except Exception:
                continue
    except Exception:
        pass
    # Fallback: try to find the name in locally cached match files (no network needed)
    try:
        from pathlib import Path
        cache_matches = Path(__file__).parent.parent / 'data' / 'cache' / 'matches'
        if cache_matches.exists():
            for p in cache_matches.glob('*.json'):
                try:
                    mj = json.loads(p.read_text(encoding='utf-8'))
                    info = mj.get('info') or {}
                    parts = info.get('participants') or []
                    for part in parts:
                        try:
                            if int(part.get('championId', 0)) == int(champion_id):
                                # championName may be present
                                return part.get('championName') or part.get('champion') or ''
                        except Exception:
                            continue
                except Exception:
                    continue
    except Exception:
        pass

    # Fallback 2: try processed aggregated files which may include participant data
    try:
        from pathlib import Path
        proc_dir = Path(__file__).parent.parent / 'data' / 'processed'
        if proc_dir.exists():
            for p in proc_dir.glob('*.json'):
                try:
                    data = json.loads(p.read_text(encoding='utf-8'))
                    matches = data.get('matches') or []
                    for m in matches:
                        parts = m.get('participants') or []
                        for part in parts:
                            try:
                                if int(part.get('championId', 0)) == int(champion_id):
                                    return part.get('championName') or part.get('champion') or ''
                            except Exception:
                                continue
                except Exception:
                    continue
    except Exception:
        pass

    return ''

def champ_name_to_icon_url(champion_name: str) -> str:
    """Return a DataDragon CDN URL for the champion square icon for a champion name and cached version."""
    if not champion_name:
        return ''
    # Normalize champion name for DataDragon file names (no spaces). Handle Wukong/MonkeyKing special-case.
    name = str(champion_name).replace(' ', '')
    if name == 'Wukong':
        name = 'MonkeyKing'

    # prefer latest cached version, otherwise fall back to a pinned version (works offline)
    version = get_dd_latest_version()
    if not version:
        # fallback version chosen to be reasonably recent; update if needed
        version = '15.11.1'

    return f'https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{name}.png'

def format_champion_display(champion_name: str) -> str:
    """Return a human-friendly champion display name.

    DataDragon uses 'MonkeyKing' for Wukong; present as 'Wukong'.
    Also split CamelCase into spaced words for readability.
    """
    if not champion_name:
        return ''
    name = str(champion_name)
    # fix DataDragon oddity and known naming exceptions
    if name == 'MonkeyKing':
        return 'Wukong'
    # Normalize common variants of Fiddlesticks (different spacing/casing)
    simple = re.sub(r"[^A-Za-z0-9]", "", name).lower()
    if simple == 'fiddlesticks':
        return 'Fiddlesticks'
    # split CamelCase (e.g., KogMaw -> Kog Maw) but keep known exceptions compact
    out = ''
    prev = ''
    for ch in name:
        if prev and ch.isupper() and (prev.islower() or prev.isdigit()):
            out += ' '
        out += ch
        prev = ch
    return out

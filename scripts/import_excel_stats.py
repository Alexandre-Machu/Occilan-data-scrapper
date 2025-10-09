"""
Import an Excel with per-team and per-player stats (as provided) and convert it to a
standard JSON the app can consume directly without any API.

Input: path to Excel (one sheet with columns [Equipe, Position, RiotName, RiotTag] and optional KPI columns)
Output: data/processed/excel_stats_edition{edition}.json

Usage:
  python scripts/import_excel_stats.py --edition 6 --excel data/OccilanStats-6.xlsx
"""
import argparse
import json
from pathlib import Path
import unicodedata
import pandas as pd

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / 'data' / 'processed'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize the core columns; allow extra stat columns to pass through.

    Handles accented headers (e.g., 'Équipe'), synonyms (e.g., 'Pseudo' -> RiotName),
    and minor variations (e.g., 'Riot Tag', 'Tagline').
    """
    def _slug(s: str) -> str:
        s = str(s or '')
        # strip accents
        s = ''.join(ch for ch in unicodedata.normalize('NFKD', s) if not unicodedata.combining(ch))
        s = s.lower().strip()
        # remove spaces, dashes and separators
        for ch in [' ', '\t', '\n', '-', '_']:
            s = s.replace(ch, '')
        return s

    # Map normalized header -> original header
    norm_to_orig = {_slug(c): c for c in df.columns}

    # Synonyms mapping to desired names
    synonyms = {
        # team
        'equipe': 'Equipe', 'equipes': 'Equipe', 'equipee': 'Equipe', 'equipe1': 'Equipe', 'team': 'Equipe', 'teams': 'Equipe', 'equipe_': 'Equipe', 'equipe#': 'Equipe',
        'equipejoueuse': 'Equipe', 'equipejoueurs': 'Equipe', 'eqp': 'Equipe', 'equipejoueur': 'Equipe', 'equipejoueures': 'Equipe', 'equipeequipe': 'Equipe', 'equipeequipee': 'Equipe', 'equipeequipes': 'Equipe', 'equipeeqp': 'Equipe', 'equipeclub': 'Equipe', 'club': 'Equipe', 'clubname': 'Equipe', 'teamname': 'Equipe', 'nomdeequipe': 'Equipe', 'nomequipe': 'Equipe', 'equipe_nom': 'Equipe', 'equipesnom': 'Equipe',
        # position / role
        'position': 'Position', 'poste': 'Position', 'role': 'Position', 'lane': 'Position', 'pos': 'Position',
        # riot name
        'riotname': 'RiotName', 'name': 'RiotName', 'player': 'RiotName', 'pseudo': 'RiotName', 'summoner': 'RiotName', 'summonername': 'RiotName', 'riotid': 'RiotName', 'gamename': 'RiotName', 'riotgamename': 'RiotName', 'riot name': 'RiotName', 'riotidgamename': 'RiotName',
        # riot tag
        'riottag': 'RiotTag', 'tag': 'RiotTag', 'tagline': 'RiotTag', 'riottagline': 'RiotTag', 'riot tag': 'RiotTag', 'hashtag': 'RiotTag',
    }

    rename = {}
    for norm, orig in norm_to_orig.items():
        if norm in synonyms:
            desired = synonyms[norm]
            rename[orig] = desired

    if rename:
        df = df.rename(columns=rename)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--edition', type=int, required=True)
    ap.add_argument('--excel', required=True, help='Path to the Excel file to import')
    args = ap.parse_args()

    xls = Path(args.excel)
    if not xls.exists():
        print('Excel not found:', xls)
        return 2

    # Try the simple flat roster format first (one sheet with Equipe/Position/RiotName[/RiotTag])
    try:
        df = pd.read_excel(xls, engine='openpyxl')
        df = normalize_columns(df)
        has_flat = all(col in df.columns for col in ['Equipe', 'Position', 'RiotName'])
    except Exception:
        df, has_flat = None, False

    if has_flat:
        if 'RiotTag' not in df.columns:
            df['RiotTag'] = ''

        # Build normalized JSON structure
        teams = {}
        for _, r in df.iterrows():
            team = str(r.get('Equipe') or '').strip() or '—'
            pos = str(r.get('Position') or '').strip()
            name = str(r.get('RiotName') or '').strip()
            tag = str(r.get('RiotTag') or '').strip()
            # Keep any extra columns as player stats payload
            extras = {k: r[k] for k in df.columns if k not in ('Equipe','Position','RiotName','RiotTag')}
            teams.setdefault(team, []).append({
                'position': pos,
                'riot_name': name,
                'riot_tag': tag,
                'stats': extras,
            })

        out = OUT_DIR / f'excel_stats_edition{args.edition}.json'
        out.write_text(json.dumps({'edition': args.edition, 'teams': teams}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Wrote', out)
        return 0

    # Fallback: parse per-team sheets with a "Statistiques des joueurs" table
    xl = pd.ExcelFile(xls, engine='openpyxl')

    def _slug(s: str) -> str:
        s = ''.join(ch for ch in unicodedata.normalize('NFKD', str(s or '')) if not unicodedata.combining(ch))
        s = s.strip().lower()
        # remove spaces and punctuation to ease matching (e.g., 'Matchs joués' -> 'matchsjoues')
        out = []
        for ch in s:
            if ch.isalnum():
                out.append(ch)
        return ''.join(out)

    def parse_team_sheet(sheet_name: str):
        df = xl.parse(sheet_name=sheet_name, header=None)
        # find header row containing 'Joueur'
        header_row_idx = None
        for i in range(min(len(df), 60)):
            row = [str(x) for x in df.iloc[i].tolist()]
            row_norm = [_slug(x) for x in row]
            if any(x == 'joueur' for x in row_norm):
                header_row_idx = i
                break
        if header_row_idx is None:
            return None, None
        headers = [str(x).strip() for x in df.iloc[header_row_idx].tolist()]
        # map header names to indices (normalize)
        idx_map = {}
        for j, h in enumerate(headers):
            h_norm = _slug(h)
            idx_map[h_norm] = j

        # Extract team summary stats from above the header
        team_stats = {}
        try:
            for i in range(max(0, header_row_idx-20), header_row_idx):
                key_raw = df.iloc[i, 0] if df.shape[1] > 0 else ''
                val_raw = df.iloc[i, 1] if df.shape[1] > 1 else ''
                key = _slug(key_raw)
                val = str(val_raw)
                if key.startswith('matchsjoues') or key.startswith('matchjoues') or key.startswith('matchesjoues'):
                    try: team_stats['matches'] = int(float(val))
                    except Exception: team_stats['matches'] = val
                elif key.startswith('victoires') or key == 'wins':
                    try: team_stats['wins'] = int(float(val))
                    except Exception: team_stats['wins'] = val
                elif key.startswith('defaites') or key.startswith('defaites') or key == 'losses':
                    try: team_stats['losses'] = int(float(val))
                    except Exception: team_stats['losses'] = val
                elif key.startswith('winrate'):
                    team_stats['winrate'] = val
                elif key.startswith('dureemoyenne') or key.startswith('dureemoy'):
                    team_stats['avg_duration'] = val
                elif key.startswith('pluscourt'):
                    team_stats['min_duration'] = val
                elif key.startswith('pluslong'):
                    team_stats['max_duration'] = val
        except Exception:
            pass

        # Expected columns
        def cidx(name_variants):
            for v in name_variants:
                vn = _slug(v)
                if vn in idx_map:
                    return idx_map[vn]
            return None

        name_i = cidx(['Joueur'])
        kda_i = cidx(['KDA'])
        kills_i = cidx(['Kills/G', 'Kills par game', 'Kills par match'])
        deaths_i = cidx(['Deaths/G', 'Morts/G', 'Deaths par game'])
        assists_i = cidx(['Assists/G', 'Assist/G'])
        cs_i = cidx(['CS/min', 'CS par min'])
        vision_i = cidx(['Vision/G', 'Vision par game'])
        champs_i = cidx(['Champions'])

        # iterate rows until blank name
        players = []
        i = header_row_idx + 1
        while i < len(df):
            try:
                name_val = df.iat[i, name_i] if name_i is not None else ''
            except Exception:
                break
            name = str(name_val).strip()
            # stop at empty or NaN
            if not name or name.lower() == 'nan':
                break
            stats = {}
            def set_stat(label, idx):
                if idx is None:
                    return
                try:
                    v = df.iat[i, idx]
                    if v is None:
                        return
                    stats[label] = v
                except Exception:
                    pass
            set_stat('KDA', kda_i)
            set_stat('Kills/G', kills_i)
            set_stat('Deaths/G', deaths_i)
            set_stat('Assists/G', assists_i)
            set_stat('CS/min', cs_i)
            set_stat('Vision/G', vision_i)
            set_stat('Champions', champs_i)
            players.append({'position': '', 'riot_name': name, 'riot_tag': '', 'stats': stats})
            i += 1

        # Guess positions by order if exactly five players listed
        if len(players) == 5:
            for pos, p in zip(['Top', 'Jungle', 'Mid', 'Adc', 'Supp'], players):
                p['position'] = pos

        return players, team_stats

    teams = {}
    team_summaries = {}
    for sheet in xl.sheet_names:
        if _slug(sheet) in ('records', 'recap', 'sommaire', 'summary'):
            continue
        players, tstats = parse_team_sheet(sheet)
        if players:
            teams[sheet] = players
            if tstats:
                team_summaries[sheet] = tstats

    if not teams:
        print('Unable to parse any team sheets from Excel. Provide a flat sheet with Equipe/Position/RiotName or ensure per-team sheets contain a "Statistiques des joueurs" table.')
        return 2

    payload = {'edition': args.edition, 'teams': teams}
    if team_summaries:
        payload['team_stats'] = team_summaries

    out = OUT_DIR / f'excel_stats_edition{args.edition}.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Parsed {len(teams)} team sheets. Wrote', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

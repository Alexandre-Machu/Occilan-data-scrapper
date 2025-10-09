import streamlit as st
import re
import pandas as pd
import sys
from pathlib import Path

# Ensure the repository root is on sys.path so imports like `from src.utils import ...`
# work when Streamlit runs this file directly (Streamlit sets sys.path[0] to the
# `src` directory which prevents `src` from being importable). Insert the parent
# of the `src` folder (the repo root) at the front of sys.path.
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from src.utils import parse_opgg_adversaires_csv, normalize_elo
import os
import time
from dotenv import load_dotenv
from src.match_stats import get_match, aggregate_matches, parse_match, get_summoner_by_puuid
from src.utils import champ_id_to_name, champ_name_to_icon_url, load_champion_metadata, format_champion_display
from pathlib import Path as _Path
import altair as alt
from urllib.parse import quote_plus
import json

DATA_DIR = Path(__file__).parent.parent / 'data' / 'raw'

st.set_page_config(page_title="OcciLan Dashboard", layout='wide')
st.title("OcciLan - Dashboard (Prototype)")

# Prevent very large raw JSON / preformatted outputs from flooding the UI.
# Make <pre> blocks scrollable and limited in height so accidental dumps don't take the whole page.
_PAGE_CSS = """
<style>
    /* limit raw pre/code blocks to a reasonable height and enable scrolling */
    pre, code {
        max-height: 220px;
        overflow: auto;
        white-space: pre-wrap;
        word-break: break-word;
    }
    /* slightly mute raw blocks so they don't overpower UI */
    pre { background: rgba(0,0,0,0.6); padding:8px; border-radius:6px; color: #e6eef6; }
</style>
"""
try:
        st.markdown(_PAGE_CSS, unsafe_allow_html=True)
except Exception:
        pass

st.sidebar.header('Configuration')
# default to edition 7 for viewers
edition = st.sidebar.selectbox('Choisir édition', [4, 5, 6, 7], index=3)
# keep the old behaviour by default (distribution of alternate pseudos)
split_alternates = True


# Matches quick tool in sidebar (paste match IDs or upload CSV)
st.sidebar.markdown('---')
st.sidebar.header('Matchs / Tournoi')
# ensure dotenv is loaded so OCCILAN_RIOT_API_KEY is available
ROOT = _Path(__file__).parent.parent
load_dotenv(ROOT / '.env')

# persistence file for entered match ids
MATCHES_FILE = ROOT / 'data' / 'tournament_matches.json'
MATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)

def _read_saved_matches():
    try:
        if MATCHES_FILE.exists():
            import json as _json
            return _json.loads(MATCHES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return {}

def _save_matches(obj):
    import json as _json
    # write atomically
    tmp = MATCHES_FILE.with_suffix('.tmp')
    tmp.write_text(_json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        tmp.replace(MATCHES_FILE)
    except Exception:
        # fallback to write
        MATCHES_FILE.write_text(_json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def safe_rerun():
    """Try to rerun the Streamlit script; if not available, show a message asking user to reload."""
    try:
        fn = getattr(st, 'experimental_rerun', None)
        if callable(fn):
            fn()
            return
    except Exception:
        pass
    # Fallback: prompt user to refresh and stop execution
    st.info('Rechargement nécessaire — merci de rafraîchir la page manuellement.')
    try:
        st.stop()
    except Exception:
        pass

# load saved matches from data/tournament_matches.json (viewer mode: read-only)
saved_matches_all = _read_saved_matches() if isinstance(_read_saved_matches(), dict) else {}
cur_key = f"edition_{edition}"
saved_matches = list(dict.fromkeys(saved_matches_all.get(cur_key, [])))

# Sidebar stats: number of saved matches and number of processed files for this edition
proc_dir = _Path(__file__).parent.parent / 'data' / 'processed'
files_for_edition = sorted([p for p in proc_dir.glob(f'match_stats_edition{edition}_*.json')], key=lambda p: p.stat().st_mtime, reverse=True)
# placeholder -- will show a single stat after we load cached matches

def resolve_player_display(player_id: str) -> str:
    """Try to resolve a potentially opaque player id (puuid) into a summonerName
    by scanning processed files and cached matches. Returns the original value if not found."""
    # robust resolver that checks multiple sources for puuid -> summonerName
    try:
        if not isinstance(player_id, str):
            return player_id

        # If it looks like a human-readable name (contains space) return as-is
        if ' ' in player_id:
            return player_id

        # If the value is already an abbreviated display (contains ellipsis), try to
        # match it against known puuid keys by prefix/suffix before giving up.
        abbrev_prefix = abbrev_suffix = None
        if '\u2026' in player_id or '...' in player_id:
            # split on either unicode ellipsis or three dots
            if '\u2026' in player_id:
                parts = player_id.split('\u2026')
            else:
                parts = player_id.split('...')
            if len(parts) == 2:
                abbrev_prefix, abbrev_suffix = parts[0], parts[1]

        # 1) module-level puuid_map (built from cached matches / processed files)
        try:
            if 'puuid_map' in globals() and isinstance(globals().get('puuid_map'), dict):
                pm = globals().get('puuid_map')
                # direct full-key match
                if player_id in pm:
                    return pm.get(player_id)
                # if we have an abbreviation, try to match by prefix/suffix
                if abbrev_prefix is not None and abbrev_suffix is not None:
                    for k, v in pm.items():
                        if k.startswith(abbrev_prefix) and k.endswith(abbrev_suffix):
                            return v
        except Exception:
            pass

        # 2) check processed files for an explicit puuid_map (fast) or participant objects
        proc_dir = _Path(__file__).parent.parent / 'data' / 'processed'
        if proc_dir.exists():
            for p in sorted(proc_dir.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    d = json.loads(p.read_text(encoding='utf-8'))
                except Exception:
                    continue

                # prefer an explicit puuid_map if present
                try:
                    pm = d.get('puuid_map') or {}
                    if isinstance(pm, dict) and pm:
                        if player_id in pm:
                            return pm.get(player_id)
                        if abbrev_prefix is not None and abbrev_suffix is not None:
                            for k, v in pm.items():
                                if k.startswith(abbrev_prefix) and k.endswith(abbrev_suffix):
                                    return v
                except Exception:
                    pass

                # fallback: iterate matches[] participants which may be dicts
                try:
                    for m in d.get('matches', []) or []:
                        parts = m.get('participants') or []
                        # if participants are dict-like
                        if parts and isinstance(parts[0], dict):
                            for part in parts:
                                try:
                                    if part.get('puuid') == player_id or part.get('player') == player_id:
                                        return part.get('summonerName') or part.get('player') or part.get('player_name') or player_id
                                except Exception:
                                    continue
                        else:
                            # participants might be simple puuid strings; try to load cached full match by id
                            mid = m.get('matchId') or m.get('gameId')
                            if mid:
                                cache_p = _Path(__file__).parent.parent / 'data' / 'cache' / 'matches' / f"{mid}.json"
                                if cache_p.exists():
                                    try:
                                        full = json.loads(cache_p.read_text(encoding='utf-8'))
                                        for fp in (full.get('info') or {}).get('participants', []):
                                            if fp.get('puuid') == player_id:
                                                    # prefer summonerName, then riotIdGameName, then summonerId
                                                    name = fp.get('summonerName') or fp.get('riotIdGameName') or fp.get('summonerId')
                                                    if isinstance(name, str):
                                                        name = name.strip()
                                                    if name:
                                                        return name
                                                    return player_id
                                    except Exception:
                                        continue
                except Exception:
                    pass

        # 3) search raw cached full matches directly
        cache_dir = _Path(__file__).parent.parent / 'data' / 'cache' / 'matches'
        if cache_dir.exists():
            for f in cache_dir.glob('*.json'):
                try:
                    mj = json.loads(f.read_text(encoding='utf-8'))
                    for p in (mj.get('info') or {}).get('participants', []):
                            pu = p.get('puuid')
                            if not pu:
                                continue
                            matched = False
                            # exact match
                            if pu == player_id:
                                matched = True
                            # abbreviated match: prefix\u2026suffix
                            elif abbrev_prefix is not None and abbrev_suffix is not None:
                                try:
                                    if pu.startswith(abbrev_prefix) and pu.endswith(abbrev_suffix):
                                        matched = True
                                except Exception:
                                    matched = False

                            if not matched:
                                continue

                            # prefer summonerName then riotIdGameName then summonerId
                            name = p.get('summonerName') or p.get('riotIdGameName') or p.get('summonerId')
                            if isinstance(name, str):
                                name = name.strip()
                            if name:
                                return name

                            # as a last resort, if we have the Riot API key, try to fetch by full puuid and cache
                            try:
                                _api_key = os.environ.get('OCCILAN_RIOT_API_KEY')
                                _region = os.environ.get('OCCILAN_RIOT_API_REGION', 'euw')
                                if _api_key:
                                    res = get_summoner_by_puuid(pu, api_key=_api_key, region=_region, use_cache=True)
                                    if res and isinstance(res, dict):
                                        disp = res.get('displayName') or (res.get('raw') or {}).get('name')
                                        if disp:
                                            return disp
                            except Exception:
                                pass
                            # if nothing, return the abbreviated input
                            return player_id
                except Exception:
                    continue
    except Exception:
        pass

    # If we couldn't resolve, try to abbreviate if it looks long/opaque (keep original short names intact)
    try:
        if isinstance(player_id, str) and len(player_id) >= 20 and ' ' not in player_id:
            # As last resort, if we have a Riot API key, try to resolve the puuid via API (and cache)
            try:
                _api_key = os.environ.get('OCCILAN_RIOT_API_KEY')
                _region = os.environ.get('OCCILAN_RIOT_API_REGION', 'euw')
                if _api_key:
                    res = get_summoner_by_puuid(player_id, api_key=_api_key, region=_region, use_cache=True)
                    if res and isinstance(res, dict):
                        # prefer displayName then raw.name
                        disp = res.get('displayName') or (res.get('raw') or {}).get('name') or (res.get('raw') or {}).get('summonerName')
                        if disp:
                            return disp
            except Exception:
                pass
            # keep the short display used elsewhere
            return f"{player_id[:6]}\u2026{player_id[-4:]}"
    except Exception:
        pass
    return player_id

def update_saved_matches_and_refresh(new_list):
    saved_matches_all[cur_key] = new_list
    _save_matches(saved_matches_all)
    st.session_state.saved_matches_all = saved_matches_all
    # try to refresh UI
    try:
        rerun = getattr(st, 'experimental_rerun', None)
        if callable(rerun):
            rerun()
            return
    except Exception:
        pass
    st.experimental_rerun if hasattr(st, 'experimental_rerun') else None

st.sidebar.markdown(f"**Matchs sauvegardés pour l'édition {edition}:** {len(saved_matches)}")

# Note: editing match lists via the web UI is disabled.
# You will manage match IDs manually in the repository under data/ (e.g. data/tournament_matches.json)

# Admin auth: show processing controls only to authenticated admin users.
_admin_secret_env = os.environ.get('OCCILAN_ADMIN_SECRET')
try:
    # If not present in the environment, try Streamlit Cloud secrets. `st.secrets`
    # is not necessarily a dict instance, so call `.get()` and fall back to
    # mapping access if needed.
    if not _admin_secret_env and hasattr(st, 'secrets'):
        try:
            _admin_secret_env = st.secrets.get('OCCILAN_ADMIN_SECRET')
        except Exception:
            try:
                _admin_secret_env = st.secrets['OCCILAN_ADMIN_SECRET']
            except Exception:
                _admin_secret_env = _admin_secret_env
except Exception:
    # best-effort: keep whatever the environment provided
    _admin_secret_env = _admin_secret_env
is_admin = bool(st.session_state.get('is_admin'))
if _admin_secret_env:
    admin_input = st.sidebar.text_input('Admin token (pour mise à jour)', type='password')
    if st.sidebar.button('Unlock admin'):
        try:
            if admin_input == _admin_secret_env:
                st.session_state['is_admin'] = True
                is_admin = True
                st.sidebar.success('Mode admin activé')
            else:
                st.session_state['is_admin'] = False
                is_admin = False
                st.sidebar.error('Token admin invalide')
        except Exception:
            st.session_state['is_admin'] = False
            is_admin = False
            st.sidebar.error('Erreur lors de la validation du token admin')
else:
    # Help the deployer understand why the admin control is not shown in cloud.
    st.sidebar.info(
        'Mode admin non configuré — la variable d\'environnement OCCILAN_ADMIN_SECRET '
        'n\'est pas définie pour cette instance. Pour activer le panneau admin, '
        'ajoutez OCCILAN_ADMIN_SECRET dans les Secrets / Environment variables de Streamlit Cloud.'
    )

# Detect changes to tournament_matches.json and optionally auto-process when admin
try:
    tm_mtime = MATCHES_FILE.stat().st_mtime
except Exception:
    tm_mtime = None
prev_tm = st.session_state.get('tournament_matches_mtime')
if prev_tm is None:
    st.session_state['tournament_matches_mtime'] = tm_mtime

if is_admin and tm_mtime is not None and prev_tm is not None and tm_mtime != prev_tm:
    # file changed since last view; notify admin and mark for processing
    st.sidebar.info('Changements détectés dans tournament_matches.json — prêt à lancer le traitement (admin)')
    st.session_state['tournament_matches_mtime'] = tm_mtime

if is_admin:
    if st.sidebar.button('Lancer le traitement maintenant'):
        # mark request; actual processing will run after helper is defined
        st.session_state['admin_request_process'] = True

# Automatic processing for viewers: aggregate cached match files listed in data/tournament_matches.json
# We will not fetch from the Riot API here; use only cached match JSONs in data/cache/matches
def _load_cached_matches_for_ids(ids):
    matches = []
    cache_dir = _Path(__file__).parent.parent / 'data' / 'cache' / 'matches'
    for mid in ids:
        p = cache_dir / f"{mid}.json"
        if p.exists():
            try:
                matches.append(json.loads(p.read_text(encoding='utf-8')))
            except Exception:
                continue
    return matches


# Optional: if environment requests auto-processing on start, fetch missing matches
try:
    _api_key = os.environ.get('OCCILAN_RIOT_API_KEY')
    _auto = os.environ.get('OCCILAN_AUTO_PROCESS', '').lower() in ('1', 'true', 'yes')
    _region = os.environ.get('OCCILAN_RIOT_API_REGION', 'euw')
except Exception:
    _api_key = None
    _auto = False
    _region = 'euw'

def _auto_process_matches_if_requested(ids, edition, api_key, region='euw'):
    """Fetch missing matches listed in ids using Riot API (get_match) and write a processed file.
    This runs only when api_key is provided and OCCILAN_AUTO_PROCESS is enabled.
    Returns True if processing occurred (and wrote a file), False otherwise.
    """
    if not api_key:
        return False
    if not ids:
        return False
    cache_dir = _Path(__file__).parent.parent / 'data' / 'cache' / 'matches'
    proc_dir = _Path(__file__).parent.parent / 'data' / 'processed'
    proc_dir.mkdir(parents=True, exist_ok=True)
    fetched_any = False
    try:
        # fetch missing into cache
        for mid in ids:
            p = cache_dir / f"{mid}.json"
            if not p.exists():
                try:
                    # display small message in sidebar
                    st.sidebar.info(f"Récupération match {mid}...")
                    m = get_match(mid, api_key=api_key, region=region)
                    fetched_any = True
                    # small polite delay
                    time.sleep(1.0)
                except Exception as e:
                    st.sidebar.warning(f"Échec récupération {mid}: {e}")
                    continue
        # rebuild cached matches list
        cached = _load_cached_matches_for_ids(ids)
        if not cached:
            return fetched_any
        agg = aggregate_matches(cached)
        # build puuid_map
        puuid_map_local = {}
        for m in cached:
            info = (m.get('info') or {})
            for p in info.get('participants', []):
                pu = p.get('puuid')
                # prefer Riot's 'summonerName', but fall back to riotIdGameName or summonerId when empty
                name = p.get('summonerName') or p.get('riotIdGameName') or p.get('summonerId')
                if isinstance(name, str):
                    name = name.strip()
                if pu and name:
                    # avoid empty strings
                    if name:
                        puuid_map_local[pu] = name
        ts = int(time.time())
        out = proc_dir / f'match_stats_edition{edition}_{ts}.json'
        payload = {'matches': [m.get('metadata', {}) for m in cached], 'agg': agg, 'puuid_map': puuid_map_local}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        st.sidebar.success(f"Traitement automatique terminé — fichier écrit: {out.name}")
        return True
    except Exception as e:
        st.sidebar.error(f"Erreur lors du traitement automatique: {e}")
        return False


# If admin clicked or file-change flagged processing, run it now (function defined above)
try:
    if st.session_state.get('admin_request_process') and _api_key:
        _auto_process_matches_if_requested(saved_matches, edition, _api_key, region=_region)
        # clear flag
        st.session_state['admin_request_process'] = False
except Exception:
    pass


# perform aggregation now using cached files (no network calls)
# If requested via env, try to auto-process (fetch missing cached matches and write processed file)
if _auto and _api_key and saved_matches:
    try:
        _auto_process_matches_if_requested(saved_matches, edition, _api_key, region=_region)
    except Exception:
        pass

cached_matches = _load_cached_matches_for_ids(saved_matches)
if not cached_matches:
    st.sidebar.markdown(f"Matchs traités (cache): 0")
    st.sidebar.info('Aucun match complet mis en cache pour cette édition — les graphiques seront limités.')
    agg_preview = {}
else:
    agg_preview = aggregate_matches(cached_matches)
    # show a single stat in the sidebar (viewer mode)
    st.sidebar.markdown(f"Matchs traités (cache): {len(cached_matches)}")

# build a quick puuid -> summonerName map from cached full matches and processed summaries
puuid_map = {}
try:
    # from full cached matches
    cache_dir = _Path(__file__).parent.parent / 'data' / 'cache' / 'matches'
    for m in cached_matches:
        info = (m.get('info') or {})
        for p in info.get('participants', []):
            pu = p.get('puuid')
            name = p.get('summonerName') or p.get('riotIdGameName') or p.get('summonerId')
            if isinstance(name, str):
                name = name.strip()
            if pu and name:
                if name:
                    puuid_map[pu] = name
    # also scan processed files for matchId -> cached match mapping
    proc_dir = _Path(__file__).parent.parent / 'data' / 'processed'
    if proc_dir.exists():
        for pf in proc_dir.glob('*.json'):
            try:
                d = json.loads(pf.read_text(encoding='utf-8'))
                for mm in d.get('matches', []) or []:
                    # if match contains participant objects
                    parts = mm.get('participants') or []
                    if parts and isinstance(parts[0], dict):
                        for part in parts:
                                for part in parts:
                                    pu = part.get('puuid') or part.get('player')
                                    # prefer explicit summonerName, then riotIdGameName, then player/player_name/summonerId
                                    name = part.get('summonerName') or part.get('riotIdGameName') or part.get('player') or part.get('player_name') or part.get('summonerId')
                                    if isinstance(name, str):
                                        name = name.strip()
                                    if pu and name:
                                        puuid_map[pu] = name
                    else:
                        # if participants are puuid strings, try loading cached match by id
                        mid = mm.get('matchId') or mm.get('gameId')
                        if mid:
                            cache_p = cache_dir / f"{mid}.json"
                            if cache_p.exists():
                                try:
                                    full = json.loads(cache_p.read_text(encoding='utf-8'))
                                    for fp in (full.get('info') or {}).get('participants', []):
                                        pu = fp.get('puuid')
                                        name = fp.get('summonerName')
                                        if pu and name:
                                            puuid_map[pu] = name
                                except Exception:
                                    pass
            except Exception:
                continue
except Exception:
    puuid_map = puuid_map


def elo_color(elo: str) -> str:
    """Return a CSS color for a normalized elo string."""
    m = (elo or '').lower()
    if 'grand' in m:
        return '#e74c3c'  # red
    if 'master' in m:
        return '#8e44ad'  # purple
    if 'diamond' in m or 'diamant' in m:
        return '#3498db'  # blue
    if 'emer' in m or 'émeraude' in m or 'emeraude' in m:
        return '#9ae6b4'  # greenish
    if 'plat' in m or 'platine' in m or 'platinum' in m:
        return '#5dade2'  # teal
    if 'gold' in m or 'or' in m:
        return '#f1c40f'  # yellow
    if 'silver' in m or 'argent' in m:
        return '#95a5a6'  # gray
    if 'bronze' in m:
        return '#cd7f32'
    if 'iron' in m or 'fer' in m:
        return '#7f8c8d'
    return '#ecf0f1'


def render_team_card(team: str, team_df: pd.DataFrame, multi_link: str):
    """Render a single team as a card with five role columns."""
    # Header with clickable team name
    if multi_link:
        team_md = f"## [{team}]({multi_link})"
    else:
        team_md = f"## {team}"
    st.markdown(team_md, unsafe_allow_html=True)

    cols = st.columns(5)
    desired = ['Top', 'Jungle', 'Mid', 'Adc', 'Supp']

    # Build a mapping role -> row
    role_map = {}
    for _, r in team_df.iterrows():
        key = (r.get('role') or '').strip()
        if key:
            role_map[key.lower()] = r

    def find_for(role_name):
        # try exact then lowercase contains
        key = role_name.lower()
        if key in role_map:
            return role_map[key]
        for k, v in role_map.items():
            if key in k:
                return v
        return None

    for i, role_name in enumerate(desired):
        with cols[i]:
            r = find_for(role_name)
            # Card box
            st.markdown(f"**{role_name}**")
            if r is None:
                st.markdown("_(vide)_")
                continue
            summ = r.get('summoner') or r.get('summoner_raw') or ''
            elo = r.get('elo_norm') or r.get('elo_raw') or ''
            champ = r.get('main_champ_raw') or ''
            # build personal op.gg link in the expected format
            def build_personal_link(summoner_raw: str) -> str:
                s = (summoner_raw or '').strip()
                # remove any #REGION or #digits tags
                s = re.sub(r"#.*$", "", s).strip()
                if s == '':
                    return ''
                # op.gg expects spaces encoded as %20, append -EUW suffix
                return f"https://op.gg/fr/lol/summoners/euw/{quote_plus(s)}-EUW"

            profile = build_personal_link(summ)
            # Elo badge
            color = elo_color(elo)
            badge = f'<div style="background:{color};padding:6px;border-radius:6px;text-align:center;font-weight:600">{elo}</div>'
            st.markdown(f"[{summ}]({profile})")
            st.markdown(badge, unsafe_allow_html=True)
            if champ:
                st.markdown(f"_Main:_ {champ}")


fname_map = {
    4: "Occi'lan #4 - OPGG Adversaires.csv",
    5: "Occi'lan #5 - OPGG Adversaires.csv",
    6: "Occi'lan #6 - OPGG Adversaires.csv",
    7: "Occi'lan #7 - OPGG Adversaires.csv",
}
path = DATA_DIR / fname_map.get(edition)
if not path.exists():
    st.info(f"Fichier pour édition {edition} introuvable: {path}. Place le CSV dans data/raw pour le charger automatiquement.")
    df = None
else:
    df = parse_opgg_adversaires_csv(path, edition=edition, split_alternates=split_alternates)

if df is not None:
    df['elo_norm'] = df['elo_raw'].apply(normalize_elo)
    df['summoner'] = df['summoner_raw']

    st.success(f"{len(df)} joueurs chargés (édition {edition})")

    # Tabs: Teams / Stats Teams / Stats Tournoi
    tab1, tab2, tab3 = st.tabs(["Teams", "Stats Teams", "Stats Tournoi"])

    with tab1:
        st.write("Clique sur le nom de l'équipe pour ouvrir le multi-OP.GG. Clique sur un joueur pour ouvrir son profil OP.GG.")
        # group by team
        grp = df.groupby(['team', 'opgg_multilink'])
        for (team_name, multi_link), group in grp:
            with st.container():
                render_team_card(team_name or '—', group, multi_link)
                st.markdown('---')

        # Exports below
        st.download_button('Exporter CSV nettoyé', df.to_csv(index=False).encode('utf-8'), file_name=f'opgg_adversaires_edition_{edition}_clean.csv')
        st.download_button('Exporter JSON', df.to_json(orient='records', force_ascii=False).encode('utf-8'), file_name=f'opgg_adversaires_edition_{edition}_clean.json')

    with tab2:
        st.subheader('Stats par rôle et Élo')
        # pivot table Elo x Role
        roles = ['Top', 'Jungle', 'Mid', 'Adc', 'Supp']
        # Order from weakest -> strongest for left-to-right axis and use normalized French names
        elo_order = ['Iron', 'Bronze', 'Silver', 'Gold', 'Platinum', 'Emeraude', 'Diamond', 'Master', 'Grandmaster']

        # Normalize role strings to a canonical set so 'Support' variants map to 'Supp'
        def _normalize_role(r):
            """Normalize role strings to canonical values.

            Handle noisy inputs exported from the OPGG CSV where extra columns
            may have been concatenated into the role cell (e.g. "Supp,,Bronze,2").
            Strategy:
            - If the value contains comma/semicolon/space separators, split into
              tokens and pick the first token that looks like a role.
            - Otherwise clean non-alphanumerics and map common variants.
            """
            try:
                if not isinstance(r, str):
                    return r
                s = r.strip()
            except Exception:
                return r

            # split on common separators and try to pick the token that matches a role
            tokens = re.split(r'[\,;\|/\s]+', s)
            tokens = [t for t in tokens if t]
            candidate = None
            for t in tokens:
                tl = t.lower()
                # direct match for known short tokens
                if tl in ('support', 'supp', 'sup', 's', 'top', 'toplane', 'jungle', 'jg', 'mid', 'middle', 'adc', 'bot', 'bottom', 'carry'):
                    candidate = tl
                    break
                # sometimes token may include punctuation; remove non-alpha for check
                tc = re.sub(r'[^a-z]', '', tl)
                if tc in ('support', 'supp', 'sup', 's', 'top', 'toplane', 'jungle', 'jg', 'mid', 'middle', 'adc', 'bot', 'bottom', 'carry'):
                    candidate = tc
                    break

            # If we still didn't find a clean candidate, check the whole cleaned
            # alpha-numeric string for role substrings (handles 'Supp,,Bronze,2').
            if candidate is None:
                try:
                    cleaned = re.sub(r'[^a-z0-9]', '', s.lower())
                except Exception:
                    cleaned = ''.join(ch for ch in s.lower() if ch.isalnum())
                # quick substring checks
                if 'supp' in cleaned:
                    candidate = 'supp'
                elif 'top' in cleaned and 'toplane' not in cleaned:
                    candidate = 'top'
                elif 'toplane' in cleaned:
                    candidate = 'toplane'
                elif 'jungle' in cleaned or 'jg' in cleaned:
                    candidate = 'jungle'
                elif 'middle' in cleaned or 'mid' in cleaned:
                    candidate = 'mid'
                elif 'adc' in cleaned or 'bot' in cleaned or 'bottom' in cleaned or 'carry' in cleaned:
                    candidate = 'adc'
                else:
                    candidate = cleaned

            # Map canonical roles
            if candidate in ('support', 'supp', 'sup', 's'):
                return 'Supp'
            if candidate in ('top', 'toplane'):
                return 'Top'
            if candidate in ('jungle', 'jg'):
                return 'Jungle'
            if candidate in ('mid', 'middle'):
                return 'Mid'
            if candidate in ('adc', 'bot', 'bottom', 'carry'):
                return 'Adc'

            # fallback: capitalize
            try:
                return candidate.capitalize() if isinstance(candidate, str) and candidate else r
            except Exception:
                return r

        # Quick heuristic: if the raw role cell contains the substring 'supp'
        # (case-insensitive), force it to the canonical 'Supp' to handle messy
        # CSV exports like 'Supp,,Bronze,2' that can confuse tokenization.
        try:
            df['role'] = df['role'].apply(lambda r: 'Supp' if isinstance(r, str) and 'supp' in r.lower() else r)
        except Exception:
            pass

        df['role'] = df['role'].apply(_normalize_role)

        pivot = df.pivot_table(index='elo_norm', columns='role', values='summoner_raw', aggfunc='count', fill_value=0)
        # ensure all roles present
        for r in roles:
            if r not in pivot.columns:
                pivot[r] = 0
        pivot = pivot[roles]
        # add Total column
        pivot['Total'] = pivot.sum(axis=1)
        # reindex to desired elo order, keep only existing elos
        existing = [e for e in elo_order if e in pivot.index]
        pivot = pivot.reindex(existing)
        existing = [e for e in elo_order if e in pivot.index]
        pivot = pivot.reindex(existing)

        # show styled table (display descending: Grandmaster on top, Iron at bottom)
        display_index = list(reversed(existing)) if existing else []
        display_pivot = pivot.reindex(display_index)

        # sanitize labels: remove underscores and present friendly names
        display_pivot2 = display_pivot.copy()
        # rename index to a nicer label
        display_pivot2.index.name = 'Élo'
        # replace underscores in column names and title-case where appropriate
        def _clean_col(c):
            try:
                if isinstance(c, str) and '_' in c:
                    return c.replace('_', ' ').title()
                if isinstance(c, str):
                    # keep short role names as-is but capitalize first letter
                    return c.capitalize()
                return c
            except Exception:
                return c
        display_pivot2 = display_pivot2.rename(columns=_clean_col)

        # Build a custom HTML table for precise styling (pill colors, spacing, bold Total)
        try:
            cols = list(display_pivot2.columns)
            html = '<div style="padding:10px;border-radius:8px;background:transparent">'
            html += f'<div style="color:#cfe7ff;font-size:18px;font-weight:600;margin-bottom:8px">Répartition par rôle - édition {edition}</div>'
            html += '<div style="overflow:auto">'
            html += '<table style="border-collapse:collapse;width:100%;font-family:Inter,Helvetica,Arial;color:#dfe6ee">'
            # header
            html += '<thead><tr style="background:#0b1220;color:#9fb0c6">'
            html += '<th style="padding:10px;text-align:left;min-width:160px">Élo</th>'
            for c in cols:
                html += f'<th style="padding:10px;text-align:center">{c}</th>'
            html += '</tr></thead><tbody>'

            # rows with striping
            for i, idx in enumerate(display_pivot2.index):
                row_bg = '#0f1113' if i % 2 == 0 else '#0b0d10'
                elo_color_hex = elo_color(idx)
                html += f'<tr style="background:{row_bg};border-top:1px solid rgba(255,255,255,0.02)">' 
                # elo pill cell
                html += f'<td style="padding:10px;min-width:160px">'
                html += f'<span style="display:inline-block;padding:8px 12px;border-radius:6px;background:{elo_color_hex};color:#071019;font-weight:700">{idx}</span>'
                html += '</td>'
                # values
                for c in cols:
                    val = display_pivot2.at[idx, c]
                    try:
                        disp = f"{int(val)}"
                    except Exception:
                        try:
                            disp = f"{float(val):.0f}"
                        except Exception:
                            disp = str(val)
                    # bold Total
                    if c == 'Total':
                        html += f'<td style="padding:10px;text-align:center;font-weight:700">{disp}</td>'
                    else:
                        html += f'<td style="padding:10px;text-align:center">{disp}</td>'
                html += '</tr>'

            # footer with totals per role
            try:
                totals_row = display_pivot2[cols].sum()
                grand_total = int(totals_row.sum()) if not totals_row.empty else 0
                html += '<tfoot>'
                html += '<tr style="background:#081018;border-top:2px solid rgba(255,255,255,0.04)">' 
                html += f'<td style="padding:10px;font-weight:700">Totaux</td>'
                for c in cols:
                    try:
                        tval = int(totals_row.get(c, 0))
                    except Exception:
                        try:
                            tval = int(float(totals_row.get(c, 0)))
                        except Exception:
                            tval = 0
                    # highlight the grand total cell (if this is the Total column)
                    if c == 'Total':
                        html += f'<td style="padding:10px;text-align:center;font-weight:800;background:rgba(255,255,255,0.03)">{tval}</td>'
                    else:
                        html += f'<td style="padding:10px;text-align:center">{tval}</td>'
                html += '</tr>'
                html += '</tfoot>'
            except Exception:
                # ignore footer if computation fails
                pass
            html += '</tbody></table></div>'
            html += '</div>'
            st.markdown(html, unsafe_allow_html=True)
        except Exception:
            # fallback to the simple styled dataframe if HTML fails
            styled = display_pivot2.style.format('{:.0f}').set_caption(f"Répartition par rôle - édition {edition}")
            st.dataframe(styled)

        # Stacked bar: roles per elo
        pivot_reset = pivot.reset_index().melt(id_vars=['elo_norm', 'Total'] if 'Total' in pivot.columns else ['elo_norm'], var_name='role', value_name='count')
        # Role color palette (consistent with team listing)
        role_colors = {
            'Adc': '#7fc8ff',
            'Jungle': '#2b6fbf',
            'Mid': '#ffb1c1',
            'Top': '#ff4c4c',
            'Supp': '#f39c12'
        }
        role_domain = [r for r in roles if r in pivot_reset['role'].unique()]
        role_range = [role_colors.get(r, '#999999') for r in role_domain]

        # Display stacked bars with Elo on the X axis from weakest -> strongest
        # use `existing` (already ordered weakest->strongest) so Iron is left and Grandmaster is right
        # Horizontal stacked bar: Elo on the Y axis (weak -> strong), counts across X
        chart = alt.Chart(pivot_reset).mark_bar().encode(
            x=alt.X('sum(count):Q', title='Count'),
            # show Grandmaster at the top: reverse the existing (weak->strong) order
            y=alt.Y('elo_norm:N', sort=list(reversed(existing)), title='Élo', axis=alt.Axis(labelAngle=0, labelAlign='right', labelFontSize=12)),
            color=alt.Color('role:N', title='Role', scale=alt.Scale(domain=role_domain, range=role_range)),
            order=alt.Order('role:N')
        ).transform_filter(alt.datum.count > 0)
        st.altair_chart(chart.properties(width=900, height=360, title='Répartition des rôles par Élo'), use_container_width=True)

        # Total per Elo colored by elo_color
        totals = pivot['Total'].reset_index()
        totals['color'] = totals['elo_norm'].apply(elo_color)
        # Elo color mapping (same as badges)
        elo_colors_map = {
            'Grandmaster': '#e74c3c',
            'Master': '#8e44ad',
            'Diamond': '#3498db',
            'Emeraude': '#9ae6b4',
            'Platinum': '#5dade2',
            'Gold': '#f1c40f',
            'Silver': '#95a5a6',
            'Bronze': '#cd7f32',
            'Iron': '#7f8c8d'
        }
        elo_domain = [e for e in existing]
        elo_range = [elo_colors_map.get(e, '#cccccc') for e in elo_domain]

        bar = alt.Chart(totals).mark_bar().encode(
            x=alt.X('elo_norm:N', sort=existing, title='Élo', axis=alt.Axis(labelAngle=0, labelAlign='center', labelBaseline='middle')),
            y=alt.Y('Total:Q', title='Total'),
            color=alt.Color('elo_norm:N', legend=None, scale=alt.Scale(domain=elo_domain, range=elo_range))
        )
        # make the bar larger and keep consistent width
        st.altair_chart(bar.properties(width=600, height=420, title='Total par Élo (nombre de joueurs)'), use_container_width=True)

        # Smooth line for Total per Elo (ordered by existing)
        totals['order'] = range(len(totals))
        line = alt.Chart(totals).mark_line(interpolate='monotone', point=True, strokeWidth=3, color='#5dade2').encode(
            x=alt.X('elo_norm:N', sort=existing, title='Élo', axis=alt.Axis(labelAngle=0, labelAlign='center', labelBaseline='middle')),
            y=alt.Y('Total:Q', title='Total')
        )
        st.altair_chart(line.properties(width=1000, height=320, title='Tendance : Total par Élo'), use_container_width=True)

        # Seeding: classement des équipes par elo moyen
        try:
            st.subheader('Seeding / Classement des équipes')
            # scoring: base mapping for tiers below Master, then LP-aware scoring for Master/Grandmaster
            base_map = {
                'Iron': 0,
                'Bronze': 1,
                'Silver': 2,
                'Gold': 3,
                'Platinum': 4,
                'Emeraude': 5,
                'Diamond': 6,
            }

            # Master starts at 8 (Master(0) -> 8) and gains +1 per 100 LP
            MASTER_BASE = 8
            # Grandmaster represents Master + 700LP -> MASTER_BASE + 7 == 15 (Grandmaster base)
            GM_OFFSET = 7

            def score_from_row(elo_norm, elo_raw):
                """Return a numeric score for a player's elo row.

                - tiers below Master use base_map
                - Master: MASTER_BASE + floor(LP / 100)
                - Grandmaster: MASTER_BASE + GM_OFFSET + floor(LP / 100) (if LP present)
                """
                try:
                    if not isinstance(elo_norm, str) or not elo_norm:
                        return None
                    en = elo_norm.strip()
                    # direct below-master mapping
                    if en in base_map:
                        return base_map[en]

                    # extract LP if present in elo_raw like 'Master (300)'
                    lp = 0
                    try:
                        if isinstance(elo_raw, str):
                            m = re.search(r"\((\d+)\)", elo_raw)
                            if m:
                                lp = int(m.group(1))
                    except Exception:
                        lp = 0

                    low = en.lower()
                    if 'master' in low and 'grand' not in low:
                        return MASTER_BASE + (lp // 100)
                    if 'grand' in low:
                        # Grandmaster baseline equals MASTER_BASE + GM_OFFSET (i.e. 15)
                        return MASTER_BASE + GM_OFFSET + (lp // 100)
                except Exception:
                    return None
                return None

            def avg_label_from_score(avg):
                """Map an average numeric score back to a coarse elo label.

                Use floor-based mapping for tiers below Master so that fractional
                averages don't round up into non-existent buckets (which previously
                produced empty labels). Master and Grandmaster are handled by
                threshold checks.
                """
                if avg is None:
                    return ''
                try:
                    v = float(avg)
                except Exception:
                    return ''
                # Grandmaster / Master thresholds
                if v >= MASTER_BASE + GM_OFFSET:
                    return 'Grandmaster'
                if v >= MASTER_BASE:
                    return 'Master'

                # revert to integer bucket for lower tiers, using floor to avoid
                # rounding up fractional averages into the next (missing) bucket
                import math
                mapping_rev = {v: k for k, v in base_map.items()}
                key = int(math.floor(v)) if v >= 0 else int(v)
                # clamp key to available mapping range
                if key not in mapping_rev:
                    # if key exceeds known buckets, pick the nearest lower known bucket
                    keys = sorted(mapping_rev.keys())
                    for kk in reversed(keys):
                        if key >= kk:
                            return mapping_rev.get(kk, '')
                    return ''
                return mapping_rev.get(key, '')

            # group by team and compute average elo score
            teams = []
            for team, g in df.groupby('team'):
                # compute numeric scores per player using elo_norm and elo_raw
                scores = []
                for _, row in g.iterrows():
                    s = score_from_row(row.get('elo_norm'), row.get('elo_raw'))
                    if s is not None:
                        scores.append(s)
                if not scores:
                    avg = None
                else:
                    avg = sum(scores) / len(scores)

                # prepare a compact sample of players with elos
                players = []
                for _, row in g.sort_values('elo_raw', ascending=False).head(6).iterrows():
                    name = row.get('summoner') or row.get('summoner_raw') or ''
                    e = row.get('elo_norm') or ''
                    players.append(f"{name} ({e})" if name else f"({e})")

                teams.append({'team': team or '—', 'players_count': len(g), 'avg_score': avg, 'sample_players': ', '.join(players)})

            import pandas as _pd
            df_seed = _pd.DataFrame(teams)
            # drop teams with no score info at the bottom
            df_with_score = df_seed[df_seed['avg_score'].notna()].copy()
            df_without = df_seed[df_seed['avg_score'].isna()].copy()

            # sort by avg_score desc, tie-breaker players_count desc
            if not df_with_score.empty:
                df_with_score = df_with_score.sort_values(['avg_score', 'players_count'], ascending=[False, False])
                df_with_score['rank'] = range(1, len(df_with_score) + 1)
                # map avg_score back to a human label (Master/Grandmaster with LP-adjusted thresholds)
                df_with_score['avg_elo_label'] = df_with_score['avg_score'].apply(lambda v: avg_label_from_score(v) if v is not None else '')

            if not df_without.empty:
                df_without = df_without.sort_values('team')
                df_without['rank'] = ['-'] * len(df_without)
                df_without['avg_elo_label'] = ['Unknown'] * len(df_without)

            final_seed = _pd.concat([df_with_score, df_without], ignore_index=True, sort=False)
            if not final_seed.empty:
                # Only show rank, team, avg_score and avg_elo_label — keep the table compact
                display_df = final_seed[['rank', 'team', 'avg_score', 'avg_elo_label']].copy()
                # ensure avg_score is nicely formatted
                def _fmt(v):
                    try:
                        return f"{float(v):.2f}"
                    except Exception:
                        return ''
                display_df['avg_score'] = display_df['avg_score'].apply(_fmt)

                # Build a compact HTML table with colored elo badges for better visuals
                try:
                    html = '<div style="background:#0f1113;padding:10px;border-radius:8px;color:#dfe6ee">'
                    html += '<table style="width:100%;border-collapse:collapse;font-family:Inter,Helvetica,Arial;color:#e6eef6">'
                    html += '<thead><tr style="text-align:left;color:#9fb0c6"><th style="padding:8px">Rank</th><th style="padding:8px">Team</th><th style="padding:8px">Avg Score</th><th style="padding:8px">Estimated Tier</th></tr></thead><tbody>'
                    for _, r in display_df.iterrows():
                        rank = r.get('rank', '')
                        team = r.get('team', '')
                        avg = r.get('avg_score', '')
                        label = r.get('avg_elo_label', '')
                        # ensure rank is rendered as an integer (no decimals/commas)
                        try:
                            if isinstance(rank, (float,)):
                                rank_disp = str(int(rank))
                            else:
                                # try cast to int for numpy types, otherwise keep as-is (e.g. '-')
                                rank_disp = str(int(rank)) if (isinstance(rank, (int,)) or (isinstance(rank, str) and rank.isdigit())) else str(rank)
                        except Exception:
                            try:
                                rank_disp = str(int(float(rank)))
                            except Exception:
                                rank_disp = str(rank)

                        # color the label using elo_color helper
                        try:
                            color = elo_color(label)
                        except Exception:
                            color = '#777777'
                        badge = f'<span style="display:inline-block;background:{color};padding:6px 10px;border-radius:999px;font-weight:700;color:#071019">{label}</span>' if label else ''
                        html += f'<tr style="border-top:1px solid #1e2933"><td style="padding:8px">{rank_disp}</td><td style="padding:8px">{team}</td><td style="padding:8px;font-weight:600">{avg}</td><td style="padding:8px">{badge}</td></tr>'
                    html += '</tbody></table>'

                    # Build a compact legend below the table similar to the provided image
                    tiers = [
                        ('Iron', 'Iron', 1),
                        ('Bronze', 'Bronze', 2),
                        ('Silver', 'Silver', 3),
                        ('Gold', 'Gold', 4),
                        ('Platin', 'Platin', 5),
                        ('Emeraude', 'Emeraude', 6),
                        ('Diamant', 'Diamant', 7),
                        ('Master', 'Master', 8),
                        ('Grandmaster', 'Grandmaster', 15),
                    ]
                    legend_html = (
                        '<div style="margin-top:12px;padding:8px;border-radius:8px;background:transparent;">'
                        '<div style="display:inline-block;background:rgba(0,0,0,0.35);padding:6px;border-radius:6px">'
                        '<table style="border-collapse:collapse;font-size:14px;font-family:Inter,Helvetica,Arial;color:#dfe6ee;">'
                    )
                    for name, key, pts in tiers:
                        try:
                            c = elo_color(key)
                        except Exception:
                            c = '#777777'
                        # each row: colored pill on left, points cell on right with spacing
                        legend_html += (
                            '<tr style="height:34px">'
                            f'<td style="padding:4px 10px;border-radius:6px 0 0 6px;background:{c};color:#071019;font-weight:700;min-width:120px">{name}</td>'
                            f'<td style="padding:4px 12px;background:rgba(0,0,0,0.45);color:#dfe6ee;border-left:1px solid rgba(255,255,255,0.04);min-width:36px;text-align:center">{pts}</td>'
                            '</tr>'
                        )
                    legend_html += '</table></div>'
                    # explanatory text below legend
                    legend_html += (
                        '<div style="margin-top:8px;color:#aab8c6;font-size:13px;max-width:360px">'
                        'Explication: la colonne <strong>Rank</strong> est un entier (1 = meilleur seed). Les valeurs numériques à droite correspondent au score de base par tier. ' 
                        'Pour Master, le score de base est 8 et s\'augmente de +1 tous les 100 LP. Grandmaster a une base 15. Ces scores sont agrégés en moyenne par équipe pour déterminer le seed.'
                        '</div>'
                    )
                    legend_html += '</div>'
                    html += legend_html
                    html += '</div>'
                    st.markdown(html, unsafe_allow_html=True)
                except Exception:
                    # fallback to plain dataframe if HTML rendering fails
                    st.dataframe(display_df)
            else:
                st.info('Aucune information d\'élo disponible pour calculer le seeding.')
        except Exception as _e:
            st.error(f"Erreur lors du calcul du seeding: {_e}")

    # Stats Tournoi: load latest processed file for this edition
    with tab3:
        proc_dir = _Path(__file__).parent.parent / 'data' / 'processed'
        files = sorted([p for p in proc_dir.glob(f'match_stats_edition{edition}_*.json')], key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            st.info('Aucun fichier de stats tournoi traité pour cette édition. Traite les matchs depuis la sidebar.')
        else:
            latest = files[0]
            # do not expose raw filename to viewers; show a brief summary instead
            num_matches = 0
            try:
                import json as _json
                num_matches = len(_json.loads(latest.read_text(encoding='utf-8')).get('matches', []))
            except Exception:
                num_matches = 0
            st.write(f'Dernier fichier traité: {num_matches} match(s)')
            try:
                import json as _json
                data = _json.loads(latest.read_text(encoding='utf-8'))
                agg = data.get('agg', {})
                # Collapsible: Aperçu agrégé tournoi (metrics)
                with st.expander('Aperçu agrégé tournoi', expanded=True):
                    # Champions played / banned in two columns
                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown('### Champions les plus joués')
                        mp = agg.get('most_played_champion')
                        if mp:
                            # show icon if possible
                            icon = champ_name_to_icon_url(mp)
                            if icon:
                                st.image(icon, width=64)
                            st.metric('Champion le plus joué', f"{format_champion_display(mp)} ({agg.get('most_played_count', 0)})")
                    with cols[1]:
                        st.markdown('### Champions les plus bannis')
                        mb_id = agg.get('most_banned_champion_id')
                        if mb_id:
                            # map id -> champion name if DataDragon available
                            mb_name = champ_id_to_name(mb_id) or str(mb_id)
                            icon = champ_name_to_icon_url(mb_name) if mb_name else ''
                            if icon:
                                st.image(icon, width=64)
                            st.metric('Champion le plus banni', f"{format_champion_display(mb_name)} ({agg.get('most_banned_count', 0)})")

                # Top players table (display player summonerName when possible)
                with st.expander('Tops par statistiques', expanded=True):
                    st.markdown('### Tops par statistiques')
                    tops = []
                    for key in ['top_kills','top_cs_per_min','top_deaths','top_kda','top_vision']:
                        v = agg.get(key)
                        if v:
                            player = v.get('player')
                            tops.append({'stat': key.replace('top_','').replace('_',' ').title(), 'player': resolve_player_display(player), 'value': v.get('value'), 'champion': v.get('champion'), 'role': v.get('role')})
                    if tops:
                        import pandas as _pd
                        df_tops = _pd.DataFrame(tops)
                        # sanitize player-like columns
                        if 'player' in df_tops.columns:
                            df_tops['player'] = df_tops['player'].apply(lambda v: resolve_player_display(v))
                        st.dataframe(df_tops)

                # Per-role breakdown
                with st.expander('Par rôle', expanded=True):
                    st.markdown('### Par rôle')
                    per_role = agg.get('per_role', {})
                    if per_role:
                        rows = []
                        for role, info in per_role.items():
                            rows.append({'role': role,
                                         'most_played': info.get('most_played_champ'),
                                         'most_played_count': info.get('most_played_count'),
                                         'top_kills': resolve_player_display(info.get('top_kills')),
                                         'top_cs_per_min': resolve_player_display(info.get('top_cs_per_min')),
                                         'top_deaths': resolve_player_display(info.get('top_deaths'))})
                        import pandas as _pd
                        df_rows = _pd.DataFrame(rows)
                        if 'top_kills' in df_rows.columns:
                            df_rows['top_kills'] = df_rows['top_kills'].apply(lambda v: resolve_player_display(v))
                        if 'top_cs_per_min' in df_rows.columns:
                            df_rows['top_cs_per_min'] = df_rows['top_cs_per_min'].apply(lambda v: resolve_player_display(v))
                        if 'top_deaths' in df_rows.columns:
                            df_rows['top_deaths'] = df_rows['top_deaths'].apply(lambda v: resolve_player_display(v))
                        st.dataframe(df_rows)

                # Charts: champion play counts and ban counts (summary)
                with st.expander('Graphiques : Champions joués & bannis (résumé)', expanded=True):
                    try:
                        st.markdown('### Champions joués (résumé)')
                        champ_counts = agg.get('champion_counts') or {}
                        if champ_counts:
                            df_champs = _pd.DataFrame([{'champion': k, 'count': int(v)} for k, v in champ_counts.items()])
                            df_champs = df_champs.sort_values('count', ascending=False).head(25)
                            df_champs['count'] = df_champs['count'].astype(int)
                            df_champs['champion'] = df_champs['champion'].apply(lambda v: format_champion_display(v))
                            small_chart = alt.Chart(df_champs).mark_bar().encode(
                                x=alt.X('count:Q', title='Nombre de parties', axis=alt.Axis(format='d')),
                                y=alt.Y('champion:N', sort='-x', title='Champion'),
                                tooltip=['champion', 'count']
                            ).properties(height=300)
                            st.altair_chart(small_chart, use_container_width=True)

                        # show top banned champions (summary)
                        ban_counts = agg.get('ban_counts') or {}
                        if ban_counts:
                            st.markdown('### Champions bannis (résumé)')
                            items = []
                            for cid, ccount in ban_counts.items():
                                name = champ_id_to_name(cid) or str(cid)
                                items.append({'champion': format_champion_display(name), 'count': int(ccount)})
                            df_bans = _pd.DataFrame(items).sort_values('count', ascending=False).head(25)
                            df_bans['count'] = df_bans['count'].astype(int)
                            ban_small = alt.Chart(df_bans).mark_bar().encode(
                                x=alt.X('count:Q', title='Nombre de bans', axis=alt.Axis(format='d')),
                                y=alt.Y('champion:N', sort='-x', title='Champion'),
                                tooltip=['champion', 'count']
                            ).properties(height=300)
                            st.altair_chart(ban_small, use_container_width=True)
                    except Exception as e:
                        st.warning('Impossible d’afficher les graphiques résumé: ' + str(e))

                # Detailed distribution (moved to bottom): show full Distribution with winrate labels
                with st.expander('Distribution : Champions joués & bannis (détaillé)', expanded=True):
                    try:
                        st.markdown('## Champions joués')
                        # reconstruct counts for champions from agg if present, otherwise from matches list
                        champ_counts = {}
                        if isinstance(agg.get('champion_counts'), dict):
                            champ_counts = agg.get('champion_counts')
                        else:
                            matches = data.get('matches', [])
                            for m in matches:
                                parts = m.get('participants') or []
                                for p in parts:
                                    cname = p.get('champion') or p.get('championName')
                                    if not cname:
                                        continue
                                    champ_counts[cname] = champ_counts.get(cname, 0) + 1

                        if champ_counts:
                            # compute per-champion win counts when full cached matches are available
                            champ_wins = {}
                            champ_games = {k: int(v) for k, v in champ_counts.items()}
                            try:
                                for mj in cached_matches:
                                    info = (mj.get('info') or {})
                                    for p in info.get('participants', []):
                                        cname = p.get('championName') or p.get('champion')
                                        if not cname:
                                            continue
                                        if p.get('win'):
                                            champ_wins[cname] = champ_wins.get(cname, 0) + 1
                            except Exception:
                                champ_wins = {}

                            rows = []
                            for cname, games in sorted(champ_games.items(), key=lambda x: x[1], reverse=True)[:25]:
                                wins = champ_wins.get(cname, 0)
                                winrate = round((wins / games * 100.0) if games else 0.0, 1)
                                rows.append({'champion': format_champion_display(cname), 'count': int(games), 'winrate': winrate})

                            df_champs = pd.DataFrame(rows)
                            chart = alt.Chart(df_champs).mark_bar().encode(
                                x=alt.X('count:Q', title='Nombre de fois joué', axis=alt.Axis(format='d')),
                                y=alt.Y('champion:N', sort='-x', title='Champion'),
                                color=alt.Color('winrate:Q', title='Winrate %', scale=alt.Scale(domain=[0,100], range=['#d73027','#f46d43','#fdae61','#a6d96a','#1a9850'], clamp=True)),
                                tooltip=[alt.Tooltip('champion:N'), alt.Tooltip('count:Q', format='d'), alt.Tooltip('winrate:Q', format='.1f')]
                            ).properties(height=480)

                            text = alt.Chart(df_champs).mark_text(align='left', dx=4, color='white').encode(
                                x=alt.X('count:Q'),
                                y=alt.Y('champion:N', sort='-x'),
                                text=alt.Text('winrate:Q', format='.1f')
                            )

                            st.altair_chart((chart + text).configure_view(strokeOpacity=0).configure_axis(labelColor='white', titleColor='white'), use_container_width=True)

                        # bans distribution in detailed view
                        bans = {}
                        if isinstance(agg.get('ban_counts'), dict):
                            bans = agg.get('ban_counts')
                        else:
                            matches = data.get('matches', [])
                            for m in matches:
                                mid = m.get('matchId') or m.get('gameId')
                                if not mid:
                                    continue
                                cache_p = Path(__file__).parent.parent / 'data' / 'cache' / 'matches' / f"{mid}.json"
                                if cache_p.exists():
                                    try:
                                        mj = _json.loads(cache_p.read_text(encoding='utf-8'))
                                        info = mj.get('info', {})
                                        for t in info.get('teams', []):
                                            for b in t.get('bans', []) or []:
                                                cid = b.get('championId')
                                                if cid:
                                                    bans[cid] = bans.get(cid, 0) + 1
                                    except Exception:
                                        continue

                        if bans:
                            rows = []
                            # recompute per-champ games/wins if not present
                            champ_games = {k: int(v) for k, v in champ_counts.items()} if champ_counts else {}
                            champ_wins = champ_wins if 'champ_wins' in locals() else {}
                            for cid, cnt in sorted(bans.items(), key=lambda x: x[1], reverse=True)[:25]:
                                name = champ_id_to_name(cid) or str(cid)
                                games = champ_games.get(name, 0)
                                wins = champ_wins.get(name, 0)
                                winrate = round((wins / games * 100.0) if games else 0.0, 1)
                                rows.append({'champion': format_champion_display(name), 'count': int(cnt), 'winrate': winrate})
                            df_bans = pd.DataFrame(rows)
                            df_bans['count'] = df_bans['count'].astype(int)
                            ban_chart = alt.Chart(df_bans).mark_bar().encode(
                                x=alt.X('count:Q', title='Nombre de bans', axis=alt.Axis(format='d')),
                                y=alt.Y('champion:N', sort='-x', title='Champion'),
                                color=alt.Color('winrate:Q', title='Winrate %', scale=alt.Scale(domain=[0,100], range=['#d73027','#f46d43','#fdae61','#a6d96a','#1a9850'], clamp=True)),
                                tooltip=[alt.Tooltip('champion:N'), alt.Tooltip('count:Q', format='d'), alt.Tooltip('winrate:Q', format='.1f')]
                            ).properties(height=420)
                            ban_text = alt.Chart(df_bans).mark_text(align='left', dx=4, color='white').encode(
                                x=alt.X('count:Q'),
                                y=alt.Y('champion:N', sort='-x'),
                                text=alt.Text('winrate:Q', format='.1f')
                            )
                            st.altair_chart((ban_chart + ban_text).configure_view(strokeOpacity=0), use_container_width=True)
                    except Exception as e:
                        st.warning('Impossible d’afficher la distribution détaillée: ' + str(e))
            except Exception as e:
                st.error('Impossible de lire le fichier traité: ' + str(e))
            # (download button will be placed below the full champion table)

            # Rebuild and render the full champion table (the detailed rows table) here, between the download button and the distribution
            try:
                champ_rows = []
                if cached_matches:
                    per_champ = {}
                    for mj in cached_matches:
                        parsed = parse_match(mj)
                        team_kills = {}
                        for p in parsed.get('participants', []):
                            team_kills[p.get('teamId')] = team_kills.get(p.get('teamId'), 0) + (p.get('kills') or 0)
                        for p in parsed.get('participants', []):
                            cname = p.get('championName') or p.get('champion')
                            if not cname:
                                continue
                            if cname not in per_champ:
                                per_champ[cname] = {'games':0,'wins':0,'kda_sum':0.0,'kp_sum':0.0}
                            per_champ[cname]['games'] += 1
                            if p.get('win'):
                                per_champ[cname]['wins'] += 1
                            per_champ[cname]['kda_sum'] += (p.get('kda') or 0.0)
                            tk = team_kills.get(p.get('teamId'), 0)
                            kp = 0.0
                            if tk > 0:
                                kp = ( (p.get('kills') or 0) + (p.get('assists') or 0) ) / tk * 100.0
                            per_champ[cname]['kp_sum'] += kp
                    for cname, info in per_champ.items():
                        games = info['games']
                        winrate = round(info['wins']/games*100.0,1) if games else 0.0
                        avg_kda = round(info['kda_sum']/games,2) if games else 0.0
                        avg_kp = round(info['kp_sum']/games,1) if games else 0.0
                        champ_rows.append({'champion': cname, 'games': games, 'winrate': winrate, 'kda': avg_kda, 'kp': avg_kp})
                    champ_rows = sorted(champ_rows, key=lambda x: x['games'], reverse=True)

                if champ_rows:
                    st.markdown('### Tableau complet — Champions (détails)')
                    html = '<div style="background:#0f1113;padding:10px;border-radius:8px;color:#dfe6ee">'
                    html += '<table style="width:100%;border-collapse:collapse;font-family:Inter,Helvetica,Arial;">'
                    html += '<thead><tr style="text-align:left;color:#9fb0c6"><th>Champion</th><th>Games</th><th>WR</th><th>KDA</th><th>KP</th></tr></thead><tbody>'
                    for r in champ_rows:
                        disp = format_champion_display(r['champion'])
                        icon = champ_name_to_icon_url(r['champion'])
                        icon_html = f'<img src="{icon}" width="28" height="28" style="vertical-align:middle;border-radius:4px;margin-right:8px">' if icon else ''
                        html += f'<tr style="border-top:1px solid #1e2933;padding:6px">'
                        html += f'<td style="padding:8px">{icon_html}<span style="vertical-align:middle">{disp}</span></td>'
                        html += f"<td style=\"padding:8px\">{r['games']}</td>"
                        wr_color = '#4CAF50' if r['winrate']>=50 else '#F44336'
                        html += f"<td style=\"padding:8px;color:{wr_color}\">{r['winrate']}%</td>"
                        html += f"<td style=\"padding:8px;color:#8e44ad\">{r['kda']}</td>"
                        kp_color = '#4CAF50' if r['kp']>=50 else '#F44336'
                        html += f"<td style=\"padding:8px;color:{kp_color}\">{r['kp']}%</td>"
                        html += '</tr>'
                    html += '</tbody></table></div>'
                    st.markdown(html, unsafe_allow_html=True)
                    # Download button placed immediately after the full champion table
                    st.download_button('Télécharger JSON tournoi (brut)', latest.read_bytes(), file_name=latest.name, mime='application/json')
            except Exception:
                pass

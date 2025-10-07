import streamlit as st
import re
import pandas as pd
from pathlib import Path
from src.utils import parse_opgg_adversaires_csv, normalize_elo
import altair as alt
from urllib.parse import quote_plus

DATA_DIR = Path(__file__).parent.parent / 'data' / 'raw'

st.set_page_config(page_title="OcciLan Dashboard", layout='wide')
st.title("OcciLan - Dashboard (Prototype)")

st.sidebar.header('Configuration')
edition = st.sidebar.selectbox('Choisir édition', [4, 5, 6], index=0)
split_alternates = st.sidebar.checkbox('Distribuer automatiquement les pseudos alternatifs (A / B)', value=True)


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
    if 'plat' in m or 'platine' in m:
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


if st.sidebar.button('Charger les données'):
    fname_map = {
        4: "Occi'lan #4 - OPGG Adversaires.csv",
        5: "Occi'lan #5 - OPGG Adversaires.csv",
        6: "Occi'lan #6 - OPGG Adversaires.csv",
    }
    path = DATA_DIR / fname_map[edition]
    if not path.exists():
        st.error(f"Fichier pour édition {edition} introuvable: {path}")
    else:
        df = parse_opgg_adversaires_csv(path, edition=edition, split_alternates=split_alternates)
        df['elo_norm'] = df['elo_raw'].apply(normalize_elo)
        df['summoner'] = df['summoner_raw']

        st.success(f"{len(df)} joueurs chargés (édition {edition})")

        # Tabs: Teams / Stats
        tab1, tab2 = st.tabs(["Teams", "Stats"])

        with tab1:
            st.write("Clique sur le nom de l'équipe pour ouvrir la multi-OP.GG. Clique sur un joueur pour ouvrir son profil OP.GG.")
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
            elo_order = ['Grandmaster', 'Master', 'Diamond', 'Emeraude', 'Platine', 'Gold', 'Silver', 'Bronze', 'Iron']
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

            # show styled table
            styled = pivot.style.format('{:.0f}').set_caption(f"Répartition par rôle - édition {edition}")
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

            chart = alt.Chart(pivot_reset).mark_bar().encode(
                x=alt.X('sum(count):Q', title='Count'),
                y=alt.Y('elo_norm:N', sort=existing, title='Élo'),
                color=alt.Color('role:N', title='Role', scale=alt.Scale(domain=role_domain, range=role_range)),
                order=alt.Order('role:N')
            ).transform_filter(alt.datum.count > 0)
            st.altair_chart(chart.properties(width=800, height=340), use_container_width=True)

            # Total per Elo colored by elo_color
            totals = pivot['Total'].reset_index()
            totals['color'] = totals['elo_norm'].apply(elo_color)
            # Elo color mapping (same as badges)
            elo_colors_map = {
                'Grandmaster': '#e74c3c',
                'Master': '#8e44ad',
                'Diamond': '#3498db',
                'Emeraude': '#9ae6b4',
                'Platine': '#5dade2',
                'Gold': '#f1c40f',
                'Silver': '#95a5a6',
                'Bronze': '#cd7f32',
                'Iron': '#7f8c8d'
            }
            elo_domain = [e for e in existing]
            elo_range = [elo_colors_map.get(e, '#cccccc') for e in elo_domain]

            bar = alt.Chart(totals).mark_bar().encode(
                x=alt.X('Total:Q', title='Total'),
                y=alt.Y('elo_norm:N', sort=existing, title='Élo'),
                color=alt.Color('elo_norm:N', legend=None, scale=alt.Scale(domain=elo_domain, range=elo_range))
            )
            # make the bar larger and keep consistent width
            st.altair_chart(bar.properties(width=600, height=420), use_container_width=True)

            # Smooth line for Total per Elo (ordered by existing)
            totals['order'] = range(len(totals))
            line = alt.Chart(totals).mark_line(interpolate='monotone', point=True, strokeWidth=3, color='#5dade2').encode(
                x=alt.X('elo_norm:N', sort=existing, title='Élo'),
                y=alt.Y('Total:Q', title='Total')
            )
            st.altair_chart(line.properties(width=1000, height=320), use_container_width=True)

else:
    st.info('Clique sur "Charger les données" pour importer l\'édition 4/5/6 depuis les CSV fournis dans `data/raw`.')

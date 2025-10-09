"""
Streamlit-friendly helper to render a player's aggregated stats and recent match history as HTML.
Adapted from SC-Esport-Stats player display components; simplified and safe (no puuid leakage).

Provides:
- render_player_summary_html(player_name, matches) -> HTML string
- get_player_matches(player_name, cached_matches) -> list of participant dicts

`matches` is a list of parsed match JSON objects (same shape as src.match_stats.parse_match output)

This module is intentionally minimal so it can be called from `src/app.py`.
"""

from typing import List, Dict, Any
import math
import html


def get_player_matches(player_name: str, cached_match_objs: List[Dict]) -> List[Dict]:
    """Return list of participant dicts for that player across cached match objects.
    We assume cached_match_objs are raw match JSONs (match-v5 structure) and will parse participants
    similarly to src.match_stats.parse_match but keeping minimal fields.
    """
    parts = []
    for mj in cached_match_objs:
        info = mj.get('info', {})
        game_duration = info.get('gameDuration', 0)
        for p in info.get('participants', []) or []:
            raw_name = p.get('riotIdGameName') or p.get('summonerName') or p.get('summonerId')
            name = raw_name.strip() if isinstance(raw_name, str) else raw_name
            if name == player_name:
                # minimal projection
                total_minions = p.get('totalMinionsKilled', 0)
                neutral = p.get('neutralMinionsKilled', 0)
                cs = total_minions + neutral
                duration_min = max(game_duration / 60.0, 1/60.0)
                cs_per_min = round(cs / duration_min, 2)
                k = p.get('kills', 0); d = p.get('deaths', 0); a = p.get('assists', 0)
                kda = round((k + a) / (d if d>0 else 1), 2)
                champ = p.get('championName')
                vision = p.get('visionScore', 0)
                win = p.get('win', False)
                parts.append({
                    'match_id': mj.get('metadata', {}).get('matchId') or mj.get('metadata', {}).get('gameId'),
                    'champion': champ,
                    'kills': k, 'deaths': d, 'assists': a, 'kda': kda,
                    'cs': cs, 'cs_per_min': cs_per_min,
                    'vision': vision, 'win': win,
                    'role': p.get('teamPosition') or p.get('position') or p.get('lane')
                })
    # sort by most recent if metadata contains timestamp (not always present)
    return parts


def render_player_summary_html(player_name: str, player_matches: List[Dict]) -> str:
    """Return HTML summary for a player (safe for st.markdown(..., unsafe_allow_html=True))."""
    n = len(player_matches)
    if n == 0:
        return f"<div><strong>{html.escape(player_name)}</strong>: pas de matchs locaux trouvés.</div>"

    total_k = sum(m['kills'] for m in player_matches)
    total_d = sum(m['deaths'] for m in player_matches)
    total_a = sum(m['assists'] for m in player_matches)
    avg_kda = round((total_k + total_a) / (total_d if total_d>0 else 1), 2)
    avg_cs = round(sum(m['cs'] for m in player_matches) / n, 1)
    avg_cs_min = round(sum(m['cs_per_min'] for m in player_matches) / n, 2)
    avg_vision = round(sum(m['vision'] for m in player_matches) / n, 1)
    winrate = round(sum(1 for m in player_matches if m.get('win')) / n * 100, 1)

    # champions breakdown
    champ_counts = {}
    for m in player_matches:
        c = m.get('champion') or '—'
        champ_counts[c] = champ_counts.get(c, 0) + 1
    top_champs = sorted(champ_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    # build HTML
    html_lines = [f"<div class=\"player-summary\">",
                  f"<h3>{html.escape(player_name)}</h3>",
                  f"<div><strong>Matchs trouvés:</strong> {n} — <strong>Winrate:</strong> {winrate}%</div>",
                  f"<div><strong>KDA moyen:</strong> {avg_kda} — <strong>CS/moy:</strong> {avg_cs} ({avg_cs_min}/min) — <strong>Vision:</strong> {avg_vision}</div>",
                  "<div style='margin-top:8px'><strong>Champions:</strong></div>",
                  "<ul>"]
    for c, cnt in top_champs:
        html_lines.append(f"<li>{html.escape(c)} — {cnt} partie(s)</li>")
    html_lines.append("</ul>")

    # small recent matches table (last 8)
    html_lines.append("<div style='margin-top:8px'><strong>Récents:</strong></div>")
    html_lines.append("<table class='player-matches' style='border-collapse:collapse;width:100%'>")
    html_lines.append("<thead><tr><th>Champ</th><th>K/D/A</th><th>CS</th><th>Vision</th><th>Win</th></tr></thead>")
    html_lines.append("<tbody>")
    for m in player_matches[:8]:
        win_mark = '✅' if m.get('win') else '❌'
        html_lines.append(f"<tr><td>{html.escape(str(m.get('champion') or '—'))}</td><td>{m['kills']}/{m['deaths']}/{m['assists']}</td><td>{m['cs']} ({m['cs_per_min']}/m)</td><td>{m['vision']}</td><td>{win_mark}</td></tr>")
    html_lines.append("</tbody></table>")

    html_lines.append("</div>")
    return '\n'.join(html_lines)

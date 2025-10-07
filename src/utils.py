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

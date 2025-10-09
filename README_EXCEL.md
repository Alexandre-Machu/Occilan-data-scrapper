Excel import (offline)

1) Place your Excel in `data/` (e.g. `data/OccilanStats-6.xlsx`).
2) Install dependencies (openpyxl is already listed in requirements.txt).
3) Import:
   - python scripts/import_excel_stats.py --edition 6 --excel data/OccilanStats-6.xlsx
4) The script writes `data/processed/excel_stats_edition6.json`.
5) (Optional) Wire to the app or view it with a quick Python snippet.

Columns expected (case-insensitive):
- Equipe (or Team)
- Position (or Role)
- RiotName (or Name)
- RiotTag (optional)
Any extra columns are kept in the `stats` map per player.

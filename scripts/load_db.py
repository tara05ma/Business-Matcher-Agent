"""Copy the Kings County register CSV into SQLite, unchanged.

Usage:  uv run python scripts/load_db.py
"""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "kings_register.csv"
DB_PATH = ROOT / "data" / "register.db"

# Read everything as text so IDs and ZIPs keep their exact form.
df = pd.read_csv(CSV_PATH, dtype=str)

DB_PATH.unlink(missing_ok=True)  # start fresh so the script can be re-run
with sqlite3.connect(DB_PATH) as con:
    df.to_sql("companies", con, index=False)

print(f"Loaded {len(df):,} rows into {DB_PATH.name}")
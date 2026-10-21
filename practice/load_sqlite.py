"""
Build a SQLite database from the shipped CSVs, so you can practise the SQL in
practice/questions.md without installing a database server.

    python practice/load_sqlite.py                 # writes practice/hospital.db
    python practice/load_sqlite.py --out my.db

Then open it with any SQLite client, for example:

    sqlite3 practice/hospital.db
    python -c "import sqlite3; print(sqlite3.connect('practice/hospital.db').execute('select count(*) from admissions').fetchone())"

The CSVs are the dataset in app/data/ (17 tables plus icd10_lookup). Dates are stored as
text in ISO format ('2026-01-31 14:05:00'), which SQLite's date functions read directly.
The tables carry no primary or foreign key declarations (SQLite loads them as plain tables);
the relationships are documented in docs/SCHEMA.md. Indexes are added on the ID columns so
joins are fast.
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "app" / "data"

TABLES = [
    "departments", "payers", "procedures", "patients", "doctors", "nurses",
    "employees", "rooms", "admissions", "triage", "diagnoses",
    "patient_procedures", "medications", "medical_tests", "staff_shifts",
    "billing", "billing_line_items", "icd10_lookup",
]


def build(out: Path) -> dict:
    """Create (or replace) the database at `out`; return {table: row count}."""
    if out.exists():
        out.unlink()
    counts = {}
    with sqlite3.connect(out) as con:
        for table in TABLES:
            df = pd.read_csv(DATA / f"{table}.csv")
            df.to_sql(table, con, index=False)
            counts[table] = len(df)
            for col in df.columns:
                if col.endswith("_id") or col == "icd10_code":
                    con.execute(f'CREATE INDEX idx_{table}_{col} ON "{table}" ("{col}")')
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "practice" / "hospital.db"), help="database file to create")
    args = ap.parse_args()
    counts = build(Path(args.out))
    print(f"Wrote {args.out}: {len(counts)} tables, {sum(counts.values()):,} rows")
    for table, n in counts.items():
        print(f"  {table:<22}{n:>9,}")


if __name__ == "__main__":
    main()

"""
export_to_csv.py
=================
Exports every hospital_db table (plus an ICD-10 code -> name lookup built
from icd10_diagnoses.py) to CSV. Used to produce the self-contained data
bundle that ships with the dashboard in app/data/, so the dashboard never
needs a live database connection.

Usage:
    python src/export_to_csv.py
    python src/export_to_csv.py --out app/data --host localhost --db hospital_db
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from icd10_diagnoses import get_diagnoses_df  # noqa: E402

TABLES = [
    "departments", "payers", "procedures", "patients", "doctors", "nurses",
    "employees", "rooms", "admissions", "triage", "diagnoses",
    "patient_procedures", "medications", "medical_tests", "staff_shifts",
    "billing", "billing_line_items",
]


def export(out_dir: Path, host: str, user: str, password: str, port: int, db: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}")

    total_rows = 0
    with engine.connect() as conn:
        for table in TABLES:
            df = pd.read_sql(f"SELECT * FROM `{table}`", conn)
            df.to_csv(out_dir / f"{table}.csv", index=False)
            total_rows += len(df)
            print(f"  {table:<22} {len(df):>7,} rows -> {out_dir / f'{table}.csv'}")

    icd10 = get_diagnoses_df()[["icd10_code", "diagnosis_name"]]
    icd10.to_csv(out_dir / "icd10_lookup.csv", index=False)
    print(f"  {'icd10_lookup':<22} {len(icd10):>7,} rows -> {out_dir / 'icd10_lookup.csv'}")

    print(f"\nTotal: {total_rows:,} rows across {len(TABLES)} tables + icd10_lookup")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export hospital_db to CSV for the dashboard.")
    parser.add_argument("--out", default="app/data", help="Output directory (default: app/data)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--db", default="hospital_db")
    args = parser.parse_args()

    export(Path(args.out), args.host, args.user, args.password, args.port, args.db)

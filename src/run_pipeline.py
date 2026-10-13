"""
run_pipeline.py
===============
The whole pipeline in one command:

    generate -> validate (before) -> repair -> validate (after) -> export

    python src/run_pipeline.py --size large
    python src/run_pipeline.py --size small --no-export \
        --report-path docs/validation_runs/small.csv

Writes a before/after validation report (one row per check) that the
dashboard's Data Quality page reads, plus a small metadata file next to it.
Needs a running MySQL/MariaDB with data/hospital_db.sql loaded; the connection
string comes from HOSPITAL_DB_URL (default: root, no password, localhost).

WARNING: this truncates and regenerates every table in the target database.
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "src"))

import hospital_generator as gen      # noqa: E402
import validate_repair as vr          # noqa: E402
from export_to_csv import export      # noqa: E402
from sqlalchemy import create_engine  # noqa: E402


SUMMARY_FIELDS = ["size", "admissions", "checks", "violations_before_repair",
                  "violations_after_repair", "generated_at_utc"]
SIZE_ORDER = ["small", "medium", "large"]


def update_runs_summary(summary_path: Path, meta: dict) -> None:
    """Upsert this run's one-line result into the per-scale summary the dashboard shows."""
    rows = {}
    if summary_path.exists():
        with open(summary_path, newline="", encoding="utf-8") as f:
            rows = {r["size"]: r for r in csv.DictReader(f)}
    rows[meta["size"]] = {k: meta[k] for k in SUMMARY_FIELDS}
    ordered = sorted(rows.values(), key=lambda r: SIZE_ORDER.index(r["size"]))
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        w.writeheader()
        w.writerows(ordered)


def run(size: str, export_dir: Path, report_path: Path, do_export: bool,
        summary_path: Path = None) -> dict:
    gen.main(size)

    engine = create_engine(vr.DB_URL, echo=False)
    with engine.connect() as conn:
        before = vr.validate_all(conn)
    print("\n--- Pre-repair validation ---")
    vr.print_report(before)

    with engine.connect() as conn:
        vr.repair_all(conn)

    with engine.connect() as conn:
        after = vr.validate_all(conn)
    print("\n--- Post-repair validation ---")
    vr.print_report(after)

    before_rows = {(r["group"], r["rule"]): r for r in vr.report_to_rows(before)}
    out_rows = []
    for r in vr.report_to_rows(after):
        b = before_rows[(r["group"], r["rule"])]
        out_rows.append({
            "group": r["group"], "group_label": r["group_label"], "rule": r["rule"],
            "before_repair": b["count"], "after_repair": r["count"],
        })

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["group", "group_label", "rule", "before_repair", "after_repair"])
        w.writeheader()
        w.writerows(out_rows)

    meta = {
        "size": size,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "checks": len(out_rows),
        "violations_before_repair": sum(r["before_repair"] for r in out_rows),
        "violations_after_repair": sum(r["after_repair"] for r in out_rows),
        "admissions": gen.HOSPITAL_SIZES[size]["admissions"],
    }
    with open(report_path.with_name(report_path.stem + "_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"\nWrote {report_path} ({len(out_rows)} checks)")

    if summary_path:
        update_runs_summary(summary_path, meta)
        print(f"Updated {summary_path}")

    if do_export:
        print("\n--- Exporting CSVs ---")
        export(export_dir, url=vr.DB_URL)
    return meta


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Generate, validate, repair and export the hospital database.")
    ap.add_argument("--size", default="large", choices=list(gen.HOSPITAL_SIZES))
    ap.add_argument("--out", default=str(ROOT / "app" / "data"), help="CSV export directory")
    ap.add_argument("--report-path", default=str(ROOT / "app" / "data" / "validation_report.csv"))
    ap.add_argument("--runs-summary", default=str(ROOT / "app" / "data" / "validation_runs.csv"),
                    help="per-scale results table read by the dashboard")
    ap.add_argument("--no-export", action="store_true", help="skip the CSV export")
    args = ap.parse_args()
    run(args.size, Path(args.out), Path(args.report_path), not args.no_export, Path(args.runs_summary))

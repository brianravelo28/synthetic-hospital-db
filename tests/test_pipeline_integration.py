"""
End-to-end: generate -> validate -> repair -> export against a real database.

This REGENERATES every table in the target database, so it only runs when
HOSPITAL_DB_URL is set explicitly (CI sets it; locally point it at a scratch
database, never the one behind your dashboard).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("HOSPITAL_DB_URL"), reason="HOSPITAL_DB_URL not set"),
]

ROOT = Path(__file__).resolve().parent.parent
AS_OF = "2026-10-13 12:00:00"      # pinned reference date for the reproducibility tests
TABLES = ["departments", "payers", "procedures", "patients", "doctors", "nurses", "employees",
          "rooms", "admissions", "triage", "diagnoses", "patient_procedures", "medications",
          "medical_tests", "staff_shifts", "billing", "billing_line_items"]


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    import run_pipeline
    out = tmp_path_factory.mktemp("run")
    meta = run_pipeline.run("small", out / "csv", out / "report.csv", do_export=True,
                            summary_path=out / "runs.csv")
    import pandas as pd
    return {"meta": meta, "out": out, "report": pd.read_csv(out / "report.csv")}


def test_all_57_checks_ran(result):
    assert result["meta"]["checks"] == len(result["report"]) == 57


def test_generator_prevents_admission_type_and_financial_violations(result):
    """Groups 3 and 6 used to be fixed only by repair; the generator now avoids them."""
    r = result["report"]
    for group in ("group3_admission_type", "group6_financial"):
        assert r.loc[r["group"] == group, "before_repair"].sum() == 0, group


def test_treatments_fit_the_patient_and_diagnosis_before_any_repair(result):
    """Group 8 has no repair, so the generator alone must keep it at zero."""
    r = result["report"]
    assert r.loc[r["group"] == "group8_clinical", "before_repair"].sum() == 0


def test_repair_leaves_only_room_scarcity(result):
    r = result["report"]
    leftover = r[r["after_repair"] > 0]
    assert set(leftover["rule"]) <= {"condition_room_mismatch"}


def test_realism_checks_pass_on_fresh_data(result):
    r = result["report"]
    assert r.loc[r["group"] == "group7_realism", "after_repair"].sum() == 0


def test_export_wrote_every_table_and_the_summary(result):
    csvs = {p.name for p in (result["out"] / "csv").glob("*.csv")}
    assert len(csvs) == 18 and "icd10_lookup.csv" in csvs and "admissions.csv" in csvs
    assert (result["out"] / "runs.csv").read_text(encoding="utf-8").startswith("size,")


# ── reproducibility ───────────────────────────────────────────────────────
# Each run is a fresh process with the same pinned reference date, because
# the seeds are applied once at import.

def _env():
    return {**os.environ, "HOSPITAL_AS_OF": AS_OF, "PYTHONIOENCODING": "utf-8"}


def _run_pipeline(tmp_path, tag):
    subprocess.run(
        [sys.executable, str(ROOT / "src" / "run_pipeline.py"), "--size", "small", "--no-export",
         "--report-path", str(tmp_path / f"{tag}.csv"), "--runs-summary", str(tmp_path / f"{tag}_runs.csv")],
        check=True, env=_env(), capture_output=True, cwd=ROOT,
    )


def _table_hashes():
    import pandas as pd
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ["HOSPITAL_DB_URL"])
    out = {}
    with engine.connect() as conn:
        for t in TABLES:
            df = pd.read_sql(text(f"SELECT * FROM {t} ORDER BY 1"), conn)
            out[t] = (len(df), int(pd.util.hash_pandas_object(df.astype(str), index=False).sum()))
    return out


def test_same_reference_date_gives_identical_tables(tmp_path):
    _run_pipeline(tmp_path, "a")
    first = _table_hashes()
    _run_pipeline(tmp_path, "b")
    second = _table_hashes()
    assert first == second


def test_repair_is_idempotent(tmp_path):
    """Running repair again on already-repaired data must change nothing."""
    _run_pipeline(tmp_path, "c")
    before = _table_hashes()
    subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path[:0]=['data','src']; import validate_repair as vr; "
         "from sqlalchemy import create_engine; "
         "e=create_engine(vr.DB_URL); c=e.connect(); vr.repair_all(c)"],
        check=True, env=_env(), capture_output=True, cwd=ROOT,
    )
    assert _table_hashes() == before

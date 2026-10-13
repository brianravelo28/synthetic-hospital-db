"""
End-to-end: generate -> validate -> repair -> export against a real database.

This REGENERATES every table in the target database, so it only runs when
HOSPITAL_DB_URL is set explicitly (CI sets it; locally point it at a scratch
database, never the one behind your dashboard).
"""

import os
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("HOSPITAL_DB_URL"), reason="HOSPITAL_DB_URL not set"),
]


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    import run_pipeline
    out = tmp_path_factory.mktemp("run")
    meta = run_pipeline.run("small", out / "csv", out / "report.csv", do_export=True,
                            summary_path=out / "runs.csv")
    import pandas as pd
    return {"meta": meta, "out": out, "report": pd.read_csv(out / "report.csv")}


def test_all_51_checks_ran(result):
    assert result["meta"]["checks"] == len(result["report"]) == 51


def test_generator_prevents_admission_type_and_financial_violations(result):
    """Groups 3 and 6 used to be fixed only by repair; the generator now avoids them."""
    r = result["report"]
    for group in ("group3_admission_type", "group6_financial"):
        assert r.loc[r["group"] == group, "before_repair"].sum() == 0, group


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
